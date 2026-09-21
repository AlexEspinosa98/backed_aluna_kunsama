"""Diseño de presentación con IA a partir de los assets de la jornada
(docs/HU_BACKEND_DISENO_PRESENTACION.md) — construcción de mensajes, llamada síncrona a OpenAI
con visión y saneamiento de la respuesta antes de guardarla. La vista (`PresentacionDisenoViewSet`
en `admin_views.py`) solo resuelve la fuente, valida forma y delega acá todo lo demás.

A diferencia de `analitica/v2/llm.py` (análisis, asíncrono en un hilo) esta llamada es SÍNCRONA
por diseño de la HU: el usuario pulsa «Diagramar con IA» y espera entre 7 y 20 segundos, no hay
polling. Cualquier fallo se propaga como `ErrorGeneracionDiseno`, con el código HTTP exacto que
pide la sección 2.3 de la HU — así la vista solo necesita un único `except`.
"""
import base64
import json
import os
import re

from jornadas.models import JornadaAsset

VERSION_PRESENTACION = 'kunsamu.presentacion/v1'

TIPOS_DIAPOSITIVA_VALIDOS = frozenset({
    'portada', 'cobertura', 'resumen', 'hallazgo', 'recomendaciones', 'limitaciones', 'cierre',
})

# --- assets e imágenes (HU §5.1) -------------------------------------------------------------

MAX_IMAGENES_ADJUNTAS = 6
MAX_TAMANO_IMAGEN_BYTES = 4 * 1024 * 1024
# El mime se detecta con PIL a partir de los BYTES reales, nunca de la extensión del nombre de
# archivo — un .png renombrado a .jpg (o viceversa) no debe colarse como si fuera el formato que
# dice su nombre. PDF y SVG quedan fuera a propósito (HU §5.1: se mencionan por nombre, pero
# nunca se adjuntan como imagen).
MIME_POR_FORMATO_PIL = {
    'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp', 'GIF': 'image/gif',
}


def _mime_real(asset):
    """Mime real de la imagen de este asset (detectado con PIL) o `None` si no es adjuntable
    (no es imagen, o PIL no puede abrirla — ej. un PDF o un SVG)."""
    if not asset.archivo:
        return None
    try:
        from PIL import Image

        asset.archivo.open('rb')
        try:
            formato = Image.open(asset.archivo).format
        finally:
            asset.archivo.close()
    except Exception:  # noqa: BLE001 — un archivo ilegible simplemente no es adjuntable
        return None
    return MIME_POR_FORMATO_PIL.get(formato)


def _nombre_asset(asset):
    if asset.nombre_archivo_original:
        return asset.nombre_archivo_original
    if asset.archivo:
        return asset.archivo.name.rsplit('/', 1)[-1]
    if asset.tipo == JornadaAsset.TIPO_SYSTEM_DESIGN:
        return 'Guía de marca'
    return f'Asset {asset.id}'


def _reunir_assets(jornada):
    """(resumen, imagenes) — `resumen` es una entrada por CADA asset de la jornada (id como
    texto, tipo, nombre, texto de marca si aplica, si se le adjuntó imagen), en el mismo orden
    del queryset (`JornadaAsset.Meta.ordering = ['-creado_en']`, ya del más reciente al más
    antiguo). `imagenes` es `[(id_texto, mime, bytes)]`, como máximo `MAX_IMAGENES_ADJUNTAS`,
    cada una ≤ `MAX_TAMANO_IMAGEN_BYTES` y con mime real png/jpeg/webp/gif."""
    resumen = []
    imagenes = []
    for asset in jornada.assets.all():
        id_texto = str(asset.id)
        es_marca_con_texto = asset.tipo == JornadaAsset.TIPO_SYSTEM_DESIGN and asset.texto
        texto = asset.texto if es_marca_con_texto else None
        imagen_adjunta = False
        if len(imagenes) < MAX_IMAGENES_ADJUNTAS and asset.archivo:
            try:
                cabe = asset.archivo.size <= MAX_TAMANO_IMAGEN_BYTES
            except Exception:  # noqa: BLE001 — archivo roto o inaccesible: no se adjunta
                cabe = False
            if cabe:
                mime = _mime_real(asset)
                if mime:
                    try:
                        asset.archivo.open('rb')
                        try:
                            contenido = asset.archivo.read()
                        finally:
                            asset.archivo.close()
                    except Exception:  # noqa: BLE001 — un asset puntual no debe tumbar el resto
                        contenido = None
                    if contenido:
                        imagenes.append((id_texto, mime, contenido))
                        imagen_adjunta = True
        resumen.append({
            'id': id_texto, 'tipo': asset.tipo, 'nombre': _nombre_asset(asset),
            'texto': texto, 'imagen_adjunta': imagen_adjunta,
        })
    return resumen, imagenes


# --- errores ------------------------------------------------------------------------------

class ErrorGeneracionDiseno(Exception):
    """`status_code`/`detail` son exactamente el código y el cuerpo que la vista debe responder
    (HU §2.3) — un único `except` en la vista basta para cualquier fallo de esta capa."""
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


# --- system prompt, literal (HU §6) --------------------------------------------------------
# Reconstruido línea a línea contra el bloque ```text de la HU (cada línea del markdown es un
# párrafo/viñeta completo, sin saltos internos) — se listan acá tal cual y se unen con '\n'
# para reproducir el texto exacto sin salirse de 100 caracteres por línea de código. Una línea
# vacía en la lista reproduce la línea en blanco entre párrafos del original.
_LINEAS_SYSTEM_PROMPT = [
    'Eres el director de arte de Kunsamu, la plataforma de análisis participativo de Aluna I.A. '
    '(Universidad del Magdalena). Diagramas la presentación con la que un equipo proyecta ante '
    'directivos y comunidades los resultados de una jornada. Recibes: el contexto de la '
    'jornada, un resumen del análisis, la lista de diapositivas ya definida (id, tipo y '
    'contenido disponible) y los assets visuales de la jornada, cada uno como imagen adjunta '
    'precedida de su id, más la guía de marca escrita si existe. Devuelves únicamente un JSON '
    'conforme al esquema kunsamu.presentacion/v1.',
    '',
    '## Cómo se tratan los assets (regla central)',
    '',
    'Los assets acompañan la identidad visual de la jornada. Se muestran siempre completos: sin '
    'recortar, sin estirar, sin marco, sin tarjeta, sin sombra, sin velo de color y nunca como '
    'fondo a sangre. El frontend los coloca enteros, con aire, al lado del texto o en una '
    'esquina; tú decides cuál va dónde. Hay tres papeles:',
    '- "logo" (el principal) o "logo_secundario": imagotipo, wordmark, escudo, lettering. Va '
    'pequeño en una esquina de todas las diapositivas y, en la portada sin ilustración, grande '
    'junto al título.',
    '- "ilustracion": una figura, ilustración, fotografía o pieza gráfica que acompaña la '
    'identidad (un animal, un objeto, un paisaje, un patrón con motivo claro). Va entera al '
    'lado del texto en portada, resumen y cierre, ocupando cerca de la mitad de la diapositiva. '
    'Si la imagen tiene fondo opaco (crema, blanco, un color plano), indica ese color exacto en '
    '"fondo_recomendado": la diapositiva lo adopta y la imagen se funde sin bordes; si el fondo '
    'es transparente, "fondo_recomendado" es null.',
    '- "no_usar": lo que no aporta (borroso, duplicado, captura de pantalla, documento, la guía '
    'de marca en imagen, un asset con texto pequeño incrustado). Es válido no usar la mayoría; '
    'usa sólo lo que mejora la presentación.',
    '',
    '## Qué decides',
    '',
    '1. Tema: estilo, siete colores, tipografía y fondo. Los colores salen de la guía de marca '
    'si trae códigos; si no, de los colores reales de los assets (logo primero, ilustraciones '
    'después); si no hay nada, elige una paleta sobria institucional (azules profundos con un '
    'acento cálido). Si las ilustraciones tienen fondo opaco, elige como "fondo" del tema ese '
    'mismo color o uno muy cercano, para que toda la presentación se sienta continua. Contraste '
    'mínimo 4.5:1 entre texto y fondo, y entre texto y superficie. El fondo y la superficie '
    'siempre claros: encima van gráficas con sus propios colores de datos. Tipografía: serif en '
    'títulos para lo editorial e institucional; sans para jornadas tecnológicas, juveniles o '
    'dinámicas. Fondo: halos para lo institucional, plano para lo sobrio (y siempre que haya '
    'ilustraciones con fondo opaco), gradiente sólo si la marca es vibrante.',
    '',
    '2. Assets, uno por uno, mirando la imagen: rol, fondo recomendado y una nota con lo que '
    'viste y por qué le diste ese papel.',
    '',
    '3. Logo global: el asset con rol "logo" y su esquina. Sin logo, asset_id null.',
    '',
    '4. Diapositivas: para cada id de la lista, una plantilla admisible por su tipo, un acento '
    'opcional, la ilustración que la acompaña y el lado en que va.',
    '- portada: "portada_ilustracion" si hay una ilustración; si no, "portada_color". Elige '
    '"lado_imagen" según la composición de la figura (una figura que cuelga o mira hacia la '
    'izquierda suele ir a la derecha del título).',
    '- resumen: "resumen_ilustracion" con una segunda ilustración distinta de la de portada; '
    'con una sola ilustración, "resumen" sin imagen para no repetirla en diapositivas seguidas.',
    '- hallazgo con visualización: alterna "hallazgo_visual" y "hallazgo_visual_invertido" para '
    'que no se vean todas iguales. Sin visualización pero con citas: "hallazgo_cita". Sin '
    'visualización ni citas: "hallazgo_texto". Un hallazgo nunca lleva ilustración ni logo '
    'dentro del contenido.',
    '- cobertura, recomendaciones y limitaciones tienen una sola plantilla.',
    '- cierre: "cierre_ilustracion" (puede repetir la de portada, invirtiendo el lado) o '
    '"cierre_color".',
    '- acento: puedes rotar entre primario, secundario y acento del tema para distinguir '
    'hallazgos; nunca un color que no esté en el tema.',
    '- mostrar_logo: true en todas si hay logo; los fondos son siempre claros y el logo se lee '
    'bien. El frontend ya lo omite en "portada_color", donde el logo va grande junto al título.',
    '',
    '## Reglas que no se negocian',
    '- Usa sólo los ids de assets y de diapositivas recibidos; no inventes ni omitas '
    'diapositivas.',
    '- No escribas texto para las diapositivas: el contenido ya existe. Sólo diseñas.',
    '- Sobrio antes que llamativo: es un informe de decisiones, no publicidad. Variedad con '
    'criterio, no caos.',
    '- Explica en "justificacion" (una o dos frases) de dónde salieron los colores y por qué '
    'esa tipografía.',
    '- Responde sólo con el JSON.',
]
SYSTEM_PROMPT = '\n'.join(_LINEAS_SYSTEM_PROMPT)


# --- esquema JSON estricto (HU §7) ---------------------------------------------------------

_HEX = '^#[0-9a-fA-F]{6}$'

JSON_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['version', 'tema', 'logo', 'assets', 'diapositivas'],
    'properties': {
        'version': {'type': 'string', 'enum': [VERSION_PRESENTACION]},
        'tema': {
            'type': 'object',
            'additionalProperties': False,
            'required': ['estilo', 'colores', 'tipografia', 'fondo', 'justificacion'],
            'properties': {
                'estilo': {
                    'type': 'string',
                    'enum': ['institucional', 'editorial', 'sobrio', 'vibrante'],
                },
                'colores': {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': [
                        'primario', 'secundario', 'acento', 'fondo', 'superficie', 'texto',
                        'texto_suave',
                    ],
                    'properties': {
                        'primario': {'type': 'string', 'pattern': _HEX},
                        'secundario': {'type': 'string', 'pattern': _HEX},
                        'acento': {'type': 'string', 'pattern': _HEX},
                        'fondo': {'type': 'string', 'pattern': _HEX},
                        'superficie': {'type': 'string', 'pattern': _HEX},
                        'texto': {'type': 'string', 'pattern': _HEX},
                        'texto_suave': {'type': 'string', 'pattern': _HEX},
                    },
                },
                'tipografia': {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': ['titulos', 'cuerpo'],
                    'properties': {
                        'titulos': {'type': 'string', 'enum': ['serif', 'sans']},
                        'cuerpo': {'type': 'string', 'enum': ['sans', 'serif']},
                    },
                },
                'fondo': {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': ['tipo', 'colores'],
                    'properties': {
                        'tipo': {'type': 'string', 'enum': ['halos', 'plano', 'gradiente']},
                        'colores': {
                            'type': 'array',
                            'items': {'type': 'string', 'pattern': _HEX},
                        },
                    },
                },
                'justificacion': {'type': 'string'},
            },
        },
        'logo': {
            'type': 'object',
            'additionalProperties': False,
            'required': ['asset_id', 'posicion'],
            'properties': {
                'asset_id': {'type': ['string', 'null']},
                'posicion': {
                    'type': 'string',
                    'enum': [
                        'superior_izquierda', 'superior_derecha', 'inferior_izquierda',
                        'inferior_derecha',
                    ],
                },
            },
        },
        'assets': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['id', 'rol', 'fondo_recomendado', 'notas'],
                'properties': {
                    'id': {'type': 'string'},
                    'rol': {
                        'type': 'string',
                        'enum': ['logo', 'logo_secundario', 'ilustracion', 'no_usar'],
                    },
                    'fondo_recomendado': {'type': ['string', 'null'], 'pattern': _HEX},
                    'notas': {'type': 'string'},
                },
            },
        },
        'diapositivas': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': [
                    'id', 'plantilla', 'acento', 'asset_id', 'lado_imagen', 'mostrar_logo',
                ],
                'properties': {
                    'id': {'type': 'string'},
                    'plantilla': {
                        'type': 'string',
                        'enum': [
                            'portada_ilustracion', 'portada_color', 'cobertura', 'resumen',
                            'resumen_ilustracion', 'hallazgo_visual',
                            'hallazgo_visual_invertido', 'hallazgo_texto', 'hallazgo_cita',
                            'recomendaciones', 'limitaciones', 'cierre_ilustracion',
                            'cierre_color',
                        ],
                    },
                    'acento': {'type': ['string', 'null'], 'pattern': _HEX},
                    'asset_id': {'type': ['string', 'null']},
                    'lado_imagen': {'type': 'string', 'enum': ['izquierda', 'derecha']},
                    'mostrar_logo': {'type': 'boolean'},
                },
            },
        },
    },
}


# --- llamada a OpenAI (HU §5.4) ------------------------------------------------------------

MODELO_FALLBACK_1 = 'gpt-5.1'
MODELO_FALLBACK_2 = 'gpt-4.1'
TIMEOUT_SEGUNDOS = 60
MAX_COMPLETION_TOKENS = 6000
NOMBRE_ESQUEMA = 'kunsamu_presentacion_v1'


def _cascada_modelos():
    """[`KUNSAMU_DESIGN_MODEL` (si está definido), 'gpt-5.1', 'gpt-4.1'] sin duplicados —
    HU §5.4."""
    configurado = os.environ.get('KUNSAMU_DESIGN_MODEL')
    modelos = [configurado] if configurado else []
    for modelo in (MODELO_FALLBACK_1, MODELO_FALLBACK_2):
        if modelo not in modelos:
            modelos.append(modelo)
    return modelos


def _es_error_de_modelo_no_disponible(exc):
    """True si el proveedor respondió un 4xx que menciona "model" — la señal de que ESE modelo
    puntual no está disponible para la clave (HU §5.4), y no un problema de la solicitud en sí
    (payload, esquema, etc.), que sí debe cortar con 502 sin seguir probando modelos."""
    status_code = getattr(exc, 'status_code', None)
    return status_code is not None and 400 <= status_code < 500 and 'model' in str(exc).lower()


def llamar_openai_presentacion(mensajes):
    """(diseno_bruto, modelo_usado) tras probar la cascada de modelos. Nunca devuelve un error:
    ante cualquier fallo levanta `ErrorGeneracionDiseno` con el código HTTP de la HU (§2.3/§5.4).
    Llamada síncrona (sin hilo) — la HU pide que el `POST` tarde lo que tarde el proveedor."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise ErrorGeneracionDiseno(503, 'Falta OPENAI_API_KEY')

    from openai import OpenAI

    cliente = OpenAI(api_key=api_key, timeout=TIMEOUT_SEGUNDOS)
    formato = {
        'type': 'json_schema',
        'json_schema': {'name': NOMBRE_ESQUEMA, 'strict': True, 'schema': JSON_SCHEMA},
    }

    ultimo_error = None
    for modelo in _cascada_modelos():
        try:
            respuesta = cliente.chat.completions.create(
                model=modelo, messages=mensajes, response_format=formato,
                max_completion_tokens=MAX_COMPLETION_TOKENS,
            )
        except Exception as exc:  # noqa: BLE001 — se decide abajo si se prueba otro modelo
            if _es_error_de_modelo_no_disponible(exc):
                ultimo_error = exc
                continue
            raise ErrorGeneracionDiseno(502, str(exc)) from exc

        opcion = respuesta.choices[0]
        refusal = getattr(opcion.message, 'refusal', None)
        if refusal:
            raise ErrorGeneracionDiseno(502, f'El proveedor rechazó la solicitud: {refusal}')
        if opcion.finish_reason != 'stop':
            raise ErrorGeneracionDiseno(
                502,
                f'La respuesta no terminó completa (finish_reason={opcion.finish_reason}).',
            )
        try:
            diseno_bruto = json.loads(opcion.message.content or '')
        except ValueError as exc:  # json.JSONDecodeError es subclase de ValueError
            raise ErrorGeneracionDiseno(
                502, f'El proveedor devolvió JSON inválido: {exc}',
            ) from exc
        return diseno_bruto, modelo

    raise ErrorGeneracionDiseno(
        502, f'Ningún modelo de la cascada está disponible para esta clave: {ultimo_error}',
    )


# --- saneamiento (HU §8) --------------------------------------------------------------------

_HEX_RE = re.compile(_HEX)

RESPALDO_INSTITUCIONAL = {
    'colores': {
        'primario': '#033659', 'secundario': '#0f3c5f', 'acento': '#2fc2d6',
        'fondo': '#fbfcfd', 'superficie': '#ffffff', 'texto': '#0f3c5f', 'texto_suave': '#64748b',
    },
    'tipografia': {'titulos': 'serif', 'cuerpo': 'sans'},
    'fondo_tipo': 'halos',
}

PLANTILLAS_POR_TIPO = {
    'portada': {'portada_ilustracion', 'portada_color'},
    'cobertura': {'cobertura'},
    'resumen': {'resumen', 'resumen_ilustracion'},
    'hallazgo': {'hallazgo_visual', 'hallazgo_visual_invertido', 'hallazgo_cita', 'hallazgo_texto'},
    'recomendaciones': {'recomendaciones'},
    'limitaciones': {'limitaciones'},
    'cierre': {'cierre_ilustracion', 'cierre_color'},
}
PLANTILLA_UNICA_POR_TIPO = {
    'cobertura': 'cobertura', 'recomendaciones': 'recomendaciones', 'limitaciones': 'limitaciones',
}
PLANTILLAS_CON_ILUSTRACION = {'portada_ilustracion', 'resumen_ilustracion', 'cierre_ilustracion'}
PLANTILLAS_HALLAZGO_VISUAL = {'hallazgo_visual', 'hallazgo_visual_invertido'}
# Plantilla sin imagen a la que cae cada plantilla "_ilustracion" cuando no hay ninguna
# ilustración disponible (HU §8.4, último punto de la viñeta de plantillas _ilustracion).
PLANTILLA_SIN_IMAGEN = {
    'portada_ilustracion': 'portada_color',
    'resumen_ilustracion': 'resumen',
    'cierre_ilustracion': 'cierre_color',
}


def _es_hex_valido(valor):
    return isinstance(valor, str) and bool(_HEX_RE.match(valor))


def _luminancia(color_hex):
    """Luminancia relativa WCAG sobre sRGB linealizado (HU §8, «claro» = luminancia ≥ 0.5)."""
    color_hex = color_hex.lstrip('#')
    canales = (int(color_hex[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def _linealizar(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (_linealizar(c) for c in canales)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _hex_o_institucional(valor, clave, correcciones):
    if _es_hex_valido(valor):
        return valor
    correcciones.append(f'color {clave} inválido; se usa el institucional')
    return RESPALDO_INSTITUCIONAL['colores'][clave]


def _sanear_tema(tema):
    correcciones = []
    if not isinstance(tema, dict):
        tema = {}

    colores_entrada = tema.get('colores') if isinstance(tema.get('colores'), dict) else {}
    colores = {
        clave: _hex_o_institucional(colores_entrada.get(clave), clave, correcciones)
        for clave in RESPALDO_INSTITUCIONAL['colores']
    }

    if _luminancia(colores['fondo']) < 0.5:
        colores['fondo'] = RESPALDO_INSTITUCIONAL['colores']['fondo']
        colores['superficie'] = RESPALDO_INSTITUCIONAL['colores']['superficie']
        correcciones.append(
            'el fondo era oscuro; se aclara para mantener legibilidad de gráficas'
        )
    # A partir de acá el fondo SIEMPRE es claro (se acaba de forzar arriba si no lo era), así
    # que la condición «si el fondo es claro» del §8.1 queda cubierta sin chequeo adicional.
    if _luminancia(colores['texto']) > 0.35:
        colores['texto'] = RESPALDO_INSTITUCIONAL['colores']['texto']
        correcciones.append('texto poco legible sobre el fondo; se oscurece')

    estilo = tema.get('estilo')
    if estilo not in ('institucional', 'editorial', 'sobrio', 'vibrante'):
        estilo = 'institucional'

    tipografia_entrada = tema.get('tipografia') if isinstance(tema.get('tipografia'), dict) else {}
    titulos = tipografia_entrada.get('titulos')
    if titulos not in ('serif', 'sans'):
        titulos = RESPALDO_INSTITUCIONAL['tipografia']['titulos']
    cuerpo = tipografia_entrada.get('cuerpo')
    if cuerpo not in ('sans', 'serif'):
        cuerpo = RESPALDO_INSTITUCIONAL['tipografia']['cuerpo']

    fondo_entrada = tema.get('fondo') if isinstance(tema.get('fondo'), dict) else {}
    tipo_fondo = fondo_entrada.get('tipo')
    if tipo_fondo not in ('halos', 'plano', 'gradiente'):
        tipo_fondo = RESPALDO_INSTITUCIONAL['fondo_tipo']
    colores_fondo_entrada = fondo_entrada.get('colores')
    colores_fondo_entrada = colores_fondo_entrada if isinstance(colores_fondo_entrada, list) else []
    colores_fondo = [c for c in colores_fondo_entrada if _es_hex_valido(c)][:2]
    if not colores_fondo:
        colores_fondo = [colores['acento'], colores['secundario']]

    justificacion = tema.get('justificacion')
    if not isinstance(justificacion, str):
        justificacion = ''

    tema_saneado = {
        'estilo': estilo, 'colores': colores,
        'tipografia': {'titulos': titulos, 'cuerpo': cuerpo},
        'fondo': {'tipo': tipo_fondo, 'colores': colores_fondo},
        'justificacion': justificacion,
    }
    return tema_saneado, correcciones


def _sanear_assets(assets_modelo, ids_jornada_ordenados):
    """`ids_jornada_ordenados`: ids (texto) de TODOS los `JornadaAsset` de la jornada, del más
    reciente al más antiguo (HU §8.2). Devuelve (assets_saneados, correcciones)."""
    correcciones = []
    if not isinstance(assets_modelo, list):
        assets_modelo = []

    vistos = set()
    saneados = []
    for entrada in assets_modelo:
        if not isinstance(entrada, dict):
            continue
        id_asset = entrada.get('id')
        if id_asset not in ids_jornada_ordenados:
            correcciones.append(f'asset desconocido descartado: {id_asset}')
            continue
        if id_asset in vistos:
            continue  # duplicado: se conserva la primera aparición
        vistos.add(id_asset)

        rol = entrada.get('rol')
        if rol not in ('logo', 'logo_secundario', 'ilustracion', 'no_usar'):
            rol = 'no_usar'

        fondo_recomendado = entrada.get('fondo_recomendado')
        if fondo_recomendado is not None:
            if not _es_hex_valido(fondo_recomendado):
                fondo_recomendado = None
            elif _luminancia(fondo_recomendado) < 0.5:
                correcciones.append(f'fondo recomendado oscuro para {id_asset}; se ignora')
                fondo_recomendado = None

        notas = entrada.get('notas')
        if not isinstance(notas, str):
            notas = ''

        saneados.append({
            'id': id_asset, 'rol': rol, 'fondo_recomendado': fondo_recomendado, 'notas': notas,
        })

    # Assets de la jornada que el modelo no mencionó → se añaden como no_usar (HU §8.2).
    for id_asset in ids_jornada_ordenados:
        if id_asset not in vistos:
            saneados.append({
                'id': id_asset, 'rol': 'no_usar', 'fondo_recomendado': None, 'notas': '',
            })
            vistos.add(id_asset)

    return saneados, correcciones


def _sanear_logo(logo_modelo, assets_saneados):
    correcciones = []
    if not isinstance(logo_modelo, dict):
        logo_modelo = {}

    roles_por_id = {a['id']: a['rol'] for a in assets_saneados}
    asset_id = logo_modelo.get('asset_id')
    if asset_id is not None and roles_por_id.get(asset_id) not in ('logo', 'logo_secundario'):
        correcciones.append('el asset elegido como logo no tiene rol de logo; se omite')
        asset_id = None
    if asset_id is None:
        primer_logo = next((a['id'] for a in assets_saneados if a['rol'] == 'logo'), None)
        if primer_logo is not None:
            asset_id = primer_logo

    posicion = logo_modelo.get('posicion')
    if posicion not in (
        'superior_izquierda', 'superior_derecha', 'inferior_izquierda', 'inferior_derecha',
    ):
        posicion = 'superior_derecha'

    return {'asset_id': asset_id, 'posicion': posicion}, correcciones


def _plantilla_por_defecto(item_entrada):
    tipo = item_entrada.get('tipo')
    if tipo == 'portada':
        return 'portada_color'
    if tipo == 'resumen':
        return 'resumen'
    if tipo == 'hallazgo':
        if item_entrada.get('tiene_visual'):
            return 'hallazgo_visual'
        if item_entrada.get('tiene_citas'):
            return 'hallazgo_cita'
        return 'hallazgo_texto'
    if tipo == 'cierre':
        return 'cierre_color'
    return PLANTILLA_UNICA_POR_TIPO.get(tipo)


def _sanear_diapositivas(diapositivas_entrada, diapositivas_modelo, assets_saneados):
    """Recorre SIEMPRE `diapositivas_entrada` (la secuencia recibida en el POST), nunca la del
    modelo — ids que el modelo inventó se ignoran solos al no buscarse nunca (HU §8.4)."""
    correcciones = []
    por_id_modelo = {
        item.get('id'): item for item in (diapositivas_modelo or []) if isinstance(item, dict)
    }
    ilustraciones_disponibles = [a['id'] for a in assets_saneados if a['rol'] == 'ilustracion']
    hay_logo = any(a['rol'] == 'logo' for a in assets_saneados)

    resultado = []
    ilustracion_anterior = None
    for item_entrada in diapositivas_entrada:
        id_slide = item_entrada.get('id')
        tipo = item_entrada.get('tipo')
        modelo_item = por_id_modelo.get(id_slide) or {}
        defecto = _plantilla_por_defecto(item_entrada)

        plantilla = modelo_item.get('plantilla')
        if plantilla not in PLANTILLAS_POR_TIPO.get(tipo, set()):
            if plantilla is not None:
                correcciones.append(f'plantilla {plantilla} no aplica a {tipo}')
            plantilla = defecto

        if tipo == 'hallazgo':
            if plantilla in PLANTILLAS_HALLAZGO_VISUAL and not item_entrada.get('tiene_visual'):
                plantilla = 'hallazgo_cita' if item_entrada.get('tiene_citas') else 'hallazgo_texto'
                # El texto nombra la plantilla que quedó de verdad: la corrección se le muestra a
                # quien pidió el diseño, y decir "de texto" cuando terminó en cita confunde.
                cual = 'de cita' if plantilla == 'hallazgo_cita' else 'de texto'
                correcciones.append(f'hallazgo {id_slide} sin visualización; plantilla {cual}')
            elif plantilla == 'hallazgo_cita' and not item_entrada.get('tiene_citas'):
                plantilla = 'hallazgo_texto'
                correcciones.append(f'hallazgo {id_slide} sin citas; plantilla de texto')

        asset_id = None
        if plantilla in PLANTILLAS_CON_ILUSTRACION:
            candidato = modelo_item.get('asset_id')
            candidato_valido = candidato is not None and any(
                a['id'] == candidato and a['rol'] == 'ilustracion' for a in assets_saneados
            )
            if candidato is not None and not candidato_valido:
                correcciones.append(f'{candidato} no es una ilustración; no se usa en {id_slide}')

            if candidato_valido:
                asset_id = candidato
            elif ilustraciones_disponibles:
                distintas = [i for i in ilustraciones_disponibles if i != ilustracion_anterior]
                asset_id = distintas[0] if distintas else ilustraciones_disponibles[0]
            else:
                plantilla_previa = plantilla
                plantilla = PLANTILLA_SIN_IMAGEN[plantilla]
                correcciones.append(f'sin ilustración para {plantilla_previa}; se usa {plantilla}')

            if asset_id is not None:
                ilustracion_anterior = asset_id
        # Cualquier otra plantilla: asset_id se queda en None siempre (HU §8.4, último punto —
        # los hallazgos nunca llevan imagen).

        acento = modelo_item.get('acento')
        if not _es_hex_valido(acento):
            acento = None

        lado_imagen = modelo_item.get('lado_imagen')
        if lado_imagen not in ('izquierda', 'derecha'):
            lado_imagen = 'derecha'

        mostrar_logo = modelo_item.get('mostrar_logo')
        if not isinstance(mostrar_logo, bool):
            mostrar_logo = hay_logo

        resultado.append({
            'id': id_slide, 'plantilla': plantilla, 'acento': acento, 'asset_id': asset_id,
            'lado_imagen': lado_imagen, 'mostrar_logo': mostrar_logo,
        })
    return resultado, correcciones


def sanear_diseno(diseno_bruto, diapositivas_entrada, ids_jornada_ordenados):
    """(diseno_saneado, correcciones). El esquema estricto ya garantiza la forma en el caso
    normal; estas comprobaciones son la red de seguridad para cuando el proveedor no la respeta
    del todo (HU §8: «sólo se responde 502 si falta la forma base»)."""
    error_forma = 'La respuesta del modelo no tiene la forma esperada'
    if not isinstance(diseno_bruto, dict) or diseno_bruto.get('version') != VERSION_PRESENTACION:
        raise ErrorGeneracionDiseno(502, f'{error_forma} (version).')
    if not isinstance(diseno_bruto.get('tema'), dict):
        raise ErrorGeneracionDiseno(502, f'{error_forma} (tema).')
    if not isinstance(diseno_bruto.get('logo'), dict):
        raise ErrorGeneracionDiseno(502, f'{error_forma} (logo).')
    if not isinstance(diseno_bruto.get('assets'), list):
        raise ErrorGeneracionDiseno(502, f'{error_forma} (assets).')
    if not isinstance(diseno_bruto.get('diapositivas'), list):
        raise ErrorGeneracionDiseno(502, f'{error_forma} (diapositivas).')

    correcciones = []
    tema, correcciones_tema = _sanear_tema(diseno_bruto['tema'])
    correcciones += correcciones_tema
    assets, correcciones_assets = _sanear_assets(diseno_bruto['assets'], ids_jornada_ordenados)
    correcciones += correcciones_assets
    logo, correcciones_logo = _sanear_logo(diseno_bruto['logo'], assets)
    correcciones += correcciones_logo
    diapositivas, correcciones_slides = _sanear_diapositivas(
        diapositivas_entrada, diseno_bruto['diapositivas'], assets,
    )
    correcciones += correcciones_slides

    diseno = {
        'version': VERSION_PRESENTACION, 'tema': tema, 'logo': logo, 'assets': assets,
        'diapositivas': diapositivas,
    }
    return diseno, correcciones


# --- orquestación (HU §5) -------------------------------------------------------------------

def generar_diseno(jornada, contexto_analisis, diapositivas):
    """Orquesta la sección 5 completa de la HU: reúne assets/imágenes de la jornada, arma los
    mensajes, llama al modelo (con su cascada) y sanea la respuesta. Devuelve (diseno saneado,
    correcciones, modelo que respondió, ids de JornadaAsset "enviados" — los que aparecen en
    `diseno['assets']`, igual que en el ejemplo de la HU §2.2). Levanta `ErrorGeneracionDiseno`
    con el código HTTP correcto ante cualquier fallo; la vista solo necesita un `except`."""
    resumen_assets, imagenes = _reunir_assets(jornada)
    hay_imagen = any(a['imagen_adjunta'] for a in resumen_assets)
    hay_texto = any(a['texto'] for a in resumen_assets)
    if not hay_imagen and not hay_texto:
        raise ErrorGeneracionDiseno(422, 'La jornada no tiene assets ni guía de marca')

    bloque_json = {
        'jornada': {'nombre': jornada.nombre, 'descripcion': jornada.descripcion or ''},
        'analisis': contexto_analisis,
        'diapositivas': diapositivas,
        'assets': resumen_assets,
    }
    contenido_usuario = [{
        'type': 'text',
        'text': json.dumps(bloque_json, indent=2, ensure_ascii=False),
    }]
    for id_texto, mime, contenido in imagenes:
        b64 = base64.b64encode(contenido).decode('ascii')
        contenido_usuario.append({'type': 'text', 'text': f'Asset {id_texto}:'})
        contenido_usuario.append({
            'type': 'image_url',
            'image_url': {'url': f'data:{mime};base64,{b64}', 'detail': 'low'},
        })

    mensajes = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': contenido_usuario},
    ]

    diseno_bruto, modelo_usado = llamar_openai_presentacion(mensajes)
    ids_jornada_ordenados = [a['id'] for a in resumen_assets]
    diseno, correcciones = sanear_diseno(diseno_bruto, diapositivas, ids_jornada_ordenados)
    # HU §2.2: "assets son los ids de JornadaAsset que se enviaron al modelo" — el ejemplo de la
    # HU muestra exactamente los mismos ids que terminan en `diseno.assets` (el saneamiento ya
    # garantiza una entrada por cada asset real de la jornada), así que se derivan de ahí.
    ids_enviados = [int(a['id']) for a in diseno['assets']]
    return diseno, correcciones, modelo_usado, ids_enviados
