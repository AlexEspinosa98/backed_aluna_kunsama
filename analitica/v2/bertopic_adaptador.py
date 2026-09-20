"""Adaptador BERTopic → contrato v2 (docs/mejora_promps/ENTRADA_Y_BERTOPIC.md §6–§7; D8 del plan).

Una ejecución por pregunta de texto con al menos MIN_RESPUESTAS_TOPICOS respuestas no vacías,
con la MISMA configuración que el pipeline legacy (`analysis._descubrir_topicos_bertopic`),
copiada y no importada porque esa función no expone el modelo ajustado. Se exporta únicamente lo
que BERTopic calcula: tópicos con Count y términos c-TF-IDF, asignación final por documento y
conteos agregados. Distribuciones aproximadas, similitudes, coocurrencias y proyecciones NO se
calculan y van vacías — inventarlas violaría el contrato. El tópico -1 (outliers de HDBSCAN) se
conserva como tal, nunca como "otros".

`exportar_ejecucion` está separada de `_ajustar_modelo` y solo usa `.topics_`, `.get_topic_info()`,
`.get_topic(t)` y `.get_representative_docs(t)` — los tests la ejercitan con un doble, sin
descargar el modelo de embeddings.
"""
from collections import Counter
from urllib.parse import quote

from analitica.analysis import (
    EMBEDDING_MODEL_NAME, MAX_TEMAS_CANDIDATOS, MIN_RESPUESTAS_TOPICOS, STOPWORDS_ES, _get_embedder,
)

VERSION_ADAPTADOR = '1.0'
MAX_TERMINOS_POR_TOPICO = 10
TIPOS_TEXTO = ('abierta', 'audio')
ETIQUETA_OUTLIERS = 'Sin asignar (outliers de HDBSCAN)'


def _parametros(n):
    return {
        'umap': {
            'n_neighbors': max(2, min(15, n - 1)), 'n_components': max(2, min(5, n - 2)),
            'min_dist': 0.0, 'metric': 'cosine',
        },
        'hdbscan': {
            'min_cluster_size': max(2, min(5, n // 4)), 'metric': 'euclidean',
            'cluster_selection_method': 'eom',
        },
        'vectorizador': {'ngram_range': [1, 3], 'min_df': 1, 'stop_words': 'lista propia en español'},
        'nr_topics': MAX_TEMAS_CANDIDATOS,
        'calculate_probabilities': False,
    }


def _ajustar_modelo(textos):
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    p = _parametros(len(textos))
    umap_model = UMAP(random_state=42, **p['umap'])
    hdbscan_model = HDBSCAN(prediction_data=True, **p['hdbscan'])
    vectorizer_model = CountVectorizer(stop_words=STOPWORDS_ES, ngram_range=(1, 3), min_df=1)
    modelo = BERTopic(
        embedding_model=_get_embedder(), umap_model=umap_model, hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer_model, verbose=False, calculate_probabilities=False,
        nr_topics=MAX_TEMAS_CANDIDATOS,
    )
    modelo.fit_transform(textos)
    return modelo


def id_topico(ejecucion_id, native_id):
    """`encodeURIComponent(ejecucion_id) + '::' + encodeURIComponent(native_id)` (contrato §6)."""
    return f'{quote(ejecucion_id, safe="")}::{quote(str(native_id), safe="")}'


def _version_bertopic():
    try:
        import bertopic
        return getattr(bertopic, '__version__', None)
    except Exception:  # noqa: BLE001 — el dato es informativo, nunca debe tumbar la exportación
        return None


def exportar_ejecucion(modelo, documentos, ejecucion_id, fuente_corpus_id, momento_id, pregunta_id,
                       texto_pregunta, version_corpus):
    """`documentos`: lista de `(indice_en_respuestas, respuesta_dict)` en el MISMO orden con que
    se ajustó el modelo. Devuelve `(fuente_bertopic, ejecucion)`."""
    asignaciones = [int(t) for t in modelo.topics_]
    if len(asignaciones) != len(documentos):
        raise ValueError('BERTopic devolvió una cantidad de asignaciones distinta al corpus')

    fuente_id = f'fbt-p{pregunta_id}'
    docs_salida, texto_por_doc = [], {}
    for i, ((indice, respuesta), topico) in enumerate(zip(documentos, asignaciones)):
        doc_id = f'doc-p{pregunta_id}-{i}'
        texto_por_doc[doc_id] = respuesta['valor']
        docs_salida.append({
            'id': doc_id,
            'respuesta_id': respuesta['id'],
            'fuente_id': fuente_corpus_id,
            'localizador': f'/respuestas/{indice}/valor',
            'momento_id': momento_id,
            'pregunta_id': pregunta_id,
            'topico_original_id': id_topico(ejecucion_id, topico),
            'topico_final_id': id_topico(ejecucion_id, topico),
            'es_representativo': False,
            'score': None,
            'score_type': None,
            'texto': respuesta['valor'],
        })

    topicos, representativos = [], set()
    for _, fila in modelo.get_topic_info().iterrows():
        native = int(fila['Topic'])
        terminos = [
            {
                'termino': str(palabra), 'peso': float(peso),
                'weight_type': 'c_tf_idf', 'representation_method': 'c-TF-IDF',
            }
            for palabra, peso in (modelo.get_topic(native) or [])[:MAX_TERMINOS_POR_TOPICO]
        ]
        rep_ids = []
        if native != -1:
            try:
                textos_rep = list(modelo.get_representative_docs(native) or [])
            except Exception:  # noqa: BLE001 — sin representativos, el tópico se exporta igual
                textos_rep = []
            for texto in textos_rep:
                doc_id = next((d for d, t in texto_por_doc.items() if t == texto and d not in rep_ids), None)
                if doc_id:
                    rep_ids.append(doc_id)
        representativos.update(rep_ids)
        topicos.append({
            'id': id_topico(ejecucion_id, native),
            'native_id': str(native),
            'etiqueta': ETIQUETA_OUTLIERS if native == -1 else str(fila['Name']),
            'conteo_documentos': int(fila['Count']),
            'terminos': terminos,
            'documentos_representativos_ids': rep_ids,
        })
    for doc in docs_salida:
        doc['es_representativo'] = doc['id'] in representativos

    n = len(documentos)
    conteos = Counter(asignaciones)
    outliers = conteos.get(-1, 0)
    fuente = {
        'id': fuente_id,
        'tipo': 'bertopic',
        'etiqueta': f'Tópicos BERTopic — pregunta "{texto_pregunta[:80]}"',
        'momento_ids': [momento_id],
        'pregunta_ids': [pregunta_id],
        'cobertura': 'completa',
        'datos': {
            'topicos': topicos,
            'documentos': docs_salida,
            'distribuciones': [],
            'agregados': [{
                'id': f'agg-p{pregunta_id}',
                'momento_ids': [momento_id],
                'pregunta_ids': [pregunta_id],
                'unidad_analisis': 'documento (una respuesta de texto completa)',
                'denominador_n': n,
                'incluye_outliers': True,
                'conteos': [
                    {'topico_id': id_topico(ejecucion_id, t), 'n': c}
                    for t, c in sorted(conteos.items())
                ],
            }],
            'similitudes': [],
            'coocurrencias': [],
            'proyecciones': [],
        },
    }
    ejecucion = {
        'ejecucion_id': ejecucion_id,
        'fuente_resultados_id': fuente_id,
        'fuente_corpus_ids': [fuente_corpus_id],
        'corpus': {
            'version': version_corpus,
            'unidad_documento': 'respuesta_completa',
            'regla_segmentacion': 'Una respuesta de texto no vacía = un documento; sin segmentación.',
            'documentos_elegibles_n': n,
            'documentos_procesados_n': n,
            'documentos_excluidos_n': 0,
            'outliers_originales_n': outliers,
            'outliers_finales_n': outliers,
            'documentos_reasignados_n': 0,
            'textos_disponibles_llm_n': n,
            'seleccion_textos': 'Todos los documentos procesados, con texto completo.',
        },
        'configuracion': {
            'bertopic_version': _version_bertopic(),
            'embedding_model': EMBEDDING_MODEL_NAME,
            'agrupador': 'HDBSCAN',
            'vectorizador': 'CountVectorizer(ngram_range=(1,3), stop_words=es)',
            'representacion': 'c-TF-IDF',
            'parametros': _parametros(n),
            'semillas': {'umap_random_state': 42},
        },
        'asignacion': {'tipo': 'principal', 'score_type': None, 'topico_ids_por_columna': [], 'parametros': {}},
        'transformaciones': [{
            'tipo': 'reduccion_topicos',
            'metodo': f'BERTopic(nr_topics={MAX_TEMAS_CANDIDATOS}) durante fit_transform',
            'parametros': {'nr_topics': MAX_TEMAS_CANDIDATOS},
            'mapping': [],
        }],
    }
    return fuente, ejecucion


def anexar_bertopic(entrada, analisis_id=None):
    """Agrega a `entrada` las fuentes `bertopic` y el bloque `bertopic` (una ejecución por
    pregunta de texto con corpus suficiente). Devuelve `(entrada, notas)`; las notas van a
    `AnalisisV2.diagnostico['bertopic']` — una pregunta insuficiente o cuya ejecución falle
    simplemente no tiene ejecución, nunca tumba el análisis completo. No lanza."""
    notas, ejecuciones, fuentes_bt = [], [], []
    fuentes_respuestas = {
        f['momento_ids'][0]: f for f in entrada['fuentes'] if f['tipo'] == 'respuestas' and f['momento_ids']
    }
    for momento in entrada['momentos']:
        fuente = fuentes_respuestas.get(momento['id'])
        if fuente is None:
            continue
        for pregunta in momento['preguntas']:
            if pregunta['tipo'] not in TIPOS_TEXTO:
                continue
            documentos = [
                (i, r) for i, r in enumerate(fuente['datos']['respuestas'])
                if r['pregunta_id'] == pregunta['id'] and isinstance(r['valor'], str) and r['valor'].strip()
            ]
            nota = {'pregunta_id': pregunta['id'], 'documentos_n': len(documentos)}
            if len(documentos) < MIN_RESPUESTAS_TOPICOS:
                nota['motivo'] = 'insuficiente'
                notas.append(nota)
                continue
            try:
                modelo = _ajustar_modelo([r['valor'] for _, r in documentos])
                fuente_bt, ejecucion = exportar_ejecucion(
                    modelo, documentos, f"run-p{pregunta['id']}", fuente['id'], momento['id'],
                    pregunta['id'], pregunta['texto'], f'analisis-{analisis_id}',
                )
            except Exception as exc:  # noqa: BLE001 — ver docstring
                nota.update({'motivo': 'error', 'detalle': str(exc)[:300]})
                notas.append(nota)
                continue
            fuentes_bt.append(fuente_bt)
            ejecuciones.append(ejecucion)
            nota.update({
                'motivo': 'ok',
                'topicos_n': len(fuente_bt['datos']['topicos']),
                'outliers_n': ejecucion['corpus']['outliers_finales_n'],
            })
            notas.append(nota)
    entrada['fuentes'].extend(fuentes_bt)
    entrada['bertopic'] = {'version_adaptador': VERSION_ADAPTADOR, 'ejecuciones': ejecuciones}
    return entrada, notas
