# Integración frontend — Assets/system design de la jornada + infografía generada con IA

Guía para el equipo de frontend sobre dos cosas nuevas que van juntas (viven en la pantalla de
administración de una jornada):

- **Assets y system design**: subir imágenes de la jornada y una guía de marca (system design,
  imagen o PDF) desde la creación/actualización de la Jornada.
- **Infografía con IA**: generar 3 láminas complementarias (16:9) a partir de esos assets + la analítica
  ya calculada de la jornada.

Ambos endpoints son de **administración** (`/api/admin/...`, `Authorization: Token <hex>`), igual
que el resto del panel — ver la nota de autenticación al final.

---

## 0. URL base — el prefijo de despliegue

**Esto aplica a TODOS los endpoints de esta API, no solo a los de este documento.** En el servidor
la aplicación no vive en la raíz del dominio: está montada bajo `/api/aluna-kunsama/`, y nginx
quita ese prefijo antes de pasarle la petición al backend.

```
Base URL (producción):  https://back.alunaia.co/api/aluna-kunsama
```

Todas las rutas que aparecen en este documento son **relativas a esa base**:

| Lo que dice el documento | URL completa que hay que llamar |
|---|---|
| `POST /api/admin/infografias/` | `https://back.alunaia.co/api/aluna-kunsama/api/admin/infografias/` |
| `GET /api/admin/jornada-assets/?jornada=14` | `https://back.alunaia.co/api/aluna-kunsama/api/admin/jornada-assets/?jornada=14` |

Sí, el `/api/` aparece dos veces: uno es el prefijo de despliegue y el otro es parte de la ruta de
la app. No es un error de tipeo.

### Si les da 404, revisen esto primero

Omitir el prefijo devuelve **404**, y es un 404 engañoso porque **lo genera nginx, no la
aplicación**: la petición nunca llega al backend, así que no deja rastro en los logs del servidor y
parece que el endpoint "no existe" cuando en realidad está respondiendo bien a todos los demás.

```
❌  https://back.alunaia.co/api/admin/infografias/?jornada=15              → 404 (nginx)
✅  https://back.alunaia.co/api/aluna-kunsama/api/admin/infografias/?jornada=15  → 200
```

**La barra final también importa.** Sin ella, Django responde `301` a la versión con barra; si su
cliente HTTP no sigue redirecciones —o las sigue pero descarta el header `Authorization` al
hacerlo, que es el comportamiento por defecto de varias librerías— van a ver un `401` o un error
raro en lugar del dato.

```
❌  .../api/admin/infografias?jornada=15   → 301
✅  .../api/admin/infografias/?jornada=15  → 200
```

Recomendación: definan la base URL **una sola vez** en el cliente HTTP y nunca escriban URLs
absolutas a mano en los servicios. La mayoría de estos casos aparecen justo en la ruta que alguien
escribió suelta.

### Las URLs de archivos ya vienen completas

Los campos `archivo` de assets e infografías **ya incluyen el prefijo y el dominio**
(`https://back.alunaia.co/api/aluna-kunsama/media/...`). Úsenlos tal cual en un `<img src>`: no
hay que anteponerles la base ni reconstruirlos, porque hacerlo los rompe.

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
    "archivo": "https://back.alunaia.co/api/aluna-kunsama/media/jornadas/assets/2026/09/foto-1.png",
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

### Límites de carga (importante para la subida en bloque)

| Límite | Valor | Quién lo impone | Qué pasa si se excede |
|---|---|---|---|
| **Tamaño total del request** | **20 MB** | nginx (`client_max_body_size`) | **413** con una página HTML de nginx, **no** un JSON |
| Cantidad de archivos por request | 100 | Django | `400` |
| Tamaño por archivo | sin límite propio | — | lo acota el de 20 MB del request |

**El que van a chocar es el de 20 MB, y es por request completo, no por archivo.** Cinco fotos de
celular de 5 MB cada una ya lo superan. Y como nginx corta la petición **antes** de que Django la
vea, el backend no puede devolverles un mensaje decente: reciben HTML, no JSON.

Por eso, del lado del FE:
- Sumen el tamaño de los archivos seleccionados **antes** de enviar y avisen si pasan de ~18 MB.
- Si el usuario selecciona muchas fotos, **manden varias tandas** en vez de una sola. Como cada
  POST crea sus assets de forma independiente, partir en lotes no tiene ningún efecto secundario.
- Contemplen el `413` con cuerpo HTML como caso de error, porque no van a poder parsearlo como JSON.

Si les resulta muy justo, el límite de nginx se puede subir (son dos líneas de config en el
servidor, requiere root) — díganlo y se gestiona.

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

## 2. Generar la infografía (3 láminas 16:9 con IA)

> **Este apartado quedó corto desde HU-64.** La infografía ahora se puede pedir también sobre
> **un momento** (`{"momento": <id>}`), no solo sobre la jornada, y el contrato completo —los dos
> alcances, los códigos de error, el sondeo y cómo auditar la fuente— está en
> **[INTEGRACION_FRONTEND_INFOGRAFIA.md](INTEGRACION_FRONTEND_INFOGRAFIA.md)**. Lo que sigue acá
> cubre solo el alcance de jornada; úsenlo como referencia rápida y el otro documento como la
> fuente de verdad.

### Requisito previo

La infografía se genera a partir de la analítica **ya calculada** de la jornada. Basta con que
exista **cualquiera** de estas dos (no las dos):

- un **reporte integral** (`AnalisisJornadaIA`) con `estado: "completo"` ← el que genera el panel, **o**
- un `Reporte` del pipeline local con `estado: "completo"`.

**No hace falta crear un `Reporte`.** Si lo que tienen es el reporte integral, con eso alcanza.

### Disparar la generación

Cuelga de la **jornada**:

```
POST /api/admin/infografias/
Authorization: Token <hex de 40 chars>
Content-Type: application/json

{"jornada": 14}
```

Mismo patrón que ya usan para `analisis-jornada-ia` y `reportes`.

> ### ⚠️ Usen esta vía, no la del reporte
>
> **El endpoint que eligen decide de qué datos sale la infografía**, y la diferencia de calidad es
> grande:
>
> | Llamada | Fuente de los datos |
> |---|---|
> | `POST /api/admin/infografias/` con `{"jornada": id}` | **Reporte integral** (`AnalisisJornadaIA`) — el que ya generan en el panel |
> | `POST /api/admin/reportes/{id}/generar-infografia/` | El `Reporte` de ese id (pipeline local) |
>
> Hoy el panel está usando la segunda, y por eso las láminas salen del pipeline local, que con
> pocas respuestas produce un análisis muy pobre (en un caso real quedó sin ningún tema
> detectado). **Cambien a la primera**: es solo cambiar la URL y el body, no hay nada más que
> ajustar.
>
> El atajo desde un reporte sigue existiendo a propósito, para cuando se quiera una infografía de
> un reporte puntual. Si mandan `{"jornada": 14, "reporte": 8}` fuerzan esa fuente de forma
> explícita.

Si la jornada **no tiene analítica**, responde `400` de inmediato con el mensaje explicándolo —
no crea un registro que iba a fallar. Así pueden mostrar el error sin esperar al polling. Si no
hay reporte integral pero sí un `Reporte` completo, el backend lo usa como respaldo en vez de
fallar.

Respuesta `201` — arranca en background, no trae las imágenes todavía:
```json
{
  "id": 7,
  "jornada": 14,
  "jornada_slug": "mujeres-al-mar",
  "reporte": null,
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

- `400` si la jornada no tiene analítica calculada (ni reporte integral ni `Reporte` completo).
- `409` si ya hay una infografía `pendiente`/`procesando` para esa jornada — esperen a que termine
  (o falle) antes de dejar pedir otra desde el botón.
- Se puede pedir **más de una vez** (cada `POST` crea una `InfografiaJornada` nueva, no sobrescribe
  la anterior) — útil para regenerar sin perder la versión previa.

### Esperar el resultado — es asíncrono

`estado` avanza `pendiente` → `procesando` → `completo` (o `error`). Hagan **polling** contra:

```
GET /api/admin/infografias/?jornada={jornada_id}
```

o directo por id si ya lo tienen: `GET /api/admin/infografias/{id}/`. Un intervalo de 3–5 s está
bien — llamar al modelo de imágenes puede tardar bastante más que un análisis de texto.

| `estado`      | Qué mostrar                                                        |
|----------------|---------------------------------------------------------------------|
| `pendiente`    | "En cola"                                                            |
| `procesando`   | "Generando infografía…" (puede tardar varios minutos)              |
| `completo`     | Mostrar las láminas de `imagenes` en orden (ver abajo)             |
| `error`        | Mostrar `error_mensaje` y ofrecer reintentar (nuevo `POST`)         |

Respuesta cuando `estado: "completo"`:
```json
{
  "id": 7,
  "reporte": null,
  "estado": "completo",
  "prompt_usado": "Diseña una lámina APAISADA en formato 16:9...",
  "error_mensaje": "",
  "modelo_usado": "gpt-image-2",
  "imagenes": [
    {"id": 30, "archivo": "https://back.alunaia.co/api/aluna-kunsama/media/analitica/infografias/2026/09/infografia-7-0.png", "orden": 0},
    {"id": 31, "archivo": "https://back.alunaia.co/api/aluna-kunsama/media/analitica/infografias/2026/09/infografia-7-1.png", "orden": 1},
    {"id": 32, "archivo": "https://back.alunaia.co/api/aluna-kunsama/media/analitica/infografias/2026/09/infografia-7-2.png", "orden": 2}
  ],
  "solicitado_por": 3,
  "creado_en": "2026-09-18T15:30:00Z",
  "actualizado_en": "2026-09-18T15:34:12Z",
  "completado_en": "2026-09-18T15:34:12Z"
}
```

`imagenes` viene ordenado por `orden` (0/1/2) y **el orden importa**: no son variaciones de lo
mismo, son **3 láminas complementarias**, como las diapositivas de una presentación:

| `orden` | Lámina | Contenido |
|---|---|---|
| 0 | Portada | Nombre de la jornada + cifras clave de participación |
| 1 | Hallazgos | Temas principales con sus datos y las visualizaciones |
| 2 | Cierre | Conclusiones y mensajes accionables |

Muéstrenlas siempre en ese orden (carrusel, galería o descarga como set). Cada una es **16:9
(2048×1152)**, pensada para proyectar. `archivo` es la URL directa (sirve tal cual en un
`<img src>` o para descarga).

**Puede venir menos de 3.** Cada lámina es una llamada independiente al modelo; si una falla, las
que sí salieron se conservan y el `estado` queda en `completo` con un `error_mensaje` que dice
cuál faltó. Si reciben `error_mensaje` no vacío con `estado: "completo"`, muestren las imágenes
que llegaron y un aviso — no lo traten como un fallo total.

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
- [ ] **Migrar el disparo** de `POST /api/admin/reportes/{id}/generar-infografia/` a
      `POST /api/admin/infografias/` con `{"jornada": id}`. No es cosmético: de eso depende que
      las láminas salgan del reporte integral y no del pipeline local (ver el aviso de la
      sección 2). Tampoco hace falta crear un `Reporte`.
- [ ] Manejar `409` (ya hay una en curso) sin dejar mandar un segundo `POST` mientras tanto.
- [ ] Polling de `estado` contra `/api/admin/infografias/?jornada=<id>` hasta `completo`/`error`.
- [ ] Mostrar las `imagenes` en orden (`orden` 0/1/2): son portada, hallazgos y cierre — no variaciones. Contemplar que puedan venir menos de 3.
- [ ] En `error`, mostrar `error_mensaje` y permitir reintentar con un `POST` nuevo.

---

## Nota sobre autenticación

Todo esto vive bajo `/api/admin/...`: `Authorization: Token <hex de 40 chars>`, mismo token de
sesión admin que ya usan para jornadas/momentos/reportes. No hay ninguna ruta pública (de
participante) para assets ni infografías.

Recuerden el prefijo de despliegue de la sección 0: la ruta completa es
`https://back.alunaia.co/api/aluna-kunsama` + lo que diga cada endpoint acá.

---

## Apéndice — Diagnóstico rápido por código de respuesta

Tabla para no tener que rastrear de cero cuando algo falla:

| Código | Qué suele significar | Dónde mirar |
|---|---|---|
| `401` | Falta el header `Authorization`, o se perdió al seguir un `301` | El header y la barra final de la URL |
| `403` | El token es de una cuenta *dependencia* y la jornada no le pertenece | Propietarios de la jornada |
| `404` (HTML) | **Falta el prefijo `/api/aluna-kunsama`** — lo corta nginx, no llega al backend | La URL completa en la pestaña Network |
| `404` (JSON) | El id existe en la URL pero no en la base, o está fuera del alcance de la cuenta | El id que están mandando |
| `400` | Validación: campo mal nombrado, formato no soportado, o falta analítica para generar | El cuerpo de la respuesta, que dice cuál |
| `409` | Ya hay una generación en curso para esa jornada | Esperar a que termine o falle |
| `413` (HTML) | La tanda de archivos superó los 20 MB de nginx | Sumar tamaños antes de enviar |

La diferencia entre los dos `404` es la clave: si el cuerpo es **HTML** de nginx, el problema es la
URL; si es **JSON** de DRF, la URL está bien y el problema es el recurso.
