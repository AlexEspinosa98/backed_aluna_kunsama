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
GENERATION_TIMEOUT_SECONDS = 180
MAX_OUTPUT_TOKENS = 16000

SYSTEM_PROMPT = (
    "Eres un diseñador de reportes institucionales. Se te entrega, en JSON, el análisis YA "
    "CALCULADO de una jornada participativa universitaria (participación, momentos, preguntas, "
    "temas con su tamaño/porcentaje, nivel de acuerdo entre mesas cuando aplica, y una síntesis "
    "narrativa ya redactada). Tu trabajo es maquetarlo como una página de presentación HTML "
    "profesional — nunca inventes ni modifiques una sola cifra, tema o frase de la síntesis: usa "
    "EXCLUSIVAMENTE los datos entregados, en el mismo idioma (español).\n\n"
    "Requisitos de la página:\n"
    "- COBERTURA COMPLETA, sin excepción: la página debe incluir TODOS los momentos y TODAS las "
    "preguntas que vengan en el JSON — nunca selecciones un subconjunto 'representativo' ni "
    "resumas salteando preguntas. Si el JSON trae 11 preguntas, la página debe tener 11 "
    "preguntas, no 4. Antes de responder, cuenta las preguntas del JSON y verifica que tu HTML "
    "tenga esa misma cantidad.\n"
    "- HTML autocontenido en un solo archivo: CSS en un <style> embebido, sin dependencias "
    "externas (sin CDNs, sin fuentes remotas, sin JavaScript de terceros) — debe abrir "
    "directamente desde el disco en cualquier navegador.\n"
    "- Encabezado con el nombre de la jornada y las cifras de participación.\n"
    "- Una sección por cada momento incluido, indicando si es de reflexión individual o de "
    "consenso de mesa (usa el campo `tipo` de cada momento) — nunca los mezcles ni los presentes "
    "igual, son datos de naturaleza distinta.\n"
    "- Por cada pregunta con temas cuantificados (`tamano`/`porcentaje` no nulos), una "
    "visualización de barras horizontales en SVG inline mostrando cada tema con su porcentaje real "
    "— construida a partir de los números dados, nunca aproximada a ojo. Las preguntas sin "
    "cuantificación (`metodo_valores` distinto de `bertopic_llm`/`conteo`, o sin temas) igual van "
    "en la página, con su descripción en texto — nunca se omiten por no tener gráfica.\n"
    "- Cuando una pregunta traiga `nivel_acuerdo`, muéstralo de forma visible (ej. una etiqueta de "
    "estado) junto a esa pregunta.\n"
    "- El campo `sintesis_narrativa` puede traer marcado markdown (**negrita**, títulos) — "
    "conviértelo a HTML real (<strong>, <h3>, etc.), nunca lo muestres con los asteriscos "
    "literales. Inclúyelo completo, sin resumirlo ni reescribirlo.\n"
    "- Tipografía y paleta de color coherentes y profesionales — sobrias, no genéricas de IA "
    "(evita el cliché de fondo crema + serif + acento terracota, o negro con un solo acento neón).\n\n"
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
