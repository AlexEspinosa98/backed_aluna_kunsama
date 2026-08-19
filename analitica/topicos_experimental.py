"""Herramienta EXPERIMENTAL de comparación, para evaluar si vale la pena adoptar una versión
mejorada de la extracción de tópicos antes de tocar el pipeline de producción
(`analitica/analysis.py`). No se expone por API — se corre a mano con el management command
`comparar_bertopic`. No modifica ni importa nada que altere el comportamiento de producción; el
flujo "actual" se corre llamando a `_run_bertopic` tal cual está hoy en `analysis.py`.

Diferencias del flujo "mejorado" frente al actual:
- Lista de paro más completa (más verbos auxiliares comunes conjugados: haber, hacer, ser, estar,
  tener, poder...) — la de producción ya filtra verbos modales (debe, debería...) pero se siguen
  colando auxiliares como "hay", "hace".
- `ngram_range=(1, 3)` en vez de `(1, 2)` — permite tri-términos.
  (`min_df` se deja en 1 como en producción: BERTopic corre el vectorizador sobre los documentos
  ya agrupados por tema, no sobre las respuestas crudas — con solo 2-3 temas, `min_df=2` exige que
  un término aparezca en 2 de esos 2-3 "documentos" y termina podando todo. La reducción de ruido
  viene de las stopwords ampliadas y de que ahora las etiquetas las redacta el LLM, no de min_df.)
- En vez de concatenar las palabras clave crudas de c-TF-IDF, un LLM redacta una frase natural
  por tema a partir de 2-3 respuestas reales representativas de ese tema
  (`BERTopic.get_representative_docs`), y clasifica si los temas de la pregunta se contradicen
  (tensión) o tienen mucha relación entre sí (consenso).
"""
import re

from .analysis import STOPWORDS_ES, _get_embedder, _llamar_llm, _run_bertopic  # noqa: F401 — _run_bertopic es el flujo "actual", se reexporta para el comando

STOPWORDS_ES_AMPLIADAS = STOPWORDS_ES + [
    # Conjugaciones comunes de los verbos auxiliares/más frecuentes del español. La lista de
    # producción ya cubre los modales (debe, debería...); esta amplía a los verbos genéricos que
    # aparecen como relleno en casi cualquier respuesta, sin aportar contenido temático.
    'haber', 'hay', 'había', 'habían', 'habrá', 'habría', 'hube', 'hubo', 'hubiera', 'haya',
    'hemos', 'han', 'he', 'has', 'ha',
    'hacer', 'hace', 'hacen', 'hacía', 'hacían', 'hizo', 'hicieron', 'haciendo', 'hecho', 'haremos',
    'tener', 'tiene', 'tienen', 'tenía', 'tenían', 'tuvo', 'tuvieron', 'teniendo', 'tengo', 'tenemos',
    'ver', 'vemos', 'ven', 'veo', 'vio', 'vieron', 'veía',
    'dar', 'da', 'dan', 'dio', 'dieron', 'daba', 'damos',
    'ir', 'va', 'van', 'iba', 'iban', 'fue', 'fueron', 'vamos', 'voy',
    'decir', 'dice', 'dicen', 'dijo', 'dijeron', 'decía', 'digo',
    'saber', 'sabe', 'saben', 'sabía', 'supo',
    'hacia', 'aquí', 'allí', 'ahí', 'así', 'cada', 'cómo', 'dentro', 'fuera', 'igual', 'incluso',
    'luego', 'mientras', 'siempre', 'tal', 'tras', 'vez', 'veces',
]


def _run_bertopic_mejorado(textos):
    """Igual estructura que `_run_bertopic` (analysis.py) pero con stopwords ampliadas,
    tri-términos, min_df=2, y devolviendo también las respuestas representativas de cada tema
    (para que el LLM las use al redactar la etiqueta natural)."""
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
    vectorizer_model = CountVectorizer(
        stop_words=STOPWORDS_ES_AMPLIADAS, ngram_range=(1, 3), min_df=1,
    )
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
        try:
            ejemplos = modelo.get_representative_docs(row['Topic'])[:3]
        except Exception:  # noqa: BLE001 — herramienta experimental, nunca debe tumbar la comparación
            ejemplos = []
        temas.append({
            'palabras_clave': palabras,
            'tamano': int(row['Count']),
            'porcentaje': round(row['Count'] / n * 100, 1),
            'ejemplos': ejemplos,
        })
    temas.sort(key=lambda t: t['tamano'], reverse=True)
    return temas


RELACION_TAG_RE = re.compile(
    r'RELACION:\s*(consenso_fuerte|consenso_moderado|tension|dispersos)', re.IGNORECASE
)
TEMA_TAG_RE = re.compile(r'TEMA\s+(\d+):\s*(.+)')


def _etiquetar_temas_llm(temas):
    """Una sola llamada al LLM: redacta una frase natural por tema (a partir de sus respuestas
    representativas reales) y clasifica la relación entre todos los temas de la pregunta. Nunca
    lanza excepción — si el modelo no sigue el formato para algún tema, ese tema cae de vuelta a
    sus palabras clave crudas; nunca se pierde el dato."""
    if not temas:
        return {}, None

    system = (
        "Eres un analista de datos. Se te dan los temas recurrentes encontrados en las "
        "respuestas de una pregunta de encuesta. Por cada tema tienes su tamaño (cuántas "
        "respuestas) y hasta 3 respuestas reales de ejemplo. Para cada tema escribe una frase "
        "corta y natural (3 a 8 palabras) que lo describa, basada EXCLUSIVAMENTE en los ejemplos "
        "dados — nunca agregues ideas que no estén ahí. "
        "Si hay 2 o más temas, clasifica además la relación entre ellos con una etiqueta EXACTA: "
        "'RELACION: consenso_fuerte' (dicen básicamente lo mismo), "
        "'RELACION: consenso_moderado' (coinciden en general, con matices), "
        "'RELACION: tension' (se contradicen o proponen cosas opuestas), o "
        "'RELACION: dispersos' (hablan de cosas distintas, sin relación clara). "
        "Responde en este formato EXACTO, una línea por elemento, sin texto adicional:\n"
        "TEMA 1: <frase>\nTEMA 2: <frase>\n...\nRELACION: <etiqueta>"
    )
    lineas = []
    for i, tema in enumerate(temas, start=1):
        ejemplos = ' | '.join(tema.get('ejemplos') or []) or ', '.join(tema['palabras_clave'])
        lineas.append(f"Tema {i} ({tema['tamano']} respuestas). Ejemplos: {ejemplos}")
    texto, error = _llamar_llm(system, '\n'.join(lineas), max_tokens=300, temperature=0.4)

    etiquetas = {}
    relacion = None
    if texto:
        for num, frase in TEMA_TAG_RE.findall(texto):
            etiquetas[int(num)] = frase.strip()
        m = RELACION_TAG_RE.search(texto)
        if m:
            relacion = m.group(1).lower()
    return etiquetas, relacion


def comparar_pregunta(pregunta):
    """Corre el flujo ACTUAL (producción, sin modificar) y el MEJORADO (experimental) sobre las
    mismas respuestas reales de una pregunta, para comparar lado a lado."""
    from participantes.models import Respuesta

    textos = list(
        Respuesta.objects.filter(pregunta=pregunta)
        .exclude(texto_libre='')
        .values_list('texto_libre', flat=True)
    )

    temas_actual = _run_bertopic(textos)

    temas_mejorado_raw = _run_bertopic_mejorado(textos)
    etiquetas, relacion = _etiquetar_temas_llm(temas_mejorado_raw)
    temas_mejorado = [
        {
            'etiqueta': etiquetas.get(i, ', '.join(t['palabras_clave'])),
            'tamano': t['tamano'],
            'porcentaje': t['porcentaje'],
            'palabras_clave_crudas': t['palabras_clave'],
        }
        for i, t in enumerate(temas_mejorado_raw, start=1)
    ]

    return {
        'pregunta_id': pregunta.id,
        'texto': pregunta.texto,
        'momento_titulo': pregunta.momento.titulo,
        'total_respuestas': len(textos),
        'temas_actual': temas_actual,
        'temas_mejorado': temas_mejorado,
        'relacion_mejorado': relacion,
    }
