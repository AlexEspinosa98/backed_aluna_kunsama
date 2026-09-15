# Integración frontend — Diagnóstico de Articulación Académica

Guía para el equipo de frontend: cómo mostrar el instrumento de diagnóstico dentro de una jornada
y cómo integrar la nueva función de "subir documento ya diligenciado" (Word o PDF) que lo
transcribe con IA.

## 1. Contexto — 90 preguntas, 7 de ellas tipo matriz real

El diagnóstico vive en un **único Momento** ("Instrumento de Diagnóstico para la Articulación
Académica") con **90 preguntas** — la misma cantidad que el documento original. `Pregunta` ahora
soporta un cuarto tipo, `matriz`, además de `abierta`/`unica`/`multiple`: una pregunta matriz no
tiene texto de una sola celda, tiene **filas y columnas reales** (cada una con su propio id), y se
llena una celda a la vez (fila × columna). 7 de las 90 preguntas son de este tipo: Matriz de
responsabilidades (12×4), Análisis de coherencia × 3 componentes (7×4 cada uno), Mapa de
capacidades profesorales (12×6), Asuntos para decisión institucional (8×4), Compromisos
inmediatos (8×4).

```
GET /api/admin/momentos/?jornada=<id_jornada>
GET /api/admin/preguntas/?momento=<id_momento>
```

Cada pregunta en esa respuesta trae, según su tipo, `opciones` (única/múltiple) o `filas`/`columnas`
(matriz) ya anidadas — no hace falta ninguna llamada extra ni parsear texto para reconstruir nada:

```json
{
  "id": 901,
  "tipo": "matriz",
  "texto": "Para cada proceso, indique quién lo hace hoy, quién debería liderar...",
  "obligatoria": true,
  "filas": [{"id": 1, "texto": "Microdiseños", "orden": 1}, {"id": 2, "texto": "Estándares disciplinares", "orden": 2}],
  "columnas": [{"id": 1, "texto": "¿Quién lo hace hoy?", "orden": 1}, {"id": 2, "texto": "¿Quién debería liderar?", "orden": 2}]
}
```

## 2. Cómo dibujarla: una tabla real, `filas` en el eje Y, `columnas` en el eje X

Con `filas`/`columnas` ya en la respuesta, dibujar la tabla es directo: una fila HTML por cada
elemento de `filas`, una columna por cada elemento de `columnas`, una celda editable (input/
textarea) en cada intersección. No hace falta agrupar preguntas ni parsear texto — eso era
necesario en la versión anterior de este documento, cuando `Pregunta` todavía no tenía tipo
`matriz` y cada celda llegaba como una pregunta suelta con el texto combinando fila y columna;
ya no aplica.

**Enviar una celda** (`POST .../momentos/{id}/respuestas/`, mismo endpoint de siempre para
cualquier tipo de pregunta): una entrada por celda, todas con el mismo `pregunta_id` pero
`fila_id`/`columna_id` distintos —

```json
{"respuestas": [
  {"pregunta_id": 901, "fila_id": 1, "columna_id": 1, "texto_libre": "El jefe de departamento"},
  {"pregunta_id": 901, "fila_id": 1, "columna_id": 2, "texto_libre": "El comité curricular"}
]}
```

Si la pregunta es `obligatoria`, el backend exige **todas** las celdas (todo fila × columna) antes
de aceptar el envío — si falta una sola, responde `400` con `{"faltantes": [901, ...]}` (el id de
la pregunta, no celda por celda). `fila_id`/`columna_id` nunca van en preguntas que no son matriz
(sería `400`), y en una matriz son obligatorios y deben pertenecer a esa pregunta específica.

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
| `momento` | sí | id del Momento (90 preguntas del diagnóstico, 7 de ellas tipo matriz) |
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
      {"pregunta": 8, "texto_libre": "Departamento de Sistemas", "opcion_ids": [], "fila_id": null, "columna_id": null},
      {"pregunta": 21, "texto_libre": "", "opcion_ids": [111], "fila_id": null, "columna_id": null},
      {"pregunta": 901, "texto_libre": "El jefe de departamento", "opcion_ids": [], "fila_id": 1, "columna_id": 1}
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
