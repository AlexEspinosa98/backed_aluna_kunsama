"""Análisis cualitativo → cuantitativo para reportes de jornadas: estadísticas determinísticas
sobre las respuestas, modelado de tópicos con BERTopic sobre las preguntas abiertas, y una
narrativa redactada por un LLM local (`Qwen2.5-3B-Instruct`, cuantizado GGUF, servido con
`llama-cpp-python` — sin GPU, sin `torch`; mismo enfoque ya probado en el repo hermano
`aluna_propositos_backend/backend/catalog/ai_analysis.py`).

Decisión de diseño central, igual que en ese repo hermano: **los números nunca dependen del
LLM**. `calcular_estadisticas` y `modelar_topicos` son 100% determinísticos; el modelo solo
redacta prosa sobre esos datos ya calculados, nunca los inventa. Si el LLM falla, tarda demasiado
o no está descargado, el reporte igual queda `completo` con las estadísticas y tópicos — solo
cambia si la narrativa es texto generado o un aviso de respaldo.

    calcular_estadisticas ─┐
    modelar_topicos (BERTopic) ─┴─→ generar_narrativa (LLM, con timeout) ─→ Reporte.completo
                                                    └─(timeout / error)──→ texto de respaldo
"""
import os
import threading
from pathlib import Path

from django.db import close_old_connections
from django.utils import timezone

MODELS_DIR = Path(__file__).resolve().parent / '.models'
DEFAULT_MODEL_REPO = 'Qwen/Qwen2.5-3B-Instruct-GGUF'
DEFAULT_MODEL_FILE = os.environ.get('KUNSAMU_LLM_MODEL_FILE', 'qwen2.5-3b-instruct-q4_k_m.gguf')
MODEL_PATH = MODELS_DIR / DEFAULT_MODEL_FILE

EMBEDDING_MODEL_NAME = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'

MIN_RESPUESTAS_TOPICOS = 8
GENERATION_TIMEOUT_SECONDS = 90

BASE_SYSTEM_PROMPT = (
    "Eres un analista de datos que redacta el reporte de una jornada participativa para su "
    "equipo organizador. Usa EXCLUSIVAMENTE los datos que se te entregan a continuación "
    "(estadísticas y tópicos ya calculados a partir de las respuestas reales) — nunca inventes "
    "cifras, porcentajes, temas ni citas que no estén en esos datos. Si un dato no está "
    "disponible, no lo menciones. Escribe en español, en prosa clara, sin viñetas innecesarias."
)

FALLBACK_TEXTO = (
    'No se pudo generar el análisis narrativo automáticamente (el modelo no está disponible o '
    'tardó demasiado). A continuación se muestran las estadísticas y los tópicos calculados.'
)


# ---------------------------------------------------------------------------
# Modelo LLM (llama.cpp) — carga perezosa y única por proceso.
# ---------------------------------------------------------------------------

_llm_lock = threading.Lock()
_llm_instance = None


def _get_llm():
    global _llm_instance
    if _llm_instance is None:
        with _llm_lock:
            if _llm_instance is None:
                from llama_cpp import Llama
                if not MODEL_PATH.exists():
                    raise FileNotFoundError(
                        f'No se encontró el modelo en {MODEL_PATH}. Corre '
                        "'python manage.py download_llm_model' primero."
                    )
                _llm_instance = Llama(
                    model_path=str(MODEL_PATH), n_ctx=16384,
                    n_threads=os.cpu_count(), verbose=False,
                )
    return _llm_instance


# ---------------------------------------------------------------------------
# Embeddings (sentence-transformers) — carga perezosa y única por proceso.
# ---------------------------------------------------------------------------

_embedder_lock = threading.Lock()
_embedder_instance = None


def _get_embedder():
    global _embedder_instance
    if _embedder_instance is None:
        with _embedder_lock:
            if _embedder_instance is None:
                from sentence_transformers import SentenceTransformer
                _embedder_instance = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedder_instance


# ---------------------------------------------------------------------------
# Estadísticas determinísticas.
# ---------------------------------------------------------------------------

def calcular_estadisticas(jornada, momentos):
    from participantes.models import Participante, Respuesta

    from jornadas.models import Pregunta

    total_participantes = Participante.objects.filter(jornada=jornada).count()
    preguntas = (
        Pregunta.objects.filter(momento__in=momentos)
        .select_related('momento')
        .prefetch_related('opciones')
        .order_by('momento__orden', 'orden')
    )

    participantes_respondieron = set(
        Respuesta.objects.filter(pregunta__in=preguntas, participante__isnull=False)
        .values_list('participante_id', flat=True)
        .distinct()
    )

    por_pregunta = []
    for pregunta in preguntas:
        respuestas_qs = Respuesta.objects.filter(pregunta=pregunta)
        entry = {
            'pregunta_id': pregunta.id,
            'texto': pregunta.texto,
            'tipo': pregunta.tipo,
            'momento_id': pregunta.momento_id,
            'momento_titulo': pregunta.momento.titulo,
            'total_respuestas': respuestas_qs.count(),
        }
        if pregunta.tipo == Pregunta.TIPO_ABIERTA:
            entry['respuestas_no_vacias'] = respuestas_qs.exclude(texto_libre='').count()
        else:
            entry['conteo_opciones'] = [
                {
                    'opcion_id': opcion.id,
                    'texto': opcion.texto,
                    'conteo': respuestas_qs.filter(opciones=opcion).count(),
                }
                for opcion in pregunta.opciones.all()
            ]
        por_pregunta.append(entry)

    tasa = (
        round(len(participantes_respondieron) / total_participantes * 100, 1)
        if total_participantes else 0.0
    )
    return {
        'total_participantes': total_participantes,
        'participantes_que_respondieron': len(participantes_respondieron),
        'tasa_participacion': tasa,
        'preguntas': por_pregunta,
    }


# ---------------------------------------------------------------------------
# Modelado de tópicos (BERTopic) — una corrida por pregunta abierta.
# ---------------------------------------------------------------------------

# Lista de paro en español para el vectorizador de palabras clave (c-TF-IDF). Sin esto, las
# "palabras clave" de cada tema quedan dominadas por conectores ("de", "el", "sobre") en vez de
# las palabras con contenido real — sklearn no trae una lista de paro en español integrada.
STOPWORDS_ES = [
    'de', 'la', 'que', 'el', 'en', 'y', 'a', 'los', 'del', 'se', 'las', 'por', 'un', 'para',
    'con', 'no', 'una', 'su', 'al', 'lo', 'como', 'más', 'pero', 'sus', 'le', 'ya', 'o', 'este',
    'sí', 'porque', 'esta', 'entre', 'cuando', 'muy', 'sin', 'sobre', 'también', 'me', 'hasta',
    'hay', 'donde', 'quien', 'desde', 'todo', 'nos', 'durante', 'todos', 'uno', 'les', 'ni',
    'contra', 'otros', 'ese', 'eso', 'ante', 'ellos', 'e', 'esto', 'mí', 'antes', 'algunos',
    'qué', 'unos', 'yo', 'otro', 'otras', 'otra', 'él', 'tanto', 'esa', 'estos', 'mucho',
    'quienes', 'nada', 'muchos', 'cual', 'poco', 'ella', 'estar', 'estas', 'algunas', 'algo',
    'nosotros', 'mi', 'mis', 'tú', 'te', 'ti', 'tu', 'tus', 'ellas', 'nosotras', 'vosotros',
    'vosotras', 'os', 'mío', 'mía', 'míos', 'mías', 'tuyo', 'tuya', 'tuyos', 'tuyas', 'suyo',
    'suya', 'suyos', 'suyas', 'nuestro', 'nuestra', 'nuestros', 'nuestras', 'vuestro', 'vuestra',
    'vuestros', 'vuestras', 'esos', 'esas', 'soy', 'eres', 'es', 'somos', 'sois', 'son', 'fui',
    'fue', 'fuimos', 'fueron', 'ser', 'era', 'muy', 'bien', 'fue', 'está', 'estuvo', 'the', 'and',
]


def _run_bertopic(textos):
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    n = len(textos)
    umap_model = UMAP(
        n_neighbors=max(2, min(15, n - 1)),
        n_components=max(2, min(5, n - 2)),
        min_dist=0.0, metric='cosine', random_state=42,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=max(2, min(5, n // 4)),
        metric='euclidean', cluster_selection_method='eom', prediction_data=True,
    )
    vectorizer_model = CountVectorizer(stop_words=STOPWORDS_ES, ngram_range=(1, 2), min_df=1)
    modelo = BERTopic(
        embedding_model=_get_embedder(), umap_model=umap_model, hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer_model, verbose=False, calculate_probabilities=False,
    )
    modelo.fit_transform(textos)
    info = modelo.get_topic_info()

    temas = []
    sin_tema = 0
    for _, row in info.iterrows():
        if row['Topic'] == -1:
            sin_tema = int(row['Count'])
            continue
        palabras = [palabra for palabra, _peso in modelo.get_topic(row['Topic'])][:6]
        temas.append({
            'tema': int(row['Topic']),
            'palabras_clave': palabras,
            'tamano': int(row['Count']),
            'porcentaje': round(row['Count'] / n * 100, 1),
        })
    temas.sort(key=lambda t: t['tamano'], reverse=True)
    return temas, round(sin_tema / n * 100, 1)


def modelar_topicos(momentos):
    from jornadas.models import Pregunta
    from participantes.models import Respuesta

    resultado = {}
    preguntas_abiertas = Pregunta.objects.filter(momento__in=momentos, tipo=Pregunta.TIPO_ABIERTA)
    for pregunta in preguntas_abiertas:
        textos = list(
            Respuesta.objects.filter(pregunta=pregunta)
            .exclude(texto_libre='')
            .values_list('texto_libre', flat=True)
        )
        if len(textos) < MIN_RESPUESTAS_TOPICOS:
            resultado[str(pregunta.id)] = {
                'pregunta': pregunta.texto,
                'muestra_insuficiente': True,
                'total_respuestas': len(textos),
                'temas': [],
            }
            continue

        temas, sin_tema_pct = _run_bertopic(textos)
        resultado[str(pregunta.id)] = {
            'pregunta': pregunta.texto,
            'muestra_insuficiente': False,
            'total_respuestas': len(textos),
            'temas': temas,
            'sin_tema_pct': sin_tema_pct,
        }
    return resultado


# ---------------------------------------------------------------------------
# Narrativa (LLM).
# ---------------------------------------------------------------------------

def _formatear_contexto(jornada, alcance_label, estadisticas, topicos):
    lineas = [
        f"Jornada: {jornada.nombre} — alcance del reporte: {alcance_label}.",
        f"Participantes totales en la jornada: {estadisticas['total_participantes']}.",
        f"Participantes que respondieron algo en este alcance: "
        f"{estadisticas['participantes_que_respondieron']} "
        f"({estadisticas['tasa_participacion']}% de participación).",
        '',
    ]
    for pregunta in estadisticas['preguntas']:
        lineas.append(f"Pregunta — [{pregunta['momento_titulo']}] {pregunta['texto']}")
        lineas.append(f"  Total de respuestas recibidas: {pregunta['total_respuestas']}.")
        if pregunta['tipo'] == 'abierta':
            lineas.append(f"  Respuestas de texto no vacías: {pregunta['respuestas_no_vacias']}.")
            temas_p = topicos.get(str(pregunta['pregunta_id']))
            if temas_p:
                if temas_p['muestra_insuficiente']:
                    lineas.append('  Muestra insuficiente para identificar temas recurrentes.')
                elif not temas_p['temas']:
                    lineas.append('  No se identificaron temas recurrentes claros en las respuestas.')
                else:
                    for tema in temas_p['temas']:
                        palabras = ', '.join(tema['palabras_clave'])
                        lineas.append(
                            f"  Tema recurrente ({tema['porcentaje']}% · {tema['tamano']} "
                            f"respuestas): {palabras}."
                        )
                    lineas.append(f"  Respuestas sin tema claro: {temas_p['sin_tema_pct']}%.")
        else:
            for opcion in pregunta.get('conteo_opciones', []):
                lineas.append(f"  - {opcion['texto']}: {opcion['conteo']} respuestas.")
        lineas.append('')
    return '\n'.join(lineas)


def generar_narrativa(plantilla, contexto_texto):
    """Devuelve (texto, error). `texto` es None si falló o se pasó del tiempo — nunca lanza
    excepción; `error` queda disponible para diagnóstico aunque el reporte igual se complete con
    el texto de respaldo."""
    system = BASE_SYSTEM_PROMPT
    if plantilla and plantilla.prompt_sistema:
        system += '\n\nInstrucciones adicionales de estilo del equipo organizador:\n' + plantilla.prompt_sistema

    resultado = {}

    def _run():
        try:
            llm = _get_llm()
            salida = llm.create_chat_completion(
                messages=[
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': contexto_texto},
                ],
                max_tokens=900, temperature=0.5,
            )
            resultado['texto'] = salida['choices'][0]['message']['content'].strip()
        except Exception as exc:  # noqa: BLE001 — cualquier falla del modelo cae a texto de respaldo
            resultado['error'] = str(exc)

    hilo = threading.Thread(target=_run, daemon=True)
    hilo.start()
    hilo.join(timeout=GENERATION_TIMEOUT_SECONDS)

    if hilo.is_alive():
        return None, f'Tiempo de espera agotado ({GENERATION_TIMEOUT_SECONDS}s).'
    if not resultado.get('texto'):
        return None, resultado.get('error', 'El modelo no devolvió texto.')
    return resultado['texto'], None


# ---------------------------------------------------------------------------
# Orquestador — corre en un hilo en background lanzado desde la vista.
# ---------------------------------------------------------------------------

def procesar_reporte(reporte_id):
    close_old_connections()
    from .models import Reporte

    reporte = None
    try:
        reporte = Reporte.objects.select_related('jornada', 'plantilla').get(pk=reporte_id)
        reporte.estado = Reporte.ESTADO_PROCESANDO
        reporte.save(update_fields=['estado'])

        momentos = list(reporte.momentos.all()) or list(reporte.jornada.momentos.all())
        if not momentos:
            raise ValueError('La jornada no tiene momentos para analizar.')

        estadisticas = calcular_estadisticas(reporte.jornada, momentos)
        topicos = modelar_topicos(momentos)

        alcance_label = dict(Reporte.ALCANCE_CHOICES)[reporte.alcance]
        contexto = _formatear_contexto(reporte.jornada, alcance_label, estadisticas, topicos)
        texto, error_narrativa = generar_narrativa(reporte.plantilla, contexto)

        reporte.estadisticas = estadisticas
        reporte.topicos = topicos
        reporte.texto_reporte = texto or FALLBACK_TEXTO
        reporte.modelo_usado = DEFAULT_MODEL_FILE if texto else ''
        reporte.error_mensaje = '' if texto else f'Narrativa no generada: {error_narrativa}'
        reporte.estado = Reporte.ESTADO_COMPLETO
        reporte.completado_en = timezone.now()
        reporte.save()
    except Exception as exc:  # noqa: BLE001 — nunca debe dejar el hilo morir en silencio
        if reporte is not None:
            reporte.estado = Reporte.ESTADO_ERROR
            reporte.error_mensaje = str(exc)
            reporte.save(update_fields=['estado', 'error_mensaje'])
    finally:
        close_old_connections()
