# Historias de usuario

Formato: **Como** `<rol>` **quiero** `<acción>` **para** `<beneficio>`, con criterios de aceptación.

## Administrador

### HU-01 — Crear una jornada
Como administrador quiero crear una jornada indicando slug, nombre, descripción y fechas de inicio/fin, para publicar un nuevo evento.
- El slug es único; si ya existe, la API responde 400.
- `fecha_fin` no puede ser anterior a `fecha_inicio`.
- Solo un usuario `staff` autenticado (`POST /api/admin/login/`) puede crear jornadas (`POST /api/admin/jornadas/`).
- `GET /api/admin/jornadas/` y `GET /api/admin/jornadas/{slug}/` listan/consultan las jornadas ya creadas, incluidas las inactivas (a diferencia del listado público, que solo muestra `activa=true`).

### HU-02 — Editar o desactivar una jornada
Como administrador quiero editar los datos de una jornada o marcarla como inactiva, para corregir información o cerrar su inscripción.
- `PATCH /api/admin/jornadas/{slug}/` permite editar cualquier campo.
- Al poner `activa=false`, la jornada **sigue apareciendo** en `GET /api/jornadas/` (con `activa: false` en la respuesta, para que el frontend la muestre marcada como desactivada) pero su detalle deja de ser accesible (`GET /api/jornadas/{slug}/` responde 404) y no se pueden hacer nuevos registros de participantes.
- `DELETE /api/admin/jornadas/{slug}/` la elimina por completo (en cascada, con sus momentos, preguntas, participantes y respuestas) — distinto de desactivarla; úsese con cuidado.

### HU-03 — Crear momentos dentro de una jornada
Como administrador quiero crear momentos definiendo su orden, título, contexto y tipo (`individual` o `mesa`), para estructurar el recorrido del evento.
- `POST /api/admin/momentos/`. `orden` es único dentro de la jornada.
- El tipo determina cómo se guardan las respuestas de sus preguntas (por participante o por mesa).
- `GET /api/admin/momentos/` (filtrable `?jornada=<id>`) y `GET /api/admin/momentos/{id}/` consultan los momentos ya creados.

### HU-04 — Editar, reordenar o eliminar momentos
Como administrador quiero editar, reordenar o eliminar momentos de una jornada, para ajustar la agenda.
- `PATCH /api/admin/momentos/{id}/` y `DELETE /api/admin/momentos/{id}/`.
- Eliminar un momento elimina en cascada sus preguntas, opciones y respuestas asociadas.
- Cambiar `orden` falla con 400 si colisiona con otro momento de la misma jornada.

### HU-05 — Crear preguntas dentro de un momento
Como administrador quiero crear preguntas eligiendo tipo (`abierta`, `unica` o `multiple`), texto, orden y si son obligatorias, para recolectar información de los participantes.
- `POST /api/admin/preguntas/`. Preguntas `unica`/`multiple` requieren luego al menos una opción para ser respondibles.
- `orden` es único dentro del momento.
- `GET /api/admin/preguntas/` (filtrable `?momento=<id>`) y `GET /api/admin/preguntas/{id}/` consultan las preguntas ya creadas.

### HU-06 — Definir opciones de respuesta
Como administrador quiero definir las opciones de respuesta de una pregunta `unica` o `multiple`, para que los participantes elijan entre ellas.
- `POST /api/admin/opciones/`. Cada opción tiene texto y orden únicos dentro de la pregunta.
- `GET /api/admin/opciones/` (filtrable `?pregunta=<id>`) y `GET /api/admin/opciones/{id}/` consultan las opciones ya creadas.

### HU-07 — Editar o eliminar preguntas y opciones
Como administrador quiero editar o eliminar preguntas y sus opciones existentes, para corregir o actualizar el cuestionario.
- `PATCH`/`DELETE /api/admin/preguntas/{id}/` y `PATCH`/`DELETE /api/admin/opciones/{id}/`.
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
- `GET /api/admin/participantes/{id}/` consulta el detalle de un participante puntual.

### HU-11 — Ver/exportar respuestas
Como administrador quiero ver las respuestas registradas filtradas por momento o pregunta (incluidas las de mesa), para analizar los resultados.
- `GET /api/admin/respuestas/?momento=<id>` o `?pregunta=<id>` devuelve cada respuesta con su dueño (`participante` o `mesa`), texto libre y opciones elegidas.
- `GET /api/admin/respuestas/{id}/` consulta el detalle de una respuesta puntual.

### HU-12 — Configurar plantillas de análisis con IA
Como administrador quiero crear y editar plantillas de prompt que definen el tono y el foco con el que el LLM redacta los reportes, para adaptar el análisis a distintos tipos de jornada sin tocar código.
- CRUD completo en `/api/admin/plantillas-analisis/` (`GET`, `POST`) y `/api/admin/plantillas-analisis/{id}/` (`GET`, `PATCH`, `DELETE`).
- Solo una plantilla puede quedar marcada `predeterminada=true` a la vez; marcar una nueva desmarca automáticamente la anterior.
- El texto de la plantilla (`prompt_sistema`) son instrucciones de estilo/foco — los datos reales (estadísticas y tópicos) se le entregan al modelo aparte, ya calculados, nunca los inventa.

### HU-13 — Generar un reporte de análisis jerárquico (jornada → momento → pregunta) con IA
Como administrador quiero pedir un análisis de una jornada completa, un momento individual o varios momentos combinados, para convertir las respuestas cualitativas en estadísticas cuantitativas y una síntesis narrativa a tres niveles.
- `POST /api/admin/reportes/` con `jornada` (obligatorio), `momentos` (opcional: vacío = jornada completa, uno = momento individual, varios = momentos combinados) y `plantilla` (opcional; si no se manda usa la marcada `predeterminada`).
- Responde de inmediato (`201`) con el reporte en estado `procesando` — el análisis corre en segundo plano, no bloquea el request.
- El análisis es **multiagente**: una llamada al LLM local por cada pregunta (redacta su `descripcion` a partir de sus estadísticas/tópicos ya calculados), una por cada momento (sintetiza las descripciones de sus preguntas) y una para la jornada completa (sintetiza las descripciones de sus momentos) — nunca una sola llamada con todo el detalle de la jornada encima, así el tamaño del contexto no depende de cuántas preguntas tenga la jornada.
- Para preguntas `abierta`: con muestra suficiente (≥8 respuestas) los `valores_caracteristicos` salen de BERTopic (determinístico); con muestra chica, el propio LLM extrae 3-5 frases características tomadas de las respuestas dadas (`metodo_valores: "llm"`) en vez de dejarlas vacías.
- El LLM nunca inventa cifras: cada agente solo ve los datos ya calculados de su propio nivel. Si una llamada puntual falla o tarda demasiado, esa pieza queda con un aviso corto — no tumba el resto del reporte.

### HU-14 — Consultar el estado y el resultado de un reporte
Como administrador quiero consultar el estado de un reporte y su resultado una vez listo, para hacer seguimiento del análisis sin bloquear mi sesión de trabajo.
- `GET /api/admin/reportes/` (filtrable `?jornada=<id>`) y `GET /api/admin/reportes/{id}/` devuelven `estado` (`pendiente`/`procesando`/`completo`/`error`), `analisis` y `texto_reporte`.
- `analisis` trae `participacion` (totales) y `momentos[]`, cada uno con `descripcion_general` y `preguntas[]` — cada pregunta con `tipo`, `tipo_grafica`, `descripcion`, `valores_caracteristicos` y `metodo_valores` (`"bertopic"`/`"llm"`/`"conteo"`). No repite el texto de preguntas/momentos — se referencian por id contra `/api/admin/preguntas/` y `/api/admin/momentos/`.
- `tipo_grafica` es `null` para preguntas `abierta`. Para `unica`/`multiple` es `"pastel"`, `"barras"` o `"radar"` — para estas, el propio agente de pregunta lo elige según hacia dónde le parece que se inclina el público entre las opciones (radar cuando hay 4+ opciones y conviene ver la forma general de la inclinación entre todas); si el modelo no responde con una elección válida, se usa un respaldo determinístico según la cantidad de opciones.
- `texto_reporte` es la síntesis del agente de jornada (el nivel más alto).
- `slug` se autogenera como `{jornada}-{alcance}-{fecha y hora local de Colombia}` (ej. `jornada-agil-2-jornada-20260818-2043`) para poder distinguir reportes a simple vista sin decodificar timestamps.
- `DELETE /api/admin/reportes/{id}/` elimina un reporte.

## Participante / Usuario

### HU-15 — Ver jornadas disponibles
Como usuario quiero ver la lista de todas las jornadas (activas e inactivas) con su descripción, fechas y estado, para elegir a cuál inscribirme y para que la interfaz pueda mostrar las cerradas como desactivadas en vez de simplemente ocultarlas.
- `GET /api/jornadas/` no requiere autenticación y devuelve **todas** las jornadas, incluida la key `activa` en cada una para que el cliente decida cómo representarla (p. ej. deshabilitar el botón de inscripción).

### HU-16 — Ver el detalle de una jornada
Como usuario quiero consultar el detalle de una jornada (nombre, descripción, fechas), para decidir si me inscribo antes de dar mis datos.
- `GET /api/jornadas/{slug}/` no requiere autenticación.
- Solo devuelve el detalle de jornadas **activas**; una jornada inactiva responde `404` aunque siga apareciendo en el listado de HU-15.

### HU-17 — Registrarme en una jornada (momento 0)
Como usuario quiero registrarme en una jornada indicando mi correo institucional, nombre, apellido y teléfono, para inscribirme.
- `POST /api/jornadas/{slug}/registro/` crea el `Participante`.
- Si el correo ya está registrado en esa jornada, la API responde 400 sin crear un duplicado.
- Se genera automáticamente un `slug` a partir de nombre y apellido (con sufijo si hay colisión).

### HU-18 — Recibir un token de sesión
Como usuario quiero recibir un token de sesión al registrarme, para autenticar mis siguientes solicitudes sin usuario/contraseña.
- La respuesta de HU-17 incluye `token` (UUID), que el cliente debe reenviar como `Authorization: Participant <token>` en cada solicitud posterior.

### HU-19 — Listar los momentos de mi jornada
Como usuario ya registrado quiero consultar el índice de momentos de la jornada a la que pertenezco, para saber qué pasos debo recorrer.
- `GET /api/jornadas/{slug}/momentos/` requiere el token del paso anterior y devuelve `id`, `orden`, `título`, `slug` (autogenerado del título, único dentro de la jornada) y `tipo` de cada momento activo, ordenados por `orden`.

### HU-20 — Ver el detalle de un momento
Como usuario quiero consultar el contexto y las preguntas (con sus opciones) de un momento, para poder responderlo.
- `GET /api/jornadas/{slug}/momentos/{id}/` requiere token y devuelve 403 si el token no pertenece a esa jornada.

### HU-21 — Responder un momento individual
Como usuario quiero responder las preguntas de un momento `individual` (abiertas, únicas o de selección múltiple), para que mis respuestas queden guardadas asociadas a mí.
- `POST /api/jornadas/{slug}/momentos/{id}/respuestas/` guarda una `Respuesta` por pregunta asociada a mi `Participante`.

### HU-22 — Responder un momento de tipo "mesa"
Como usuario en un momento `mesa` quiero indicar el identificador de mi mesa y enviar una respuesta compartida, para que el resultado represente a todo el grupo.
- El body debe incluir `mesa` (texto libre); la API responde 400 si falta.
- Si otro participante de la misma mesa vuelve a responder, la respuesta se actualiza (no se duplica); se registra quién la envió por última vez (`registrado_por`) para trazabilidad.

### HU-23 — Corregir una respuesta ya enviada
Como usuario quiero poder reenviar mis respuestas a un momento antes de avanzar, para corregir errores.
- Un segundo `POST` al mismo momento actualiza (`update_or_create`) las respuestas existentes en vez de crear duplicados.

### HU-24 — Validación de preguntas obligatorias
Como usuario quiero que el sistema valide que las preguntas obligatorias tengan respuesta, para evitar enviar información incompleta.
- Si falta una pregunta obligatoria del momento en el envío, o su contenido no cumple el tipo (p. ej. `unica` con más de una opción, `abierta` vacía), la API responde 400 detallando el problema.

### HU-25 — Aislamiento entre jornadas y protección por token
Como usuario quiero que se rechacen intentos de acceder a momentos de una jornada distinta a la mía o sin token válido, para proteger mis datos y los de otros participantes.
- Sin header `Authorization` válido → 401.
- Con token de otra jornada → 403.
- Un `momento_id` que no pertenece a la jornada de la URL → 404.
- Un token de participante usado contra un endpoint de admin (o viceversa) → 403 limpio, nunca error de servidor.

## Documentación técnica (pública, sin rol)

No son historias de usuario en sentido estricto, pero son endpoints que expone la API y conviene tener presentes:

- `GET /api/schema/` — esquema OpenAPI 3 en crudo.
- `GET /api/docs/` — Swagger UI interactivo.
- `GET /api/redoc/` — Redoc (documentación de solo lectura).
