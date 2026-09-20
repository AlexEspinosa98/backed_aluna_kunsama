# Integración frontend — Análisis v2 (contrato `kunsamu.analisis/v2`)

Implementa la entrega `docs/mejora_promps/` (20-sep-2026), plan de ejecución en
[`docs/mejora_promps/plan_implementacion/`](mejora_promps/plan_implementacion/README.md). Lo que
el frontend recibe en `resultado` es EXACTAMENTE el JSON de
[`analisis.schema.json`](mejora_promps/analisis.schema.json), ya validado (esquema + reglas de
negocio) — nunca llega un resultado inválido: si la IA no logra producir uno válido tras un
reintento de reparación, el trabajo termina en `estado: "error"` con `resultado: {}`, nunca con un
JSON a medias. Los tres análisis legacy (`reportes/`, `analisis-momento-ia/`,
`analisis-jornada-ia/`, ver [INTEGRACION_FRONTEND_ANALISIS_GUIADO.md](INTEGRACION_FRONTEND_ANALISIS_GUIADO.md))
siguen funcionando exactamente igual para el histórico; el frontend elige renderer por la
presencia (o no) del campo `version` en el item.

Sin `enfoque`: el contrato v2 lo elimina. El modelo decide, pregunta por pregunta, el método más
adecuado y lo declara en `naturaleza`/`metodos` de cada hallazgo — la personalización del usuario
viaja como `contexto`/`instrucciones` (generales y por momento), nunca como una instrucción de
formato.

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

## 1. Pedir un análisis — `POST /api/admin/analisis-v2/`

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
| `pipeline` | `"llm"` \| `"bertopic_llm"` | `"llm"` | `bertopic_llm` agrega, antes de llamar a la IA, una ejecución de BERTopic por cada pregunta de texto (`abierta`/`audio`) con 8 o más respuestas no vacías (ver §4). |
| `contexto` | string, ≤4000 caracteres | `""` | Contexto general de quien pide el análisis. Viaja como dato en `entrada.personalizacion.contexto_usuario` — nunca se anexa al system prompt. |
| `instrucciones` | string, ≤4000 caracteres | `""` | Ídem, en `entrada.personalizacion.instrucciones_usuario`. Ajusta énfasis y tono; el formato del informe (el esquema) es fijo por contrato, no lo cambian las instrucciones. |
| `personalizacion_momentos` | array de `{"momento": <id>, "contexto": "", "instrucciones": ""}` | `[]` | Opcional. Cada `momento` debe estar en el alcance de este análisis (todos los de la jornada en `integral`, los indicados en `por_momento`) y aparecer como máximo una vez. |

Respuesta `201` con el análisis recién creado en `estado: "pendiente"` (serializer de detalle,
`AnalisisV2Serializer` — ver §2; `resultado`/`entrada`/`diagnostico` llegan vacíos porque el
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
del contrato (ver §4) — el backend lo produce sin llamar a la IA y el frontend lo renderiza como
un estado vacío, igual que cualquier otro `resultado.estado`.

Antes de evaluar el `409`, la vista sanea automáticamente cualquier `AnalisisV2` de esa jornada
que lleve más de 45 minutos `pendiente`/`procesando` (lo marca `error` con un mensaje explícito:
probablemente el worker se reinició o falló) — ese umbral es más alto que el de los análisis
legacy (10 min) porque una llamada v2 es una sola pero grande, y en `bertopic_llm` va precedida de
clustering por pregunta.

---

## 2. Consultar

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
| `resultado` | El JSON `kunsamu.analisis/v2` validado (ver §4). `{}` mientras `estado` no es `completo`. |
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

## 3. Lista unificada — `GET /api/admin/analisis/`

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

## 4. Leer `resultado`

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

## 5. Infografía desde un `AnalisisV2`

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

## 6. Qué NO cambió

Los tres endpoints legacy (`reportes/`, `analisis-momento-ia/`, `analisis-jornada-ia/`), sus
formatos de request/response y `analisis-sugerencias/` (que sigue aceptando `enfoque` opcional; el
asistente de sugerencias puede dejar de mandarlo sin que nada cambie, porque tiene un default).
Presentación HTML/PDF, Excel e infografía automática **no existen** para `AnalisisV2` (salvo el
punto §5, que siempre requiere un `POST` explícito) — fuera de alcance del plan.

---

## 7. Checklist de mapeo para el frontend

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
