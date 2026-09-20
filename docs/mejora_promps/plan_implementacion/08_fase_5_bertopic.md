# 08 — Fase 5: adaptador BERTopic → contrato v2 (pipeline `bertopic_llm`)

**Objetivo**: reemplazar el stub de `analitica/v2/bertopic_adaptador.py` por el adaptador real
(`ENTRADA_Y_BERTOPIC.md` §6–§7, D8 del plan): una ejecución de BERTopic por pregunta de texto
(`abierta`/`audio`) con al menos 8 respuestas no vacías, exportada **solo con lo que BERTopic
calcula de verdad**.

**Prerrequisitos**: fase 4 (para probarlo de punta a punta) — el módulo en sí solo depende de la
fase 2 (formato de la entrada).

**Qué NO hace**: no reduce outliers, no calcula distribuciones aproximadas, similitudes,
coocurrencias ni proyecciones (van `[]`), no usa `categorias_semilla` (en v2 son contexto, D7), y
no toca `analysis.py` (solo importa sus constantes y el embedder singleton).

## Paso 5.1 — Anatomía de una ejecución (lo que exporta cada pregunta)

| Pieza | Valor |
|---|---|
| `ejecucion_id` | `run-p{pregunta.id}` |
| Fuente `bertopic` | `id = fbt-p{pregunta.id}`, `momento_ids = [mid]`, `pregunta_ids = [pid]`, `cobertura = completa`, `etiqueta = 'Tópicos BERTopic — pregunta "<texto recortado a 80>"'` |
| `datos.topicos[]` | uno por fila de `get_topic_info()` (incluido `-1`): `id = run-p{pid}::{native}` (con `urllib.parse.quote(..., safe='')` en las dos mitades), `native_id = str(native)`, `etiqueta` = columna `Name` (o `'Sin asignar (outliers de HDBSCAN)'` para -1), `conteo_documentos = Count`, `terminos` = hasta 10 de `get_topic(native)` como `{termino, peso, weight_type: 'c_tf_idf', representation_method: 'c-TF-IDF'}`, `documentos_representativos_ids` = ids de los docs cuyo texto devuelve `get_representative_docs(native)` (`[]` para -1) |
| `datos.documentos[]` | uno por texto, en el orden del corpus: `id = doc-p{pid}-{i}`, `respuesta_id`, `fuente_id` (la fuente `respuestas` del momento), `localizador = /respuestas/{indice}/valor`, `momento_id`, `pregunta_id`, `topico_original_id = topico_final_id = id compuesto de topics_[i]`, `es_representativo`, `score = null`, `score_type = null`, `texto` |
| `datos.agregados[]` | uno: `id = agg-p{pid}`, `unidad_analisis = 'documento (una respuesta de texto completa)'`, `denominador_n = n`, `incluye_outliers = true`, `conteos = [{topico_id, n}]` desde `Counter(topics_)` |
| `datos.distribuciones/similitudes/coocurrencias/proyecciones` | `[]` |
| `ejecucion.corpus` | `version = analisis-{id}`, `unidad_documento = 'respuesta_completa'`, `regla_segmentacion`, `documentos_elegibles_n = documentos_procesados_n = textos_disponibles_llm_n = n`, `documentos_excluidos_n = 0`, `outliers_originales_n = outliers_finales_n = conteo de -1`, `documentos_reasignados_n = 0`, `seleccion_textos = 'Todos los documentos procesados, con texto completo.'` |
| `ejecucion.configuracion` | `bertopic_version`, `embedding_model = EMBEDDING_MODEL_NAME`, `agrupador = 'HDBSCAN'`, `vectorizador = 'CountVectorizer(ngram_range=(1,3), stop_words=es)'`, `representacion = 'c-TF-IDF'`, `parametros` (los reales), `semillas = {'umap_random_state': 42}` |
| `ejecucion.asignacion` | `{tipo: 'principal', score_type: null, topico_ids_por_columna: [], parametros: {}}` |
| `ejecucion.transformaciones` | `[{tipo: 'reduccion_topicos', metodo: 'BERTopic(nr_topics=5) durante fit', parametros: {nr_topics: 5}, mapping: []}]` — la reducción ocurre dentro de `fit_transform`; todo lo exportado (conteos, etiquetas, asignaciones) es del estado final, así que es consistente aunque el mapping no esté disponible. |

## Paso 5.2 — `analitica/v2/bertopic_adaptador.py` (reemplazar el stub completo)

```python
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
```

## Paso 5.3 — Verificación

```bash
source .venv/bin/activate
python -m py_compile analitica/v2/bertopic_adaptador.py
```

Prueba de exportación con un doble (sin descargar modelos):

```bash
python - <<'EOF'
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django; django.setup()
import pandas as pd
from analitica.v2.bertopic_adaptador import anexar_bertopic, exportar_ejecucion, id_topico
from unittest.mock import patch

class Doble:
    topics_ = [0, 0, 0, 1, 1, 1, -1, -1]
    def get_topic_info(self):
        return pd.DataFrame({'Topic': [-1, 0, 1], 'Count': [2, 3, 3], 'Name': ['-1_x', '0_horario', '1_turno']})
    def get_topic(self, t):
        return [('horario', 0.5), ('turno', 0.2)]
    def get_representative_docs(self, t):
        return ['t0'] if t == 0 else ['t3']

docs = [(i + 10, {'id': f'r{i}', 'pregunta_id': 'q2', 'sujeto_id': None, 'valor': f't{i}'}) for i in range(8)]
fuente, ejecucion = exportar_ejecucion(Doble(), docs, 'run-pq2', 'f-m1', 'm1', 'q2', '¿Por qué?', 'analisis-1')
assert fuente['id'] == 'fbt-pq2' and fuente['datos']['documentos'][0]['localizador'] == '/respuestas/10/valor'
assert fuente['datos']['documentos'][6]['topico_final_id'] == id_topico('run-pq2', -1) == 'run-pq2::-1'
assert fuente['datos']['documentos'][0]['es_representativo'] and not fuente['datos']['documentos'][1]['es_representativo']
assert [t['conteo_documentos'] for t in fuente['datos']['topicos']] == [2, 3, 3]
assert fuente['datos']['agregados'][0]['conteos'] == [{'topico_id': 'run-pq2::-1', 'n': 2}, {'topico_id': 'run-pq2::0', 'n': 3}, {'topico_id': 'run-pq2::1', 'n': 3}]
assert ejecucion['corpus']['outliers_finales_n'] == 2 and ejecucion['fuente_resultados_id'] == 'fbt-pq2'

entrada = {'momentos': [{'id': 'm1', 'preguntas': [{'id': 'q2', 'tipo': 'abierta', 'texto': '¿?'}, {'id': 'q1', 'tipo': 'unica', 'texto': 'x'}]}],
           'fuentes': [{'id': 'f-m1', 'tipo': 'respuestas', 'momento_ids': ['m1'], 'datos': {'respuestas': [d for _, d in docs]}}]}
with patch('analitica.v2.bertopic_adaptador._ajustar_modelo', return_value=Doble()):
    entrada, notas = anexar_bertopic(entrada, analisis_id=1)
assert len(entrada['bertopic']['ejecuciones']) == 1 and notas[0]['motivo'] == 'ok', notas
entrada['fuentes'][0]['datos']['respuestas'] = entrada['fuentes'][0]['datos']['respuestas'][:3]
del entrada['fuentes'][1]
_, notas = anexar_bertopic(entrada)
assert notas[0]['motivo'] == 'insuficiente', notas
print('OK adaptador')
EOF
```

Prueba real (opcional, tarda y descarga el modelo de embeddings en `.hf_cache/` la primera vez):

```bash
python - <<'EOF'
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django; django.setup()
from analitica.v2.bertopic_adaptador import _ajustar_modelo
textos = ['El horario me sirve', 'Puedo asistir en ese horario', 'Mantendría el horario', 'El horario está bien',
          'Necesito una opción al final de la tarde', 'Mi turno coincide con la sesión', 'La sesión termina antes de mi turno',
          'Prefiero la tarde por el turno', 'Más cupos en la mañana', 'Quisiera más cupos'] * 2
m = _ajustar_modelo(textos)
print('topics_', list(m.topics_)[:10]); print(m.get_topic_info()[['Topic', 'Count', 'Name']])
EOF
```

## Paso 5.4 — Tests (escribir, no correr) — agregar a `analitica/tests_v2.py`

Portar el script del paso 5.3 a una clase `BertopicAdaptadorTests(SimpleTestCase)` con dos
tests (`test_exportar_ejecucion_mapea_topicos_documentos_y_agregados`,
`test_anexar_bertopic_omite_preguntas_insuficientes`) — misma clase `Doble`, mismos asserts,
`patch('analitica.v2.bertopic_adaptador._ajustar_modelo', return_value=Doble())`. Además:

```python
    def test_pipeline_bertopic_end_to_end_con_dobles(self):
        # Fase 4 + 5: el orquestador anexa las ejecuciones antes de llamar al modelo y las guarda en la entrada.
        d = crear_jornada_completa()   # necesita TestCase, no SimpleTestCase: ponerlo en ProcesarAnalisisV2Tests
```

Concretamente, agregar a `ProcesarAnalisisV2Tests`:

```python
    def test_bertopic_llm_guarda_ejecuciones_en_la_entrada(self):
        q = self.d['q_abierta']
        for i in range(10):
            Respuesta.objects.create(pregunta=q, texto_libre=f'Texto de prueba número {i}')
        a = AnalisisV2.objects.create(jornada=self.d['jornada'], modo='por_momento', pipeline='bertopic_llm')
        a.momentos.set([self.d['m1']])

        class Doble:
            topics_ = [0] * 6 + [-1] * 5
            def get_topic_info(self):
                import pandas as pd
                return pd.DataFrame({'Topic': [-1, 0], 'Count': [5, 6], 'Name': ['-1_x', '0_prueba']})
            def get_topic(self, t):
                return [('prueba', 0.4)]
            def get_representative_docs(self, t):
                return []

        def salida(system, user, modelo=None, reparacion=None):
            entrada = json.loads(user)
            return construir_salida_sin_datos(entrada, 'bertopic_llm'), None, {}

        with patch('analitica.v2.bertopic_adaptador._ajustar_modelo', return_value=Doble()), \
             patch('analitica.v2.procesar.llamar_openai_estructurado', side_effect=salida):
            procesar_analisis_v2(a.id)
        a.refresh_from_db()
        self.assertEqual(a.estado, AnalisisV2.ESTADO_COMPLETO, a.error_mensaje)
        self.assertEqual(len(a.entrada['bertopic']['ejecuciones']), 1)
        self.assertEqual(a.entrada['bertopic']['ejecuciones'][0]['ejecucion_id'], f'run-p{q.id}')
        self.assertIn(f'fbt-p{q.id}', [f['id'] for f in a.entrada['fuentes']])
        self.assertEqual(a.diagnostico['bertopic'][0]['motivo'], 'ok')
        self.assertTrue(a.prompt_usado.startswith('# System prompt Kunsamu — BERTopic + LLM'))
```

(11 textos: la respuesta original de p1 + 10 nuevas; la de p2 está en blanco y no cuenta.)

## Paso 5.5 — Commit

```bash
git status --short
git add analitica/v2/bertopic_adaptador.py analitica/tests_v2.py
git commit -m "feat(v2): adaptador BERTopic real para el pipeline bertopic_llm

Una ejecución por pregunta de texto con ≥8 respuestas, misma configuración que el pipeline
legacy, exportando solo lo que BERTopic calcula (tópicos con Count y c-TF-IDF, asignación final
por documento con localizador a la fuente de respuestas, conteos agregados con outliers). Nada
inventado: distribuciones, similitudes, coocurrencias y proyecciones van vacías. Una pregunta
insuficiente o con error queda anotada en diagnostico y no tumba el análisis."
```

## Criterios de "hecho"

- [ ] El script con doble imprime `OK adaptador`.
- [ ] (Opcional) la prueba real muestra `topics_` y una tabla de tópicos.
- [ ] Tests escritos (no corridos). Commit sin `Dockerfile`/`docker-compose.yml`.

**Riesgo conocido**: la primera ejecución en el servidor descarga el modelo de embeddings
(`.hf_cache/` está montado desde el host, ver `docker-compose.yml`) y compila la caché JIT de
numba (`NUMBA_CACHE_DIR`); un análisis `bertopic_llm` de una jornada grande puede tardar varios
minutos por eso. El umbral de huérfano de 45 min lo contempla.
