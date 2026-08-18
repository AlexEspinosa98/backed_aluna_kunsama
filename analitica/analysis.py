"""Análisis jerárquico de una jornada: jornada → momento → pregunta, con un LLM local
(`Qwen2.5-3B-Instruct`, cuantizado GGUF, servido con `llama-cpp-python` — sin GPU, sin `torch`;
mismo enfoque ya probado en el repo hermano `aluna_propositos_backend/backend/catalog/ai_analysis.py`)
actuando como varios agentes chicos en vez de uno solo con todo el contexto encima.

Decisión de diseño central, igual que en el repo hermano: **los números nunca dependen del LLM**.
Las estadísticas y los tópicos (BERTopic) son 100% determinísticos; el modelo solo redacta prosa
sobre esos datos ya calculados. Cada agente además solo ve los datos de **su propio nivel** — nunca
el detalle completo de la jornada — así que el tamaño del contexto no escala con la cantidad de
preguntas/momentos de la jornada (a diferencia de la versión anterior de una sola llamada, que
llegó a superar la ventana de contexto del modelo con una jornada real de 34 preguntas).

    Por pregunta:                      Por momento:                 Jornada completa:
      estadísticas + (BERTopic si         agente_momento(              agente_jornada(
      hay muestra, si no extracción       [descripciones               [síntesis de
      directa por LLM)         ─┐          de sus preguntas])           sus momentos])
      agente_pregunta(datos) ───┴──────────────┴──────────────────────────┘

    Total: N (preguntas) + M (momentos) + 1 llamadas al LLM, todas secuenciales sobre la misma
    instancia de `Llama` cacheada. Cada agente falla de forma aislada (nunca tumba el reporte
    completo): si una llamada falla o se pasa del tiempo, esa pieza queda con un aviso corto en
    vez de descripción generada, y el resto del análisis sigue su curso.
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
# Cada llamada de agente ve un contexto chico y acotado (una pregunta, o las descripciones ya
# resumidas de un nivel inferior) — este timeout es por llamada, no por reporte completo.
GENERATION_TIMEOUT_SECONDS = 90

BASE_SYSTEM_PROMPT = (
    "Eres un analista de datos que redacta el reporte de una jornada participativa para su "
    "equipo organizador. Usa EXCLUSIVAMENTE los datos que se te entregan a continuación — nunca "
    "inventes cifras, porcentajes, temas ni citas que no estén en esos datos. Si un dato no está "
    "disponible, no lo menciones. Escribe en español, en prosa clara, sin viñetas innecesarias."
)

FALLBACK_TEXTO = (
    'No se pudo generar la síntesis narrativa automáticamente. A continuación se muestra el '
    'análisis por momento y por pregunta.'
)

TIPO_GRAFICA_POR_TIPO_PREGUNTA = {'unica': 'pastel', 'multiple': 'barras'}


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
                    model_path=str(MODEL_PATH), n_ctx=4096,
                    n_threads=os.cpu_count(), verbose=False,
                )
    return _llm_instance


def _llamar_llm(system, user, max_tokens=250, temperature=0.5):
    """Una llamada de agente al LLM. Devuelve (texto, error) — nunca lanza excepción; `error`
    queda disponible para diagnóstico cuando `texto` es None."""
    resultado = {}

    def _run():
        try:
            llm = _get_llm()
            salida = llm.create_chat_completion(
                messages=[
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': user},
                ],
                max_tokens=max_tokens, temperature=temperature,
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
# Tópicos (BERTopic) para muestras grandes — determinístico, sin LLM.
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
    # Verbos modales/auxiliares: como las preguntas se frasean "¿Qué debería...?", casi toda
    # respuesta los repite, y no discriminan entre temas.
    'debe', 'deben', 'debería', 'deberían', 'debemos', 'debiera', 'debieran',
    'puede', 'pueden', 'podría', 'podrían', 'podemos', 'quiero', 'quiere', 'quieren', 'creo',
    'considero', 'considera', 'consideran', 'pienso', 'siento', 'debía', 'debían',
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
    for _, row in info.iterrows():
        if row['Topic'] == -1:
            continue
        palabras = [palabra for palabra, _peso in modelo.get_topic(row['Topic'])][:6]
        temas.append({'palabras_clave': palabras, 'tamano': int(row['Count'])})
    temas.sort(key=lambda t: t['tamano'], reverse=True)
    return temas


def _extraer_valores_llm(textos):
    """Para muestras chicas (no alcanza para BERTopic): el propio LLM lee las respuestas crudas
    (son pocas) y extrae frases características tomadas/parafraseadas de ellas — no hay riesgo de
    invención relevante porque debe basarse en lo dado, a diferencia de redactar sobre datos ya
    resumidos."""
    system = (
        "Lees un grupo pequeño de respuestas abiertas de una encuesta. Devuelve entre 2 y 5 "
        "frases cortas (3 a 6 palabras) que resuman los temas o ideas que aparecen, tomadas o "
        "parafraseadas directamente de las respuestas dadas — nunca agregues ideas que no estén "
        "ahí. Responde SOLO con las frases, una por línea, sin numerarlas ni agregar nada más."
    )
    user = '\n'.join(f'- {t}' for t in textos)
    texto, error = _llamar_llm(system, user, max_tokens=150, temperature=0.4)
    if not texto:
        return [], error
    frases = [linea.strip('-• ').strip() for linea in texto.splitlines() if linea.strip()]
    return frases[:5], None


# ---------------------------------------------------------------------------
# Agente de pregunta.
# ---------------------------------------------------------------------------

def _estadisticas_pregunta(pregunta):
    from participantes.models import Respuesta

    respuestas_qs = Respuesta.objects.filter(pregunta=pregunta)
    if pregunta.tipo == 'abierta':
        return {
            'total_respuestas': respuestas_qs.count(),
            'respuestas_no_vacias': respuestas_qs.exclude(texto_libre='').count(),
        }
    return {
        'total_respuestas': respuestas_qs.count(),
        'conteo_opciones': [
            {'opcion_id': o.id, 'texto': o.texto, 'conteo': respuestas_qs.filter(opciones=o).count()}
            for o in pregunta.opciones.all()
        ],
    }


def _agente_pregunta_descripcion(pregunta, estad, valores_caracteristicos, metodo_valores):
    system = (
        "Eres un analista de datos. Redacta una descripción breve (2 a 3 frases) de los "
        "resultados de UNA pregunta de encuesta, usando EXCLUSIVAMENTE los datos entregados a "
        "continuación — nunca inventes cifras ni ideas que no estén ahí. Español, prosa clara."
    )
    if pregunta.tipo == 'abierta':
        lineas = [
            f"Respuestas de texto no vacías: {estad['respuestas_no_vacias']} "
            f"(de {estad['total_respuestas']} recibidas)."
        ]
        if metodo_valores == 'sin_datos':
            lineas.append('No se recibieron respuestas.')
        elif metodo_valores == 'insuficiente':
            lineas.append('Muestra insuficiente para identificar patrones robustos.')
        elif valores_caracteristicos:
            lineas.append('Temas/frases recurrentes: ' + '; '.join(valores_caracteristicos) + '.')
        else:
            lineas.append('No se identificaron patrones claros en las respuestas.')
    else:
        lineas = [f"Total de respuestas: {estad['total_respuestas']}."]
        for opcion in estad.get('conteo_opciones', []):
            lineas.append(f"- {opcion['texto']}: {opcion['conteo']} respuestas.")
    texto, error = _llamar_llm(system, '\n'.join(lineas), max_tokens=200, temperature=0.5)
    return texto or f'(Sin descripción automática — {error})'


def analizar_pregunta(pregunta):
    """Analiza una pregunta de forma aislada: estadísticas + (para abiertas) tópicos/frases +
    descripción del agente de pregunta. Nunca lanza excepción — una falla puntual del LLM solo
    deja un aviso corto en `descripcion`, no tumba el resto del análisis."""
    estad = _estadisticas_pregunta(pregunta)

    if pregunta.tipo == 'abierta':
        from participantes.models import Respuesta
        textos = list(
            Respuesta.objects.filter(pregunta=pregunta)
            .exclude(texto_libre='')
            .values_list('texto_libre', flat=True)
        )
        if not textos:
            valores, metodo = [], 'sin_datos'
        elif len(textos) >= MIN_RESPUESTAS_TOPICOS:
            temas = _run_bertopic(textos)
            valores = [', '.join(t['palabras_clave']) for t in temas]
            metodo = 'bertopic'
        else:
            valores, error = _extraer_valores_llm(textos)
            metodo = 'llm' if valores else 'insuficiente'

        descripcion = _agente_pregunta_descripcion(pregunta, estad, valores, metodo)
        return {
            'pregunta_id': pregunta.id,
            'tipo': pregunta.tipo,
            'tipo_grafica': None,
            'total_respuestas': estad['total_respuestas'],
            'descripcion': descripcion,
            'valores_caracteristicos': valores,
            'metodo_valores': metodo,
        }

    descripcion = _agente_pregunta_descripcion(pregunta, estad, None, 'conteo')
    return {
        'pregunta_id': pregunta.id,
        'tipo': pregunta.tipo,
        'tipo_grafica': TIPO_GRAFICA_POR_TIPO_PREGUNTA.get(pregunta.tipo),
        'total_respuestas': estad['total_respuestas'],
        'descripcion': descripcion,
        'valores_caracteristicos': estad['conteo_opciones'],
        'metodo_valores': 'conteo',
    }


# ---------------------------------------------------------------------------
# Agente de momento.
# ---------------------------------------------------------------------------

def analizar_momento(momento):
    preguntas = momento.preguntas.all().order_by('orden')
    analisis_preguntas = [analizar_pregunta(p) for p in preguntas]

    system = (
        "Eres un analista de datos. Redacta una síntesis breve (2 a 4 frases) de UN momento de "
        "una jornada participativa, integrando las descripciones ya redactadas de sus preguntas "
        "— no repitas pregunta por pregunta, encuentra el hilo común. No agregues datos que no "
        "estén en las descripciones dadas. Español."
    )
    user = '\n'.join(f"- {p['descripcion']}" for p in analisis_preguntas)
    descripcion_general, error = _llamar_llm(system, user, max_tokens=250, temperature=0.5)

    return {
        'momento_id': momento.id,
        'descripcion_general': descripcion_general or f'(Sin síntesis automática — {error})',
        'preguntas': analisis_preguntas,
    }


# ---------------------------------------------------------------------------
# Agente de jornada.
# ---------------------------------------------------------------------------

def analizar_jornada(plantilla, momentos_analisis, participacion):
    system = BASE_SYSTEM_PROMPT
    if plantilla and plantilla.prompt_sistema:
        system += '\n\nInstrucciones adicionales de estilo del equipo organizador:\n' + plantilla.prompt_sistema

    lineas = [
        f"Participantes totales: {participacion['total_participantes']}.",
        f"Participantes que respondieron: {participacion['participantes_que_respondieron']} "
        f"({participacion['tasa_participacion']}%).",
        '',
    ]
    for m in momentos_analisis:
        lineas.append(f"- {m['descripcion_general']}")
    return _llamar_llm(system, '\n'.join(lineas), max_tokens=700, temperature=0.5)


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
        momentos.sort(key=lambda m: m.orden)

        from participantes.models import Participante, Respuesta

        from jornadas.models import Pregunta

        total_participantes = Participante.objects.filter(jornada=reporte.jornada).count()
        preguntas_scope = Pregunta.objects.filter(momento__in=momentos)
        participantes_respondieron = set(
            Respuesta.objects.filter(pregunta__in=preguntas_scope, participante__isnull=False)
            .values_list('participante_id', flat=True)
            .distinct()
        )
        tasa = (
            round(len(participantes_respondieron) / total_participantes * 100, 1)
            if total_participantes else 0.0
        )
        participacion = {
            'total_participantes': total_participantes,
            'participantes_que_respondieron': len(participantes_respondieron),
            'tasa_participacion': tasa,
        }

        momentos_analisis = [analizar_momento(m) for m in momentos]

        texto, error_narrativa = analizar_jornada(reporte.plantilla, momentos_analisis, participacion)

        reporte.analisis = {'participacion': participacion, 'momentos': momentos_analisis}
        reporte.texto_reporte = texto or FALLBACK_TEXTO
        reporte.modelo_usado = DEFAULT_MODEL_FILE if texto else ''
        reporte.error_mensaje = '' if texto else f'Síntesis de jornada no generada: {error_narrativa}'
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
