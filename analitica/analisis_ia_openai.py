"""Vía de análisis alternativa a `analysis.py`: en vez del pipeline local multiagente (una llamada
de LLM local por pregunta + BERTopic para descubrir temas), UNA sola llamada a OpenAI lee el
INSTRUMENTO completo de un momento (contexto + todas sus preguntas y respuestas reales) y redacta
un reporte general — no una lista mecánica de "pregunta 1 dice X, pregunta 2 dice Y". El objetivo
es que GPT deduzca hallazgos que cruzan varias preguntas a la vez (un momento con 30 preguntas es
UN instrumento, no 30 análisis aislados), igual que lo haría un analista humano leyendo todas las
respuestas de corrido. No depende de un `Reporte` — se dispara directo desde un `Momento`."""
import json
import os
import threading

from django.utils import timezone

DEFAULT_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o')
GENERATION_TIMEOUT_SECONDS = 240
MAX_OUTPUT_TOKENS = 6000

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
    "cuestionario completo sobre la mesa, y deduce los hallazgos que de verdad importan — "
    "patrones, tensiones o consensos que solo se ven cruzando varias preguntas entre sí (ej. si "
    "el 80% apoya un principio en una pregunta de escala, pero ese mismo tema reaparece como "
    "'requiere ajuste' en los comentarios abiertos, esa tensión ES un hallazgo en sí mismo, más "
    "interesante que reportar cada pregunta por separado). Prioriza deducciones sobre datos "
    "directos: no te limites a repetir 'el 80% dijo que sí' — explica qué revela eso en conjunto "
    "con el resto del instrumento. Saca tantos hallazgos como el instrumento realmente sostenga "
    "(puede ser media docena, pueden ser doce) — ni fuerces relleno para llegar a un número, ni "
    "te cortes si hay más que decir.\n\n"

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
    "`datos` son SOLO los números reales que respaldan ESE hallazgo puntual, tomados "
    "directamente de los conteos u respuestas que se te dieron — nunca inventados. Un hallazgo "
    "puede combinar datos de varias preguntas (ej. el conteo de una pregunta de escala junto con "
    "cuántas respuestas abiertas tocan el mismo tema) — eso es exactamente el tipo de síntesis "
    "que se busca. `preguntas_relacionadas` lista TODOS los pregunta_id que sustentan el "
    "hallazgo, aunque sean varios. Si un hallazgo es una lectura cualitativa sin una "
    "distribución clara que graficar, `tipo_grafica` y `datos` pueden ir `null`/`[]` — no fuerces "
    "un gráfico donde no hay una cifra limpia que mostrar. Cuando sí haya datos: 'pastel' si "
    "pocos ítems y uno domina claramente; 'barras' para comparaciones; 'radar' si hay 4 o más "
    "ítems con tamaños relativamente parejos.\n\n"

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


def _construir_payload_momento(momento):
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

    return {
        'momento_id': momento.id,
        'titulo': momento.titulo,
        'tipo': momento.tipo,
        'contexto': momento.contexto,
        'categorias_semilla': momento.categorias_semilla,
        'preguntas': preguntas_payload,
    }


def _llamar_openai_json(system, user, model=None):
    """Una sola llamada a la API de OpenAI en modo JSON estricto. Devuelve (dict_o_None, error) —
    nunca lanza excepción."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None, 'OPENAI_API_KEY no está configurada en el entorno del servidor (.env).'

    resultado = {}

    def _run():
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            respuesta = client.chat.completions.create(
                model=model or DEFAULT_MODEL,
                messages=[
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': user},
                ],
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.4,
                response_format={'type': 'json_object'},
            )
            resultado['texto'] = respuesta.choices[0].message.content.strip()
        except Exception as exc:  # noqa: BLE001 — cualquier falla de la API cae a error legible
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
    from .models import AnalisisMomentoIA

    analisis = None
    try:
        analisis = AnalisisMomentoIA.objects.select_related('momento').get(pk=analisis_id)
        analisis.estado = AnalisisMomentoIA.ESTADO_PROCESANDO
        analisis.save(update_fields=['estado'])

        payload = _construir_payload_momento(analisis.momento)
        user = 'DATOS DEL MOMENTO (JSON):\n' + json.dumps(payload, ensure_ascii=False, indent=2)
        modelo = DEFAULT_MODEL
        resultado, error = _llamar_openai_json(SYSTEM_PROMPT, user, model=modelo)

        if resultado:
            analisis.resultado = _validar_y_limpiar(resultado, analisis.momento)
            analisis.estado = AnalisisMomentoIA.ESTADO_COMPLETO
            analisis.error_mensaje = ''
            analisis.modelo_usado = modelo
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
