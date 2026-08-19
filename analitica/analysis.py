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

    Total: N (preguntas) + M (momentos) + 1 llamadas al LLM. Como cada agente solo ve los datos de
    su propio nivel, las N preguntas de TODA la jornada son independientes entre sí (igual que,
    después, las M síntesis de momento) — así que corren en paralelo sobre un pool de
    `LLM_POOL_SIZE` instancias de `Llama` (una sola instancia solo puede atender una inferencia a
    la vez; instancias distintas sí pueden hacerlo en simultáneo). Solo la síntesis final de
    jornada, que necesita las M síntesis de momento ya listas, sigue siendo una llamada aislada al
    final. Cada agente falla de forma aislada (nunca tumba el reporte completo): si una llamada
    falla o se pasa del tiempo, esa pieza queda con un aviso corto en vez de descripción generada,
    y el resto del análisis sigue su curso.

Metodología de codificación temática del equipo: un `Momento` puede traer `categorias_semilla`
(lista de categorías predefinidas por eje temático, ej. EIBIC o Innovación y Emprendimiento). Si
las trae, se usan como candidatos de tema en vez de dejar que BERTopic los descubra desde cero —
el LLM las clasifica igual, pero solo puede agregar como máximo una categoría nueva por pregunta
si de verdad ninguna encaja (`_etiquetar_y_clasificar(permitir_categoria_nueva=True)`), y cada
tema resultante queda marcado con `origen` ('semilla' o 'inductivo'). Además, para preguntas de
momentos `tipo='mesa'` (consenso, no reflexión individual) se calcula `nivel_acuerdo` —qué tan de
acuerdo estuvieron las mesas entre sí para cada tema— con el mismo patrón de pista determinística +
confirmación del LLM que ya usa `tipo_grafica` (`_pista_nivel_acuerdo` / `_extraer_nivel_acuerdo`).
"""
import os
import queue
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.db import close_old_connections
from django.utils import timezone

MODELS_DIR = Path(__file__).resolve().parent / '.models'
DEFAULT_MODEL_REPO = 'Qwen/Qwen2.5-3B-Instruct-GGUF'
DEFAULT_MODEL_FILE = os.environ.get('KUNSAMU_LLM_MODEL_FILE', 'qwen2.5-3b-instruct-q4_k_m.gguf')
MODEL_PATH = MODELS_DIR / DEFAULT_MODEL_FILE

EMBEDDING_MODEL_NAME = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'

MIN_RESPUESTAS_TOPICOS = 8
# BERTopic solo DESCUBRE temas candidatos (nunca más de estos) — la cuantificación real de cada
# uno viene después, de que el LLM clasifique cada respuesta (ver `_etiquetar_y_clasificar`).
MAX_TEMAS_CANDIDATOS = 5
# Tope de respuestas que se envían en la llamada de clasificación, para que el prompt nunca escale
# sin límite con el tamaño de la jornada (mismo espíritu que ya obligó a acotar el resto del
# pipeline — ver la nota de diseño al inicio del archivo).
MAX_RESPUESTAS_CLASIFICACION = 60
# Cada llamada de agente ve un contexto chico y acotado (una pregunta, o las descripciones ya
# resumidas de un nivel inferior) — este timeout es por llamada, no por reporte completo.
# Subido de 90s a 150s cuando se aumentaron los max_tokens de cada agente (análisis más robusto,
# ver los distintos `max_tokens=` más abajo): con el presupuesto de tokens más alto, 90s hacía que
# la mayoría de las preguntas de un reporte real cayeran a "(Sin descripción automática...)" por
# timeout — validado contra datos reales (reporte #26, jornada-agil-2).
GENERATION_TIMEOUT_SECONDS = 150
# Preguntas y momentos son independientes entre sí (cada uno solo ve sus propios datos, ver nota
# de diseño arriba), así que no hay razón para analizarlos uno a la vez: el servidor tiene núcleos
# de sobra, así que en vez de una sola instancia del modelo usando todos los hilos para UNA
# llamada a la vez, se reparten entre varias instancias que procesan preguntas EN PARALELO. Esto
# no cambia una sola palabra de lo que se genera — mismo contenido, mismos prompts — solo cuánto
# tarda en generarse.
# Probado contra datos reales: con 8 instancias (6 hilos c/u en un servidor de 48 núcleos) las
# llamadas individuales se vuelven tan lentas que varias chocan con GENERATION_TIMEOUT_SECONDS y
# la clasificación falla (cae a resultado sin conteo) — con 6 (8 hilos c/u) el mismo lote de
# preguntas terminó sin ningún fallo. El rendimiento total no mejora mucho más allá de este punto
# porque el CPU total es fijo (48 núcleos): más instancias == menos hilos cada una == llamadas
# individuales más lentas, así que la ganancia de más paralelismo se cancela con la pérdida de
# velocidad por instancia. 6 es el punto validado que da paralelismo real sin arriesgar timeouts.
LLM_POOL_SIZE = int(os.environ.get('KUNSAMU_LLM_POOL_SIZE', '6'))

def _instrucciones_plantilla(plantilla):
    """Instrucciones adicionales de la plantilla activa (`PlantillaAnalisis.prompt_sistema`,
    editable por el equipo vía POST/PATCH /api/admin/plantillas-analisis/) — se aplican en TODOS
    los niveles del análisis (pregunta, momento, jornada), no solo en la síntesis final, para que
    ajustar tono o profundidad desde la plantilla tenga efecto real en todo el reporte, no solo en
    su último párrafo."""
    if plantilla and plantilla.prompt_sistema:
        return '\n\nInstrucciones adicionales del equipo organizador:\n' + plantilla.prompt_sistema
    return ''


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

GRAFICA_TAG_RE = re.compile(r'GRAFICA:\s*(pastel|barras|radar)\b', re.IGNORECASE)
NIVEL_ACUERDO_RE = re.compile(
    r'NIVEL_ACUERDO:\s*(consenso_fuerte|consenso_moderado|tension_estrategica|tema_emergente|'
    r'asunto_pendiente)\b',
    re.IGNORECASE,
)


def _extraer_etiqueta(texto, patron):
    """Busca la etiqueta que matchea `patron` (con un grupo de captura) en cualquier parte del
    texto del LLM (no siempre aparece en su propia línea final pese a la instrucción, y a veces el
    modelo la repite más de una vez) y retira TODAS las apariciones, cada una junto con la oración
    que la contiene, para que no queden fragmentos crudos como "GRAFICA: radar" en la descripción
    mostrada al usuario. Devuelve (valor_o_None, texto_limpio) — el valor es el de la primera
    aparición. Genérica: la misma mecánica sirve para cualquier tag `ETIQUETA: valor`, no solo
    `GRAFICA:` — ver `_extraer_tipo_grafica` y `_extraer_nivel_acuerdo`."""
    valor = None
    while True:
        m = patron.search(texto)
        if not m:
            break
        if valor is None:
            valor = m.group(1).lower()
        inicio = texto.rfind('.', 0, m.start())
        inicio = inicio + 1 if inicio != -1 else 0
        fin = texto.find('.', m.end())
        fin = fin + 1 if fin != -1 else len(texto)
        texto = texto[:inicio] + texto[fin:]
    return valor, re.sub(r'\s+', ' ', texto).strip()


def _extraer_tipo_grafica(texto):
    return _extraer_etiqueta(texto, GRAFICA_TAG_RE)


def _extraer_nivel_acuerdo(texto):
    return _extraer_etiqueta(texto, NIVEL_ACUERDO_RE)


def _tipo_grafica_por_defecto(tipo_pregunta, num_opciones):
    """Respaldo determinístico si el LLM no elige una gráfica válida (o falla): con pocas
    opciones mutuamente excluyentes un pastel/barras simple es más claro; con 4+ opciones un
    radar muestra mejor la forma general de hacia dónde se inclina el público entre todas."""
    if num_opciones >= 4:
        return 'radar'
    return 'pastel' if tipo_pregunta == 'unica' else 'barras'


# ---------------------------------------------------------------------------
# Modelo LLM (llama.cpp) — pool de instancias perezoso y único por proceso.
# ---------------------------------------------------------------------------

_llm_pool = None
_llm_pool_lock = threading.Lock()


def _crear_instancia_llm():
    from llama_cpp import Llama
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f'No se encontró el modelo en {MODEL_PATH}. Corre '
            "'python manage.py download_llm_model' primero."
        )
    # Los hilos disponibles se reparten entre las instancias del pool en vez de dárselos todos a
    # una sola — con LLM_POOL_SIZE llamadas corriendo de verdad en paralelo, cada una individual
    # tarda un poco más que si tuviera el CPU entero para ella (ver más abajo), pero el conjunto
    # avanza LLM_POOL_SIZE veces más rápido, que es lo que importa para el tiempo total del reporte.
    hilos = max(1, (os.cpu_count() or LLM_POOL_SIZE) // LLM_POOL_SIZE)
    return Llama(model_path=str(MODEL_PATH), n_ctx=4096, n_threads=hilos, verbose=False)


def _get_llm_pool():
    """Pool de `LLM_POOL_SIZE` instancias `Llama` independientes, una por 'carril' de paralelismo.
    llama.cpp no soporta llamadas concurrentes de inferencia sobre la MISMA instancia — corrompen
    el contexto interno y crashean el proceso entero con un GGML_ASSERT nativo (no es una excepción
    de Python, ningún try/except lo detiene). Esto pasó en producción una vez: dos hilos llamando
    al modelo a la vez tumbaron el worker y dejaron dos reportes huérfanos en 'procesando' para
    siempre. La lección de ese incidente NO era "nunca paralelizar" sino "nunca compartir una
    instancia entre hilos" — instancias DISTINTAS sí pueden inferir al mismo tiempo sin problema.
    El `queue.Queue` es el mecanismo de exclusión: sacar una instancia (`get`) se la reserva a ese
    hilo hasta que la devuelve (`put`), así nunca hay dos hilos usando la misma instancia a la vez,
    sin necesidad de un lock global que serialice todo el pool."""
    global _llm_pool
    if _llm_pool is None:
        with _llm_pool_lock:
            if _llm_pool is None:
                pool = queue.Queue()
                for _ in range(LLM_POOL_SIZE):
                    pool.put(_crear_instancia_llm())
                _llm_pool = pool
    return _llm_pool


def _llamar_llm(system, user, max_tokens=250, temperature=0.5):
    """Una llamada de agente al LLM. Devuelve (texto, error) — nunca lanza excepción; `error`
    queda disponible para diagnóstico cuando `texto` es None."""
    resultado = {}

    def _run():
        pool = _get_llm_pool()
        llm = pool.get()
        try:
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
        finally:
            pool.put(llm)

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
    # Verbos auxiliares/genéricos de alta frecuencia (haber, hacer, tener, ver, dar, ir, decir,
    # saber, conjugados) — no discriminan tema, solo rellenan casi cualquier respuesta.
    'haber', 'había', 'habían', 'habrá', 'habría', 'hube', 'hubo', 'hubiera', 'haya',
    'hemos', 'han', 'he', 'has', 'ha',
    'hacer', 'hace', 'hacen', 'hacía', 'hacían', 'hizo', 'hicieron', 'haciendo', 'hecho', 'haremos',
    'tener', 'tiene', 'tienen', 'tenía', 'tenían', 'tuvo', 'tuvieron', 'teniendo', 'tengo', 'tenemos',
    'ver', 'vemos', 'ven', 'veo', 'vio', 'vieron', 'veía',
    'dar', 'da', 'dan', 'dio', 'dieron', 'daba', 'damos',
    'ir', 'va', 'van', 'iba', 'iban', 'vamos', 'voy',
    'decir', 'dice', 'dicen', 'dijo', 'dijeron', 'decía', 'digo',
    'saber', 'sabe', 'saben', 'sabía', 'supo',
    'hacia', 'aquí', 'allí', 'ahí', 'así', 'cada', 'cómo', 'dentro', 'fuera', 'igual', 'incluso',
    'luego', 'mientras', 'siempre', 'tal', 'tras', 'vez', 'veces',
]


def _descubrir_topicos_bertopic(textos):
    """Corre BERTopic para DESCUBRIR hasta `MAX_TEMAS_CANDIDATOS` temas candidatos — solo de qué
    hablan los grupos que encuentra (palabras clave + un par de respuestas de ejemplo reales por
    grupo). A propósito, NO calcula aquí el tamaño/porcentaje final de cada tema: en muestras
    chicas, HDBSCAN separa mal los temas y deja muchas respuestas sueltas como "ruido" (tópico -1,
    excluido del conteo), así que un % basado en el clustering crudo subestima sistemáticamente. La
    cuantificación real sale de que el LLM clasifique CADA respuesta en uno de estos temas
    candidatos — ver `_etiquetar_y_clasificar`, que se llama justo después con el resultado de esta
    función."""
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
    vectorizer_model = CountVectorizer(stop_words=STOPWORDS_ES, ngram_range=(1, 3), min_df=1)
    modelo = BERTopic(
        embedding_model=_get_embedder(), umap_model=umap_model, hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer_model, verbose=False, calculate_probabilities=False,
        nr_topics=MAX_TEMAS_CANDIDATOS,
    )
    modelo.fit_transform(textos)
    info = modelo.get_topic_info()

    temas = []
    for _, row in info.iterrows():
        if row['Topic'] == -1:
            continue
        palabras = [palabra for palabra, _peso in modelo.get_topic(row['Topic'])][:6]
        try:
            ejemplos = modelo.get_representative_docs(row['Topic'])[:2]
        except Exception:  # noqa: BLE001 — sin ejemplos, el LLM etiqueta solo con las palabras clave
            ejemplos = []
        temas.append({'palabras_clave': palabras, 'ejemplos': ejemplos, '_tamano_bruto': int(row['Count'])})
    # El tamaño bruto del clustering solo ordena qué candidatos van primero en el prompt de
    # clasificación — no se expone al resto del pipeline (ver docstring).
    temas.sort(key=lambda t: t['_tamano_bruto'], reverse=True)
    return [{'palabras_clave': t['palabras_clave'], 'ejemplos': t['ejemplos']} for t in temas[:MAX_TEMAS_CANDIDATOS]]


TEMA_ETIQUETA_RE = re.compile(r'^(\d+)\s*[:.\)]\s*(.+)$')
CLASIFICACION_RE = re.compile(r'^(\d+)\s*[:.\)]\s*(\d+)')


def _parsear_temas_y_clasificacion(texto):
    seccion_temas = re.search(r'TEMAS:\s*(.*?)(?=CLASIFICACION:|$)', texto, re.IGNORECASE | re.DOTALL)
    seccion_clas = re.search(r'CLASIFICACION:\s*(.*)', texto, re.IGNORECASE | re.DOTALL)

    etiquetas = {}
    if seccion_temas:
        for linea in seccion_temas.group(1).splitlines():
            m = TEMA_ETIQUETA_RE.match(linea.strip().lstrip('-•*').strip())
            if m:
                etiqueta = m.group(2).strip().strip('*').strip()
                # Respaldo: el modelo a veces copia literalmente el marcador de formato ('<...>')
                # o repite la línea "Palabras clave: ..." del prompt en vez de redactar su propia
                # frase — ninguno de los dos es una etiqueta usable, se limpian aquí.
                etiqueta = etiqueta.strip('<>').strip().strip('"\'').strip()
                if etiqueta.lower().startswith('palabras clave'):
                    etiqueta = etiqueta.split(':', 1)[-1].strip() if ':' in etiqueta else ''
                if etiqueta:
                    etiquetas[int(m.group(1))] = etiqueta

    asignaciones = {}
    if seccion_clas:
        for linea in seccion_clas.group(1).splitlines():
            m = CLASIFICACION_RE.match(linea.strip().lstrip('-•*').strip())
            if m:
                asignaciones[int(m.group(1))] = int(m.group(2))

    return etiquetas, asignaciones


def _etiquetar_y_clasificar(textos, temas_candidatos, permitir_categoria_nueva=False):
    """Le da a cada tema candidato una etiqueta corta y natural, y clasifica CADA una de las
    respuestas dadas en el tema cuya etiqueta le quede mejor — esta clasificación, no el
    clustering crudo, es la que determina el tamaño/porcentaje final de cada tema.

    Dos modos, según de dónde vinieron `temas_candidatos`:
    - `permitir_categoria_nueva=False` (por defecto): los candidatos los descubrió BERTopic desde
      cero (`_descubrir_topicos_bertopic`) — se le pide al LLM que les redacte una etiqueta
      natural a partir de sus palabras clave/ejemplos.
    - `permitir_categoria_nueva=True`: los candidatos son categorías SEMILLA predefinidas por el
      equipo (`Momento.categorias_semilla`, ver metodología de codificación temática) — sus
      nombres ya son la etiqueta final, no se reformulan; el LLM solo puede agregar como máximo
      UNA categoría nueva si de verdad ninguna de las dadas encaja (codificación inductiva
      acotada). Cada tema resultante queda marcado con `origen`: `'semilla'` si es uno de los
      dados, `'inductivo'` si es el que el LLM agregó.

    Devuelve (lista_de_temas_con_conteo_o_None, error)."""
    muestra = textos[:MAX_RESPUESTAS_CLASIFICACION]

    if permitir_categoria_nueva:
        instrucciones_etiquetas = (
            "Los nombres de los temas ya están dados (son categorías predefinidas del eje "
            "temático) — reprodúcelos EXACTAMENTE en la sección TEMAS, sin reformularlos. Solo si "
            "una respuesta no encaja razonablemente en NINGUNA, puedes agregar UNA categoría "
            "nueva y breve al final de la lista de TEMAS — como máximo una, y solo si es "
            "genuinamente necesario."
        )
    else:
        instrucciones_etiquetas = (
            "Primero, dale a cada grupo una etiqueta corta y natural en español (3 a 5 palabras, "
            "una frase con sentido — nunca una palabra clave aislada). Las etiquetas van en texto "
            "plano, nunca entre símbolos como '<' '>' o comillas, y nunca repitas la lista de "
            "'Palabras clave' tal cual — redacta una frase propia."
        )

    system = (
        "Eres un analista de datos clasificando respuestas abiertas de una encuesta. Se te dan "
        f"{len(temas_candidatos)} grupos candidatos de tema. " + instrucciones_etiquetas + " "
        "Luego, clasifica CADA una de las respuestas numeradas en el tema cuya etiqueta le quede "
        "mejor. SIEMPRE asigna uno de los temas a cada respuesta, incluso si el encaje no es "
        "perfecto — nunca dejes una respuesta sin clasificar: la clasificación de cada respuesta "
        "es siempre un número de tema, nunca un guion, un '?' ni la palabra 'ninguno'.\n\n"
        "Responde EXACTAMENTE con este formato (usa tus propias etiquetas y números, el ejemplo "
        "de abajo es solo para mostrar la estructura — no la copies), sin texto adicional antes "
        "ni después:\n"
        "TEMAS:\n1: Transparencia en el manejo de datos\n2: Consentimiento informado de las "
        "comunidades\n"
        "CLASIFICACION:\n1: 2\n2: 1\n3: 1\n..."
    )
    lineas = ['GRUPOS CANDIDATOS:']
    for i, tema in enumerate(temas_candidatos, start=1):
        if permitir_categoria_nueva:
            lineas.append(f"{i}. {tema['palabras_clave'][0]}")
        else:
            lineas.append(f"{i}. Palabras clave: {', '.join(tema['palabras_clave'])}.")
            for ejemplo in tema.get('ejemplos') or []:
                lineas.append(f'   Ejemplo: "{ejemplo}"')
    lineas.append('')
    lineas.append('RESPUESTAS A CLASIFICAR:')
    for i, texto in enumerate(muestra, start=1):
        lineas.append(f'{i}. {texto}')

    max_tokens = min(900, 150 + len(temas_candidatos) * 20 + len(muestra) * 10)
    texto_llm, error = _llamar_llm(system, '\n'.join(lineas), max_tokens=max_tokens, temperature=0.2)
    if not texto_llm:
        return None, error

    etiquetas_llm, asignaciones = _parsear_temas_y_clasificacion(texto_llm)

    if permitir_categoria_nueva:
        # Probado contra datos reales: pese a la instrucción de "reprodúcelas EXACTAMENTE", el
        # modelo a veces reformula igual las categorías semilla en la sección TEMAS — así que no
        # se confía en su reproducción. Las semilla se precargan aquí, tal cual las dio el equipo,
        # sin depender de que el LLM las haya listado bien; el único texto que SÍ se toma del LLM
        # es el de una eventual categoría inductiva (el índice justo después de las dadas).
        etiquetas = {i: t['palabras_clave'][0] for i, t in enumerate(temas_candidatos, start=1)}
        limite = len(temas_candidatos) + 1
        if limite in etiquetas_llm:
            etiquetas[limite] = etiquetas_llm[limite]
    else:
        etiquetas = etiquetas_llm

    if not etiquetas or not asignaciones:
        return None, 'El modelo no devolvió el formato de clasificación esperado.'

    conteos = {idx: 0 for idx in etiquetas}
    for idx_respuesta, idx_tema in asignaciones.items():
        # El modelo a veces "alucina" líneas de clasificación para índices de respuesta que no
        # existen (más allá de `muestra`) — sin este chequeo, esas líneas fantasma inflan el
        # conteo total por encima del número real de respuestas.
        if idx_tema in conteos and 1 <= idx_respuesta <= len(muestra):
            conteos[idx_tema] += 1
    if not sum(conteos.values()):
        return None, 'El modelo no clasificó ninguna respuesta en un tema válido.'

    # El porcentaje se calcula sobre el tamaño real de la muestra, no sobre lo que el modelo
    # alcanzó a clasificar — así una clasificación incompleta (el modelo se saltó respuestas) no
    # infla artificialmente el % de los temas que sí alcanzó a asignar.
    temas_final = []
    for idx in sorted(etiquetas, key=lambda i: conteos[i], reverse=True):
        if conteos[idx] <= 0:
            continue
        tema = {
            'tema': etiquetas[idx],
            'tamano': conteos[idx],
            'porcentaje': round(conteos[idx] / len(muestra) * 100, 1),
        }
        if permitir_categoria_nueva:
            # Posicional, no por texto: los candidatos semilla siempre ocupan los índices
            # 1..len(temas_candidatos) en el prompt — cualquier índice más allá de eso solo puede
            # ser la categoría inductiva que el LLM agregó (ya recortada a como mucho 1 arriba).
            tema['origen'] = 'semilla' if idx <= len(temas_candidatos) else 'inductivo'
        temas_final.append(tema)
    if not temas_final:
        return None, 'Ningún tema candidato recibió respuestas clasificadas.'
    return temas_final, None


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


NIVELES_ACUERDO_VALIDOS = (
    'consenso_fuerte', 'consenso_moderado', 'tension_estrategica', 'tema_emergente',
    'asunto_pendiente',
)


def _agente_pregunta_abierta(pregunta, estad, valores_caracteristicos, metodo_valores, plantilla=None):
    """Devuelve (descripcion, tipo_grafica, nivel_acuerdo). `tipo_grafica` solo se decide cuando
    hay datos cuantitativos reales que graficar — 2 o más temas con tamaño/porcentaje conocidos,
    que salen de que el LLM haya clasificado las respuestas en los temas candidatos (método
    `bertopic_llm`). `nivel_acuerdo` además solo aplica en preguntas de momentos de tipo `mesa`
    (comparar "acuerdo entre mesas" no tiene sentido para reflexión individual) — clasifica qué
    tan de acuerdo estuvieron las mesas entre sí para este tema, según la metodología de
    codificación temática del equipo. Con `llm` (muestra chica, frases extraídas libremente sin
    conteo por tema), `bertopic_sin_clasificar` (la clasificación falló y solo quedan las palabras
    clave/categorías crudas), `insuficiente` o `sin_datos` ninguno de los dos se calcula, quedan
    `None`."""
    system = (
        "Eres un analista de datos senior interpretando los resultados de UNA pregunta de "
        "encuesta abierta para un informe institucional que va a leer la Rectoría. Escribe un "
        "análisis robusto y sustancioso — un párrafo de 5 a 8 frases, nunca un resumen "
        "telegráfico de 2 líneas — en español, como haría un analista humano explicándole el "
        "hallazgo en detalle a un colega, no una ficha técnica. Ve directo a la interpretación: "
        "nunca empieces con muletillas como 'Resultados de la encuesta:', 'Los resultados indican "
        "que' o 'Descripción de los resultados:' — esas frases no aportan nada y suenan "
        "robóticas. No te limites a enumerar temas y porcentajes: explica qué significa esa "
        "distribución (¿hay consenso claro o está dividida la opinión?, ¿qué prioriza el grupo y "
        "por qué podría ser así?, ¿cómo se relacionan entre sí los temas principales?, ¿qué "
        "implicación práctica sugiere para la Universidad?). Usa EXCLUSIVAMENTE los datos "
        "entregados a continuación — nunca inventes cifras ni ideas que no estén ahí." +
        _instrucciones_plantilla(plantilla)
    )
    lineas = [
        f"Respuestas de texto no vacías: {estad['respuestas_no_vacias']} "
        f"(de {estad['total_respuestas']} recibidas)."
    ]
    graficable = metodo_valores == 'bertopic_llm' and len(valores_caracteristicos) >= 2
    es_momento_mesa = pregunta.momento.tipo == 'mesa'
    calcula_acuerdo = graficable and es_momento_mesa
    if metodo_valores == 'sin_datos':
        lineas.append('No se recibieron respuestas.')
    elif metodo_valores == 'insuficiente':
        lineas.append('Muestra insuficiente para identificar patrones robustos.')
    elif not valores_caracteristicos:
        lineas.append('No se identificaron patrones claros en las respuestas.')
    elif metodo_valores == 'bertopic_llm':
        for tema in valores_caracteristicos:
            lineas.append(f"- Tema: {tema['tema']} ({tema['tamano']} respuestas, {tema['porcentaje']}%).")
    else:  # 'llm' o 'bertopic_sin_clasificar' — temas/frases sin conteo por tema
        lineas.append('Temas/frases recurrentes: ' + '; '.join(
            t['tema'] for t in valores_caracteristicos
        ) + '.')

    if graficable:
        system += (
            " Luego, en una línea aparte, recomienda la gráfica que mejor muestre hacia "
            "dónde se inclina el público entre los temas encontrados, escribiendo EXACTAMENTE "
            "una de estas líneas: 'GRAFICA: pastel' (pocos temas, uno domina claramente), "
            "'GRAFICA: barras' (comparación simple de tamaños), o 'GRAFICA: radar' (varios temas "
            "— 4 o más — donde interesa ver la forma general de la inclinación entre todos). Si "
            "se te da una nota con una recomendación, síguela salvo que los datos digan "
            "claramente lo contrario."
        )
        pista_grafica = _pista_equilibrio([t['tamano'] for t in valores_caracteristicos], sujeto='los temas')
        if pista_grafica:
            lineas.append(pista_grafica)

    pista_acuerdo = None
    if calcula_acuerdo:
        pista_acuerdo = _pista_nivel_acuerdo(valores_caracteristicos, estad['total_respuestas'])
        system += (
            " Además, en otra línea aparte, clasifica el nivel de acuerdo ENTRE LAS MESAS para "
            "este tema, escribiendo EXACTAMENTE una de estas líneas: 'NIVEL_ACUERDO: "
            "consenso_fuerte' (casi todas las mesas coinciden, sin divergencias sustantivas), "
            "'NIVEL_ACUERDO: consenso_moderado' (la mayoría coincide, con diferencias de alcance "
            "o formulación), 'NIVEL_ACUERDO: tension_estrategica' (hay posiciones claramente "
            "distintas entre mesas que requieren decisión o profundización), 'NIVEL_ACUERDO: "
            "tema_emergente' (aparece en pocas mesas pero introduce un asunto relevante no "
            "previsto), o 'NIVEL_ACUERDO: asunto_pendiente' (el tema requiere información "
            "adicional —análisis jurídico, técnico, financiero o institucional— antes de poder "
            "concluir algo). Si se te da una nota con una recomendación, síguela salvo que los "
            "datos digan claramente lo contrario."
        )
        if pista_acuerdo:
            lineas.append(f'Nota: la forma de la distribución sugiere NIVEL_ACUERDO: {pista_acuerdo}.')

    texto, error = _llamar_llm(system, '\n'.join(lineas), max_tokens=480, temperature=0.5)

    tipo_grafica = None
    nivel_acuerdo = None
    if texto:
        if graficable:
            tipo_grafica, texto = _extraer_tipo_grafica(texto)
            if tipo_grafica not in ('pastel', 'barras', 'radar'):
                tipo_grafica = _tipo_grafica_por_defecto('unica', len(valores_caracteristicos))
        if calcula_acuerdo:
            nivel_acuerdo, texto = _extraer_nivel_acuerdo(texto)
            if nivel_acuerdo not in NIVELES_ACUERDO_VALIDOS:
                # Sin respaldo universal (a diferencia de tipo_grafica): asunto_pendiente no se
                # puede derivar de la forma de la distribución, así que si el LLM no devolvió un
                # tag válido, solo hay pista determinística para 4 de los 5 niveles.
                nivel_acuerdo = pista_acuerdo

    descripcion = texto or f'(Sin descripción automática — {error})'
    return descripcion, tipo_grafica, nivel_acuerdo


def _pista_equilibrio(conteos, sujeto='las opciones'):
    """Un LLM chico (3B) razona mal 'a ojo' sobre la forma de una distribución a partir de una
    tabla de conteos — en pruebas, con instrucciones neutrales terminaba recomendando 'barras'
    casi siempre, sin importar qué tan pareja o desbalanceada fuera. En vez de pedirle que infiera
    el equilibrio, se lo calculamos aquí (determinístico) y se lo entregamos como dato explícito
    — así solo tiene que reaccionar a una pista ya lista, que es una tarea mucho más confiable
    para un modelo de este tamaño. `sujeto` es solo para que la nota se lea natural ("opciones" o
    "temas")."""
    maximo = max(conteos) if conteos else 0
    if maximo == 0 or len(conteos) < 4:
        return None
    minimo = min(conteos)
    parejo = minimo / maximo >= 0.4
    if parejo:
        return (
            f'Nota: los conteos están relativamente parejos entre {sujeto} (ninguna domina '
            'claramente) — con 4 o más así, casi siempre conviene GRAFICA: radar para mostrar la '
            'forma general de la inclinación entre todas a la vez.'
        )
    return (
        f'Nota: los conteos están desbalanceados entre {sujeto} — una o pocas concentran las '
        'respuestas — eso suele mostrarse mejor con GRAFICA: barras o GRAFICA: pastel que con '
        'un radar.'
    )


def _pista_nivel_acuerdo(valores_caracteristicos, num_mesas):
    """Mismo espíritu que `_pista_equilibrio`: calcular determinísticamente la forma de la
    distribución de temas entre mesas y entregarla como hint textual, en vez de pedirle al LLM que
    la infiera de una tabla cruda. Solo cubre los 4 niveles derivables del tamaño relativo de cada
    tema — `asunto_pendiente` es un juicio sobre el CONTENIDO del tema (si requiere análisis
    jurídico/técnico/financiero adicional), no sobre su forma, así que no tiene hint aquí: sin pista
    clara, el LLM decide libremente entre los 5 niveles."""
    if not valores_caracteristicos or not num_mesas:
        return None
    principal = valores_caracteristicos[0]
    resto = valores_caracteristicos[1:]
    cobertura_principal = principal['porcentaje']
    # Umbral relativo, no absoluto: con pocas mesas (4-8, lo típico) una sola dissidencia ya pesa
    # 12-25% del total — un umbral fijo tipo "segundo puesto < 15%" clasificaría un 5-contra-1
    # genuino como 'moderado' en vez de 'fuerte'. 80% de cobertura principal ya es mayoría
    # aplastante sin importar cuántas mesas dejó afuera.
    segundo = resto[0]['porcentaje'] if resto else 0
    if cobertura_principal >= 80:
        return 'consenso_fuerte'
    if cobertura_principal >= 50 and segundo < 30:
        return 'consenso_moderado'
    if segundo >= 30:
        return 'tension_estrategica'
    if resto and resto[-1]['porcentaje'] <= 15:
        return 'tema_emergente'
    return None


def _agente_pregunta_cerrada(pregunta, estad, plantilla=None):
    """Para preguntas `unica`/`multiple`: además de la descripción, el propio LLM elige el tipo
    de gráfica que mejor muestre hacia dónde se inclina el público entre las opciones — pastel
    (pocas, mutuamente excluyentes), barras (comparación simple de conteos) o radar (varias
    opciones, muestra la forma general de la inclinación entre todas). Si el modelo no devuelve
    una elección válida, se usa `_tipo_grafica_por_defecto` como respaldo."""
    opciones = estad.get('conteo_opciones', [])
    system = (
        "Eres un analista de datos senior interpretando los resultados de UNA pregunta de "
        "encuesta de opción cerrada para un informe institucional que va a leer la Rectoría. "
        "Escribe un análisis robusto — 4 a 6 frases, nunca un resumen telegráfico de 2 líneas — "
        "en español, como haría un analista humano explicándole el hallazgo en detalle a un "
        "colega. Ve directo a la interpretación: nunca empieces con muletillas como 'Resultados "
        "de la encuesta:', 'Los resultados indican que' o 'Descripción de los resultados:' — esas "
        "frases no aportan nada y suenan robóticas. No te limites a leer los números en voz alta: "
        "explica qué revela esa inclinación sobre la prioridad del grupo y qué implicación "
        "práctica sugiere. Usa EXCLUSIVAMENTE los datos entregados — nunca inventes cifras. Luego, "
        "en una última línea aparte, recomienda la gráfica que mejor muestre hacia dónde se "
        "inclina el público entre las opciones, escribiendo EXACTAMENTE una de estas tres líneas: "
        "'GRAFICA: pastel' (pocas opciones mutuamente excluyentes), 'GRAFICA: barras' (comparación "
        "simple de conteos), o 'GRAFICA: radar' (varias opciones — 4 o más — donde interesa ver la "
        "forma general de la inclinación entre todas a la vez). Si se te da una nota con una "
        "recomendación, síguela salvo que los datos digan claramente lo contrario." +
        _instrucciones_plantilla(plantilla)
    )
    lineas = [f"Total de respuestas: {estad['total_respuestas']}."]
    for opcion in opciones:
        lineas.append(f"- {opcion['texto']}: {opcion['conteo']} respuestas.")
    pista = _pista_equilibrio([o['conteo'] for o in opciones])
    if pista:
        lineas.append(pista)
    texto, error = _llamar_llm(system, '\n'.join(lineas), max_tokens=380, temperature=0.5)

    tipo_grafica = None
    if texto:
        tipo_grafica, texto = _extraer_tipo_grafica(texto)

    if tipo_grafica not in ('pastel', 'barras', 'radar'):
        tipo_grafica = _tipo_grafica_por_defecto(pregunta.tipo, len(opciones))

    descripcion = texto or f'(Sin descripción automática — {error})'
    return descripcion, tipo_grafica


def _clasificar_topicos(textos, temas_candidatos, permitir_categoria_nueva):
    """Envoltorio compartido para el par 'clasificar o degradar a palabras clave crudas' — usado
    tanto para temas descubiertos por BERTopic como para categorías semilla predefinidas, así el
    respaldo (`bertopic_sin_clasificar`) se comporta igual sin importar de dónde salieron los
    candidatos. Devuelve (valores, metodo)."""
    if not temas_candidatos:
        return [], 'insuficiente'
    valores, _error = _etiquetar_y_clasificar(textos, temas_candidatos, permitir_categoria_nueva)
    if valores:
        return valores, 'bertopic_llm'
    # Respaldo: si la clasificación del LLM falló, se muestran las palabras clave/categorías
    # crudas de cada candidato sin conteo (mejor que no mostrar nada) en vez de tumbar el
    # análisis de la pregunta.
    valores = [
        {'tema': ', '.join(t['palabras_clave']), 'tamano': None, 'porcentaje': None}
        for t in temas_candidatos
    ]
    return valores, 'bertopic_sin_clasificar'


def analizar_pregunta(pregunta, plantilla=None):
    """Analiza una pregunta de forma aislada: estadísticas + (para abiertas) tópicos/frases +
    descripción del agente de pregunta. Nunca lanza excepción — una falla puntual del LLM solo
    deja un aviso corto en `descripcion`, no tumba el resto del análisis. `plantilla` (opcional,
    `PlantillaAnalisis` editable vía /api/admin/plantillas-analisis/) se reenvía a los agentes de
    redacción para que sus instrucciones de tono/profundidad apliquen también a nivel de
    pregunta, no solo en la síntesis final de la jornada."""
    estad = _estadisticas_pregunta(pregunta)

    if pregunta.tipo == 'abierta':
        from participantes.models import Respuesta
        textos = list(
            Respuesta.objects.filter(pregunta=pregunta)
            .exclude(texto_libre='')
            .values_list('texto_libre', flat=True)
        )
        categorias_semilla = pregunta.momento.categorias_semilla
        if not textos:
            valores, metodo = [], 'sin_datos'
        elif categorias_semilla and len(textos) >= 2:
            # Categorías predefinidas por el equipo (metodología de codificación temática): no
            # hace falta descubrirlas con BERTopic, así que tampoco aplica el piso de muestra que
            # protege la calidad del clustering (MIN_RESPUESTAS_TOPICOS) — con solo 2+ respuestas
            # ya hay algo que clasificar. Esto es clave para preguntas de momentos `mesa`, donde
            # la muestra es una por mesa (normalmente pocas, casi nunca llega a
            # MIN_RESPUESTAS_TOPICOS) pero es exactamente donde se necesita nivel_acuerdo.
            temas_candidatos = [{'palabras_clave': [c], 'ejemplos': []} for c in categorias_semilla]
            valores, metodo = _clasificar_topicos(textos, temas_candidatos, permitir_categoria_nueva=True)
        elif len(textos) >= MIN_RESPUESTAS_TOPICOS:
            # BERTopic solo descubre de 3 a 5 temas candidatos (palabras clave + ejemplos); el
            # propio LLM les da una etiqueta natural y clasifica CADA respuesta en uno de ellos —
            # el tamaño/porcentaje final sale de esa clasificación, no del clustering crudo.
            temas_candidatos = _descubrir_topicos_bertopic(textos)
            valores, metodo = _clasificar_topicos(textos, temas_candidatos, permitir_categoria_nueva=False)
        else:
            frases, error = _extraer_valores_llm(textos)
            # Con muestra chica el LLM extrae frases libres, no clusters — no hay un conteo real
            # por frase que asignar (una respuesta puede tocar varias a la vez), así que tamano/
            # porcentaje quedan en None en vez de inventar un número. La forma del dato se
            # mantiene igual (lista de objetos) para que el consumidor no tenga que distinguir
            # dos formas distintas de valores_caracteristicos según el método.
            valores = [{'tema': frase, 'tamano': None, 'porcentaje': None} for frase in frases]
            metodo = 'llm' if valores else 'insuficiente'

        descripcion, tipo_grafica, nivel_acuerdo = _agente_pregunta_abierta(
            pregunta, estad, valores, metodo, plantilla)
        return {
            'pregunta_id': pregunta.id,
            'texto': pregunta.texto,
            'tipo': pregunta.tipo,
            'tipo_grafica': tipo_grafica,
            'nivel_acuerdo': nivel_acuerdo,
            'total_respuestas': estad['total_respuestas'],
            'descripcion': descripcion,
            'valores_caracteristicos': valores,
            'metodo_valores': metodo,
        }

    descripcion, tipo_grafica = _agente_pregunta_cerrada(pregunta, estad, plantilla)
    return {
        'pregunta_id': pregunta.id,
        'texto': pregunta.texto,
        'tipo': pregunta.tipo,
        'tipo_grafica': tipo_grafica,
        'nivel_acuerdo': None,
        'total_respuestas': estad['total_respuestas'],
        'descripcion': descripcion,
        'valores_caracteristicos': estad['conteo_opciones'],
        'metodo_valores': 'conteo',
    }


# ---------------------------------------------------------------------------
# Agente de momento.
# ---------------------------------------------------------------------------

def _sintetizar_momento(momento, analisis_preguntas, plantilla=None):
    """La síntesis en sí (una llamada al LLM) — separada de analizar las preguntas del momento
    para que estas últimas puedan correr en paralelo entre TODOS los momentos de la jornada (ver
    `procesar_reporte`), no solo dentro de cada uno."""
    system = (
        "Eres un analista de datos senior. Redacta una síntesis robusta (6 a 10 frases, no un "
        "resumen de 2 líneas), en prosa fluida y natural, de UN momento de una jornada "
        "participativa, integrando las descripciones ya redactadas de sus preguntas — no repitas "
        "pregunta por pregunta, encuentra el hilo común, compara los temas más y menos "
        "recurrentes entre preguntas, y explica qué implicación práctica sugiere el conjunto. "
        "Nunca empieces con muletillas como 'Resultados de la encuesta:' o 'Los resultados "
        "indican que'. No agregues datos que no estén en las descripciones dadas. Español." +
        _instrucciones_plantilla(plantilla)
    )
    user = '\n'.join(f"- {p['descripcion']}" for p in analisis_preguntas)
    descripcion_general, error = _llamar_llm(system, user, max_tokens=550, temperature=0.5)

    return {
        'momento_id': momento.id,
        'tipo': momento.tipo,
        'descripcion_general': descripcion_general or f'(Sin síntesis automática — {error})',
        'preguntas': analisis_preguntas,
    }


# ---------------------------------------------------------------------------
# Agente de jornada.
# ---------------------------------------------------------------------------

def analizar_jornada(plantilla, momentos_analisis, participacion):
    system = BASE_SYSTEM_PROMPT + _instrucciones_plantilla(plantilla)

    lineas = [
        f"Participantes totales: {participacion['total_participantes']}.",
        f"Participantes que respondieron: {participacion['participantes_que_respondieron']} "
        f"({participacion['tasa_participacion']}%).",
        '',
    ]
    for m in momentos_analisis:
        lineas.append(f"- {m['descripcion_general']}")
    return _llamar_llm(system, '\n'.join(lineas), max_tokens=900, temperature=0.5)


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

        preguntas_por_momento = {m.id: list(m.preguntas.all().order_by('orden')) for m in momentos}
        todas_las_preguntas = [p for m in momentos for p in preguntas_por_momento[m.id]]

        def _analizar_pregunta_en_hilo(pregunta):
            # Cada pregunta corre en un hilo nuevo del pool de abajo — necesita su propia
            # conexión a la base de datos (Django abre una por hilo; esto la deja limpia si el
            # hilo se reutiliza) antes de tocar el ORM.
            close_old_connections()
            return pregunta.id, analizar_pregunta(pregunta, reporte.plantilla)

        resultados_pregunta = {}
        with ThreadPoolExecutor(max_workers=LLM_POOL_SIZE) as executor:
            for pregunta_id, resultado in executor.map(_analizar_pregunta_en_hilo, todas_las_preguntas):
                resultados_pregunta[pregunta_id] = resultado

        def _sintetizar_momento_en_hilo(momento):
            close_old_connections()
            analisis_preguntas = [resultados_pregunta[p.id] for p in preguntas_por_momento[momento.id]]
            return _sintetizar_momento(momento, analisis_preguntas, reporte.plantilla)

        with ThreadPoolExecutor(max_workers=min(LLM_POOL_SIZE, len(momentos))) as executor:
            momentos_analisis = list(executor.map(_sintetizar_momento_en_hilo, momentos))

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
