# Integración frontend — Carga de documentos por el usuario y responsable detectado por IA

Guía para el equipo de frontend sobre dos cambios que van juntos en la misma pantalla:

- **HU-56**: el usuario preregistrado puede subir **él mismo** su documento diligenciado.
- **HU-55**: al subir ya no hace falta decir **de quién es** el documento — la IA lo lee y lo
  empareja sola.

---

## 1. HU-56 — El botón de subir en la pantalla del usuario

### Cuándo mostrarlo

El detalle del instrumento y el listado de asignados traen un campo nuevo:

```
GET /api/instrumentos/                      (listado)
GET /api/instrumentos/{slug}/               (detalle)
Authorization: Token <token del usuario>
```
```json
{
  "id": 3,
  "slug": "diagnostico-articulacion",
  "nombre": "Diagnóstico de Articulación Académica",
  "permite_carga_archivo": true,
  "secciones": [ ... ],
  "mi_aplicacion": null
}
```

**Mostrar el botón solo si `permite_carga_archivo` es `true`.** Viene apagado por defecto y se
habilita instrumento por instrumento: si está en `false` y se intenta subir igual, el backend
responde `403`. No lo deduzcan de ninguna otra cosa — es el único dato que lo dice.

### Subir

```
POST /api/instrumentos/{slug}/cargar-archivo/
Authorization: Token <token del usuario>
Content-Type: multipart/form-data

archivo: <el .pdf o .docx>
```

Solo `.pdf` y `.docx` (`400` con la clave `archivo` si es otra cosa — validen también del lado
del cliente para no gastar la subida).

El documento queda **siempre a nombre de quien sube**. No manden `usuario_id` ni nada parecido:
el backend lo ignora y usa la sesión. No hay forma de subir a nombre de otra persona por esta vía.

Respuesta `201`:
```json
{
  "id": 42,
  "instrumento": 3,
  "usuario": 17,
  "nombre_archivo_original": "diagnostico-firmado.pdf",
  "estado": "pendiente",
  "aplicacion": null,
  "responsable_estado": "no_buscado",
  "preguntas_omitidas": []
}
```

### Esperar el resultado — es asíncrono

La transcripción corre en background. `estado` avanza
`pendiente` → `procesando` → `completo` (o `error`). Hagan **polling** contra:

```
GET /api/instrumentos/{slug}/mis-cargas/
```

que devuelve solo las cargas del propio usuario (el endpoint de admin no les va a responder).
Un intervalo de 3–5 s está bien; un documento largo con páginas escaneadas puede tardar minutos.

| `estado`      | Qué mostrar                                                                 |
|---------------|------------------------------------------------------------------------------|
| `pendiente`   | "En cola"                                                                     |
| `procesando`  | "Leyendo tu documento…"                                                       |
| `completo`    | "Listo, quedó en revisión" + refrescar el detalle para ver `mi_aplicacion`     |
| `error`       | Mostrar `error_mensaje` y ofrecer volver a intentar                           |

### Importante para el copy de la pantalla

Subir el documento **no es enviarlo aprobado**. El resultado queda como una aplicación en estado
**pendiente de revisión**, marcada como generada por IA, y un encargado la revisa. Díganlo en la
UI: "Tu documento se transcribió y quedó en revisión", no "Instrumento enviado".

Tampoco reemplaza diligenciar en línea: si el usuario ya tiene respuestas, la transcripción las
sobrescribe con lo que traiga el documento.

---

## 2. HU-55 — El responsable ya no se pregunta al subir

Esto aplica a la **pantalla de administración** (cargar documentos de otras personas), tanto de
instrumentos como de momentos de jornada.

### Antes / ahora

Antes había que elegir la persona **antes** de subir. Ahora `usuario_id` (instrumentos) y
`participante_id` (momentos) son **opcionales**: si no se mandan, la IA lee el responsable del
propio documento y el backend lo empareja contra la base.

```bash
# Instrumentos — basta el archivo
POST /api/admin/instrumento-extracciones/
{ "instrumento": 3, "archivo": <file> }

# Momentos — igual
POST /api/admin/momento-extracciones/
{ "momento": 61, "archivo": <file> }
```

Los tres caminos siguen siendo válidos:

| Qué mandan                                             | Qué pasa                                            |
|--------------------------------------------------------|-----------------------------------------------------|
| `usuario_id` / `participante_id`                       | Se usa esa persona. La IA **no** lo pisa.           |
| Los campos de alta completos                           | Se crea/reutiliza la persona, como siempre.         |
| **Nada**                                               | La IA detecta al responsable y se intenta emparejar.|

Ojo: mandar **media** ficha de alta (ej. solo `nombre`) sigue siendo `400`. Omitir todo es
delegarle la detección a la IA; mandar la mitad es un error del cliente.

### Lo que devuelve el emparejamiento

Dos campos nuevos en el detalle de la extracción:

```json
{
  "id": 42,
  "usuario": 17,
  "responsable_detectado": {
    "nombre": "Juan Pérez",
    "correo": "juan@uni.edu.co",
    "cargo": "Jefe de departamento",
    "dependencia": "Ingeniería"
  },
  "responsable_estado": "emparejado"
}
```

`responsable_detectado` es **lo que la IA leyó**, tal cual, sin normalizar. `responsable_estado`
es el resultado de nuestro emparejamiento:

| `responsable_estado` | Significa                                            | Qué debe hacer el front                          |
|----------------------|------------------------------------------------------|--------------------------------------------------|
| `no_buscado`         | Se indicó la persona a mano al subir                 | Nada                                             |
| `emparejado`         | Se encontró exactamente una persona                  | Mostrarla; permitir corregir si se ve mal        |
| `ambiguo`            | Coinciden **varias** personas                        | **Pedir que elijan** — mostrar lo detectado      |
| `sin_coincidencia`   | No coincide nadie                                    | **Pedir que elijan**                             |
| `sin_dato`           | El documento no traía responsable                    | **Pedir que elijan**                             |

En los tres últimos casos `usuario` / `participante` viene en **`null`**: la transcripción está
hecha y guardada, lo único que falta es a nombre de quién se escribe.

> **No "resuelvan" ustedes una ambigüedad tomando el primero.** El backend deliberadamente no lo
> hace: una respuesta atribuida a quien no la dio es peor que una que espera un clic. Muestren
> `responsable_detectado` para que la persona que revisa decida con el dato a la vista.

### Estados de la extracción

**Instrumentos** gana un estado nuevo:

| `estado`           | Significa                                                              |
|--------------------|-------------------------------------------------------------------------|
| `pendiente`        | En cola                                                                 |
| `procesando`       | La IA está leyendo                                                      |
| `sin_responsable`  | **Transcrito, pero falta asignar la persona** — hay que actuar          |
| `completo`         | Escrito, la aplicación quedó en revisión                                |
| `error`            | Falló (ver `error_mensaje`)                                             |

**Momentos** no necesita estado nuevo: ese flujo ya guardaba el resultado y esperaba un `aprobar`
explícito. Una extracción sin responsable llega a `completo` con `participante: null`, y el
`aprobar` responde `400` hasta que se asigne.

### Asignar la persona que faltó

```bash
POST /api/admin/instrumento-extracciones/{id}/asignar-responsable/
{ "usuario_id": 17 }

POST /api/admin/momento-extracciones/{id}/asignar-responsable/
{ "participante_id": 343 }
```

- **No vuelve a llamar a OpenAI**: usa la transcripción ya guardada. Es instantáneo.
- En instrumentos, solo funciona sobre una extracción en `sin_responsable` (`400` si no).
- En momentos, después de asignar hay que llamar a `aprobar/` como siempre.
- Solo acepta personas **que ya existen**. Si el responsable del documento no tiene cuenta, hay
  que crearla primero por la vía normal y después asignarla — a propósito no se crean cuentas
  desde un nombre leído por IA.
- `responsable_estado` **no cambia** al asignar: queda como registro de por qué hubo que hacerlo
  a mano. No lo usen para saber si ya está resuelto — para eso está `usuario`/`participante` y,
  en instrumentos, el `estado`.

---

## 3. Flujo sugerido para la pantalla de admin

1. Subir el archivo (sin preguntar la persona).
2. Polling del `estado`.
3. Al terminar:
   - instrumentos `completo` / momentos con `participante` → mostrar a quién quedó asignado, con
     `responsable_detectado` al lado para que se pueda verificar de un vistazo;
   - instrumentos `sin_responsable` / momentos con `participante: null` → bloque de "¿quién
     diligenció este documento?" con lo detectado visible y un selector de personas.
4. En momentos, `aprobar/` al final.

---

## 4. Checklist

- [ ] Leer `permite_carga_archivo` antes de pintar el botón de subir (no deducirlo).
- [ ] Validar extensión en cliente (`.pdf` / `.docx`).
- [ ] No mandar `usuario_id` en el endpoint de usuario: el dueño es quien sube.
- [ ] Polling de `estado` con `mis-cargas/`, y copy que diga "quedó en revisión", no "enviado".
- [ ] En admin, dejar de exigir la persona antes de subir.
- [ ] Manejar los 5 valores de `responsable_estado`, no solo `emparejado`.
- [ ] Mostrar `responsable_detectado` siempre que haya que elegir a mano.
- [ ] No auto-seleccionar en `ambiguo`.
- [ ] En instrumentos, tratar `sin_responsable` como un estado que **pide acción**, no como error.
- [ ] En momentos, recordar el `aprobar/` después de asignar.

---

## Nota sobre autenticación

| Quién                      | Header                                   |
|----------------------------|------------------------------------------|
| Admin/staff                | `Authorization: Token <hex de 40 chars>` |
| Usuario de instrumento     | `Authorization: Token <hex de 40 chars>` |
| Participante de jornada    | `Authorization: Participant <uuid>`      |

El usuario de instrumento es un `User` de Django con `is_staff=false`, y usa el mismo esquema
`Token` que el admin — lo que cambia es a qué endpoints llega, no el header. Se autentica en
`POST /api/instrumentos/login/`.
