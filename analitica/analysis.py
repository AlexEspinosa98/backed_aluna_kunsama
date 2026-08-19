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
import re
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
# BERTopic solo DESCUBRE temas candidatos (nunca más de estos) — la cuantificación real de cada
# uno viene después, de que el LLM clasifique cada respuesta (ver `_etiquetar_y_clasificar`).
MAX_TEMAS_CANDIDATOS = 5
# Tope de respuestas que se envían en la llamada de clasificación, para que el prompt nunca escale
# sin límite con el tamaño de la jornada (mismo espíritu que ya obligó a acotar el resto del
# pipeline — ver la nota de diseño al inicio del archivo).
MAX_RESPUESTAS_CLASIFICACION = 60
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

GRAFICA_TAG_RE = re.compile(r'GRAFICA:\s*(pastel|barras|radar)\b', re.IGNORECASE)


def _extraer_tipo_grafica(texto):
    """Busca la etiqueta `GRAFICA: <tipo>` en cualquier parte del texto del LLM (no siempre
    aparece en su propia línea final pese a la instrucción, y a veces el modelo la repite más de
    una vez) y retira TODAS las apariciones, cada una junto con la oración que la contiene, para
    que no queden fragmentos crudos como "GRAFICA: radar" en la descripción mostrada al usuario.
    Devuelve (tipo_grafica_o_None, texto_limpio) — `tipo_grafica` es el de la primera aparición."""
    tipo = None
    while True:
        m = GRAFICA_TAG_RE.search(texto)
        if not m:
            break
        if tipo is None:
            tipo = m.group(1).lower()
        inicio = texto.rfind('.', 0, m.start())
        inicio = inicio + 1 if inicio != -1 else 0
        fin = texto.find('.', m.end())
        fin = fin + 1 if fin != -1 else len(texto)
        texto = texto[:inicio] + texto[fin:]
    return tipo, re.sub(r'\s+', ' ', texto).strip()


def _tipo_grafica_por_defecto(tipo_pregunta, num_opciones):
    """Respaldo determinístico si el LLM no elige una gráfica válida (o falla): con pocas
    opciones mutuamente excluyentes un pastel/barras simple es más claro; con 4+ opciones un
    radar muestra mejor la forma general de hacia dónde se inclina el público entre todas."""
    if num_opciones >= 4:
        return 'radar'
    return 'pastel' if tipo_pregunta == 'unica' else 'barras'


# ---------------------------------------------------------------------------
# Modelo LLM (llama.cpp) — carga perezosa y única por proceso.
# ---------------------------------------------------------------------------

_llm_lock = threading.Lock()
_llm_instance = None
# Aparte del lock de arriba (que solo protege la creación de la instancia): llama.cpp no soporta
# llamadas concurrentes de inferencia sobre la misma instancia de Llama — dos hilos del mismo
# proceso llamando create_chat_completion() al mismo tiempo corrompen el estado interno del
# contexto y lo hacen abortar con un GGML_ASSERT (crash nativo, tumba todo el worker; no es un
# error de Python, no hay try/except que lo pueda atajar). Pasó en producción: se creó un segundo
# reporte mientras el primero seguía procesando, dos hilos en background llamaron al modelo a la
# vez, y el worker murió dejando ambos reportes huérfanos en 'procesando' para siempre. Este lock
# serializa toda inferencia dentro del proceso — junto con el guard a nivel de API en
# ReporteViewSet.create que ya evita disparar un segundo reporte mientras hay uno en curso.
_inference_lock = threading.Lock()


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
            with _inference_lock:
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


def _etiquetar_y_clasificar(textos, temas_candidatos):
    """Le da a cada tema candidato (descubierto por BERTopic) una etiqueta corta y natural (3 a 5
    palabras), y clasifica CADA una de las respuestas dadas en el tema cuya etiqueta le quede
    mejor — esta clasificación, no el clustering crudo, es la que determina el tamaño/porcentaje
    final de cada tema. Devuelve (lista_de_temas_con_conteo_o_None, error)."""
    muestra = textos[:MAX_RESPUESTAS_CLASIFICACION]
    system = (
        "Eres un analista de datos clasificando respuestas abiertas de una encuesta. Se te dan "
        f"{len(temas_candidatos)} grupos candidatos de tema, cada uno con sus palabras clave y "
        "hasta 2 respuestas de ejemplo reales. Primero, dale a cada grupo una etiqueta corta y "
        "natural en español (3 a 5 palabras, una frase con sentido — nunca una palabra clave "
        "aislada). Luego, clasifica CADA una de las respuestas numeradas en el tema cuya etiqueta "
        "le quede mejor. SIEMPRE asigna uno de los temas dados a cada respuesta, incluso si el "
        "encaje no es perfecto — nunca inventes un tema nuevo ni dejes una respuesta sin "
        "clasificar: la clasificación de cada respuesta es siempre un número de tema, nunca un "
        "guion, un '?' ni la palabra 'ninguno'. Las etiquetas van en texto plano, nunca entre "
        "símbolos como '<' '>' o comillas, y nunca repitas la lista de 'Palabras clave' tal cual "
        "— redacta una frase propia.\n\n"
        "Responde EXACTAMENTE con este formato (usa tus propias etiquetas y números, el ejemplo "
        "de abajo es solo para mostrar la estructura — no la copies), sin texto adicional antes "
        "ni después:\n"
        "TEMAS:\n1: Transparencia en el manejo de datos\n2: Consentimiento informado de las "
        "comunidades\n"
        "CLASIFICACION:\n1: 2\n2: 1\n3: 1\n..."
    )
    lineas = ['GRUPOS CANDIDATOS:']
    for i, tema in enumerate(temas_candidatos, start=1):
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

    etiquetas, asignaciones = _parsear_temas_y_clasificacion(texto_llm)
    if not etiquetas or not asignaciones:
        return None, 'El modelo no devolvió el formato de clasificación esperado.'

    conteos = {idx: 0 for idx in etiquetas}
    for idx_tema in asignaciones.values():
        if idx_tema in conteos:
            conteos[idx_tema] += 1
    total_clasificadas = sum(conteos.values())
    if not total_clasificadas:
        return None, 'El modelo no clasificó ninguna respuesta en un tema válido.'

    temas_final = [
        {
            'tema': etiquetas[idx],
            'tamano': conteos[idx],
            'porcentaje': round(conteos[idx] / total_clasificadas * 100, 1),
        }
        for idx in sorted(etiquetas, key=lambda i: conteos[i], reverse=True)
        if conteos[idx] > 0
    ]
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


def _agente_pregunta_abierta(estad, valores_caracteristicos, metodo_valores):
    """Devuelve (descripcion, tipo_grafica). `tipo_grafica` solo se decide cuando hay datos
    cuantitativos reales que graficar — 2 o más temas con tamaño/porcentaje conocidos, que salen de
    que el LLM haya clasificado las respuestas en los temas descubiertos por BERTopic (método
    `bertopic_llm`). Con `llm` (muestra chica, frases extraídas libremente sin conteo por tema),
    `bertopic_sin_clasificar` (la clasificación falló y solo quedan las palabras clave crudas),
    `insuficiente` o `sin_datos` no hay nada cuantificable que graficar, así que queda `None`."""
    system = (
        "Eres un analista de datos. Redacta una descripción breve (2 a 3 frases) de los "
        "resultados de UNA pregunta de encuesta abierta, usando EXCLUSIVAMENTE los datos "
        "entregados a continuación — nunca inventes cifras ni ideas que no estén ahí. Español, "
        "prosa clara."
    )
    lineas = [
        f"Respuestas de texto no vacías: {estad['respuestas_no_vacias']} "
        f"(de {estad['total_respuestas']} recibidas)."
    ]
    graficable = metodo_valores == 'bertopic_llm' and len(valores_caracteristicos) >= 2
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
            " Luego, en una última línea aparte, recomienda la gráfica que mejor muestre hacia "
            "dónde se inclina el público entre los temas encontrados, escribiendo EXACTAMENTE "
            "una de estas líneas: 'GRAFICA: pastel' (pocos temas, uno domina claramente), "
            "'GRAFICA: barras' (comparación simple de tamaños), o 'GRAFICA: radar' (varios temas "
            "— 4 o más — donde interesa ver la forma general de la inclinación entre todos). Si "
            "se te da una nota con una recomendación, síguela salvo que los datos digan "
            "claramente lo contrario."
        )
        pista = _pista_equilibrio([t['tamano'] for t in valores_caracteristicos], sujeto='los temas')
        if pista:
            lineas.append(pista)

    texto, error = _llamar_llm(system, '\n'.join(lineas), max_tokens=220, temperature=0.5)

    tipo_grafica = None
    if graficable and texto:
        tipo_grafica, texto = _extraer_tipo_grafica(texto)
        if tipo_grafica not in ('pastel', 'barras', 'radar'):
            tipo_grafica = _tipo_grafica_por_defecto('unica', len(valores_caracteristicos))

    descripcion = texto or f'(Sin descripción automática — {error})'
    return descripcion, tipo_grafica


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


def _agente_pregunta_cerrada(pregunta, estad):
    """Para preguntas `unica`/`multiple`: además de la descripción, el propio LLM elige el tipo
    de gráfica que mejor muestre hacia dónde se inclina el público entre las opciones — pastel
    (pocas, mutuamente excluyentes), barras (comparación simple de conteos) o radar (varias
    opciones, muestra la forma general de la inclinación entre todas). Si el modelo no devuelve
    una elección válida, se usa `_tipo_grafica_por_defecto` como respaldo."""
    opciones = estad.get('conteo_opciones', [])
    system = (
        "Eres un analista de datos. Redacta una descripción breve (2 a 3 frases) de los "
        "resultados de UNA pregunta de encuesta de opción cerrada, usando EXCLUSIVAMENTE los "
        "datos entregados — nunca inventes cifras. Luego, en una última línea aparte, recomienda "
        "la gráfica que mejor muestre hacia dónde se inclina el público entre las opciones, "
        "escribiendo EXACTAMENTE una de estas tres líneas: 'GRAFICA: pastel' (pocas opciones "
        "mutuamente excluyentes), 'GRAFICA: barras' (comparación simple de conteos), o "
        "'GRAFICA: radar' (varias opciones — 4 o más — donde interesa ver la forma general de la "
        "inclinación entre todas a la vez). Si se te da una nota con una recomendación, síguela "
        "salvo que los datos digan claramente lo contrario. Español, prosa clara."
    )
    lineas = [f"Total de respuestas: {estad['total_respuestas']}."]
    for opcion in opciones:
        lineas.append(f"- {opcion['texto']}: {opcion['conteo']} respuestas.")
    pista = _pista_equilibrio([o['conteo'] for o in opciones])
    if pista:
        lineas.append(pista)
    texto, error = _llamar_llm(system, '\n'.join(lineas), max_tokens=220, temperature=0.5)

    tipo_grafica = None
    if texto:
        tipo_grafica, texto = _extraer_tipo_grafica(texto)

    if tipo_grafica not in ('pastel', 'barras', 'radar'):
        tipo_grafica = _tipo_grafica_por_defecto(pregunta.tipo, len(opciones))

    descripcion = texto or f'(Sin descripción automática — {error})'
    return descripcion, tipo_grafica


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
            # BERTopic solo descubre de 3 a 5 temas candidatos (palabras clave + ejemplos); el
            # propio LLM les da una etiqueta natural y clasifica CADA respuesta en uno de ellos —
            # el tamaño/porcentaje final sale de esa clasificación, no del clustering crudo.
            temas_candidatos = _descubrir_topicos_bertopic(textos)
            valores, metodo = None, None
            if temas_candidatos:
                valores, _error_clas = _etiquetar_y_clasificar(textos, temas_candidatos)
                if valores:
                    metodo = 'bertopic_llm'
            if not valores:
                # Respaldo: si BERTopic no encontró candidatos o la clasificación del LLM falló,
                # se muestran las palabras clave crudas de cada candidato sin conteo (mejor que no
                # mostrar nada) en vez de tumbar el análisis de la pregunta.
                valores = [
                    {'tema': ', '.join(t['palabras_clave']), 'tamano': None, 'porcentaje': None}
                    for t in temas_candidatos
                ]
                metodo = 'bertopic_sin_clasificar' if valores else 'insuficiente'
        else:
            frases, error = _extraer_valores_llm(textos)
            # Con muestra chica el LLM extrae frases libres, no clusters — no hay un conteo real
            # por frase que asignar (una respuesta puede tocar varias a la vez), así que tamano/
            # porcentaje quedan en None en vez de inventar un número. La forma del dato se
            # mantiene igual (lista de objetos) para que el consumidor no tenga que distinguir
            # dos formas distintas de valores_caracteristicos según el método.
            valores = [{'tema': frase, 'tamano': None, 'porcentaje': None} for frase in frases]
            metodo = 'llm' if valores else 'insuficiente'

        descripcion, tipo_grafica = _agente_pregunta_abierta(estad, valores, metodo)
        return {
            'pregunta_id': pregunta.id,
            'tipo': pregunta.tipo,
            'tipo_grafica': tipo_grafica,
            'total_respuestas': estad['total_respuestas'],
            'descripcion': descripcion,
            'valores_caracteristicos': valores,
            'metodo_valores': metodo,
        }

    descripcion, tipo_grafica = _agente_pregunta_cerrada(pregunta, estad)
    return {
        'pregunta_id': pregunta.id,
        'tipo': pregunta.tipo,
        'tipo_grafica': tipo_grafica,
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
