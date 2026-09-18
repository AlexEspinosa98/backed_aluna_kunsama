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

### Subir un asset

```
POST /api/admin/jornada-assets/
Authorization: Token <hex de 40 chars>
Content-Type: multipart/form-data

jornada: <id de la jornada>
tipo: asset | system_design
archivo: <el archivo>
```

Formatos aceptados **según `tipo`** (`400` con la clave `archivo` si no calza):

| `tipo`          | Formatos                        |
|------------------|----------------------------------|
| `asset`          | `.png`, `.jpg`, `.jpeg`, `.webp` |
| `system_design`  | `.png`, `.jpg`, `.jpeg`, `.webp`, `.pdf` |

`system_design` **no acepta `.docx`** — si la guía de marca solo existe en Word, hay que
exportarla a PDF o a imagen antes de subirla (no hay forma de rasterizar un Word sin herramientas
externas que el backend no tiene instaladas). Validen la extensión también en el cliente para no
gastar la subida.

Respuesta `201`:
```json
{
  "id": 12,
  "jornada": 4,
  "tipo": "asset",
  "archivo": "http://.../media/jornadas/assets/2026/09/logo.png",
  "nombre_archivo_original": "logo.png",
  "subido_por": 3,
  "creado_en": "2026-09-18T15:20:00Z"
}
```

### Listar / borrar

```
GET /api/admin/jornada-assets/?jornada=<id>
DELETE /api/admin/jornada-assets/{id}/
```

No hay `PUT`/`PATCH`: un asset se reemplaza subiendo uno nuevo y borrando el viejo. Se permiten
varios `asset` por jornada (se muestran todos, más reciente primero); de `system_design` también
se pueden subir varios (historial), pero **la infografía siempre usa el más reciente** — si suben
uno nuevo, el anterior queda solo como registro.

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
- [ ] Validar extensión en cliente según `tipo` (`asset`: imagen; `system_design`: imagen o PDF,
      nunca `.docx`).
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
