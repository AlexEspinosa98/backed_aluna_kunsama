"""Emparejar un responsable LEÍDO EN UN DOCUMENTO contra la gente que ya existe en la base.

Lo usan los dos extractores por IA (instrumentos.extraccion_ia_openai y
participantes.extraccion_momento_ia_openai): el documento diligenciado casi siempre trae al
principio quién lo llenó ("Responsable: …", "Diligenciado por: …"), así que la IA lo transcribe
y acá se decide a quién corresponde.

Dos decisiones de diseño que vale la pena no perder:

1. **El LLM lee, no decide.** Lo único que hace la IA es transcribir el nombre/correo tal como
   aparece; a quién corresponde se resuelve acá, con reglas determinísticas y reproducibles. Un
   modelo eligiendo entre personas reales es exactamente el tipo de decisión que no queremos que
   cambie entre corridas ni que dependa de qué tan convincente suene un nombre.

2. **Ante la duda, no se empareja.** Atribuirle el documento de un departamento a la persona
   equivocada es peor que dejarlo esperando asignación manual: la respuesta queda firmada por
   alguien que nunca la dio. Por eso hay un estado `ambiguo` propio — dos homónimos no se
   resuelven "por el primero", se devuelven sin emparejar para que lo decida una persona.

Funciones puras: no importan modelos ni tocan la base, reciben los candidatos ya resueltos por
el llamador (que es quien sabe si el conjunto correcto son los preregistrados de un instrumento
o los participantes de una jornada)."""
import unicodedata

# Sin emparejar todavía: no se intentó (el llamador ya traía el responsable dado a mano).
ESTADO_NO_BUSCADO = 'no_buscado'
# La IA no reportó ningún responsable en el documento.
ESTADO_SIN_DATO = 'sin_dato'
# Exactamente una persona coincide.
ESTADO_EMPAREJADO = 'emparejado'
# Coincide más de una y no hay forma de desempatar sin inventar un criterio.
ESTADO_AMBIGUO = 'ambiguo'
# Nadie coincide.
ESTADO_SIN_COINCIDENCIA = 'sin_coincidencia'

ESTADO_CHOICES = [
    (ESTADO_NO_BUSCADO, 'No se buscó (responsable indicado a mano)'),
    (ESTADO_SIN_DATO, 'El documento no traía responsable'),
    (ESTADO_EMPAREJADO, 'Emparejado con una persona'),
    (ESTADO_AMBIGUO, 'Ambiguo — varias personas coinciden'),
    (ESTADO_SIN_COINCIDENCIA, 'Sin coincidencia'),
]


def normalizar(texto):
    """Minúsculas, sin tildes, sin espacios de más. Lo que permite que "JOSÉ  PÉREZ " y
    "jose perez" se reconozcan como el mismo nombre — que es justo la diferencia entre cómo se
    escribe un nombre en un formulario de papel y cómo quedó registrado en el sistema."""
    if not texto:
        return ''
    sin_tildes = ''.join(
        caracter for caracter in unicodedata.normalize('NFD', str(texto))
        if unicodedata.category(caracter) != 'Mn'
    )
    return ' '.join(sin_tildes.lower().split())


def _tokens(texto):
    return set(normalizar(texto).split())


def emparejar(candidatos, nombre=None, correo=None):
    """Empareja contra una lista de `(objeto, nombre, correo)`.

    Devuelve `(objeto_o_None, estado)`. La escalera va de la señal más fuerte a la más débil y
    se corta en la primera que dé algo:

    1. **correo exacto** (sin distinguir mayúsculas) — es un identificador, no un parecido.
    2. **nombre normalizado idéntico**.
    3. **todos los tokens de uno contenidos en el otro** — cubre el caso real de que el documento
       diga "José Pérez" y el registro sea "José Antonio Pérez Gómez", o al revés.

    En los pasos 2 y 3, más de un candidato devuelve `ambiguo` y **ningún** objeto: desempatar
    tomando el primero sería atribuirle el documento a quien salió antes en la consulta.
    """
    if correo:
        correo_normalizado = normalizar(correo)
        coincidencias = [
            objeto for objeto, _nombre, correo_candidato in candidatos
            if correo_candidato and normalizar(correo_candidato) == correo_normalizado
        ]
        if len(coincidencias) == 1:
            return coincidencias[0], ESTADO_EMPAREJADO
        if len(coincidencias) > 1:
            return None, ESTADO_AMBIGUO

    if not normalizar(nombre):
        # Sin nombre utilizable: si tampoco hubo correo, es que el documento no traía responsable.
        return None, ESTADO_SIN_DATO if not correo else ESTADO_SIN_COINCIDENCIA

    nombre_normalizado = normalizar(nombre)
    exactos = [
        objeto for objeto, nombre_candidato, _correo in candidatos
        if normalizar(nombre_candidato) == nombre_normalizado
    ]
    if len(exactos) == 1:
        return exactos[0], ESTADO_EMPAREJADO
    if len(exactos) > 1:
        return None, ESTADO_AMBIGUO

    tokens_buscados = _tokens(nombre)
    parciales = []
    for objeto, nombre_candidato, _correo in candidatos:
        tokens_candidato = _tokens(nombre_candidato)
        if not tokens_candidato:
            continue
        if tokens_buscados <= tokens_candidato or tokens_candidato <= tokens_buscados:
            parciales.append(objeto)
    if len(parciales) == 1:
        return parciales[0], ESTADO_EMPAREJADO
    if len(parciales) > 1:
        return None, ESTADO_AMBIGUO

    return None, ESTADO_SIN_COINCIDENCIA
