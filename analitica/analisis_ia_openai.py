"""Vía de análisis alternativa a `analysis.py`: en vez del pipeline local multiagente (una llamada
de LLM local por pregunta + BERTopic para descubrir temas), UNA sola llamada a OpenAI analiza TODO
un momento de una vez — se le dan los conteos reales de las preguntas cerradas (nunca los inventa,
igual que el pipeline local) y TODAS las respuestas de texto crudas de las preguntas abiertas, y el
propio GPT identifica temas, clasifica cada respuesta y redacta. Devuelve el mismo formato de JSON
que ya produce el pipeline local para un momento (`MomentoAnalisis`, ver
`docs/REPORTE_ANALITICA_SCHEMA.html`) para que el frontend renderice cualquiera de los dos caminos
con el mismo componente. No depende de un `Reporte` — se dispara directo desde un `Momento`."""
import json
import os
import re
import threading

from django.utils import timezone

DEFAULT_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o')
GENERATION_TIMEOUT_SECONDS = 240
MAX_OUTPUT_TOKENS = 6000

SYSTEM_PROMPT = (
    "Eres un analista de datos senior redactando el análisis de UN momento completo de una "
    "jornada participativa universitaria, dirigido a la Rectoría de la Universidad del "
    "Magdalena. Se te entrega, en JSON, el enunciado de cada pregunta del momento y sus datos "
    "reales: para preguntas de opción única/múltiple, el conteo EXACTO de cada opción (nunca lo "
    "recalcules ni lo cambies); para preguntas abiertas, TODAS las respuestas de texto reales "
    "recibidas, sin resumir ni recortar. Tu trabajo es identificar los temas recurrentes en las "
    "respuestas abiertas, clasificar cada una en un tema, y redactar el análisis — SOLO usando "
    "los datos entregados, nunca inventes una cifra, tema o cita que no esté ahí.\n\n"

    "=== FORMATO DE SALIDA (obligatorio) ===\n"
    "Responde ÚNICAMENTE con un objeto JSON válido, sin explicación antes ni después, sin "
    "fences de markdown, con esta forma exacta:\n"
    "{\n"
    '  "momento_id": <int, el mismo que te dieron>,\n'
    '  "tipo": "<individual|mesa, el mismo que te dieron>",\n'
    '  "descripcion_general": "<síntesis del momento completo, 3 a 6 frases>",\n'
    '  "preguntas": [\n'
    "    {\n"
    '      "pregunta_id": <int>,\n'
    '      "texto": "<el enunciado exacto que te dieron>",\n'
    '      "tipo": "<abierta|unica|multiple>",\n'
    '      "tipo_grafica": "<pastel|barras|radar|null>",\n'
    '      "nivel_acuerdo": "<consenso_fuerte|consenso_moderado|tension_estrategica|'
    'tema_emergente|asunto_pendiente|null>",\n'
    '      "total_respuestas": <int>,\n'
    '      "descripcion": "<análisis de esta pregunta puntual>",\n'
    '      "valores_caracteristicos": [ ... ver reglas abajo ... ],\n'
    '      "metodo_valores": "<bertopic_llm|conteo|llm|sin_datos|insuficiente>"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"

    "=== REGLAS POR TIPO DE PREGUNTA ===\n"
    "- unica/multiple: usa EXACTAMENTE los `opciones` que te dieron (opcion_id, texto, conteo) "
    "como `valores_caracteristicos`, sin cambiar ni un número. `metodo_valores`: 'conteo'.\n"
    "- abierta con 8 o más respuestas de texto: identifica 3 a 6 temas recurrentes (si te dieron "
    "`categorias_semilla`, úsalas como candidatos fijos — como mucho puedes sumar UN tema nuevo "
    "si de verdad ninguna semilla encaja) y clasifica cada respuesta real en uno de ellos. "
    "`valores_caracteristicos`: lista de {\"tema\": string, \"tamano\": int (conteo real de "
    "respuestas clasificadas ahí), \"porcentaje\": float, \"origen\": \"semilla\"|\"inductivo\"}. "
    "`metodo_valores`: 'bertopic_llm'.\n"
    "- abierta con menos de 8 respuestas: extrae 3 a 5 frases cortas características tomadas o "
    "parafraseadas de las respuestas dadas, sin clasificar ni contar — "
    "`valores_caracteristicos`: [{\"tema\": frase, \"tamano\": null, \"porcentaje\": null}]. "
    "`metodo_valores`: 'llm'.\n"
    "- abierta sin respuestas: `total_respuestas`: 0, `valores_caracteristicos`: [], "
    "`metodo_valores`: 'sin_datos', `descripcion`: 'No se recibieron respuestas.'\n\n"

    "=== tipo_grafica ===\n"
    "Solo para unica/multiple, o abierta con 2+ temas clasificados (bertopic_llm): 'pastel' si "
    "pocos temas/opciones y uno domina claramente; 'barras' para comparación simple; 'radar' si "
    "hay 4 o más temas/opciones con tamaños relativamente parejos. `null` en cualquier otro "
    "caso.\n\n"

    "=== nivel_acuerdo ===\n"
    "SOLO si `tipo` del momento es 'mesa' Y la pregunta es abierta con 2+ temas clasificados. "
    "Calcúlalo de la cobertura relativa del tema principal sobre el total: >=80% -> "
    "'consenso_fuerte'; >=50% y el segundo tema <30% -> 'consenso_moderado'; el segundo tema "
    ">=30% -> 'tension_estrategica'; el tema de menor tamaño <=15% del total -> 'tema_emergente'; "
    "si nada de eso aplica con claridad pero el tema requiere análisis jurídico/técnico/"
    "financiero adicional antes de decidir -> 'asunto_pendiente'. En cualquier otro caso: "
    "`null`.\n\n"

    "=== ESTILO DE REDACCIÓN (aplica a descripcion y descripcion_general) ===\n"
    "Profesional, conciso, centrado en cifras — prosa corrida en español, NUNCA con etiquetas "
    "como '(1)', '(2)', 'Hallazgo:', 'Conclusión:' o 'Recomendación:' en el texto. Nunca "
    "empieces con muletillas como 'Resultados de la encuesta:' o 'Los resultados indican que'. "
    "Ancla siempre la interpretación al enunciado REAL de esa pregunta — nunca generalices con "
    "frases sobre 'satisfacción general' u otro tema que la pregunta no plantee. Menciona el "
    "hallazgo principal con su cifra exacta y cierra con una conclusión breve, razonada "
    "genuinamente para ESE dato puntual — nunca una fórmula genérica ('es fundamental', 'es "
    "crucial') que serviría para cualquier pregunta. La elección de gráfica es un dato técnico "
    "aparte (el campo `tipo_grafica`) — nunca la menciones ni la justifiques dentro del texto. "
    "`descripcion` de cada pregunta: 2 a 4 frases. `descripcion_general` del momento: 3 a 6 "
    "frases. El conjunto de todo el texto del momento (todas las `descripcion` + "
    "`descripcion_general`) no debe superar el equivalente a 10 páginas impresas (~4000-5000 "
    "palabras) — pero prioriza densidad real, no relleno para acercarte a ese máximo.\n\n"

    "Nunca inventes cifras, temas ni respuestas que no estén en los datos entregados a "
    "continuación."
)

CIFRA_FALSA_RE = re.compile(
    r'\s*\(?\b\d+(?:[.,]\d+)?\s*%\)?|\s*\(?\b\d+\s+respuestas?\)?', re.IGNORECASE
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


def _purgar_cifras_falsas(texto):
    if not isinstance(texto, str) or not texto:
        return texto
    limpio = CIFRA_FALSA_RE.sub('', texto)
    limpio = re.sub(r'\s+([.,;:])', r'\1', limpio)
    return re.sub(r'\s{2,}', ' ', limpio).strip()


def _validar_y_limpiar(resultado, momento):
    """Defensa mínima contra un JSON bien formado pero con datos que no cuadran: fuerza
    `momento_id`/`tipo` a los reales (nunca los que 'recuerde' el modelo), y para preguntas sin
    conteo real (metodo_valores 'llm'/'sin_datos') purga cualquier cifra que se haya colado en la
    descripción — mismo principio que ya se validó en el pipeline local: no confiar en que el
    modelo respete la ausencia de un dato solo porque se le pidió con palabras."""
    resultado['momento_id'] = momento.id
    resultado['tipo'] = momento.tipo
    for pregunta in resultado.get('preguntas') or []:
        if pregunta.get('metodo_valores') in ('llm', 'sin_datos', 'insuficiente'):
            pregunta['descripcion'] = _purgar_cifras_falsas(pregunta.get('descripcion'))
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
