# Integración frontend — Assets/system design de la jornada + infografía generada con IA

Guía para el equipo de frontend sobre dos cosas nuevas que van juntas (viven en la pantalla de
administración de una jornada):

- **Assets y system design**: subir imágenes de la jornada y una guía de marca (system design,
  imagen o PDF) desde la creación/actualización de la Jornada.
- **Infografía con IA**: generar 3 imágenes de infografía a partir de esos assets + la analítica
  ya calculada de la jornada.

Ambos endpoints son de **administración** (`/api/admin/...`, `Authorization: Token <hex>`), igual
que el resto del panel — ver la nota de autenticación al final.

---

## 1. Assets de la jornada

### Cuándo mostrarlos

En la pantalla de creación/edición de una `Jornada` (después de guardarla, porque un asset
siempre cuelga de un `id` de jornada ya existente): dos secciones, "Imágenes" y "System design
(guía de marca)".

### Subir assets — **en bloque, un solo POST**

```
POST /api/admin/jornada-assets/
Authorization: Token <hex de 40 chars>
Content-Type: multipart/form-data

jornada: <id de la jornada>
tipo: asset | system_design
archivos: <archivo 1>
archivos: <archivo 2>
archivos: <archivo 3>
texto: <opcional, solo para system_design>
```

El campo se llama **`archivos`** (plural) y se repite una vez por archivo — es el formato estándar
de multipart para listas, el que produce un `<input type="file" multiple>` tal cual. Con un solo
archivo también va como lista de uno.

Un POST **crea un asset por cada archivo**, más uno extra por el `texto` si lo mandan. Por eso la
respuesta es siempre un **array**, nunca un objeto suelto:

```json
[
  {
    "id": 12,
    "jornada": 4,
    "tipo": "asset",
    "archivo": "http://.../media/jornadas/assets/2026/09/foto-1.png",
    "nombre_archivo_original": "foto-1.png",
    "texto": "",
    "subido_por": 3,
    "creado_en": "2026-09-18T15:20:00Z"
  },
  { "id": 13, "...": "..." }
]
```

**Todo o nada**: si un solo archivo de la tanda no pasa la validación, responde `400` (con la
clave `archivos` y el nombre del archivo culpable) y **no se crea ninguno**. Así no quedan dudas
de cuáles entraron — si falla, se corrige y se reintenta la tanda completa.

Formatos aceptados **según `tipo`**:

| `tipo`          | Formatos                                |
|------------------|------------------------------------------|
| `asset`          | `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif` |
| `system_design`  | `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.pdf` |

**No** se aceptan `.svg` ni `.heic`: el backend rasteriza las imágenes con Pillow antes de
mandarlas al modelo, y ninguno de los dos se puede abrir así. Un logo en SVG hay que exportarlo a
PNG; una foto de iPhone en HEIC, a JPG. Si les hace falta alguno de los dos, díganlo y se agrega
la librería correspondiente — hoy se rechazan a propósito, en vez de aceptarlos y que fallen en
silencio a la hora de generar.

> **Ojo si vienen de la primera versión de este doc**: el campo se llamaba `archivo` (singular) y
> ahora es **`archivos`**. Mandar `archivo` responde `400` con un mensaje que lo dice explícito.

`system_design` **no acepta `.docx`** — si la guía de marca solo existe en Word, o la exportan a
PDF/imagen, o la mandan como `texto` (ver abajo). Validen la extensión también en el cliente para
no gastar la subida.

### System design escrito (sin archivo)

No hace falta tener un PDF de marca: se puede mandar la guía como texto plano.

```
POST /api/admin/jornada-assets/
jornada: 4
tipo: system_design
texto: Paleta #14384A (azul institucional) y #C08A28 (ocre). Tipografía serif para títulos,
       sans-serif para cuerpo. Tono sobrio, institucional, sin ilustraciones caricaturescas.
```

- Se puede mandar **solo texto**, **solo archivos**, o **ambos** (ahí se crean dos registros: uno
  con el archivo y otro con el texto, cada uno con su `id`, para poder borrar uno sin el otro).
- Un `system_design` sin archivos **y** sin texto es `400`.
- `texto` **solo aplica a `system_design`**. Mandarlo con `tipo: asset` es `400` (un asset es una
  imagen que se compone, no una instrucción de estilo) — así no se pierde silenciosamente.
- El texto entra **en el prompt** de la generación como guía de marca a respetar; los archivos
  entran como **referencia visual**. Se complementan: pueden mandar el logo como archivo y las
  reglas de color como texto.

### Listar / borrar

```
GET /api/admin/jornada-assets/?jornada=<id>
DELETE /api/admin/jornada-assets/{id}/
```

No hay `PUT`/`PATCH`: un asset se reemplaza subiendo uno nuevo y borrando el viejo. Se permiten
varios `asset` por jornada (se muestran todos, más reciente primero); de `system_design` también
se pueden cargar varios (historial). La infografía usa siempre **lo más reciente de cada clase**:
el último `system_design` con archivo y el último `system_design` con texto — si suben uno nuevo,
el anterior queda solo como registro.

Mismo scoping por dependencia que el resto del panel: una cuenta de dependencia solo ve/crea
assets de sus propias jornadas (`403` si intenta contra una ajena).

---

## 2. Generar la infografía (3 imágenes con IA)

### Requisito previo

La infografía se genera a partir de la analítica **ya calculada** de la jornada — hace falta que
exista, para esa jornada, alguno de estos dos (los que ya usan para el reporte/presentación
normales):

- un `Reporte` con `estado: "completo"` (`POST /api/admin/reportes/` con alcance jornada +
  esperar a que termine), **o**
- un `AnalisisJornadaIA` con `estado: "completo"`.

Si no hay ninguno, la generación termina en `error` con un mensaje explícito pidiendo generar uno
primero — no hace falta validarlo ustedes antes de ofrecer el botón, pero sí es buena UX
deshabilitarlo si saben que la jornada no tiene ni reporte ni análisis completo todavía.

### Disparar la generación

Cuelga de un `Reporte` puntual (no de la jornada directo):

```
POST /api/admin/reportes/{reporte_id}/generar-infografia/
Authorization: Token <hex de 40 chars>
```

Respuesta `202` — arranca en background, no trae las imágenes todavía:
```json
{
  "id": 7,
  "reporte": 21,
  "estado": "pendiente",
  "prompt_usado": "",
  "error_mensaje": "",
  "modelo_usado": "",
  "imagenes": [],
  "solicitado_por": 3,
  "creado_en": "2026-09-18T15:30:00Z",
  "actualizado_en": "2026-09-18T15:30:00Z",
  "completado_en": null
}
```

- `400` si el reporte todavía no está `completo`.
- `409` si ya hay una infografía `pendiente`/`procesando` para ese mismo reporte — esperen a que
  termine (o falle) antes de dejar pedir otra desde el botón.
- Se puede pedir **más de una vez** sobre el mismo reporte (cada `POST` crea una
  `InfografiaJornada` nueva, no sobrescribe la anterior) — útil si quieren repetir la generación.

### Esperar el resultado — es asíncrono

`estado` avanza `pendiente` → `procesando` → `completo` (o `error`). Hagan **polling** contra:

```
GET /api/admin/infografias/?reporte={reporte_id}
```

o directo por id si ya lo tienen: `GET /api/admin/infografias/{id}/`. Un intervalo de 3–5 s está
bien — llamar al modelo de imágenes puede tardar bastante más que un análisis de texto.

| `estado`      | Qué mostrar                                                        |
|----------------|---------------------------------------------------------------------|
| `pendiente`    | "En cola"                                                            |
| `procesando`   | "Generando infografía…" (puede tardar varios minutos)              |
| `completo`     | Mostrar las 3 imágenes de `imagenes`                                |
| `error`        | Mostrar `error_mensaje` y ofrecer reintentar (nuevo `POST`)         |

Respuesta cuando `estado: "completo"`:
```json
{
  "id": 7,
  "reporte": 21,
  "estado": "completo",
  "prompt_usado": "Diseña una infografía vertical...",
  "error_mensaje": "",
  "modelo_usado": "gpt-image-2",
  "imagenes": [
    {"id": 30, "archivo": "http://.../media/analitica/infografias/2026/09/infografia-7-0.png", "orden": 0},
    {"id": 31, "archivo": "http://.../media/analitica/infografias/2026/09/infografia-7-1.png", "orden": 1},
    {"id": 32, "archivo": "http://.../media/analitica/infografias/2026/09/infografia-7-2.png", "orden": 2}
  ],
  "solicitado_por": 3,
  "creado_en": "2026-09-18T15:30:00Z",
  "actualizado_en": "2026-09-18T15:34:12Z",
  "completado_en": "2026-09-18T15:34:12Z"
}
```

`imagenes` viene ordenado por `orden` (0/1/2) — muéstrenlas en ese orden, son 3 variaciones de la
misma infografía, no partes de una sola pieza. `archivo` es la URL directa a la imagen (sirve tal
cual en un `<img src>` o para descarga).

### Qué usan de referencia visual (contexto, no requiere nada del frontend)

El backend arma la infografía usando como referencia real los `asset` más recientes (hasta 4) y el
`system_design` más reciente de esa jornada — si la jornada no tiene ningún asset subido todavía,
igual genera la infografía (sin referencia visual, solo a partir de los datos). No hace falta que
el frontend mande nada de esto en el `POST`: el backend los busca solo a partir de `reporte.jornada`.

---

## 3. Checklist

- [ ] Solo dejar subir assets sobre una jornada ya guardada (con `id`).
- [ ] Usar `<input type="file" multiple>` y mandar **`archivos`** repetido: es subida en bloque,
      no un POST por archivo.
- [ ] Tratar la respuesta del `POST` como **array**, no como objeto.
- [ ] Validar extensión en cliente según `tipo` (`asset`: imagen; `system_design`: imagen o PDF,
      nunca `.docx`) — el backend rechaza la tanda completa si uno falla.
- [ ] Ofrecer el system design también como **campo de texto**, no solo como upload: es lo que se
      va a usar cuando no haya PDF de marca a la mano.
- [ ] No mandar `texto` con `tipo: asset` (es `400`).
- [ ] Listar assets con `?jornada=<id>`; no hay edición, solo subir uno nuevo + borrar el viejo.
- [ ] Deshabilitar (o avisar) el botón de generar infografía si la jornada no tiene ni `Reporte`
      completo ni `AnalisisJornadaIA` completo.
- [ ] `generar-infografia/` cuelga del `id` del **reporte**, no de la jornada.
- [ ] Manejar `409` (ya hay una en curso) sin dejar mandar un segundo `POST` mientras tanto.
- [ ] Polling de `estado` contra `/api/admin/infografias/?reporte=<id>` hasta `completo`/`error`.
- [ ] Mostrar las 3 `imagenes` en orden (`orden` 0/1/2), no asumir que viene una sola.
- [ ] En `error`, mostrar `error_mensaje` y permitir reintentar con un `POST` nuevo.

---

## Nota sobre autenticación

Todo esto vive bajo `/api/admin/...`: `Authorization: Token <hex de 40 chars>`, mismo token de
sesión admin que ya usan para jornadas/momentos/reportes. No hay ninguna ruta pública (de
participante) para assets ni infografías.
