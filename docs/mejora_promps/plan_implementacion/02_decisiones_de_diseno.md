# 02 — Decisiones de diseño (obligatorias)

Cada decisión trae el porqué. Si al implementar encuentras una razón fuerte para cambiar alguna,
**no la cambies en silencio**: implementa lo que dice aquí y reporta la objeción.

## D1. Modelo nuevo `AnalisisV2`; los tres modelos legacy no cambian

Se crea `analitica.models.AnalisisV2` (tabla nueva) con el resultado v2. `Reporte`,
`AnalisisMomentoIA` y `AnalisisJornadaIA` quedan **exactamente como están** (modelo, endpoints,
pipelines, formato). Razones:

- El FE va a elegir renderer **por `version` del resultado** y conservar los visores históricos
  (`MIGRACION_FRONTEND.md` §7). Un modelo nuevo hace esa distinción trivial: todo lo legacy sigue
  sin `version`; todo lo v2 la trae.
- El contrato v2 rompe la partición actual por alcance (un `por_momento` con varios momentos
  produce varios informes en **una** solicitud). Encajarlo en tres modelos separados obligaría a
  tocar los tres y sus consumidores (presentación HTML, PDF, Excel, infografía).
- Riesgo: cero regresiones en lo que hoy funciona en producción.

## D2. Un endpoint nuevo: `POST/GET/DELETE /api/admin/analisis-v2/`

Cuerpo de creación:

```json
{
  "jornada": 14,
  "modo": "integral" | "por_momento",
  "momentos": [61, 62],                 // obligatorio y no vacío en por_momento; DEBE ir vacío/ausente en integral
  "pipeline": "llm" | "bertopic_llm",
  "contexto": "…",                      // ≤ 4000 caracteres, opcional
  "instrucciones": "…",                 // ≤ 4000, opcional
  "personalizacion_momentos": [         // opcional; cada momento del alcance como máximo una vez
    {"momento": 61, "contexto": "…", "instrucciones": "…"}
  ]
}
```

Semántica de alcance: `integral` = **todos** los momentos de la jornada (activos o no, ordenados
por `orden`), un solo informe. `por_momento` = los momentos indicados, ordenados por `orden`
(ese es "el orden recibido" que el contrato pide respetar en `informes`), un informe por momento.
No se acepta `momentos` en `integral` (400) para que nadie crea que "integral de tres momentos"
existe: el FE ya distingue "Toda la jornada" de "Por momento".

`metodo` en la lista unificada se deriva del pipeline (`bertopic_llm` → `"bertopic"`, `llm` →
`"openai"`) para que la agrupación actual del panel siga funcionando sin cambios.

## D3. Estados: el del trabajo y el analítico son cosas distintas

`AnalisisV2.estado` ∈ `pendiente` | `procesando` | `completo` | `error` (estado del trabajo, como
el resto del módulo). El estado **analítico** vive dentro de `resultado.estado` (`completo` |
`parcial` | `sin_datos` | `datos_insuficientes`). Un fallo de OpenAI, de validación o de tamaño es
`estado='error'` con `error_mensaje`, **nunca** un `resultado` con `sin_datos`.

## D4. Guards en la creación: 403 → 400 de forma → 409 en curso. Sin guard de "sin respuestas"

Orden en `create()`: `is_valid` (400 de forma) → `verificar_acceso_jornada` (403) → sanar
huérfanos → 409 si hay otro `AnalisisV2` `pendiente/procesando` con **la misma jornada, el mismo
`modo` y el mismo conjunto de momentos** → 400 si la jornada no tiene momentos (nada que
inventariar) → crear + hilo. Dos análisis v2 de alcances distintos de la misma jornada sí pueden
correr en paralelo (cada uno es una llamada independiente a OpenAI).

**No hay guard de "el alcance no tiene respuestas"**: `sin_datos` es un estado analítico válido
del contrato y el FE lo renderiza (ver D11 para cómo se produce sin gastar una llamada).

Umbral de huérfano: 45 minutos (`UMBRAL_HUERFANO_ANALISIS_V2`) — la llamada v2 es una sola pero
grande (salida de hasta ~24k tokens con un modelo de razonamiento) y en `bertopic_llm` va
precedida de embeddings + clustering por pregunta.

## D5. El prompt es el archivo, entero, sin anexos. La personalización es un dato del `user`

`system` = contenido íntegro de `SYSTEM_PROMPT_LLM.md` o `SYSTEM_PROMPT_BERTOPIC.md` (copias
congeladas en `analitica/v2/recursos/`). `user` = `json.dumps(entrada, ensure_ascii=False)` (sin
indentación: es el mismo JSON, menos tokens). **No** se usan `PlantillaAnalisis`, ni
`prompt_comun.ensamblar_system`, ni `REGLA_DATOS_ANALISIS`, ni los bloques de enfoque. Lo pide el
README de la entrega de forma explícita ("No se deben anexar los antiguos bloques de enfoque ni
las instrucciones que permiten al prompt del usuario prevalecer sobre el system"). Contexto e
instrucciones del usuario viajan en `entrada.personalizacion`.

Versionado: `VERSION_PROMPT` y `VERSION_ESQUEMA` (constantes en `contrato.py`, `'v2.0'`) se
guardan en cada `AnalisisV2` para auditoría. Quien cambie un archivo de `recursos/` sube la
constante correspondiente a mano.

## D6. Salida estructurada estricta, con respaldo

`response_format = {'type': 'json_schema', 'json_schema': {'name': 'kunsamu_analisis_v2',
'strict': True, 'schema': <esquema sin `$schema`/`title`/`description` raíz>}}`. Si el proveedor
rechaza ese `response_format` (excepción cuyo texto menciona `schema` o `response_format`), se
reintenta **una vez** con `{'type': 'json_object'}` y el esquema completo anexado al `system`
bajo el encabezado `ESQUEMA JSON OBLIGATORIO DE LA SALIDA`. En ambos casos la respuesta se valida
igual (D9): el modo estricto reduce errores, no reemplaza la validación. Antes de parsear se
comprueba `message.refusal` (rechazo → error) y `finish_reason == 'stop'` (truncado → error, nunca
se parsea un JSON incompleto). `json.loads` con `parse_constant` que rechaza `NaN`/`Infinity`.

Parámetros: `max_completion_tokens = KUNSAMU_V2_MAX_OUTPUT_TOKENS` (default 24000), timeout
`KUNSAMU_V2_TIMEOUT_SECONDS` (default 540 s), modelo `OPENAI_MODEL_V2` si existe, si no
`OPENAI_MODEL`; `reasoning_effort` / `temperature` con la misma regla que el resto del módulo.

## D7. La entrada normalizada se construye desde la base de datos, con IDs string y orden determinista

`analitica/v2/entrada.py::construir_entrada(...)` produce el sobre completo de
`ENTRADA_Y_BERTOPIC.md` §1–§2. Reglas fijas (detalle en la fase 2):

- IDs: `str(pk)` para jornada, momentos, preguntas, opciones, filas, columnas. Fuentes:
  `f-m{momento.id}` (respuestas), `f-agg-m{momento.id}` (agregado), `fbt-p{pregunta.id}`
  (bertopic). Respuestas escalares: `r{respuesta.id}`; respuestas de matriz/lista (agrupadas por
  sujeto): `r-q{pregunta.id}-{sujeto}`. Sujetos: `p{participante_id}` o `mesa-{n}`.
- Inventario de preguntas por momento: `activa=True` **o** con al menos una `Respuesta`
  (`Q(activa=True) | Q(respuestas__isnull=False)`, `distinct`), ordenadas por `orden`. Así una
  pregunta desactivada con datos reales no desaparece del inventario en silencio.
- **Una fuente `respuestas` por momento del alcance, siempre** (aunque esté vacía): esa fuente
  vacía con `cobertura: "completa"` es lo que permite afirmar `sin_datos` en vez de `no_recibida`.
- **Una fuente `agregado` por momento con preguntas cerradas**: conteos por opción y bases
  calculados por el backend (la filosofía del módulo: los números nunca dependen del LLM). Le da
  al modelo cifras `origen: reportado` con ruta verificable (`/distribuciones/0`).
- El orden del array `respuestas` de cada fuente es: preguntas por `orden`, dentro de cada
  pregunta por `Respuesta.id` ascendente (matriz/lista: por primer `id` de celda de cada sujeto).
  Los JSON Pointers de citas y de documentos BERTopic dependen de ese orden; **la entrada se
  guarda en `AnalisisV2.entrada` antes de llamar a OpenAI y no se recalcula nunca**.
- `categorias_semilla` del momento no tiene campo propio en el contrato: se agrega al final de
  `momentos[].contexto` como una frase descriptiva ("Categorías temáticas de referencia definidas
  por el equipo organizador: a, b, c."). Es contexto, no una orden de formato.
- `reglas_elegibilidad`: `descripcion` redactada desde `roles_permitidos`, `mesas_permitidas`,
  `depende_de_opcion` y `obligatoria`; `filtro` = identificador legible de esas reglas o `null`;
  `unidad_esperada` = `persona` (momento individual) | `mesa`; `escala` siempre `null` (el modelo
  de datos no tiene escalas ordinales); `estructura` solo en `matriz`/`lista`.

## D8. BERTopic en v2: una ejecución por pregunta de texto con ≥ 8 respuestas, exportación honesta

Fase 5. Misma configuración de UMAP/HDBSCAN/vectorizador/`nr_topics` que
`analysis._descubrir_topicos_bertopic` (copiada, no modificada), mismo embedder singleton. Se
exporta lo que BERTopic **realmente** calcula: `topicos` (con `Count`, términos c-TF-IDF con
`weight_type: "c_tf_idf"`, docs representativos), `documentos` (asignación final por documento,
con `localizador` a la fuente `respuestas`), `agregados` (conteos por tópico, denominador = docs
procesados, outliers incluidos). `distribuciones`, `similitudes`, `coocurrencias`, `proyecciones`
van `[]` (no se calculan; inventarlos violaría el contrato). El tópico `-1` se conserva como
outliers. IDs compuestos `run-p{pregunta.id}::{native_id}` con `urllib.parse.quote`. Preguntas con
menos de 8 textos o cuya ejecución falle no tienen ejecución; se anota en
`AnalisisV2.diagnostico['bertopic']` (no en la salida del LLM). Con cero ejecuciones, `bertopic =
{"version_adaptador": "1.0", "ejecuciones": []}` — válido y declarado.

Hasta que la fase 5 exista, `bertopic_adaptador.anexar_bertopic` es un **stub** que devuelve
exactamente eso, para que `pipeline=bertopic_llm` no rompa nada desde la fase 4.

## D9. Validar dos veces, reparar una vez, nunca publicar inválido

`procesar.py`: (1) `validar_esquema` con `jsonschema.Draft202012Validator` sobre el esquema
congelado; si pasa, (2) `validar_negocio` (porta y amplía `verificar_entrega.semantic_checks`:
alcance, cobertura, fuentes, IDs, referencias, citas literales, porcentajes, reglas por tipo de
visualización — lista completa en la fase 1). Si hay errores: **un** reintento con la conversación
extendida (`assistant`: JSON previo, `user`: lista de errores + "devuelve el objeto completo
corregido"). Si sigue fallando: `estado='error'`, `error_mensaje` con los primeros errores, y todo
(ambas salidas descartadas + errores + metadatos de la llamada) en `AnalisisV2.diagnostico` para
auditoría. `resultado` queda `{}`. Prohibido "arreglar" números, convertir `null` en 0 o borrar
claves para que pase.

Las reglas de **estilo** (longitud de resumen, palabras por título) no se validan: no están en la
tabla de validación obligatoria del README y fallarlas convertiría en error técnico un informe
correcto.

## D10. Fuera de alcance de este plan (explícito)

- Presentación HTML y PDF de un `AnalisisV2` (los actuales leen el formato jerárquico de
  `Reporte`). El FE renderiza v2 con su renderer común; si más adelante se quiere PDF, es otra HU.
- Transcripciones como fuente `transcripcion`/`resumen_secundario` en v2. Hoy solo
  `AnalisisJornadaIA` las incluye (como resúmenes). Se deja para una HU posterior; el contrato ya
  lo contempla y no hay que cambiar nada del esquema.
- Corpus que excedan el contexto del modelo (codificación por lotes + agregación). Guard: si el
  JSON de entrada supera `KUNSAMU_V2_MAX_CARACTERES_ENTRADA` (default 1.200.000 caracteres,
  ≈300k tokens), el trabajo termina en `error` con un mensaje que pide usar `por_momento` con
  menos momentos.
- Cambios en `analisis-sugerencias/` (sigue aceptando `enfoque` opcional; el FE puede dejar de
  mandarlo sin que nada cambie).
- Instrumentos (`instrumentos/`), que tienen su propio modelo de respuestas.

## D11. `sin_datos` lo produce el backend sin llamar a la IA

Si ninguna fuente `respuestas` del alcance tiene respuestas, `procesar.py` construye la salida
v2 determinísticamente (`sin_datos.py`): `estado: "sin_datos"`, cobertura completa con
`estado: "sin_datos"` por pregunta, un informe por alcance con un `resumen` fijo y
`hallazgos/recomendaciones/visualizaciones` vacíos, `fuentes` copiadas de la entrada. Se valida
con las mismas dos capas (si no pasara, es un bug y el trabajo termina en `error`).
`modelo_usado = 'Sin datos — generado por el backend sin IA'`, `prompt_usado = ''`. Ahorra una
llamada cara para producir nada, y es más fiable que pedirle al modelo que "no invente".

## D12. Infografía desde un `AnalisisV2` (fase 6)

`InfografiaJornada` gana un cuarto FK `analisis_v2` (mutuamente excluyente con los otros tres,
misma regla "exactamente uno"). `_obtener_datos_analitica` traduce el resultado v2 al mismo
diccionario que ya consumen las láminas (`resumen_ejecutivo`, `hallazgos[{titulo, descripcion,
tipo_grafica, datos[{etiqueta, valor, unidad}]}]`), tomando `afirmacion` (+ `implicacion`) como
descripción y `metricas` como datos. No cambia el prompt de imagen. Es la única pieza legacy que
se toca, porque el FE pide la infografía desde la tarjeta del análisis y no debería quedar sin
botón para los v2.
