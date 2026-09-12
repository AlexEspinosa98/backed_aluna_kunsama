# Historias de usuario — Instrumentos de reflexión (aplicación restringida por preregistro)

Formato: **Como** `<rol>` **quiero** `<acción>` **para** `<beneficio>`, con criterios de aceptación.
Complementa a [USER_STORIES.md](USER_STORIES.md) (jornadas/participantes) con un caso de uso
independiente: ver el contexto completo del módulo en `CLAUDE.md`.

A diferencia de `jornadas`/`participantes` (autorregistro libre por link), un **instrumento** es un
documento de reflexión —como `Reflexion_Lectura_Escritura_IA_UNIMAGDALENA.docx`, precargado con
`python manage.py cargar_instrumento_reflexion`— que solo pueden responder usuarios preregistrados
uno por uno por un encargado, y cuyas respuestas quedan pendientes de revisión (aceptar/rechazar)
antes de darse por válidas. El árbol de contenido (`Instrumento` → `SeccionInstrumento` →
`PreguntaInstrumento` → `OpcionPreguntaInstrumento`/`FilaMatrizInstrumento`/
`ColumnaMatrizInstrumento`) es 100% editable desde `/api/admin/**` — se puede agregar, quitar o
reordenar cualquier sección, pregunta, opción, fila o columna sin tocar código.

### HU-26 — Crear y editar un instrumento y su árbol de secciones/preguntas/matriz
Como administrador o encargado quiero crear un instrumento y construir libremente sus secciones y preguntas (incluida una matriz comparativa de filas × columnas), para modelar cualquier documento de reflexión sin depender de una estructura fija en el código.
- `POST /api/admin/instrumentos/` crea el instrumento (`slug` autogenerado desde `nombre`, igual que `Momento`).
- `POST /api/admin/instrumento-secciones/` — cada sección es `tipo=contenido` (texto de solo lectura, para narrativa) o `tipo=preguntas` (agrupa preguntas a diligenciar).
- `POST /api/admin/instrumento-preguntas/` — `tipo` es `abierta`, `unica`, `multiple` o `matriz`. Para `unica`/`multiple` se agregan opciones en `POST /api/admin/instrumento-opciones/`; para `matriz` se agregan filas en `POST /api/admin/instrumento-filas-matriz/` y columnas en `POST /api/admin/instrumento-columnas-matriz/`.
- Todos los niveles se pueden editar (`PATCH`) o eliminar (`DELETE`) independientemente — agregar o quitar una fila de la matriz, por ejemplo, no afecta las demás.
- Mismo scoping admin-completo/dependencia que `jornadas`: `Instrumento.encargados` (M2M) funciona igual que `Jornada.propietarios` — varios encargados pueden compartir un instrumento; un usuario de dependencia solo ve/crea contenido bajo instrumentos donde es encargado, y queda forzado a sí mismo como único encargado al crear uno.

<details><summary>Ejemplo — <code>POST /api/admin/instrumento-preguntas/</code> (pregunta tipo matriz)</summary>

Request:
```json
{
  "seccion": 4,
  "tipo": "matriz",
  "texto": "Compare el texto original, la reescritura humana y la versión con IA.",
  "orden": 1,
  "obligatoria": true
}
```

Response `201`:
```json
{
  "id": 10, "seccion": 4, "tipo": "matriz",
  "texto": "Compare el texto original, la reescritura humana y la versión con IA.",
  "orden": 1, "obligatoria": true, "activa": true,
  "opciones": [], "filas": [], "columnas": []
}
```
</details>

### HU-27 — Preregistrar usuarios que podrán responder un instrumento
Como encargado de un instrumento quiero dar de alta, uno por uno, a los usuarios autorizados a responderlo, para que solo ellos —y nadie más— puedan diligenciarlo.
- `POST /api/admin/instrumento-preregistrados/` con `instrumento` + (`usuario_id` de un usuario ya existente, **o** `username`/`password`/`email`/`first_name`/`last_name` para crear uno nuevo). El usuario creado queda con `is_staff=False`: nunca puede entrar a `/api/admin/**`, sin necesidad de ningún chequeo adicional (`IsAdminUser` ya lo bloquea).
- Un mismo usuario puede estar preregistrado en varios instrumentos (reutiliza sus credenciales).
- `GET /api/admin/instrumento-preregistrados/?instrumento={id}` lista los preregistrados con su `estado_visible` (`sin_enviar`/`pendiente`/`aceptado`/`rechazado`).
- `DELETE /api/admin/instrumento-preregistrados/{id}/` revoca el acceso a ese instrumento (no borra al usuario ni sus otros preregistros).

### HU-28 — Autenticarse como usuario preregistrado
Como usuario preregistrado quiero iniciar sesión con mi usuario y contraseña, para obtener un token con el que responder los instrumentos que me asignaron.
- `POST /api/instrumentos/login/` recibe `{"username", "password"}` y responde `{"token": "..."}` — es el mismo `obtain_auth_token` de `/api/admin/login/`, montado en una URL propia; el token se usa igual en ambos casos: header `Authorization: Token <token>`.
- Como no es `staff`, ese token nunca sirve contra `/api/admin/**` (403), y solo da acceso a los instrumentos donde el usuario tiene un `PreregistroInstrumento` — cualquier otro (o uno donde no está preregistrado) responde 403.

### HU-29 — Ver y responder el instrumento asignado
Como usuario preregistrado quiero ver el contenido completo del instrumento (narrativa, preguntas y matriz) y enviar mis respuestas, para completar la reflexión que me pidieron.
- `GET /api/instrumentos/` lista los instrumentos donde el usuario está preregistrado, con `estado_visible`.
- `GET /api/instrumentos/{slug}/` devuelve las secciones en orden (con sus preguntas/opciones/filas/columnas) y `mi_aplicacion` (`null` si nunca ha enviado nada, o `{estado_visible, comentario_revision, respuestas}` prellenado si ya envió — útil para corregir tras un rechazo).
- `POST /api/instrumentos/{slug}/respuestas/` envía **todas** las respuestas de una sola vez: cada pregunta obligatoria debe tener respuesta (en una `matriz`, obligatoria significa que **todas** las celdas fila×columna deben tener texto), o la API responde 400 con las preguntas faltantes.
- Reenviar mientras la aplicación no esté `aceptado` sobreescribe las respuestas y reinicia el estado a `pendiente` (así se modela corregir tras un `rechazado`). Si ya está `aceptado`, el envío se rechaza con 403.

<details><summary>Ejemplo — <code>POST /api/instrumentos/reflexion-lectura-escritura-ia/respuestas/</code></summary>

Request:
```json
{
  "respuestas": [
    { "pregunta": 5, "texto_libre": "Creo que la IA no reemplaza aprender a escribir." },
    { "pregunta": 10, "fila": 1, "columna": 1, "texto_libre": "El propósito era pedir una cita." },
    { "pregunta": 10, "fila": 1, "columna": 2, "texto_libre": "Quedó claro que pedía una valoración." }
  ]
}
```

Response `200`: la lista de `RespuestaInstrumento` guardadas.
</details>

### HU-30 — Revisar una aplicación enviada (aceptar/rechazar)
Como encargado quiero aceptar o rechazar cada aplicación que me envían, dejando un comentario, para controlar la calidad de lo diligenciado antes de darlo por válido.
- `GET /api/admin/instrumento-aplicaciones/?instrumento={id}` lista las aplicaciones (con sus respuestas) del instrumento.
- `POST /api/admin/instrumento-aplicaciones/{id}/revisar/` con `{"estado": "aceptado"|"rechazado", "comentario_revision": "..."}` — falla con 400 si la aplicación todavía no fue enviada (no hay nada que revisar).
- El preregistrado ve el resultado (incluido el comentario) en `mi_aplicacion` la próxima vez que consulte el instrumento (HU-29), y puede corregir y reenviar si fue `rechazado`.

### HU-31 — Ver el avance de un instrumento (dashboard)
Como encargado quiero ver cuántos preregistrados no han enviado nada, cuántos están pendientes de revisión y cuántos fueron aceptados/rechazados, para hacerle seguimiento a la aplicación del instrumento.
- `GET /api/admin/instrumentos/{slug}/dashboard/` responde el total de preregistrados, el conteo por estado (`sin_enviar`/`pendiente`/`aceptado`/`rechazado`), el `porcentaje_avance` (enviados sobre el total) y el listado de preregistrados con su estado individual.

### HU-32 — Descargar una aplicación diligenciada en Word (.docx)
Como encargado o como el propio preregistrado quiero descargar en formato Word lo que se respondió, para archivarlo o compartirlo fuera del sistema.
- `GET /api/admin/instrumento-aplicaciones/{id}/descargar/` (encargado) y `GET /api/instrumentos/{slug}/descargar/` (el propio preregistrado, sobre su propia aplicación) generan el `.docx` a partir de las respuestas ya guardadas — nunca de una IA — incluyendo la matriz como una tabla Word real.
- Solo puede descargarse una aplicación que ya fue enviada; si el preregistrado todavía no ha respondido, responde 404.

### HU-33 — Aislamiento entre preregistrados e instrumentos
Como usuario preregistrado quiero que solo pueda ver/responder los instrumentos donde fui explícitamente preregistrado, para que mis respuestas y las de los demás queden protegidas.
- Un usuario sin `PreregistroInstrumento` para un instrumento recibe 403 en cualquier endpoint bajo `/api/instrumentos/{slug}/...`, aunque su token sea válido.
- Un token de `Participante` (jornadas) usado contra `/api/instrumentos/**` responde 403 limpio, nunca error de servidor — mismo cuidado que ya existe entre `Participante` y `/api/admin/**` (HU-25 en [USER_STORIES.md](USER_STORIES.md)).
