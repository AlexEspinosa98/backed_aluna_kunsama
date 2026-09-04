"""Vía de análisis alternativa a `analysis.py`: en vez del pipeline local multiagente (una llamada
de LLM local por pregunta + BERTopic para descubrir temas), UNA sola llamada a OpenAI lee el
INSTRUMENTO completo (de un momento, o de la jornada entera) y redacta un reporte general — no
una lista mecánica de "pregunta 1 dice X, pregunta 2 dice Y". El objetivo es que GPT deduzca
hallazgos que cruzan varias preguntas (o varios momentos, a escala de jornada) a la vez, igual
que lo haría un analista humano leyendo todo el material de corrido. Ninguna de las dos vías
depende de un `Reporte` — `analizar_momento_ia` se dispara directo desde un `Momento`
(AnalisisMomentoIA) y `analizar_jornada_ia` desde una `Jornada` completa (AnalisisJornadaIA)."""
import json
import os
import threading

from django.utils import timezone

DEFAULT_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o')
# Los modelos de razonamiento (o1/o3/gpt-5+) aceptan un nivel de esfuerzo de razonamiento en vez
# de temperature — se pasa solo si el modelo configurado lo soporta; si el modelo no es de
# razonamiento, OpenAI simplemente ignora o rechaza el parámetro (queda como error legible, nunca
# como excepción sin capturar).
REASONING_EFFORT = os.environ.get('OPENAI_REASONING_EFFORT', 'medium')
GENERATION_TIMEOUT_SECONDS = 240
MAX_OUTPUT_TOKENS = 6000
# La jornada completa (varios momentos a la vez) es un payload más grande y se le pide más
# hallazgos (hasta 12 en vez de 10, y prosa un poco más larga) — más margen de tiempo y de
# tokens de salida que el análisis de un solo momento.
GENERATION_TIMEOUT_SECONDS_JORNADA = 300
MAX_OUTPUT_TOKENS_JORNADA = 8000
# Nunca se expone el nombre real del modelo de un proveedor externo en la respuesta de la API —
# solo que el análisis fue generado con IA.
MODELO_USADO_LABEL = 'Generado con IA'

SYSTEM_PROMPT = (
    "Eres un analista de datos senior leyendo TODO el instrumento de un momento de una jornada "
    "participativa universitaria, para redactar un reporte dirigido a la Rectoría de la "
    "Universidad del Magdalena. Se te entrega, en JSON, el título y el contexto del momento (qué "
    "buscaba lograr esta parte de la jornada — léelo primero, te da el marco para interpretar "
    "todo lo demás), y cada una de sus preguntas con datos reales: para preguntas de opción "
    "única/múltiple, el conteo EXACTO de cada opción (nunca lo recalcules ni lo cambies); para "
    "preguntas abiertas, TODAS las respuestas de texto reales recibidas, sin resumir ni "
    "recortar. Si se te da `categorias_semilla`, son temas que el equipo organizador ya sabe que "
    "son relevantes para este momento — úsalos como guía para reconocer esos patrones en las "
    "respuestas, pero nunca los repitas literal ni marques en tu salida cuáles 'vinieron' de "
    "ahí — el reporte debe leerse como un análisis unificado, no como una lista de categorías "
    "predefinidas etiquetadas.\n\n"

    "=== CÓMO PENSAR ESTE ANÁLISIS (lo más importante) ===\n"
    "NO analices pregunta por pregunta de forma mecánica ni produzcas una lista donde cada "
    "pregunta tiene su propio bloque aislado — eso es lo que ya hace el pipeline local, y "
    "precisamente NO es lo que se te pide. Un momento con 30 preguntas es UN SOLO instrumento, "
    "no 30 análisis sueltos: léelo todo de corrido, como lo haría un analista humano con el "
    "cuestionario completo sobre la mesa, buscando ACTIVAMENTE dónde varias preguntas apuntan al "
    "mismo punto antes de conformarte con un hallazgo de una sola pregunta (ej. si el 80% apoya "
    "un principio en una pregunta de escala, pero ese mismo tema reaparece como 'requiere ajuste' "
    "en los comentarios abiertos Y en la pregunta de cambios indispensables, esas tres preguntas "
    "juntas son UN hallazgo — la tensión entre apoyo declarado y ajuste pedido — no tres hallazgos "
    "sueltos). Prioriza pocos hallazgos densos y sustanciales por encima de muchos hallazgos "
    "superficiales: entrega SIEMPRE un mínimo de 6 y un máximo de 10 hallazgos, ni uno menos ni "
    "uno más — si el instrumento da para más de 10 patrones reales, quédate con los 10 más "
    "sustanciales; si a primera vista parece dar para menos de 6, profundiza más y cruza más "
    "preguntas entre sí hasta encontrar los 6. Cada hallazgo respaldado por 2 a 4 preguntas "
    "relacionadas cuando el patrón realmente lo sostenga (no fuerces un cruce donde no hay "
    "relación genuina, pero búscalo activamente antes de rendirte a un hallazgo de una sola "
    "pregunta). Prioriza deducciones sobre datos directos: no te limites a repetir 'el 80% dijo "
    "que sí' — explica qué revela eso en conjunto con el resto del instrumento. Cada hallazgo "
    "debe dejar claro, con las cifras que lo sustentan, en qué concuerdan los participantes y en "
    "qué no (consenso amplio, opinión dividida, una minoría con una postura relevante, etc.).\n\n"

    "=== TRANSFORMAR LO CUALITATIVO EN GRAFICABLE (obligatorio) ===\n"
    "Casi ningún hallazgo debería quedar sin datos graficables — incluso uno que nazca de "
    "respuestas de texto se puede cuantificar: extrae las palabras clave o categorías temáticas "
    "que mejor resuman el patrón en las respuestas abiertas relevantes (de una pregunta o de "
    "varias combinadas, si el hallazgo las une) y CUENTA cuántas respuestas reales tocan cada "
    "una — eso es tu `datos`. Deja `datos` vacío solo en el caso raro de un hallazgo puramente "
    "contextual sin ningún conteo posible detrás.\n\n"

    "=== FORMATO DE SALIDA (obligatorio) ===\n"
    "Responde ÚNICAMENTE con un objeto JSON válido, sin explicación antes ni después, sin "
    "fences de markdown, con esta forma exacta:\n"
    "{\n"
    '  "momento_id": <int, el mismo que te dieron>,\n'
    '  "tipo": "<individual|mesa, el mismo que te dieron>",\n'
    '  "resumen_ejecutivo": "<panorama general del instrumento completo, 4 a 7 frases>",\n'
    '  "hallazgos": [\n'
    "    {\n"
    '      "titulo": "<título corto y natural del hallazgo, no un identificador técnico>",\n'
    '      "descripcion": "<la deducción en sí, 2 a 5 frases, con sus cifras exactas>",\n'
    '      "preguntas_relacionadas": [<pregunta_id>, ...],\n'
    '      "tipo_grafica": "<pastel|barras|radar|null>",\n'
    '      "datos": [ {"etiqueta": "<string>", "valor": <número>, '
    '"unidad": "conteo"|"porcentaje"} ]\n'
    "    }\n"
    "  ]\n"
    "}\n\n"

    "=== REGLAS DE LOS DATOS QUE SUSTENTAN CADA HALLAZGO ===\n"
    "`datos` son SOLO los números reales que respaldan ESE hallazgo puntual, nunca cifras "
    "inventadas — pero deben ser de UNA SOLA naturaleza de medición, no una mezcla. Un conteo de "
    "opciones de una pregunta de escala (base: todos los que respondieron esa pregunta) y un "
    "conteo de cuántas respuestas de texto mencionan una palabra clave (base: solo quienes "
    "escribieron algo sobre eso) NO son comparables entre sí y NUNCA deben ir juntos en el mismo "
    "`datos` — mezclarlos en una sola gráfica es engañoso porque las barras usan bases distintas "
    "aunque se vean una al lado de la otra. Para un hallazgo que integra ambos tipos de evidencia: "
    "usa `datos` para SOLO uno de los dos (el que mejor represente el hallazgo — casi siempre el "
    "conteo de palabras clave, que es el más específico) y menciona el otro dato en la "
    "`descripcion` en prosa, sin graficarlo junto. `preguntas_relacionadas` sigue listando TODOS "
    "los pregunta_id que sustentan el hallazgo aunque el gráfico solo represente una parte de la "
    "evidencia.\n\n"
    "Usa los tres tipos de gráfica disponibles según lo que mejor comunique cada hallazgo — "
    "varía la elección de verdad, no caigas en usar 'barras' para todo por default: 'pastel' "
    "cuando son 2 o 3 ítems y uno domina claramente sobre el resto; 'barras' para comparar "
    "tamaños de forma simple; 'radar' cuando hay 4 o más ítems (temas o palabras clave "
    "extraídas de respuestas abiertas suelen dar naturalmente 4-6 categorías) y vale la pena ver "
    "la forma general de la distribución entre todos a la vez — con un instrumento de este "
    "tamaño, el reporte completo debe incluir AL MENOS un hallazgo con 'radar' cuando haya al "
    "menos un conjunto de 4+ palabras clave/temas real que lo sostenga; no lo fuerces con menos "
    "de 4 ítems reales, pero sí búscalo activamente antes de conformarte con solo pastel/"
    "barras.\n\n"

    "=== ESTILO DE REDACCIÓN ===\n"
    "Natural, profesional, como un reporte que de verdad se lee bien — no una ficha técnica. "
    "Prosa corrida en español, NUNCA con etiquetas como '(1)', '(2)', 'Hallazgo:', "
    "'Conclusión:' o 'Recomendación:' dentro del texto (el campo `titulo` ya cumple ese rol). "
    "Nunca empieces con muletillas como 'Resultados de la encuesta:' o 'Los resultados indican "
    "que'. Nunca caigas en frases genéricas que servirían para cualquier informe ('es "
    "fundamental', 'es crucial') — cada hallazgo debe sonar específico a estos datos concretos, "
    "no intercambiable con otro informe. La elección de gráfica es un dato técnico aparte (el "
    "campo `tipo_grafica`) — nunca la menciones ni la justifiques dentro del texto. El conjunto "
    "de todo el texto (resumen_ejecutivo + todas las descripciones) no debe superar el "
    "equivalente a 10 páginas impresas (~4000-5000 palabras) — prioriza densidad real, no "
    "relleno para acercarte a ese máximo.\n\n"

    "Nunca inventes cifras, temas ni respuestas que no estén en los datos entregados a "
    "continuación."
)


SYSTEM_PROMPT_JORNADA = (
    "Eres un analista de datos senior leyendo TODA una jornada participativa universitaria "
    "completa (todos sus momentos, no uno solo), para redactar un reporte dirigido a la "
    "Rectoría de la Universidad del Magdalena. Se te entrega, en JSON, el nombre y la "
    "descripción de la jornada, y la lista completa de sus momentos — cada uno con su título, "
    "contexto (qué buscaba lograr esa parte específica), y todas sus preguntas con datos "
    "reales: para preguntas de opción única/múltiple, el conteo EXACTO de cada opción (nunca lo "
    "recalcules ni lo cambies); para preguntas abiertas, TODAS las respuestas de texto reales "
    "recibidas, sin resumir ni recortar. Si un momento trae `categorias_semilla`, son temas que "
    "el equipo organizador ya sabe que son relevantes para ESE momento — úsalos como guía para "
    "reconocer esos patrones en las respuestas, pero nunca los repitas literal ni marques en tu "
    "salida cuáles 'vinieron' de ahí.\n\n"

    "=== CÓMO PENSAR ESTE ANÁLISIS (lo más importante) ===\n"
    "NO analices momento por momento de forma mecánica ni produzcas una lista donde cada "
    "momento tiene su propio bloque aislado — eso es lo que ya hacen el pipeline local y el "
    "análisis de momento individual (AnalisisMomentoIA), y precisamente NO es lo que se te "
    "pide acá. Una jornada con varios momentos es UN SOLO instrumento de principio a fin, no N "
    "análisis de momento sueltos pegados uno tras otro: léela toda de corrido, como lo haría un "
    "analista humano con TODO el material de la jornada sobre la mesa, buscando ACTIVAMENTE "
    "dónde un mismo patrón, tensión o consenso reaparece en momentos distintos antes de "
    "conformarte con un hallazgo de un solo momento (ej. si en el Momento 2 los participantes "
    "piden más acompañamiento institucional y en el Momento 5, sobre un tema totalmente "
    "distinto, vuelve a aparecer la misma demanda de acompañamiento, esas dos cosas juntas son "
    "UN hallazgo transversal de la jornada completa — no dos hallazgos de momento). Prioriza "
    "pocos hallazgos densos y sustanciales por encima de muchos hallazgos superficiales: "
    "entrega SIEMPRE un mínimo de 6 y un máximo de 12 hallazgos, ni uno menos ni uno más — si la "
    "jornada da para más de 12 patrones reales, quédate con los 12 más sustanciales; si a "
    "primera vista parece dar para menos de 6, profundiza más y cruza más momentos entre sí "
    "hasta encontrar los 6. Un hallazgo puede nacer de un solo momento cuando el patrón "
    "realmente no se repite en otro lado — eso también es válido — pero busca activamente los "
    "que cruzan momentos antes de conformarte con eso. Prioriza deducciones sobre datos "
    "directos: no te limites a repetir 'el 80% dijo que sí' — explica qué revela eso en "
    "conjunto con el resto de la jornada. Cada hallazgo debe dejar claro, con las cifras que lo "
    "sustentan, en qué concuerdan los participantes y en qué no (consenso amplio, opinión "
    "dividida, una minoría con una postura relevante, etc.).\n\n"

    "=== TRANSFORMAR LO CUALITATIVO EN GRAFICABLE (obligatorio) ===\n"
    "Casi ningún hallazgo debería quedar sin datos graficables — incluso uno que nazca de "
    "respuestas de texto se puede cuantificar: extrae las palabras clave o categorías temáticas "
    "que mejor resuman el patrón en las respuestas abiertas relevantes (de un momento o de "
    "varios combinados, si el hallazgo los une) y CUENTA cuántas respuestas reales tocan cada "
    "una — eso es tu `datos`. Deja `datos` vacío solo en el caso raro de un hallazgo puramente "
    "contextual sin ningún conteo posible detrás.\n\n"

    "=== FORMATO DE SALIDA (obligatorio) ===\n"
    "Responde ÚNICAMENTE con un objeto JSON válido, sin explicación antes ni después, sin "
    "fences de markdown, con esta forma exacta:\n"
    "{\n"
    '  "jornada_id": <int, el mismo que te dieron>,\n'
    '  "resumen_ejecutivo": "<panorama general de la jornada completa, 4 a 7 frases>",\n'
    '  "hallazgos": [\n'
    "    {\n"
    '      "titulo": "<título corto y natural del hallazgo, no un identificador técnico>",\n'
    '      "descripcion": "<la deducción en sí, 2 a 5 frases, con sus cifras exactas>",\n'
    '      "momentos_relacionados": [<momento_id>, ...],\n'
    '      "preguntas_relacionadas": [<pregunta_id>, ...],\n'
    '      "tipo_grafica": "<pastel|barras|radar|null>",\n'
    '      "datos": [ {"etiqueta": "<string>", "valor": <número>, '
    '"unidad": "conteo"|"porcentaje"} ]\n'
    "    }\n"
    "  ]\n"
    "}\n\n"

    "=== REGLAS DE LOS DATOS QUE SUSTENTAN CADA HALLAZGO ===\n"
    "`datos` son SOLO los números reales que respaldan ESE hallazgo puntual, nunca cifras "
    "inventadas — pero deben ser de UNA SOLA naturaleza de medición, no una mezcla. Un conteo de "
    "opciones de una pregunta de un momento (base: todos los que respondieron esa pregunta) y "
    "un conteo de menciones de palabra clave en respuestas de texto de otro momento (base: solo "
    "quienes escribieron algo sobre eso) NO son comparables entre sí y NUNCA deben ir juntos en "
    "el mismo `datos` — mezclarlos en una sola gráfica es engañoso porque las barras usan bases "
    "distintas aunque se vean una al lado de la otra. Para un hallazgo que integra evidencia de "
    "varios momentos con naturalezas distintas: usa `datos` para SOLO una de esas naturalezas "
    "(la que mejor represente el hallazgo) y menciona el resto en la `descripcion` en prosa, sin "
    "graficarlo junto. `momentos_relacionados` y `preguntas_relacionadas` siguen listando TODOS "
    "los momentos/preguntas que sustentan el hallazgo aunque el gráfico solo represente una "
    "parte de la evidencia.\n\n"
    "Usa los tres tipos de gráfica disponibles según lo que mejor comunique cada hallazgo — "
    "varía la elección de verdad, no caigas en usar 'barras' para todo por default: 'pastel' "
    "cuando son 2 o 3 ítems y uno domina claramente sobre el resto; 'barras' para comparar "
    "tamaños de forma simple; 'radar' cuando hay 4 o más ítems (temas o palabras clave "
    "extraídas de respuestas abiertas, o los propios momentos de la jornada comparados entre "
    "sí, suelen dar naturalmente 4+ categorías) y vale la pena ver la forma general de la "
    "distribución entre todos a la vez — con una jornada de este tamaño, el reporte completo "
    "debe incluir AL MENOS un hallazgo con 'radar' cuando haya al menos un conjunto de 4+ "
    "ítems real que lo sostenga; no lo fuerces con menos de 4 ítems reales, pero sí búscalo "
    "activamente antes de conformarte con solo pastel/barras.\n\n"

    "=== ESTILO DE REDACCIÓN ===\n"
    "Natural, profesional, como un reporte que de verdad se lee bien — no una ficha técnica. "
    "Prosa corrida en español, NUNCA con etiquetas como '(1)', '(2)', 'Hallazgo:', "
    "'Conclusión:' o 'Recomendación:' dentro del texto (el campo `titulo` ya cumple ese rol). "
    "Nunca empieces con muletillas como 'Resultados de la jornada:' o 'Los resultados indican "
    "que'. Nunca caigas en frases genéricas que servirían para cualquier informe ('es "
    "fundamental', 'es crucial') — cada hallazgo debe sonar específico a estos datos concretos, "
    "no intercambiable con otro informe. La elección de gráfica es un dato técnico aparte (el "
    "campo `tipo_grafica`) — nunca la menciones ni la justifiques dentro del texto. El conjunto "
    "de todo el texto (resumen_ejecutivo + todas las descripciones) no debe superar el "
    "equivalente a 15 páginas impresas (~6000-7500 palabras) — prioriza densidad real, no "
    "relleno para acercarte a ese máximo.\n\n"

    "Nunca inventes cifras, temas ni respuestas que no estén en los datos entregados a "
    "continuación."
)


def _instrucciones_plantilla(plantilla):
    """Instrucciones adicionales editables por el equipo (PlantillaAnalisis con
    tipo='gpt_momento', vía POST/PATCH /api/admin/plantillas-analisis/) — mismo mecanismo que
    `analysis._instrucciones_plantilla` para el pipeline local, pero con su propio tipo de
    plantilla: son prompts de propósito distinto y no deben compartir la misma 'predeterminada'."""
    if plantilla and plantilla.prompt_sistema:
        return '\n\nInstrucciones adicionales del equipo organizador:\n' + plantilla.prompt_sistema
    return ''


def _preguntas_payload(momento):
    """Compartido entre `_construir_payload_momento` (un solo momento) y
    `_construir_payload_jornada` (todos los momentos de la jornada) — mismo detalle de pregunta
    en ambos casos, solo cambia cuántos momentos se empaquetan alrededor."""
    from participantes.models import Respuesta

    from .analysis import _estadisticas_pregunta

    preguntas_payload = []
    for pregunta in momento.preguntas.filter(activa=True).order_by('orden'):
        estad = _estadisticas_pregunta(pregunta)
        item = {
            'pregunta_id': pregunta.id,
            'texto': pregunta.texto,
            'tipo': pregunta.tipo,
            'total_respuestas': estad['total_respuestas'],
        }
        if pregunta.tipo == 'abierta':
            item['respuestas_texto'] = list(
                Respuesta.objects.filter(pregunta=pregunta)
                .exclude(texto_libre='')
                .values_list('texto_libre', flat=True)
            )
        else:
            item['opciones'] = estad['conteo_opciones']
        preguntas_payload.append(item)
    return preguntas_payload


def _construir_payload_momento(momento):
    return {
        'momento_id': momento.id,
        'titulo': momento.titulo,
        'tipo': momento.tipo,
        'contexto': momento.contexto,
        'categorias_semilla': momento.categorias_semilla,
        'preguntas': _preguntas_payload(momento),
    }


def _construir_payload_jornada(jornada):
    momentos_payload = [
        {
            'momento_id': momento.id,
            'titulo': momento.titulo,
            'tipo': momento.tipo,
            'contexto': momento.contexto,
            'categorias_semilla': momento.categorias_semilla,
            'preguntas': _preguntas_payload(momento),
        }
        for momento in jornada.momentos.filter(activo=True).order_by('orden')
    ]
    return {
        'jornada_id': jornada.id,
        'jornada_nombre': jornada.nombre,
        'jornada_descripcion': jornada.descripcion,
        'momentos': momentos_payload,
    }


def _llamar_openai_json(system, user, model=None, max_output_tokens=None, timeout_seconds=None):
    """Una sola llamada a la API de OpenAI en modo JSON estricto. Devuelve (dict_o_None, error) —
    nunca lanza excepción."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None, 'OPENAI_API_KEY no está configurada en el entorno del servidor (.env).'

    max_output_tokens = max_output_tokens or MAX_OUTPUT_TOKENS
    timeout_seconds = timeout_seconds or GENERATION_TIMEOUT_SECONDS
    resultado = {}

    def _run():
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            kwargs = dict(
                model=model or DEFAULT_MODEL,
                messages=[
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': user},
                ],
                max_completion_tokens=max_output_tokens,
                response_format={'type': 'json_object'},
            )
            if REASONING_EFFORT:
                # Los modelos de razonamiento no aceptan `temperature` (la fijan ellos mismos) —
                # se manda reasoning_effort en su lugar, nunca ambos a la vez.
                kwargs['reasoning_effort'] = REASONING_EFFORT
            else:
                kwargs['temperature'] = 0.4
            respuesta = client.chat.completions.create(**kwargs)
            resultado['texto'] = respuesta.choices[0].message.content.strip()
        except Exception as exc:  # noqa: BLE001 — cualquier falla de la API cae a error legible
            resultado['error'] = str(exc)

    hilo = threading.Thread(target=_run, daemon=True)
    hilo.start()
    hilo.join(timeout=timeout_seconds)

    if hilo.is_alive():
        return None, f'Tiempo de espera agotado ({timeout_seconds}s) esperando a OpenAI.'
    if resultado.get('error'):
        return None, resultado['error']
    texto = resultado.get('texto')
    if not texto:
        return None, 'OpenAI no devolvió contenido.'
    try:
        return json.loads(texto), None
    except json.JSONDecodeError as exc:
        return None, f'OpenAI devolvió JSON inválido: {exc}'


def _validar_y_limpiar(resultado, momento):
    """Defensa mínima contra un JSON bien formado pero con detalles que no cuadran: fuerza
    `momento_id`/`tipo` a los reales (nunca los que 'recuerde' el modelo), y limpia
    determinísticamente cualquier etiqueta de estructura ('(1)', 'Hallazgo:', etc.) o mención
    suelta de qué gráfica usar que se haya colado en el texto — mismo principio ya validado en el
    pipeline local (`analysis._purgar_etiquetas_estructura`): no confiar en que el modelo respete
    una instrucción de formato solo porque se le pidió con palabras."""
    from .analysis import _purgar_etiquetas_estructura

    resultado['momento_id'] = momento.id
    resultado['tipo'] = momento.tipo
    resultado['resumen_ejecutivo'] = _purgar_etiquetas_estructura(resultado.get('resumen_ejecutivo'))
    for hallazgo in resultado.get('hallazgos') or []:
        hallazgo['titulo'] = _purgar_etiquetas_estructura(hallazgo.get('titulo'))
        hallazgo['descripcion'] = _purgar_etiquetas_estructura(hallazgo.get('descripcion'))
    return resultado


def analizar_momento_ia(analisis_id):
    """Genera el análisis de un `AnalisisMomentoIA` ya creado (estado `pendiente`). Corre en un
    hilo de background — mismo patrón que `procesar_reporte`/`generar_presentacion_html` — y no
    toca el modelo local ni su pool, así que puede correr en paralelo con un análisis local en
    curso."""
    from django.db import close_old_connections

    close_old_connections()
    from .models import AnalisisMomentoIA, PlantillaAnalisis

    analisis = None
    try:
        analisis = AnalisisMomentoIA.objects.select_related('momento').get(pk=analisis_id)
        analisis.estado = AnalisisMomentoIA.ESTADO_PROCESANDO
        analisis.save(update_fields=['estado'])

        plantilla = PlantillaAnalisis.objects.filter(
            tipo=PlantillaAnalisis.TIPO_GPT_MOMENTO, predeterminada=True
        ).first()
        system = SYSTEM_PROMPT + _instrucciones_plantilla(plantilla)
        payload = _construir_payload_momento(analisis.momento)
        user = 'DATOS DEL MOMENTO (JSON):\n' + json.dumps(payload, ensure_ascii=False, indent=2)
        modelo = DEFAULT_MODEL
        resultado, error = _llamar_openai_json(system, user, model=modelo)

        if resultado:
            analisis.resultado = _validar_y_limpiar(resultado, analisis.momento)
            analisis.estado = AnalisisMomentoIA.ESTADO_COMPLETO
            analisis.error_mensaje = ''
            analisis.modelo_usado = MODELO_USADO_LABEL
            analisis.completado_en = timezone.now()
        else:
            analisis.estado = AnalisisMomentoIA.ESTADO_ERROR
            analisis.error_mensaje = error or 'Error desconocido generando el análisis.'
        analisis.save(update_fields=[
            'resultado', 'estado', 'error_mensaje', 'modelo_usado', 'completado_en',
        ])
    except Exception as exc:  # noqa: BLE001 — nunca debe dejar el hilo morir en silencio
        if analisis is not None:
            analisis.estado = AnalisisMomentoIA.ESTADO_ERROR
            analisis.error_mensaje = str(exc)
            analisis.save(update_fields=['estado', 'error_mensaje'])
    finally:
        close_old_connections()


def _validar_y_limpiar_jornada(resultado, jornada):
    """Misma defensa que `_validar_y_limpiar`, a escala de jornada: fuerza `jornada_id` al real
    y limpia etiquetas de estructura que se hayan colado en el texto."""
    from .analysis import _purgar_etiquetas_estructura

    resultado['jornada_id'] = jornada.id
    resultado['resumen_ejecutivo'] = _purgar_etiquetas_estructura(resultado.get('resumen_ejecutivo'))
    for hallazgo in resultado.get('hallazgos') or []:
        hallazgo['titulo'] = _purgar_etiquetas_estructura(hallazgo.get('titulo'))
        hallazgo['descripcion'] = _purgar_etiquetas_estructura(hallazgo.get('descripcion'))
    return resultado


def analizar_jornada_ia(analisis_id):
    """Genera el análisis de un `AnalisisJornadaIA` ya creado (estado `pendiente`) — mismo patrón
    que `analizar_momento_ia`, pero leyendo TODOS los momentos activos de la jornada en una sola
    llamada a OpenAI (ver `SYSTEM_PROMPT_JORNADA` y `_construir_payload_jornada`)."""
    from django.db import close_old_connections

    close_old_connections()
    from .models import AnalisisJornadaIA, PlantillaAnalisis

    analisis = None
    try:
        analisis = AnalisisJornadaIA.objects.select_related('jornada').get(pk=analisis_id)
        analisis.estado = AnalisisJornadaIA.ESTADO_PROCESANDO
        analisis.save(update_fields=['estado'])

        plantilla = PlantillaAnalisis.objects.filter(
            tipo=PlantillaAnalisis.TIPO_GPT_JORNADA, predeterminada=True
        ).first()
        system = SYSTEM_PROMPT_JORNADA + _instrucciones_plantilla(plantilla)
        payload = _construir_payload_jornada(analisis.jornada)
        user = 'DATOS DE LA JORNADA (JSON):\n' + json.dumps(payload, ensure_ascii=False, indent=2)
        resultado, error = _llamar_openai_json(
            system, user, model=DEFAULT_MODEL,
            max_output_tokens=MAX_OUTPUT_TOKENS_JORNADA,
            timeout_seconds=GENERATION_TIMEOUT_SECONDS_JORNADA,
        )

        if resultado:
            analisis.resultado = _validar_y_limpiar_jornada(resultado, analisis.jornada)
            analisis.estado = AnalisisJornadaIA.ESTADO_COMPLETO
            analisis.error_mensaje = ''
            analisis.modelo_usado = MODELO_USADO_LABEL
            analisis.completado_en = timezone.now()
        else:
            analisis.estado = AnalisisJornadaIA.ESTADO_ERROR
            analisis.error_mensaje = error or 'Error desconocido generando el análisis.'
        analisis.save(update_fields=[
            'resultado', 'estado', 'error_mensaje', 'modelo_usado', 'completado_en',
        ])
    except Exception as exc:  # noqa: BLE001 — nunca debe dejar el hilo morir en silencio
        if analisis is not None:
            analisis.estado = AnalisisJornadaIA.ESTADO_ERROR
            analisis.error_mensaje = str(exc)
            analisis.save(update_fields=['estado', 'error_mensaje'])
    finally:
        close_old_connections()
