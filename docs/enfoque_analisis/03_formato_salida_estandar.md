# 03 — Formato de salida estándar: `aluna.analisis/v1`

> **Este es el documento que se pasa al frontend.** Es un borrador para ajustar en conjunto
> antes de la Fase 2 (ver [01_plan_de_desarrollo.md](01_plan_de_desarrollo.md) §4). Los nombres
> de campo son propuestas; lo que no debería cambiar es la estructura: un **sobre** que pone el
> backend, un **cuerpo** que produce el modelo, y **evidencia discriminada** en cada hallazgo.

Índice: [§1 Principios](#1-principios) · [§2 Estructura](#2-estructura) · [§3 Campos](#3-campos-uno-por-uno) ·
[§4 Invariantes por enfoque](#4-invariantes-por-enfoque) · [§5 Cómo renderizar cada cosa](#5-qué-es-cada-cosa-y-cómo-se-renderiza) ·
[§6 Ejemplos completos](#6-ejemplos-completos) · [§7 Dónde aparece](#7-dónde-aparece-en-la-api) · [§8 Compatibilidad](#8-compatibilidad-con-lo-que-existe)

---

## 1. Principios

1. **Un solo formato para todas las vías.** Análisis integral de momento, de jornada, informe
   de transcripción y reporte local entregan el mismo documento. Lo que cambia es `alcance`
   y el contenido, no la forma.
2. **El frontend nunca adivina por la forma del objeto.** Cada hallazgo dice explícitamente
   qué evidencia trae (`evidencia.tipo`) y el documento dice explícitamente su `enfoque`. Si hay
   que renderizar algo, hay un campo que lo dice.
3. **El backend garantiza los invariantes, no el modelo.** Un documento `cualitativo` **nunca**
   trae gráficas ni `cifras_clave`; si el modelo las produce, el backend las borra antes de
   guardar. El frontend puede construir sobre eso sin defensas extra.
4. **Sobre vs. cuerpo.** El modelo de lenguaje solo produce el cuerpo (`resumen_ejecutivo`,
   `temas`, `hallazgos`, `recomendaciones`). Todo lo que se puede calcular en código
   (`cifras_clave`, `alcance`, `meta`) lo calcula el código — así no hay dos versiones de
   "cuántos participaron".
5. **Ids estables dentro del documento.** Cada hallazgo tiene `id` (`h1`, `h2`, …) y las
   recomendaciones lo referencian, para poder enlazar y resaltar.

---

## 2. Estructura

```
documento
├── esquema              "aluna.analisis/v1"                       ← SOBRE (backend)
├── enfoque              "cuantitativo" | "cualitativo"
├── alcance              { tipo, id, titulo, jornada }
├── cifras_clave         [ {etiqueta, valor, unidad} ]              (vacío en cualitativo)
├── resumen_ejecutivo    string                                     ← CUERPO (modelo)
├── temas                [ string ]
├── hallazgos            [ hallazgo ]
│     ├── id, titulo, descripcion, naturaleza
│     ├── fuentes        { momentos[], preguntas[], sesiones[] }
│     └── evidencia      { tipo, grafica | null, citas[] }
├── recomendaciones      [ {titulo, descripcion, hallazgos[]} ]
└── meta                 { generado_en, modelo, version_prompt, advertencias[] }   ← SOBRE
```

---

## 3. Campos, uno por uno

### 3.1 Sobre

| Campo | Tipo | Siempre | Descripción |
|---|---|---|---|
| `esquema` | `"aluna.analisis/v1"` | sí | Discriminador de versión. Si un día cambia la forma, cambia a `v2` y el FE sabe qué esperar. |
| `enfoque` | `"cuantitativo"` \| `"cualitativo"` | sí | Con qué enfoque **se generó este documento** (no el enfoque actual de la jornada, que pudo cambiar después). |
| `alcance.tipo` | `"jornada"` \| `"momento"` \| `"momentos"` \| `"sesion"` | sí | Sobre qué se hizo el análisis. `momentos` = reporte local de varios momentos combinados. |
| `alcance.id` | int \| int[] | sí | Id del objeto (lista solo en `momentos`). |
| `alcance.titulo` | string | sí | Nombre de la jornada / título del momento / nombre de la sesión. |
| `alcance.jornada` | `{id, slug, nombre}` \| null | sí | La jornada, siempre que exista (una sesión de transcripción puede no tener). |
| `cifras_clave` | `[{etiqueta, valor, unidad}]` | sí (puede ser `[]`) | Números de cabecera calculados por el backend: participantes, respondieron, tasa, momentos, preguntas, sesiones. **`[]` siempre en cualitativo.** `unidad` ∈ `conteo` \| `porcentaje`. |
| `meta.generado_en` | ISO 8601 | sí | |
| `meta.modelo` | string | sí | Siempre la etiqueta genérica `"Generado con IA"` (nunca el nombre real del proveedor). |
| `meta.version_prompt` | string | sí | Fecha o tag del prompt usado, para poder comparar corridas. |
| `meta.advertencias` | string[] | sí (puede ser `[]`) | Cosas que el backend corrigió o notó: `"Se eliminaron 2 gráficas por enfoque cualitativo"`, `"Documento normalizado desde formato anterior"`, `"Tramos con error: [3]"`. |

### 3.2 Cuerpo

| Campo | Tipo | Siempre | Descripción |
|---|---|---|---|
| `resumen_ejecutivo` | string | sí | 4–7 frases, prosa. Sin markdown. |
| `temas` | string[] | sí (puede ser `[]`) | Temas transversales, 3–8 ítems cortos (2–5 palabras). Para pintar como chips. En cuantitativo salen de los hallazgos; en cualitativo de los diálogos. |
| `hallazgos` | hallazgo[] | sí, ≥1 | Ver 3.3. Ordenados por relevancia (el modelo los ordena; el backend no reordena). |
| `recomendaciones` | `[{titulo, descripcion, hallazgos}]` | sí (puede ser `[]`) | 3–5 acciones. `hallazgos` = ids (`["h1","h4"]`) de los que la sustentan; puede ser `[]`. |

### 3.3 Hallazgo

| Campo | Tipo | Siempre | Descripción |
|---|---|---|---|
| `id` | string | sí | `"h1"`, `"h2"`, … en orden. Lo asigna el backend si el modelo no lo trae. |
| `titulo` | string | sí | Corto y natural, no un identificador. |
| `descripcion` | string | sí | 2–5 frases. En cuantitativo con sus cifras exactas; en cualitativo **sin ningún número**. |
| `naturaleza` | `"consenso"` \| `"division"` \| `"tension"` \| `"emergente"` \| `"pendiente"` | sí | Qué clase de patrón es, para una etiqueta de color. `consenso` = acuerdo amplio; `division` = posturas repartidas; `tension` = apoyo declarado vs. objeción o demanda de ajuste; `emergente` = tema que aparece sin que se preguntara; `pendiente` = asunto planteado sin resolución. |
| `fuentes.momentos` | int[] | sí | Ids de momentos que lo sustentan (`[]` si no aplica). |
| `fuentes.preguntas` | int[] | sí | Ids de preguntas. |
| `fuentes.sesiones` | int[] | sí | Ids de sesiones de transcripción. |
| `evidencia.tipo` | `"grafica"` \| `"citas"` \| `"grafica_y_citas"` \| `"ninguna"` | sí | **El discriminador de render.** Lo calcula el backend a partir de lo que hay en `grafica` y `citas`; nunca lo contradice. |
| `evidencia.grafica` | objeto \| null | sí | `null` salvo en cuantitativo con datos. Ver 3.4. |
| `evidencia.citas` | cita[] | sí (puede ser `[]`) | Ver 3.5. |

### 3.4 Gráfica (`evidencia.grafica`)

```json
{
  "tipo": "barras",
  "unidad": "porcentaje",
  "base": 118,
  "series": [
    { "etiqueta": "Muy de acuerdo", "valor": 62.7 },
    { "etiqueta": "De acuerdo",     "valor": 25.4 },
    { "etiqueta": "En desacuerdo",  "valor": 11.9 }
  ]
}
```

| Campo | Valores | Descripción |
|---|---|---|
| `tipo` | `pastel` \| `barras` \| `radar` | Sugerencia del modelo. El FE puede degradar (ej. pastel con >5 series → barras), como hace hoy el PDF. |
| `unidad` | `conteo` \| `porcentaje` | **Una sola por gráfica.** Nunca se mezclan bases (regla que ya existe en los prompts actuales). |
| `base` | int \| null | Sobre cuántas respuestas se calculó (el denominador). `null` si no aplica. Sirve para el pie de la gráfica: "n = 118". |
| `series` | `[{etiqueta, valor}]` | ≥2 ítems. `valor` numérico. |

### 3.5 Cita (`evidencia.citas[]`)

```json
{ "texto": "Lo que falta no es plata, es que alguien nos escuche antes de decidir.", "hablante": "Docente, mesa 3", "fuente": { "tipo": "sesion", "id": 7 } }
```

| Campo | Descripción |
|---|---|
| `texto` | Literal, nunca parafraseada. Sin comillas propias (las pone el FE). |
| `hablante` | string \| null. La etiqueta de quien habla si la transcripción la trae, o el rol/mesa si la respuesta lo permite. `null` si no se sabe. |
| `fuente` | `{tipo: "sesion"|"pregunta", id}` \| null. De dónde salió. |

---

## 4. Invariantes por enfoque

El backend los garantiza en `validar_y_limpiar()` antes de guardar. El frontend puede darlos
por ciertos.

| | `cuantitativo` | `cualitativo` |
|---|---|---|
| `cifras_clave` | Puede traer ítems | **Siempre `[]`** |
| `evidencia.grafica` | Puede ser objeto | **Siempre `null`** |
| `evidencia.tipo` posibles | `grafica`, `citas`, `grafica_y_citas`, `ninguna` | Solo `citas` o `ninguna` |
| Números en `descripcion` / `resumen_ejecutivo` | Sí, exactos | **No** (el backend purga patrones `NN %`, `NN respuestas`) |
| `temas` | Puede ser `[]` | Normalmente ≥3 |
| `evidencia.citas` | Opcional | Cada hallazgo debería traer ≥1 (el prompt lo exige; si el modelo falla, `tipo="ninguna"` y una advertencia en `meta`) |

---

## 5. Qué es cada cosa y cómo se renderiza

Tabla de referencia para el componente único del frontend.

| Bloque | Condición | Render sugerido |
|---|---|---|
| Cabecera | siempre | `alcance.titulo` + etiqueta de `enfoque` ("Percepción general" / "Instrumentos con datos") + `alcance.tipo` |
| Cifras clave | `cifras_clave.length > 0` | Mosaico de 3–5 tarjetas numéricas (valor grande + etiqueta). **No pintar la sección si está vacío** — en cualitativo nunca aparece. |
| Resumen ejecutivo | siempre | Bloque destacado, prosa. |
| Temas | `temas.length > 0` | Fila de chips. |
| Hallazgo | uno por ítem | Tarjeta: `titulo` + badge de `naturaleza` + `descripcion` + zona de evidencia (abajo) + pie con fuentes (`fuentes.*` como enlaces "Momento 3", "Pregunta 12", "Sesión 7"). |
| ↳ Evidencia `grafica` | `evidencia.tipo == "grafica"` | Gráfica según `grafica.tipo`, eje/leyenda en `grafica.unidad`, pie "n = base". |
| ↳ Evidencia `citas` | `evidencia.tipo == "citas"` | Lista de citas en formato de cita (comillas/borde lateral), con `hablante` en cursiva debajo. |
| ↳ Evidencia `grafica_y_citas` | `evidencia.tipo == "grafica_y_citas"` | Gráfica arriba, citas debajo (o dos columnas). |
| ↳ Evidencia `ninguna` | `evidencia.tipo == "ninguna"` | Solo el texto; no dejar espacio vacío. |
| Recomendaciones | `recomendaciones.length > 0` | Lista numerada; cada una con `titulo` en negrita, `descripcion`, y chips de los hallazgos referenciados (`hallazgos` → scroll/resaltado al `id`). |
| Pie | siempre | `meta.modelo` · `meta.generado_en`; `meta.advertencias` como aviso discreto si `length > 0`. |

Badge de `naturaleza` (misma escala de color que ya usa la presentación HTML para
`nivel_acuerdo`): `consenso` verde · `division` azul/teal · `tension` naranja · `emergente`
morado · `pendiente` gris.

---

## 6. Ejemplos completos

### 6.1 Cuantitativo — análisis integral de un momento

```json
{
  "esquema": "aluna.analisis/v1",
  "enfoque": "cuantitativo",
  "alcance": {
    "tipo": "momento", "id": 61, "titulo": "Diagnóstico de articulación académica",
    "jornada": { "id": 4, "slug": "jornada-agil-2026", "nombre": "Jornada Ágil 2026" }
  },
  "cifras_clave": [
    { "etiqueta": "Participantes inscritos", "valor": 140, "unidad": "conteo" },
    { "etiqueta": "Respondieron este momento", "valor": 118, "unidad": "conteo" },
    { "etiqueta": "Tasa de respuesta", "valor": 84.3, "unidad": "porcentaje" },
    { "etiqueta": "Preguntas", "valor": 9, "unidad": "conteo" }
  ],
  "resumen_ejecutivo": "El momento muestra un respaldo amplio a la articulación entre facultades, pero ese apoyo convive con una demanda concreta de acompañamiento operativo que reaparece en tres preguntas distintas. …",
  "temas": ["Articulación entre facultades", "Acompañamiento institucional", "Carga administrativa", "Comunicación interna"],
  "hallazgos": [
    {
      "id": "h1",
      "titulo": "Apoyo declarado, con condiciones",
      "descripcion": "El 88,1 % está de acuerdo o muy de acuerdo con avanzar en la articulación, pero 41 de las 63 respuestas abiertas sobre cambios indispensables piden acompañamiento antes de implementarla. …",
      "naturaleza": "tension",
      "fuentes": { "momentos": [61], "preguntas": [301, 305, 309], "sesiones": [] },
      "evidencia": {
        "tipo": "grafica_y_citas",
        "grafica": {
          "tipo": "barras", "unidad": "conteo", "base": 63,
          "series": [
            { "etiqueta": "Acompañamiento", "valor": 41 },
            { "etiqueta": "Recursos", "valor": 12 },
            { "etiqueta": "Tiempo", "valor": 7 },
            { "etiqueta": "Otros", "valor": 3 }
          ]
        },
        "citas": [
          { "texto": "Sí a la articulación, pero que no nos dejen solos con el papeleo.", "hablante": null, "fuente": { "tipo": "pregunta", "id": 309 } }
        ]
      }
    },
    {
      "id": "h2",
      "titulo": "Consenso sobre el calendario unificado",
      "descripcion": "…",
      "naturaleza": "consenso",
      "fuentes": { "momentos": [61], "preguntas": [302], "sesiones": [] },
      "evidencia": {
        "tipo": "grafica",
        "grafica": { "tipo": "pastel", "unidad": "porcentaje", "base": 118, "series": [ { "etiqueta": "Sí", "valor": 91.5 }, { "etiqueta": "No", "valor": 8.5 } ] },
        "citas": []
      }
    }
  ],
  "recomendaciones": [
    { "titulo": "Diseñar el acompañamiento antes que el cronograma", "descripcion": "…", "hallazgos": ["h1"] },
    { "titulo": "Cerrar el calendario unificado este semestre", "descripcion": "…", "hallazgos": ["h2"] }
  ],
  "meta": { "generado_en": "2026-09-19T15:04:00Z", "modelo": "Generado con IA", "version_prompt": "2026-09-19", "advertencias": [] }
}
```

### 6.2 Cualitativo — análisis integral de una jornada de percepción general

```json
{
  "esquema": "aluna.analisis/v1",
  "enfoque": "cualitativo",
  "alcance": {
    "tipo": "jornada", "id": 9, "titulo": "Conversatorio: la universidad que queremos",
    "jornada": { "id": 9, "slug": "conversatorio-2026", "nombre": "Conversatorio: la universidad que queremos" }
  },
  "cifras_clave": [],
  "resumen_ejecutivo": "A lo largo de las tres intervenciones y la plenaria, la conversación gira alrededor de una misma preocupación: la distancia entre las decisiones institucionales y quienes las viven en el aula. …",
  "temas": ["Distancia entre decisión y aula", "Reconocimiento del trabajo docente", "Bienestar estudiantil", "Regionalización", "Confianza institucional"],
  "hallazgos": [
    {
      "id": "h1",
      "titulo": "Decidir sin quienes lo viven",
      "descripcion": "Tanto en la conferencia inaugural como en la plenaria, los participantes describen procesos que se anuncian ya cerrados. La demanda no es de más recursos sino de ser consultados antes, y aparece con casi las mismas palabras en voces de docentes y de estudiantes.",
      "naturaleza": "consenso",
      "fuentes": { "momentos": [72], "preguntas": [], "sesiones": [7, 8] },
      "evidencia": {
        "tipo": "citas",
        "grafica": null,
        "citas": [
          { "texto": "Lo que falta no es plata, es que alguien nos escuche antes de decidir.", "hablante": "Docente", "fuente": { "tipo": "sesion", "id": 7 } },
          { "texto": "Nos enteramos por el correo masivo, cuando ya estaba firmado.", "hablante": "Estudiante", "fuente": { "tipo": "sesion", "id": 8 } }
        ]
      }
    },
    {
      "id": "h2",
      "titulo": "Regionalización: entusiasmo con reservas",
      "descripcion": "…",
      "naturaleza": "tension",
      "fuentes": { "momentos": [], "preguntas": [], "sesiones": [8] },
      "evidencia": { "tipo": "citas", "grafica": null, "citas": [ { "texto": "…", "hablante": null, "fuente": { "tipo": "sesion", "id": 8 } } ] }
    }
  ],
  "recomendaciones": [
    { "titulo": "Instalar una consulta previa breve antes de cada decisión académica", "descripcion": "…", "hallazgos": ["h1"] }
  ],
  "meta": { "generado_en": "2026-09-19T16:20:00Z", "modelo": "Generado con IA", "version_prompt": "2026-09-19", "advertencias": [] }
}
```

### 6.3 Cualitativo — informe de una sesión de transcripción

Idéntico a 6.2 con `alcance.tipo = "sesion"`, `alcance.jornada` posiblemente `null`,
`fuentes.sesiones = [id]` en todos los hallazgos, y `meta.advertencias` con
`"Tramos con error: [3]"` cuando aplique.

---

## 7. Dónde aparece en la API

| Endpoint | Campo | Notas |
|---|---|---|
| `GET /api/admin/analisis-momento-ia/{id}/` | `resultado` | v1 con `alcance.tipo="momento"` |
| `GET /api/admin/analisis-jornada-ia/{id}/` | `resultado` | v1 con `alcance.tipo="jornada"` |
| `GET /api/admin/informes-transcripcion/{id}/` | `resultado` | v1 con `alcance.tipo="sesion"`, siempre `cualitativo` |
| `GET /api/admin/reportes/{id}/` | `analisis_estandar` (nuevo) | v1 derivado del pipeline local. `analisis` (forma jerárquica) sigue existiendo por ahora. |
| `GET /api/admin/infografias/{id}/` | `prompt_usado` | Contiene el v1 recortado que se le dio al modelo de imagen (solo trazabilidad). |
| `POST` de cualquiera de los anteriores | `enfoque` (opcional) | Override por corrida; si no viene, hereda `jornada.enfoque_analisis`. |
| `POST/PATCH /api/admin/jornadas/` | `enfoque_analisis` | `"cuantitativo"` (default) \| `"cualitativo"`. |

Todas las respuestas incluyen además `enfoque` a nivel del objeto (igual al del sobre) para
poder filtrar listados sin abrir el JSON.

---

## 8. Compatibilidad con lo que existe

- Los análisis **ya guardados** con la forma anterior (`tipo_grafica` + `datos`, o `citas`
  directas) se sirven **ya convertidos** a v1 por el backend. El frontend no ve la forma vieja
  en ningún endpoint a partir de la Fase 2. Se marcan con
  `meta.advertencias: ["Documento normalizado desde formato anterior"]`.
- Mapeo de la forma vieja → v1 (para quien tenga que revisar la conversión):

| Vieja (momento/jornada) | v1 |
|---|---|
| `hallazgos[].tipo_grafica` + `datos[]` | `evidencia.grafica = {tipo, unidad: datos[0].unidad, series: datos → {etiqueta, valor}}`; `null` si `tipo_grafica` es `null` o `datos` vacío |
| `hallazgos[].preguntas_relacionadas` | `fuentes.preguntas` |
| `hallazgos[].momentos_relacionados` | `fuentes.momentos` (`[momento_id]` en análisis de momento) |
| `hallazgos[].transcripciones_relacionadas` | `fuentes.sesiones` |
| — | `naturaleza = "pendiente"` (no se puede inferir; se marca en advertencias) |
| — | `temas = []`, `recomendaciones = []` |

| Vieja (transcripción) | v1 |
|---|---|
| `temas_discutidos` | `temas` |
| `hallazgos[].citas[]` (strings) | `evidencia.citas[] = {texto, hablante: null, fuente: {tipo:"sesion", id}}` |
| `tramos_con_error` | `meta.advertencias` |

- `Reporte.analisis` (pipeline local) → `analisis_estandar`: cada pregunta se convierte en un
  hallazgo (`fuentes.preguntas=[id]`, `titulo` = texto de la pregunta, `descripcion` = su
  descripción, `evidencia.grafica` desde `valores_caracteristicos` cuando `metodo_valores ∈
  {conteo, bertopic_llm}`, `naturaleza` desde `nivel_acuerdo` cuando exista); `descripcion_general`
  de cada momento va al `resumen_ejecutivo` concatenado con `texto_reporte`.
