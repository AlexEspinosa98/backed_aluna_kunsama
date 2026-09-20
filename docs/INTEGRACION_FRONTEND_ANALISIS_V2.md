# Integración frontend — Análisis v2 (contrato `kunsamu.analisis/v2`)

Implementa la entrega `docs/mejora_promps/` (20-sep-2026), plan de ejecución en
[`docs/mejora_promps/plan_implementacion/`](mejora_promps/plan_implementacion/README.md).

**Rediseño (20-sep-2026, HU-78 en `docs/USER_STORIES_COMPLETO.md`):** la primera implementación
levantó el contrato v2 como una vía aparte, `POST /api/admin/analisis-v2/` (HU-73 a HU-77). El
dueño del repo corrigió el rumbo: la intención siempre fue que el contrato v2 **reemplazara** la
salida de los tres endpoints que el frontend ya integraba (`analisis-jornada-ia/`,
`analisis-momento-ia/`, `reportes/`), no que conviviera aparte de ellos. Desde entonces, esos tres
endpoints corren el mismo pipeline v2 por dentro y devuelven el mismo JSON — **sin que el frontend
tenga que cambiar ninguna llamada**: cuerpos de petición idénticos a los de siempre, mismos campos
de respuesta de siempre (`resultado`/`analisis`), ahora con el contrato v2 adentro. La §1 de abajo
es la referencia completa de ese mapeo; el resto del documento (§2 en adelante, sin cambios de
fondo respecto a la versión anterior de esta guía) describe `POST /api/admin/analisis-v2/`, que
sigue existiendo como vía adicional con la misma salida, pero ya NO es el camino principal.

Lo que el frontend recibe en el campo de resultado (`resultado` en los tres endpoints existentes y
en `analisis-v2/`; `analisis` en `reportes/`) es EXACTAMENTE el JSON de
[`analisis.schema.json`](mejora_promps/analisis.schema.json), ya validado (esquema + reglas de
negocio) — nunca llega un resultado inválido: si la IA no logra producir uno válido tras un
reintento de reparación, el trabajo termina en `estado: "error"` con `resultado`/`analisis: {}`,
nunca con un JSON a medias. Los registros generados ANTES del rediseño conservan su formato
jerárquico de siempre (ver
[INTEGRACION_FRONTEND_ANALISIS_GUIADO.md](INTEGRACION_FRONTEND_ANALISIS_GUIADO.md)) — el frontend
elige renderer por la presencia (o no) del campo `version` en el item (§1, §4).

Sin `enfoque`: el contrato v2 lo elimina. El modelo decide, pregunta por pregunta, el método más
adecuado y lo declara en `naturaleza`/`metodos` de cada hallazgo — la personalización del usuario
viaja como `contexto`/`instrucciones` (generales y por momento), nunca como una instrucción de
formato. `enfoque` (y `plantilla`, en `reportes/`) se siguen aceptando y guardando en los tres
endpoints existentes por compatibilidad con el frontend actual, pero ya no influyen en nada (§1).

---

## 0. URL base

Igual que el resto del panel (ver §0 de
[INTEGRACION_FRONTEND_ANALISIS_GUIADO.md](INTEGRACION_FRONTEND_ANALISIS_GUIADO.md)):

```
Base URL (desarrollo, rama develop):  https://kunsamu.josec.ddns.net
```

Sin el prefijo `/api/aluna-kunsama/` en desarrollo; en producción (cuando el dueño del repo haga
el merge a `main`) las mismas rutas quedan bajo ese prefijo. Autenticación: `Authorization: Token
<hex de 40 chars>`. Permiso `IsAdminUser` + scoping por dependencia (`jornadas.scoping`), igual
que todo `analitica/`.

---

## 1. Los endpoints de siempre ya devuelven v2 (sin cambiar las llamadas)

Los tres endpoints que el frontend ya integraba (ver
[INTEGRACION_FRONTEND_ANALISIS_GUIADO.md](INTEGRACION_FRONTEND_ANALISIS_GUIADO.md)) corren ahora
`analitica/v2/procesar.py::ejecutar_analisis_v2` por dentro (`analisis_ia_openai.py::
analizar_momento_ia`/`analizar_jornada_ia`, `analysis.py::procesar_reporte`). El cuerpo de la
petición NO cambia — sigue siendo el de siempre — y el campo donde ya se leía el resultado sigue
siendo el mismo campo; lo único que cambia es lo que hay adentro.

| Endpoint | Pipeline v2 | Modo v2 | Campo con el JSON v2 |
|---|---|---|---|
| `POST /api/admin/analisis-jornada-ia/` | `llm` | `integral` — todos los momentos de la jornada, un solo informe | `resultado` |
| `POST /api/admin/analisis-momento-ia/` | `llm` | `por_momento` de ESE momento | `resultado` |
| `POST /api/admin/reportes/` | `bertopic_llm` | `momentos=[]` → `integral`; `momentos` con ids → `por_momento` (un informe por cada momento) | `analisis` |

- `contexto_momento`/`instrucciones_momento` (el par que ya mandaban `analisis-momento-ia/` y, en
  `reportes/`, un reporte de un único momento) viajan al pipeline v2 como
  `personalizacion_momentos=[{"momento": <id>, "contexto": ..., "instrucciones": ...}]`, que
  `analitica/v2/entrada.py::construir_entrada` vuelca en
  `entrada.personalizacion.instrucciones_por_momento` (`[{"momento_id", "instrucciones",
  "contexto"}, ...]`) — mismo lugar del sobre de entrada que llena `personalizacion_momentos` en
  `POST /api/admin/analisis-v2/` (§2).
- En `reportes/`, `Reporte.texto_reporte` (el resumen narrativo que ya exponía el serializer) ahora
  sale de `resumen_de_salida(resultado)`: la concatenación de los `resumen` de cada informe del
  JSON v2, en vez de la síntesis del pipeline multiagente anterior.
- **`enfoque` (los tres endpoints) y `plantilla` (`reportes/`) se siguen aceptando y guardando en
  el registro por compatibilidad con el frontend actual, pero ya NO influyen en el análisis** — el
  contrato v2 no tiene noción de enfoque; el modelo decide método/gráfica por hallazgo (ver la
  intro de este documento).
- Los tres modelos (`Reporte`, `AnalisisMomentoIA`, `AnalisisJornadaIA`) ganan los mismos cuatro
  campos de auditoría que ya tenía `AnalisisV2` (mixin `ResultadoV2Mixin`, migración
  `analitica/migrations/0019_resultado_v2_en_analisis_existentes.py`):

  | Campo | Qué es | ¿Sale en el `GET`? |
  |---|---|---|
  | `entrada` | El sobre exacto que se le mandó al modelo (`ENTRADA_Y_BERTOPIC.md`), guardado ANTES de llamar a la IA. | No — pesa (contiene el corpus completo); solo vive en la base. |
  | `diagnostico` | `{"bertopic": [...], "intentos": [...]}`, mismo formato que en `AnalisisV2` (§2). | Sí. |
  | `version_prompt` | Versión del prompt usado (`"v2.0"`). | Sí. |
  | `version_esquema` | Versión del esquema de salida validado (`"v2.0"`). | Sí. |

  Es decir: los `GET` de detalle y de lista de los tres endpoints exponen `diagnostico`,
  `version_prompt` y `version_esquema`, pero nunca `entrada` — mismo criterio que
  `AnalisisV2ListaSerializer`/`AnalisisV2Serializer` (§2).
- **Lista unificada `GET /api/admin/analisis/`**: TODOS los items (los tres tipos legacy más
  `analisis_v2`) traen ahora las claves `version` y `estado_analitico` (`_claves_v2` en
  `admin_views.py`). Un item generado con el contrato v2 trae `version: "kunsamu.analisis/v2"`; un
  registro de ANTES del rediseño (formato jerárquico, con `hallazgos[].tipo_grafica` a la antigua)
  trae `version: null`. `estado_analitico` es `resultado.estado` (o `null` si `version` es
  `null`). **Es exactamente lo que le dice al frontend qué renderer usar** — no hace falta
  inspeccionar la forma del JSON: basta mirar `version`.
- **Infografía**: `_obtener_datos_analitica` (`analitica/infografia_ia_openai.py`) ahora traduce el
  resultado v2 venga de cualquiera de las cuatro fuentes — `reporte`, `analisis_momento`,
  `analisis_jornada` o `analisis_v2` — con la misma lógica (`_datos_desde_resultado_v2`). Pedir una
  infografía de un `Reporte`/`AnalisisMomentoIA`/`AnalisisJornadaIA` generado después del rediseño
  funciona igual que antes, sin cambios en `POST /api/admin/infografias/`.
- **Presentación HTML y PDF de un reporte v2 → `400`**: `POST
  /api/admin/reportes/{id}/generar-presentacion/` y `GET /api/admin/reportes/{id}/pdf/` leen el
  formato jerárquico ANTERIOR de `Reporte.analisis` (`participacion` + `momentos` + `preguntas`);
  un reporte generado con el contrato v2 no tiene esa forma, así que ambos responden `400` con un
  mensaje claro (`MENSAJE_SIN_PRESENTACION_V2` en `admin_views.py`) en vez de una página o un PDF
  vacíos:

  ```json
  {
    "detail": "Este reporte está en el formato kunsamu.analisis/v2: la presentación HTML y el PDF del servidor todavía no soportan ese formato (se renderiza en el panel). Sigue disponible para los reportes generados antes del rediseño."
  }
  ```

  Sigue funcionando sin cambios para los reportes generados ANTES del rediseño. Adaptar esas dos
  capas al contrato v2 es una HU aparte.
- **Transcripciones vinculadas a la jornada** (`incluir_en_analisis_jornada=True`) todavía no
  entran al análisis v2 de jornada (`analisis-jornada-ia/`) — antes del rediseño sí se incluían
  como resúmenes en el análisis de jornada anterior. Limitación conocida, HU aparte.

---

## 2. Pedir un análisis — `POST /api/admin/analisis-v2/`

Cuerpo (`AnalisisV2CrearSerializer`, ver `analitica/serializers.py`):

```json
{
  "jornada": 14,
  "modo": "integral",
  "pipeline": "llm",
  "contexto": "Jornada de planeación estratégica con docentes y estudiantes.",
  "instrucciones": "Prioriza tensiones entre grupos, no solo consensos.",
  "personalizacion_momentos": [
    {"momento": 61, "contexto": "Se trabajó en mesas de ocho personas.", "instrucciones": "Destaca las tensiones entre generaciones."}
  ]
}
```

| Campo | Tipo | Default | Notas |
|---|---|---|---|
| `jornada` | int (pk) | — obligatorio | Debe pertenecer a la dependencia del usuario (o ser admin completo). |
| `modo` | `"integral"` \| `"por_momento"` | — obligatorio | `integral` = TODOS los momentos de la jornada, activos o no, un solo informe. `por_momento` = solo los `momentos` indicados, un informe por cada uno, en el orden de `Momento.orden` (no en el orden en que se mandaron los ids). |
| `momentos` | array de int (pks) | `[]` | **Obligatorio y no vacío** en `por_momento`; **no se acepta** (debe ir vacío o ausente) en `integral`. Cada id debe pertenecer a `jornada`. |
| `pipeline` | `"llm"` \| `"bertopic_llm"` | `"llm"` | `bertopic_llm` agrega, antes de llamar a la IA, una ejecución de BERTopic por cada pregunta de texto (`abierta`/`audio`) con 8 o más respuestas no vacías (ver §5). |
| `contexto` | string, ≤4000 caracteres | `""` | Contexto general de quien pide el análisis. Viaja como dato en `entrada.personalizacion.contexto_usuario` — nunca se anexa al system prompt. |
| `instrucciones` | string, ≤4000 caracteres | `""` | Ídem, en `entrada.personalizacion.instrucciones_usuario`. Ajusta énfasis y tono; el formato del informe (el esquema) es fijo por contrato, no lo cambian las instrucciones. |
| `personalizacion_momentos` | array de `{"momento": <id>, "contexto": "", "instrucciones": ""}` | `[]` | Opcional. Cada `momento` debe estar en el alcance de este análisis (todos los de la jornada en `integral`, los indicados en `por_momento`) y aparecer como máximo una vez. |

Respuesta `201` con el análisis recién creado en `estado: "pendiente"` (serializer de detalle,
`AnalisisV2Serializer` — ver §3; `resultado`/`entrada`/`diagnostico` llegan vacíos porque el
trabajo todavía no corrió):

```json
{
  "id": 91,
  "version": "kunsamu.analisis/v2",
  "jornada": "jornada-agil-2",
  "jornada_id": 14,
  "momentos": [],
  "modo": "integral",
  "pipeline": "llm",
  "metodo": "openai",
  "contexto": "Jornada de planeación estratégica con docentes y estudiantes.",
  "instrucciones": "Prioriza tensiones entre grupos, no solo consensos.",
  "personalizacion_momentos": [
    {"momento": 61, "contexto": "Se trabajó en mesas de ocho personas.", "instrucciones": "Destaca las tensiones entre generaciones."}
  ],
  "estado": "pendiente",
  "estado_analitico": null,
  "error_mensaje": "",
  "version_prompt": "",
  "version_esquema": "",
  "modelo_usado": "",
  "solicitado_por": 4,
  "creado_en": "2026-09-20T15:30:00Z",
  "actualizado_en": "2026-09-20T15:30:00Z",
  "completado_en": null,
  "resultado": {},
  "entrada": {},
  "diagnostico": {},
  "prompt_usado": ""
}
```

`version_prompt`/`version_esquema` quedan vacíos hasta que el hilo de background arma la entrada
(justo antes de llamar a la IA o de producir `sin_datos`) — llegan llenos (`"v2.0"`) tanto en
`completo` como en `error`, salvo que el trabajo haya fallado antes de ese punto (excepción muy
temprana).

En `integral`, `momentos` en la respuesta sale `[]` (la M2M queda vacía a propósito: el alcance es
"toda la jornada", no una lista fija de ids que se desactualiza si luego se agregan momentos —
aunque para efectos prácticos el orquestador sí congela la lista real al construir `entrada`).

### Errores

| Código | Cuándo | Forma |
|---|---|---|
| `400` | Forma inválida (`is_valid` del serializer) | Dict con la clave del campo: `{"jornada": [...]}`, `{"modo": [...]}`, `{"pipeline": [...]}`, `{"momentos": ["En modo integral no se mandan momentos: el alcance es toda la jornada."]}` o `{"personalizacion_momentos": [...]}`. |
| `400` | `modo=integral` y la jornada no tiene ningún momento | `{"jornada": ["La jornada no tiene momentos: no hay nada que analizar."]}` |
| `403` | La jornada no pertenece a la dependencia del usuario | `verificar_acceso_jornada` (`PermissionDenied`), mismo formato que el resto del panel. |
| `409` | Ya hay un `AnalisisV2` `pendiente`/`procesando` con la MISMA jornada, el MISMO `modo` y el MISMO conjunto de momentos | `{"detail": "Ya hay un análisis v2 en proceso para este mismo alcance — espera a que termine (o falle) antes de pedir otro."}`. Dos alcances distintos de la misma jornada (por ejemplo un `integral` y un `por_momento` de un solo momento) sí pueden correr en paralelo. |

**No hay `400` por "el alcance no tiene respuestas"**: `sin_datos` es un estado ANALÍTICO válido
del contrato (ver §5) — el backend lo produce sin llamar a la IA y el frontend lo renderiza como
un estado vacío, igual que cualquier otro `resultado.estado`.

Antes de evaluar el `409`, la vista sanea automáticamente cualquier `AnalisisV2` de esa jornada
que lleve más de 45 minutos `pendiente`/`procesando` (lo marca `error` con un mensaje explícito:
probablemente el worker se reinició o falló) — ese umbral es más alto que el de los análisis
legacy (10 min) porque una llamada v2 es una sola pero grande, y en `bertopic_llm` va precedida de
clustering por pregunta.

---

## 3. Consultar

### `GET /api/admin/analisis-v2/?jornada=<id>` | `?momento=<id>`

Lista (`AnalisisV2ListaSerializer`) — **sin** `resultado`, `entrada`, `diagnostico` ni
`prompt_usado` (pesan; la entrada contiene el corpus completo y el resultado puede pesar cientos
de KB):

```json
[
  {
    "id": 91,
    "version": "kunsamu.analisis/v2",
    "jornada": "jornada-agil-2",
    "jornada_id": 14,
    "momentos": [],
    "modo": "integral",
    "pipeline": "llm",
    "metodo": "openai",
    "contexto": "Jornada de planeación estratégica con docentes y estudiantes.",
    "instrucciones": "Prioriza tensiones entre grupos, no solo consensos.",
    "personalizacion_momentos": [],
    "estado": "completo",
    "estado_analitico": "completo",
    "error_mensaje": "",
    "version_prompt": "v2.0",
    "version_esquema": "v2.0",
    "modelo_usado": "Generado con IA",
    "solicitado_por": 4,
    "creado_en": "2026-09-20T15:30:00Z",
    "actualizado_en": "2026-09-20T15:31:40Z",
    "completado_en": "2026-09-20T15:31:40Z"
  }
]
```

Sin `?jornada=`/`?momento=` devuelve todos los que la dependencia del usuario puede ver (mismo
scoping que el resto de `analitica/`). `?momento=<id>` filtra los `AnalisisV2` cuya M2M
`momentos` incluye ese id — un `integral` nunca aparece (su M2M queda vacía), aunque
analíticamente sí cubra ese momento.

### `GET /api/admin/analisis-v2/{id}/`

Detalle (`AnalisisV2Serializer`) — todo lo de la lista más `resultado`, `entrada`, `diagnostico` y
`prompt_usado`:

| Campo | Notas |
|---|---|
| `resultado` | El JSON `kunsamu.analisis/v2` validado (ver §5). `{}` mientras `estado` no es `completo`. |
| `entrada` | El sobre exacto (`ENTRADA_Y_BERTOPIC.md`) que se mandó al modelo — guardado ANTES de llamar y nunca recalculado. Sirve para resolver en el cliente los `localizador` (JSON Pointer) de las citas y de los documentos BERTopic, si se quiere mostrar el texto fuente exacto. |
| `diagnostico` | `{"bertopic": [...], "intentos": [...]}` — notas del adaptador BERTopic (una por pregunta: `ok`/`insuficiente`/`error`) y metadatos de cada llamada a OpenAI (`modo_salida`, `finish_reason`, `usage`, errores de validación de intentos fallidos). Nunca incluye el nombre del proveedor/modelo real. |
| `prompt_usado` | El contenido íntegro de `SYSTEM_PROMPT_LLM.md` o `SYSTEM_PROMPT_BERTOPIC.md` tal cual se mandó como `system` — `""` cuando el resultado es `sin_datos` (no hubo llamada). |

Campos comunes a lista y detalle (`_AnalisisV2CamposDerivados` en `serializers.py`):

| Campo | De dónde sale |
|---|---|
| `version` | Constante `"kunsamu.analisis/v2"` — no depende de si el análisis terminó bien o mal. |
| `jornada` | Slug de la jornada (no el id — para eso está `jornada_id`). |
| `momentos` | `[{"id", "titulo", "slug", "orden"}, ...]` — vacío en `integral`. |
| `metodo` | Derivado del `pipeline` (`bertopic_llm` → `"bertopic"`, `llm` → `"openai"`) para que la agrupación actual del panel (que agrupa por `metodo`) siga funcionando sin cambios. |
| `estado` | Estado del TRABAJO: `pendiente` \| `procesando` \| `completo` \| `error`. |
| `estado_analitico` | `resultado.estado` (`completo` \| `parcial` \| `sin_datos` \| `datos_insuficientes`), o `null` mientras no hay `resultado`. Es un campo DISTINTO de `estado` — un análisis puede estar `estado: "completo"` (el trabajo terminó bien) con `estado_analitico: "sin_datos"` (no había nada que analizar). Un fallo de OpenAI, de tamaño o de validación es siempre `estado: "error"`, nunca un `resultado` con `estado_analitico: "sin_datos"`. |
| `modelo_usado` | `"Generado con IA"` (hubo llamada a OpenAI) o `"Sin datos — generado por el backend sin IA"` (`sin_datos`, D11) — nunca el nombre real del proveedor/modelo. |

Polling: igual que los legacy — reconsultar cada pocos segundos mientras `estado` sea
`pendiente`/`procesando`.

### `DELETE /api/admin/analisis-v2/{id}/`

Borra el registro (sin soft-delete), mismo criterio que el resto del módulo.

---

## 4. Lista unificada — `GET /api/admin/analisis/`

Los items de `AnalisisV2` (`_item_analisis_v2` en `admin_views.py`) llegan con `tipo:
"analisis_v2"` junto a las claves comunes de siempre (`id`, `jornada`, `momento`,
`momento_titulo`, `momento_orden`, `metodo`, `alcance`, `estado`, `error_mensaje`, `creado_en`,
`completado_en`) más cuatro claves EXCLUSIVAS de v2 que le dicen al frontend qué renderer usar:

```json
{
  "tipo": "analisis_v2",
  "id": 91,
  "jornada": 14,
  "momento": null,
  "momento_titulo": null,
  "momento_orden": null,
  "metodo": "openai",
  "enfoque": null,
  "alcance": "jornada",
  "estado": "completo",
  "error_mensaje": "",
  "creado_en": "2026-09-20T15:30:00Z",
  "completado_en": "2026-09-20T15:31:40Z",
  "version": "kunsamu.analisis/v2",
  "modo": "integral",
  "pipeline": "llm",
  "estado_analitico": "completo"
}
```

- `enfoque` siempre viene `null` en los items v2 (el contrato no tiene ese campo).
- `alcance` ∈ `"jornada"` (modo `integral`) \| `"momento"` (`por_momento` de UN momento) \|
  `"momentos"` (`por_momento` de varios) — mismo vocabulario que usan `reporte`/`analisis_jornada`
  en la lista unificada.
- `momento`/`momento_titulo`/`momento_orden` solo se llenan cuando el `AnalisisV2` es
  `por_momento` de EXACTAMENTE un momento; en cualquier otro caso (`integral`, o `por_momento` de
  varios) quedan `null` — mismo criterio que el resto de tipos en esta lista.
- `?momento=<id>` incluye solo los `por_momento` que contienen ese momento en su M2M; un
  `integral` nunca aparece (analíticamente cubre todos los momentos, pero no es "de" ninguno en
  particular) — mismo criterio que `analisis_jornada`.

---

## 5. Leer `resultado`

El JSON completo, sus 17 tipos de visualización y las reglas semánticas de cada uno están
documentados en la entrega original — no se repiten acá:

- Esquema: [`docs/mejora_promps/analisis.schema.json`](mejora_promps/analisis.schema.json).
- Reglas por tipo de visualización (dona exhaustiva, radar con rango, histograma `[desde,
  hasta)`, etc.): [`docs/mejora_promps/TIPOS_VISUALES.md`](mejora_promps/TIPOS_VISUALES.md).
- Qué cambia en el frontend, cómo se elige renderer, formularios de alcance/pipeline/personalización:
  [`docs/mejora_promps/MIGRACION_FRONTEND.md`](mejora_promps/MIGRACION_FRONTEND.md) §4–§7.
- Contrato de la entrada (`entrada` en el detalle) y del adaptador BERTopic:
  [`docs/mejora_promps/ENTRADA_Y_BERTOPIC.md`](mejora_promps/ENTRADA_Y_BERTOPIC.md).

Notas propias de esta implementación de backend (verificadas contra `analitica/v2/`, no contra el
plan):

- **Unidades de porcentaje**: `metricas[].unidad` y `datos.unidad` de las visualizaciones
  categóricas pueden venir como `"porcentaje"` (el que usan los ejemplos congelados) o `"%"` (el
  que usa `TIPOS_VISUALES.md`) — `analitica/v2/validacion.py` acepta ambos como equivalentes; el
  frontend debe tratarlos igual.
- **`alcance` es idéntico a `entrada.solicitud`** (`{modo, jornada_id, momento_ids}`) — se valida
  como invariante en cada análisis publicado (`validacion.py::validar_negocio`).
- Los IDs de jornada/momentos/preguntas/opciones dentro del JSON de `resultado` y de `entrada` son
  los ids numéricos reales del sistema, pero **siempre como string** (`"14"`, no `14"`) — así lo
  fija `analitica/v2/entrada.py`.
- `fuentes[].id` sigue un patrón fijo y verificable en el propio `entrada`: `f-m<momento_id>`
  (respuestas), `f-agg-m<momento_id>` (agregado, solo si el momento tiene preguntas cerradas en su
  inventario), `fbt-p<pregunta_id>` (BERTopic, solo con `pipeline=bertopic_llm` y esa pregunta con
  ≥8 respuestas de texto).
- Las citas (`hallazgos[].citas[].texto`) son **subcadenas literales** de un texto localizado con
  `fuente_id` + `localizador` (JSON Pointer relativo a `entrada.fuentes[].datos`, por ejemplo
  `/respuestas/10/valor`) — validado byte a byte contra `entrada`, nunca contra el texto original
  de la base de datos en el momento de la consulta (que pudo cambiar desde entonces).
- En `pipeline=bertopic_llm`, los ids de tópico dentro de `entrada.bertopic` y de las fuentes tipo
  `bertopic` tienen el formato `run-p<pregunta_id>::<native_id>` (con `urllib.parse.quote`); el
  tópico `-1` son los outliers de HDBSCAN, conservados como tal (nunca renombrados a "otros").
- Con cero preguntas de texto elegibles (o si `pipeline=llm`), `entrada.bertopic` es
  `{"version_adaptador": "1.0", "ejecuciones": []}` — válido y declarado, no un error.

---

## 6. Infografía desde un `AnalisisV2`

`POST /api/admin/infografias/` acepta `analisis_v2: <id>` como una cuarta opción, mutuamente
excluyente con `reporte`/`analisis_momento`/`analisis_jornada` (exactamente uno de los cuatro,
igual regla "HU-73" que describe el §6 de
[INTEGRACION_FRONTEND_ANALISIS_GUIADO.md](INTEGRACION_FRONTEND_ANALISIS_GUIADO.md)):

```json
POST /api/admin/infografias/
{
  "analisis_v2": 91,
  "instrucciones": "Tono institucional, dirigido al equipo organizador."
}
```

- `jornada`/`momento` se derivan solos del `AnalisisV2` fijado (`analisis_v2.jornada`; `momento`
  solo si es `por_momento` de EXACTAMENTE un momento — un `integral` o un `por_momento` de varios
  es "de la jornada", no de un momento puntual) y salen read-only en la respuesta.
- `GET /api/admin/infografias/?analisis_v2=<id>` filtra por esa versión exacta, mismo criterio que
  `?analisis_momento=`/`?analisis_jornada=`.
- El `409` de "ya hay una infografía en curso" y la traducción del contenido
  (`resumen`→`resumen_ejecutivo`, `hallazgos[].afirmacion`(+`implicacion`)→`descripcion`,
  `hallazgos[].metricas`→`datos[{etiqueta,valor,unidad}]`) están aisladas por versión exacta del
  análisis, igual que con los otros tres tipos — dos infografías de dos `AnalisisV2` distintos
  (aunque sean de la misma jornada) nunca se bloquean ni se confunden entre sí.
- Solo aplica a un `AnalisisV2` con `estado="completo"` y `resultado` con `estado` distinto de
  `sin_datos`/`datos_insuficientes` — de lo contrario, `400` con un mensaje explícito (mismo
  criterio que con `reporte`/`analisis_momento`/`analisis_jornada`: no tiene sentido ilustrar un
  análisis que no tiene hallazgos).

---

## 7. Qué NO cambió

Los cuerpos de petición de `reportes/`, `analisis-momento-ia/` y `analisis-jornada-ia/` no
cambiaron (§1) — mismos campos de siempre. Tampoco cambió `analisis-sugerencias/` (que sigue
aceptando `enfoque` opcional; el asistente de sugerencias puede dejar de mandarlo sin que nada
cambie, porque tiene un default). Presentación HTML/PDF, Excel e infografía automática **no
existen** para `AnalisisV2` como modelo propio (salvo el punto §6, que siempre requiere un `POST`
explícito) — fuera de alcance del plan; para un reporte v2 generado vía `reportes/`, la
presentación HTML y el PDF del servidor responden `400` con un mensaje claro en vez de faltar en
silencio (§1).

---

## 8. Checklist de mapeo para el frontend

- [ ] El wizard manda `jornada` + `modo` + `momentos` (solo en `por_momento`) + `pipeline` +
      `contexto`/`instrucciones` (+ `personalizacion_momentos`) a `POST /api/admin/analisis-v2/`;
      ya no manda `enfoque`.
- [ ] El renderer se elige por la presencia del campo `version` en el item (`kunsamu.analisis/v2`
      → renderer común nuevo; sin `version` → visores históricos de `reportes`/`analisis-momento-ia`/`analisis-jornada-ia`).
- [ ] El estado del trabajo (`estado`) y el estado analítico (`estado_analitico` en la lista y en
      la lista unificada, `resultado.estado` en el detalle) se muestran por separado — nunca
      asumir que `estado: "completo"` implica que hay hallazgos.
- [ ] La lista (`GET analisis-v2/` y la unificada) NO trae `resultado`/`entrada`/`diagnostico`; el
      detalle (`GET analisis-v2/{id}/`) sí — pedirlo solo cuando se va a renderizar ese análisis en
      concreto, no en el listado.
- [ ] Al pedir la infografía de un `AnalisisV2` concreto, mandar `analisis_v2: <id>` — no confiar
      en "la jornada"/"el momento" solos.
