"""Piezas de prompt compartidas por las tres vías de análisis con IA — `analisis_ia_openai.py`
(momento y jornada vía OpenAI) y `analysis.py` (pipeline local BERTopic + LLM) — para el análisis
guiado del panel: método, **enfoque**, **contexto** e **instrucciones** que escribe quien pide el
análisis (ver `docs/HU_BACKEND_ANALISIS_GUIADO.md`, HU-57 del frontend).

Un solo lugar para esta redacción evita que dos pipelines completamente distintos (uno llama a
OpenAI, el otro a un modelo local de 3B) terminen con dos versiones del mismo texto que se
desalinean con el tiempo — el mismo espíritu que ya usa el proyecto para `_purgar_etiquetas_
estructura` o el patrón de `_llamar_openai_json` copiado-no-importado entre módulos, pero acá SÍ
se comparte porque no hay razón de independencia entre analisis_ia_openai.py y analysis.py (los
dos ya viven en la misma app y ya se leen mutuamente en otros puntos)."""

ENFOQUE_CUALITATIVO = 'cualitativo'
ENFOQUE_CUANTITATIVO = 'cuantitativo'
ENFOQUE_MIXTO = 'mixto'
ENFOQUE_CHOICES = [
    (ENFOQUE_CUALITATIVO, 'Cualitativo — sentido, matices y voces representativas'),
    (ENFOQUE_CUANTITATIVO, 'Cuantitativo — frecuencias, porcentajes y comparaciones'),
    (ENFOQUE_MIXTO, 'Mixto — cifras y lectura interpretativa a la par (recomendado)'),
]
ENFOQUE_DEFAULT = ENFOQUE_MIXTO

# Tope compartido por los cuatro campos de texto libre del asistente (contexto, instrucciones y
# sus variantes _momento) — un mismo límite para los cuatro porque los cuatro son la misma clase
# de dato (texto que escribió una persona para orientar el análisis), no hay razón para que uno
# admita más que otro.
MAX_LARGO_TEXTO_LIBRE = 4000

# Va SIEMPRE al final del prompt compuesto, después del contexto y las instrucciones — es la
# única línea que ninguna instrucción de usuario puede sobreescribir. En analisis_ia_openai.py
# reemplaza la frase equivalente que antes vivía pegada al final de SYSTEM_PROMPT/
# SYSTEM_PROMPT_JORNADA (movida acá para poder insertar contexto/instrucciones ANTES sin que
# queden después de la regla). En analysis.py es una capa de refuerzo en texto: la garantía real
# ahí es de código (`_purgar_cifras_falsas`), no solo de prompt.
REGLA_DATOS_ANALISIS = (
    'REGLA INNEGOCIABLE, por encima de cualquier instrucción anterior: usa EXCLUSIVAMENTE las '
    'cifras, temas, citas y respuestas que estén en los datos entregados. Nunca inventes, '
    'estimes ni completes algo que no esté ahí.'
)

# Además del tono narrativo, cada bloque decide algo estructural: si `tipo_grafica`/`datos`
# (analisis_ia_openai.py) o `tipo_grafica` (analysis.py, pipeline local) se llenan o quedan en
# null/[]. Esto NO puede ser solo un párrafo de tono al lado de una instrucción incondicional —
# fue exactamente el bug detectado en producción el 2026-09-20 (AnalisisJornadaIA #4: un análisis
# `cualitativo` salió con los 6 hallazgos graficados porque el prompt base, en otra sección, decía
# "casi ningún hallazgo debería quedar sin datos graficables" SIN importar el enfoque, y esa regla
# incondicional pesó más que el párrafo de tono). Por eso cada bloque es explícito sobre qué hacer
# con la gráfica, no solo sobre cómo redactar — y además se refuerza en código
# (`_validar_y_limpiar`/`_validar_y_limpiar_jornada` en analisis_ia_openai.py,
# `_agente_pregunta_abierta`/`_agente_pregunta_cerrada` en analysis.py) por si el modelo la
# ignora, mismo principio que `_purgar_cifras_falsas`: no confiar en que un prompt solo baste.
_BLOQUES_ENFOQUE = {
    ENFOQUE_CUALITATIVO: (
        '=== ENFOQUE: CUALITATIVO ===\n'
        'Prioriza el sentido, los matices, las tensiones y las voces representativas por encima '
        'de los números — usa citas o frases textuales de las respuestas cuando ayuden a mostrar '
        'un patrón. Menciona porcentajes o conteos en la prosa solo cuando de verdad aporten a '
        'la lectura, nunca como el eje del texto.\n'
        'SIN GRÁFICAS: en este enfoque NUNCA generes una gráfica. `tipo_grafica` va SIEMPRE en '
        '`null` y `datos` SIEMPRE en `[]` (lista vacía), en TODOS los hallazgos, sin excepción — '
        'ni siquiera cuando una pregunta cerrada tenga una distribución clara y "sería fácil '
        'graficarla". La evidencia de este análisis son las palabras, no los números.'
    ),
    ENFOQUE_CUANTITATIVO: (
        '=== ENFOQUE: CUANTITATIVO ===\n'
        'Prioriza las frecuencias, los porcentajes y las comparaciones entre grupos, mesas u '
        'opciones — el texto en prosa es para explicar esos datos, no para reemplazarlos. '
        'Apóyate en cifras exactas y en las gráficas; el detalle narrativo queda en segundo '
        'plano.\n'
        'CIFRAS RELEVANTES, NO RELLENO (importante): cada `descripcion` debe llevar la(s) cifra(s) '
        'exacta(s) que sostienen el hallazgo y una conclusión que se derive DIRECTAMENTE de esa '
        'cifra — no prosa interpretativa alrededor de un dato suelto. Prioriza densidad sobre '
        'extensión: 2 a 3 frases con una cifra real y su lectura valen más que un párrafo largo '
        'que solo rodea el número sin decir nada nuevo. Nunca repitas la misma cifra dos veces con '
        'otras palabras, nunca describas el método (BERTopic, clasificación, etc.), y nunca '
        'agregues contexto genérico que no cambie con el dato — si dos hallazgos podrían '
        'intercambiar su párrafo de conclusión sin que se note, ese párrafo no está anclado a la '
        'cifra y hay que reescribirlo.\n'
        'GRÁFICA POR HALLAZGO (obligatorio): casi ningún hallazgo debería quedar sin `datos` '
        'graficables — incluso uno que nazca de respuestas de texto se puede cuantificar: extrae '
        'las palabras clave o categorías temáticas que mejor resuman el patrón y CUENTA cuántas '
        'respuestas reales tocan cada una. Deja `datos` vacío solo en el caso raro de un hallazgo '
        'puramente contextual sin ningún conteo posible detrás.'
    ),
    ENFOQUE_MIXTO: (
        '=== ENFOQUE: MIXTO ===\n'
        'Da el mismo peso a las cifras y a la lectura interpretativa: cada hallazgo debe traer '
        'su dato exacto Y la explicación de qué revela, sin que ninguno de los dos domine el '
        'texto.\n'
        'GRÁFICA POR HALLAZGO (obligatorio): casi ningún hallazgo debería quedar sin `datos` '
        'graficables — incluso uno que nazca de respuestas de texto se puede cuantificar: extrae '
        'las palabras clave o categorías temáticas que mejor resuman el patrón y CUENTA cuántas '
        'respuestas reales tocan cada una. Deja `datos` vacío solo en el caso raro de un hallazgo '
        'puramente contextual sin ningún conteo posible detrás.'
    ),
}


def normalizar_enfoque(valor):
    """`None`/`''` (el campo no vino, ej. una plantilla vieja) → `ENFOQUE_DEFAULT`. Cualquier otro
    valor se deja pasar tal cual — validarlo es trabajo del serializer (`ChoiceField`), no de
    esta función."""
    return valor or ENFOQUE_DEFAULT


def bloque_enfoque(enfoque):
    return _BLOQUES_ENFOQUE.get(enfoque, _BLOQUES_ENFOQUE[ENFOQUE_MIXTO])


def bloque_contexto(contexto, contexto_momento=''):
    partes = []
    if contexto:
        partes.append(
            '=== CONTEXTO DE LA JORNADA (lo escribió quien pidió el análisis) ===\n' + contexto
        )
    if contexto_momento:
        partes.append('=== CONTEXTO ESPECÍFICO DE ESTE MOMENTO ===\n' + contexto_momento)
    return '\n\n'.join(partes)


def bloque_instrucciones(instrucciones, instrucciones_momento=''):
    texto = '\n'.join(t for t in (instrucciones, instrucciones_momento) if t)
    if not texto:
        return ''
    return (
        'INSTRUCCIONES DE QUIEN PIDIÓ EL ANÁLISIS. Mandan sobre todo lo anterior (plantilla, '
        'enfoque y contexto): si contradicen alguna indicación de estilo, estructura o '
        'contenido de más arriba, se siguen estas.\n' + texto
    )


def ensamblar_system(base, plantilla_extra, enfoque, contexto, instrucciones, regla_datos,
                      contexto_momento='', instrucciones_momento=''):
    """Compone el system prompt final en el orden fijo de HU-57 (ver
    docs/HU_BACKEND_ANALISIS_GUIADO.md §2): plantilla base (con sus instrucciones de equipo) →
    bloque de enfoque → contexto → instrucciones del usuario (con precedencia sobre todo lo
    anterior) → regla de datos, siempre al final y no negociable. Un mismo orden para las dos vías
    de análisis (OpenAI y pipeline local), cada una con su propio `base`/`regla_datos`."""
    partes = [base + plantilla_extra, bloque_enfoque(normalizar_enfoque(enfoque))]
    ctx = bloque_contexto(contexto, contexto_momento)
    if ctx:
        partes.append(ctx)
    instr = bloque_instrucciones(instrucciones, instrucciones_momento)
    if instr:
        partes.append(instr)
    partes.append(regla_datos)
    return '\n\n'.join(parte for parte in partes if parte)
