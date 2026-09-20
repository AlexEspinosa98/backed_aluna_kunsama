"""Sugerencias rápidas de contexto/instrucciones para el paso de resumen del asistente guiado
(HU-57 §3, ver `docs/HU_BACKEND_ANALISIS_GUIADO.md`). Es un ayudante para ENCARGAR el análisis,
no una vista previa de resultados: la IA recibe de qué trata la jornada/los momentos y cuántas
respuestas tiene cada uno, nunca las respuestas en sí — sugiere cómo ENMARCAR el análisis, no qué
dicen los datos (no los tiene).

Mismo espíritu de "nunca lanza, nunca bloquea" que el resto de módulos de IA del proyecto, pero
con un presupuesto de tiempo mucho más corto: es parte de un formulario que se está llenando, no
un reporte que se espera. Un modelo chico y rápido (no el de razonamiento que usan
analisis_ia_openai.py/analysis.py — acá sobra profundidad y sobra tiempo)."""
import json
import os
import threading

SUGERENCIAS_MODEL = os.environ.get('OPENAI_SUGERENCIAS_MODEL', 'gpt-4o-mini')
# HU-57 exige "menos de 10 segundos"; 8s deja margen para el round-trip HTTP y el parseo antes de
# que la vista misma se acerque al límite que le pidió el frontend.
SUGERENCIAS_TIMEOUT_SECONDS = 8
SUGERENCIAS_MAX_TOKENS = 500
TIPOS_VALIDOS = ('contexto', 'instruccion')

SYSTEM_PROMPT = (
    "Ayudas a alguien a preparar el ENCARGO de un análisis de datos de una jornada participativa "
    "— todavía no hay resultados que leer: solo se te da de qué trata la jornada y sus momentos, "
    "y cuántas respuestas tiene cada uno, para sugerir cómo ENMARCAR el análisis, nunca qué dicen "
    "los datos (no los tienes, y no debes inventar que sí). Con el enfoque, el contexto y las "
    "instrucciones que la persona ya escribió, sugiere entre 0 y 6 ideas cortas (una frase cada "
    "una) para afinar el contexto o las instrucciones — nunca repitas ni parafrasees algo que la "
    "persona ya escribió, y nunca sugieras algo genérico que serviría para cualquier jornada. En "
    "español.\n\n"
    "Responde ÚNICAMENTE con un objeto JSON válido, sin explicación antes ni después, sin fences "
    "de markdown, con esta forma exacta:\n"
    '{"sugerencias": [{"tipo": "contexto" | "instruccion", "texto": "<una frase corta>"}]}\n\n'
    '0 sugerencias (`"sugerencias": []`) es una respuesta válida y preferible a forzar ideas '
    "que no aportarían nada."
)


def _payload_momentos(jornada, momento_ids):
    """Sin respuestas de participantes — solo lo que hace falta para enmarcar el análisis (HU-57
    §3): título, contexto ya escrito por el equipo, tipo, cuántas respuestas hay y qué tipos de
    pregunta trae. `momento_ids` vacío = todos los momentos de la jornada (alcance de jornada
    completa). Sin filtrar por `activo` — ese campo es de visibilidad para participantes, no dice
    nada sobre si hay respuestas reales que enmarcar; mismo criterio que
    `analisis_ia_openai._construir_payload_jornada`, para sugerir sobre exactamente el mismo
    material que el análisis real va a usar."""
    from participantes.models import Respuesta

    momentos = jornada.momentos.all()
    if momento_ids:
        momentos = momentos.filter(id__in=momento_ids)

    payload = []
    for momento in momentos.order_by('orden'):
        payload.append({
            'momento_id': momento.id,
            'titulo': momento.titulo,
            'contexto': momento.contexto,
            'tipo': momento.tipo,
            'total_respuestas': Respuesta.objects.filter(pregunta__momento=momento).count(),
            'tipos_pregunta': sorted(set(
                momento.preguntas.filter(activa=True).values_list('tipo', flat=True)
            )),
        })
    return payload


def generar_sugerencias(jornada, momento_ids, metodo, enfoque, contexto, instrucciones):
    """Devuelve SIEMPRE una lista (nunca `None`, nunca lanza) — `[]` si `OPENAI_API_KEY` no está
    configurada, si el proveedor tarda más de `SUGERENCIAS_TIMEOUT_SECONDS`, o si la respuesta no
    se puede interpretar. El endpoint que llama a esto (`AnalisisSugerenciasView`) responde `200`
    con esta lista sin importar qué pasó adentro — HU-57 §3: "el frontend nunca bloquea por
    esto"."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return []

    payload = {
        'jornada': jornada.nombre,
        'jornada_contexto': jornada.descripcion,
        'metodo': metodo,
        'enfoque': enfoque,
        'contexto_ya_escrito': contexto,
        'instrucciones_ya_escritas': instrucciones,
        'momentos': _payload_momentos(jornada, momento_ids),
    }
    user = 'DATOS PARA SUGERIR (JSON):\n' + json.dumps(payload, ensure_ascii=False)

    resultado = {}

    def _run():
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            respuesta = client.chat.completions.create(
                model=SUGERENCIAS_MODEL,
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': user},
                ],
                max_completion_tokens=SUGERENCIAS_MAX_TOKENS,
                response_format={'type': 'json_object'},
                temperature=0.6,
            )
            resultado['texto'] = respuesta.choices[0].message.content
        except Exception as exc:  # noqa: BLE001 — cualquier falla cae a lista vacía, nunca a error
            resultado['error'] = str(exc)

    hilo = threading.Thread(target=_run, daemon=True)
    hilo.start()
    hilo.join(timeout=SUGERENCIAS_TIMEOUT_SECONDS)
    if hilo.is_alive() or not resultado.get('texto'):
        return []

    try:
        data = json.loads(resultado['texto'])
    except (json.JSONDecodeError, TypeError):
        return []

    sugerencias = []
    for item in (data.get('sugerencias') or [])[:6]:
        if not isinstance(item, dict):
            continue
        tipo = item.get('tipo')
        texto = (item.get('texto') or '').strip()
        if tipo in TIPOS_VALIDOS and texto:
            sugerencias.append({'tipo': tipo, 'texto': texto})
    return sugerencias
