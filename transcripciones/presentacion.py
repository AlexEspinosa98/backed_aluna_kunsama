"""Presentación HTML de un InformeTranscripcion, generada por OpenAI — misma capa de presentación
aparte del análisis que analitica/presentacion.py: nunca recalcula nada, solo redacta/maqueta a
partir de `informe.resultado` ya cerrado."""
import json
import os
import threading

from django.utils import timezone

DEFAULT_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o')
GENERATION_TIMEOUT_SECONDS = 240
MAX_OUTPUT_TOKENS = 12000

SYSTEM_PROMPT = (
    "Eres el equipo de diseño que produce los informes institucionales que la Rectoría de una "
    "universidad presenta públicamente — el nivel de acabado tiene que sostener esa vara: "
    "elaborado, denso en contenido real, con jerarquía visual clara. Se te entrega, en JSON, el "
    "informe YA REDACTADO de una sesión transcrita (reunión, entrevista o taller): un resumen "
    "ejecutivo, los temas discutidos, y una lista de hallazgos, cada uno con su descripción y sus "
    "citas textuales reales. Tu trabajo es maquetarlo como una página de presentación HTML — "
    "nunca inventes ni modifiques una sola palabra del resumen, los hallazgos o las citas: usa "
    "EXCLUSIVAMENTE los datos entregados, en español.\n\n"

    "=== COBERTURA (innegociable) ===\n"
    "La página debe incluir TODOS los hallazgos del JSON, sin excepción, y cada cita textual debe "
    "aparecer literal (nunca parafraseada) — presentada visualmente como una cita (comillas, "
    "cursiva o un bloque con borde lateral, tu elección), no como texto corrido indistinguible "
    "del resto.\n\n"

    "=== ESTRUCTURA (en este orden) ===\n"
    "1. PORTADA a pantalla completa: fondo con un color institucional, el nombre de la sesión en "
    "tipografía grande, fecha si está disponible.\n"
    "2. RESUMEN EJECUTIVO en un bloque destacado con borde o fondo distintivo.\n"
    "3. TEMAS DISCUTIDOS como una fila de etiquetas/chips visuales.\n"
    "4. Una tarjeta grande POR CADA HALLAZGO: título, descripción, y sus citas textuales "
    "presentadas visualmente como citas reales.\n\n"

    "=== FORMATO TÉCNICO (innegociable) ===\n"
    "HTML de una sola página, con TODO el CSS inline en un <style> en el <head> (nunca hojas "
    "externas ni JavaScript de terceros) para que abra directo desde el disco en cualquier "
    "navegador.\n\n"

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
                # max_completion_tokens, no max_tokens, y sin `temperature` explícito: los
                # modelos más nuevos (ej. OPENAI_MODEL=gpt-5.6-terra en producción) rechazan el
                # nombre viejo del primer parámetro, y para el segundo solo aceptan su valor por
                # defecto (1) — mandar cualquier otro valor es 400 "Unsupported value:
                # 'temperature'".
                max_completion_tokens=max_tokens,
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
    texto = texto.strip()
    if texto.startswith('```'):
        texto = texto.split('\n', 1)[1] if '\n' in texto else texto.lstrip('`')
        if texto.rstrip().endswith('```'):
            texto = texto.rstrip()[:-3]
    return texto.strip()


def generar_presentacion_html(informe_id):
    """Genera la presentación HTML de un InformeTranscripcion ya `completo` y la guarda en
    `presentacion_html`. Corre en un hilo de background — no comparte ningún recurso con
    generar_informe_transcripcion, así que puede pedirse aunque haya otro informe en proceso."""
    from django.db import close_old_connections

    close_old_connections()
    from .models import InformeTranscripcion

    informe = None
    try:
        informe = InformeTranscripcion.objects.select_related('sesion').get(pk=informe_id)
        informe.presentacion_estado = InformeTranscripcion.PRESENTACION_ESTADO_PROCESANDO
        informe.save(update_fields=['presentacion_estado'])

        datos = {
            'sesion_nombre': informe.sesion.nombre,
            'resumen_ejecutivo': informe.resultado.get('resumen_ejecutivo'),
            'temas_discutidos': informe.resultado.get('temas_discutidos'),
            'hallazgos': informe.resultado.get('hallazgos'),
        }
        user = 'DATOS DEL INFORME (JSON):\n' + json.dumps(datos, ensure_ascii=False, indent=2)
        modelo = DEFAULT_MODEL
        texto, error = _llamar_openai(SYSTEM_PROMPT, user, model=modelo)

        if texto:
            informe.presentacion_html = _limpiar_html(texto)
            informe.presentacion_estado = InformeTranscripcion.PRESENTACION_ESTADO_COMPLETO
            informe.presentacion_error = ''
            informe.presentacion_modelo = modelo
            informe.presentacion_generada_en = timezone.now()
        else:
            informe.presentacion_estado = InformeTranscripcion.PRESENTACION_ESTADO_ERROR
            informe.presentacion_error = error or 'Error desconocido generando la presentación.'
        informe.save(update_fields=[
            'presentacion_html', 'presentacion_estado', 'presentacion_error',
            'presentacion_modelo', 'presentacion_generada_en',
        ])
    except Exception as exc:  # noqa: BLE001 — nunca debe dejar el hilo morir en silencio
        if informe is not None:
            informe.presentacion_estado = InformeTranscripcion.PRESENTACION_ESTADO_ERROR
            informe.presentacion_error = str(exc)
            informe.save(update_fields=['presentacion_estado', 'presentacion_error'])
    finally:
        close_old_connections()
