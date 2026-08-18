# Historias de usuario

Formato: **Como** `<rol>` **quiero** `<acción>` **para** `<beneficio>`, con criterios de aceptación.

## Administrador

### HU-01 — Crear una jornada
Como administrador quiero crear una jornada indicando slug, nombre, descripción y fechas de inicio/fin, para publicar un nuevo evento.
- El slug es único; si ya existe, la API responde 400.
- `fecha_fin` no puede ser anterior a `fecha_inicio`.
- Solo un usuario `staff` autenticado (`POST /api/admin/login/`) puede crear jornadas (`POST /api/admin/jornadas/`).

### HU-02 — Editar o desactivar una jornada
Como administrador quiero editar los datos de una jornada o marcarla como inactiva, para corregir información o cerrar su inscripción.
- `PATCH /api/admin/jornadas/{slug}/` permite editar cualquier campo.
- Al poner `activa=false`, la jornada deja de aparecer en `GET /api/jornadas/` y no se pueden hacer nuevos registros de participantes.

### HU-03 — Crear momentos dentro de una jornada
Como administrador quiero crear momentos definiendo su orden, título, contexto y tipo (`individual` o `mesa`), para estructurar el recorrido del evento.
- `orden` es único dentro de la jornada.
- El tipo determina cómo se guardan las respuestas de sus preguntas (por participante o por mesa).

### HU-04 — Editar, reordenar o eliminar momentos
Como administrador quiero editar, reordenar o eliminar momentos de una jornada, para ajustar la agenda.
- Eliminar un momento elimina en cascada sus preguntas, opciones y respuestas asociadas.
- Cambiar `orden` falla con 400 si colisiona con otro momento de la misma jornada.

### HU-05 — Crear preguntas dentro de un momento
Como administrador quiero crear preguntas eligiendo tipo (`abierta`, `unica` o `multiple`), texto, orden y si son obligatorias, para recolectar información de los participantes.
- Preguntas `unica`/`multiple` requieren luego al menos una opción para ser respondibles.
- `orden` es único dentro del momento.

### HU-06 — Definir opciones de respuesta
Como administrador quiero definir las opciones de respuesta de una pregunta `unica` o `multiple`, para que los participantes elijan entre ellas.
- Cada opción tiene texto y orden únicos dentro de la pregunta.

### HU-07 — Editar o eliminar preguntas y opciones
Como administrador quiero editar o eliminar preguntas y sus opciones existentes, para corregir o actualizar el cuestionario.
- Eliminar una opción elimina su referencia de las respuestas ya enviadas que la incluían.

### HU-08 — Mover preguntas entre momentos
Como administrador quiero reasignar el `momento` (y por lo tanto la jornada) al que pertenece una pregunta, para reorganizar el contenido.
- `PATCH /api/admin/preguntas/{id}/` con un nuevo `momento` mueve la pregunta; sus respuestas previas quedan asociadas al nuevo momento.

### HU-09 — Autenticarse como administrador
Como administrador quiero autenticarme con usuario y contraseña y obtener un token, para usar la API de administración de forma segura.
- `POST /api/admin/login/` devuelve un token si las credenciales son válidas y el usuario es `staff`.
- Todos los endpoints `/api/admin/**` exigen ese token vía `Authorization: Token <token>` y usuario `is_staff=True`.

### HU-10 — Ver participantes inscritos
Como administrador quiero ver la lista de participantes inscritos en una jornada, para hacer seguimiento de la asistencia.
- `GET /api/admin/participantes/?jornada=<id>` lista nombre, apellido, correo, teléfono y fecha de registro.

### HU-11 — Ver/exportar respuestas
Como administrador quiero ver las respuestas registradas filtradas por momento o pregunta (incluidas las de mesa), para analizar los resultados.
- `GET /api/admin/respuestas/?momento=<id>` o `?pregunta=<id>` devuelve cada respuesta con su dueño (`participante` o `mesa`), texto libre y opciones elegidas.

## Participante / Usuario

### HU-12 — Ver jornadas disponibles
Como usuario quiero ver la lista de jornadas activas con su descripción y fechas, para elegir a cuál inscribirme.
- `GET /api/jornadas/` no requiere autenticación y solo muestra jornadas con `activa=true`.

### HU-13 — Registrarme en una jornada (momento 0)
Como usuario quiero registrarme en una jornada indicando mi correo institucional, nombre, apellido y teléfono, para inscribirme.
- `POST /api/jornadas/{slug}/registro/` crea el `Participante`.
- Si el correo ya está registrado en esa jornada, la API responde 400 sin crear un duplicado.
- Se genera automáticamente un `slug` a partir de nombre y apellido (con sufijo si hay colisión).

### HU-14 — Recibir un token de sesión
Como usuario quiero recibir un token de sesión al registrarme, para autenticar mis siguientes solicitudes sin usuario/contraseña.
- La respuesta de HU-13 incluye `token` (UUID), que el cliente debe reenviar como `Authorization: Participant <token>` en cada solicitud posterior.

### HU-15 — Listar los momentos de mi jornada
Como usuario ya registrado quiero consultar el índice de momentos de la jornada a la que pertenezco, para saber qué pasos debo recorrer.
- `GET /api/jornadas/{slug}/momentos/` requiere el token del paso anterior y devuelve `id`, `orden`, `título` y `tipo` de cada momento activo, ordenados por `orden`.

### HU-16 — Ver el detalle de un momento
Como usuario quiero consultar el contexto y las preguntas (con sus opciones) de un momento, para poder responderlo.
- `GET /api/jornadas/{slug}/momentos/{id}/` requiere token y devuelve 403 si el token no pertenece a esa jornada.

### HU-17 — Responder un momento individual
Como usuario quiero responder las preguntas de un momento `individual` (abiertas, únicas o de selección múltiple), para que mis respuestas queden guardadas asociadas a mí.
- `POST /api/jornadas/{slug}/momentos/{id}/respuestas/` guarda una `Respuesta` por pregunta asociada a mi `Participante`.

### HU-18 — Responder un momento de tipo "mesa"
Como usuario en un momento `mesa` quiero indicar el identificador de mi mesa y enviar una respuesta compartida, para que el resultado represente a todo el grupo.
- El body debe incluir `mesa` (texto libre); la API responde 400 si falta.
- Si otro participante de la misma mesa vuelve a responder, la respuesta se actualiza (no se duplica); se registra quién la envió por última vez (`registrado_por`) para trazabilidad.

### HU-19 — Corregir una respuesta ya enviada
Como usuario quiero poder reenviar mis respuestas a un momento antes de avanzar, para corregir errores.
- Un segundo `POST` al mismo momento actualiza (`update_or_create`) las respuestas existentes en vez de crear duplicados.

### HU-20 — Validación de preguntas obligatorias
Como usuario quiero que el sistema valide que las preguntas obligatorias tengan respuesta, para evitar enviar información incompleta.
- Si falta una pregunta obligatoria del momento en el envío, o su contenido no cumple el tipo (p. ej. `unica` con más de una opción, `abierta` vacía), la API responde 400 detallando el problema.

### HU-21 — Aislamiento entre jornadas y protección por token
Como usuario quiero que se rechacen intentos de acceder a momentos de una jornada distinta a la mía o sin token válido, para proteger mis datos y los de otros participantes.
- Sin header `Authorization` válido → 401.
- Con token de otra jornada → 403.
- Un `momento_id` que no pertenece a la jornada de la URL → 404.
