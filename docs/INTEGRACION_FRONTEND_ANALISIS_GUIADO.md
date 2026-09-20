# Integración frontend — Análisis guiado (método, enfoque, contexto, instrucciones)

Guía de los endpoints y esquemas de HU-71 y HU-72 (brief original del frontend en
[HU_BACKEND_ANALISIS_GUIADO.md](HU_BACKEND_ANALISIS_GUIADO.md), HU-57 de ese repo). Cubre: los
campos nuevos de las tres vías de análisis, el formato exacto de lo que devuelve cada una, las
sugerencias del asistente, la lista unificada y cómo la infografía fija el análisis exacto del
que sale.

Para carga de assets/system design y el detalle de las 3 láminas de infografía, ver
[INTEGRACION_FRONTEND_INFOGRAFIA.md](INTEGRACION_FRONTEND_INFOGRAFIA.md) y
[INTEGRACION_FRONTEND_ASSETS_INFOGRAFIA.md](INTEGRACION_FRONTEND_ASSETS_INFOGRAFIA.md) — esta
guía no repite eso, solo lo que cambió con el análisis guiado.

---

## 0. URL base — esto vive en `develop`, no en producción todavía

Todo lo de este documento está en la rama `develop`, desplegado para pruebas en:

```
Base URL (desarrollo):  https://kunsamu.josec.ddns.net
```

**Sin el prefijo `/api/aluna-kunsama/`** que sí tiene producción — este servidor de pruebas no
está detrás de ese nginx, así que las rutas van directas:

```
https://kunsamu.josec.ddns.net/api/admin/reportes/
https://kunsamu.josec.ddns.net/api/admin/analisis-momento-ia/
```

`GET /` (sin `/api`) es un healthcheck público sin autenticación — sirve para confirmar que el
servidor y la base de datos responden antes de perder tiempo debuggeando otra cosa:

```json
{"status": "ok", "database": "ok", "hora_servidor": "2026-09-20T14:41:59.023346+00:00"}
```

Autenticación: `Authorization: Token <hex de 40 chars>`, igual que el resto del panel. Cuando
esto se mergee a `main`, las mismas rutas aplican en producción bajo el prefijo de siempre
(`https://back.alunaia.co/api/aluna-kunsama/api/admin/...`, ver la nota de doble `/api/` en
INTEGRACION_FRONTEND_INFOGRAFIA.md).

---

## 1. Los tres métodos y sus endpoints

| Método | Alcance | Endpoint | Modelo |
|---|---|---|---|
| `bertopic` (pipeline local) | jornada o momento(s) | `POST /api/admin/reportes/` | `Reporte` |
| `openai` (lectura integral) | un momento | `POST /api/admin/analisis-momento-ia/` | `AnalisisMomentoIA` |
| `openai` (lectura integral) | jornada completa | `POST /api/admin/analisis-jornada-ia/` | `AnalisisJornadaIA` |

`metodo` viene en la respuesta de los tres (`"bertopic"` o `"openai"`) — es una constante por
modelo, no hace falta deducirla del endpoint.

Una jornada o un momento acumulan **varios** análisis a la vez, de cualquier combinación de
método/enfoque — no hay un límite de "uno vigente". Por eso la lista unificada (§4) existe y por
eso la infografía necesita poder fijar cuál usar (§5).

**El análisis de jornada completa (`bertopic` y `openai`) incluye TODOS los momentos, estén o no
`activo`.** `Momento.activo` es solo una bandera de visibilidad para participantes (si todavía
pueden responder ese momento) — no dice nada sobre si tiene respuestas reales que valga la pena
analizar. Corregido el 2026-09-20: antes, la vía `openai` (y sus sugerencias, §5) excluía
silenciosamente cualquier momento desactivado, aunque tuviera respuestas reales — un momento que
se desactiva después de cerrar la jornada sigue siendo parte real de lo que se vivió. Si el
panel en algún punto filtraba u ocultaba momentos inactivos pensando que "no cuentan" para el
análisis, hay que quitar ese supuesto.

---

## 2. Campos del análisis guiado

Los mismos tres/cinco campos, agregados a las tres solicitudes. Se **guardan tal cual** (sin
normalizar) y se devuelven en el `GET` — sirven para mostrar en el detalle "con qué se generó" y
como punto de partida si se vuelve a lanzar.

| Campo | Tipo | Default | En cuáles | Notas |
|---|---|---|---|---|
| `enfoque` | `"cualitativo"` \| `"cuantitativo"` \| `"mixto"` | `"mixto"` | los 3 | Valor inválido → `400` con la clave `enfoque`. |
| `contexto` | string, ≤4000 caracteres | `""` | los 3 | Contexto general (puede precargarse con `Jornada.descripcion`). |
| `instrucciones` | string, ≤4000 caracteres | `""` | los 3 | Tono, público, cantidad de gráficos, idioma… manda sobre el estilo por defecto. |
| `contexto_momento` | string, ≤4000 caracteres | `""` | `reportes` y `analisis-momento-ia` | Solo aplica con alcance de un único momento. |
| `instrucciones_momento` | string, ≤4000 caracteres | `""` | `reportes` y `analisis-momento-ia` | Ídem. |

`AnalisisJornadaIA` **no** tiene los dos `_momento` — su alcance es siempre la jornada entera.

### Qué hace cada valor de `enfoque` (aplica a los tres métodos)

| Valor | En el texto | En las gráficas |
|---|---|---|
| `cualitativo` | Prioriza sentido, matices, voces representativas; cifras solo si aportan | **Nunca hay gráfica.** `tipo_grafica` siempre `null`, `datos` siempre `[]` — garantizado en código, no solo en el prompt (era un bug real, corregido: ver el registro de cambios al final). |
| `cuantitativo` | Prioriza frecuencias, porcentajes, comparaciones | Gráfica en casi todos los hallazgos |
| `mixto` (default) | Cifra exacta + explicación, mismo peso | Gráfica en casi todos los hallazgos — comportamiento de siempre |

### Ejemplo — análisis de un momento con IA

```json
POST /api/admin/analisis-momento-ia/
{
  "momento": 61,
  "enfoque": "cualitativo",
  "contexto": "Diálogo de mesas sobre el rol de las mujeres en el cuidado del mar.",
  "instrucciones": "Tono cercano, cita al menos una frase textual por hallazgo.",
  "contexto_momento": "Este momento se trabajó en mesas de ocho personas.",
  "instrucciones_momento": "Destaca las tensiones entre generaciones."
}
```

### Ejemplo — reporte del pipeline local, por momento

```json
POST /api/admin/reportes/
{
  "jornada": 14,
  "momentos": [61],
  "plantilla": null,
  "enfoque": "cuantitativo",
  "contexto": "…",
  "instrucciones": "…"
}
```

`momentos: []` = jornada completa. `momentos: [<id>]` = un solo momento (alcance `momento`, ahí
sí aplican `contexto_momento`/`instrucciones_momento`). Varios ids = alcance `momentos`
(combinados) — en ese caso los campos `_momento` se guardan pero no tienen un único momento al
que aplicarse dentro del prompt.

---

## 3. Qué devuelve cada `GET` (lista y detalle)

### 3.1 `Reporte` — `GET /api/admin/reportes/` y `/{id}/`

```json
{
  "id": 32,
  "slug": "jornada-agil-2-momento-20260920-1530",
  "jornada": "jornada-agil-2",
  "momentos": [ {"id": 61, "titulo": "Diagnóstico", "slug": "diagnostico", "orden": 2} ],
  "alcance": "momento",
  "metodo": "bertopic",
  "plantilla": 3,
  "plantilla_nombre": "Reporte institucional",
  "enfoque": "mixto",
  "contexto": "",
  "instrucciones": "",
  "contexto_momento": "",
  "instrucciones_momento": "",
  "estado": "completo",
  "error_mensaje": "",
  "analisis": { "...": "ver §3.4, formato jerárquico del pipeline local" },
  "texto_reporte": "La jornada muestra un respaldo amplio a…",
  "modelo_usado": "qwen2.5-3b-instruct-q4_k_m.gguf",
  "prompt_usado": "Eres un analista de datos que redacta el reporte…",
  "presentacion_html": "",
  "presentacion_estado": "pendiente",
  "presentacion_error": "",
  "presentacion_modelo": "",
  "presentacion_generada_en": null,
  "solicitado_por": 4,
  "creado_en": "2026-09-20T15:30:00Z",
  "actualizado_en": "2026-09-20T15:31:12Z",
  "completado_en": "2026-09-20T15:31:12Z"
}
```

`prompt_usado` guarda el prompt de la **síntesis de jornada** (el de más alto nivel) — un reporte
real tiene decenas de otros prompts, uno por pregunta y por momento; guardar todos sería
excesivo, así que se conserva el más representativo.

### 3.2 `AnalisisMomentoIA` — `GET /api/admin/analisis-momento-ia/` y `/{id}/`

```json
{
  "id": 8,
  "momento": 61,
  "momento_titulo": "Diagnóstico de articulación académica",
  "momento_orden": 2,
  "metodo": "openai",
  "estado": "completo",
  "resultado": { "...": "ver §3.5, formato del hallazgo con IA" },
  "error_mensaje": "",
  "modelo_usado": "Generado con IA",
  "prompt_usado": "Eres un analista senior leyendo TODO el instrumento…",
  "enfoque": "cualitativo",
  "contexto": "…",
  "instrucciones": "…",
  "contexto_momento": "…",
  "instrucciones_momento": "…",
  "solicitado_por": 4,
  "creado_en": "2026-09-20T14:07:00Z",
  "actualizado_en": "2026-09-20T14:07:48Z",
  "completado_en": "2026-09-20T14:07:48Z"
}
```

`modelo_usado` es siempre la etiqueta genérica `"Generado con IA"` — el proveedor/modelo real de
OpenAI nunca se expone.

### 3.3 `AnalisisJornadaIA` — `GET /api/admin/analisis-jornada-ia/` y `/{id}/`

Igual forma que `AnalisisMomentoIA`, sin `momento`/`momento_titulo`/`momento_orden` ni los campos
`_momento`:

```json
{
  "id": 4,
  "jornada": "jornada-agil-2",
  "metodo": "openai",
  "estado": "completo",
  "resultado": { "...": "ver §3.5" },
  "error_mensaje": "",
  "modelo_usado": "Generado con IA",
  "prompt_usado": "Eres un analista senior leyendo TODA una jornada…",
  "enfoque": "cualitativo",
  "contexto": "…",
  "instrucciones": "",
  "solicitado_por": 4,
  "creado_en": "2026-09-20T14:07:00Z",
  "actualizado_en": "2026-09-20T14:07:48Z",
  "completado_en": "2026-09-20T14:07:48Z"
}
```

### 3.4 `Reporte.analisis` — formato jerárquico del pipeline local

No cambió con esta HU (es el formato de siempre del pipeline BERTopic + LLM local), documentado
acá porque `ReporteSerializer` lo expone tal cual:

```json
{
  "participacion": {
    "total_participantes": 140,
    "participantes_que_respondieron": 118,
    "tasa_participacion": 84.3
  },
  "momentos": [
    {
      "momento_id": 61,
      "tipo": "individual",
      "descripcion_general": "El momento muestra…",
      "preguntas": [
        {
          "pregunta_id": 301,
          "texto": "¿Qué tan de acuerdo estás con…?",
          "tipo": "unica",
          "tipo_grafica": "pastel",
          "nivel_acuerdo": null,
          "total_respuestas": 118,
          "descripcion": "El 88,1% está de acuerdo…",
          "valores_caracteristicos": [
            {"opcion_id": 12, "texto": "De acuerdo", "conteo": 104}
          ],
          "metodo_valores": "conteo"
        },
        {
          "pregunta_id": 305,
          "texto": "¿Qué cambios son indispensables?",
          "tipo": "abierta",
          "tipo_grafica": "radar",
          "nivel_acuerdo": "consenso_moderado",
          "total_respuestas": 63,
          "descripcion": "El tema dominante es…",
          "valores_caracteristicos": [
            {"tema": "Acompañamiento institucional", "tamano": 41, "porcentaje": 65.1}
          ],
          "metodo_valores": "bertopic_llm"
        }
      ]
    }
  ]
}
```

`metodo_valores` ∈ `conteo` (opción cerrada) \| `bertopic_llm` (clasificado con conteo real) \|
`llm` (muestra chica, frases sin conteo) \| `bertopic_sin_clasificar` (clasificación falló,
quedan palabras clave crudas) \| `sin_datos` \| `insuficiente`. Solo `conteo` y `bertopic_llm`
traen un `tamano`/`conteo` real graficable; los demás traen `tamano: null`.

`nivel_acuerdo` ∈ `consenso_fuerte` \| `consenso_moderado` \| `tension_estrategica` \|
`tema_emergente` \| `asunto_pendiente` \| `null` — solo se calcula en preguntas abiertas de
momentos `tipo="mesa"` con suficiente muestra clasificada.

**En `enfoque=cualitativo`, `tipo_grafica` sale `null` en todas las preguntas** (forzado en
código, mismo criterio que en `resultado` — ver §3.5).

### 3.5 `resultado` — formato del análisis con IA (momento y jornada)

Mismo formato para las dos vías, con una diferencia en las llaves de "a qué pregunta/momento se
refiere" (`AnalisisMomentoIA` no cruza momentos, así que no tiene `momentos_relacionados` ni
`transcripciones_relacionadas`):

```json
// AnalisisMomentoIA.resultado
{
  "momento_id": 61,
  "tipo": "individual",
  "resumen_ejecutivo": "El momento muestra un respaldo amplio a…",
  "hallazgos": [
    {
      "titulo": "Apoyo declarado, con condiciones",
      "descripcion": "El 88,1% está de acuerdo…",
      "preguntas_relacionadas": [301, 305, 309],
      "tipo_grafica": "barras",
      "datos": [
        {"etiqueta": "Acompañamiento", "valor": 41, "unidad": "conteo"},
        {"etiqueta": "Recursos", "valor": 12, "unidad": "conteo"}
      ]
    }
  ]
}
```

```json
// AnalisisJornadaIA.resultado
{
  "jornada_id": 14,
  "resumen_ejecutivo": "A lo largo de los momentos…",
  "hallazgos": [
    {
      "titulo": "Demanda transversal de acompañamiento",
      "descripcion": "…",
      "momentos_relacionados": [61, 65],
      "preguntas_relacionadas": [305, 412],
      "transcripciones_relacionadas": [7],
      "tipo_grafica": null,
      "datos": []
    }
  ]
}
```

Reglas de `hallazgos[]`:

- `tipo_grafica` ∈ `"pastel"` \| `"barras"` \| `"radar"` \| `null`.
- `datos[].unidad` ∈ `"conteo"` \| `"porcentaje"` — **una sola por hallazgo**, nunca mezcladas
  (dos bases de medición distintas en el mismo gráfico serían engañosas).
- **En `enfoque=cualitativo`, `tipo_grafica` es SIEMPRE `null` y `datos` SIEMPRE `[]`, en todos
  los hallazgos, sin excepción** — forzado en código (`_validar_y_limpiar`/
  `_validar_y_limpiar_jornada`), no solo pedido por prompt: el 20-sep-2026 un análisis
  cualitativo real salió con gráficas en los 6 hallazgos porque el prompt base tenía una
  instrucción incondicional que le ganaba al párrafo de enfoque — desde el fix, el código lo
  garantiza sin depender de que el modelo obedezca. El frontend puede confiar en esta invariante
  para decidir si pinta la sección de gráfica o no, sin tener que inspeccionar `enfoque` aparte.

---

## 4. Lista unificada — `GET /api/admin/analisis/`

Une `Reporte` + `AnalisisMomentoIA` + `AnalisisJornadaIA` en una sola consulta, para pintar la
pestaña Analítica sin tres llamadas repetidas cada pocos segundos mientras algo procesa.

```
GET /api/admin/analisis/?jornada=<id>
GET /api/admin/analisis/?momento=<id>
```

Manda exactamente uno de los dos — sin ninguno es `400`. Solo lectura: abrir, borrar y el detalle
siguen en los endpoints propios de cada tipo (§3). Sin paginación. Orden: `creado_en`
descendente.

Cada item:

```json
{
  "tipo": "analisis_momento",
  "id": 8,
  "jornada": 14,
  "momento": 61,
  "momento_titulo": "Diálogos mesas",
  "momento_orden": 2,
  "metodo": "openai",
  "enfoque": "cualitativo",
  "alcance": "momento",
  "estado": "procesando",
  "error_mensaje": "",
  "creado_en": "2026-09-20T15:20:00Z",
  "completado_en": null
}
```

| Campo | Valores |
|---|---|
| `tipo` | `"reporte"` \| `"analisis_momento"` \| `"analisis_jornada"` |
| `alcance` | `"jornada"` \| `"momento"` \| `"momentos"` (solo `reporte`, varios momentos combinados) |
| `momento`, `momento_titulo`, `momento_orden` | `null` cuando el alcance no es un único momento — incluye un `reporte` de jornada completa o de varios momentos combinados, no solo `analisis_jornada`. |

`?momento=<id>` **excluye** cualquier `analisis_jornada` (una jornada completa nunca es "de" un
momento puntual) y cualquier `reporte` que no tenga ESE momento en su M2M (uno de jornada
completa no aparece aunque exista).

---

## 5. Sugerencias del asistente — `POST /api/admin/analisis-sugerencias/`

Para el paso de resumen: sugiere cómo enmarcar el análisis (nunca qué dicen los datos — no recibe
respuestas de participantes, solo metadatos).

```json
POST /api/admin/analisis-sugerencias/
{
  "jornada": 14,
  "momentos": [61, 62],
  "metodo": "openai",
  "enfoque": "mixto",
  "contexto": "…",
  "instrucciones": "…"
}
```

`momentos` vacío o ausente = alcance de toda la jornada. `metodo` ∈ `"bertopic"` \| `"openai"`
(requerido). `enfoque`/`contexto`/`instrucciones` opcionales, mismos defaults que en §2.

Respuesta, **siempre `200`**:

```json
{
  "sugerencias": [
    { "tipo": "contexto", "texto": "Las mesas mezclaron docentes de pregrado y posgrado." },
    { "tipo": "instruccion", "texto": "Compara las respuestas de directivos con las de docentes." }
  ]
}
```

- Entre 0 y 6 ítems. `tipo` ∈ `"contexto"` \| `"instruccion"`.
- **Nunca es un error para el frontend**: sin `OPENAI_API_KEY`, si el proveedor tarda más de 8s,
  o si la respuesta no se puede interpretar, `sugerencias` llega vacía — nunca hay que manejar un
  `5xx` de este endpoint por timeouts del modelo. Si llega vacía, simplemente no se muestra la
  sección (igual que si el endpoint no existiera, comportamiento que ya esperaba el frontend
  según el brief original).
- Errores reales: `400` (jornada/momentos inválidos, `metodo`/`enfoque` fuera de choices), `403`
  (jornada ajena, mismo scoping por dependencia que el resto del panel).

---

## 6. Infografías — aisladas a una versión exacta de análisis (HU-73)

> ⚠️ **CAMBIO DISRUPTIVO, acción requerida ya.** `POST /api/admin/infografias/` con solo
> `{"jornada": <id>}` o `{"momento": <id>}` **dejó de funcionar** — ahora responde `400`. Si el
> panel todavía manda eso, hay que actualizarlo antes de que alguien vuelva a pedir una
> infografía en `develop`.

### Qué cambió y por qué

Con HU-71 una jornada o un momento acumulan **varias versiones** de análisis a la vez (distintos
métodos, distintos enfoques). Con el contrato de HU-72, fijar de cuál salían los datos
(`reporte`/`analisis_momento`/`analisis_jornada`) era **opcional**: sin ninguno, el backend caía
al análisis **más reciente** completo de ese alcance.

Eso resultó ser el hueco exacto que produce justamente lo que las infografías no pueden hacer:
que dos versiones terminen compartiendo infografía, o que una generada mirando la versión A
muestre datos de la versión B que se volvió "la más reciente" mientras tanto. Desde HU-73, **cada
infografía queda atada para siempre a la versión exacta de análisis con la que se generó, y
nunca se comparte entre versiones distintas** — ni siquiera del mismo alcance.

### El contrato nuevo

Manda **EXACTAMENTE UNO** de estos tres — ya no hay opción de mandar `jornada`/`momento` solos:

| Campo | Qué fija |
|---|---|
| `reporte` | Un `Reporte` (pipeline local) concreto. |
| `analisis_momento` | Un `AnalisisMomentoIA` concreto. |
| `analisis_jornada` | Un `AnalisisJornadaIA` concreto. |

`jornada` y `momento` **ya no se aceptan como entrada** — se derivan solos de la versión que
fijaste (`analisis_momento.momento`, `analisis_jornada.jornada`, `reporte.jornada`) y salen
read-only en la respuesta. Si los mandas igual en el cuerpo, se ignoran silenciosamente (no da
error, pero tampoco hacen nada — no confíes en que "eligen" el alcance).

```json
POST /api/admin/infografias/
{
  "analisis_momento": 8,
  "instrucciones": "Tono informal, dirigido a estudiantes."
}
```

```json
POST /api/admin/infografias/
{
  "analisis_jornada": 4
}
```

Esto es exactamente lo que ya tenías disponible desde la lista unificada (§4: cada item trae
`tipo` + `id`) — el mapeo es directo:

| `tipo` en `GET /api/admin/analisis/` | Campo a mandar en `POST /api/admin/infografias/` |
|---|---|
| `"reporte"` | `reporte: <id>` |
| `"analisis_momento"` | `analisis_momento: <id>` |
| `"analisis_jornada"` | `analisis_jornada: <id>` |

### Errores

| Situación | Código |
|---|---|
| Ninguno de los tres | `400` — `"Manda EXACTAMENTE uno de..."` |
| Dos o tres al mismo tiempo | `400` — mismo mensaje |
| El análisis fijado no existe, no está completo, o no tiene resultado | `400`, mensaje explícito (igual que antes) |
| Ya hay una infografía **de esa misma versión** en curso | `409` |
| Jornada ajena (derivada de la versión fijada) | `403` |

**Aislamiento también en el "ya hay una en curso":** el bloqueo de `409` ahora es por versión
exacta, no por jornada/momento en general — pedir la infografía de la versión B mientras la
versión A todavía está procesando ya **no** da `409`, son trabajos independientes.

### Al listar/filtrar

`GET /api/admin/infografias/` ahora también filtra por `?analisis_momento=<id>` y
`?analisis_jornada=<id>`, además de `?jornada=`, `?momento=` y `?reporte=` que ya existían. Para
mostrar "las infografías de ESTA versión" en el detalle de un análisis, filtra siempre por el id
exacto (`?analisis_momento=8`, no `?momento=61`) — filtrar por jornada/momento sigue trayendo las
de TODAS las versiones de ese alcance, útil para una vista de administración general, pero no es
lo que hay que usar para "las de este análisis puntual".

La respuesta de cada `InfografiaJornada` incluye `analisis_momento`/`analisis_jornada` (ids,
`null` si no aplica a esa versión) junto a los campos de siempre (`reporte`, `instrucciones`,
`prompt_usado`, `imagenes`, etc. — ver INTEGRACION_FRONTEND_INFOGRAFIA.md).

**Recordatorio explícito, porque se preguntó:** nada de esto genera infografías automáticamente.
Ni terminar un análisis, ni fijar la versión, dispara nada por sí solo — la infografía siempre
requiere un `POST` explícito a este endpoint.

---

## 7. Checklist de mapeo para el frontend

- [ ] Los 5 campos del análisis guiado (§2) en el formulario/asistente de las tres solicitudes.
- [ ] Leer `metodo` de la respuesta en vez de inferirlo del endpoint.
- [ ] El componente de hallazgo decide su render por `evidencia`/`tipo_grafica` presente o no —
      nunca asumir que hay gráfica solo porque el método es `openai`/`bertopic`; en `cualitativo`
      nunca la hay (§3.5).
- [ ] Migrar la lista de Analítica a `GET /api/admin/analisis/` (§4) en vez de las tres consultas
      sueltas, si todavía no se hizo.
- [ ] El paso de sugerencias (§5) nunca bloquea ni muestra error — una lista vacía es una
      respuesta válida.
- [ ] Al pedir una infografía desde el detalle de un análisis concreto, mandar
      `analisis_momento`/`analisis_jornada` (§6) — no confiar en que "la jornada"/"el momento"
      solos basten para identificar cuál.
