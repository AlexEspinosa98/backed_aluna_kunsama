# 01 — Contexto y estado actual (todo lo que hace falta saber)

Este archivo reemplaza tener que leer el repo entero. Cita rutas y símbolos reales, verificados el
20 de septiembre de 2026 (último commit `513e770` en `develop`). Si algo de aquí no coincide con
el código cuando ejecutes una fase, manda el código real y repórtalo.

## 1. Qué pide el frontend (la entrega `docs/mejora_promps/`)

La entrega define **un solo contrato de salida** para el análisis con IA, `kunsamu.analisis/v2`,
que el frontend va a renderizar con un único renderer, y **dos system prompts** (uno por
pipeline). Archivos de la entrega y para qué sirven aquí:

| Archivo | Qué es | Cómo lo usa este plan |
|---|---|---|
| `analisis.schema.json` | JSON Schema Draft 2020-12 de la SALIDA. Todo obligatorio, `additionalProperties: false` en todo, 17 tipos de visualización en 8 variantes (`visual_categorica`, `visual_coordenadas`, `visual_histograma`, `visual_caja`, `visual_calor`, `visual_nube`, `visual_red`, `visual_tabla`). | Se copia congelado a `analitica/v2/recursos/` y se usa (a) como `response_format` estricto de OpenAI y (b) para validar la respuesta con `jsonschema`. |
| `SYSTEM_PROMPT_LLM.md` | System prompt completo de la ruta `llm` (sin BERTopic). | Se manda **tal cual, entero, como `system`**. No se le anexa nada (ni bloques de enfoque, ni plantillas, ni "las instrucciones del usuario mandan"). |
| `SYSTEM_PROMPT_BERTOPIC.md` | System prompt completo de la ruta `bertopic_llm`. | Ídem, para `pipeline=bertopic_llm`. |
| `ENTRADA_Y_BERTOPIC.md` | Contrato del **payload de entrada** (`solicitud`, `jornada`, `momentos`, `personalizacion`, `fuentes`, `bertopic`) y del adaptador BERTopic. | Es la especificación de `analitica/v2/entrada.py` y `analitica/v2/bertopic_adaptador.py`. La fase 2 y la fase 5 lo traducen a código contra los modelos reales. |
| `README.md` | Decisiones del contrato, cableado sugerido con `response_format: json_schema, strict: true`, y la **tabla de validación de negocio obligatoria**. | Fase 1 (validación) y fase 3 (llamada). |
| `TIPOS_VISUALES.md` | Condiciones semánticas por tipo de visualización (dona exhaustiva, radar con rango, histograma `[desde, hasta)`, etc.). | Fase 1 — reglas por variante en `validacion.py`. |
| `MIGRACION_FRONTEND.md` | Cambios del lado del frontend. Lo relevante para el backend: **desaparece la elección de `enfoque`**, el usuario elige **alcance** (`integral` / `por_momento`) + contexto + instrucciones (+ por momento), el FE elige renderer **por `version` del resultado** y conserva los visores históricos. | Justifica D1 (modelo nuevo, legacy intacto). |
| `ejemplos/*.entrada.json` / `*.salida.json` | 4 pares ficticios (llm_integral, llm_por_momento, bertopic_integral, sin_datos) + `catalogo_visual.salida.json` (fixture del renderer, sin entrada). | Fixtures de la fase 1 (comando y tests). |
| `verificar_entrega.py` | Validador de referencia (esquema + invariantes). | Se porta y amplía en `analitica/v2/validacion.py`. No se ejecuta desde el backend. |

Resumen del contrato de salida (raíz): `version` (const `"kunsamu.analisis/v2"`), `pipeline`
(`llm` | `bertopic_llm`), `estado` (`completo` | `parcial` | `sin_datos` | `datos_insuficientes`),
`alcance` (`{modo, jornada_id, momento_ids}` — **debe ser idéntico a `solicitud` de la entrada**),
`fuentes[]` (metadatos copiados tal cual de las fuentes de entrada, **sin `datos`**),
`cobertura[]` (exactamente una fila por pregunta inventariada), `limitaciones[]`, `informes[]`
(1 en integral; 1 por momento en por_momento, en el orden de `solicitud.momento_ids`), cada
informe con `resumen`, `hallazgos[]` (`titulo`, `naturaleza`, `afirmacion`, `implicacion|null`,
`metodos[]`, `fuente_ids[]`, `pregunta_ids[]`, `metricas[]`, `citas[]`, `limitaciones[]`,
`visualizacion_ids[]`) y `recomendaciones[]`; y `visualizaciones[]` tipadas referenciadas por id.
Las citas son **subcadenas literales** de un texto localizado con `fuente_id` + JSON Pointer
relativo a `fuente.datos` (`/respuestas/10/valor`). Los IDs de la entrada son **strings**.

**Unidades de porcentaje**: los ejemplos usan `"porcentaje"` en `metricas[].unidad` y en
`datos.unidad` de las visualizaciones categóricas; `TIPOS_VISUALES.md` usa `"%"`. La validación
de este plan trata **ambas** como porcentaje (ver fase 1).

## 2. Qué hay hoy en el backend (app `analitica`)

### 2.1 Modelos (`analitica/models.py`)

- `PlantillaAnalisis` — prompts de sistema editables por tipo (`local`, `gpt_momento`,
  `gpt_jornada`). **v2 NO los usa** (D5).
- `Reporte` — pipeline local "bertopic" (`analysis.py`): `jornada` FK, `momentos` M2M (vacío =
  jornada completa), `alcance` (`jornada`|`momento`|`momentos`), `estado`
  (`pendiente`|`procesando`|`completo`|`error`), `analisis` JSON (formato jerárquico
  `{participacion, momentos[{preguntas[...]}]}`), `texto_reporte`, `presentacion_*`,
  `prompt_usado`, `modelo_usado`, más los campos del "análisis guiado" (mixins
  `AnalisisGuiadoMixin`: `enfoque`, `contexto`, `instrucciones`; `AnalisisGuiadoPorMomentoMixin`:
  `contexto_momento`, `instrucciones_momento`).
- `AnalisisMomentoIA` — una llamada a OpenAI por momento (`analisis_ia_openai.py`), `resultado`
  JSON `{momento_id, tipo, resumen_ejecutivo, hallazgos[{titulo, descripcion,
  preguntas_relacionadas, tipo_grafica, datos[]}]}`.
- `AnalisisJornadaIA` — ídem a escala de jornada, `resultado` con `momentos_relacionados` y
  `transcripciones_relacionadas` además.
- `InfografiaJornada` (+ `InfografiaImagen`) — 3 láminas por OpenAI Images; se ata a EXACTAMENTE
  uno de `reporte` / `analisis_momento` / `analisis_jornada` (validado en
  `InfografiaJornadaCrearSerializer.validate`).

Los tres modelos de análisis comparten el patrón: campos `estado`, `error_mensaje`,
`modelo_usado`, `prompt_usado`, `solicitado_por` FK a usuario (`SET_NULL`), `creado_en`,
`actualizado_en`, `completado_en`; `Meta.ordering = ['-creado_en']`.

Migraciones existentes: hasta `analitica/migrations/0016_infografia_fija_analisis_exacto.py`. La
próxima es `0017`.

### 2.2 Modelos de dominio que la entrada v2 necesita

`jornadas/models.py`:
- `Jornada`: `id`, `slug`, `nombre`, `descripcion` (texto libre, único "objetivo" disponible),
  `fecha_inicio`, `fecha_fin`, `propietarios` M2M (scoping), `momentos` (reverse FK).
- `Momento`: `jornada` FK, `orden`, `titulo`, `contexto`, `tipo` (`individual` | `mesa`),
  `categorias_semilla` JSON (lista de strings, puede estar vacía), `mesas_permitidas` JSON,
  `roles_permitidos` JSON, `activo` (visibilidad para participantes — **NO** significa "sin
  datos"; los análisis de jornada completa incluyen momentos inactivos), `preguntas` (reverse FK).
- `Pregunta`: `momento` FK, `tipo` ∈ `abierta` | `unica` | `multiple` | `matriz` | `lista` |
  `audio` (**los mismos nombres canónicos que pide el contrato v2**; `audio` se guarda igual que
  `abierta`: texto), `texto`, `orden`, `obligatoria`, `activa`, `filas_adicionales`,
  `mesas_permitidas`, `roles_permitidos`, `depende_de_opcion` FK a `OpcionPregunta` (nullable),
  propiedad `acepta_filas_dinamicas`, constante `Pregunta.TIPOS_TEXTO_LIBRE = ('abierta','audio')`.
  Relaciones reversas: `opciones` (`OpcionPregunta`: `id`, `texto`, `orden`), `filas`
  (`FilaMatrizPregunta`: `id`, `texto`, `orden` — solo matriz), `columnas`
  (`ColumnaMatrizPregunta`: `id`, `texto`, `orden` — matriz y lista).

`participantes/models.py`:
- `Participante`: `jornada` FK, `nombre`, `apellido`, `rol`, `mesa` (int nullable), `es_vocero`.
- `FilaListaRespuesta`: fila agregada por quien responde (todas las filas de una `lista`; filas
  extra de una `matriz` con `filas_adicionales`): `pregunta` FK, `participante` FK nullable,
  `mesa` nullable, `orden`.
- `Respuesta`: `pregunta` FK, `participante` FK nullable (momentos individuales), `mesa` int
  nullable (momentos tipo mesa; `participante` queda null), `registrado_por`, `fila` FK
  `FilaMatrizPregunta` nullable, `columna` FK `ColumnaMatrizPregunta` nullable, `fila_lista` FK
  `FilaListaRespuesta` nullable, `texto_libre` (texto; `''` = vacío), `opciones` M2M a
  `OpcionPregunta`. Para `matriz`/`lista` hay **una fila `Respuesta` por celda** (fila×columna),
  todas con texto en `texto_libre`; las celdas de una misma persona/mesa se agrupan por
  (`participante_id` o `mesa`).

`transcripciones/models.py` (no entra en v2 en este plan, ver D10): `SesionTranscripcion`
(`jornada` FK nullable, `incluir_en_analisis_jornada`), `FragmentoTranscripcion` (`texto`,
`hablante`, `inicio_ms`, `fin_ms`), `InformeTranscripcion` (`resultado` JSON).

### 2.3 Endpoints actuales (`analitica/urls.py`, montados bajo `/api/admin/` y también bajo `/api/aluna-kunsama/api/admin/`)

| Ruta | Vista | Nota |
|---|---|---|
| `plantillas-analisis/` | `PlantillaAnalisisViewSet` | |
| `reportes/` (+ `generar-presentacion/`, `generar-infografia/`, `pdf/`) | `ReporteViewSet` | pipeline local |
| `analisis-momento-ia/` | `AnalisisMomentoIAViewSet` | OpenAI, un momento |
| `analisis-jornada-ia/` | `AnalisisJornadaIAViewSet` | OpenAI, jornada |
| `infografias/` | `InfografiaJornadaViewSet` | |
| `analisis/` | `AnalisisUnificadoView` | **lista unificada** `GET ?jornada=` / `?momento=` (une los tres modelos; items con `tipo`, `id`, `jornada`, `momento`, `momento_titulo`, `momento_orden`, `metodo`, `enfoque`, `alcance`, `estado`, `error_mensaje`, `creado_en`, `completado_en`) |
| `analisis-sugerencias/` | `AnalisisSugerenciasView` | sugerencias de contexto/instrucciones; `enfoque` es opcional con default — **no requiere cambios** |
| `estadisticas-preguntas/`, `progreso-participantes/`, `mesas/`, `reporte-excel-*` | varias | sin relación con v2 |

Autenticación: `Authorization: Token <token>` (staff). Permiso base `IsAdminUser`. Scoping por
"dependencia": `jornadas.scoping.filtrar_por_propietario(queryset, user, 'jornada__propietarios')`
para listados y `jornadas.scoping.verificar_acceso_jornada(user, jornada)` (lanza
`PermissionDenied` → 403) para creaciones. Un usuario sin `PerfilUsuario` es admin completo.

### 2.4 Patrones del módulo que v2 debe replicar

- **Trabajo en background**: la vista crea el registro en `pendiente`, lanza
  `threading.Thread(target=funcion, args=(id,), daemon=True).start()` y responde `201` con el
  serializer de lectura. La función de background empieza con `from django.db import
  close_old_connections; close_old_connections()`, envuelve todo en `try/except Exception` que
  marca `estado='error'` + `error_mensaje`, y termina con `close_old_connections()` en `finally`.
  Ver `analitica/analisis_ia_openai.py::analizar_jornada_ia` (líneas ~524–576).
- **Auto-sanación de huérfanos**: antes de crear, marcar `error` cualquier registro
  `pendiente/procesando` del mismo alcance con `actualizado_en` más viejo que un umbral
  (`UMBRAL_HUERFANO_ANALISIS_IA = timedelta(minutes=10)` en `admin_views.py`).
- **409 si ya hay uno en curso** para el mismo alcance.
- **Llamada a OpenAI**: cliente `from openai import OpenAI; OpenAI(api_key=...)`,
  `client.chat.completions.create(model=..., messages=[system, user],
  max_completion_tokens=..., response_format={'type': 'json_object'})`; si
  `OPENAI_REASONING_EFFORT` (default `'medium'`) está definido se manda `reasoning_effort` y **no**
  `temperature` (los modelos de razonamiento rechazan `temperature`). Llamada en un hilo con
  `hilo.join(timeout=...)`. Devuelve `(dict_o_None, error)` y **nunca lanza**. Ver
  `_llamar_openai_json` en `analisis_ia_openai.py` (líneas ~370–419). Variables: `OPENAI_API_KEY`,
  `OPENAI_MODEL` (default `gpt-4o`; en producción real está configurado un modelo de
  razonamiento), `OPENAI_REASONING_EFFORT`.
- **Serializers**: uno de creación (`*CrearSerializer`, `ModelSerializer` con `read_only_fields`
  para `id/estado/creado_en`) y uno de lectura con `read_only_fields = fields`. Los `GET` exponen
  `metodo` como `SerializerMethodField` constante por modelo.
- **Tests**: `analitica/tests.py` (822 líneas, `APITestCase`, sin `OPENAI_API_KEY` en el entorno,
  helpers `crear_jornada(slug, propietario=None)`, `crear_momento_con_respuesta(jornada, orden=1,
  titulo=...)`, `crear_dependencia(username)`, `crear_admin_completo(username)`). Los nuevos van en
  `analitica/tests_v2.py` (Django descubre `test*.py`) importando esos helpers.

### 2.5 Pipeline local actual (`analitica/analysis.py`) — lo que se reutiliza en la fase 5

- `MIN_RESPUESTAS_TOPICOS = 8`, `MAX_TEMAS_CANDIDATOS = 5`,
  `EMBEDDING_MODEL_NAME = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'`,
  `STOPWORDS_ES` (lista), `_get_embedder()` (singleton de `SentenceTransformer`).
- `_descubrir_topicos_bertopic(textos)` (líneas ~316–362) arma `UMAP(n_neighbors=max(2, min(15,
  n-1)), n_components=max(2, min(5, n-2)), min_dist=0.0, metric='cosine', random_state=42)`,
  `HDBSCAN(min_cluster_size=max(2, min(5, n//4)), metric='euclidean',
  cluster_selection_method='eom', prediction_data=True)`, `CountVectorizer(stop_words=STOPWORDS_ES,
  ngram_range=(1, 3), min_df=1)` y `BERTopic(embedding_model=_get_embedder(), umap_model=...,
  hdbscan_model=..., vectorizer_model=..., verbose=False, calculate_probabilities=False,
  nr_topics=MAX_TEMAS_CANDIDATOS)`, luego `modelo.fit_transform(textos)`. **Devuelve solo palabras
  clave y ejemplos** — no exporta asignaciones por documento ni pesos, por eso la fase 5 escribe
  su propio adaptador (copiando esta configuración, sin modificar esta función).
- `_estadisticas_pregunta(pregunta)` — conteos por opción (`{'total_respuestas', 'conteo_opciones':
  [{'opcion_id','texto','conteo'}]}`) o para texto libre `{'total_respuestas','respuestas_no_vacias'}`.

### 2.6 Infraestructura

- Docker Compose (`db`, `app`, `git-sync`). `git-sync` vigila `origin/develop` y reconstruye `app`
  con cada commit nuevo (`docker compose up -d --build --no-deps app`). Las migraciones las aplica
  `docker/entrypoint.sh` al arrancar el contenedor.
- `requirements.txt` sin pines. `jsonschema` **no está declarado** aunque llega como dependencia
  transitiva; la fase 0 lo declara explícitamente.
- `.env.example` documenta `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_IMAGE_MODEL`, `OPENAI_IMAGE_SIZE`.

## 3. La brecha, punto por punto

| Lo que el FE espera | Lo que hay | Qué hace el plan |
|---|---|---|
| Un resultado `kunsamu.analisis/v2` con `informes[]`, `cobertura[]`, `fuentes[]`, `visualizaciones[]` tipadas | Tres formatos distintos y planos (`Reporte.analisis` jerárquico; `resultado` con `hallazgos[{tipo_grafica ∈ pastel/barras/radar, datos[]}]`) | Modelo nuevo `AnalisisV2` con `resultado` v2 (D1). Legacy intacto. |
| El usuario elige alcance `integral` / `por_momento` (varios momentos en una sola solicitud → varios informes) | `Reporte` (jornada/momento/momentos), `AnalisisMomentoIA` (1 momento), `AnalisisJornadaIA` (jornada) | `POST /api/admin/analisis-v2/` con `modo` + `momentos` (D2). |
| Sin `enfoque`; personalización = contexto + instrucciones + por momento | `enfoque` obligatorio en los tres; bloques de enfoque anexados al prompt | v2 no tiene `enfoque`; personalización viaja **como datos** en el payload `user`, nunca en el `system` (D5). |
| Prompt = archivo entero + esquema estricto; el backend controla prompt/esquema/inventario | Prompts compuestos (plantilla → enfoque → contexto → instrucciones → regla) | `system` = archivo congelado; `user` = JSON de entrada; `response_format` json_schema strict (D5, D6). |
| Entrada normalizada con fuentes `respuestas`/`agregado`/`bertopic`, IDs string, JSON Pointers, inventario completo incluso sin respuestas | Payloads ad hoc (`_construir_payload_*`) con conteos y textos | `analitica/v2/entrada.py` (D7, D8). |
| Validación de esquema **y** de negocio antes de publicar; un reintento de reparación; nunca publicar JSON inválido; conservar entrada inmutable y errores para auditoría | Limpiezas puntuales por regex; sin esquema | `validacion.py` + `procesar.py` con `entrada`, `diagnostico`, `version_prompt`, `version_esquema` (D9). |
| `sin_datos` es un estado analítico válido; un fallo técnico es estado del trabajo | `400` si el alcance no tiene respuestas | v2 genera la salida `sin_datos` **en el backend, sin llamar a la IA** (D11). |
| BERTopic exportado como `topicos/documentos/agregados` con IDs compuestos `run::native` | Solo palabras clave + ejemplos | Adaptador nuevo, fase 5 (D8). |
| Infografía/presentación/historial como consumidores a revisar | Infografía atada a los tres modelos legacy | Fase 6: `InfografiaJornada.analisis_v2` (D12). Presentación HTML/PDF de v2: fuera de alcance (D10). |
