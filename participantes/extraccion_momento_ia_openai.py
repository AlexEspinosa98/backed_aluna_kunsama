"""Lee un Momento ya diligenciado fuera de la web (PDF o Word) y lo transcribe con UNA sola
llamada a OpenAI — mismo mecanismo que instrumentos.extraccion_ia_openai (ver ese módulo para el
razonamiento completo de texto-vs-visión), portado acá porque este contenido vive en el modelo
clásico `jornadas.Momento`/`jornadas.Pregunta`, no en el módulo `instrumentos`.

A diferencia de esa otra vía, acá `Pregunta` no tiene tipo "matriz" — el esquema que se le manda
a la IA es plano (una lista de preguntas con su id, tipo y opciones), así que el prompt es más
simple. El resultado queda guardado en `ExtraccionMomento.resultado` (JSON) SIN tocar `Respuesta`
— la escritura real pasa por `aprobar_extraccion_momento`, disparada a mano por un admin desde la
vista (ver participantes/admin_views.py)."""
import base64
import json
import os
import threading

from django.utils import timezone

DEFAULT_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o')
REASONING_EFFORT = os.environ.get('OPENAI_REASONING_EFFORT', 'medium')
GENERATION_TIMEOUT_SECONDS = 300
MAX_OUTPUT_TOKENS = 8000
MODELO_USADO_LABEL = 'Generado con IA'
MAX_PAGINAS_IMAGEN = 20
UMBRAL_CARACTERES_POR_PAGINA = 40

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
    "3. Pregunta tipo 'abierta': una entrada con texto_libre = lo transcrito literalmente "
    "(puedes corregir errores obvios de tipeo, pero no resumas ni parafrasees).\n"
    "4. Pregunta tipo 'unica'/'multiple': una entrada con opcion_ids = [id de la(s) opción(es) "
    "marcada(s)], usando el id de la opción cuyo texto mejor coincida con lo marcado/escrito — "
    "nunca opciones que no estén en el esquema de esa pregunta.\n"
    "5. Nunca mezcles: no le pongas opcion_ids a una pregunta abierta ni texto_libre a una de "
    "opción.\n\n"

    "=== FORMATO DE SALIDA (obligatorio) ===\n"
    "Responde ÚNICAMENTE con un objeto JSON válido, sin explicación antes ni después, sin fences "
    "de markdown, con esta forma exacta:\n"
    "{\n"
    '  "respuestas": [\n'
    '    {"pregunta": <id>, "texto_libre": "<texto o \'\'>", "opcion_ids": [<ids>]}\n'
    "  ]\n"
    "}\n"
)


def _extraer_texto_docx(archivo):
    from docx import Document

    documento = Document(archivo)
    partes = [p.text for p in documento.paragraphs if p.text.strip()]
    for tabla in documento.tables:
        for fila in tabla.rows:
            celdas = [c.text.strip() for c in fila.cells]
            if any(celdas):
                partes.append(' | '.join(celdas))
    return '\n'.join(partes)


def _extraer_texto_o_imagenes_pdf(archivo):
    import pdfplumber

    archivo.seek(0)
    paginas_texto = []
    with pdfplumber.open(archivo) as pdf:
        n_paginas = len(pdf.pages)
        for pagina in pdf.pages:
            paginas_texto.append(pagina.extract_text() or '')

    texto = '\n'.join(paginas_texto).strip()
    if n_paginas and len(texto) / n_paginas >= UMBRAL_CARACTERES_POR_PAGINA:
        return texto, None

    import fitz  # PyMuPDF

    archivo.seek(0)
    imagenes = []
    documento = fitz.open(stream=archivo.read(), filetype='pdf')
    for pagina in documento[:MAX_PAGINAS_IMAGEN]:
        pixmap = pagina.get_pixmap(dpi=150)
        imagenes.append(base64.b64encode(pixmap.tobytes('png')).decode('ascii'))
    documento.close()
    return None, imagenes


def _leer_documento(extraccion):
    nombre = extraccion.nombre_archivo_original or extraccion.archivo.name
    extension = nombre.rsplit('.', 1)[-1].lower() if '.' in nombre else ''

    extraccion.archivo.open('rb')
    try:
        if extension == 'docx':
            return _extraer_texto_docx(extraccion.archivo), None
        if extension == 'pdf':
            return _extraer_texto_o_imagenes_pdf(extraccion.archivo)
        raise ValueError(f'Formato de archivo no soportado: .{extension} (solo .pdf o .docx).')
    finally:
        extraccion.archivo.close()


def _construir_payload_esquema(momento):
    preguntas = []
    for pregunta in momento.preguntas.filter(activa=True).order_by('orden'):
        preguntas.append({
            'id': pregunta.id,
            'texto': pregunta.texto,
            'tipo': pregunta.tipo,
            'opciones': [{'id': o.id, 'texto': o.texto} for o in pregunta.opciones.all()],
        })
    return {'momento': momento.titulo, 'preguntas': preguntas}


def _llamar_openai_extraccion(esquema, texto_documento=None, imagenes_base64=None):
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None, 'OPENAI_API_KEY no está configurada en el entorno del servidor (.env).'

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
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
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
            resultado['texto'] = respuesta.choices[0].message.content.strip()
        except Exception as exc:  # noqa: BLE001
            resultado['error'] = str(exc)

    hilo = threading.Thread(target=_run, daemon=True)
    hilo.start()
    hilo.join(timeout=GENERATION_TIMEOUT_SECONDS)

    if hilo.is_alive():
        return None, f'Tiempo de espera agotado ({GENERATION_TIMEOUT_SECONDS}s) esperando a OpenAI.'
    if resultado.get('error'):
        return None, resultado['error']
    texto = resultado.get('texto')
    if not texto:
        return None, 'OpenAI no devolvió contenido.'
    try:
        return json.loads(texto), None
    except json.JSONDecodeError as exc:
        return None, f'OpenAI devolvió JSON inválido: {exc}'


def _limpiar_y_validar(resultado_crudo, momento):
    """Descarta cualquier entrada que no pase la misma validación por tipo que ya usa el envío
    normal (participantes.views._validar_entrada) — a diferencia de ese endpoint, NO aborta todo
    si una entrada falla, solo la omite (queda en preguntas_omitidas). No escribe Respuesta acá —
    solo deja `resultado` listo para que aprobar_extraccion_momento lo escriba después."""
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
        try:
            _validar_entrada(pregunta, texto_libre, opciones)
        except Exception:  # noqa: BLE001 — ValidationError u otra inconsistencia de la IA
            omitidas.append(pregunta.id)
            continue
        limpio.append({'pregunta': pregunta.id, 'texto_libre': texto_libre, 'opcion_ids': [o.id for o in opciones]})

    return {'respuestas': limpio}, omitidas


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
        esquema = _construir_payload_esquema(extraccion.momento)
        resultado, error = _llamar_openai_extraccion(esquema, texto_documento=texto, imagenes_base64=imagenes)

        if resultado is None:
            extraccion.estado = ExtraccionMomento.ESTADO_ERROR
            extraccion.error_mensaje = error or 'Error desconocido generando la extracción.'
            extraccion.save(update_fields=['estado', 'error_mensaje'])
            return

        limpio, omitidas = _limpiar_y_validar(resultado, extraccion.momento)

        extraccion.resultado = limpio
        extraccion.preguntas_omitidas = omitidas
        extraccion.estado = ExtraccionMomento.ESTADO_COMPLETO
        extraccion.error_mensaje = ''
        extraccion.modelo_usado = MODELO_USADO_LABEL
        extraccion.completado_en = timezone.now()
        extraccion.save(update_fields=[
            'resultado', 'preguntas_omitidas', 'estado', 'error_mensaje', 'modelo_usado', 'completado_en',
        ])
    except Exception as exc:  # noqa: BLE001
        if extraccion is not None:
            extraccion.estado = ExtraccionMomento.ESTADO_ERROR
            extraccion.error_mensaje = str(exc)
            extraccion.save(update_fields=['estado', 'error_mensaje'])
    finally:
        close_old_connections()


def aprobar_extraccion_momento(extraccion, aprobado_por):
    """Escribe `extraccion.resultado` como Respuesta reales del participante — mismo lookup/save
    que RespuestasMomentoView.post() (participante individual, registrado_por=el mismo
    participante). Solo llamable sobre una extracción en estado completo y no aprobada aún (ver
    la vista para esas guardas)."""
    from django.utils import timezone as tz

    from jornadas.models import Pregunta

    from .models import Respuesta

    preguntas = {p.id: p for p in Pregunta.objects.filter(momento=extraccion.momento)}
    guardadas = []
    for item in extraccion.resultado.get('respuestas') or []:
        pregunta = preguntas.get(item['pregunta'])
        if pregunta is None:
            continue
        respuesta, _ = Respuesta.objects.update_or_create(
            pregunta=pregunta, participante=extraccion.participante,
            defaults={'texto_libre': item.get('texto_libre', ''), 'registrado_por': extraccion.participante},
        )
        respuesta.opciones.set(item.get('opcion_ids') or [])
        guardadas.append(respuesta)

    extraccion.aprobado_en = tz.now()
    extraccion.aprobado_por = aprobado_por
    extraccion.save(update_fields=['aprobado_en', 'aprobado_por'])
    return guardadas
