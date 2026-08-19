"""Presentación HTML de un Reporte, generada por OpenAI (GPT) — capa de presentación aparte del
análisis en sí. El pipeline local (`analitica/analysis.py`: BERTopic + LLM local) ya calculó todos
los números (participación, temas con tamaño/porcentaje/origen, nivel de acuerdo, tipo de gráfica
sugerido) y la síntesis narrativa; este módulo NUNCA recalcula nada de eso — solo le pide a GPT que
redacte y arme una página HTML de presentación a partir de esos datos ya cerrados, igual que un
diseñador maquetando un informe cuyas cifras ya vienen dadas.

Se generó a partir de un Reporte ya `completo` (no de respuestas crudas), así que hereda gratis el
`alcance` (jornada / un momento / varios momentos) que ese Reporte ya tenía — no hace falta lógica
de scope nueva aquí.
"""
import os
import threading

from django.utils import timezone

DEFAULT_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o')
GENERATION_TIMEOUT_SECONDS = 240
MAX_OUTPUT_TOKENS = 16000

SYSTEM_PROMPT = (
    "Eres el equipo de diseño que produce los informes institucionales que la Rectoría de una "
    "universidad presenta públicamente — el nivel de acabado tiene que sostener esa vara: "
    "elaborado, denso en contenido real, con jerarquía visual clara, NUNCA una página corta y "
    "plana. Se te entrega, en JSON, el análisis YA CALCULADO de una jornada participativa "
    "(participación, momentos, preguntas, temas con su tamaño/porcentaje, nivel de acuerdo entre "
    "mesas cuando aplica, y una síntesis narrativa ya redactada). Tu trabajo es maquetarlo como "
    "una página de presentación HTML — nunca inventes ni modifiques una sola cifra, tema o frase "
    "de la síntesis: usa EXCLUSIVAMENTE los datos entregados, en español.\n\n"

    "=== COBERTURA (innegociable) ===\n"
    "La página debe incluir TODOS los momentos y TODAS las preguntas del JSON, sin excepción — "
    "nunca selecciones un subconjunto 'representativo'. Si el JSON trae 11 preguntas, cuenta 11 "
    "secciones de pregunta en tu HTML antes de responder. Un informe institucional no omite datos "
    "por acortar.\n\n"

    "=== ESTRUCTURA (en este orden) ===\n"
    "1. PORTADA a pantalla completa: fondo con el color institucional principal, el nombre de la "
    "jornada en tipografía grande, y debajo — como mosaico de 3 o 4 tarjetas — las cifras clave de "
    "participación (participantes, tasa de participación, número de momentos). Se siente como la "
    "carátula de un informe impreso, no como el encabezado de una página web.\n"
    "2. ÍNDICE con enlaces ancla a cada momento (para navegar si se abre en pantalla).\n"
    "3. RESUMEN EJECUTIVO: la síntesis narrativa completa (`sintesis_narrativa`, con su markdown "
    "convertido a HTML real — nunca asteriscos literales), presentada en un bloque destacado con "
    "borde o fondo distintivo — es el bloque que más va a leer un rector con poco tiempo.\n"
    "4. Una sección grande POR CADA MOMENTO: título del momento, una etiqueta visible de tipo "
    "('Reflexión individual' o 'Consenso de mesa', según el campo `tipo` — nunca los mezcles ni "
    "los presentes igual, son datos de naturaleza distinta), la síntesis de ese momento "
    "(`descripcion_general`), y luego UNA TARJETA POR CADA PREGUNTA de ese momento con: el "
    "enunciado REAL de la pregunta (campo `texto` — este es el encabezado de la tarjeta, en "
    "tipografía destacada; nunca lo omitas ni lo reemplaces por 'Pregunta N'), su descripción "
    "completa de resultados, y su visualización.\n"
    "5. Cierre con CONCLUSIONES — deriva 3 a 5 puntos accionables apoyándote solo en lo que ya "
    "dice `sintesis_narrativa` y en los temas de mayor porcentaje de cada momento — nunca agregues "
    "un dato que no esté ya en el JSON.\n\n"

    "=== VISUALIZACIÓN DE DATOS ===\n"
    "Por cada pregunta con temas cuantificados (`tamano`/`porcentaje` no nulos), un gráfico real "
    "en SVG inline construido a partir de esos números exactos — barras horizontales para la "
    "mayoría de los casos, o un donut/pastel en SVG cuando `tipo_grafica` sea 'pastel' y haya 5 "
    "temas o menos. Cada barra o porción lleva su etiqueta de tema y su porcentaje real impreso al "
    "lado. Las preguntas sin cuantificación (`metodo_valores` distinto de `bertopic_llm`/`conteo`, "
    "o sin temas) igual llevan su propia tarjeta, con la descripción en texto — nunca se omiten "
    "por no tener gráfica. Cuando una pregunta traiga `nivel_acuerdo`, una etiqueta de estado "
    "visible junto a ella (colores distintos por nivel: consenso_fuerte en verde, "
    "consenso_moderado en azul/teal, tension_estrategica en naranja, tema_emergente en morado, "
    "asunto_pendiente en gris).\n\n"

    "=== DISEÑO VISUAL (sistema de diseño a seguir, no genérico) ===\n"
    "- Paleta: fondo de página #F4F6F5 (gris muy claro, no crema); superficies de tarjeta #FFFFFF "
    "con sombra sutil; color institucional principal #14384A (azul-petróleo oscuro) para la "
    "portada, encabezados de sección y acentos; color secundario cálido #C08A28 (ocre/dorado) "
    "usado con moderación para detalles y subrayados; texto principal #1A1F24, texto secundario "
    "#5B6670. Para las series de datos (barras/donut) usa esta paleta categórica en este orden fijo "
    "y nunca la repitas ni la mezcles con los colores de nivel_acuerdo: #2A78D6, #EB6834, #1BAF7A, "
    "#EDA100, #7A5EC9.\n"
    "- Tipografía: una fuente serif para títulos grandes (usa el stack "
    "'Georgia, \"Iowan Old Style\", \"Times New Roman\", serif' — nunca dependas de una fuente "
    "externa) y una sans-serif para cuerpo y datos ('-apple-system, \"Segoe UI\", Roboto, "
    "sans-serif'). Escala tipográfica clara: portada ~48-56px, títulos de momento ~32px, títulos "
    "de pregunta ~20px, cuerpo ~16px.\n"
    "- Layout: usa grid/flexbox para que las tarjetas de estadísticas y de preguntas se organicen "
    "en mosaico cuando el ancho lo permita, no una sola columna angosta de texto corrido. Espaciado "
    "generoso entre secciones (mínimo 48px). Cada momento nuevo empieza con un separador visual "
    "marcado (línea gruesa o cambio de fondo).\n"
    "- CSS de impresión: agrega reglas @media print con saltos de página (`break-before`/"
    "`break-inside: avoid`) para que cada momento y cada tarjeta de pregunta impriman bien — este "
    "documento está pensado para imprimirse y entregarse físicamente, debe verse como un informe "
    "de varias páginas, no como una sola pantalla corta.\n"
    "- HTML autocontenido en un solo archivo (CSS embebido, sin CDNs, sin fuentes remotas, sin "
    "JavaScript de terceros) para que abra directo desde el disco en cualquier navegador.\n\n"

    "Devuelve ÚNICAMENTE el HTML completo de la página, empezando en '<!doctype html>' — sin "
    "explicaciones antes ni después, sin fences de markdown (```)."
)


def _llamar_openai(system, user, max_tokens=MAX_OUTPUT_TOKENS, model=None):
    """Una sola llamada a la API de OpenAI. Devuelve (texto, error) — nunca lanza excepción."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None, (
            'OPENAI_API_KEY no está configurada en el entorno del servidor (.env) — no se puede '
            'generar la presentación.'
        )

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
                max_tokens=max_tokens,
                temperature=0.4,
            )
            resultado['texto'] = respuesta.choices[0].message.content.strip()
        except Exception as exc:  # noqa: BLE001 — cualquier falla de la API cae a error legible
            resultado['error'] = str(exc)

    hilo = threading.Thread(target=_run, daemon=True)
    hilo.start()
    hilo.join(timeout=GENERATION_TIMEOUT_SECONDS)

    if hilo.is_alive():
        return None, f'Tiempo de espera agotado ({GENERATION_TIMEOUT_SECONDS}s) esperando a OpenAI.'
    if not resultado.get('texto'):
        return None, resultado.get('error', 'OpenAI no devolvió texto.')
    return resultado['texto'], None


def _limpiar_html(texto):
    """El modelo a veces envuelve la respuesta en fences de markdown (```html ... ```) pese a la
    instrucción de no hacerlo — se retiran si aparecen, sin tocar el resto del contenido."""
    texto = texto.strip()
    if texto.startswith('```'):
        texto = texto.split('\n', 1)[1] if '\n' in texto else texto.lstrip('`')
        if texto.rstrip().endswith('```'):
            texto = texto.rstrip()[:-3]
    return texto.strip()


def generar_presentacion_html(reporte_id):
    """Genera la presentación HTML de un Reporte ya `completo` y la guarda en
    `presentacion_html`. Corre en un hilo de background, igual que `procesar_reporte` en
    analysis.py — mismo patrón, pero esta llamada no toca el modelo local ni su pool, así que
    puede correr en paralelo con un análisis local en curso sin riesgo de crash."""
    from django.db import close_old_connections

    close_old_connections()
    from .models import Reporte

    reporte = None
    try:
        reporte = Reporte.objects.select_related('jornada').get(pk=reporte_id)
        reporte.presentacion_estado = Reporte.PRESENTACION_ESTADO_PROCESANDO
        reporte.save(update_fields=['presentacion_estado'])

        datos = {
            'jornada': reporte.jornada.nombre,
            'alcance': reporte.alcance,
            'participacion': reporte.analisis.get('participacion'),
            'momentos': reporte.analisis.get('momentos'),
            'sintesis_narrativa': reporte.texto_reporte,
        }

        import json
        user = (
            'DATOS DEL REPORTE (JSON):\n' + json.dumps(datos, ensure_ascii=False, indent=2)
        )
        modelo = DEFAULT_MODEL
        texto, error = _llamar_openai(SYSTEM_PROMPT, user, model=modelo)

        if texto:
            reporte.presentacion_html = _limpiar_html(texto)
            reporte.presentacion_estado = Reporte.PRESENTACION_ESTADO_COMPLETO
            reporte.presentacion_error = ''
            reporte.presentacion_modelo = modelo
            reporte.presentacion_generada_en = timezone.now()
        else:
            reporte.presentacion_estado = Reporte.PRESENTACION_ESTADO_ERROR
            reporte.presentacion_error = error or 'Error desconocido generando la presentación.'
        reporte.save(update_fields=[
            'presentacion_html', 'presentacion_estado', 'presentacion_error',
            'presentacion_modelo', 'presentacion_generada_en',
        ])
    except Exception as exc:  # noqa: BLE001 — nunca debe dejar el hilo morir en silencio
        if reporte is not None:
            reporte.presentacion_estado = Reporte.PRESENTACION_ESTADO_ERROR
            reporte.presentacion_error = str(exc)
            reporte.save(update_fields=['presentacion_estado', 'presentacion_error'])
    finally:
        close_old_connections()
