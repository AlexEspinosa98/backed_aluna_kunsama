# Estructura de preguntas — los 6 tipos completos

Referencia rápida: para cada tipo de `Pregunta`, cómo se **crea** (admin), qué **trae** al leerla
(`GET .../momentos/{id}/` o `GET /api/admin/preguntas/?momento=<id>`), cómo se **responde**
(`POST .../momentos/{id}/respuestas/`) y cómo se **lee lo ya respondido**
(`GET .../momentos/{id}/respuestas/`, HU-47).

Todos los ejemplos de creación/edición van con `Authorization: Token <token de admin>`. Todos los
de responder/leer respuestas van con `Authorization: Participant <token de participante>` (dos
esquemas de auth distintos — ver nota al final).

---

## 1. `abierta` — texto libre

### Crear
```bash
POST /api/admin/preguntas/
{
  "momento": 61,
  "tipo": "abierta",
  "texto": "¿Por qué esos nodos priorizó?",
  "orden": 4,
  "obligatoria": true
}
```

### Cómo se lee (dentro de `GET .../momentos/{id}/`)
```json
{
  "id": 934,
  "tipo": "abierta",
  "texto": "¿Por qué esos nodos priorizó?",
  "orden": 4,
  "obligatoria": true,
  "opciones": [],
  "filas": [],
  "columnas": []
}
```

### Responder
```json
{ "respuestas": [
  { "pregunta_id": 934, "texto_libre": "Porque concentran la mayor actividad portuaria actual." }
] }
```

### Leer respuesta guardada
```json
[{ "id": 4801, "pregunta": 934, "participante": 343, "mesa": null, "fila": null, "fila_lista": null,
   "columna": null, "texto_libre": "Porque concentran la mayor actividad portuaria actual.",
   "opciones": [], "actualizado_en": "2026-09-17T12:00:00Z" }]
```

---

## 2. `unica` — selección única

### Crear pregunta + opciones
```bash
POST /api/admin/preguntas/
{ "momento": 61, "tipo": "unica", "texto": "A5 · Tipo de actor", "orden": 5, "obligatoria": true }
# -> id: 950

POST /api/admin/opciones/
{ "pregunta": 950, "texto": "Autoridad local o distrital", "orden": 1 }
POST /api/admin/opciones/
{ "pregunta": 950, "texto": "Zona franca", "orden": 2 }
# ... una llamada por opción
```

### Cómo se lee
```json
{
  "id": 950,
  "tipo": "unica",
  "texto": "A5 · Tipo de actor",
  "opciones": [
    { "id": 665, "pregunta": 950, "texto": "Autoridad local o distrital", "orden": 1 },
    { "id": 666, "pregunta": 950, "texto": "Zona franca", "orden": 2 }
  ],
  "filas": [], "columnas": []
}
```

### Responder — máximo una opción
```json
{ "respuestas": [
  { "pregunta_id": 950, "opcion_ids": [666] }
] }
```
`400` si se mandan 2+ `opcion_ids` en una pregunta `unica`.

### Leer respuesta guardada
```json
[{ "id": 4802, "pregunta": 950, "participante": 343, "mesa": null, "fila": null, "fila_lista": null,
   "columna": null, "texto_libre": "", "opciones": [{"id": 666, "texto": "Zona franca", "orden": 2}],
   "actualizado_en": "..." }]
```

---

## 3. `multiple` — selección múltiple

Idéntico a `unica` en creación (mismas llamadas `POST /preguntas/` + `POST /opciones/`), la única
diferencia real está en la respuesta:

### Responder — varias opciones a la vez
```json
{ "respuestas": [
  { "pregunta_id": 951, "opcion_ids": [670, 672, 675] }
] }
```
Sin límite de cantidad a nivel de backend (un "máximo 3" en el texto de la pregunta es solo una
instrucción visual, no algo que el backend valide).

---

## 4. `matriz` — tabla de tamaño fijo (filas Y columnas las define el admin)

### Crear pregunta + filas + columnas
```bash
POST /api/admin/preguntas/
{ "momento": 68, "tipo": "matriz", "texto": "Mapa de capacidades profesorales", "orden": 1, "obligatoria": true }
# -> id: 1200

POST /api/admin/preguntas-filas-matriz/
{ "pregunta": 1200, "texto": "Profesor 1", "orden": 1 }
POST /api/admin/preguntas-filas-matriz/
{ "pregunta": 1200, "texto": "Profesor 2", "orden": 2 }
# ... una llamada por fila (cantidad FIJA, conocida de antemano)

POST /api/admin/preguntas-columnas-matriz/
{ "pregunta": 1200, "texto": "Formación", "orden": 1 }
POST /api/admin/preguntas-columnas-matriz/
{ "pregunta": 1200, "texto": "Área de experticia", "orden": 2 }
# ... una llamada por columna
```

### Cómo se lee
```json
{
  "id": 1200,
  "tipo": "matriz",
  "texto": "Mapa de capacidades profesorales",
  "opciones": [],
  "filas": [
    { "id": 10, "pregunta": 1200, "texto": "Profesor 1", "orden": 1 },
    { "id": 11, "pregunta": 1200, "texto": "Profesor 2", "orden": 2 }
  ],
  "columnas": [
    { "id": 20, "pregunta": 1200, "texto": "Formación", "orden": 1 },
    { "id": 21, "pregunta": 1200, "texto": "Área de experticia", "orden": 2 }
  ]
}
```

### Responder — una entrada por celda (fila × columna), usando los `id` reales de arriba
```json
{ "respuestas": [
  { "pregunta_id": 1200, "fila_id": 10, "columna_id": 20, "texto_libre": "Magíster" },
  { "pregunta_id": 1200, "fila_id": 10, "columna_id": 21, "texto_libre": "Biotecnología marina" },
  { "pregunta_id": 1200, "fila_id": 11, "columna_id": 20, "texto_libre": "Doctora" },
  { "pregunta_id": 1200, "fila_id": 11, "columna_id": 21, "texto_libre": "Economía circular" }
] }
```
Si `obligatoria: true`, el backend exige **todas** las celdas (todo fila×columna) — falta una sola
y es `400` con `{"faltantes": [1200]}` (el id de la pregunta, no celda por celda).

### Leer respuestas guardadas — una fila plana por celda, agrupar por `fila` en el front
```json
[
  { "id": 5001, "pregunta": 1200, "fila": 10, "fila_lista": null, "columna": 20, "texto_libre": "Magíster", "opciones": [], "actualizado_en": "..." },
  { "id": 5002, "pregunta": 1200, "fila": 10, "fila_lista": null, "columna": 21, "texto_libre": "Biotecnología marina", "opciones": [], "actualizado_en": "..." }
]
```

### `filas_adicionales` — dejar que además agreguen filas (HU-53)
Por defecto una matriz es de filas fijas (`filas_adicionales: false`). Encendiéndolo, quien
responde puede **anexar filas extra** a las que definió el admin:
```bash
POST /api/admin/preguntas/
{ "momento": 68, "tipo": "matriz", "texto": "...", "orden": 1, "filas_adicionales": true }
# o sobre una que ya existe:
PATCH /api/admin/preguntas/1200/
{ "filas_adicionales": true }
```
Las filas extra se mandan con `fila_temporal`, igual que en una `lista`, y conviven con las fijas
**en el mismo envío**:
```json
{ "respuestas": [
  { "pregunta_id": 1200, "fila_id": 10, "columna_id": 20, "texto_libre": "Magíster" },
  { "pregunta_id": 1200, "fila_id": 10, "columna_id": 21, "texto_libre": "Biotecnología marina" },
  { "pregunta_id": 1200, "fila_temporal": 1, "columna_id": 20, "texto_libre": "Doctora" },
  { "pregunta_id": 1200, "fila_temporal": 1, "columna_id": 21, "texto_libre": "Economía circular" }
] }
```
- `400` si una celda trae `fila_id` y `fila_temporal` a la vez, y `400` si se manda
  `fila_temporal` con el flag apagado.
- Al leer, las celdas fijas vienen con `fila` y las extra con `fila_lista` — el front agrupa por
  el que no sea `null`.
- **Las filas extra nunca son obligatorias**: `obligatoria: true` sigue exigiendo solo todas las
  celdas fijas (fila×columna del admin).
- **Cada envío reemplaza por completo las filas extra** (misma regla que `lista`): reenviar el
  momento sin ninguna celda `fila_temporal` las borra todas. Las fijas no se tocan.

---

## 5. `lista` — columnas fijas, filas las agrega quien responde (HU-51, nuevo)

Igual que `matriz` pero **sin** `POST /preguntas-filas-matriz/` — las filas no las define el admin.

Una `lista` siempre trae `filas_adicionales: true` y no se puede apagar (`400` si se intenta):
sus filas *son* las que agrega quien responde, así que con el flag apagado quedaría sin ninguna
forma de responderse. Si lo que se quiere es una tabla con filas fijas más algunas extra, eso es
una `matriz` con `filas_adicionales: true` (ver sección 4), no una lista.

### Crear pregunta + solo columnas
```bash
POST /api/admin/preguntas/
{ "momento": 68, "tipo": "lista", "texto": "Mapa de capacidades profesorales", "orden": 1, "obligatoria": true }
# -> id: 1300

POST /api/admin/preguntas-columnas-matriz/
{ "pregunta": 1300, "texto": "Profesor(a)", "orden": 1 }
POST /api/admin/preguntas-columnas-matriz/
{ "pregunta": 1300, "texto": "Formación", "orden": 2 }
POST /api/admin/preguntas-columnas-matriz/
{ "pregunta": 1300, "texto": "Área de experticia", "orden": 3 }
```

### Cómo se lee — `filas` siempre viene vacío (no existen filas predefinidas)
```json
{
  "id": 1300,
  "tipo": "lista",
  "texto": "Mapa de capacidades profesorales",
  "opciones": [],
  "filas": [],
  "columnas": [
    { "id": 30, "pregunta": 1300, "texto": "Profesor(a)", "orden": 1 },
    { "id": 31, "pregunta": 1300, "texto": "Formación", "orden": 2 },
    { "id": 32, "pregunta": 1300, "texto": "Área de experticia", "orden": 3 }
  ]
}
```

### Responder — `fila_temporal` en vez de `fila_id`
`fila_temporal` **no es el id de nada que ya exista** — es un número que el propio cliente
inventa para decir "estas celdas van en la misma fila" (1 para la primera fila que agrega, 2
para la segunda...). El backend crea la fila real al procesar el envío.
```json
{ "respuestas": [
  { "pregunta_id": 1300, "fila_temporal": 1, "columna_id": 30, "texto_libre": "Juan Pérez" },
  { "pregunta_id": 1300, "fila_temporal": 1, "columna_id": 31, "texto_libre": "Magíster" },
  { "pregunta_id": 1300, "fila_temporal": 1, "columna_id": 32, "texto_libre": "Biotecnología marina" },
  { "pregunta_id": 1300, "fila_temporal": 2, "columna_id": 30, "texto_libre": "Ana Gómez" },
  { "pregunta_id": 1300, "fila_temporal": 2, "columna_id": 31, "texto_libre": "Doctora" },
  { "pregunta_id": 1300, "fila_temporal": 2, "columna_id": 32, "texto_libre": "Economía circular" }
] }
```
**Cada envío reemplaza por completo las filas anteriores** de esa pregunta (no intenta emparejar
`fila_temporal` entre envíos distintos — reenviar con 1 fila en vez de 2 borra la segunda).
Si `obligatoria: true`, alcanza con que **al menos una fila** tenga **todas** sus columnas
respondidas (no exige que todas las filas estén completas).

### Leer respuestas guardadas — agrupar por `fila_lista` en el front (no por `fila`, que siempre viene `null` acá)
```json
[
  { "id": 6001, "pregunta": 1300, "fila": null, "fila_lista": 55, "columna": 30, "texto_libre": "Juan Pérez", "opciones": [], "actualizado_en": "..." },
  { "id": 6002, "pregunta": 1300, "fila": null, "fila_lista": 55, "columna": 31, "texto_libre": "Magíster", "opciones": [], "actualizado_en": "..." },
  { "id": 6003, "pregunta": 1300, "fila": null, "fila_lista": 56, "columna": 30, "texto_libre": "Ana Gómez", "opciones": [], "actualizado_en": "..." }
]
```

---

## 6. `audio` — el cliente graba y transcribe; el backend guarda solo el texto (HU-52, nuevo)

El participante contesta hablando. **La transcripción la hace el front**, y lo único que llega
acá es el texto resultante. El backend **no recibe, no guarda y no sirve ningún archivo de
audio** — no hay campo de archivo, no hay upload, no hay URL de audio en ninguna respuesta.

Para el backend, `audio` es idéntica a `abierta`: se responde con `texto_libre` y se guarda en
`Respuesta.texto_libre`. Existe como tipo aparte para que el front sepa qué renderizar (un
grabador en vez de un textarea) y para que la analítica pueda distinguir de dónde salió el texto.

### Crear
```bash
POST /api/admin/preguntas/
{
  "momento": 61,
  "tipo": "audio",
  "texto": "Cuéntanos en voz alta qué te llevas de la jornada",
  "orden": 6,
  "obligatoria": true
}
```
No lleva opciones, ni filas, ni columnas — no hay nada más que crear.

### Cómo se lee (dentro de `GET .../momentos/{id}/`)
```json
{
  "id": 1400,
  "tipo": "audio",
  "texto": "Cuéntanos en voz alta qué te llevas de la jornada",
  "orden": 6,
  "obligatoria": true,
  "opciones": [],
  "filas": [],
  "columnas": []
}
```

### Responder — exactamente igual que una `abierta`
```json
{ "respuestas": [
  { "pregunta_id": 1400, "texto_libre": "Me llevo la idea de que el diálogo de saberes no es un paso previo, es el método." }
] }
```
`texto_libre` es la transcripción ya hecha por el cliente. `400` si se mandan `opcion_ids`,
`fila_id`, `columna_id` o `fila_temporal`. Si `obligatoria: true`, un `texto_libre` vacío o solo
con espacios también es `400`.

### Leer respuesta guardada
```json
[{ "id": 7001, "pregunta": 1400, "participante": 343, "mesa": null, "fila": null, "fila_lista": null,
   "columna": null, "texto_libre": "Me llevo la idea de que el diálogo de saberes no es un paso previo, es el método.",
   "opciones": [], "actualizado_en": "2026-09-18T12:00:00Z" }]
```

### En analítica y exportes
Cuenta como texto libre, igual que `abierta`: entra al pipeline de tópicos/BERTopic, al análisis
por IA y sale como texto (no como conteo de opciones) en el Excel. Si algún día se quisiera
guardar el audio en sí, sería otro modelo y otro ticket — hoy no se almacena nada más que la
transcripción.

---

## Extras que aplican a cualquier tipo de pregunta (o de momento)

### Restringir por mesa (solo tiene efecto en momentos `tipo: "mesa"`)
```bash
PATCH /api/admin/momentos/{id}/
{ "mesas_permitidas": [1, 3] }          # vacío = visible para todas

PATCH /api/admin/preguntas/{id}/
{ "mesas_permitidas": [2] }
```

### Restringir por rol (aplica siempre, sea el momento individual o de mesa)
```bash
# 1. opcional: definir el catálogo de roles de la jornada
POST /api/admin/jornadas-roles/
{ "jornada": 12, "nombre": "directivo" }

# 2. restringir
PATCH /api/admin/momentos/{id}/
{ "roles_permitidos": ["directivo"] }   # vacío = visible para todos los roles

PATCH /api/admin/preguntas/{id}/
{ "roles_permitidos": ["directivo", "docente"] }
```
Compara contra `Participante.rol` como texto exacto (sensible a mayúsculas) — no depende de que
el catálogo `jornadas-roles` exista.

### Condicionar una pregunta a la opción de otra (misma jornada, cualquier momento)
```bash
PATCH /api/admin/preguntas/{id_pregunta_condicionada}/
{ "depende_de_opcion": <id de una OpcionPregunta de OTRA pregunta de la misma jornada> }
```
La pregunta condicionada no aparece en `GET .../momentos/{id}/` hasta que el participante ya
haya marcado esa opción específica (en un envío anterior, o en el mismo `POST` si va junto con
la disparadora). Solo funciona con preguntas `unica`/`multiple` como disparadoras — no hay forma
de condicionar por un valor de escala/rango ni por "cualquiera de varias opciones" (ver
docs/USER_STORIES_COMPLETO.md, HU-50, sección de limitaciones).

---

## Nota sobre autenticación

Dos esquemas **distintos**, no intercambiables — el keyword del header es lo que le dice al
backend a qué tabla ir a buscar:

| Quién | Header | Tabla |
|---|---|---|
| Admin/staff | `Authorization: Token <hex de 40 caracteres>` | `authtoken_token` (Django) |
| Participante | `Authorization: Participant <uuid>` | `Participante.token` |

`POST /api/admin/login/` (con usuario/contraseña de staff) da el primero. `POST
/api/jornadas/{slug}/registro/` o `.../login/` (con correo institucional) dan el segundo.
