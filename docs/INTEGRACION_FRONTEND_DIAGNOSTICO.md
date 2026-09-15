# Integración frontend — Diagnóstico de Articulación Académica

Guía para el equipo de frontend: cómo mostrar el instrumento de diagnóstico dentro de una jornada
y cómo integrar la nueva función de "subir documento ya diligenciado" (Word o PDF) que lo
transcribe con IA.

## 1. Contexto — por qué hay 351 preguntas "sueltas"

El documento original tiene varias tablas tipo matriz (ej. "Matriz de responsabilidades": 12
filas × 4 columnas). El modelo `Pregunta` que ya usa el resto de las jornadas (Jornada Ágil 2, Tu
Voz Nuestra Política, etc.) **no tiene un tipo "matriz"** — solo `abierta` / `unica` / `multiple`,
sin filas × columnas. Para que el diagnóstico apareciera en la misma pantalla de jornada sin tocar
el backend de tipos de pregunta, cada celda de cada matriz quedó convertida en **una pregunta
suelta** (tipo `abierta`), con su texto combinando fila y columna.

Resultado actual: **1 Momento** ("Instrumento de Diagnóstico para la Articulación Académica") con
**351 preguntas**, en la jornada `diagnostico-articulacion-academica`.

```
GET /api/admin/momentos/?jornada=<id_jornada>
GET /api/admin/preguntas/?momento=<id_momento>
```

## 2. Cómo agrupar visualmente sin tocar el backend (recomendado)

El `texto` de cada pregunta generada a partir de una matriz sigue un patrón consistente y
parseable, pensado para que el frontend pueda reconstruir la tabla sin ningún cambio de API:

- Celda simple: `"<fila> — <columna>"` — ej. `"Microdiseños — ¿Quién lo hace hoy?"`
- Celda con contexto adicional (cuando una sección tiene varias matrices, ej. los 3 componentes
  del análisis de coherencia): `"<contexto> · <fila> — <columna>"` — ej.
  `"Componente 1 · Nombre — Programa/modalidad A"`

Heurística sugerida para el frontend:
1. Separar por `" — "`. Si hay match, la parte izquierda es la **fila** (y si contiene `" · "`,
   lo que está antes de eso es un contexto/grupo mayor — ej. "Componente 1"), la derecha es la
   **columna**.
2. Agrupar preguntas consecutivas que comparten el mismo prefijo de fila (o de contexto) en un
   bloque/tabla visual — como ya vienen consecutivas en `orden`, agrupar por prefijo igual entre
   preguntas contiguas es suficiente, no hace falta ninguna llamada extra a la API.
3. Preguntas sin `" — "` en el texto (datos generales, síntesis ejecutiva, etc.) se muestran igual
   que cualquier pregunta normal, sin agrupar.

Esto da una experiencia tipo tabla con **cero cambios de backend**. Si más adelante se prefiere
tener soporte real de matriz en la API (tipo `matriz` + filas/columnas explícitas, igual que ya
existe en el módulo `instrumentos` — ver `instrumentos/models.py` `PreguntaInstrumento`,
`FilaMatrizInstrumento`, `ColumnaMatrizInstrumento` como referencia de diseño), es una migración
de modelo aparte que también implica cambios de renderizado en el frontend — avisen cuando quieran
encararlo y lo construimos de punta a punta.

## 3. Subir un documento ya diligenciado (Word o PDF)

Para departamentos que ya llenaron el diagnóstico en papel o Word antes de que existiera esta
jornada: se sube el archivo, una IA (GPT-4o) lo lee y transcribe las respuestas, y un admin las
revisa y aprueba antes de que cuenten como reales. **El resultado nunca se guarda solo** — queda
en un estado intermedio de revisión hasta que alguien lo aprueba explícitamente, porque hoy no hay
forma de corregir una respuesta ya guardada desde el admin.

Todos los endpoints requieren `Authorization: Token <token de admin>` (mismo login de siempre,
`POST /api/admin/login/`).

### 3.1 Subir el archivo

```
POST /api/admin/momento-extracciones/
Content-Type: multipart/form-data
```

Campos:
| Campo | Obligatorio | Descripción |
|---|---|---|
| `momento` | sí | id del Momento (351 preguntas del diagnóstico) |
| `archivo` | sí | `.pdf` o `.docx` (cualquier otro formato se rechaza con 400) |
| `participante_id` | uno de los dos | id de un `Participante` ya registrado en la jornada |
| `correo_institucional` + `nombre` + `apellido` + `rol` (+ `telefono` opcional) | uno de los dos | para registrar a la persona/departamento de una vez, si todavía no existe |

Respuesta `201`:
```json
{
  "id": 7,
  "momento": 12,
  "momento_titulo": "Instrumento de Diagnóstico para la Articulación Académica",
  "participante": 258,
  "participante_nombre": "Depto Sistemas",
  "estado": "pendiente",
  "resultado": {},
  "preguntas_omitidas": [],
  ...
}
```

El procesamiento corre en segundo plano — el `estado` pasa de `pendiente` → `procesando` →
`completo` (o `error`) en unos segundos/minutos según el tamaño del documento. El frontend debe
hacer polling a `GET /api/admin/momento-extracciones/<id>/` hasta que `estado` deje de ser
`pendiente`/`procesando`.

### 3.2 Revisar el resultado (antes de aprobar)

```
GET /api/admin/momento-extracciones/<id>/
```

Con `estado: "completo"`, `resultado` trae lo que la IA transcribió, sin haber tocado ninguna
`Respuesta` real todavía:
```json
{
  "estado": "completo",
  "resultado": {
    "respuestas": [
      {"pregunta": 8, "texto_libre": "Departamento de Sistemas", "opcion_ids": []},
      {"pregunta": 21, "texto_libre": "", "opcion_ids": [111]}
    ]
  },
  "preguntas_omitidas": []
}
```
`preguntas_omitidas` lista ids de preguntas que la IA intentó llenar pero no pasaron validación
(quedan sin respuesta, a completar manualmente por la persona después si hace falta). El frontend
debería mostrar esta pantalla como una previsualización — idealmente cruzando cada `pregunta` id
contra `GET /api/admin/preguntas/?momento=<id>` para mostrar el texto de la pregunta junto a lo
transcrito, para que el admin pueda leerlo antes de aprobar.

### 3.3 Aprobar (recién ahí se escriben las respuestas reales)

```
POST /api/admin/momento-extracciones/<id>/aprobar/
```

Copia `resultado` a `Respuesta` reales del participante (mismas reglas de validación que un envío
normal desde la web) y marca `aprobado_en`/`aprobado_por`. Solo se puede llamar una vez
(`403` si ya estaba aprobada) y solo si `estado == "completo"` (`400` si no).

No hay endpoint de "rechazar" — si el resultado no sirve, simplemente no se aprueba y se sube el
documento de nuevo (o se le pide a la persona que lo diligencie directo en la web).

### 3.4 Listar extracciones de un momento

```
GET /api/admin/momento-extracciones/?momento=<id>
```

Útil para un panel tipo "documentos pendientes de revisión" — filtrar client-side por
`estado == "completo" && !aprobado_en`.
