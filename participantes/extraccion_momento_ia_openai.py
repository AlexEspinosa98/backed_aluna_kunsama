"""Lee un Momento ya diligenciado fuera de la web (PDF o Word) y lo transcribe llamando a OpenAI —
mismo mecanismo que instrumentos.extraccion_ia_openai (ver ese módulo para el razonamiento completo
de texto-vs-visión y de por qué la transcripción se pide por lotes), portado acá porque este
contenido vive en el modelo clásico `jornadas.Momento`/`jornadas.Pregunta`, no en el módulo
`instrumentos`.

El esquema que se le manda a la IA lleva, por pregunta, su id real, su tipo, sus opciones y —en
las de tabla— sus filas y columnas con id propio. Transcribe los seis tipos de `Pregunta`,
incluidas las FILAS AGREGADAS: si una pregunta tiene `filas_adicionales` (las filas extra de una
matriz, y todas las filas de una lista), la IA puede transcribir filas que no están en el esquema
agrupándolas con un `fila_temporal` que ella misma inventa — el mismo mecanismo que usa el envío
normal desde la web (ver participantes.views).

El resultado queda guardado en `ExtraccionMomento.resultado` (JSON) y, desde HU-84, se escribe
SOLO como `Respuesta` en cuanto termina la transcripción (`escribir_extraccion_momento`): ya no
espera la aprobación de un admin. La excepción es la carga que hace el propio participante
(HU-56, `solicitado_por` vacío), que sigue devolviendo `respuestas_sugeridas` para que él revise
y envíe por el endpoint normal — ahí la revisión ya pasaba antes de escribir."""
import json
import os

from django.db import transaction
from django.utils import timezone

from rest_framework import status
from rest_framework.exceptions import APIException

from auditoria.openai_cliente import auditar_llamadas, hilo_con_contexto
from jornadas import emparejamiento, lectura_documentos

# Modelo de TRANSCRIPCIÓN, distinto del de generación — ver el razonamiento completo y
# las mediciones que lo sustentan en instrumentos/extraccion_ia_openai.py.
DEFAULT_MODEL = os.environ.get('OPENAI_MODEL_TRANSCRIPCION', 'gpt-6-luna')
REASONING_EFFORT = os.environ.get('OPENAI_REASONING_EFFORT', 'medium')
GENERATION_TIMEOUT_SECONDS = 300
MAX_OUTPUT_TOKENS = int(os.environ.get('OPENAI_MAX_OUTPUT_TOKENS', '16000'))
MODELO_USADO_LABEL = 'Generado con IA'
# Cuántas celdas (entradas de salida esperadas) se le piden como máximo en UNA llamada. No garantiza
# que la respuesta no se trunque —ante un truncado el lote se parte solo, ver
# `lectura_documentos.transcribir_en_partes`— sino que evita el reintento en el caso normal. Mismo
# valor y mismo razonamiento que instrumentos.extraccion_ia_openai.
PRESUPUESTO_CELDAS_POR_LLAMADA = int(os.environ.get('KUNSAMU_CELDAS_POR_LLAMADA', '40'))
# Cuántas filas agregadas se presupuestan para una pregunta que las acepta. No hay forma de saber
# cuántas trae el documento antes de leerlo; 5 es lo que se ha visto en las jornadas reales y el
# presupuesto de todos modos es un techo, no una cuota a llenar.
FILAS_DINAMICAS_ESTIMADAS = 5
MENSAJE_SIN_RESPUESTAS = (
    'El documento no traía ninguna respuesta que se pudiera transcribir: todas sus casillas y '
    'celdas están en blanco, o no corresponden a las preguntas de este momento. Verifica que el '
    'archivo subido sea la copia YA DILIGENCIADA del formato y no la plantilla vacía.'
)

SYSTEM_PROMPT_EXTRACCION = (
    "Eres un transcriptor de formularios. Se te entrega, en JSON, el ESQUEMA completo de un "
    "momento (lista de preguntas, cada una con su id real, tipo y — si aplica — sus opciones con "
    "su id real), y el contenido de un documento (PDF o Word) que alguien ya diligenció a mano o "
    "en computador fuera de este sistema. Tu única tarea es leer ese documento y transcribir, "
    "para cada pregunta que SÍ tenga contenido en el documento, una entrada que apunte al id "
    "real de esa pregunta.\n\n"

    "=== REGLAS ESTRICTAS ===\n"
    "1. USA SOLO los ids que te dimos en el esquema — nunca inventes uno.\n"
    "2. Si una pregunta no tiene contenido en el documento (en blanco, ilegible, no la "
    "encuentras), NO incluyas una entrada para ella — no inventes ni dejes texto vacío como "
    "relleno.\n"
    "3. Pregunta tipo 'abierta' o 'audio': una entrada con texto_libre = lo transcrito "
    "literalmente (puedes corregir errores obvios de tipeo, pero no resumas ni parafrasees). "
    "Las dos se tratan igual acá: en un documento diligenciado una pregunta 'audio' ya viene "
    "escrita, no grabada.\n"
    "4. Pregunta tipo 'unica'/'multiple': una entrada con opcion_ids = [id de la(s) opción(es) "
    "marcada(s)], usando el id de la opción cuyo texto mejor coincida con lo marcado/escrito — "
    "nunca opciones que no estén en el esquema de esa pregunta.\n"
    "5. Pregunta tipo 'matriz': UNA entrada POR CADA celda (fila×columna) que tenga contenido, "
    "con fila_id y columna_id = los ids correspondientes de ESA pregunta y texto_libre = lo "
    "escrito en esa celda — nunca mezcles filas/columnas de una matriz con otra.\n"
    "6. FILAS AGREGADAS. Algunas preguntas traen 'filas_adicionales': true en el esquema. Ahí el "
    "documento puede tener filas que NO están en la lista 'filas' — se las agregó a mano quien "
    "diligenció (una fila extra al final de la tabla, un renglón escrito en el margen, una hoja "
    "anexa con más registros). Transcríbelas así:\n"
    "   - una entrada POR CADA celda de esa fila nueva, con columna_id = la columna que "
    "corresponde y texto_libre = lo escrito;\n"
    "   - en vez de fila_id, pon 'fila_temporal': un número que TÚ inventas solo para agrupar "
    "las celdas de una misma fila nueva (1 para la primera fila agregada de esa pregunta, 2 para "
    "la segunda...). NO es el id de nada: no lo busques en el esquema, no lo reutilices entre "
    "preguntas distintas;\n"
    "   - nunca pongas fila_id y fila_temporal en la misma entrada: o la fila ya existía en el "
    "esquema (fila_id) o la agregó quien diligenció (fila_temporal).\n"
    "   Una pregunta tipo 'lista' funciona SOLO así: no tiene filas predefinidas, todas sus "
    "filas van con fila_temporal.\n"
    "   Si la pregunta NO trae 'filas_adicionales': true, no uses fila_temporal ahí — cualquier "
    "fila que no esté en el esquema simplemente no se transcribe.\n"
    "7. Nunca mezcles: no le pongas opcion_ids a una pregunta abierta/audio, matriz o lista, no le "
    "pongas fila_id/columna_id a una pregunta que no sea matriz/lista, ni texto_libre a una de "
    "opción.\n"
    "8. RESPONSABLE. Además de las respuestas, busca quién diligenció el documento — casi siempre "
    "está en las primeras líneas o en un encabezado, con etiquetas como 'Responsable', "
    "'Diligenciado por', 'Nombre', 'Elaborado por' o una firma al pie. Devuélvelo en el "
    "bloque 'responsable', copiando el texto TAL CUAL aparece (no lo normalices, no lo "
    "completes, no deduzcas un correo que no esté escrito). Si un dato no está, déjalo en null; "
    "si no encuentras ningún responsable, deja todo el bloque en null. NUNCA inventes un nombre "
    "ni uses el de una persona mencionada dentro de una respuesta — solo quien firma o declara "
    "haber diligenciado el documento.\n\n"

    "=== FORMATO DE SALIDA (obligatorio) ===\n"
    "Responde ÚNICAMENTE con un objeto JSON válido, sin explicación antes ni después, sin fences "
    "de markdown, con esta forma exacta:\n"
    "{\n"
    '  "responsable": {"nombre": "<texto o null>", "correo": "<texto o null>", '
    '"cargo": "<texto o null>", "dependencia": "<texto o null>"},\n'
    '  "respuestas": [\n'
    '    {"pregunta": <id>, "texto_libre": "<texto o \'\'>", "opcion_ids": [<ids>], '
    '"fila_id": <id o null>, "fila_temporal": <número o null>, "columna_id": <id o null>}\n'
    "  ]\n"
    "}\n"
)


def _leer_documento(extraccion):
    """Despacha por extensión de archivo. Devuelve (texto_o_None, imagenes_base64_o_None).

    La lectura misma vive en `jornadas.lectura_documentos`, compartida con la extracción de
    instrumentos (ver el docstring de ese módulo: estaba duplicada y el bug de orden de los bloques
    del .docx existía en las dos copias)."""
    nombre = extraccion.nombre_archivo_original or extraccion.archivo.name
    extraccion.archivo.open('rb')
    try:
        return lectura_documentos.leer_documento(extraccion.archivo, nombre)
    finally:
        extraccion.archivo.close()


def _payload_pregunta(pregunta):
    from jornadas.models import Pregunta

    # Las columnas van tanto en matriz como en lista (una lista ES columnas fijas + filas
    # dinámicas). Las filas predefinidas solo existen en matriz. `filas_adicionales` es lo que
    # le dice a la IA si puede transcribir filas que no están en el esquema, usando
    # fila_temporal — sin este dato en el payload la regla 6 del prompt no tendría cómo
    # aplicarse pregunta por pregunta.
    es_tabla = pregunta.tipo in (Pregunta.TIPO_MATRIZ, Pregunta.TIPO_LISTA)
    return {
        'id': pregunta.id,
        'texto': pregunta.texto,
        'tipo': pregunta.tipo,
        'filas_adicionales': pregunta.acepta_filas_dinamicas,
        'opciones': [{'id': o.id, 'texto': o.texto} for o in pregunta.opciones.all()],
        'filas': (
            [{'id': f.id, 'texto': f.texto} for f in pregunta.filas.all()]
            if pregunta.tipo == Pregunta.TIPO_MATRIZ else []
        ),
        'columnas': (
            [{'id': c.id, 'texto': c.texto} for c in pregunta.columnas.all()]
            if es_tabla else []
        ),
    }


def _preguntas_activas(momento):
    return list(momento.preguntas.filter(activa=True).order_by('orden'))


def _construir_payload_esquema(momento):
    """El esquema completo, sin partir. El pipeline arma los lotes en `_transcribir_por_lotes`;
    esto queda como la vista de "todo lo que la IA puede ver" para tests y depuración."""
    return {
        'momento': momento.titulo,
        'preguntas': [_payload_pregunta(p) for p in _preguntas_activas(momento)],
    }


def _celdas_esperadas(pregunta):
    """Cuántas entradas de salida puede llegar a producir una pregunta. Es lo que define el tamaño
    de los lotes: una matriz de 14×4 sola ya son 56 entradas."""
    from jornadas.models import Pregunta

    if pregunta.tipo == Pregunta.TIPO_MATRIZ:
        celdas = max(1, len(pregunta.filas.all()) * len(pregunta.columnas.all()))
        if pregunta.acepta_filas_dinamicas:
            celdas += len(pregunta.columnas.all()) * FILAS_DINAMICAS_ESTIMADAS
        return celdas
    if pregunta.tipo == Pregunta.TIPO_LISTA:
        # Una lista no tiene filas predefinidas: todo lo que produzca son filas agregadas.
        return max(1, len(pregunta.columnas.all()) * FILAS_DINAMICAS_ESTIMADAS)
    return 1


def _lotes_de_esquema(momento):
    """El esquema partido en payloads, para inspeccionar desde fuera cómo quedaría repartido. El
    pipeline no lo usa: necesita los objetos del lote, no su payload, para poder re-partirlo si la
    respuesta se trunca (ver `_transcribir_por_lotes`)."""
    lotes = lectura_documentos.agrupar_en_lotes(
        _preguntas_activas(momento), _celdas_esperadas, PRESUPUESTO_CELDAS_POR_LLAMADA,
    )
    return [
        {'momento': momento.titulo, 'preguntas': [_payload_pregunta(p) for p in lote]}
        for lote in lotes
    ]


def _llamar_openai_extraccion(esquema, texto_documento=None, imagenes_base64=None):
    """Devuelve `(dict_o_None, error, truncado)` — nunca lanza excepción. `truncado` es lo que mira
    `lectura_documentos.transcribir_en_partes` para decidir si parte el lote y reintenta."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None, 'OPENAI_API_KEY no está configurada en el entorno del servidor (.env).', False

    encabezado = 'ESQUEMA DEL MOMENTO (JSON):\n' + json.dumps(esquema, ensure_ascii=False, indent=2)

    if imagenes_base64:
        contenido_usuario = [
            {'type': 'text', 'text': encabezado + '\n\nDOCUMENTO DILIGENCIADO (páginas adjuntas como imagen):'},
        ]
        for imagen_b64 in imagenes_base64:
            contenido_usuario.append({
                'type': 'image_url',
                'image_url': {'url': f'data:image/png;base64,{imagen_b64}', 'detail': 'high'},
            })
    else:
        contenido_usuario = (
            encabezado + '\n\nDOCUMENTO DILIGENCIADO (texto extraído):\n' + (texto_documento or '')
        )

    resultado = {}

    def _run():
        try:
            from auditoria.openai_cliente import cliente_openai
            client = cliente_openai('extraccion_momento', api_key=api_key)
            kwargs = dict(
                model=DEFAULT_MODEL,
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT_EXTRACCION},
                    {'role': 'user', 'content': contenido_usuario},
                ],
                max_completion_tokens=MAX_OUTPUT_TOKENS,
                response_format={'type': 'json_object'},
            )
            if REASONING_EFFORT:
                kwargs['reasoning_effort'] = REASONING_EFFORT
            else:
                kwargs['temperature'] = 0.2
            respuesta = client.chat.completions.create(**kwargs)
            eleccion = respuesta.choices[0]
            # Truncado por tope de tokens: el JSON viene cortado a mitad y `json.loads` de más
            # abajo falla con un error de sintaxis que no dice nada de la causa real.
            if eleccion.finish_reason == 'length':
                resultado['error'] = (
                    f'La respuesta del modelo se truncó por el tope de {MAX_OUTPUT_TOKENS} tokens '
                    'de salida: el bloque de preguntas pedido en esta llamada es demasiado grande.'
                )
                resultado['truncado'] = True
                return
            resultado['texto'] = eleccion.message.content.strip()
        except Exception as exc:  # noqa: BLE001
            resultado['error'] = str(exc)

    hilo = hilo_con_contexto(_run)
    hilo.start()
    hilo.join(timeout=GENERATION_TIMEOUT_SECONDS)

    if hilo.is_alive():
        return None, f'Tiempo de espera agotado ({GENERATION_TIMEOUT_SECONDS}s) esperando a OpenAI.', False
    if resultado.get('error'):
        return None, resultado['error'], resultado.get('truncado', False)
    texto = resultado.get('texto')
    if not texto:
        return None, 'OpenAI no devolvió contenido.', False
    try:
        return json.loads(texto), None, False
    except json.JSONDecodeError as exc:
        return None, f'OpenAI devolvió JSON inválido: {exc}', False


def _fusionar_responsable(acumulado, crudo):
    """Junta el bloque `responsable` de varias llamadas quedándose con el primer valor no vacío de
    cada campo — el documento entero viaja en todas, así que cualquiera puede leer el encabezado."""
    if not isinstance(crudo, dict):
        return acumulado
    fusionado = dict(acumulado)
    for clave in ('nombre', 'correo', 'cargo', 'dependencia'):
        valor = crudo.get(clave)
        if not fusionado.get(clave) and isinstance(valor, str) and valor.strip():
            fusionado[clave] = valor.strip()
    return fusionado


def _transcribir_por_lotes(momento, texto_documento=None, imagenes_base64=None):
    """Pide la transcripción en varias llamadas —una por lote de preguntas— y las junta en un solo
    resultado con la misma forma que devolvía la llamada única de antes.

    Un lote cuya respuesta se trunque se parte solo y se reintenta (ver
    `lectura_documentos.transcribir_en_partes`). Si falla por cualquier otra razón, falla toda la
    extracción: media transcripción sin avisar es indistinguible de un documento a medio llenar."""
    preguntas = _preguntas_activas(momento)
    if not preguntas:
        return None, 'El momento no tiene preguntas activas que transcribir.'

    lotes = lectura_documentos.agrupar_en_lotes(
        preguntas, _celdas_esperadas, PRESUPUESTO_CELDAS_POR_LLAMADA,
    )

    def llamar(sublote):
        esquema = {
            'momento': momento.titulo,
            'preguntas': [_payload_pregunta(p) for p in sublote],
        }
        return _llamar_openai_extraccion(
            esquema, texto_documento=texto_documento, imagenes_base64=imagenes_base64,
        )

    respuestas = []
    responsable = {}
    for numero, lote in enumerate(lotes, start=1):
        parciales, error = lectura_documentos.transcribir_en_partes(
            lote, llamar, describir=lambda pregunta: f'la pregunta «{pregunta.texto[:70]}»',
        )
        if parciales is None:
            return None, f'Bloque {numero} de {len(lotes)}: {error}'
        for parcial in parciales:
            respuestas.extend(parcial.get('respuestas') or [])
            responsable = _fusionar_responsable(responsable, parcial.get('responsable'))

    return {'responsable': responsable, 'respuestas': respuestas}, None


def _limpiar_y_validar(resultado_crudo, momento):
    """Descarta cualquier entrada que no pase la misma validación por tipo que ya usa el envío
    normal (participantes.views._validar_entrada) — a diferencia de ese endpoint, NO aborta todo
    si una entrada falla, solo la omite (queda en preguntas_omitidas). No escribe Respuesta acá —
    solo deja `resultado` listo para que escribir_extraccion_momento lo escriba después."""
    from jornadas.models import Pregunta

    from participantes.views import _validar_entrada

    preguntas_validas = {p.id: p for p in momento.preguntas.filter(activa=True)}
    limpio = []
    omitidas = []
    for crudo in resultado_crudo.get('respuestas') or []:
        pregunta = preguntas_validas.get(crudo.get('pregunta'))
        if pregunta is None:
            omitidas.append(crudo.get('pregunta'))
            continue
        texto_libre = crudo.get('texto_libre', '') or ''
        opcion_ids = crudo.get('opcion_ids') or []
        opciones = list(pregunta.opciones.filter(id__in=opcion_ids))

        fila = columna = None
        fila_temporal = None
        if pregunta.tipo in (Pregunta.TIPO_MATRIZ, Pregunta.TIPO_LISTA):
            columna = pregunta.columnas.filter(id=crudo.get('columna_id')).first()
            if pregunta.tipo == Pregunta.TIPO_MATRIZ:
                fila = pregunta.filas.filter(id=crudo.get('fila_id')).first()
            if pregunta.acepta_filas_dinamicas and crudo.get('fila_temporal') is not None:
                # `fila_temporal` lo inventa la IA para agrupar las celdas de una fila que no
                # estaba en el esquema (ver regla 6 del prompt). No se resuelve contra la base
                # —no apunta a nada todavía—, solo tiene que ser un entero; cualquier otra cosa
                # es una alucinación y la entrada se omite como cualquier otra inconsistencia.
                try:
                    fila_temporal = int(crudo['fila_temporal'])
                except (TypeError, ValueError):
                    omitidas.append(pregunta.id)
                    continue

        try:
            _validar_entrada(pregunta, texto_libre, opciones, fila, columna, fila_temporal)
        except Exception:  # noqa: BLE001 — ValidationError u otra inconsistencia de la IA
            omitidas.append(pregunta.id)
            continue
        limpio.append({
            'pregunta': pregunta.id, 'texto_libre': texto_libre, 'opcion_ids': [o.id for o in opciones],
            'fila_id': fila.id if fila else None, 'fila_temporal': fila_temporal,
            'columna_id': columna.id if columna else None,
        })

    return {'respuestas': limpio}, omitidas


def _limpiar_responsable(crudo):
    """Normaliza el bloque `responsable` que devolvió la IA a un dict de strings. La IA puede
    mandar null, omitirlo, o mandar cualquier cosa en los campos — nada de eso puede tumbar una
    extracción que por lo demás salió bien."""
    if not isinstance(crudo, dict):
        return {}
    limpio = {}
    for clave in ('nombre', 'correo', 'cargo', 'dependencia'):
        valor = crudo.get(clave)
        if isinstance(valor, str) and valor.strip():
            limpio[clave] = valor.strip()
    return limpio


def emparejar_responsable_momento(momento, responsable):
    """Busca a qué Participante de ESTA jornada corresponde el responsable que leyó la IA.

    El conjunto de candidatos es la jornada completa, no el momento: un participante existe a
    nivel de jornada y puede no haber respondido todavía nada de este momento — que es
    justamente el caso de quien llenó el documento en papel."""
    from .models import Participante

    if not responsable:
        return None, emparejamiento.ESTADO_SIN_DATO

    candidatos = [
        (p, f'{p.nombre} {p.apellido}', p.correo_institucional)
        for p in Participante.objects.filter(jornada_id=momento.jornada_id)
    ]
    return emparejamiento.emparejar(
        candidatos, nombre=responsable.get('nombre'), correo=responsable.get('correo'),
    )


# Qué hacer cuando la persona ya tiene respuestas en el momento (HU-91). Sin uno de estos, nada
# se escribe sobre respuestas existentes: ni la carga automática ni `asignar-responsable`.
MODO_SOBRESCRIBIR = 'sobrescribir'
MODO_NUEVA_VERSION = 'nueva_version'
MODOS_ESCRITURA = (MODO_SOBRESCRIBIR, MODO_NUEVA_VERSION)


class ConflictoRespuestasPrevias(APIException):
    """409: la persona ya respondió este momento y nadie dijo qué hacer con eso.

    El detalle lleva lo que el frontend necesita para preguntarle a quien carga: a quién, qué
    versiones tiene ya, y los modos válidos."""
    status_code = status.HTTP_409_CONFLICT
    default_code = 'respuestas_previas'

    def __init__(self, participante, versiones):
        super().__init__()
        # Asignado directo y no por el constructor: APIException convierte todo el detalle a
        # texto, y el frontend necesita `participante_id` y las versiones como números.
        self.detail = {
            'detail': (
                f'{participante.nombre} {participante.apellido} ya tiene respuestas en este '
                'momento. Indica `modo`: "sobrescribir" para reemplazarlas o "nueva_version" para '
                'que convivan; o asigna el documento a otra persona.'
            ),
            'participante_id': participante.id,
            'versiones_existentes': versiones,
            'modos': list(MODOS_ESCRITURA),
        }


def versiones_existentes(participante, momento):
    """Las versiones (ver Respuesta.version) que esta persona ya tiene escritas en el momento,
    ordenadas. Lista vacía = nunca respondió ese momento."""
    from .models import Respuesta

    if participante is None:
        return []
    return sorted(set(
        Respuesta.objects.filter(participante=participante, pregunta__momento=momento)
        .values_list('version', flat=True)
    ))


DOMINIO_SIN_REGISTRO = 'sin-registro.local'
ROL_SIN_REGISTRO = 'sin rol'


def _partir_nombre(completo):
    """Parte el nombre leído del documento en `(nombre, apellido)`.

    `Participante` guarda nombre y apellido por separado y el documento trae un solo texto, así que
    hay que decidir dónde cortar. Con cuatro palabras o más se corta a la mitad (el caso corriente
    acá: dos nombres y dos apellidos); con menos, la primera palabra es el nombre y el resto el
    apellido.

    Ninguna heurística acierta siempre —"Juan Carlos Pérez" puede ser dos nombres y un apellido o
    uno y dos— y no hace falta que acierte: el texto completo queda repartido entre los dos campos,
    que es lo que importa para que el emparejamiento lo reconozca en el próximo documento (compara
    nombre + apellido normalizados, ver jornadas/emparejamiento.py)."""
    partes = (completo or '').split()
    if not partes:
        return '', ''
    if len(partes) >= 4:
        mitad = len(partes) // 2
        return ' '.join(partes[:mitad]), ' '.join(partes[mitad:])
    return partes[0], ' '.join(partes[1:])


def _correo_libre(jornada_id, nombre_completo):
    """Un correo de relleno, único en la jornada y evidentemente falso.

    `correo_institucional` es obligatorio y único por jornada, así que no se puede dejar vacío:
    con dos responsables sin correo en la misma jornada, el segundo rompería la constraint. El
    dominio `sin-registro.local` no existe a propósito — marca a la persona como "esto salió de un
    papel, no de un registro" y hace que no pueda entrar a la plataforma con ese correo, que es lo
    correcto: nunca se registró."""
    from django.utils.text import slugify

    from .models import Participante

    base = slugify(nombre_completo) or 'responsable'
    candidato = f'{base}@{DOMINIO_SIN_REGISTRO}'
    contador = 1
    while Participante.objects.filter(
        jornada_id=jornada_id, correo_institucional=candidato,
    ).exists():
        contador += 1
        candidato = f'{base}-{contador}@{DOMINIO_SIN_REGISTRO}'
    return candidato


def crear_participante_desde_responsable(momento, responsable):
    """Da de alta al responsable que leyó la IA cuando no coincide con nadie de la jornada (HU-86).

    Antes esto quedaba esperando que un admin registrara a la persona a mano y recién después
    asignara el documento — dos pasos antes de poder guardar una transcripción que ya estaba
    hecha, y multiplicado por cada departamento de una carga masiva. Quien llenó el formato en
    papel muy probablemente nunca se registró en la plataforma: pedir el registro primero es
    pedirle al admin que transcriba a mano justamente el dato que la IA ya leyó.

    Se crea con `rol` = "sin rol" y, si el documento no traía correo, con uno de relleno: son los
    dos únicos campos obligatorios que un formato en papel no siempre da. Devuelve `None` si no
    hay ni un nombre utilizable — sin nombre no hay a quién crear.

    El `cargo` que la IA haya leído ("Jefa del Departamento de Biología") NO se usa como `rol`,
    aunque esté ahí y sea tentador: `rol` es el rol institucional dentro de la jornada, un
    vocabulario corto y propio del sistema por el que se agrupa y se filtra, y meterle texto libre
    de un formato lo volvería inservible para eso. El cargo leído no se pierde: queda en
    `ExtraccionMomento.responsable_detectado` junto al resto de lo que trajo el documento."""
    from .models import Participante

    nombre_completo = (responsable or {}).get('nombre') or ''
    if not nombre_completo.strip():
        return None

    nombre, apellido = _partir_nombre(nombre_completo)
    # El correo del documento, si lo trajo. No puede chocar con nadie: `emparejar` prueba el correo
    # exacto ANTES que el nombre, así que si otra persona de la jornada ya lo tuviera habríamos
    # salido por `emparejado` o `ambiguo` y no estaríamos creando. Se comprueba igual, porque
    # depender de esa coincidencia desde otro módulo es frágil.
    correo = (responsable.get('correo') or '').strip()
    if not correo or Participante.objects.filter(
        jornada_id=momento.jornada_id, correo_institucional=correo,
    ).exists():
        correo = _correo_libre(momento.jornada_id, nombre_completo)

    return Participante.objects.create(
        jornada_id=momento.jornada_id,
        correo_institucional=correo,
        nombre=nombre,
        apellido=apellido,
        rol=ROL_SIN_REGISTRO,
    )


@auditar_llamadas('participantes.ExtraccionMomento')
def procesar_extraccion_momento(extraccion_id):
    """Genera el `resultado` de una ExtraccionMomento ya creada (estado 'pendiente'). Corre en un
    hilo de background — mismo patrón que instrumentos.extraccion_ia_openai. NO escribe
    Respuesta — deja el resultado listo para revisión/aprobación manual."""
    from django.db import close_old_connections

    close_old_connections()
    from .models import ExtraccionMomento

    extraccion = None
    try:
        extraccion = ExtraccionMomento.objects.select_related('momento').get(pk=extraccion_id)
        extraccion.estado = ExtraccionMomento.ESTADO_PROCESANDO
        extraccion.save(update_fields=['estado'])

        texto, imagenes = _leer_documento(extraccion)

        if not imagenes and not (texto or '').strip():
            # Documento del que no se pudo sacar ni una línea. No se gasta una llamada al proveedor
            # para confirmarlo, y el mensaje dice qué pasó.
            extraccion.estado = ExtraccionMomento.ESTADO_ERROR
            extraccion.error_mensaje = (
                'No se pudo leer ningún texto del documento. Verifica que el archivo no esté '
                'vacío ni dañado.'
            )
            extraccion.save(update_fields=['estado', 'error_mensaje'])
            return

        resultado, error = _transcribir_por_lotes(
            extraccion.momento, texto_documento=texto, imagenes_base64=imagenes,
        )

        if resultado is None:
            extraccion.estado = ExtraccionMomento.ESTADO_ERROR
            extraccion.error_mensaje = error or 'Error desconocido generando la extracción.'
            extraccion.save(update_fields=['estado', 'error_mensaje'])
            return

        limpio, omitidas = _limpiar_y_validar(resultado, extraccion.momento)

        if not limpio['respuestas']:
            # Ninguna respuesta utilizable: acá sí se mira DESPUÉS de validar (a diferencia de
            # instrumentos, que no puede validar sin escribir), así que el corte cubre tanto el
            # documento en blanco como el caso de que la IA haya devuelto solo ids inventados —
            # `preguntas_omitidas` queda guardado para distinguir uno del otro. Sin esto la
            # extracción quedaba en `completo` con cero respuestas: indistinguible de un fallo.
            extraccion.resultado = limpio
            extraccion.preguntas_omitidas = omitidas
            extraccion.estado = ExtraccionMomento.ESTADO_ERROR
            extraccion.error_mensaje = MENSAJE_SIN_RESPUESTAS
            extraccion.modelo_usado = MODELO_USADO_LABEL
            extraccion.save(update_fields=[
                'resultado', 'preguntas_omitidas', 'estado', 'error_mensaje', 'modelo_usado',
            ])
            return

        # El responsable solo se busca si no lo dijeron al subir: un participante indicado a mano
        # es una decisión humana y no se pisa con lo que haya leído la IA.
        campos_responsable = []
        if extraccion.participante_id is None:
            detectado = _limpiar_responsable(resultado.get('responsable'))
            participante, estado = emparejar_responsable_momento(extraccion.momento, detectado)
            if participante is None and estado == emparejamiento.ESTADO_SIN_COINCIDENCIA:
                # No existe en la jornada: se da de alta con lo que trae el documento (HU-86). Solo
                # en `sin_coincidencia` — un `ambiguo` NO se crea, porque ahí el documento
                # probablemente sí es de una de las personas que ya existen y sumar una tercera
                # homónima sería el peor resultado posible.
                participante = crear_participante_desde_responsable(extraccion.momento, detectado)
                if participante is not None:
                    estado = emparejamiento.ESTADO_CREADO
            extraccion.responsable_detectado = detectado
            extraccion.responsable_estado = estado
            if participante is not None:
                extraccion.participante = participante
            campos_responsable = ['responsable_detectado', 'responsable_estado', 'participante']

        # HU-91: si la persona ya respondió este momento (por la web o con otro documento), NO se
        # le escribe encima. Pasa a `participante_sugerido` y la extracción queda sin responsable,
        # esperando que quien cargó decida en `asignar-responsable`. Vale también para el
        # participante indicado a mano al subir: haberlo elegido no es haber elegido pisarle lo
        # que ya tenía. Solo en cargas de admin — la del propio participante (HU-56) nunca
        # escribe sola, revisa y envía él mismo.
        if (
            extraccion.solicitado_por_id is not None
            and extraccion.participante_id is not None
            and versiones_existentes(extraccion.participante, extraccion.momento)
        ):
            extraccion.participante_sugerido = extraccion.participante
            extraccion.participante = None
            extraccion.responsable_estado = emparejamiento.ESTADO_CON_RESPUESTAS
            campos_responsable = [
                'responsable_detectado', 'responsable_estado', 'participante',
                'participante_sugerido',
            ]

        extraccion.resultado = limpio
        extraccion.preguntas_omitidas = omitidas
        extraccion.estado = ExtraccionMomento.ESTADO_COMPLETO
        extraccion.error_mensaje = ''
        extraccion.modelo_usado = MODELO_USADO_LABEL
        extraccion.completado_en = timezone.now()
        extraccion.save(update_fields=[
            'resultado', 'preguntas_omitidas', 'estado', 'error_mensaje', 'modelo_usado',
            'completado_en', *campos_responsable,
        ])

        # HU-84: la transcripción se escribe sola. Dos condiciones:
        # - `solicitado_por` no vacío: la subió un admin. Cuando la sube el propio participante
        #   (HU-56) el flujo no cambia — recibe `respuestas_sugeridas`, corrige en pantalla y
        #   envía por el endpoint normal, que es revisar ANTES de escribir;
        # - hay participante: si la IA no pudo emparejar al responsable, o la persona ya tenía
        #   respuestas (HU-91), no hay a nombre de quién escribir todavía, así que queda esperando
        #   `asignar-responsable`, que escribe ahí mismo.
        if extraccion.solicitado_por_id is not None and extraccion.participante_id is not None:
            escribir_extraccion_momento(extraccion, extraccion.solicitado_por)
    except Exception as exc:  # noqa: BLE001
        if extraccion is not None:
            extraccion.estado = ExtraccionMomento.ESTADO_ERROR
            extraccion.error_mensaje = str(exc)
            extraccion.save(update_fields=['estado', 'error_mensaje'])
    finally:
        close_old_connections()


def procesar_extracciones_en_serie(ids):
    """Procesa varias extracciones UNA DESPUÉS DE OTRA (carga masiva, HU-84).

    En serie y no un hilo por archivo: desde HU-81 cada documento son entre 5 y 9 llamadas a
    OpenAI, así que una tanda de treinta en paralelo serían más de doscientas llamadas simultáneas
    contra el proveedor — límite de tasa seguro, y el pipeline no reintenta ante un 429 (solo ante
    un truncado, ver lectura_documentos.transcribir_en_partes).

    Una que falle no detiene a las demás: cada extracción guarda su propio estado y su propio
    `error_mensaje`, que es justamente lo que permite reintentar solo la que falló."""
    for extraccion_id in ids:
        procesar_extraccion_momento(extraccion_id)


def _escribir_filas_agregadas(pregunta, items, participante, version):
    """Escribe las celdas que la IA transcribió como filas AGREGADAS (`fila_temporal`): las filas
    extra de una matriz con filas_adicionales, y todas las filas de una lista.

    Reemplaza las filas dinámicas que ese participante ya tuviera **en esta pregunta**, igual que
    el envío normal (participantes.views._guardar_filas_dinamicas) — el documento aprobado es la
    versión buena de esa tabla, no un anexo a lo anterior. A diferencia del envío normal, acá NO
    se borran las filas de preguntas que la IA no mencionó: escribir una extracción guarda lo que
    el documento traía, y un documento que no habla de una pregunta no es una instrucción de
    borrarla."""
    from .models import FilaListaRespuesta, Respuesta

    FilaListaRespuesta.objects.filter(
        pregunta=pregunta, participante=participante, version=version,
    ).delete()

    filas_por_temporal = {
        ft: FilaListaRespuesta.objects.create(
            pregunta=pregunta, participante=participante, version=version, orden=i,
        )
        for i, ft in enumerate(sorted({item['fila_temporal'] for item in items}), start=1)
    }

    guardadas = []
    for item in items:
        guardadas.append(Respuesta.objects.create(
            pregunta=pregunta,
            participante=participante,
            version=version,
            fila_lista=filas_por_temporal[item['fila_temporal']],
            columna_id=item.get('columna_id'),
            texto_libre=item.get('texto_libre', ''),
            registrado_por=participante,
        ))
    return guardadas


def _version_destino(extraccion, modo, version):
    """En qué versión se escribe (HU-91). Sin respuestas previas, la 1 y no hace falta modo. Con
    respuestas previas el modo es obligatorio:

    - `nueva_version`: la siguiente a la más alta; las anteriores quedan intactas. Es lo que
      corresponde a OTRO documento de la misma persona (otra facultad, otra dependencia).
    - `sobrescribir`: actualiza la indicada en `version`, o la única que haya, con lo que trae el
      documento — mismo criterio de siempre: las preguntas que el documento no menciona se
      conservan (ver `_escribir_filas_agregadas`). Es para una versión corregida del mismo
      documento; para uno distinto, mezclar los dos es justo lo que HU-91 vino a evitar."""
    from rest_framework.exceptions import ValidationError

    from .models import Respuesta

    versiones = versiones_existentes(extraccion.participante, extraccion.momento)
    if not versiones:
        return Respuesta.VERSION_ORIGINAL
    if modo is None:
        raise ConflictoRespuestasPrevias(extraccion.participante, versiones)
    if modo == MODO_NUEVA_VERSION:
        return versiones[-1] + 1
    if modo != MODO_SOBRESCRIBIR:
        raise ValidationError({'modo': f'Modo desconocido: {modo}. Usa uno de {list(MODOS_ESCRITURA)}.'})

    if version is None:
        if len(versiones) > 1:
            raise ValidationError({'version': (
                f'Esta persona tiene varias versiones en el momento ({versiones}); indica cuál '
                'sobrescribir.'
            )})
        version = versiones[0]
    elif version not in versiones:
        raise ValidationError({'version': (
            f'La versión {version} no existe para esta persona en el momento (tiene {versiones}).'
        )})
    return version


@transaction.atomic
def escribir_extraccion_momento(extraccion, escrito_por, modo=None, version=None):
    """Escribe `extraccion.resultado` como Respuesta reales del participante — mismo lookup/save
    que RespuestasMomentoView.post() (participante individual, registrado_por=el mismo
    participante).

    Desde HU-84 la dispara `procesar_extraccion_momento` SOLA, en cuanto termina la transcripción:
    ya no espera que un admin la apruebe. El cambio de criterio es del dueño del repo y es
    sensato — quien sube el documento es quien sabe si lo que dice está bien, y un admin que carga
    treinta formatos de treinta departamentos no puede revisar treinta pantallas antes de que se
    guarde nada. Lo que lo hace viable es que ahora SÍ se puede corregir lo escrito
    (`RespuestaAdminViewSet` admite PATCH y DELETE): antes esta espera era la única ventana de
    revisión que existía, y por eso existía.

    `aprobado_en`/`aprobado_por` se conservan con ese nombre —no hay migración— pero ya no
    significan "un humano lo aprobó" sino "cuándo se escribieron las respuestas y a cuenta de
    quién". Para una carga de admin es quien subió el archivo.

    Atómico por lo mismo que el envío normal: las filas agregadas se borran y se recrean, así que
    una falla a mitad dejaría la tabla del participante incompleta.

    HU-91: si la persona ya tiene respuestas en el momento, NUNCA las pisa por su cuenta — lanza
    `ConflictoRespuestasPrevias` (409) salvo que venga `modo` (ver `_version_destino`)."""
    from django.utils import timezone as tz

    from rest_framework.exceptions import ValidationError

    from jornadas.models import Pregunta

    from .models import Respuesta

    if extraccion.participante_id is None:
        # Desde HU-55 el responsable puede venir sin resolver (la IA no lo encontró, o encontró
        # dos personas con ese nombre). La transcripción sigue intacta en `resultado`; lo único
        # que falta es a nombre de quién se escribe, y eso lo decide una persona.
        raise ValidationError({'participante': (
            'Esta extracción todavía no tiene responsable asignado, así que no hay a nombre de '
            'quién escribir las respuestas. Asigna uno con `asignar-responsable` '
            f'(responsable detectado: {extraccion.responsable_detectado or "ninguno"}).'
        )})

    destino = _version_destino(extraccion, modo, version)
    preguntas = {p.id: p for p in Pregunta.objects.filter(momento=extraccion.momento)}
    guardadas = []
    # Las celdas de fila agregada se juntan por pregunta antes de escribir: una FilaListaRespuesta
    # agrupa varias celdas, así que no se puede ir celda por celda como con las de fila fija.
    agregadas_por_pregunta = {}

    for item in extraccion.resultado.get('respuestas') or []:
        pregunta = preguntas.get(item['pregunta'])
        if pregunta is None:
            continue
        if item.get('fila_temporal') is not None and pregunta.acepta_filas_dinamicas:
            agregadas_por_pregunta.setdefault(pregunta, []).append(item)
            continue
        respuesta, _ = Respuesta.objects.update_or_create(
            pregunta=pregunta, participante=extraccion.participante, version=destino,
            fila_id=item.get('fila_id'), columna_id=item.get('columna_id'),
            defaults={'texto_libre': item.get('texto_libre', ''), 'registrado_por': extraccion.participante},
        )
        respuesta.opciones.set(item.get('opcion_ids') or [])
        guardadas.append(respuesta)

    for pregunta, items in agregadas_por_pregunta.items():
        guardadas.extend(_escribir_filas_agregadas(pregunta, items, extraccion.participante, destino))

    extraccion.aprobado_en = tz.now()
    extraccion.aprobado_por = escrito_por
    extraccion.version_escrita = destino
    extraccion.save(update_fields=['aprobado_en', 'aprobado_por', 'version_escrita'])
    return guardadas
