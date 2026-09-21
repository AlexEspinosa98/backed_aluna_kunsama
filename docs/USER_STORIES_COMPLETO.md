# Historias de usuario — Aluna Kunsamu (completo)

Documento único que integra las historias de usuario de los 4 módulos del backend:
jornadas/participantes, instrumentos, transcripciones, y el caso de uso del diagnóstico
de articulación académica. Formato en todos: **Como** `<rol>` **quiero** `<acción>`
**para** `<beneficio>`, con criterios de aceptación.

---


## Administrador

### HU-01 — Crear una jornada
Como administrador quiero crear una jornada indicando slug, nombre, descripción y fechas de inicio/fin, para publicar un nuevo evento.
- El slug es único; si ya existe, la API responde 400.
- `fecha_fin` no puede ser anterior a `fecha_inicio`.
- Solo un usuario `staff` autenticado (`POST /api/admin/login/`) puede crear jornadas (`POST /api/admin/jornadas/`).
- `GET /api/admin/jornadas/` y `GET /api/admin/jornadas/{slug}/` listan/consultan las jornadas ya creadas, incluidas las inactivas (a diferencia del listado público, que solo muestra `activa=true`).

<details><summary>Ejemplo — <code>POST /api/admin/jornadas/</code></summary>

Request:
```json
{
  "slug": "jornada-agil-2",
  "nombre": "Jornada Ágil 2 — Actualización del Sistema de Investigación",
  "descripcion": "Ética, innovación y emprendimiento para transformar desde el conocimiento.",
  "fecha_inicio": "2026-08-20",
  "fecha_fin": "2026-08-20",
  "activa": true
}
```

Response `201`:
```json
{
  "id": 4,
  "slug": "jornada-agil-2",
  "nombre": "Jornada Ágil 2 — Actualización del Sistema de Investigación",
  "descripcion": "Ética, innovación y emprendimiento para transformar desde el conocimiento.",
  "fecha_inicio": "2026-08-20",
  "fecha_fin": "2026-08-20",
  "activa": true,
  "creado_en": "2026-08-18T10:02:11.204Z"
}
```
</details>

### HU-01b — Jornadas por dependencia (rol de usuario)
Como administrador quiero poder dar de alta usuarios de "dependencia" que solo vean, creen y editen sus propias jornadas, para delegar la operación de una jornada sin darle acceso a las de otras dependencias.
- Hay dos roles bajo `/api/admin/**`: **admin completo** (ve/gestiona todo) y **dependencia** (solo lo suyo). Una cuenta sin fila en `PerfilUsuario` — todas las que existían antes de este rol — se trata como admin completo, así que nada de lo que ya existía cambió de comportamiento.
- `Jornada.propietarios` (M2M, no un solo dueño) es quien scopea el acceso — distinto de `creada_por`, que es solo auditoría de quién la creó. **Varios usuarios de dependencia pueden compartir una misma jornada** (ej. dos personas de la misma área viéndola/editándola ambas). Al crear una jornada, un usuario de dependencia queda como único integrante de `propietarios` automáticamente — no puede asignársela a otro usuario aunque lo intente en el body, ni agregarse a una jornada ajena. Un admin completo sí puede fijar/reasignar la lista completa de `propietarios` en cualquier momento (`PATCH /api/admin/jornadas/{slug}/` con `{"propietarios": [id, id, ...]}`), incluida una jornada sin ningún dueño (`propietarios: []`, visible solo para admins completos).
- El scoping por dependencia aplica en cascada a todo lo que cuelga de la jornada: `momentos`, `preguntas`, `opciones`, `participantes`, `respuestas`, `reportes`, `analisis-momento-ia` y `analisis-jornada-ia` (HU-14g) — un usuario de dependencia ni ve ni puede crear nada bajo una jornada que no es suya (`403` al crear, la jornada ajena simplemente no aparece al listar/consultar, o `404` si se pide por id directo).
- Las plantillas de análisis (`/api/admin/plantillas-analisis/`) son una excepción: son prompts globales, no de una jornada — dependencia puede leerlas (para elegir cuál usar al pedir un reporte) pero solo un admin completo puede crearlas/editarlas/borrarlas.

### HU-02 — Editar o desactivar una jornada
Como administrador quiero editar los datos de una jornada o marcarla como inactiva, para corregir información o cerrar su inscripción.
- `PATCH /api/admin/jornadas/{slug}/` permite editar cualquier campo.
- Al poner `activa=false`, la jornada **sigue apareciendo** en `GET /api/jornadas/` (con `activa: false` en la respuesta, para que el frontend la muestre marcada como desactivada) pero su detalle deja de ser accesible (`GET /api/jornadas/{slug}/` responde 404) y no se pueden hacer nuevos registros de participantes.
- `DELETE /api/admin/jornadas/{slug}/` la elimina por completo (en cascada, con sus momentos, preguntas, participantes y respuestas) — distinto de desactivarla; úsese con cuidado.

<details><summary>Ejemplo — <code>PATCH /api/admin/jornadas/jornada-agil-2/</code></summary>

Request:
```json
{ "activa": false }
```

Response `200`:
```json
{
  "id": 4,
  "slug": "jornada-agil-2",
  "nombre": "Jornada Ágil 2 — Actualización del Sistema de Investigación",
  "descripcion": "Ética, innovación y emprendimiento para transformar desde el conocimiento.",
  "fecha_inicio": "2026-08-20",
  "fecha_fin": "2026-08-20",
  "activa": false,
  "creado_en": "2026-08-18T10:02:11.204Z"
}
```
</details>

### HU-03 — Crear momentos dentro de una jornada
Como administrador quiero crear momentos definiendo su orden, título, contexto y tipo (`individual` o `mesa`), para estructurar el recorrido del evento.
- `POST /api/admin/momentos/`. `orden` es único dentro de la jornada.
- El tipo determina cómo se guardan las respuestas de sus preguntas (por participante o por mesa).
- `GET /api/admin/momentos/` (filtrable `?jornada=<id>`) y `GET /api/admin/momentos/{id}/` consultan los momentos ya creados.
- `categorias_semilla` (opcional, lista de strings, ej. `["principios", "riesgos y dilemas", ...]`) predefine las categorías temáticas de este momento para el análisis con IA (HU-13) — se repite la misma lista en los momentos que comparten un eje temático (ej. individual + mesa + dinámica de un mismo bloque). Si se deja vacía, los temas se descubren automáticamente sin partir de una lista fija.
- `mesas_permitidas` (opcional, solo tiene efecto en momentos tipo `mesa`): lista de números de mesa que pueden ver/participar en este momento COMPLETO — pensado para dinámicas tipo "Café del Mundo" donde cada mesa física trabaja un momento/tema distinto, a diferencia de `Pregunta.mesas_permitidas` (HU-05), que restringe una pregunta puntual dentro de un momento compartido por todas las mesas. Vacía (por defecto) = visible para todas las mesas. Una misma mesa puede aparecer en varios momentos si un tema se reparte entre varias mesas físicas.

<details><summary>Ejemplo — <code>POST /api/admin/momentos/</code></summary>

Request:
```json
{
  "jornada": 4,
  "orden": 1,
  "titulo": "Momento 1 — EIBIC: reflexión individual",
  "tipo": "individual",
  "contexto": "Construir colectivamente los lineamientos estratégicos de EIBIC. Responde individualmente antes de la deliberación en mesa.",
  "categorias_semilla": []
}
```

Response `201`:
```json
{
  "id": 3,
  "jornada": 4,
  "orden": 1,
  "titulo": "Momento 1 — EIBIC: reflexión individual",
  "slug": "momento-1-eibic-reflexion-individual",
  "tipo": "individual",
  "contexto": "Construir colectivamente los lineamientos estratégicos de EIBIC. Responde individualmente antes de la deliberación en mesa.",
  "categorias_semilla": [],
  "activo": true
}
```
</details>

### HU-04 — Editar, reordenar o eliminar momentos
Como administrador quiero editar, reordenar o eliminar momentos de una jornada, para ajustar la agenda.
- `PATCH /api/admin/momentos/{id}/` y `DELETE /api/admin/momentos/{id}/`.
- Eliminar un momento elimina en cascada sus preguntas, opciones y respuestas asociadas.
- Cambiar `orden` falla con 400 si colisiona con otro momento de la misma jornada.

<details><summary>Ejemplo — <code>PATCH /api/admin/momentos/3/</code></summary>

Request:
```json
{ "categorias_semilla": ["principios", "riesgos y dilemas", "conflicto de interés"] }
```

Response `200`: mismo cuerpo que HU-03 con `categorias_semilla` actualizado.

Error (`orden` en colisión), `400`:
```json
{ "orden": ["Ya existe un momento con este orden en esta jornada."] }
```
</details>

### HU-05 — Crear preguntas dentro de un momento
Como administrador quiero crear preguntas eligiendo tipo (`abierta`, `unica` o `multiple`), texto, orden y si son obligatorias, para recolectar información de los participantes.
- `POST /api/admin/preguntas/`. Preguntas `unica`/`multiple` requieren luego al menos una opción para ser respondibles.
- `orden` es único dentro del momento.
- `GET /api/admin/preguntas/` (filtrable `?momento=<id>`) y `GET /api/admin/preguntas/{id}/` consultan las preguntas ya creadas.
- `mesas_permitidas` (opcional, solo tiene efecto en momentos tipo `mesa`): lista de números de mesa que pueden ver/responder esa pregunta puntual — vacía (por defecto) significa visible para todas las mesas. Una mesa que no está en la lista no ve la pregunta en `GET .../momentos/{id}/` (HU-20) y, si igual intenta responderla directo contra la API, se rechaza con `400` (HU-22).

<details><summary>Ejemplo — <code>POST /api/admin/preguntas/</code></summary>

Request:
```json
{
  "momento": 3,
  "orden": 1,
  "tipo": "abierta",
  "texto": "¿Qué principio ético debería ser irrenunciable en toda actividad de investigación en UNIMAGDALENA?",
  "obligatoria": true
}
```

Response `201`:
```json
{
  "id": 4,
  "momento": 3,
  "tipo": "abierta",
  "texto": "¿Qué principio ético debería ser irrenunciable en toda actividad de investigación en UNIMAGDALENA?",
  "orden": 1,
  "obligatoria": true,
  "activa": true,
  "opciones": []
}
```
</details>

### HU-06 — Definir opciones de respuesta
Como administrador quiero definir las opciones de respuesta de una pregunta `unica` o `multiple`, para que los participantes elijan entre ellas.
- `POST /api/admin/opciones/`. Cada opción tiene texto y orden únicos dentro de la pregunta.
- `GET /api/admin/opciones/` (filtrable `?pregunta=<id>`) y `GET /api/admin/opciones/{id}/` consultan las opciones ya creadas.

<details><summary>Ejemplo — <code>POST /api/admin/opciones/</code></summary>

Request:
```json
{ "pregunta": 20, "texto": "Verde — capacidad o fortaleza que debe consolidarse", "orden": 1 }
```

Response `201`:
```json
{ "id": 4, "pregunta": 20, "texto": "Verde — capacidad o fortaleza que debe consolidarse", "orden": 1 }
```
</details>

### HU-07 — Editar o eliminar preguntas y opciones
Como administrador quiero editar o eliminar preguntas y sus opciones existentes, para corregir o actualizar el cuestionario.
- `PATCH`/`DELETE /api/admin/preguntas/{id}/` y `PATCH`/`DELETE /api/admin/opciones/{id}/`.
- Eliminar una opción elimina su referencia de las respuestas ya enviadas que la incluían.

<details><summary>Ejemplo — <code>PATCH /api/admin/preguntas/4/</code></summary>

Request:
```json
{ "obligatoria": false }
```

Response `200`: mismo cuerpo que HU-05 con `obligatoria: false`. `DELETE` responde `204` sin cuerpo.
</details>

### HU-08 — Mover preguntas entre momentos
Como administrador quiero reasignar el `momento` (y por lo tanto la jornada) al que pertenece una pregunta, para reorganizar el contenido.
- `PATCH /api/admin/preguntas/{id}/` con un nuevo `momento` mueve la pregunta; sus respuestas previas quedan asociadas al nuevo momento.

<details><summary>Ejemplo — <code>PATCH /api/admin/preguntas/4/</code></summary>

Request:
```json
{ "momento": 5, "orden": 1 }
```

Response `200`: mismo cuerpo que HU-05 con `momento: 5`.
</details>

### HU-09 — Autenticarse como administrador
Como administrador quiero autenticarme con usuario y contraseña y obtener un token, para usar la API de administración de forma segura.
- `POST /api/admin/login/` devuelve un token si las credenciales son válidas y el usuario es `staff`.
- Todos los endpoints `/api/admin/**` exigen ese token vía `Authorization: Token <token>` y usuario `is_staff=True`.

<details><summary>Ejemplo — <code>POST /api/admin/login/</code></summary>

Request:
```json
{ "username": "admin_rectoria", "password": "••••••••" }
```

Response `200`:
```json
{ "token": "f45736154c2d7245abc8b68ad2c4bd484fea9172", "user_id": 3, "is_staff": true }
```

Error (credenciales inválidas o usuario no `staff`), `400`:
```json
{ "detail": "No se pudo iniciar sesión con las credenciales dadas." }
```
</details>

### HU-09b — Gestionar usuarios admin/dependencia
Como administrador completo quiero crear, editar y consultar usuarios de dependencia (y ver de un vistazo qué jornadas e instrumentos tiene cada uno), para delegar jornadas e instrumentos sin pasar por Django admin.
- CRUD en `/api/admin/usuarios/` — exclusivo de admin completo (`403` para dependencia). Es el mismo endpoint, el mismo rol y el mismo usuario para ambos módulos: no hay un CRUD de usuarios distinto para instrumentos — un usuario de dependencia puede quedar a cargo de varias jornadas y de varios instrumentos a la vez, sin límite y de forma independiente (ver [USER_STORIES_INSTRUMENTOS.md](USER_STORIES_INSTRUMENTOS.md) HU-26).
- `POST` crea el usuario (`is_staff=true` automático) con `username`, `password` y `rol` (`"admin"` o `"dependencia"`, por defecto `"dependencia"`). Asignarlo a una jornada o a un instrumento puntual es un segundo paso, por separado: `PATCH /api/admin/jornadas/{slug}/` con `propietarios` o `PATCH /api/admin/instrumentos/{slug}/` con `encargados`.
- `GET /api/admin/usuarios/{id}/` incluye `jornadas_propias` (id/slug/nombre/activa) e `instrumentos_a_cargo` (id/slug/nombre/activo) — todo lo que ese usuario tiene asignado en ambos módulos, sin tener que cruzarlo a mano contra `/api/admin/jornadas/` o `/api/admin/instrumentos/`.

<details><summary>Ejemplo — <code>POST /api/admin/usuarios/</code></summary>

Request:
```json
{ "username": "facultad-ingenieria", "password": "una-clave-segura", "rol": "dependencia" }
```

Response `201`:
```json
{
  "id": 7,
  "username": "facultad-ingenieria",
  "email": "",
  "first_name": "",
  "last_name": "",
  "is_active": true,
  "rol": "dependencia",
  "jornadas_propias": [],
  "instrumentos_a_cargo": [],
  "date_joined": "2026-09-04T22:10:00Z"
}
```
</details>

### HU-10 — Ver participantes inscritos
Como administrador quiero ver la lista de participantes inscritos en una jornada, para hacer seguimiento de la asistencia.
- `GET /api/admin/participantes/?jornada=<id>` lista nombre, apellido, correo, teléfono, `rol`, `mesa`, `es_vocero` y fecha de registro.
- `GET /api/admin/participantes/{id}/` consulta el detalle de un participante puntual.

<details><summary>Ejemplo — <code>GET /api/admin/participantes/?jornada=4</code></summary>

Response `200`:
```json
[
  {
    "id": 13,
    "jornada": "jornada-agil-2",
    "correo_institucional": "camila.gomez@unimagdalena.edu.co",
    "nombre": "Camila",
    "apellido": "Gómez",
    "telefono": "3000000000",
    "rol": "estudiante",
    "mesa": 3,
    "es_vocero": true,
    "slug": "camila-gomez",
    "token": "b058878f-5797-40ac-ab56-9779902ab300",
    "creado_en": "2026-08-18T19:11:58.251917-05:00"
  }
]
```
</details>

### HU-10b — Corregir la mesa o el vocero de un participante
Como administrador quiero poder cambiar la mesa de un participante o quitarle/asignarle el rol de vocero después de que se registró, para corregir errores o reorganizar mesas sin tener que re-registrar a nadie.
- `PATCH /api/admin/participantes/{id}/` acepta ÚNICAMENTE `mesa` y `es_vocero` — nunca los datos personales del registro (correo, nombre, teléfono), que no son editables por esta vía.
- El cambio aplica de inmediato: si se le quita `es_vocero` a alguien, sus próximos intentos de enviar respuestas a un momento tipo mesa responden `403` (ver HU-22); si se le asigna a otro participante, ese participante puede empezar a responder de inmediato.
- Quitar `es_vocero` a alguien **no borra** las respuestas de mesa que ya envió — quedan asociadas a la mesa, no a la persona (ver HU-22).

<details><summary>Ejemplo — <code>PATCH /api/admin/participantes/13/</code></summary>

Request (mover a otra mesa):
```json
{ "mesa": 5 }
```

Request (quitar el rol de vocero):
```json
{ "es_vocero": false }
```

Response `200`:
```json
{ "id": 13, "mesa": 5, "es_vocero": false }
```
</details>

### HU-10c — Eliminar un participante
Como administrador quiero poder eliminar por completo un participante (ej. un duplicado, un correo mal escrito, un registro de prueba), para limpiar el listado sin dejar basura que distorsione las estadísticas (HU-11b/HU-11c) ni el conteo de mesas (HU-11d).
- `DELETE /api/admin/participantes/{id}/` — elimina el registro y responde `204` sin cuerpo.
- Sus respuestas individuales (momentos tipo `individual`) se eliminan en cascada junto con él.
- Sus respuestas de mesa (momentos tipo `mesa`) **NO** se eliminan — quedan asociadas al número de mesa, no a la persona (mismo principio que HU-10b/HU-22). Si el participante eliminado era el vocero de su mesa, esa mesa queda sin vocero hasta que un admin asigne a otro (HU-10b) — no podrá enviar respuestas de mesa mientras tanto.
- `404` si el `id` no existe.

<details><summary>Ejemplo — <code>DELETE /api/admin/participantes/188/</code></summary>

Response `204`: sin cuerpo.

Error (no existe), `404`:
```json
{ "detail": "No Participante matches the given query." }
```
</details>

### HU-11 — Ver/exportar respuestas
Como administrador quiero ver las respuestas registradas filtradas por momento o pregunta (incluidas las de mesa), para analizar los resultados.
- `GET /api/admin/respuestas/?momento=<id>` o `?pregunta=<id>` devuelve cada respuesta con su dueño (`participante` o `mesa`), texto libre y opciones elegidas.
- `GET /api/admin/respuestas/{id}/` consulta el detalle de una respuesta puntual.

<details><summary>Ejemplo — <code>GET /api/admin/respuestas/?pregunta=38</code></summary>

Response `200`:
```json
[
  {
    "id": 501,
    "pregunta": 38,
    "participante": 13,
    "mesa": null,
    "texto_libre": "",
    "opciones": [16],
    "actualizado_en": "2026-08-19T21:15:03.112Z"
  }
]
```
</details>

### HU-11b — Ver estadísticas reales por pregunta, sin IA
Como administrador quiero ver de un vistazo cuántas respuestas tiene cada pregunta de un momento o de toda la jornada (y, para preguntas de opción, el conteo por opción), para revisar los números crudos sin tener que generar un reporte completo con IA.
- `GET /api/admin/estadisticas-preguntas/?momento=<id>` o `?jornada=<id>` — al menos uno de los dos es obligatorio; con `jornada` trae las preguntas de todos sus momentos.
- Responde en la misma petición (síncrono) — son solo conteos agregados de la base de datos, sin ninguna llamada a un modelo de IA (ni local ni externo).
- Es la MISMA función (`_estadisticas_pregunta`) que usan por debajo tanto el pipeline local (HU-13) como el análisis vía OpenAI (HU-14d) para sus cifras — nunca puede mostrar un número distinto al que terminan citando esos reportes.
- Para preguntas `abierta`: `estadisticas` trae `total_respuestas` y `respuestas_no_vacias`. Para `unica`/`multiple`: `total_respuestas` y `conteo_opciones` (una entrada por opción con su conteo real).

<details><summary>Ejemplo — <code>GET /api/admin/estadisticas-preguntas/?momento=3</code></summary>

Response `200`:
```json
[
  {
    "pregunta_id": 38,
    "momento_id": 3,
    "texto": "Reconocer que la ética debe acompañar investigación, creación, innovación, emprendimiento, transferencia y apropiación del conocimiento.",
    "tipo": "unica",
    "obligatoria": true,
    "estadisticas": {
      "total_respuestas": 25,
      "conteo_opciones": [
        {"opcion_id": 16, "texto": "De acuerdo", "conteo": 20},
        {"opcion_id": 17, "texto": "Requiere ajuste", "conteo": 5},
        {"opcion_id": 18, "texto": "No debería incorporarse", "conteo": 0}
      ]
    }
  },
  {
    "pregunta_id": 45,
    "momento_id": 3,
    "texto": "Cuando una investigación o proyecto trabaja con comunidades o con conocimientos propios del territorio, ¿qué prácticas mínimas debería exigir la Universidad...?",
    "tipo": "abierta",
    "obligatoria": true,
    "estadisticas": { "total_respuestas": 25, "respuestas_no_vacias": 25 }
  }
]
```

Error (falta el filtro), `400`:
```json
{ "detail": "Debes indicar ?momento=<id> o ?jornada=<id>." }
```
</details>

### HU-11c — Ver cómo va toda la jornada: por momento, por participante y por pregunta
Como administrador quiero ver el avance completo de una jornada en un solo llamado — un reporte agregado por cada momento (cuántas preguntas tiene, cuántas son obligatorias, cuántos ya lo completaron) y, además, el detalle de cada participante pregunta por pregunta — para saber exactamente cómo va cada momento y a quién le falta qué, sin tener que cruzar manualmente HU-11b contra el registro de participantes.
- `GET /api/admin/progreso-participantes/?jornada=<id>` — `jornada` es obligatorio.
- Opcional `?solo_completados=true` para que `participantes` solo traiga a quienes ya terminaron el instrumento completo.
- Responde en la misma petición (síncrono) — son conteos y comparaciones de sets agregados de la base de datos, igual que HU-11b; sin IA.
- El completado (`completado`, `completado_instrumento`) se cuenta solo sobre preguntas `obligatoria: true` y `activa: true` — las opcionales no bloquean el estado, pero sí aparecen listadas en `preguntas` y cuentan en `total_preguntas`/`respondidas_total`.
- Para momentos `tipo: "mesa"` el avance es el de la MESA, no de la persona: como solo el vocero envía (ver HU-22), todos los integrantes de una misma mesa comparten el mismo estado en esos momentos (incluida la lista `preguntas`, pregunta por pregunta). Un participante sin mesa asignada siempre muestra todo sin responder en los momentos de mesa.
- La respuesta trae dos bloques:
  - `resumen_momentos`: un reporte por momento, agregado para TODA la jornada — `total_preguntas` (todas, obligatorias u opcionales), `total_obligatorias`, `universo` (participantes para momentos individuales, mesas registradas para momentos de mesa), `completaron` y `porcentaje_completado`.
  - `participantes`: el detalle persona por persona; dentro de cada `momentos[]`, el array `preguntas[]` trae CADA pregunta del momento con `respondida: true/false` — no solo un conteo.

<details><summary>Ejemplo — <code>GET /api/admin/progreso-participantes/?jornada=5</code></summary>

Response `200`:
```json
{
  "jornada_id": 5,
  "resumen_momentos": [
    {
      "momento_id": 3,
      "titulo": "Reflexión individual sobre ética",
      "tipo": "individual",
      "total_preguntas": 5,
      "total_obligatorias": 4,
      "universo": 25,
      "completaron": 23,
      "porcentaje_completado": 92
    },
    {
      "momento_id": 4,
      "titulo": "Consenso de mesa — EIBIC",
      "tipo": "mesa",
      "total_preguntas": 6,
      "total_obligatorias": 5,
      "universo": 6,
      "completaron": 1,
      "porcentaje_completado": 17
    }
  ],
  "participantes": [
    {
      "participante_id": 12,
      "nombre": "Ricardo",
      "apellido": "Pupo",
      "correo_institucional": "rpupo@unimagdalena.edu.co",
      "rol": "estudiante",
      "mesa": 22,
      "es_vocero": true,
      "momentos": [
        {
          "momento_id": 3,
          "titulo": "Reflexión individual sobre ética",
          "tipo": "individual",
          "total_preguntas": 5,
          "total_obligatorias": 4,
          "respondidas_obligatorias": 4,
          "respondidas_total": 5,
          "completado": true,
          "preguntas": [
            { "pregunta_id": 38, "texto": "Reconocer que la ética debe acompañar investigación...", "tipo": "unica", "obligatoria": true, "respondida": true },
            { "pregunta_id": 39, "texto": "¿Algo más que quieras agregar? (opcional)", "tipo": "abierta", "obligatoria": false, "respondida": true }
          ]
        },
        {
          "momento_id": 4,
          "titulo": "Consenso de mesa — EIBIC",
          "tipo": "mesa",
          "total_preguntas": 6,
          "total_obligatorias": 5,
          "respondidas_obligatorias": 2,
          "respondidas_total": 2,
          "completado": false,
          "preguntas": [
            { "pregunta_id": 50, "texto": "¿La mesa está de acuerdo con el lineamiento propuesto?", "tipo": "unica", "obligatoria": true, "respondida": true },
            { "pregunta_id": 51, "texto": "¿Qué ajuste propone la mesa?", "tipo": "abierta", "obligatoria": true, "respondida": false }
          ]
        }
      ],
      "total_preguntas": 11,
      "total_obligatorias": 9,
      "total_respondidas_total": 7,
      "total_respondidas_obligatorias": 6,
      "completado_instrumento": false
    }
  ]
}
```
Nótese que en el momento 4 (tipo mesa) el estado de `preguntas` es el de la mesa 22 entera — si otro participante de esa misma mesa apareciera en `participantes`, tendría exactamente el mismo array de `preguntas` en ese momento, aunque solo Ricardo (el vocero) pueda enviarlo.

Error (falta el filtro), `400`:
```json
{ "detail": "Debes indicar ?jornada=<id>." }
```

Error (jornada sin momentos), `404`:
```json
{ "detail": "Esta jornada no tiene momentos." }
```
</details>

### HU-11d — Ver cuántas mesas hay y quién está en cada una
Como administrador quiero ver de un vistazo cuántas mesas quedaron formadas en una jornada y qué participantes (y quién es el vocero) hay en cada una, para revisar que la distribución quedó bien antes de que arranquen los momentos grupales.
- `GET /api/admin/mesas/?jornada=<id>` — `jornada` es obligatorio.
- Agrupa a todos los participantes de la jornada por su campo `mesa` (fijado en el registro, ver HU-10/HU-17, editable por admin vía HU-10b). Dentro de cada mesa, `vocero` es el participante con `es_vocero: true` de esa mesa (o `null` si todavía no tiene) — nunca hay más de uno, porque el registro y el PATCH de admin lo impiden (ver HU-17/HU-10b).
- Los participantes sin mesa asignada (`mesa: null`) van aparte en `sin_mesa_asignada`, no cuentan como una "mesa" más.

<details><summary>Ejemplo — <code>GET /api/admin/mesas/?jornada=5</code></summary>

Response `200`:
```json
{
  "jornada_id": 5,
  "total_mesas": 2,
  "mesas": [
    {
      "mesa": 12,
      "total_participantes": 3,
      "vocero": {
        "participante_id": 8,
        "nombre": "Laura",
        "apellido": "Gómez",
        "correo_institucional": "lgomez@unimagdalena.edu.co",
        "rol": "docente",
        "es_vocero": true
      },
      "participantes": [
        { "participante_id": 8, "nombre": "Laura", "apellido": "Gómez", "correo_institucional": "lgomez@unimagdalena.edu.co", "rol": "docente", "es_vocero": true },
        { "participante_id": 9, "nombre": "Andrés", "apellido": "Pérez", "correo_institucional": "aperez@unimagdalena.edu.co", "rol": "estudiante", "es_vocero": false },
        { "participante_id": 10, "nombre": "Camila", "apellido": "Ruiz", "correo_institucional": "cruiz@unimagdalena.edu.co", "rol": "estudiante", "es_vocero": false }
      ]
    },
    {
      "mesa": 22,
      "total_participantes": 2,
      "vocero": {
        "participante_id": 12,
        "nombre": "Ricardo",
        "apellido": "Pupo",
        "correo_institucional": "rpupo@unimagdalena.edu.co",
        "rol": "estudiante",
        "es_vocero": true
      },
      "participantes": [
        { "participante_id": 12, "nombre": "Ricardo", "apellido": "Pupo", "correo_institucional": "rpupo@unimagdalena.edu.co", "rol": "estudiante", "es_vocero": true },
        { "participante_id": 13, "nombre": "Vanesa", "apellido": "Martínez", "correo_institucional": "vmartinez@unimagdalena.edu.co", "rol": "directivo", "es_vocero": false }
      ]
    }
  ],
  "sin_mesa_asignada": [
    { "participante_id": 14, "nombre": "Jorge", "apellido": "Díaz", "correo_institucional": "jdiaz@unimagdalena.edu.co", "rol": "estudiante", "es_vocero": false }
  ]
}
```

Error (falta el filtro), `400`:
```json
{ "detail": "Debes indicar ?jornada=<id>." }
```
</details>

### HU-11e — Descargar el reporte completo de la jornada en Excel, una hoja por pregunta
Como administrador quiero descargar un solo archivo Excel con todo el resultado de la jornada — un resumen general, un índice, el listado de participantes y de mesas, y una hoja por cada pregunta con su caracterización y el detalle real de cada respuesta — para poder revisarlo, filtrarlo o compartirlo fuera del sistema sin tener que armar nada a mano.
- `GET /api/admin/reporte-excel-por-pregunta/?jornada=<id>` — `jornada` es obligatorio. Responde el archivo directo (`Content-Type` de Excel, `Content-Disposition: attachment`), no un JSON — se descarga al hacer la petición.
- 100% determinístico, **sin IA**: reusa la misma función (`_estadisticas_pregunta`) que ya usan HU-11b, el pipeline local (HU-13) y el análisis vía OpenAI (HU-14d), así que las cifras nunca pueden desalinearse de las que se ven en esos otros lugares.
- Los conteos y porcentajes de cada hoja son **fórmulas de Excel reales** (`COUNTIF`, `SUM`, `IF`), no números pegados — si se edita una respuesta directamente en la hoja, las cifras se recalculan solas.
- **No filtra por `momento.activo`**: funciona igual con la jornada en curso o ya cerrada (todos sus momentos desactivados) — es justo ahí cuando más se necesita el reporte final.
- Estructura del archivo:
  - **Resumen**: totales generales (participantes, mesas, momentos, preguntas), caracterización de participantes por rol, y una tabla de los momentos de la jornada.
  - **Índice**: una fila por cada pregunta de la jornada, con hipervínculo directo a su hoja.
  - **Participantes** y **Mesas**: el listado completo de cada uno.
  - **Una hoja por pregunta** (nombrada `M{orden momento}-P{orden pregunta} {inicio del texto}`): título con el momento y la posición de la pregunta, bloque de **Caracterización** (para preguntas de opción: conteo y % por opción; para abiertas: total y respuestas no vacías; en ambos casos, cobertura sobre el universo esperado) y bloque de **Respuestas registradas** con cada participante (o cada mesa, si el momento es tipo `mesa`) y su respuesta real, incluyendo a quienes no respondieron (resaltados).
- Este mismo formato es el disponible también agrupado por momento — ver HU-11f.

<details><summary>Ejemplo — <code>GET /api/admin/reporte-excel-por-pregunta/?jornada=4</code></summary>

Response `200`, headers:
```
Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
Content-Disposition: attachment; filename="reporte-jornada-agil-2-por-pregunta-20260825.xlsx"
```
Cuerpo: el archivo `.xlsx` binario. Para una jornada con 7 momentos y 49 preguntas activas, el archivo trae 53 hojas (4 fijas + 49 de pregunta).

Error (falta el filtro), `400`:
```json
{ "detail": "Debes indicar ?jornada=<id>." }
```

Error (la jornada no existe), `404`:
```json
{ "detail": "No existe una jornada con ese id." }
```
</details>

### HU-11f — Mismo reporte Excel, pero agrupado una hoja por momento
Como administrador quiero la misma información de HU-11e pero organizada por momento en vez de por pregunta — todas las preguntas de un mismo momento apiladas en una sola hoja — para revisar un momento completo de corrido sin saltar entre decenas de hojas.
- `GET /api/admin/reporte-excel-por-momento/?jornada=<id>` — mismos requisitos, mismo tipo de respuesta (archivo directo) y las mismas garantías (sin IA, fórmulas reales, no filtra por `momento.activo`) que HU-11e.
- Estructura idéntica en **Resumen**, **Índice**, **Participantes** y **Mesas**. La diferencia está en las hojas de contenido: en vez de una por pregunta, hay **una hoja por momento** (nombrada `M{orden} {inicio del título del momento}`), con el título del momento arriba, un enlace de vuelta al índice, y luego cada una de sus preguntas apilada verticalmente — cada una con su propio bloque de Caracterización y Respuestas registradas, igual que en HU-11e.
- El Índice sigue teniendo una fila por pregunta (no por momento) — cada fila salta directo al bloque exacto de esa pregunta dentro de la hoja de su momento, no solo al principio de la hoja.

<details><summary>Ejemplo — <code>GET /api/admin/reporte-excel-por-momento/?jornada=4</code></summary>

Response `200`, headers:
```
Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
Content-Disposition: attachment; filename="reporte-jornada-agil-2-por-momento-20260825.xlsx"
```
Cuerpo: el archivo `.xlsx` binario. Para la misma jornada de 7 momentos y 49 preguntas, el archivo trae 11 hojas (4 fijas + 7 de momento) en vez de 53.

Errores: iguales a HU-11e.
</details>

### HU-12 — Configurar plantillas de análisis con IA
Como administrador quiero crear y editar plantillas de prompt que definen el tono, foco y profundidad con que el LLM redacta los reportes, para adaptar el análisis a distintos tipos de jornada sin tocar código.
- CRUD completo en `/api/admin/plantillas-analisis/` (`GET`, `POST`) y `/api/admin/plantillas-analisis/{id}/` (`GET`, `PATCH`, `DELETE`).
- `tipo` (`"local"` o `"gpt_momento"`) distingue para cuál motor de análisis es la plantilla — el pipeline local multiagente (HU-13) o el análisis de instrumento completo vía OpenAI (HU-14d). **Cada `tipo` tiene su propia plantilla `predeterminada`**, independiente del otro: marcar una nueva predeterminada de un tipo nunca desmarca la del otro tipo, porque son prompts de propósito distinto (uno redacta muchas descripciones cortas, el otro un reporte con hallazgos cruzados).
- El texto de la plantilla (`prompt_sistema`) son instrucciones de estilo/foco/profundidad — los datos reales (estadísticas y tópicos) se le entregan al modelo aparte, ya calculados, nunca los inventa.
- **La plantilla `local` aplica en TODOS los niveles del pipeline local** — cada pregunta, cada momento y la jornada completa — no solo en la síntesis final: editar la plantilla activa y volver a pedir un reporte cambia el tono/profundidad de principio a fin, sin tocar código ni redeploy.

<details><summary>Ejemplo — <code>POST /api/admin/plantillas-analisis/</code></summary>

Request:
```json
{
  "nombre": "Síntesis institucional Jornada Ágil",
  "tipo": "local",
  "prompt_sistema": "Sé breve y muy concisa: prioriza cifras concretas sobre prosa interpretativa. Tono formal e institucional, dirigido a la Rectoría de la Universidad del Magdalena. Si estás redactando la síntesis de la jornada completa, ciérrala con una recomendación breve y accionable.",
  "predeterminada": true
}
```

Response `201`:
```json
{
  "id": 2,
  "nombre": "Síntesis institucional Jornada Ágil",
  "tipo": "local",
  "prompt_sistema": "Sé breve y muy concisa: prioriza cifras concretas sobre prosa interpretativa. Tono formal e institucional, dirigido a la Rectoría de la Universidad del Magdalena. Si estás redactando la síntesis de la jornada completa, ciérrala con una recomendación breve y accionable.",
  "predeterminada": true,
  "creada_por": 3,
  "creado_en": "2026-08-18T17:25:06.591739-05:00",
  "actualizado_en": "2026-08-18T17:25:06.591739-05:00"
}
```
</details>

### HU-13 — Generar un reporte de análisis jerárquico (jornada → momento → pregunta) con IA
Como administrador quiero pedir un análisis de una jornada completa, un momento individual o varios momentos combinados, para convertir las respuestas cualitativas en estadísticas cuantitativas y un análisis narrativo robusto a tres niveles.
- `POST /api/admin/reportes/` con `jornada` (obligatorio), `momentos` (opcional: vacío = jornada completa, uno = momento individual, varios = momentos combinados) y `plantilla` (opcional; si no se manda usa la marcada `predeterminada`). Como el reporte solo cubre los momentos pedidos, se puede generar apenas esté lista la información de al menos uno — no hace falta esperar a que toda la jornada esté cerrada.
- Responde de inmediato (`201`) con el reporte en estado `procesando` — el análisis corre en segundo plano, no bloquea el request, y sus preguntas se procesan **en paralelo** (pool de instancias del modelo local) para no escalar linealmente con la cantidad de preguntas de la jornada.
- El análisis es **multiagente**: una llamada al LLM local por cada pregunta (redacta un análisis interpretativo — no un resumen telegráfico — a partir de sus estadísticas/tópicos ya calculados), una por cada momento (sintetiza e interpreta el conjunto de sus preguntas) y una para la jornada completa (sintetiza sus momentos) — nunca una sola llamada con todo el detalle de la jornada encima, así el tamaño del contexto no depende de cuántas preguntas tenga la jornada.
- Para preguntas `abierta`: si el momento trae `categorias_semilla` (HU-03), esas categorías predefinidas son los candidatos de tema — el modelo solo puede sumar como máximo una categoría nueva por pregunta si de verdad ninguna encaja. Si no hay categorías semilla y la muestra alcanza (≥8 respuestas), los temas se descubren automáticamente (BERTopic, determinístico). Con muestra chica, el propio LLM extrae 3-5 frases características tomadas de las respuestas dadas (`metodo_valores: "llm"`) en vez de dejarlas vacías. En cualquiera de los dos primeros casos, es el propio LLM quien clasifica CADA respuesta real en uno de los temas — el conteo/porcentaje de cada tema sale de esa clasificación, nunca del clustering crudo.
- Para preguntas de momentos tipo `mesa`, además se calcula `nivel_acuerdo` por tema (`consenso_fuerte`/`consenso_moderado`/`tension_estrategica`/`tema_emergente`/`asunto_pendiente`) — qué tan de acuerdo estuvieron las mesas entre sí, según la metodología de codificación temática del equipo.
- El LLM nunca inventa cifras: cada agente solo ve los datos ya calculados de su propio nivel. Si una llamada puntual falla o tarda demasiado, esa pieza queda con un aviso corto — no tumba el resto del reporte.

<details><summary>Ejemplo — <code>POST /api/admin/reportes/</code></summary>

Request (alcance = varios momentos combinados):
```json
{ "jornada": 4, "momentos": [3, 5] }
```

Response `201` (recién creado, todavía `procesando`):
```json
{
  "id": 30,
  "slug": "jornada-agil-2-momentos-20260819-2124",
  "jornada": "jornada-agil-2",
  "momentos": [
    { "id": 3, "titulo": "Momento 1 — EIBIC: reflexión individual", "slug": "momento-1-eibic-reflexion-individual", "orden": 1 },
    { "id": 5, "titulo": "Dinámica 1 — El nudo que cuida", "slug": "dinamica-1-el-nudo-que-cuida", "orden": 3 }
  ],
  "alcance": "momentos",
  "plantilla": 2,
  "plantilla_nombre": "Síntesis institucional Jornada Ágil",
  "estado": "procesando",
  "error_mensaje": "",
  "analisis": {},
  "texto_reporte": "",
  "modelo_usado": "",
  "presentacion_html": "",
  "presentacion_estado": "pendiente",
  "presentacion_error": "",
  "presentacion_modelo": "",
  "presentacion_generada_en": null,
  "solicitado_por": 3,
  "creado_en": "2026-08-19T21:24:44.367091-05:00",
  "actualizado_en": "2026-08-19T21:24:44.367097-05:00",
  "completado_en": null
}
```

Error (ya hay otro reporte `procesando`), `409`:
```json
{ "detail": "Ya hay un reporte en proceso (pendiente o procesando). El análisis usa un único modelo de IA compartido y no soporta más de un reporte a la vez — espera a que termine (o falle) antes de pedir otro." }
```
</details>

### HU-14 — Consultar el estado y el resultado de un reporte (incluida vista tabular)
Como administrador quiero consultar el estado de un reporte y su resultado una vez listo en formato estructurado, para revisarlo con claridad sin tener que descargar nada.
- `GET /api/admin/reportes/` (filtrable `?jornada=<id>`) y `GET /api/admin/reportes/{id}/` devuelven `estado` (`pendiente`/`procesando`/`completo`/`error`), `analisis` y `texto_reporte`.
- **`analisis` ya es la vista tabular** — no hace falta descargar el PDF para verlo claro: trae `participacion` (totales) y `momentos[]`, cada uno con `tipo` (`individual`/`mesa`), `descripcion_general` y `preguntas[]` — cada pregunta con `texto` (el enunciado real, no solo su id), `tipo`, `tipo_grafica`, `nivel_acuerdo`, `descripcion`, `valores_caracteristicos` y `metodo_valores` (`"bertopic_llm"`/`"bertopic_sin_clasificar"`/`"llm"`/`"conteo"`). Un frontend puede renderizar esto directamente como tabla por momento, sin transformación adicional.
- Cada tema de `valores_caracteristicos` (para preguntas con `metodo_valores: "bertopic_llm"`) trae además `origen` (`"semilla"` si vino de `categorias_semilla`, `"inductivo"` si el LLM lo agregó porque nada más encajaba).
- `tipo_grafica` es `null` para preguntas `abierta` sin suficientes temas cuantificados. Cuando aplica, es `"pastel"`, `"barras"` o `"radar"` — elegido por el propio agente de pregunta según hacia dónde le parece que se inclina el público (radar cuando hay 4+ temas/opciones parejos); si el modelo no responde con una elección válida, se usa un respaldo determinístico.
- `texto_reporte` es la síntesis del agente de jornada (el nivel más alto).
- `slug` se autogenera como `{jornada}-{alcance}-{fecha y hora local de Colombia}` (ej. `jornada-agil-2-jornada-20260818-2043`) para poder distinguir reportes a simple vista sin decodificar timestamps.
- Ver `docs/REPORTE_ANALITICA_SCHEMA.html` para el detalle exacto de cada campo.
- `DELETE /api/admin/reportes/{id}/` elimina un reporte.

<details><summary>Ejemplo — <code>GET /api/admin/reportes/30/</code> (recortado — ver el schema para la estructura completa)</summary>

Response `200`:
```json
{
  "id": 30,
  "estado": "completo",
  "error_mensaje": "",
  "analisis": {
    "participacion": { "total_participantes": 25, "participantes_que_respondieron": 25, "tasa_participacion": 100.0 },
    "momentos": [
      {
        "momento_id": 3,
        "tipo": "individual",
        "descripcion_general": "El principio de que la ética debe acompañar toda la investigación tiene amplio respaldo, con 80% de acuerdo. La formación en integridad científica es el punto que más ajustes pide el grupo.",
        "preguntas": [
          {
            "pregunta_id": 38,
            "texto": "Reconocer que la ética debe acompañar investigación, creación, innovación, emprendimiento, transferencia y apropiación del conocimiento.",
            "tipo": "unica",
            "tipo_grafica": "barras",
            "nivel_acuerdo": null,
            "total_respuestas": 25,
            "descripcion": "De acuerdo domina con 80% (20/25) sobre este principio, mostrando respaldo amplio a que la ética acompañe toda la cadena de investigación e innovación. La Universidad puede tomar este punto como base ya consolidada del nuevo marco EIBIC, sin necesidad de mayor discusión.",
            "valores_caracteristicos": [
              { "opcion_id": 16, "texto": "De acuerdo", "conteo": 20 },
              { "opcion_id": 17, "texto": "Requiere ajuste", "conteo": 4 },
              { "opcion_id": 18, "texto": "No debería incorporarse", "conteo": 1 }
            ],
            "metodo_valores": "conteo"
          }
        ]
      }
    ]
  },
  "texto_reporte": "Participantes totales: 25. Participantes que respondieron: 25 (100.0%). El principio de ética transversal a la investigación tiene consenso amplio (80%)...",
  "modelo_usado": "qwen2.5-3b-instruct-q4_k_m.gguf"
}
```
</details>

### HU-14b — Descargar un PDF listo para entregar, sin depender de una IA externa
Como administrador quiero descargar un PDF ya maquetado (portada, síntesis ejecutiva, secciones por momento con gráficos reales, badges de nivel de acuerdo) de un reporte ya completo, para tener un documento presentable sin esperas ni riesgo de que salga mal armado.
- `GET /api/admin/reportes/{id}/pdf/` — responde en la misma petición (no es asíncrono: no hay nada que generar de antemano ni estado que consultar después). 400 si el análisis del reporte todavía no está `completo`.
- Se arma 100% en el servidor a partir de `analisis` (mismo dato de HU-14) — no llama a ningún servicio externo, así que es rápido y sale igual cada vez.
- Incluye portada institucional a página completa, resumen ejecutivo con el markdown de la síntesis convertido a formato real, una sección por momento con su tipo (individual/mesa), y una tarjeta por pregunta con su enunciado real, análisis y gráfico (barras u pastel, con todos los temas — nunca solo los principales) o etiquetas de temas cuando no hay conteo.

<details><summary>Ejemplo — <code>GET /api/admin/reportes/30/pdf/</code></summary>

No lleva body de request (solo el header `Authorization: Token <token>`). Response `200`: binario `application/pdf` (no JSON) con header `Content-Disposition: inline; filename="jornada-agil-2-momentos-20260819-2124.pdf"`.

Error (análisis no completo), `400`:
```json
{ "detail": "El análisis de este reporte todavía no está completo." }
```
</details>

### HU-14c — Generar una presentación HTML alternativa con IA externa (experimental)
Como administrador quiero pedir opcionalmente que una IA externa (OpenAI) redacte y maquete una presentación HTML a partir del mismo análisis ya calculado, para explorar una alternativa de diseño más libre cuando el PDF determinístico no sea suficiente.
- `POST /api/admin/reportes/{id}/generar-presentacion/` — asíncrono (`202`, hay que consultar el estado después, a diferencia del PDF de HU-14b). 400 si el análisis no está `completo`; 409 si ya hay una presentación en curso para ese reporte (se auto-sana sola si quedó huérfana por más de 10 minutos, ej. tras un redeploy a mitad de generación).
- Requiere `OPENAI_API_KEY` configurada en el servidor (variable de entorno, nunca en el repo) — si falta, el reporte queda con `presentacion_estado: "error"` y un mensaje claro, no revienta.
- `presentacion_html`, `presentacion_estado` (`pendiente`/`procesando`/`completo`/`error`), `presentacion_error`, `presentacion_modelo` y `presentacion_generada_en` se consultan en el mismo `GET /api/admin/reportes/{id}/` de HU-14.
- A diferencia del PDF, la IA externa arma el HTML/CSS/gráficos SVG completos por su cuenta — más flexible visualmente, pero sin la garantía de armado determinístico del PDF; se recomienda el PDF (HU-14b) como la vía confiable por defecto.

<details><summary>Ejemplo — <code>POST /api/admin/reportes/30/generar-presentacion/</code></summary>

No lleva body de request.

Response `202`:
```json
{
  "id": 30,
  "estado": "completo",
  "presentacion_html": "",
  "presentacion_estado": "procesando",
  "presentacion_error": "",
  "presentacion_modelo": "",
  "presentacion_generada_en": null
}
```

Luego, consultando `GET /api/admin/reportes/30/` hasta que `presentacion_estado` sea `"completo"`:
```json
{
  "presentacion_estado": "completo",
  "presentacion_modelo": "gpt-4o",
  "presentacion_generada_en": "2026-08-19T21:40:12.001Z",
  "presentacion_html": "<!doctype html><html>...</html>"
}
```

Error (falta `OPENAI_API_KEY` en el servidor):
```json
{ "presentacion_estado": "error", "presentacion_error": "OPENAI_API_KEY no está configurada en el servidor." }
```
</details>

### HU-14d — Analizar un momento completo como un solo instrumento con IA (experimental)
Como administrador quiero pedirle a una IA externa que lea TODO un momento de una vez — su contexto y todas sus preguntas y respuestas reales — y me entregue un reporte con hallazgos que crucen varias preguntas, en vez de un análisis mecánico pregunta por pregunta, para tener una lectura más natural y profesional de momentos con muchas preguntas (un momento de 30 preguntas es un solo instrumento, no 30 análisis sueltos).
- `POST /api/admin/analisis-momento-ia/` con `{"momento": <id>}` — asíncrono (`201` con estado `pendiente`, hay que consultar el estado después). No depende de crear un `Reporte` primero: se dispara directo desde el `Momento`.
- `GET /api/admin/analisis-momento-ia/?momento=<id>` lista el historial de análisis de ese momento; `GET /api/admin/analisis-momento-ia/{id}/` consulta uno puntual hasta que `estado` sea `"completo"`. `DELETE /api/admin/analisis-momento-ia/{id}/` elimina uno.
- 409 si ya hay un análisis en curso para ESE momento (no bloquea otros momentos — cada llamada a OpenAI es independiente); se auto-sana si quedó huérfana por más de 10 minutos (mismo patrón que HU-14c).
- **`resultado` tiene una forma distinta a `analisis` de HU-14** — no es una lista de preguntas, es `resumen_ejecutivo` + `hallazgos[]`, cada hallazgo con `titulo`, `descripcion`, `preguntas_relacionadas` (los `pregunta_id` que lo sustentan — puede ser una o varias), `tipo_grafica` (`"pastel"`/`"barras"`/`"radar"`/`null`) y `datos[]` (`{etiqueta, valor, unidad}`, con conteos reales — nunca de dos naturalezas de medición distintas en el mismo `datos`, ej. nunca mezcla un conteo de opción de escala con un conteo de palabra clave de texto abierto en la misma gráfica).
- Para preguntas de opción única/múltiple el conteo es exacto (calculado por el backend, la IA nunca lo recalcula). Para preguntas abiertas, la IA lee TODAS las respuestas de texto reales y extrae sus propias palabras clave/temas con conteo real — sin la etiqueta `origen: "semilla"/"inductivo"` que sí tiene HU-13, aquí el reporte se lee unificado.
- Reporte entre 6 y 10 hallazgos, cada uno respaldado por 2 a 4 preguntas relacionadas cuando el patrón del instrumento realmente lo sostenga — prioriza deducciones (qué revela un patrón cruzando varias preguntas) sobre repetir una cifra aislada.
- Requiere `OPENAI_API_KEY` configurada en el servidor — mismo comportamiento de error claro que HU-14c si falta.

<details><summary>Ejemplo — <code>POST /api/admin/analisis-momento-ia/</code></summary>

Request:
```json
{ "momento": 3 }
```

Response `201`:
```json
{
  "id": 3,
  "momento": 3,
  "momento_titulo": "Momento 1 — EIBIC: reflexión individual",
  "estado": "pendiente",
  "resultado": {},
  "error_mensaje": "",
  "modelo_usado": "",
  "solicitado_por": 3,
  "creado_en": "2026-08-19T22:19:34.430766-05:00",
  "actualizado_en": "2026-08-19T22:19:34.430782-05:00",
  "completado_en": null
}
```

Luego, consultando `GET /api/admin/analisis-momento-ia/3/` hasta que `estado` sea `"completo"` (recortado — un `resultado` real trae entre 6 y 10 hallazgos):
```json
{
  "estado": "completo",
  "modelo_usado": "gpt-4o",
  "resultado": {
    "momento_id": 3,
    "tipo": "individual",
    "resumen_ejecutivo": "El instrumento busca establecer lineamientos estratégicos para la ética en la investigación en UNIMAGDALENA. La mayoría de los participantes está de acuerdo con la incorporación de la ética en diversas etapas del proceso investigativo, aunque algunos sugieren ajustes específicos...",
    "hallazgos": [
      {
        "titulo": "Consenso sobre la importancia de la ética en la investigación",
        "descripcion": "Una mayoría significativa de participantes (80%) está de acuerdo en que la ética debe acompañar la investigación y otros procesos relacionados. Sin embargo, un 20% considera que se requieren ajustes.",
        "preguntas_relacionadas": [38],
        "tipo_grafica": "pastel",
        "datos": [
          {"etiqueta": "De acuerdo", "valor": 20, "unidad": "conteo"},
          {"etiqueta": "Requiere ajuste", "valor": 5, "unidad": "conteo"}
        ]
      },
      {
        "titulo": "Protección de datos y uso de inteligencia artificial",
        "descripcion": "Hay un fuerte consenso (19 de 25) sobre la necesidad de fortalecer las reglas para la protección de datos y el uso responsable de inteligencia artificial. Las respuestas abiertas indican preocupaciones sobre la anonimización y auditoría de datos sensibles.",
        "preguntas_relacionadas": [41, 46],
        "tipo_grafica": "radar",
        "datos": [
          {"etiqueta": "Reglas para IA y datos sensibles", "valor": 6, "unidad": "conteo"},
          {"etiqueta": "Auditorías de sesgo en IA", "valor": 5, "unidad": "conteo"},
          {"etiqueta": "Políticas de conservación y acceso a datos", "valor": 5, "unidad": "conteo"},
          {"etiqueta": "Protocolos de seguridad para datos genéticos", "valor": 5, "unidad": "conteo"}
        ]
      }
    ]
  },
  "completado_en": "2026-08-19T22:19:45.751992-05:00"
}
```

Error (ya hay un análisis en curso para este momento), `409`:
```json
{ "detail": "Ya hay un análisis con IA en proceso para este momento — espera a que termine (o falle) antes de pedir otro." }
```
</details>

### HU-14e — Editar el prompt del análisis de instrumento completo (HU-14d)
Como administrador quiero editar el tono, foco o reglas del análisis de instrumento completo (HU-14d) sin tocar código, igual que ya puedo hacerlo con el pipeline local (HU-12).
- Se usa el mismo CRUD de HU-12 (`/api/admin/plantillas-analisis/`), creando o editando una plantilla con `tipo: "gpt_momento"` y `predeterminada: true`.
- Sus instrucciones se agregan al prompt base de HU-14d en cada llamada — no reemplazan las reglas fijas (formato de salida JSON, no inventar cifras, no mezclar naturalezas de datos), solo ajustan tono/foco encima de ellas.
- Si no hay ninguna plantilla `gpt_momento` marcada como predeterminada, HU-14d funciona igual con el prompt base — la plantilla es un ajuste opcional, no un requisito.

<details><summary>Ejemplo — <code>POST /api/admin/plantillas-analisis/</code></summary>

Request:
```json
{
  "nombre": "Instrumento completo — foco en gobernanza",
  "tipo": "gpt_momento",
  "prompt_sistema": "Da prioridad a los hallazgos relacionados con gobernanza institucional y toma de decisiones sobre los puramente operativos. Cuando compares posturas, sé explícito sobre si la divergencia es de fondo (principios) o de forma (implementación).",
  "predeterminada": true
}
```

Response `201`: mismo cuerpo que el ejemplo de HU-12, con `tipo: "gpt_momento"`.
</details>

### HU-14f — Ventana de edición del prompt del análisis de instrumento completo
Como administrador quiero abrir una ventana dedicada que me muestre el prompt actual del análisis de instrumento completo (HU-14d) y me deje editarlo y guardarlo, para ajustar su tono/foco sin tener que entender el sistema general de plantillas ni su campo `tipo`.

Es el mismo recurso de HU-12/HU-14e (`/api/admin/plantillas-analisis/`) — esta historia describe el flujo completo, de punta a punta, para implementar esa ventana como si fuera independiente. El frontend siempre manda `tipo: "gpt_momento"` fijo (quemado) en cada request; nunca se lo pide al usuario ni lo expone en la UI.

**1. Al abrir la ventana — cargar el prompt actual (o detectar que no existe ninguno todavía):**
```
GET /api/admin/plantillas-analisis/?tipo=gpt_momento&predeterminada=true
```
- Si devuelve un array con un elemento: ese es el prompt activo — precarga su `prompt_sistema` en el textarea y guarda su `id` (lo vas a necesitar para el `PATCH` del paso 3).
- Si devuelve un array vacío `[]`: todavía no existe ninguno — el motor está usando su prompt base de fábrica. Muestra el textarea vacío con un placeholder tipo *"Sin personalizar — se está usando el comportamiento por defecto"* y en el paso 3 usa `POST` en vez de `PATCH`.

<details><summary>Ejemplo — sin personalizar todavía</summary>

Response `200`:
```json
[]
```
</details>

<details><summary>Ejemplo — ya existe una personalización</summary>

Response `200`:
```json
[
  {
    "id": 5,
    "nombre": "Instrumento completo — foco en gobernanza",
    "tipo": "gpt_momento",
    "prompt_sistema": "Da prioridad a los hallazgos relacionados con gobernanza institucional y toma de decisiones sobre los puramente operativos. Cuando compares posturas, sé explícito sobre si la divergencia es de fondo (principios) o de forma (implementación).",
    "predeterminada": true,
    "creada_por": 3,
    "creado_en": "2026-08-19T23:10:00-05:00",
    "actualizado_en": "2026-08-19T23:10:00-05:00"
  }
]
```
</details>

**2. Mientras el usuario escribe:** solo el campo `prompt_sistema` es editable en esta ventana — es texto libre, sin estructura que validar en el cliente. Un campo `nombre` corto también es requerido por el backend; si la ventana no lo expone, generarlo automáticamente (ej. `"Instrumento completo — personalizado"`) es suficiente, no necesita ser significativo para el usuario.

**3. Al guardar:**
- Si en el paso 1 SÍ había un `id` → `PATCH /api/admin/plantillas-analisis/{id}/` con `{"prompt_sistema": "<el texto editado>"}`.
- Si en el paso 1 NO había ninguno (`[]`) → `POST /api/admin/plantillas-analisis/` con `{"nombre": "...", "tipo": "gpt_momento", "prompt_sistema": "<el texto>", "predeterminada": true}`.
- En ambos casos el cambio aplica de inmediato al siguiente `POST /api/admin/analisis-momento-ia/` que se dispare — no hace falta redeploy ni reinicio del backend.

<details><summary>Ejemplo — guardar edición (ya existía, id 5)</summary>

Request:
```
PATCH /api/admin/plantillas-analisis/5/
```
```json
{ "prompt_sistema": "Prioriza hallazgos de gobernanza y toma de decisiones. Además, cuando el instrumento incluya preguntas sobre inteligencia artificial, dedica al menos un hallazgo específico a ese tema." }
```

Response `200`: el mismo objeto del paso 1 con `prompt_sistema` y `actualizado_en` actualizados.
</details>

**4. Restablecer al comportamiento de fábrica (opcional):** `DELETE /api/admin/plantillas-analisis/{id}/` — sin ninguna plantilla `gpt_momento` predeterminada, HU-14d vuelve a su prompt base sin ningún ajuste adicional.

### HU-14g — Analizar una jornada completa cruzando momentos con IA (experimental)
Como administrador quiero pedirle a una IA externa que lea TODOS los momentos activos de una jornada de una sola vez — su contexto y todas sus preguntas y respuestas reales — y me entregue hallazgos que crucen momentos distintos, para no perder de vista un patrón que se repite en varias mesas/temas cuando cada momento se analiza aislado (HU-14d). Pensado para jornadas tipo "Café del Mundo": varios momentos cortos, uno por mesa/tema, donde el valor real está en el panorama completo, no mesa por mesa.
- `POST /api/admin/analisis-jornada-ia/` con `{"jornada": <id>}` — asíncrono (`201` con estado `pendiente`), mismo patrón que HU-14d pero a nivel de jornada en vez de momento; no depende de crear un `Reporte` ni de pedir antes el análisis de cada momento por separado — ambos endpoints son independientes y coexisten.
- `GET /api/admin/analisis-jornada-ia/?jornada=<id>` lista el historial de análisis de esa jornada; `GET /api/admin/analisis-jornada-ia/{id}/` consulta uno puntual hasta que `estado` sea `"completo"`. `DELETE /api/admin/analisis-jornada-ia/{id}/` elimina uno.
- 409 si ya hay un análisis en curso para ESA jornada (no bloquea otras jornadas ni el análisis por momento — es un guard independiente); se auto-sana si quedó huérfano por más de 10 minutos (mismo patrón que HU-14d).
- **`resultado` tiene la misma forma que HU-14d** (`resumen_ejecutivo` + `hallazgos[]`, cada uno con `titulo`, `descripcion`, `tipo_grafica`, `datos[]`) **más `momentos_relacionados`** junto a `preguntas_relacionadas` en cada hallazgo — cuando el patrón realmente cruza momentos, un hallazgo puede citar varios a la vez (ej. `momentos_relacionados: [2, 5]`); si el patrón nace de un solo momento y no se repite en otro lado, también es válido citar solo ese.
- Si la jornada tiene grabaciones vinculadas (`transcripciones`, ver HU-42 en [USER_STORIES_TRANSCRIPCIONES.md](USER_STORIES_TRANSCRIPCIONES.md)) marcadas para incluirse en el análisis, cada hallazgo también puede traer `transcripciones_relacionadas: [<sesion_id>, ...]` — la IA recibe el resumen YA CALCULADO de cada grabación (su propio `InformeTranscripcion` completo: `resumen_ejecutivo`/`temas_discutidos`/`hallazgos`), nunca la transcripción cruda, y lo trata como una fuente de evidencia más al mismo nivel que un momento.
- El prompt instruye explícitamente a NO producir un bloque mecánico por momento (ni por grabación) — la jornada se lee de corrido como un solo instrumento, buscando activamente dónde reaparece el mismo patrón/tensión/consenso en momentos y grabaciones distintos antes de conformarse con un hallazgo aislado.
- Entrega siempre entre 6 y 12 hallazgos (ni uno menos ni uno más) — prioriza pocos hallazgos densos y sustanciales sobre muchos superficiales.
- **Respeta el mismo control de acceso por dependencia que el resto del sistema** (ver HU-01b): un usuario de dependencia solo puede pedir/ver/listar el análisis de una jornada que le pertenece (`403` al pedirlo, `404` al consultar una ajena por id, el listado simplemente no la incluye); un admin completo, de cualquiera.
- Requiere `OPENAI_API_KEY` configurada en el servidor — mismo comportamiento de error claro que HU-14c/HU-14d si falta.
- Fuera de alcance por ahora: no reemplaza `AnalisisMomentoIA` (HU-14d) — ambos coexisten, cada uno útil para una necesidad distinta (detalle de una mesa vs. panorama completo) — y no incluye una pantalla nueva en el panel, solo el endpoint (igual que se hizo primero con HU-14d).

<details><summary>Ejemplo — <code>POST /api/admin/analisis-jornada-ia/</code></summary>

Request:
```json
{ "jornada": 4 }
```

Response `201`:
```json
{
  "id": 2,
  "jornada": "jornada-agil-2",
  "estado": "pendiente",
  "resultado": {},
  "error_mensaje": "",
  "modelo_usado": "",
  "solicitado_por": 3,
  "creado_en": "2026-09-05T10:02:11.204Z",
  "actualizado_en": "2026-09-05T10:02:11.204Z",
  "completado_en": null
}
```

Luego, consultando `GET /api/admin/analisis-jornada-ia/2/` hasta que `estado` sea `"completo"` (recortado — un `resultado` real trae entre 6 y 12 hallazgos, probado de punta a punta contra "Tu Voz, Nuestra Política": 8 mesas, 40 respuestas, generó 8 hallazgos, la mayoría cruzando entre 2 y 5 mesas distintas):
```json
{
  "estado": "completo",
  "modelo_usado": "gpt-4o",
  "resultado": {
    "jornada_id": 4,
    "resumen_ejecutivo": "A lo largo de la jornada, los participantes coinciden reiteradamente en la necesidad de mecanismos institucionales más claros para canalizar sus propuestas...",
    "hallazgos": [
      {
        "titulo": "Demanda transversal de acompañamiento institucional",
        "descripcion": "El mismo reclamo por más acompañamiento institucional aparece de forma independiente en la Mesa 2 (Momento 2) y en la Mesa 5 (Momento 5), pese a tratar temas distintos — indica una necesidad estructural, no puntual de un tema.",
        "momentos_relacionados": [2, 5],
        "preguntas_relacionadas": [14, 41],
        "tipo_grafica": "barras",
        "datos": [
          {"etiqueta": "Mesa 2 — lo mencionó", "valor": 6, "unidad": "conteo"},
          {"etiqueta": "Mesa 5 — lo mencionó", "valor": 5, "unidad": "conteo"}
        ]
      }
    ]
  },
  "completado_en": "2026-09-05T10:03:02.114Z"
}
```

Error (ya hay un análisis en curso para esta jornada), `409`:
```json
{ "detail": "Ya hay un análisis con IA en proceso para esta jornada — espera a que termine (o falle) antes de pedir otro." }
```

Error (jornada de otra dependencia), `403`:
```json
{ "detail": "Esta jornada no te pertenece." }
```
</details>

### HU-14h — Editar el prompt del análisis de jornada completa (HU-14g)
Como administrador quiero editar el tono, foco o reglas del análisis de jornada completa (HU-14g) sin tocar código, igual que ya puedo hacerlo con el análisis de momento individual (HU-14e).
- Se usa el mismo CRUD de HU-12 (`/api/admin/plantillas-analisis/`), creando o editando una plantilla con `tipo: "gpt_jornada"` y `predeterminada: true` — es un tipo independiente de `"gpt_momento"` (HU-14e), cada uno con su propia plantilla predeterminada.
- Sus instrucciones se agregan al prompt base de HU-14g en cada llamada — no reemplazan las reglas fijas (mínimo 6/máximo 12 hallazgos, formato JSON, no inventar cifras, buscar patrones transversales), solo ajustan tono/foco encima de ellas.
- Si no hay ninguna plantilla `gpt_jornada` marcada como predeterminada, HU-14g funciona igual con el prompt base — es un ajuste opcional, no un requisito.

<details><summary>Ejemplo — <code>POST /api/admin/plantillas-analisis/</code></summary>

Request:
```json
{
  "nombre": "Jornada completa — foco en participación estudiantil",
  "tipo": "gpt_jornada",
  "prompt_sistema": "Da prioridad a los hallazgos que reflejen el nivel y la calidad de la participación estudiantil transversal a la jornada, por encima de los puramente administrativos.",
  "predeterminada": true
}
```

Response `201`: mismo cuerpo que el ejemplo de HU-12, con `tipo: "gpt_jornada"`.
</details>

## Participante / Usuario

### HU-15 — Ver jornadas disponibles
Como usuario quiero ver la lista de todas las jornadas (activas e inactivas) con su descripción, fechas y estado, para elegir a cuál inscribirme y para que la interfaz pueda mostrar las cerradas como desactivadas en vez de simplemente ocultarlas.
- `GET /api/jornadas/` no requiere autenticación y devuelve **todas** las jornadas, incluida la key `activa` en cada una para que el cliente decida cómo representarla (p. ej. deshabilitar el botón de inscripción).

<details><summary>Ejemplo — <code>GET /api/jornadas/</code></summary>

Response `200`:
```json
[
  {
    "slug": "jornada-agil-2",
    "nombre": "Jornada Ágil 2 — Actualización del Sistema de Investigación",
    "descripcion": "Ética, innovación y emprendimiento para transformar desde el conocimiento.",
    "fecha_inicio": "2026-08-20",
    "fecha_fin": "2026-08-20",
    "activa": true
  }
]
```
</details>

### HU-16 — Ver el detalle de una jornada
Como usuario quiero consultar el detalle de una jornada (nombre, descripción, fechas), para decidir si me inscribo antes de dar mis datos.
- `GET /api/jornadas/{slug}/` no requiere autenticación.
- Solo devuelve el detalle de jornadas **activas**; una jornada inactiva responde `404` aunque siga apareciendo en el listado de HU-15.

<details><summary>Ejemplo — <code>GET /api/jornadas/jornada-agil-2/</code></summary>

Response `200`: mismo objeto que cada item de HU-15. Error si está inactiva, `404`:
```json
{ "detail": "No encontrado." }
```
</details>

### HU-17 — Registrarme en una jornada (momento 0)
Como usuario quiero registrarme en una jornada indicando mi correo institucional, nombre, apellido, teléfono, mi rol institucional y, si aplica, mi mesa y si soy el vocero, para inscribirme.
- `POST /api/jornadas/{slug}/registro/` crea el `Participante`.
- `rol` (texto libre, ej. `"estudiante"`, `"directivo"` — sin lista fija de valores) es **obligatorio**; la API responde 400 si falta. Es un dato del participante en sí (quién es institucionalmente), distinto de `mesa`/`es_vocero` (su lugar dentro de la dinámica grupal).
- `mesa` (entero, ej. `3` — el número de la mesa física, no texto libre) y `es_vocero` (booleano) son **opcionales** y quedan fijos para **toda la jornada** — no se vuelven a pedir en cada momento tipo mesa. Un admin puede corregirlos después (HU-10b). Si `es_vocero: true` y esa mesa ya tiene otro vocero en esta jornada, la API responde 400 (máximo un vocero por mesa).
- Si el correo ya está registrado en esa jornada, la API responde 400 sin crear un duplicado.
- Se genera automáticamente un `slug` a partir de nombre y apellido (con sufijo si hay colisión).

<details><summary>Ejemplo — <code>POST /api/jornadas/jornada-agil-2/registro/</code></summary>

Request:
```json
{
  "correo_institucional": "camila.gomez@unimagdalena.edu.co",
  "nombre": "Camila",
  "apellido": "Gómez",
  "telefono": "3000000000",
  "rol": "estudiante",
  "mesa": 3,
  "es_vocero": true
}
```

Response `201`:
```json
{
  "id": 13,
  "jornada": "jornada-agil-2",
  "correo_institucional": "camila.gomez@unimagdalena.edu.co",
  "nombre": "Camila",
  "apellido": "Gómez",
  "telefono": "3000000000",
  "rol": "estudiante",
  "mesa": 3,
  "es_vocero": true,
  "slug": "camila-gomez",
  "token": "b058878f-5797-40ac-ab56-9779902ab300",
  "creado_en": "2026-08-18T19:11:58.251917-05:00"
}
```

Error (correo ya registrado en esta jornada), `400`:
```json
{ "correo_institucional": ["Ya existe un participante con este correo en esta jornada."] }
```

Error (falta `rol`), `400`:
```json
{ "rol": ["Este campo es requerido."] }
```

Error (la mesa ya tiene vocero), `400`:
```json
{ "es_vocero": ["La mesa 3 ya tiene un vocero asignado en esta jornada."] }
```
</details>

### HU-18 — Recibir un token de sesión
Como usuario quiero recibir un token de sesión al registrarme, para autenticar mis siguientes solicitudes sin usuario/contraseña.
- La respuesta de HU-17 incluye `token` (UUID), que el cliente debe reenviar como `Authorization: Participant <token>` en cada solicitud posterior.

<details><summary>Ejemplo — header en cada solicitud posterior</summary>

```
Authorization: Participant b058878f-5797-40ac-ab56-9779902ab300
```

Error (token inválido o inexistente), `401`:
```json
{ "detail": "Token de participante inválido." }
```
</details>

### HU-18b — Recuperar mi token si cerré la sesión (sin contraseña)
Como usuario que ya se registró pero perdió su token (cerré el navegador, cambié de dispositivo, borré el almacenamiento), quiero recuperarlo dando solo mi correo institucional, para volver a entrar sin tener que registrarme de nuevo ni manejar una contraseña.
- `POST /api/jornadas/{slug}/login/` con `{"correo_institucional": "..."}` — no requiere autenticación previa.
- Como el correo institucional es único por jornada (`unique_together` en `Participante`), es la única prueba de identidad necesaria — no hay contraseña que gestionar. Es un nivel de seguridad más bajo que un login tradicional (cualquiera que sepa el correo puede recuperar el token), aceptado a propósito porque esta jornada no maneja datos sensibles ni pagos.
- Devuelve el mismo objeto `Participante` completo que el registro (HU-17), incluido el `token` ya existente — no crea un participante nuevo ni cambia nada de lo ya registrado (mesa, es_vocero, respuestas ya enviadas).
- `404` si no hay ningún participante con ese correo en esa jornada — en ese caso el usuario debe registrarse (HU-17), no "iniciar sesión".

<details><summary>Ejemplo — <code>POST /api/jornadas/jornada-agil-2/login/</code></summary>

Request:
```json
{ "correo_institucional": "camila.gomez@unimagdalena.edu.co" }
```

Response `200`:
```json
{
  "id": 13,
  "jornada": "jornada-agil-2",
  "correo_institucional": "camila.gomez@unimagdalena.edu.co",
  "nombre": "Camila",
  "apellido": "Gómez",
  "telefono": "3000000000",
  "rol": "estudiante",
  "mesa": 3,
  "es_vocero": true,
  "slug": "camila-gomez",
  "token": "b058878f-5797-40ac-ab56-9779902ab300",
  "creado_en": "2026-08-18T19:11:58.251917-05:00"
}
```
Es el mismo `Participante` ya existente, con el `token` que se generó en el registro (HU-17) — no cambia nada, solo lo devuelve. Si el admin ya lo corrigió (mesa, es_vocero — HU-10b), esos valores actualizados son los que salen acá.

Error (correo no registrado en esta jornada), `404`:
```json
{ "detail": "No hay ningún participante registrado con ese correo en esta jornada." }
```
</details>

### HU-18c — Recuperar mis datos con el token ya guardado (sesión activa)
Como usuario cuyo front ya tiene mi token guardado (localStorage, tras el registro o el login), quiero un endpoint que me devuelva mis datos completos mandando solo ese token — sin volver a pedir mi correo — para repoblar el estado de la app al abrirla de nuevo (recargar la página, volver más tarde) sin pasar otra vez por el flujo de login.
- `GET /api/jornadas/{slug}/me/` con header `Authorization: Participant <token>` — mismo mecanismo de autenticación que ya usan todos los demás endpoints de participante (HU-19 en adelante).
- Devuelve exactamente el mismo cuerpo que HU-17 (registro) y HU-18b (login) — mismo `ParticipanteSerializer`, para que el front reutilice el mismo parseo en los tres casos.
- `401` si el token no existe o es inválido (mismo comportamiento que cualquier otro endpoint protegido, ver HU-18). `403` si el token es válido pero pertenece a otra jornada distinta de `{slug}`.

<details><summary>Ejemplo — <code>GET /api/jornadas/jornada-agil-2/me/</code></summary>

Header:
```
Authorization: Participant b058878f-5797-40ac-ab56-9779902ab300
```

Response `200`:
```json
{
  "id": 13,
  "jornada": "jornada-agil-2",
  "correo_institucional": "camila.gomez@unimagdalena.edu.co",
  "nombre": "Camila",
  "apellido": "Gómez",
  "telefono": "3000000000",
  "rol": "estudiante",
  "mesa": 3,
  "es_vocero": true,
  "slug": "camila-gomez",
  "token": "b058878f-5797-40ac-ab56-9779902ab300",
  "creado_en": "2026-08-18T19:11:58.251917-05:00"
}
```

Error (token inválido o inexistente), `401`:
```json
{ "detail": "Token de participante inválido." }
```

Error (token de otra jornada), `403`:
```json
{ "detail": "Debes autenticarte como participante de esta jornada." }
```
</details>

### HU-19 — Listar los momentos de mi jornada
Como usuario ya registrado quiero consultar el índice de momentos de la jornada a la que pertenezco, para saber qué pasos debo recorrer.
- `GET /api/jornadas/{slug}/momentos/` requiere el token del paso anterior y devuelve `id`, `orden`, `título`, `slug` (autogenerado del título, único dentro de la jornada) y `tipo` de cada momento activo, ordenados por `orden`.
- Si el momento es tipo `mesa` y trae `mesas_permitidas` (HU-03), no aparece en el índice para un participante cuya mesa no esté en esa lista — vacía (lo normal) significa visible para todas las mesas.

<details><summary>Ejemplo — <code>GET /api/jornadas/jornada-agil-2/momentos/</code></summary>

Response `200`:
```json
[
  { "id": 3, "orden": 1, "titulo": "Momento 1 — EIBIC: reflexión individual", "slug": "momento-1-eibic-reflexion-individual", "tipo": "individual" },
  { "id": 5, "orden": 3, "titulo": "Dinámica 1 — El nudo que cuida", "slug": "dinamica-1-el-nudo-que-cuida", "tipo": "mesa" }
]
```
</details>

### HU-20 — Ver el detalle de un momento
Como usuario quiero consultar el contexto y las preguntas (con sus opciones) de un momento, para poder responderlo.
- `GET /api/jornadas/{slug}/momentos/{id}/` requiere token y devuelve 403 si el token no pertenece a esa jornada.
- 404 ("Este momento no está disponible para tu mesa") si el momento restringe `mesas_permitidas` (HU-03) y la mesa del participante no está en la lista.

<details><summary>Ejemplo — <code>GET /api/jornadas/jornada-agil-2/momentos/3/</code></summary>

Response `200`:
```json
{
  "id": 3,
  "orden": 1,
  "titulo": "Momento 1 — EIBIC: reflexión individual",
  "slug": "momento-1-eibic-reflexion-individual",
  "contexto": "Construir colectivamente los lineamientos estratégicos de EIBIC.",
  "tipo": "individual",
  "preguntas": [
    {
      "id": 38,
      "orden": 1,
      "tipo": "unica",
      "texto": "Reconocer que la ética debe acompañar investigación, creación, innovación, emprendimiento, transferencia y apropiación del conocimiento.",
      "obligatoria": true,
      "opciones": [
        { "id": 16, "texto": "De acuerdo", "orden": 1 },
        { "id": 17, "texto": "Requiere ajuste", "orden": 2 },
        { "id": 18, "texto": "No debería incorporarse", "orden": 3 }
      ]
    }
  ]
}
```
</details>

### HU-21 — Responder un momento individual
Como usuario quiero responder las preguntas de un momento `individual` (abiertas, únicas o de selección múltiple), para que mis respuestas queden guardadas asociadas a mí.
- `POST /api/jornadas/{slug}/momentos/{id}/respuestas/` guarda una `Respuesta` por pregunta asociada a mi `Participante`.

<details><summary>Ejemplo — <code>POST /api/jornadas/jornada-agil-2/momentos/3/respuestas/</code></summary>

Request:
```json
{
  "respuestas": [
    { "pregunta_id": 38, "opcion_ids": [16] },
    { "pregunta_id": 45, "texto_libre": "Debe existir consentimiento previo, libre e informado antes de iniciar cualquier trabajo con comunidades." }
  ]
}
```

Response `200`:
```json
[
  { "id": 501, "pregunta": 38, "participante": 13, "mesa": null, "texto_libre": "", "opciones": [16], "actualizado_en": "2026-08-19T21:15:03.112Z" },
  { "id": 502, "pregunta": 45, "participante": 13, "mesa": null, "texto_libre": "Debe existir consentimiento previo, libre e informado antes de iniciar cualquier trabajo con comunidades.", "opciones": [], "actualizado_en": "2026-08-19T21:15:03.118Z" }
]
```
</details>

### HU-22 — Responder un momento de tipo "mesa" (solo el vocero)
Como vocero de mi mesa quiero enviar la respuesta compartida de un momento tipo mesa, para que el resultado represente a todo el grupo — sin que cualquier integrante pueda enviarla por error o duplicado.
- **Solo participantes con `es_vocero: true`** pueden hacer `POST` en un momento tipo mesa — cualquier otro participante recibe `403`. La mesa NO se manda en el body: se toma automáticamente de `mesa` del participante autenticado (fijada en el registro, HU-17, o corregida por un admin, HU-10b) — así un vocero no puede enviar a nombre de otra mesa por error.
- Un participante sin `es_vocero: true` puede seguir consultando el momento normalmente (`GET`, HU-20) — el bloqueo es solo al enviar respuestas.
- Si otro participante de la misma mesa (que también fuera vocero) vuelve a responder, la respuesta se actualiza (no se duplica); se registra quién la envió por última vez (`registrado_por`) para trazabilidad.
- Si el momento restringe `mesas_permitidas` (HU-03) y la mesa del vocero no está en la lista, `404` (mismo mensaje que HU-20) — no llega ni a validar las respuestas individuales. Si en cambio es una `Pregunta` puntual la que trae `mesas_permitidas` (HU-05) y esa mesa no puede responderla, `400` señalando esa pregunta específica.

<details><summary>Ejemplo — <code>POST /api/jornadas/jornada-agil-2/momentos/5/respuestas/</code> (participante con <code>es_vocero: true</code> y <code>mesa: "Mesa 3"</code>)</summary>

Request:
```json
{
  "respuestas": [
    { "pregunta_id": 20, "opcion_ids": [4] },
    { "pregunta_id": 17, "texto_libre": "Cuidar la confianza y el consentimiento informado de las comunidades." }
  ]
}
```

Response `200`:
```json
[
  { "id": 610, "pregunta": 20, "participante": null, "mesa": 3, "texto_libre": "", "opciones": [4], "actualizado_en": "2026-08-19T21:20:00.000Z" },
  { "id": 611, "pregunta": 17, "participante": null, "mesa": 3, "texto_libre": "Cuidar la confianza y el consentimiento informado de las comunidades.", "opciones": [], "actualizado_en": "2026-08-19T21:20:00.005Z" }
]
```

Error (participante sin `es_vocero`), `403`:
```json
{ "detail": "Solo el vocero de la mesa puede enviar respuestas en este momento." }
```

Error (es vocero pero no tiene `mesa` asignada), `400`:
```json
{ "mesa": "No tienes una mesa asignada — pídele a un administrador que te la asigne antes de responder." }
```
</details>

### HU-23 — Corregir una respuesta ya enviada
Como usuario quiero poder reenviar mis respuestas a un momento antes de avanzar, para corregir errores.
- Un segundo `POST` al mismo momento actualiza (`update_or_create`) las respuestas existentes en vez de crear duplicados.

<details><summary>Ejemplo — reenvío que corrige la opción de HU-21</summary>

Request (mismo endpoint que HU-21):
```json
{ "respuestas": [ { "pregunta_id": 38, "opcion_ids": [17] } ] }
```

Response `200`: la misma `Respuesta` (`id: 501`) con `opciones: [17]` — no se crea un registro nuevo.
</details>

### HU-24 — Validación de preguntas obligatorias
Como usuario quiero que el sistema valide que las preguntas obligatorias tengan respuesta, para evitar enviar información incompleta.
- Si falta una pregunta obligatoria del momento en el envío, o su contenido no cumple el tipo (p. ej. `unica` con más de una opción, `abierta` vacía), la API responde 400 detallando el problema.

<details><summary>Ejemplo — falta una pregunta obligatoria</summary>

Response `400`:
```json
{ "faltantes": "Preguntas obligatorias sin responder: [39, 40, 41, 42, 43]" }
```
</details>

### HU-25 — Aislamiento entre jornadas y protección por token
Como usuario quiero que se rechacen intentos de acceder a momentos de una jornada distinta a la mía o sin token válido, para proteger mis datos y los de otros participantes.
- Sin header `Authorization` válido → 401.
- Con token de otra jornada → 403.
- Un `momento_id` que no pertenece a la jornada de la URL → 404.
- Un token de participante usado contra un endpoint de admin (o viceversa) → 403 limpio, nunca error de servidor.

<details><summary>Ejemplos de error</summary>

Sin token, `401`:
```json
{ "detail": "Las credenciales de autenticación no se proveyeron." }
```

Token de otra jornada, `403`:
```json
{ "detail": "Debes autenticarte como participante de esta jornada." }
```
</details>

## Instrumentos de reflexión (aplicación restringida por preregistro)

Caso de uso independiente (instrumento de reflexión con preregistro cerrado, revisión y descarga
en Word), documentado aparte en
[USER_STORIES_INSTRUMENTOS.md](USER_STORIES_INSTRUMENTOS.md) (HU-26 a HU-33).

## Transcripciones (sesiones grabadas, informe con IA)

Caso de uso independiente (sesión grabada, ingesta de la transcripción en tiempo real, informe por
mapa-reducción con IA, presentación HTML y PDF), documentado aparte en
[USER_STORIES_TRANSCRIPCIONES.md](USER_STORIES_TRANSCRIPCIONES.md) (HU-34 a HU-40).

## Documentación técnica (pública, sin rol)

No son historias de usuario en sentido estricto, pero son endpoints que expone la API y conviene tener presentes:

- `GET /api/schema/` — esquema OpenAPI 3 en crudo.
- `GET /api/docs/` — Swagger UI interactivo.
- `GET /api/redoc/` — Redoc (documentación de solo lectura).

---

## Historias de usuario — Instrumentos (aplicación restringida por preregistro)

A diferencia de `jornadas`/`participantes` (autorregistro libre por link), un **instrumento** es un
documento —de reflexión, de diagnóstico, o cualquier otro formato— que solo pueden responder
usuarios preregistrados uno por uno por un encargado, y cuyas respuestas quedan pendientes de
revisión (aceptar/rechazar) antes de darse por válidas. El árbol de contenido (`Instrumento` →
`SeccionInstrumento` → `PreguntaInstrumento` → `OpcionPreguntaInstrumento`/`FilaMatrizInstrumento`/
`ColumnaMatrizInstrumento`) es 100% editable desde `/api/admin/**` — se puede agregar, quitar o
reordenar cualquier sección, pregunta, opción, fila o columna sin tocar código, así que cada
instrumento nuevo es solo un registro más, nunca una app o un modelo aparte. Dos ya precargados
como ejemplo (ambos idempotentes, correr de nuevo actualiza en vez de duplicar):
- `python manage.py cargar_instrumento_reflexion` — "Leer, escribir y pensar en tiempos de
  inteligencia artificial" (`Reflexion_Lectura_Escritura_IA_UNIMAGDALENA.docx`): narrativa +
  una matriz comparativa de 8×3 + 6 preguntas abiertas.
- `python manage.py cargar_instrumento_diagnostico_articulacion` — "Diagnóstico para la
  Articulación Académica" (`Formato_Diagnostico_Articulacion_Academica_UNIMAGDALENA.docx`): 11
  secciones, 90 preguntas, varias matrices (incluidas 3 con filas prellenadas para "cuantas hagan
  falta" — mapa de profesores, asuntos y compromisos — porque el tipo `matriz` fija las filas de
  antemano; el admin agrega más desde `/api/admin/instrumento-filas-matriz/` si una sesión
  concreta las necesita). La mayoría de sus preguntas quedaron `obligatoria=false` a propósito —
  exigir cada celda de un instrumento de 90 preguntas en una sesión de 90 minutos no es realista;
  solo los datos generales de la sesión y la síntesis ejecutiva final son obligatorios.

### HU-26 — Crear y editar un instrumento y su árbol de secciones/preguntas/matriz
Como administrador o encargado quiero crear un instrumento y construir libremente sus secciones y preguntas (incluida una matriz comparativa de filas × columnas), para modelar cualquier documento de reflexión sin depender de una estructura fija en el código.
- `POST /api/admin/instrumentos/` crea el instrumento (`slug` autogenerado desde `nombre`, igual que `Momento`).
- `POST /api/admin/instrumento-secciones/` — cada sección es `tipo=contenido` (texto de solo lectura, para narrativa) o `tipo=preguntas` (agrupa preguntas a diligenciar).
- `POST /api/admin/instrumento-preguntas/` — `tipo` es `abierta`, `unica`, `multiple` o `matriz`. Para `unica`/`multiple` se agregan opciones en `POST /api/admin/instrumento-opciones/`; para `matriz` se agregan filas en `POST /api/admin/instrumento-filas-matriz/` y columnas en `POST /api/admin/instrumento-columnas-matriz/`.
- Todos los niveles se pueden editar (`PATCH`) o eliminar (`DELETE`) independientemente — agregar o quitar una fila de la matriz, por ejemplo, no afecta las demás.
- Mismo scoping admin-completo/dependencia que `jornadas`: `Instrumento.encargados` (M2M) funciona igual que `Jornada.propietarios` — varios encargados pueden compartir un instrumento, y un mismo usuario puede ser encargado de varios instrumentos a la vez (y, por separado, propietario de varias jornadas — son M2M independientes). Un usuario de dependencia solo ve/crea contenido bajo instrumentos donde es encargado, y queda forzado a sí mismo como único encargado al crear uno.
- No hay un CRUD de usuarios aparte para instrumentos: se crean y gestionan con el mismo `/api/admin/usuarios/` de siempre (ver HU-09b en [USER_STORIES.md](USER_STORIES.md)), que ahora incluye `instrumentos_a_cargo` junto a `jornadas_propias` en la respuesta — una sola vista "universal" de todo lo que un usuario tiene asignado en ambos módulos.

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

### HU-41 — Vincular un instrumento a una jornada
Como administrador o encargado quiero poder asociar un instrumento a una jornada concreta (ej. el diagnóstico que se aplica como parte de una de sus sesiones de trabajo), para verlo agrupado junto a sus momentos y dejar que ambos compartan quién los administra.
- `Instrumento.jornada` (opcional, `null`) vincula el instrumento — `POST`/`PATCH /api/admin/instrumentos/` con `{"jornada": <id>}`; `PATCH` con `{"jornada": null}` lo desvincula. Un instrumento puede seguir existiendo suelto (sin jornada) como siempre — esto es aditivo, no rompe los instrumentos que ya existían antes de este campo.
- **Cuando está vinculado, `encargados` deja de usarse para scoping**: quién lo administra pasa a ser exactamente `Jornada.propietarios` de la jornada vinculada — un solo lugar para gestionar el acceso a todo el paquete (jornada + sus momentos + sus instrumentos), en vez de mantener dos listas de encargados por separado. `GET /api/admin/instrumentos/{slug}/` expone `jornada_nombre` de lectura para no tener que resolverlo aparte.
- Un usuario de dependencia solo puede vincular un instrumento a una jornada que le pertenece (403 si intenta vincularlo a una ajena) — igual control de acceso que crear un momento bajo esa jornada.
- Al **desvincular** un instrumento de su jornada, el usuario de dependencia que lo desvincula queda automáticamente como su único encargado — sin esto, el instrumento quedaría sin ningún encargado propio (nunca se usó `encargados` mientras estuvo vinculado) y desaparecería del scoping de todo el mundo, incluido quien lo desvinculó.
- `GET /api/admin/instrumentos/?jornada=<id>` filtra por jornada, igual que ya existe `?jornada=` en `/api/admin/momentos/`.
- Vincular un instrumento a una jornada **no cambia nada de su propio flujo**: sigue siendo cerrado por preregistro, con su propia revisión aceptar/rechazar y su descarga en Word — la jornada es solo un dato organizativo/de scoping, no una capa de permisos adicional sobre el instrumento en sí.

---

## Historias de usuario — Transcripciones (sesiones grabadas, informe con IA)


Una **sesión de transcripción** es una conversación grabada (reunión, entrevista, taller) — el
front captura el audio y lo transcribe vía `gpt-transcribe` por su cuenta (websocket, por chunks);
el backend nunca toca audio ni websockets, solo recibe el texto ya transcrito en fragmentos, en
tiempo real, y lo almacena. Recurso independiente de `Jornada`/`Momento`/`Participante` — no es una
encuesta con preguntas y respuestas por persona, es una conversación continua.

### HU-34 — Crear una sesión de transcripción y asignarle encargados
Como administrador o encargado quiero crear una sesión de transcripción y quedar (o dejar) asignados como sus encargados, para que solo quien la tiene a cargo pueda alimentarla y analizarla.
- `POST /api/admin/transcripciones/` crea la sesión (`slug` autogenerado desde `nombre`, `estado=en_curso`).
- Mismo scoping admin-completo/dependencia que `jornadas`/`instrumentos`: `SesionTranscripcion.encargados` (M2M) — varios encargados pueden compartir una sesión; un usuario de dependencia queda como único encargado al crearla y no puede reasignarla, un admin completo sí.
- Se crean y gestionan con el mismo `/api/admin/usuarios/` de siempre — ahora incluye `transcripciones_a_cargo` junto a `jornadas_propias` e `instrumentos_a_cargo` en la respuesta (ver HU-09b en [USER_STORIES.md](USER_STORIES.md)).

### HU-35 — Recibir fragmentos de transcripción en tiempo real desde el front
Como front-end (autenticado como el encargado de la sesión) quiero mandar los pedazos de texto que `gpt-transcribe` va devolviendo, a medida que llegan, para que la transcripción quede guardada sin tener que esperar a que termine la sesión.
- `POST /api/admin/transcripciones/{slug}/fragmentos/` recibe `{"fragmentos": [{"secuencia", "texto", "hablante"?, "inicio_ms"?, "fin_ms"?}, ...]}` — uno o varios de una vez.
- `secuencia` la asigna el front (0, 1, 2, ...), no el servidor: la ingesta hace `update_or_create` por `(sesion, secuencia)`, así que **reenviar el mismo fragmento por un reintento de red nunca lo duplica**, y el orden final no depende de en qué orden llegaron los paquetes por la red.
- Rechaza con 400 si la sesión ya está `cerrada` — no se aceptan más fragmentos una vez cerrada.
- `GET /api/admin/transcripciones/{slug}/transcripcion/` devuelve el texto completo reconstruido (fragmentos ordenados por `secuencia`, con el hablante entre corchetes si se indicó) — sirve tanto para ver la transcripción **en vivo** mientras la sesión está en curso, como para revisarla después.

<details><summary>Ejemplo — <code>POST /api/admin/transcripciones/reunion-comite/fragmentos/</code></summary>

Request:
```json
{
  "fragmentos": [
    { "secuencia": 0, "texto": "Buenas tardes a todos, empecemos con la agenda.", "hablante": "Moderador" }
  ]
}
```

Response `201`: la lista de fragmentos guardados (o actualizados, si la `secuencia` ya existía).
</details>

### HU-36 — Cerrar una sesión y corregir la transcripción antes de analizar
Como encargado quiero cerrar la sesión cuando termina y poder corregir cualquier error de transcripción antes de pedir el informe, para no analizar texto mal transcrito.
- `POST /api/admin/transcripciones/{slug}/cerrar/` marca `estado=cerrada` y `cerrada_en` — 400 si ya estaba cerrada. A partir de acá deja de aceptar fragmentos nuevos (HU-35).
- Mientras la sesión está `en_curso`, los fragmentos **no se pueden editar ni borrar a mano** (solo llegan por streaming) — evita pisar el flujo en vivo.
- Una vez `cerrada`: `GET /api/admin/transcripcion-fragmentos/?sesion={id}` lista cada fragmento; `PATCH /api/admin/transcripcion-fragmentos/{id}/` corrige su texto; `DELETE /api/admin/transcripcion-fragmentos/{id}/` quita un fragmento basura (ruido, silencio mal transcrito) — ambos responden 400 si la sesión sigue `en_curso`.

### HU-37 — Generar el informe de una sesión larga por mapa-reducción con IA
Como encargado quiero pedir un informe de la sesión ya cerrada, para obtener un resumen ejecutivo y los hallazgos de la conversación sin tener que leerla entera.
- `POST /api/admin/transcripcion-informes/` con `{"sesion": <id>}` — 400 si la sesión no está `cerrada` todavía (no tiene sentido analizar una grabación a medias).
- Sesiones largas (hasta 4 horas, ~35-40 mil palabras) no van en una sola llamada a OpenAI — se parten en tramos cronológicos de ~8000 palabras: cada tramo se resume en paralelo (**mapa**), y una última llamada sintetiza todos los resúmenes parciales en el informe final (**reduce**) — mismo principio jerárquico que ya usa `analysis.py` (pregunta → momento → jornada), pero por tramos de transcripción. Si un tramo falla, no tumba el informe completo: se sintetiza con los tramos que sí funcionaron (los fallidos quedan listados en `resultado.tramos_con_error`).
- Asíncrono, mismo patrón que `AnalisisJornadaIA` en `analitica`: `estado` pendiente/procesando/completo/error, 409 si ya hay un informe en proceso **para esa misma sesión** (no bloquea otras sesiones — cada llamada a OpenAI es independiente), auto-sanado si quedó huérfano por más de 15 minutos (un poco más que el resto porque el mapa-reducción de una sesión de 4h tarda más).
- `resultado`: `resumen_ejecutivo`, `temas_discutidos[]`, `hallazgos[]` (cada uno con `titulo`, `descripcion` y `citas[]` textuales reales) — a diferencia de los reportes de `analitica`, acá **no hay `tipo_grafica`/`datos`**: una conversación libre no tiene conteos reales que graficar, así que forzar cifras sería inventarlas.
- `GET /api/admin/transcripcion-informes/?sesion={id}` lista el historial de informes de esa sesión (se puede volver a pedir uno si se corrigió la transcripción después); `GET /api/admin/transcripcion-informes/{id}/` consulta uno puntual hasta que `estado` sea `completo`.

<details><summary>Ejemplo — <code>GET /api/admin/transcripcion-informes/7/</code> (completo, recortado)</summary>

```json
{
  "id": 7,
  "sesion": "reunion-comite",
  "estado": "completo",
  "resultado": {
    "sesion_id": 3,
    "resumen_ejecutivo": "El comité coincidió en priorizar el presupuesto del semestre...",
    "temas_discutidos": ["presupuesto", "cronograma", "riesgos"],
    "hallazgos": [
      {
        "titulo": "Consenso sobre el ajuste presupuestal",
        "descripcion": "Varios integrantes coincidieron en que el presupuesto actual no cubre...",
        "citas": ["\"con lo que tenemos no alcanza para el segundo semestre\""]
      }
    ],
    "tramos_analizados": 4
  },
  "modelo_usado": "Generado con IA",
  "completado_en": "2026-09-14T15:03:02.114Z"
}
```
</details>

### HU-38 — Generar una presentación HTML del informe (experimental)
Como encargado quiero una versión maquetada del informe para presentar, igual que ya existe para los reportes de jornadas.
- `POST /api/admin/transcripcion-informes/{id}/generar-presentacion/` — 400 si el informe todavía no está `completo`, 409 si ya hay una presentación en proceso para ese informe, auto-sanada tras 10 minutos huérfana.
- El HTML se guarda en `presentacion_html`, generado por OpenAI a partir de `resultado` ya calculado — nunca inventa ni modifica un hallazgo o una cita.

### HU-39 — Descargar el informe en PDF
Como encargado quiero descargar el informe en PDF, con la transcripción completa como anexo, para archivarlo o entregarlo.
- `GET /api/admin/transcripcion-informes/{id}/pdf/` — 400 si el informe no está `completo`. Armado 100% en el servidor con reportlab a partir de `resultado` y los fragmentos ya guardados, sin ninguna llamada externa: portada, resumen ejecutivo, temas, una tarjeta por hallazgo con sus citas, y un anexo final con la transcripción completa fragmento por fragmento.

### HU-40 — Aislamiento entre sesiones y protección por dependencia
Como usuario de dependencia quiero que solo pueda ver/editar las sesiones de transcripción que tengo a cargo, para que las de otras áreas queden protegidas.
- Un usuario de dependencia sin acceso a una sesión no la ve al listar (`GET /api/admin/transcripciones/`) y recibe 404 al pedirla por slug directo.
- Pedir un informe (HU-37) de una sesión ajena responde 403, igual que en `jornadas`/`instrumentos`.

### HU-42 — Vincular una grabación a una jornada, e incluirla o no en su análisis
Como administrador o encargado quiero poder asociar una sesión de transcripción a una jornada concreta y decidir si su contenido debe tomarse en cuenta al analizar esa jornada, para tratar la grabación como una fuente de evidencia más junto a los momentos, no como algo aislado.
- `SesionTranscripcion.jornada` (opcional, `null`) vincula la grabación — `POST`/`PATCH /api/admin/transcripciones/` con `{"jornada": <id>}`; `PATCH` con `{"jornada": null}` la desvincula. Una grabación puede seguir existiendo suelta como siempre — mismo mecanismo aditivo que HU-41 en [USER_STORIES_INSTRUMENTOS.md](USER_STORIES_INSTRUMENTOS.md), y las mismas reglas de scoping: vinculada, hereda `Jornada.propietarios` (encargados propios dejan de usarse); un usuario de dependencia solo puede vincularla a una jornada que le pertenece (403 si no); al desvincularla, queda automáticamente como su único encargado.
- `incluir_en_analisis_jornada` (booleano, default `true`) solo tiene efecto cuando la grabación está vinculada: decide si su informe entra o no al pedir el análisis de la jornada completa (`AnalisisJornadaIA`, HU-14g en [USER_STORIES.md](USER_STORIES.md)).
- **El análisis de jornada reutiliza el informe YA CALCULADO de la grabación** (`InformeTranscripcion.resultado` — `resumen_ejecutivo`/`temas_discutidos`/`hallazgos` de su propio informe `completo` más reciente) — nunca vuelve a leer la transcripción cruda ni relanza el mapa-reducción de HU-37. Si la grabación no tiene ningún informe `completo` todavía, simplemente no aporta nada al análisis de jornada (no bloquea ni da error).
- El análisis de la propia grabación (HU-37) sigue siendo 100% independiente — vincularla a una jornada y pedir el análisis de la jornada no reemplaza ni modifica su `InformeTranscripcion` propio.
- `GET /api/admin/transcripciones/?jornada=<id>` filtra por jornada, igual que `?jornada=` en `/api/admin/momentos/` e `/api/admin/instrumentos/`.

---

## Módulo: Diagnóstico de Articulación Académica (jornada con momento único + extracción por IA)

Formato: **Como** `<rol>` **quiero** `<acción>` **para** `<beneficio>`, con criterios de aceptación.
Caso de uso concreto sobre el módulo base de jornadas/participantes (más arriba en este mismo
archivo): el "Instrumento de Diagnóstico para la Articulación Académica" de la Universidad del
Magdalena (11 secciones, 90 preguntas del documento original, varias en formato de matriz),
montado como una jornada normal en vez de usar el módulo `instrumentos` (ver más abajo), porque el
frontend de administración de jornadas no tiene ninguna vista para ese módulo — solo sabe mostrar
`Momento`/`Pregunta`.

### HU-43 — Ver el diagnóstico como parte de una jornada, en un único recorrido fluido, con matrices reales
Como administrador quiero que el instrumento de diagnóstico aparezca en la pantalla normal de jornada (pestaña "Instrumento" = Momentos/Preguntas) y que sus tablas se representen como matrices reales (fila × columna), no como preguntas sueltas, para no depender de una vista aparte y para que el frontend pueda dibujarlas como tabla en vez de una lista plana de campos.
- El diagnóstico vive en la jornada `diagnostico-articulacion-academica`, con un **único** `Momento` ("Instrumento de Diagnóstico para la Articulación Académica") que agrupa **90 preguntas** — la misma cantidad que el documento original, porque desde que `Pregunta` soporta tipo `matriz` cada tabla del documento se guarda como UNA pregunta matriz (con sus filas y columnas reales), no aplanada celda por celda.
- **7 de esas 90 preguntas son tipo `matriz`**: Matriz de responsabilidades (12 filas × 4 columnas), Análisis de coherencia académica × 3 componentes (7 filas × 4 columnas cada uno), Mapa de capacidades profesorales (12 filas × 6 columnas), Asuntos para decisión institucional (8 filas × 4 columnas), Compromisos inmediatos (8 filas × 4 columnas).
- `GET /api/admin/momentos/?jornada=<id_jornada>` → 1 resultado. `GET /api/admin/preguntas/?momento=<id_momento>` → 90 resultados; cada pregunta tipo `matriz` trae `filas: [{id, texto, orden}, ...]` y `columnas: [{id, texto, orden}, ...]` anidadas — el frontend arma la tabla directo de ahí, sin parsear texto ni adivinar agrupaciones.
- El comando `python manage.py migrar_diagnostico_a_momentos` (idempotente) reconstruye este momento a partir del contenido ya cargado en `instrumentos.Instrumento` (slug `diagnostico-articulacion-academica`, cargado con `cargar_instrumento_diagnostico_articulacion` — ver módulo Instrumentos) — no retipea ningún texto, copia cada pregunta matriz 1:1 con sus filas/columnas reales (versión anterior de este comando las aplanaba porque `Pregunta` todavía no soportaba `matriz`; ya no aplica).

Ver **HU-46** para el detalle completo del soporte de matriz en `jornadas`/`participantes` (modelo, endpoints de fila/columna, envío y validación) — es una capacidad general del backend, no algo exclusivo de este diagnóstico.

### HU-44 — Subir un documento ya diligenciado (Word o PDF) para transcribirlo con IA
Como administrador quiero subir el diagnóstico de un departamento que ya lo llenó en papel o Word antes de que existiera el sistema, para no tener que re-transcribirlo campo por campo a mano.
- `POST /api/admin/momento-extracciones/` (`multipart/form-data`, requiere admin autenticado).
- Campos: `momento` (id, obligatorio), `archivo` (`.pdf` o `.docx`, obligatorio — cualquier otro formato responde `400`), y quién es el dueño del documento: `participante_id` (de alguien ya registrado en la jornada) **o** `correo_institucional`+`nombre`+`apellido`+`rol` (+ `telefono` opcional) para registrarlo de una vez si no existe.
- El procesamiento corre en segundo plano — una sola llamada a OpenAI (GPT-4o) lee el documento: texto directo si es seleccionable (`.docx` siempre, o PDF con texto), o las páginas como imagen (visión) si es un PDF escaneado/a mano. `estado` pasa `pendiente` → `procesando` → `completo`/`error`; el frontend hace polling a `GET /api/admin/momento-extracciones/<id>/` hasta que deje de estar en curso.
- Preguntas que la IA no pudo transcribir con confianza (en blanco, ilegible, o una inconsistencia de validación) quedan listadas en `preguntas_omitidas`, sin respuesta — no bloquean el resto.

<details><summary>Ejemplo — <code>POST /api/admin/momento-extracciones/</code></summary>

Request (`multipart/form-data`):
```
momento: 12
archivo: diagnostico_sistemas.docx
correo_institucional: jefe.sistemas@unimagdalena.edu.co
nombre: Juan
apellido: Pérez
rol: Jefe de departamento
```

Response `201`:
```json
{
  "id": 7,
  "momento": 12,
  "momento_titulo": "Instrumento de Diagnóstico para la Articulación Académica",
  "participante": 258,
  "participante_nombre": "Juan Pérez",
  "nombre_archivo_original": "diagnostico_sistemas.docx",
  "estado": "pendiente",
  "resultado": {},
  "preguntas_omitidas": [],
  "error_mensaje": "",
  "modelo_usado": "",
  "aprobado_en": null,
  "aprobado_por": null,
  "solicitado_por": 3,
  "creado_en": "2026-09-15T10:00:00-05:00"
}
```
</details>

### HU-45 — Revisar y aprobar una extracción antes de que cuente como respuesta real
Como administrador quiero revisar lo que la IA transcribió antes de que se guarde como respuesta oficial del departamento, para poder detectar un error de lectura sin que quede mezclado con datos reales — hoy no existe forma de corregir una `Respuesta` ya guardada desde el admin (`RespuestaAdminViewSet` es de solo lectura), así que la única ventana de revisión real es antes de escribirla.
- `GET /api/admin/momento-extracciones/<id>/` — con `estado: "completo"`, el campo `resultado` trae `{"respuestas": [{"pregunta": <id>, "texto_libre": "...", "opcion_ids": [...], "fila_id": <id o null>, "columna_id": <id o null>}]}` **sin haber tocado ninguna `Respuesta` real todavía** — `fila_id`/`columna_id` solo vienen con valor en preguntas tipo `matriz` (una entrada por celda). El frontend debería cruzar cada `pregunta` id contra `GET /api/admin/preguntas/?momento=<id>` para mostrar el texto de la pregunta (y, si es matriz, el texto de la fila/columna) junto a lo transcrito.
- `POST /api/admin/momento-extracciones/<id>/aprobar/` — recién acá se copia `resultado` a `Respuesta` reales del participante (mismas reglas de validación que un envío normal desde la web) y se marca `aprobado_en`/`aprobado_por`. Responde `403` si ya estaba aprobada, `400` si `estado` todavía no es `"completo"`.
- No hay endpoint de "rechazar": si el resultado no sirve, simplemente no se aprueba y se sube el documento de nuevo, o se le pide a la persona que lo diligencie directo en la web.
- `GET /api/admin/momento-extracciones/?momento=<id>` lista todas las extracciones de un momento — útil para un panel de "documentos pendientes de revisión" filtrando client-side por `estado == "completo" && !aprobado_en`.
- Mismo scoping admin-completo/dependencia que el resto de la app: un usuario de dependencia solo ve/crea extracciones de momentos de jornadas donde es propietario (`filtrar_por_propietario` sobre `momento__jornada__propietarios`).

### HU-46 — Preguntas tipo matriz en cualquier jornada (no solo el diagnóstico)
Como administrador quiero crear una pregunta de tipo matriz (fila × columna) en cualquier momento de cualquier jornada, para modelar tablas comparativas sin tener que inventar una pregunta suelta por celda — capacidad general del backend, igual a como ya existía en el módulo `instrumentos` (`PreguntaInstrumento`/`FilaMatrizInstrumento`/`ColumnaMatrizInstrumento`), ahora también en `jornadas`/`participantes`.
- `Pregunta.tipo` ahora acepta `matriz` además de `abierta`/`unica`/`multiple`. Una pregunta tipo matriz no tiene `opciones` — en su lugar tiene `filas` y `columnas`, cada una un texto + orden.
- `POST /api/admin/preguntas-filas-matriz/` y `POST /api/admin/preguntas-columnas-matriz/` (`{"pregunta": <id>, "texto": "...", "orden": <n>}`) agregan filas/columnas a una pregunta matriz — mismo patrón CRUD que `/api/admin/opciones/` para preguntas de selección. `GET`/`PATCH`/`DELETE` también disponibles, filtrando por `?pregunta=<id>`.
- `GET /api/admin/preguntas/?momento=<id>` — cada pregunta tipo matriz trae `filas`/`columnas` anidadas en la respuesta, listas para dibujar la tabla sin llamadas adicionales.
- **Envío de respuestas** (`POST .../momentos/{id}/respuestas/`, mismo endpoint de siempre): una pregunta matriz se responde con **una entrada por celda**, todas con el mismo `pregunta_id` pero distinto `fila_id`/`columna_id`:
  ```json
  {"respuestas": [
    {"pregunta_id": 901, "fila_id": 1, "columna_id": 1, "texto_libre": "El jefe de departamento"},
    {"pregunta_id": 901, "fila_id": 1, "columna_id": 2, "texto_libre": "El comité curricular"}
  ]}
  ```
  `fila_id`/`columna_id` son opcionales (`null` o ausentes) en preguntas que NO son matriz — mandarlos ahí es 400. En una pregunta matriz son obligatorios y deben pertenecer a esa pregunta — mandar la fila/columna de otra pregunta también es 400.
- **Obligatoriedad de una matriz** se evalúa por *todas* sus celdas: si `obligatoria=true`, faltan celdas mientras no haya una respuesta con `texto_libre` no vacío para cada combinación fila×columna — el error `faltantes` devuelve el id de la pregunta (no celda por celda) si falta aunque sea una.
- `Respuesta` ahora tiene `fila`/`columna` (nulos salvo en preguntas matriz) — una fila de `Respuesta` por celda, igual que ya hacía `RespuestaInstrumento` en el módulo `instrumentos`.
- La extracción por IA (HU-44/HU-45) ya soporta este tipo: el esquema que se le manda al modelo incluye `filas`/`columnas` cuando la pregunta es matriz, y el prompt le pide una entrada por celda con `fila_id`/`columna_id`.

### HU-47 — Ver mis respuestas ya guardadas de un momento
Como usuario quiero poder recuperar lo que ya respondí en un momento (no solo enviarlo), para que si vuelvo más tarde — cerré el navegador, cambié de dispositivo, quiero revisar antes de avanzar — el formulario se muestre prellenado en vez de en blanco, y HU-23 (corregir una respuesta) tenga sentido en una UI real: hasta ahora el único `GET` de un momento (HU-20) devuelve la estructura (preguntas/opciones/filas/columnas), nunca lo que ya se respondió.
- `GET /api/jornadas/{slug}/momentos/{id}/respuestas/` — mismo endpoint que HU-21/HU-22/HU-23, ahora también acepta `GET`. Devuelve la lista de `Respuesta` ya guardadas, mismo shape que la respuesta de un `POST`.
- Mismo criterio de dueño que al enviar: en un momento `individual` se filtra por mi `Participante`; en un momento tipo `mesa` se filtra por mi `mesa` — cualquier integrante de la mesa puede **ver** lo ya respondido, aunque solo el vocero (HU-22) pueda **escribir**. Si todavía no tengo mesa asignada, devuelve `[]` en vez de error.
- En preguntas tipo matriz (HU-46) trae una entrada por celda ya respondida (`fila`/`columna` con valor); en el resto, `fila`/`columna` vienen `null`.

<details><summary>Ejemplo — <code>GET /api/jornadas/diagnostico-articulacion-academica/momentos/41/respuestas/</code></summary>

Response `200` (probado contra un participante real con 12 de 81 preguntas ya respondidas):
```json
[
  { "id": 4792, "pregunta": 832, "participante": 343, "mesa": null, "fila": null, "columna": null, "texto_libre": "Departamento de Estudios Generales", "opciones": [], "actualizado_en": "2026-09-15T22:05:11.000Z" },
  { "id": 4801, "pregunta": 843, "participante": 343, "mesa": null, "fila": null, "columna": null, "texto_libre": "", "opciones": [], "actualizado_en": "2026-09-15T22:03:24.000Z" }
]
```
Nota: se devuelve una `Respuesta` por cada pregunta a la que el participante ya llegó a responder, incluidas las que dejó con `texto_libre` vacío — el front distingue "todavía no llegó a esta pregunta" (no aparece en la lista) de "llegó pero la dejó vacía" (aparece con `texto_libre: ""`).
</details>

### HU-48 — Restringir momentos y preguntas por rol institucional (además de por mesa)
Como administrador quiero poder limitar qué participantes ven un momento o una pregunta según su rol institucional (ej. "solo directivos", "solo docentes"), igual que ya se puede limitar por mesa (HU-03/HU-05), para dinámicas donde ciertos contenidos no aplican a todos los roles de la jornada.
- `Momento.roles_permitidos` y `Pregunta.roles_permitidos` — mismo patrón que `mesas_permitidas`: lista opcional de nombres de rol (`JSONField`), vacía = visible para todos. A diferencia de mesa (que solo aplica en momentos tipo `mesa`), rol **aplica siempre** — todo participante tiene un `rol`, sea el momento individual o de mesa.
- Si un momento/pregunta restringe ambos (`mesas_permitidas` y `roles_permitidos`), se combinan por **AND**: hay que cumplir las dos condiciones.
- Se edita vía `PATCH /api/admin/momentos/{id}/` / `PATCH /api/admin/preguntas/{id}/`, mismos endpoints que ya existían — no hay endpoint nuevo para esto, solo el campo nuevo en el serializer.
- La restricción se aplica en los tres lugares donde ya se filtraba por mesa: índice de momentos (HU-19), detalle de un momento (HU-20) y envío/lectura de respuestas (HU-21/HU-47) — reutiliza la misma función de visibilidad, no una lógica paralela.
- `Participante.rol` **sigue siendo texto libre** (sin cambios, sin migración de datos existentes) — la comparación es directa contra ese texto, no contra un catálogo obligatorio.

### HU-49 — Catálogo de roles por jornada
Como administrador quiero poder definir la lista de roles válidos de una jornada (para tener qué mostrar en HU-48 y, opcionalmente, en el formulario de registro), sin que esto sea obligatorio — una jornada que nunca define roles sigue funcionando exactamente igual que antes.
- Nuevo modelo `RolJornada` (`jornada` + `nombre`, únicos por jornada) — **no reemplaza** `Participante.rol` (que sigue siendo texto libre): es solo un catálogo de referencia, igual que mesa no tiene un modelo propio (`mesa` es un entero simple en `Participante`).
- Admin: `GET/POST /api/admin/jornadas-roles/?jornada=<id>`, `GET/PATCH/DELETE /api/admin/jornadas-roles/{id}/` — mismo patrón CRUD que `preguntas-filas-matriz`/`opciones`, mismo scoping admin-completo/dependencia.
- Público: `GET /api/jornadas/{slug}/roles/` — sin autenticación, para que el front pueda mostrar los roles definidos como opciones en el registro (HU-17). Una jornada sin roles definidos devuelve `[]`.

<details><summary>Ejemplo — definir roles y restringir un momento</summary>

```bash
POST /api/admin/jornadas-roles/
{ "jornada": 12, "nombre": "directivo" }

POST /api/admin/jornadas-roles/
{ "jornada": 12, "nombre": "docente" }

PATCH /api/admin/momentos/41/
{ "roles_permitidos": ["directivo"] }
```

Un participante con `rol: "docente"` deja de ver el momento 41 en `GET /api/jornadas/{slug}/momentos/` (HU-19) y recibe `404` si intenta acceder directo a `GET .../momentos/41/` (HU-20) — mismo comportamiento que ya existía para mesas no permitidas.
</details>

### HU-50 — Preguntas condicionadas por la respuesta a otra pregunta
Como administrador quiero que una pregunta solo aparezca si el participante ya marcó una opción específica en una pregunta anterior (de la misma jornada, sea del mismo momento o de otro), para no mostrar preguntas que no aplican según lo ya respondido.
- `Pregunta.depende_de_opcion` — FK opcional a una `OpcionPregunta` de **otra pregunta de la misma jornada** (se valida al crear/editar: `400` si es de otra jornada, o si una pregunta intenta depender de sí misma). `null` = sin condición, visible siempre (según mesa/rol, igual que hoy). **No tiene que ser del mismo momento** — un cuestionario real con un momento por bloque/letra (A, B, C...) necesita justo esto: la pregunta C5 del bloque C puede depender de la A5 del bloque A, cada una en su propio momento.
- A diferencia de `mesas_permitidas`/`roles_permitidos` (estáticos, dependen solo de quién es el participante), esto depende de una `Respuesta` ya guardada — se evalúa contra la base en cada consulta, no se cachea nada.
- **Un momento se responde completo en un solo `POST`**: si la pregunta disparadora y la condicionada van en el mismo envío, la disparadora todavía no está guardada en la base cuando se valida la condicionada — por eso las opciones marcadas en ese mismo envío también cuentan como "ya cumplida la condición", no solo lo que ya había en la base de antes.
- Se aplica en los mismos lugares que mesa/rol: `GET .../momentos/{id}/` (HU-20, la pregunta condicionada no aparece hasta que se cumpla) y `POST .../respuestas/` (HU-21, se rechaza con `400` si se intenta responder una condicionada que todavía no debería estar habilitada).
- Una pregunta condicionada que además es `obligatoria=true` **no cuenta como obligatoria** mientras su condición no se cumpla (HU-24) — no tiene sentido exigir una respuesta a algo que ni siquiera debería mostrarse.

<details><summary>Ejemplo — "¿Tiene hijos?" → "¿Cuántos?"</summary>

```bash
# Pregunta 10: "¿Tiene hijos?" (única), con opciones 101="Sí", 102="No"
PATCH /api/admin/preguntas/11/
{ "depende_de_opcion": 101 }   # Pregunta 11: "¿Cuántos hijos tiene?"
```

Antes de responder la pregunta 10, `GET .../momentos/{id}/` no incluye la pregunta 11 en absoluto. Al enviar:
```json
{ "respuestas": [
  { "pregunta_id": 10, "opcion_ids": [101] },
  { "pregunta_id": 11, "texto_libre": "2" }
] }
```
ambas se guardan en el mismo `POST` — la 11 se acepta porque la opción 101 viene en el mismo envío, aunque la 10 todavía no estuviera guardada al momento de validar.
</details>

### HU-51 — Pregunta tipo "lista": columnas fijas, filas las agrega quien responde
Como administrador quiero un tipo de pregunta para tablas donde no sé de antemano cuántas filas va a haber (ej. "Mapa de capacidades profesorales": columnas fijas — Profesor(a), Formación, Área de experticia... — pero cada departamento reporta el número de profesores que tenga), porque `matriz` (HU-46) exige que tanto filas como columnas estén fijadas por el admin de antemano y ese no es el caso acá.
- `Pregunta.tipo` ahora acepta `lista` además de `abierta`/`unica`/`multiple`/`matriz`. Una pregunta tipo lista **reutiliza `ColumnaMatrizPregunta`** para sus columnas (mismos endpoints `POST/GET/PATCH/DELETE /api/admin/preguntas-columnas-matriz/` de HU-46, sin necesidad de un endpoint nuevo) — pero **no tiene `FilaMatrizPregunta`**, porque las filas no las define el admin.
- Nuevo modelo `FilaListaRespuesta` (`participantes/models.py`) — una fila que el **participante** agregó al responder, no el admin. `Respuesta` gana un campo `fila_lista` (FK opcional, mutuamente excluyente con `fila` que sigue siendo solo para matriz).
- **Envío de respuestas** (`POST .../momentos/{id}/respuestas/`, mismo endpoint de siempre): una celda de tipo lista se manda con `columna_id` + un **`fila_temporal`** — un número que el propio cliente inventa para decir "estas celdas van en la misma fila" (no es el id de nada que ya exista en la base):
  ```json
  {"respuestas": [
    {"pregunta_id": 950, "fila_temporal": 1, "columna_id": 700, "texto_libre": "Juan Pérez"},
    {"pregunta_id": 950, "fila_temporal": 1, "columna_id": 701, "texto_libre": "Magíster"},
    {"pregunta_id": 950, "fila_temporal": 2, "columna_id": 700, "texto_libre": "Ana Gómez"},
    {"pregunta_id": 950, "fila_temporal": 2, "columna_id": 701, "texto_libre": "Doctora"}
  ]}
  ```
  El backend agrupa las celdas por `fila_temporal`, crea una `FilaListaRespuesta` por cada grupo, y guarda una `Respuesta` por celda apuntando a esa fila.
- **Cada envío reemplaza por completo las filas existentes** de esa pregunta para ese dueño (participante o mesa) — a diferencia de matriz/abierta/única, que hacen `update_or_create` celda por celda, acá no se intenta emparejar filas de un envío con filas de un envío anterior (un `fila_temporal=1` de hoy no es necesariamente la misma fila que un `fila_temporal=1` de ayer). Reenviar con menos filas que antes borra las que sobran; con más, las agrega.
- **Obligatoriedad** (HU-24): se exige que **al menos una fila** tenga **todas** sus columnas respondidas — no que todas las filas estén completas, solo que exista al menos un registro real.
- ~~**Límite conocido**: el extractor de documentos con IA (HU-44/45) todavía no sabe llenar preguntas tipo lista.~~ Resuelto en HU-54: ya las transcribe.

### HU-52 — Pregunta tipo "audio": el cliente graba y transcribe, el backend guarda solo el texto
Como administrador quiero poder pedir una respuesta hablada (ej. "cuéntanos en voz alta qué te llevas de la jornada"), porque hay participantes a quienes se les da mucho mejor hablar que escribir, sin que eso obligue al backend a recibir, almacenar ni servir archivos de audio.
- `Pregunta.tipo` ahora acepta `audio` además de `abierta`/`unica`/`multiple`/`matriz`/`lista`.
- **El backend nunca ve un audio**: el front graba, hace la transcripción **de su lado** y manda únicamente el texto. No hay endpoint de subida, no hay campo de archivo, no hay URL de audio en ninguna respuesta. Lo que se guarda es `Respuesta.texto_libre`, exactamente igual que en una pregunta `abierta`.
- **Se responde igual que una `abierta`** (mismo endpoint `POST .../momentos/{id}/respuestas/`):
  ```json
  {"respuestas": [
    {"pregunta_id": 1400, "texto_libre": "Me llevo la idea de que el diálogo de saberes no es un paso previo, es el método."}
  ]}
  ```
  `400` si se mandan `opcion_ids`, `fila_id`, `columna_id` o `fila_temporal`. **Obligatoriedad** (HU-24): igual que `abierta` — un `texto_libre` vacío o solo con espacios no cuenta como respondida.
- **Por qué es un tipo propio y no un `abierta` con una bandera**: el backend guarda lo mismo, pero el front necesita saber qué renderizar (grabador + transcriptor vs. textarea), y la analítica poder distinguir de dónde salió el texto. Un booleano sobre `abierta` dejaría a `tipo` mintiendo sobre lo que la pregunta es y obligaría a mirar dos campos en cada rama.
- **Analítica y exportes**: `audio` cuenta como texto libre en todas partes (tópicos/BERTopic, análisis por IA, Excel), vía `Pregunta.TIPOS_TEXTO_LIBRE` — la tupla que agrupa `abierta` + `audio` y que toda rama que pregunte "¿es de texto libre?" debe usar. Sin eso una pregunta `audio` caía en la rama de opción cerrada y se reportaba con 0 respuestas aunque las transcripciones estuvieran guardadas.
- **Alcance**: solo `jornadas.Pregunta`. `instrumentos.PreguntaInstrumento` es otro modelo, con su propio flujo, y no se tocó.
- **Límite conocido**: el backend no valida idioma, longitud ni calidad de la transcripción — confía en lo que mande el cliente, igual que con cualquier texto libre. Si algún día se quisiera conservar el audio original, sería otro modelo y otro ticket (con sus propias decisiones de almacenamiento y retención).

### HU-53 — `filas_adicionales`: permitir que quien responde agregue filas
Como administrador quiero poder decidir, al crear una pregunta de tabla, si quien responde puede **agregar filas** además de las que yo definí — porque hay tablas donde conozco de antemano unas filas obligatorias pero no puedo saber cuántas más va a necesitar cada quien (ej. las áreas fijas de siempre, más las que cada dependencia tenga de propia).
- `Pregunta` gana el campo booleano `filas_adicionales`, editable en `POST/PATCH /api/admin/preguntas/` y visible para el participante en `GET .../momentos/{id}/` (es lo único que le dice al front si debe pintar el botón de "agregar fila").
- **Defaults por tipo**, resueltos en `PreguntaAdminSerializer` y no en el modelo (un `BooleanField` admite un solo `default` y acá depende de `tipo`; además el serializer es la única capa que distingue "no mandaron el campo" de "lo mandaron en `false`"):
  - `matriz` → `false` (filas fijas, como siempre).
  - `lista` → `true`.
  - resto de tipos → `false`, y mandarlo en `true` es `400` (no significa nada ahí).
- **Una `lista` no puede apagarlo** (`400`): sus filas son, por definición, las que agrega quien responde — con el flag apagado la pregunta quedaría sin ninguna forma de responderse, y si es obligatoria bloquearía el momento completo. El campo existe igual en las listas, pero fijo en `true`.
- **El caso nuevo de verdad es la matriz mixta**: con el flag encendido, una misma pregunta acepta en el mismo envío celdas de fila fija (`fila_id`) y celdas de fila agregada (`fila_temporal`), y al leerlas vienen con `fila` o con `fila_lista` respectivamente. `400` si una celda trae los dos.
- **Reutiliza `FilaListaRespuesta`** (HU-51) para las filas extra en vez de un modelo nuevo: es exactamente el mismo concepto —una fila que puso quien responde— y `Respuesta.fila_lista` ya sabía apuntar a ella.
- **Obligatoriedad sin cambios**: en una matriz sigue siendo "todas las celdas fijas". Las filas extra son extra, nunca obligatorias, y mandarlas no sustituye una celda fija faltante.
- **Reemplazo total de las filas extra** en cada envío, igual que en `lista`: reenviar el momento sin celdas `fila_temporal` borra todas las extra. Las fijas no se tocan.
- De paso, `POST .../momentos/{id}/respuestas/` pasó a ser **atómico**. Las filas dinámicas se borran y se recrean en cada envío, así que sin transacción una celda inválida más adelante dejaba el envío a medias: las filas viejas ya borradas y las nuevas a medio escribir. Ahora entra el momento completo o no entra nada.
- El extractor de documentos con IA (HU-44/45) también transcribe filas agregadas — ver HU-54.

### HU-54 — El extractor por IA transcribe también las filas agregadas
Como administrador quiero que, al subir un documento ya diligenciado, la IA transcriba también las filas que quien lo llenó **agregó a mano** (un renglón extra al final de la tabla, una hoja anexa con más registros) — porque desde HU-53 una matriz puede aceptarlas, y hasta ahora el extractor solo sabía llenar las filas fijas del esquema.
- El esquema que se le manda a la IA ahora incluye, por pregunta, **`filas_adicionales`** — es lo que le permite decidir pregunta por pregunta si puede transcribir filas que no están en el esquema. También se corrigió que el esquema solo mandaba `columnas` en las preguntas `matriz`: ahora también en las `lista`, que es lo que hacía que una lista se omitiera entera (la IA no tenía a qué columna apuntar).
- **Nueva regla en el prompt**: en una pregunta con `filas_adicionales`, una fila que no esté en el esquema se transcribe con un **`fila_temporal`** que la propia IA inventa para agrupar las celdas de esa fila (1, 2, 3…), en vez de `fila_id`. Nunca los dos en la misma celda. En una pregunta sin el flag no debe usar `fila_temporal` y cualquier fila que no esté en el esquema simplemente no se transcribe.
- **`_limpiar_y_validar` valida igual que el envío normal**: reusa `participantes.views._validar_entrada` pasándole ahora también `fila_temporal`, así que una alucinación (un `fila_temporal` en una matriz de filas fijas, una celda con `fila_id` y `fila_temporal` a la vez, un `fila_temporal` que no es un número, una columna de otra pregunta) se omite limpiamente y queda en `preguntas_omitidas` en vez de tumbar la extracción.
- **`aprobar_extraccion_momento`** separa las celdas de fila fija (siguen por `update_or_create`) de las de fila agregada, y para estas crea las `FilaListaRespuesta` agrupando por `fila_temporal`, igual que el envío normal.
- **Reemplazo acotado a lo que el documento menciona**: aprobar reemplaza las filas agregadas de las preguntas que la IA sí transcribió, pero **no toca** las de una pregunta que el documento no menciona — a diferencia del envío normal desde la web, donde el cliente manda el momento completo y la ausencia sí significa "bórralas". Un documento que no habla de una pregunta no es una instrucción de borrar lo que ya había.
- `aprobar_extraccion_momento` pasó a ser **atómico**, por lo mismo que el envío normal: las filas agregadas se borran y se recrean, así que una falla a mitad dejaría la tabla del participante incompleta.
- **Efecto secundario**: con esto el extractor también llena por fin las preguntas tipo `lista`, que era el límite conocido que había quedado abierto en HU-51 — usan el mismo `fila_temporal`, así que salió del mismo mecanismo sin código aparte.

### HU-55 — El extractor por IA detecta al responsable del documento y lo empareja solo
Como administrador quiero no tener que decir **de quién es** cada documento antes de subirlo, porque ese dato casi siempre ya está escrito al principio del propio documento ("Responsable:", "Diligenciado por:", una firma al pie) y tenerlo que buscar y seleccionar a mano, uno por uno, es justo el paso que hace lento cargar un lote de documentos.
- **La IA lee, nosotros decidimos.** El prompt de los dos extractores (momentos e instrumentos) pide ahora un bloque `responsable` — `{"nombre", "correo", "cargo", "dependencia"}`, todo opcional — con el texto **tal cual aparece**, sin normalizar ni deducir. A quién corresponde ese texto **no lo decide el LLM**: se resuelve en `jornadas/emparejamiento.py`, con reglas determinísticas. Un modelo eligiendo entre personas reales es exactamente el tipo de decisión que no queremos que cambie entre corridas.
- **Escalera de emparejamiento**, de la señal más fuerte a la más débil: correo exacto (sin distinguir mayúsculas) → nombre normalizado idéntico (minúsculas, sin tildes, espacios colapsados) → todos los tokens de un nombre contenidos en el otro (cubre "José Pérez" contra "José Antonio Pérez Gómez", y al revés).
- **Ante la duda, no se empareja.** Si coinciden dos personas, el estado es `ambiguo` y **no se devuelve ninguna**: desempatar tomando la primera de la consulta le atribuiría el documento a quien salió antes, y una respuesta firmada por alguien que nunca la dio es peor que una extracción esperando asignación manual.
- **Nunca se crea una cuenta a partir de un nombre leído por IA.** Un nombre mal transcrito generaría cuentas basura y, peor, podría fabricar a la persona que justamente faltó identificar.
- **Conjunto de candidatos acotado**: en instrumentos se busca primero entre los **preregistrados de ese instrumento** y solo si ahí no hay nada entre el resto de usuarios no-staff — si se buscara de una en todos, cualquier nombre común saldría ambiguo. En momentos, los participantes de **esa jornada**.
- **El trabajo de transcripción nunca se pierde**, que es la parte fina:
  - `participantes.ExtraccionMomento` ya difería la escritura hasta `aprobar`, así que bastó con volver `participante` opcional: sin responsable no se puede aprobar (400 explicando qué se detectó) y `resultado` queda intacto.
  - `instrumentos.ExtraccionInstrumento` escribía directo sobre `AplicacionInstrumento`, que necesita un usuario. Se partió en transcribir (guarda en `resultado_crudo` nuevo) y escribir. Estado nuevo **`sin_responsable`** para el caso intermedio.
- **Asignación manual**: `POST /api/admin/instrumento-extracciones/{id}/asignar-responsable/` y `POST /api/admin/momento-extracciones/{id}/asignar-responsable/` terminan el trabajo con lo ya transcrito, **sin volver a llamar a OpenAI**. `responsable_estado` no se toca al asignar: deja constancia de *por qué* hubo que hacerlo a mano.
- `usuario_id`/`participante_id` siguen aceptándose al subir, y cuando se mandan **no se pisan** con lo que haya leído la IA — una decisión humana explícita gana. Mandar media ficha de alta sigue siendo `400`: omitir todo es delegar, mandar la mitad es un bug del cliente.

### HU-56 — Los participantes pueden subir ellos mismos su documento diligenciado
Como participante de una jornada quiero poder subir yo mismo el documento de un momento que ya llené en papel o en Word, en vez de tener que mandárselo a un administrador para que lo cargue por mí.
- `Momento.permite_carga_archivo` (booleano, **apagado por defecto**) habilita la carga momento por momento. Apagado, un participante igual recibe `403`. Está apagado por defecto a propósito: cada carga cuesta una llamada a OpenAI y deja una `ExtraccionMomento` a la espera de revisión, así que se abre cuando el equipo lo decide, no en todos de golpe.
- El campo viaja en el detalle y en el índice de momentos que ve el participante — **es lo único que le dice al FE si mostrar el botón de subir**.
- `POST /api/jornadas/{jornada_slug}/momentos/{momento_id}/cargar-archivo/` (auth de participante, `multipart` con `archivo`). La diferencia de fondo con el endpoint de admin (`ExtraccionMomentoViewSet`) no es el permiso sino **de quién es el documento**: acá el dueño es siempre quien sube (`participante = request.user`, no un dato del request), así que no se puede subir a nombre de otro, no hay responsable que emparejar y no se dan de alta participantes.
- `GET /api/jornadas/{jornada_slug}/momentos/{momento_id}/mis-cargas/` lista las cargas propias, para que el FE pueda mostrar "procesando / listo / falló" sin pegarle al endpoint de admin, al que el participante no tiene acceso.
- **Sin aprobación de un admin.** A diferencia de la carga que hace un admin a nombre de otra persona (HU-51, que sí necesita `aprobar/` porque nadie más puede corregir lo que la IA transcribió), acá el propio participante puede corregir su respuesta antes de enviarla — no hace falta que nadie más intervenga. `ExtraccionMomentoSerializer` expone `respuestas_sugeridas`: el mismo arreglo de `resultado.respuestas` pero con las claves ya renombradas al formato que espera `POST .../momentos/{id}/respuestas/` (`pregunta_id`, `texto_libre`, `opcion_ids`, `fila_id`, `columna_id`, `fila_temporal`). El FE precarga la pantalla del momento con eso, el participante corrige lo que haga falta, y lo envía tal cual a ese mismo endpoint de siempre — ahí es donde de verdad se escribe la `Respuesta`. Una pregunta que la IA no pudo transcribir simplemente no aparece en `respuestas_sugeridas` (y sí en `preguntas_omitidas`), para que el participante la complete a mano.

> Nota de implementación: esta historia se construyó originalmente sobre `Instrumento` (el otro
> módulo de formularios de la app, independiente de `Momento`) y se movió acá porque la necesidad
> real era la carga por momento de jornada, no por instrumento. `Instrumento` no tiene (ni tuvo
> nunca en producción) esta capacidad de autoservicio.

### HU-57 — Assets y system design (guía de marca) por jornada
Como administrador quiero poder subir, desde la creación/actualización de una jornada, las imágenes propias de esa jornada (fotos, logo) y su guía de marca, para que lo que el sistema genere después se vea como la jornada y no como una plantilla genérica.
- `jornadas.JornadaAsset`: FK a `Jornada`, `tipo` (`asset` | `system_design`), `archivo`, `nombre_archivo_original`, `subido_por`. Modelo aparte y no campos sueltos en `Jornada` porque una jornada tiene **varios** assets y porque así la subida no obliga a reenviar el resto de la jornada en cada `PATCH`.
- CRUD en `/api/admin/jornada-assets/` (`?jornada=<id>` para filtrar), mismo patrón de "recurso hijo con FK explícita" que ya usan `momentos`, `preguntas` y `jornadas-roles` — no un endpoint anidado bajo la jornada. **Sin `PUT`/`PATCH`**: un asset se reemplaza subiendo el nuevo y borrando el viejo; editar un archivo in place no significa nada.
- La carga es **en bloque** y el system design puede ser **texto**, no solo archivo — ver HU-59, que ajustó el contrato de este endpoint.
- **Formatos según el tipo, no uno solo para ambos**: `asset` acepta solo imágenes (`.png`/`.jpg`/`.jpeg`/`.webp`) porque van directo como referencia visual; `system_design` acepta además `.pdf`, que es como suele venir una guía de marca real.
- **`.docx` no se acepta como system design**, aunque el resto del sistema sí lee Word (HU-44/55): un Word no se puede rasterizar a imagen sin LibreOffice, que el servidor no tiene, y una guía de marca sirve por cómo se ve, no por su texto. Exportar a PDF o imagen es el paso que se le pide a quien sube.
- Se permite **historial** (varias filas del mismo tipo por jornada). La generación siempre usa el `system_design` más reciente y los `asset` más recientes: no hace falta borrar el anterior para corregir, y queda el registro de qué había antes.
- Mismo scoping por dependencia que el resto del panel (`jornadas.scoping`): una dependencia solo ve y crea assets de sus propias jornadas.

### HU-58 — Infografía de la jornada generada con IA a partir de los assets y la analítica
Como administrador quiero generar, con un clic, una infografía lista para publicar con los resultados reales de la jornada, para no tener que pasarle los números a un diseñador cada vez que hay que comunicar lo que salió de una jornada.
- **3 imágenes por corrida**, vía el modelo de imágenes de OpenAI (`OPENAI_IMAGE_MODEL`, por defecto `gpt-image-2`). Tres y no una porque el valor está en poder elegir: una sola salida obliga a regenerar hasta que guste, y regenerar cuesta una llamada completa.
- **Imagen a imagen, no descripción en texto.** Los `JornadaAsset` (hasta 4 `asset` + el `system_design` más reciente) se mandan como **imágenes de entrada** a `images.edit`, no como una descripción textual de la paleta. Describir una guía de marca en palabras pierde justo lo que la hace guía; mandarla como pixeles deja que el modelo la copie. Si la jornada todavía no tiene ningún asset, cae a `images.generate` (solo texto) en vez de fallar.
- **Los números nunca los pone el modelo**, mismo principio que el resto de `analitica/`: el prompt lleva la analítica **ya calculada** y pide explícitamente no inventar cifras. Fuente: `Reporte.analisis` si existe (la más completa) y, si está vacío, el `AnalisisJornadaIA` completo más reciente de esa jornada — así la infografía se puede pedir tanto desde la vía del pipeline local como desde la vía de una sola llamada a OpenAI, sin duplicar lógica.
- **Cuelga de un `Reporte`, no de la jornada**: `POST /api/admin/reportes/{id}/generar-infografia/`, igual patrón que `generar-presentacion`. El reporte ya trae resuelto el alcance (jornada / un momento / varios) y el estado "esto ya está calculado", que es exactamente la precondición de la infografía.
- **Una corrida es un objeto, no un campo**: `InfografiaJornada` (estado, `prompt_usado`, `modelo_usado`, error) + `InfografiaImagen` (las 3 imágenes, con `orden`). A diferencia de `Reporte.presentacion_*`, que sobrescribe, acá cada `POST` crea una corrida nueva — pedir otra versión no debería borrar la anterior, que puede ser la que ya se usó.
- Asíncrono con polling, como todo lo de IA en el proyecto (`threading.Thread` + estados `pendiente`/`procesando`/`completo`/`error`), consultable en `/api/admin/infografias/?reporte=<id>`. Guard de `409` si ya hay una en curso para ese reporte y auto-sanación de huérfanas a los 10 minutos, igual que presentación y análisis IA.
- `prompt_usado` se guarda: cuando una infografía sale mal, lo primero que hay que poder ver es qué se le pidió exactamente.
- **Pendiente de infraestructura**: las imágenes generadas son los primeros archivos del proyecto que el frontend necesita **ver** por URL (hasta ahora `media/` solo lo leía el backend para mandarlo a OpenAI). Se sirve `MEDIA_URL` en desarrollo (`DEBUG=True`); en producción falta decidir cómo se expone (nginx, whitenoise o un bucket con `django-storages`).

> Nota de implementación: el nombre del modelo de imágenes (`gpt-image-2`) y la forma exacta de su
> respuesta quedan aislados detrás de la variable `OPENAI_IMAGE_MODEL` y de una sola función
> (`_llamar_openai_imagenes`), para que ajustarlos si cambia el contrato real de la API sea un
> cambio de una función y no de arquitectura.

### HU-59 — Cargar los assets en bloque y escribir el system design como texto
Como administrador quiero arrastrar de una vez todas las fotos de la jornada y poder escribir la guía de marca a mano, porque subir imagen por imagen es fricción pura y muchas veces no existe un PDF de marca pero sí se sabe perfectamente qué colores y tipografía usar.
- **Un POST, varios archivos**: el campo pasó de `archivo` a **`archivos`** (lista, repetida en el multipart — lo que produce un `<input type="file" multiple>` tal cual). La respuesta pasó a ser un **array** de los assets creados. Se cambió el contrato en vez de agregar un endpoint `/bulk/` aparte porque la carga de a uno era un caso degenerado del mismo gesto, y el FE todavía no lo había integrado: dos endpoints para lo mismo es deuda desde el día uno.
- **Un `tipo` por request, no por archivo.** Mezclar fotos y guía de marca en la misma tanda no es un caso real (se arrastran las 5 fotos juntas, la guía va aparte) y mapear tipo-por-archivo en multipart es frágil.
- **Todo o nada.** Si un archivo de la tanda no pasa la validación, no se crea ninguno y el `400` nombra el archivo culpable. Una tanda a medias deja al cliente sin saber cuáles de los 5 entraron — reintentar los 5 es más barato que reconciliar un estado ambiguo.
- **`system_design` puede ser texto** (`texto`: "paleta #14384A y #C08A28, tipografía serif, tono institucional"), archivo, o ambos. `JornadaAsset.archivo` pasó a opcional y entró `texto`.
- **El texto va al prompt, el archivo va como imagen de referencia** — no son dos formas de lo mismo: un PDF de marca se copia visualmente, una regla escrita se obedece como instrucción. Por eso se complementan y se pueden mandar juntos (el logo como archivo, las reglas de color como texto).
- **Una fila = una referencia**: si mandan archivos y texto en el mismo POST, el texto queda en su **propia fila**, no pegado a uno de los archivos. Así cada referencia tiene `id` propio (se puede borrar el texto sin borrar el logo) y no hay que decidir a cuál de los N archivos "pertenece" el texto.
- `texto` con `tipo: asset` es `400` en vez de ignorarse: un asset es una imagen que se compone, no una instrucción de estilo — aceptarlo y descartarlo en silencio sería perder datos que alguien escribió.
- La generación (HU-58) ahora toma **lo más reciente de cada clase**: el último `asset`, el último `system_design` con archivo y el último `system_design` con texto.

### HU-60 — Que los assets subidos se puedan ver: servirlos y devolver la URL correcta
Como usuario del panel quiero que la imagen que acabo de subir se vea, porque hasta ahora se guardaba bien pero la URL que devolvía la API daba 404 y el asset era, a efectos prácticos, invisible.
- Eran **dos fallas encadenadas**, no una. Primera: en producción `DEBUG=False`, y lo único que servía `/media/` era un `static()` condicionado a `DEBUG` — o sea, nadie. Segunda, la de fondo: la app se sirve bajo el prefijo `/api/aluna-kunsama/` y **nginx lo quita** antes de pasar la petición (`proxy_pass ... :8004/`), así que Django armaba las URLs sin el prefijo y apuntaban a un `/media/` que públicamente no existe.
- **`MEDIA_URL` pasa a leerse del entorno.** Django no puede deducir un prefijo que el proxy ya removió, así que se configura donde se sabe: en el despliegue queda `MEDIA_URL=/api/aluna-kunsama/media/`. Se descartó la vía "elegante" de un middleware que leyera el `X-Script-Name` que nginx ya manda: no funciona para archivos, porque el storage cachea `base_url` en un `cached_property` al arrancar y nunca vuelve a mirar el prefijo. Lo descubrió un test, no el razonamiento.
- **Los archivos los sirve Django, no nginx**, vía `config/media_views.py`. La solución correcta serían cuatro líneas de `alias` en nginx (agrohub las tiene), pero requiere root y no está disponible; para un puñado de imágenes de marca e infografías el costo de servirlas desde Django es irrelevante. Queda anotado como deuda, no como diseño.
- **Solo se expone una lista blanca** (`jornadas/assets/`, `analitica/infografias/`). En `media/` también viven los documentos que suben los participantes, con datos personales, que nunca se pensaron para servirse por URL: un `serve` de `media/` entero los habría publicado a quien acertara la ruta. La ruta se **normaliza antes** de comparar contra la lista, porque `jornadas/assets/../participantes/extracciones/x.pdf` empieza por un directorio público pero apunta fuera de él.
- **`SECURE_PROXY_SSL_HEADER`**: nginx termina el TLS y manda `X-Forwarded-Proto`, pero Django no lo miraba y generaba las URLs absolutas con `http://`, que un frontend en https bloquea como contenido mixto.
- **Límites de carga** (quedan documentados, no impuestos por código): el que de verdad ata es `client_max_body_size 20M` de nginx, **por request completo**, y corta antes de que Django vea nada — devuelve HTML, no JSON, así que el FE tiene que validar el tamaño total antes de enviar y partir en tandas. Django aporta un tope de 100 archivos por request. No se agregó un límite propio de tamaño en el serializer: sería un segundo número distinto del que realmente aplica, y confundiría más de lo que protege.

### HU-61 — Pedir la infografía sin tener que crear un reporte
Como administrador quiero generar la infografía directamente desde la jornada, porque el panel produce el **reporte integral** (`AnalisisJornadaIA`, la versión resumida de una sola llamada) y se me exigía además crear y esperar un `Reporte` del pipeline local que no necesitaba para nada.
- **`InfografiaJornada` pasa a colgar de la `Jornada`**, con `reporte` opcional (`SET_NULL`). El modelo ya se llamaba así: depender de un `Reporte` era una incoherencia heredada de haber puesto el disparador ahí (HU-58).
- **Se pide con `POST /api/admin/infografias/` y `{"jornada": <id>}`**, el mismo patrón de `reportes` y `analisis-jornada-ia` — el FE no aprende un mecanismo nuevo. El atajo `POST /reportes/{id}/generar-infografia/` se mantiene para forzar los datos de un reporte concreto; no se quitó porque ya estaba documentado y no estorba.
- **La falta de analítica se valida al crear, no en el hilo.** Antes se creaba el registro y el error aparecía minutos después vía polling; ahora responde `400` de una con el motivo. Crear algo que ya se sabe que va a fallar solo sirve para que el error tarde más en llegar.
- **Orden de fuentes**: si se pasó un `reporte` con `analisis`, ese; si no, el `AnalisisJornadaIA` completo más reciente (el caso normal del panel); y como último recurso, cualquier `Reporte` completo de la jornada — así pedirla a nivel de jornada funciona igual si lo que existe es un reporte local.
- **La migración va en tres pasos** (agregar `jornada` nullable → rellenar desde `reporte.jornada` → volverlo obligatorio). En producción la tabla estaba vacía, pero un `AddField` no nulo sin default habría roto cualquier base que sí tuviera filas de la vía anterior.
- El guard de "ya hay una en curso" y la auto-sanación de huérfanas pasan a ser **por jornada** (antes por reporte) y se extraen a funciones compartidas, para que las dos rutas de creación se comporten igual.

### HU-62 — Las 3 imágenes como láminas complementarias 16:9, no como variaciones
Como administrador quiero que las tres imágenes de la infografía sean **distintas y complementarias**, como tres diapositivas de una misma presentación, y en formato 16:9 para poder proyectarlas — hasta ahora salían las tres con el mismo contenido y en vertical.
- **Tres papeles fijos** (`SLIDES`): portada (nombre de la jornada + cifras de participación), hallazgos (los temas con su dato y las visualizaciones) y cierre (conclusiones accionables). Cada prompt dice además qué **no** repetir de las otras.
- **Una llamada por lámina, no `n=3` en una sola.** Se intentó la vía de una sola llamada describiendo las tres láminas como una secuencia/storyboard, que es lo que sugiere la documentación para obtener un set coherente. **No funciona para este caso**: verificado contra la salida real, el modelo interpretó "serie de 3 láminas" como *una* imagen con las tres secciones apiladas en bandas, y `n=3` devolvió tres variantes de ese mismo compuesto. `n` genera variaciones de un único prompt, así que contenido distinto por imagen exige llamadas distintas.
- **Cada prompt insiste en que es UNA sola lámina** y prohíbe explícitamente apilar portada + hallazgos + conclusiones en la misma imagen. No es redundante: ese apilamiento fue exactamente el comportamiento observado cuando la instrucción no estaba.
- **Se lanzan en paralelo** (`ThreadPoolExecutor`, mismo patrón que `analysis.py`): tres llamadas encadenadas de ~80 s se acercaban demasiado al timeout de 300 s.
- **Consistencia visual explícita**: las tres comparten prefijo, datos y guía de marca, más una instrucción de que pertenecen a una serie y deben compartir paleta y tipografía. Sin eso se veían como piezas de autores distintos.
- **16:9 real en píxeles**: `2048x1152`, configurable con `OPENAI_IMAGE_SIZE`. gpt-image-2 acepta resoluciones arbitrarias —no solo el enum que declara el SDK— pero con reglas: **ambos lados múltiplos de 16**, proporción entre 1:3 y 3:1, ningún lado sobre 3840 y entre 655.360 y 8.294.400 píxeles. Por eso **no** sirve `1920x1080`: 1080 no es múltiplo de 16 y la API responde `400 Invalid size`. Se descartó recortar con Pillow para llegar al 16:9: mutilar los bordes de una lámina con texto es peor que pedir el lienzo correcto de entrada.
- Si el modelo devuelve menos láminas de las pedidas, las que llegaron se guardan igual y queda constancia en `error_mensaje`, en vez de que el FE tenga que deducirlo contando el arreglo.

### HU-63 — Que la infografía se construya sobre el reporte integral, no sobre el pipeline local
Como administrador quiero que las láminas se generen a partir del **reporte integral** (`AnalisisJornadaIA`, una llamada a OpenAI con modelo de razonamiento) y no del `Reporte` del pipeline local, porque el contenido que estaban mostrando salía de un análisis mucho más pobre que el que el panel ya tiene calculado.
- **El síntoma**: las infografías se estaban alimentando del `Reporte`. Verificable sin adivinar, porque `InfografiaJornada.prompt_usado` graba el campo `fuente` del JSON que se le mandó al modelo: las corridas 4, 5 y 6 decían `"fuente": "reporte"`.
- **La causa**: el FE dispara `POST /api/admin/reportes/{id}/generar-infografia/`, que fija el `reporte` de la corrida, y `_obtener_datos_analitica` prefiere `reporte.analisis` cuando le llega uno explícito — mandar un reporte concreto se interpreta, con razón, como "quiero los datos de ESTE reporte".
- **Por qué importa**: el `Reporte` lo produce el pipeline local (BERTopic + LLM Qwen 3B). Con pocas respuestas ni siquiera alcanza a descubrir temas — en el Reporte 36, con 2 respuestas, el `analisis` quedó con `participacion` y `momentos` y **ningún** `metodo_valores`. El reporte integral, en cambio, redacta hallazgos utilizables con el mismo material porque el trabajo lo hace un modelo grande de razonamiento.
- **La solución es de FE, no de backend**: basta con llamar `POST /api/admin/infografias/` con `{"jornada": <id>}` y **sin** `reporte`. Sin reporte explícito, el backend toma el `AnalisisJornadaIA` completo más reciente. El endpoint ya existe desde HU-61, así que no hay código nuevo.
- **Se descartó invertir la prioridad en el backend** (que el integral gane siempre, incluso con `reporte` explícito): eso eliminaría la única forma de pedir una infografía sobre un reporte puntual, que es un caso legítimo. Quien dispara la generación es quien sabe qué fuente quiere; el backend no debería adivinarlo por él.
- **Degradación**: si la jornada no tiene reporte integral completo, el backend cae al `Reporte` completo más reciente, y solo responde `400` si no hay ninguna de las dos. O sea, el cambio no puede dejar al FE sin infografía.
- **Cómo auditarlo después**: `prompt_usado` sigue grabando `fuente`, así que en cualquier momento se puede confirmar de dónde salió cada corrida sin instrumentar nada nuevo.

### HU-64 — Infografía de UN momento, a partir de su análisis integral
Como administrador quiero generar la infografía de un **momento** puntual desde la pestaña "Análisis integral", porque esa pestaña trabaja sobre `AnalisisMomentoIA` y hasta ahora la infografía solo sabía hablar de la jornada completa — no había forma de comunicar los resultados de una mesa o un bloque por separado.
- **Mismo endpoint, alcance distinto**: `POST /api/admin/infografias/` con `{"momento": <id>}`, **excluyente** con `jornada` y `reporte`. Se validó como "exactamente uno de los dos" en vez de aceptar ambos con una precedencia: una infografía que dijera ser de un momento mostrando cifras de toda la jornada sería un error silencioso, y el cliente no tendría cómo notarlo.
- **`jornada` se deriva, no se pide.** Aunque el alcance sea un momento, la fila guarda igual su `jornada` (desde `momento.jornada`). Es lo que sostiene el scoping por propietario sin duplicar reglas, y evita que "las infografías de esta jornada" tenga que mirar dos campos. De paso, no hay forma de mandar un momento de una jornada y el id de otra.
- **Campo nuevo `momento`** (nullable) en `InfografiaJornada`: `null` significa "de la jornada completa", que es lo que eran todas las filas anteriores — por eso la migración no necesita rellenar nada.
- **La fuente no se mezcla**: con `momento`, `_obtener_datos_analitica` usa el `AnalisisMomentoIA` completo más reciente de ese momento y **no** cae a la analítica de jornada si no lo encuentra; responde `400` diciendo que hay que generar el análisis del momento primero. La degradación que sí tiene sentido a nivel de jornada (caer al `Reporte`) acá produciría justamente la incoherencia que se quiere evitar.
- **El `409` es por alcance, no por jornada**: generar la infografía de un momento no bloquea la de la jornada ni la de los otros momentos, porque son trabajos independientes. El filtro usa `momento=None` para "la de jornada completa", que es distinto de "la de cualquier momento".
- **`prompt_usado` graba `"fuente": "analisis_momento"`**, así que se sigue pudiendo auditar de dónde salió cada corrida con el mismo mecanismo de siempre.
- El prompt de la portada pasa a titular con el **momento** cuando lo hay, y con la jornada cuando no: una lámina de un momento encabezada con el nombre de la jornada confundiría sobre qué se está mostrando.
- Sondeo con `GET /api/admin/infografias/?momento=<id>`.

### HU-65 — Ajustar el prompt de la infografía desde la API, sin tocar código
Como administrador quiero poder escribir instrucciones propias para cada generación —cambiar el tono, la composición o qué información aparece en las láminas— sin depender de un despliegue, porque afinar una pieza visual es iterar y cada iteración no puede costar un ciclo de desarrollo.
- **Campo `instrucciones`** (texto libre, opcional) aceptado por **los dos** endpoints de generación: `POST /api/admin/infografias/` y `POST /api/admin/reportes/{id}/generar-infografia/`. Vacío = comportamiento de siempre.
- **Se anexan con precedencia, no reemplazan el prompt.** Van al final, después de la guía de marca, con una línea que dice explícitamente que mandan sobre todo lo anterior. Así pueden contradecir estilo, estructura y contenido —que es justo para lo que existen— sin que haya que reescribir desde cero las reglas de formato 16:9, de una idea por lámina y de serie coherente, que seguirían haciendo falta igual.
- **Una sola regla queda fuera de su alcance**: `REGLA_DATOS` ("usa exclusivamente las cifras del JSON, nunca inventes") se movió del prefijo al **final del prompt**, después de las instrucciones. Una lámina institucional con cifras inventadas es desinformación publicada con el sello de la universidad, y ese riesgo no debería depender de lo que alguien escriba en un campo de texto. Es la única excepción y está documentada como tal.
- **Por corrida, no por jornada.** Guardar las instrucciones en la `InfografiaJornada` permite probar varias redacciones seguidas y comparar cada resultado con el `prompt_usado` que quedó grabado. Un campo por jornada obligaría a pisar el anterior para probar algo distinto.
- `instrucciones` se devuelve también en las lecturas, para que el panel pueda mostrar con qué se generó cada corrida y reusarlo como punto de partida de la siguiente.

### HU-66 — Adelgazar el prompt base a lo imprescindible
Como administrador quiero que el prompt por defecto imponga lo mínimo, para que el `system design` de cada jornada y el campo `instrucciones` (HU-65) tengan margen real de decidir el diseño en vez de tener que pelear contra criterios estéticos cableados en el backend.
- El prompt base pasó de ~2.550 a ~1.270 caracteres, **la mitad**, sin perder ninguna regla que sostenga el resultado.
- **Lo que se quitó** eran decisiones de diseño disfrazadas de instrucciones técnicas: "2 a 4 bloques grandes", "columnas o tarjetas", "barras o porciones", "entre 3 y 5 mensajes", "tipografía grande y con mucho aire", "tiene que leerse de un vistazo desde lejos". Nada de eso es necesario para que la lámina funcione, y cada una era una opinión que el usuario tenía que contradecir explícitamente si quería otra cosa.
- **Lo que se conservó, y por qué cada una se ganó el lugar**:
  - El formato 16:9 y la prohibición de vertical/cuadrado: define si la salida sirve o no.
  - "UNA sola lámina, no apiles secciones": verificado contra el modelo — sin esa frase apila portada + hallazgos + cierre en cada imagen (ver HU-62).
  - Respetar las imágenes de referencia: es la razón de existir de los assets y del system design.
  - El papel de cada lámina y qué no repetir de las otras: es lo que las hace complementarias en vez de tres variaciones.
  - `INSTRUCCION_SERIE`: las 3 son llamadas independientes, sin ella no saben que pertenecen al mismo material y salen con paletas distintas.
  - `REGLA_DATOS`: innegociable, ver HU-65.
- El criterio para futuras ediciones queda explícito en un comentario del módulo: si una instrucción no cambia si la salida **sirve o no**, y solo cambia cómo se ve, no va en el prompt base — va en el system design o en `instrucciones`.

### HU-67 — Un momento sabe quién lo creó y si es público o privado (banco de instrumentos)
Como administrador quiero que cada momento (`jornadas.Momento`) registre quién lo creó y si es público o privado, para poder decidir, al crearlo, si otros usuarios del panel pueden reutilizarlo como plantilla o si es solo mío.
- **El momento mismo es la plantilla; no hay un modelo `PlantillaMomento` aparte (D1-A).** El banco de instrumentos es una vista filtrada sobre los `Momento` que ya existen (`visibilidad=publico` o "míos"), no una copia paralela del árbol de preguntas. Eso reutiliza tal cual `Pregunta`, `OpcionPregunta`, `FilaMatrizPregunta` y `ColumnaMatrizPregunta`, evita duplicar varios modelos, y hace que "publicar" sea cambiar un solo campo (`visibilidad`) en vez de correr una copia. El costo aceptado: lo que ven los demás en el banco es el momento "vivo" de su jornada — si el dueño lo edita, el banco lo refleja de inmediato (ver HU-70 para por qué eso no afecta a quien ya copió).
- **Cuatro campos nuevos en `Momento`, ningún modelo nuevo**: `visibilidad` (`privado` | `publico`, default `privado`), `creado_por` (FK a `User`, `on_delete=SET_NULL`), `momento_origen` (FK a sí mismo, `on_delete=SET_NULL`, ver HU-70) y `origen_info` (JSON, ver HU-70). Migraciones `jornadas/0016_momento_banco.py` (esquema) y `jornadas/0017_momento_backfill_creado_por.py` (datos), separadas para poder revertir el backfill sin tocar el esquema.
- **En código y en la API el feature se llama `banco-momentos`, no "instrumentos" (D2-A).** `instrumentos.Instrumento` ya es otro módulo del backend (aplicaciones restringidas por preregistro, con su propio login y su propio extractor), y nombrar esto igual habría colisionado en código, en URLs y en la cabeza de quien lee los logs. De cara al usuario el feature sigue llamándose "banco de instrumentos" — para quien opera el panel, un momento con su árbol de preguntas **es** un instrumento — pero esa es una cuestión de vocabulario en la interfaz, no de nombres en el backend.
- **Nace `privado` por defecto (D6).** Nada se comparte sin una decisión explícita: si `visibilidad` no viene en el body de `POST /api/admin/momentos/`, queda `privado`. La migración de esquema no publica nada por sí sola — con el backfill (D7), todos los momentos existentes quedan `visibilidad=privado`, así que tras desplegar el banco público arranca vacío hasta que alguien publique algo a propósito.
- **`creado_por` es solo atribución, no control de acceso.** El acceso a un momento lo sigue dando `jornada.propietarios`, igual que hoy; `creado_por` únicamente identifica quién lo creó para mostrarlo en el banco. Por eso el backfill le pone `creado_por = jornada.creada_por` cuando existe, o `null` si no (D7): no cambia a quién se le permite ver o editar nada, solo a quién se le atribuye.
- **"Mío" es "de una jornada donde soy propietario", no "que yo creé" (D3-A).** `Jornada.propietarios` ya admite varios dueños; si un co-propietario ya ve y edita un momento dentro de su jornada, ocultárselo en el banco porque `creado_por` diga otro nombre no protegería nada — solo confundiría. `creado_por` se guarda de todas formas, para la atribución que muestra el banco.
- **Quién edita: la regla de siempre, no una nueva (D4-A, D15).** Restringir la edición al estricto `creado_por` habría sido una regresión para jornadas con varios propietarios. Se mantiene: cualquier propietario de la jornada (el creador está entre ellos) más un administrador completo pueden editar el momento y cambiar su `visibilidad` con los mismos endpoints de siempre (`PATCH /api/admin/momentos/{id}/`). Un tercero no propietario nunca puede: el banco es de solo lectura para lo ajeno, y el `PATCH` le da `404` porque el momento ni siquiera entra en su queryset.
- `creado_por`, `momento_origen` y `origen_info` viajan en `MomentoAdminSerializer` como **solo lectura**: si alguien los manda en el body, se ignoran — los fija el backend.

<details><summary>Ejemplo — <code>POST /api/admin/momentos/</code> con visibilidad</summary>

Request:
```json
{
  "jornada": 9,
  "orden": 1,
  "titulo": "Reflexión inicial",
  "tipo": "individual",
  "contexto": "…",
  "visibilidad": "publico"
}
```

Response `201`:
```json
{
  "id": 88,
  "jornada": 9,
  "orden": 1,
  "titulo": "Reflexión inicial",
  "slug": "reflexion-inicial",
  "tipo": "individual",
  "contexto": "…",
  "visibilidad": "publico",
  "creado_por": {"id": 5, "username": "mgarcia", "nombre": "María García"},
  "momento_origen": null,
  "origen_info": {},
  "activo": true,
  "preguntas": []
}
```
</details>

### HU-68 — Usar un instrumento del banco crea una copia aislada
Como administrador quiero que, al usar un instrumento del banco en una jornada, se cree una copia completa e independiente en vez de referenciar el original, para poder adaptarlo a mi jornada sin arriesgar el instrumento de otro ni verme afectado si el dueño lo cambia después.
- **Servicio único `copiar_momento(origen, jornada_destino, usuario, ...)`** en `jornadas/banco.py`, corrido dentro de una transacción (`transaction.atomic`): si algo falla a mitad de camino, no queda una copia a medias — la base vuelve a como estaba.
- **Copia profunda, nunca una referencia.** El nuevo `Momento` no comparte ninguna fila con el original: se duplican también sus `Pregunta`, `OpcionPregunta`, `FilaMatrizPregunta` y `ColumnaMatrizPregunta`. Editar después el original no cambia la copia, y editar la copia no cambia el original — es la regla central del enunciado ("las copias quedan aisladas") y solo se cumple copiando de verdad, no apuntando al mismo árbol.
- **Qué se copia**: título (salvo que se mande uno nuevo), contexto, tipo, `categorias_semilla`, `mesas_permitidas`, `roles_permitidos`, `permite_carga_archivo`, y el árbol completo de preguntas con sus opciones/filas/columnas. **Qué NO se copia**: nada de ejecución — ninguna `Respuesta`, ninguna extracción, ningún análisis de IA ni infografía. La copia nace como un momento nuevo, sin nadie habiéndolo respondido todavía.
- **Se copian TODAS las preguntas, activas e inactivas, conservando su `activa` tal cual (D11-B)** — se decidió copiar el árbol completo en vez de solo lo visible para un participante. La consecuencia directa: cualquier `depende_de_opcion` que apunte a una opción **dentro** del mismo momento origen, aunque esa opción sea de una pregunta inactiva, siempre tiene su pregunta correspondiente en la copia y por lo tanto siempre se puede remapear — ya no queda un caso especial de "la pregunta de la que dependía no se copió". El único caso real de dependencia rota es el del punto siguiente: cuando apunta fuera del árbol copiado.
- **`depende_de_opcion` hacia una opción de OTRO momento se pone en `NULL`, no se rechaza con 400 (D9-A).** Se resuelve en dos pasadas: primero se copian todas las preguntas (sin tocar `depende_de_opcion`), después se remapea cada dependencia con un mapa `id origen → id copia`. Si la opción de origen no está en ese mapa (porque pertenece a otro momento), la copia queda sin esa condición y se agrega una advertencia con el texto de la pregunta afectada. Se descartó responder `400` y bloquear la copia entera porque el resto del momento sigue siendo perfectamente usable; obligar a corregir la dependencia antes de poder copiar nada sería un bloqueo desproporcionado para un detalle que el usuario puede ni haber notado que existía.
- **`mesas_permitidas` y `roles_permitidos` se copian tal cual, con advertencia si hace falta (D10-A)**, aunque son números de mesa y nombres de rol de la jornada de origen que pueden no existir en la jornada destino (`RolJornada` es por jornada). No se traducen ni se limpian porque son contenido, no una referencia técnica — `roles_permitidos` se compara contra `Participante.rol` como texto libre, así que nada se rompe aunque el rol no exista todavía. Si algún rol de la copia no existe como `RolJornada` en la jornada destino, se agrega una advertencia listándolo, para que el usuario decida si lo crea.
- **`origen_info` sobrevive al borrado del original (D14).** Además de la FK `momento_origen` (`on_delete=SET_NULL`), la copia guarda un snapshot JSON (`momento_id`, `titulo`, `jornada_id`, `jornada_slug`, `jornada_nombre`, `creado_por`, `copiado_en`, `copiado_por`) que no depende de que la fila original siga existiendo. Es lo que hace que la relación sea documental *de verdad*: si borran el original o su jornada, la copia no pierde el rastro de dónde salió, solo pierde la posibilidad de navegar hasta él por id.
- **`orden` se calcula como `max(orden) + 1` de la jornada destino, bloqueando la jornada con `select_for_update`** antes de calcularlo. Así dos copias simultáneas hacia la misma jornada no compiten por el mismo `orden`: la segunda transacción espera a la primera y calcula sobre el valor ya actualizado.
- **La copia siempre nace `activo=True` y `visibilidad=privado`, salvo que el body diga otra cosa (D8).** `activo=True` porque es un momento nuevo en la jornada destino y el estado del original no debería decidir por el usuario. `visibilidad=privado` por defecto para que el banco público no se llene de duplicados de la misma plantilla cada vez que alguien la usa.
- Duplicar un momento **dentro de la misma jornada** no es un caso aparte: es el mismo servicio con `jornada_destino == origen.jornada`; el `orden` va al final y el slug se resuelve con un sufijo (`-2`, `-3`, …) porque `Momento` sigue exigiendo `slug` único por jornada.

### HU-69 — Explorar el banco y usar una plantilla desde la API
Como administrador quiero poder explorar el banco de instrumentos con filtros, previsualizar un instrumento antes de usarlo, y crear una copia en mi jornada con un solo llamado, para armar una jornada nueva reutilizando lo que ya construí (o lo que otros compartieron) sin recrear preguntas desde cero.
- **`GET /api/admin/banco-momentos/`** lista los momentos visibles para mí: públicos de cualquiera más los de mis jornadas (unión, sin duplicados) si soy usuario de dependencia; **todos**, incluidos los privados ajenos, si soy administrador completo (D5 — admin ve y edita todo, igual que ya ve todas las jornadas). Filtros:
  - `alcance`: `publicos` | `mios` | `todos` (default `todos`).
  - `q`: texto libre, `icontains` sobre `titulo` y `contexto`.
  - `tipo`: `individual` | `mesa`.
  - `jornada`: filtra por id de jornada — útil para "quiero reutilizar todo lo de mi jornada anterior"; si esa jornada no tiene nada visible para mí, la lista sale vacía, no da error.
  - `solo_originales`: `1` para excluir los momentos que ya son copias de otro (`momento_origen` no nulo) — evita ver copias de copias al explorar.
  - `incluir_inactivos`: `1` para incluir también momentos con `activo=False`. **Sin este flag el listado los excluye por defecto**, pero el queryset base nunca filtra por `activo` — el filtro lo aplica solo la acción de listar (D12-B). Por eso el detalle, `usar/` y `derivados/` funcionan igual sobre un momento inactivo aunque no se haya pedido `incluir_inactivos`: el momento sigue siendo perfectamente usable como plantilla, solo no aparece por defecto en el listado para no ensuciarlo con contenido que su dueño desactivó.
  - `ordering`: `titulo` | `-actualizado_en` (default) | `-veces_usado`.
  - Cada item trae `n_preguntas` (solo `activa=True`, lo que vería un participante) y `n_preguntas_inactivas` (las que también se copiarán, con `activa=False`), `veces_usado`, `es_mio`, `puedo_editar` (`es_mio or admin`) y los datos de `jornada` y `creado_por` anidados.
- **`GET /api/admin/banco-momentos/{id}/`** trae el mismo item más el árbol completo `preguntas` (con `opciones`, `filas`, `columnas`), de **solo lectura** — sirve para previsualizar el contenido antes de decidir usarlo. `404` si el momento no está en mi banco visible (privado ajeno, o no existe): la convención del proyecto para lo ajeno filtrado por queryset es no revelar que el recurso existe, así que no hay `403` acá — a diferencia de "usar en una jornada que no es mía" (ver abajo), donde el problema no es el origen sino el destino.
- **`POST /api/admin/banco-momentos/{id}/usar/`** crea la copia. Body: `jornada` (obligatorio, debe ser una jornada mía), `titulo` (opcional, default el del origen), `orden` (opcional, default `max+1`), `visibilidad` (opcional, default `privado`, ver HU-68). Respuesta `201` con `{"momento": {…}, "advertencias": [...]}`; `advertencias` siempre viene, aunque sea `[]` — es la única forma de que el usuario se entere de una dependencia que se anuló o de un rol que no existe en la jornada destino.
- **Errores de `usar/`**: `404` si el `{id}` de origen no está en mi banco visible; `403` (mensaje `"Esta jornada no te pertenece."`) si `jornada` es válida pero no es mía; `400` si `jornada` no existe, si `orden` ya está ocupado en la jornada destino, o si `visibilidad` no es un valor válido.
- **El banco es de solo lectura**: no hay `POST` en la raíz de `/banco-momentos/` ni `PATCH`/`DELETE` en el detalle — crear y editar el contenido de un momento se sigue haciendo por `/api/admin/momentos/` y los endpoints del árbol (`/preguntas/`, `/opciones/`, …) de siempre.
- **Usar varias plantillas en una jornada es una llamada por plantilla, no un endpoint de lote (D13-A).** Se descartó un `POST` atómico con una lista de ids para esta fase por la semántica de "todo o nada" que habría que definir sin que el enunciado lo pidiera; el frontend encadena un `usar/` por cada instrumento elegido.

<details><summary>Ejemplo — <code>POST /api/admin/banco-momentos/61/usar/</code></summary>

Request:
```json
{ "jornada": 9 }
```

Response `201`:
```json
{
  "momento": {
    "id": 88,
    "jornada": 9,
    "orden": 3,
    "titulo": "Diagnóstico de Articulación Académica",
    "slug": "diagnostico-articulacion-2",
    "tipo": "individual",
    "visibilidad": "privado",
    "creado_por": {"id": 12, "username": "jperez", "nombre": "Juan Pérez"},
    "momento_origen": 61,
    "origen_info": {
      "momento_id": 61,
      "titulo": "Diagnóstico de Articulación Académica",
      "jornada_id": 4,
      "jornada_slug": "jornada-agil-2026",
      "jornada_nombre": "Jornada Ágil 2026",
      "creado_por": "mgarcia",
      "copiado_en": "2026-09-19T15:04:00Z",
      "copiado_por": "jperez"
    },
    "activo": true,
    "preguntas": [ "…árbol completo de la copia…" ]
  },
  "advertencias": [
    "La pregunta «¿Cuál fue el principal obstáculo?» dependía de una opción de otro momento; la dependencia se quitó."
  ]
}
```
</details>

### HU-70 — Trazabilidad entre original y copias
Como administrador quiero poder ver de dónde salió un momento que se creó desde el banco, y qué copias salieron de un momento mío, para entender el alcance de mis instrumentos y de dónde vino cada copia que encuentro en una jornada.
- **`GET /api/admin/momentos/{id}/`** de una copia trae `momento_origen` (id del momento del que se copió, o `null` si nació "desde cero") y `origen_info` (el snapshot con `momento_id`, `titulo`, `jornada_id`, `jornada_slug`, `jornada_nombre`, `creado_por`, `copiado_en` y `copiado_por`, o `{}` si no vino del banco).
- **`GET /api/admin/banco-momentos/{id}/derivados/`** lista, en el mismo formato que el listado del banco (sin `preguntas`), los momentos que se copiaron de `{id}` **y que yo puedo ver**: mis jornadas si soy usuario de dependencia, todos si soy administrador completo. `200 []` si no hay ninguno visible para mí, aunque existan copias que no puedo ver.
- **`veces_usado`** (en cada item del listado del banco) cuenta **todas** las copias derivadas de ese momento, sin filtrar por visibilidad — a diferencia de `derivados/`, que sí filtra por lo que puedo ver. Al dueño de la plantilla le interesa el número real de veces que se usó, no solo las copias que además puede abrir.
- **La relación es puramente documental: no restringe editar ni borrar ninguno de los dos lados.** No hay ninguna regla que impida borrar un momento porque tenga copias, ni que impida editar una copia porque su origen siga existiendo. Es justo lo que hace posible cumplir "editar el original no afecta a las copias, ni al revés": si la relación bloqueara algo, dejaría de ser una simple constancia y empezaría a acoplar dos momentos que el enunciado pide aislados.
- **Si se borra el momento origen** (`DELETE /api/admin/momentos/{id}/`, como siempre): la FK `momento_origen` de cada copia pasa a `null` (`on_delete=SET_NULL`), pero `origen_info` queda intacto porque es un snapshot independiente, no una consulta al original. La copia sigue sabiendo de dónde salió aunque ya no pueda navegar hasta ahí con un id.
- **Si se borra la jornada origen** en vez del momento puntual: el `CASCADE` de `Jornada → Momento` borra el momento original igual que si lo hubieran borrado directamente, y el efecto sobre las copias es el mismo que el punto anterior — `momento_origen=null`, `origen_info` intacto.
- **Copiar una copia (nieto) es un caso normal, no uno especial.** `momento_origen` de la copia nueva apunta a la copia intermedia, no al abuelo, y `origen_info` describe esa copia intermedia. La cadena completa no se reconstruye en ningún campo propio: si hace falta rastrear varios saltos, hay que seguir `momento_origen` de copia en copia.
- Después de borrar una copia, el original **no se entera**: solo baja en uno el `veces_usado` de las copias restantes, porque `veces_usado` es un conteo, no una lista fija.

### HU-71 — Análisis guiado: método, enfoque, contexto e instrucciones
Como administrador quiero elegir el enfoque (cualitativo, cuantitativo o mixto) y escribir contexto e instrucciones libres al pedir un análisis, para orientar la lectura de los datos sin depender de un despliegue — brief completo del frontend en `docs/HU_BACKEND_ANALISIS_GUIADO.md` (HU-57 de ese repo; este es el correlativo del backend).
- **Campos nuevos en las tres solicitudes de análisis** (`POST /api/admin/reportes/`, `analisis-momento-ia/`, `analisis-jornada-ia/`), persistidos y devueltos en `GET`: `enfoque` (`cualitativo` | `cuantitativo` | `mixto`, default `mixto`), `contexto` e `instrucciones` (hasta 4000 caracteres); `contexto_momento`/`instrucciones_momento` cuando el alcance es un único momento (`reportes` y `analisis-momento-ia`). `AnalisisJornadaIA` no los tiene — su alcance es siempre la jornada entera. Dos mixins abstractos en `analitica/models.py` (`AnalisisGuiadoMixin`, `AnalisisGuiadoPorMomentoMixin`) para que los tres modelos no se desalineen entre sí.
- **`metodo` en las tres respuestas** (`"bertopic"` para `Reporte`, `"openai"` para los `Analisis*IA`) — constante por modelo, no una columna, para que el frontend no tenga que deducirlo del endpoint por el que llegó cada item.
- **Un solo compositor de prompt para las dos vías** (`analitica/prompt_comun.py`): plantilla base (con las instrucciones del equipo) → bloque de enfoque (texto fijo por valor) → contexto (+ contexto del momento) → instrucciones del usuario (con precedencia sobre todo lo anterior) → regla de datos, siempre al final y no negociable. `analisis_ia_openai.py` (OpenAI) y `analysis.py` (pipeline local BERTopic + LLM) comparten exactamente este orden y esta redacción, aunque son dos motores completamente distintos.
- **En el pipeline local, el enfoque solo entra en la SÍNTESIS** (`_agente_pregunta_abierta`, `_agente_pregunta_cerrada`, `_sintetizar_momento`, `analizar_jornada`), nunca en la clasificación de temas (`_etiquetar_y_clasificar`). Decisión deliberada, distinta de lo que sugiere el brief del frontend: ese prompt depende de un formato estricto (`TEMAS:`/`CLASIFICACION:`) que un modelo local de 3B ya es propenso a romper, y contexto/instrucciones libres ahí arriesgaban romper reportes que hoy funcionan bien para un beneficio marginal (el nombre de un tema rara vez necesita contexto extra). Los conteos y el clustering siguen siendo 100% determinísticos, como siempre — el enfoque solo cambia cómo se redacta sobre ellos.
- **`prompt_usado`** (nuevo en `Reporte`, ausente hasta ahora en los tres modelos pese a lo que decía el brief) guarda, para `Reporte`, el prompt de la síntesis de jornada (`analizar_jornada`, que ahora devuelve `(texto, error, system_usado)`) — la pieza más representativa cuando hay decenas de otros prompts (uno por pregunta y por momento) que sería excesivo guardar todos.
- **`POST /api/admin/analisis-sugerencias/`** (nuevo, sin modelo detrás — nada se persiste): recibe `{jornada, momentos, metodo, enfoque, contexto, instrucciones}` y devuelve `{"sugerencias": [{"tipo": "contexto"|"instruccion", "texto": "…"}]}`, 0 a 6 ítems. Un modelo chico y rápido (`gpt-4o-mini` por defecto, no el de razonamiento que usan las otras vías), con `timeout` de 8s — si tarda más o `OPENAI_API_KEY` no está configurada, responde `200` con lista vacía, nunca un error: es un ayudante de formulario, no debe bloquear el asistente. Solo recibe conteos y metadatos de los momentos (título, contexto, tipos de pregunta, cuántas respuestas), nunca respuestas de participantes.
- **`GET /api/admin/analisis/?jornada=<id>` o `?momento=<id>`** (nuevo, solo lectura): une `Reporte` + `AnalisisMomentoIA` + `AnalisisJornadaIA` en una sola lista ordenada por `creado_en` descendente, cada item con `tipo`, `alcance`, `metodo`, `enfoque`, `momento_titulo`/`momento_orden` resueltos (`null` cuando el alcance no es un único momento) y estado — para que el panel arme la pestaña Analítica con una consulta en vez de tres repetidas cada pocos segundos. Abrir, borrar y el detalle siguen en los endpoints propios de cada tipo. `400` sin `jornada` ni `momento`; mismo scoping por dependencia que el resto del módulo.
- **`400` inmediato si el alcance no tiene respuestas** ("El momento X no tiene respuestas todavía" / "La jornada no tiene respuestas todavía"), en las tres solicitudes — nunca un registro que gasta cómputo real para terminar en `error`. El guard vive en la vista, **después** de `verificar_acceso_jornada` (403) y del chequeo de "ya hay uno en curso" (409): ponerlo antes, dentro del serializer, tapaba esos dos códigos con un 400 y le revelaba a un admin de otra dependencia si una jornada ajena tiene respuestas o no, solo por el status code — se detectó con la suite existente (`ReporteScopingTests`, `AnalisisJornadaIAScopingTests`) al correrla después del cambio.
- **`GET /api/admin/infografias/?reporte=`** ya filtraba por reporte desde antes de esta HU — se confirmó contra el checklist del brief, sin cambios de código.
- 17 tests nuevos en `analitica/tests.py` (`AnalisisGuiadoCamposTests`, `AnalisisSugerenciasViewTests`, `AnalisisUnificadoViewTests`), suite completa del proyecto en verde (313 tests).

### HU-72 — La infografía se genera del análisis seleccionado, no del más reciente
Como administrador quiero poder pedir la infografía de un análisis CONCRETO de una jornada o de un momento, no siempre del más reciente, porque desde HU-71 una jornada o un momento acumulan varios análisis a la vez (distintos métodos, distintos enfoques) y "el más reciente" deja de ser confiable en cuanto hay más de uno.
- **Dos campos nuevos en `InfografiaJornada`**: `analisis_momento` (FK a `AnalisisMomentoIA`, `on_delete=SET_NULL`) y `analisis_jornada` (FK a `AnalisisJornadaIA`, ídem) — mismo patrón que el `reporte` que ya existía para el pipeline local. Migración `0016_infografia_fija_analisis_exacto.py`.
- **`POST /api/admin/infografias/`** acepta los dos nuevos campos, mutuamente excluyentes con el alcance contrario: `analisis_momento` solo con `momento` (y debe pertenecer a ESE momento), `analisis_jornada` solo con `jornada` sola (y debe pertenecer a ESA jornada), y `reporte`/`analisis_jornada` no se combinan entre sí (son dos métodos distintos para el mismo alcance). Cualquier combinación incoherente es `400` con la clave del campo.
- **Sin ninguno de los tres, sigue cayendo al más reciente completo de ese alcance** — comportamiento de siempre, para no romper una petición que solo manda `jornada`/`momento` (que es lo único que el brief original describía). El fijado es la vía nueva para cuando el panel ya sabe, por la lista unificada (`GET /api/admin/analisis/`, HU-71), exactamente qué tarjeta generó el clic.
- `infografia_ia_openai._obtener_datos_analitica` recibe ahora `analisis_momento`/`analisis_jornada` explícitos; si vienen, los usa directo y ya ni siquiera consulta "cuál es el más reciente".
- **Sigue sin generarse nada automáticamente** — ningún análisis dispara una infografía por sí solo; se pide siempre con un `POST` explícito, igual que antes de esta HU. Este cambio es solo sobre DE CUÁL análisis salen los datos cuando sí se pide.
- 10 tests nuevos (`InfografiaFijaAnalisisExactoTests`): a nivel de función (`_obtener_datos_analitica` usa el fijado aunque haya uno más nuevo) y a nivel de API (se guarda el id fijado, y las cinco combinaciones incoherentes dan `400`). Suite completa en verde (329 tests).

### HU-73 — Análisis con IA bajo el contrato único `kunsamu.analisis/v2`
Como administrador quiero pedir un análisis con IA que devuelva siempre la misma forma de JSON (`kunsamu.analisis/v2`), eligiendo alcance y método sin tener que elegir un "enfoque", para que el frontend tenga un único renderer y ya no dependa de tres formatos distintos según por dónde se pidió el análisis.
- **Modelo nuevo `AnalisisV2`, los tres modelos legacy (`Reporte`, `AnalisisMomentoIA`, `AnalisisJornadaIA`) quedan intactos.** El frontend va a elegir renderer por la presencia del campo `version` en el resultado y a conservar los visores históricos (`docs/mejora_promps/MIGRACION_FRONTEND.md` §7); un modelo nuevo hace esa distinción trivial (todo lo legacy sigue sin `version`, todo lo v2 la trae) y evita tocar tres pipelines y sus consumidores (presentación HTML, PDF, Excel, infografía) para encajar un contrato que además rompe su partición actual por alcance: un `por_momento` con varios momentos produce varios informes en UNA sola solicitud, algo que los tres modelos legacy no representan.
- **`POST /api/admin/analisis-v2/`** con `jornada` + `modo` (`integral` | `por_momento`) + `momentos` (obligatorio y no vacío solo en `por_momento`; rechazado en `integral` con `400` para que nadie crea que "integral de tres momentos" existe — el frontend ya distingue "Toda la jornada" de "Por momento") + `pipeline` (`llm` | `bertopic_llm`, default `llm`) + `contexto`/`instrucciones` (≤4000, opcionales) + `personalizacion_momentos` (contexto/instrucciones por momento del alcance, como máximo uno por momento). Detalle completo de campos, ejemplos de request/response y todos los códigos de error en `docs/INTEGRACION_FRONTEND_ANALISIS_V2.md` §1–§2.
- **Sin `enfoque`.** El contrato lo elimina del todo: el modelo decide el método más adecuado pregunta por pregunta y lo declara en `naturaleza`/`metodos` de cada hallazgo, en vez de que el usuario le imponga de antemano "cualitativo/cuantitativo/mixto" (como sí siguen haciendo los tres pipelines legacy, HU-71). `metodo` en la lista unificada se sigue derivando del `pipeline` (`bertopic_llm` → `"bertopic"`, `llm` → `"openai"`) para que la agrupación actual del panel siga funcionando sin cambios; `enfoque` en esos items llega `null`.
- **Estados del trabajo y estado analítico son cosas distintas.** `AnalisisV2.estado` (`pendiente`|`procesando`|`completo`|`error`) es el estado del TRABAJO, igual que en el resto del módulo. El estado ANALÍTICO vive dentro de `resultado.estado` (`completo`|`parcial`|`sin_datos`|`datos_insuficientes`) y se expone aparte como `estado_analitico`. Un fallo de OpenAI, de validación o de tamaño de entrada es siempre `estado="error"` con `error_mensaje`, nunca un `resultado` con `sin_datos` — esa distinción evita que un problema técnico se disfrace de "no había nada que analizar".
- **Guards en la creación, en este orden**: `400` de forma → `403` si la jornada no es de la dependencia del usuario → se sanea cualquier `AnalisisV2` huérfano (más de 45 minutos `pendiente`/`procesando`, marcado `error` automáticamente — umbral más alto que en las vías legacy porque la llamada v2 es una sola pero grande, y en `bertopic_llm` va precedida de clustering por pregunta) → `409` si ya hay otro `AnalisisV2` `pendiente`/`procesando` con la MISMA jornada, el MISMO `modo` y el MISMO conjunto de momentos → `400` si la jornada no tiene ningún momento en modo `integral`. **Deliberadamente no hay guard de "el alcance no tiene respuestas"**: a diferencia de las tres vías legacy (que sí devuelven `400` inmediato, HU-71), en v2 `sin_datos` es un estado analítico válido del contrato y el frontend lo renderiza — bloquearlo con `400` habría sido reintroducir exactamente el problema que el contrato v2 resuelve (ver HU-74).
- **Lista unificada (`GET /api/admin/analisis/`) extendida**: los items `AnalisisV2` llegan con `tipo: "analisis_v2"` y las claves comunes de siempre, más cuatro exclusivas (`version`, `modo`, `pipeline`, `estado_analitico`) que le dicen al frontend qué renderer usar sin tener que consultar el detalle. `?momento=<id>` incluye solo los `por_momento` que contienen ese momento — un `integral` nunca es "de" un momento puntual, mismo criterio que ya aplicaba a `analisis_jornada`.
- 12 tests nuevos en `analitica/tests_v2.py` (`AnalisisV2ApiTests`: creación en los dos modos, personalización, las cuatro combinaciones de `400`, `403` por jornada ajena, `409` solo para el mismo alcance exacto, lista/detalle con scoping, inclusión en la lista unificada); la suite completa del proyecto no se corrió en esta entrega por decisión del dueño del repo.

### HU-74 — Entrada normalizada e inmutable, con conteos calculados por el backend
Como equipo que necesita confiar en las cifras del análisis, quiero que la IA reciba un sobre de datos normalizado y completo (con los conteos ya calculados por el backend) y que ese sobre quede congelado antes de llamar al modelo, para que ninguna cifra del informe dependa de que el LLM cuente bien, y para que un análisis nunca cambie de significado por una edición posterior de los datos.
- **`analitica/v2/entrada.py::construir_entrada`** arma el sobre completo (`solicitud`, `jornada`, `momentos[]` con su inventario de preguntas, `personalizacion`, `fuentes[]`, `bertopic`) directamente desde los modelos reales de `jornadas`/`participantes` — no desde los payloads ad hoc que usaban las tres vías legacy. Todos los IDs (jornada, momentos, preguntas, opciones, filas, columnas, respuestas) son **strings**, y el orden de cada array es determinista (preguntas por `Momento.orden`, respuestas por `Respuesta.id` ascendente) porque los JSON Pointers de las citas y de los documentos BERTopic apuntan a índices de esos arrays — cambiar el orden después invalidaría en silencio cualquier cita ya publicada.
- **La entrada se guarda en `AnalisisV2.entrada` ANTES de llamar a OpenAI y nunca se recalcula.** Si se llamara dos veces a `construir_entrada` (por ejemplo, para auditar una cita mucho después), una respuesta nueva registrada entre medias correría el orden de los arrays y desalinearía los JSON Pointers ya validados contra la primera versión — por eso el orquestador (`procesar.py`) construye la entrada una sola vez, la persiste, y valida y le pide correcciones a la IA siempre contra esa misma copia congelada.
- **Inventario de preguntas por momento = activas O con al menos una respuesta real** (`Q(activa=True) | Q(respuestas__isnull=False)`), nunca solo `activa=True`: una pregunta que se desactivó después de tener respuestas reales no debe desaparecer en silencio del análisis, mismo criterio que ya usaban las vías legacy para "jornada completa incluye momentos inactivos" (ver `INTEGRACION_FRONTEND_ANALISIS_GUIADO.md` §1).
- **Siempre hay una fuente `respuestas` por momento del alcance, aunque esté completamente vacía.** Esa fuente vacía con `cobertura: "completa"` es justo lo que permite declarar `sin_datos` en vez de `no_recibida` (D11 del plan) — el contrato distingue "se buscó y no había nada" de "no se buscó".
- **Fuente `agregado` adicional por cada momento con preguntas cerradas** (`unica`/`multiple`): conteos por opción y porcentajes calculados en `_fuente_agregado`, con `procedimiento.origen: "backend"` — el modelo cita esas cifras con `origen: "reportado"` y una ruta verificable (`/distribuciones/0`), nunca las inventa ni las recalcula por su cuenta. Es la misma filosofía que ya regía el pipeline local (`analysis.py`): los números nunca dependen del LLM.
- **`categorias_semilla` del momento no tiene campo propio en el contrato de entrada**: se agrega como una frase descriptiva al final de `momentos[].contexto` ("Categorías temáticas de referencia definidas por el equipo organizador: …") — es contexto para que el modelo lo tenga en cuenta, no una instrucción de formato que le imponga esas categorías como estructura de salida.
- **`sin_datos` lo produce el backend sin llamar a la IA** (`analitica/v2/sin_datos.py::construir_salida_sin_datos`): si ninguna fuente `respuestas` del alcance tiene respuestas, se arma determinísticamente el JSON completo (cobertura completa con `estado: "sin_datos"` por pregunta, un informe por alcance con resumen fijo y `hallazgos`/`recomendaciones`/`visualizaciones` vacíos) y pasa por las mismas dos capas de validación que una respuesta real de la IA — si no pasara, sería un bug del backend, no un problema de la IA. Ahorra una llamada cara (y más lenta y menos fiable) para pedirle al modelo que "no invente" cuando ya se sabe con certeza que no hay nada que analizar.
- 6 tests nuevos en `analitica/tests_v2.py` (`EntradaNormalizadaTests`: orden en integral y por_momento, inventario y contexto del momento, respuestas escalares, agregado con conteos, matriz/lista/audio de mesa) más 1 test (`SalidaSinDatosTests`) que verifica que `sin_datos` produce una salida válida en ambos modos; la suite completa del proyecto no se corrió en esta entrega por decisión del dueño del repo.

### HU-75 — Salida estructurada estricta y validación en dos capas con un reintento de reparación
Como equipo responsable de lo que un análisis con IA afirma, quiero que la salida del modelo se fuerce a un esquema JSON estricto y se valide dos veces (esquema y reglas de negocio) antes de publicarla, con un único reintento de reparación guiado por los errores concretos, para que nunca llegue al frontend un análisis con una cita inventada, un porcentaje que no cuadra o una referencia rota.
- **`system` = el archivo del prompt entero, sin anexos; `user` = el JSON de la entrada.** `analitica/v2/llm.py` manda `SYSTEM_PROMPT_LLM.md` o `SYSTEM_PROMPT_BERTOPIC.md` (copias congeladas en `analitica/v2/recursos/`, cargadas por `contrato.cargar_prompt`) tal cual, sin los bloques de enfoque, sin `prompt_comun.ensamblar_system` ni `REGLA_DATOS_ANALISIS` que sí usan las tres vías legacy (HU-71) — lo pide explícitamente el README de la entrega ("no se deben anexar los antiguos bloques de enfoque ni las instrucciones que permiten al prompt del usuario prevalecer sobre el system"). El contexto/instrucciones del usuario viajan como datos dentro del JSON de `user` (`entrada.personalizacion`), nunca mezclados en el `system`.
- **`response_format` = `json_schema` estricto, con respaldo.** Se manda el esquema congelado (sin `$schema`/`title`/`description` de la raíz) con `strict: true`; si el proveedor lo rechaza (la excepción menciona `schema` o `response_format`), se reintenta UNA vez con `{"type": "json_object"}` y el esquema completo anexado al `system` bajo un encabezado explícito. En ambos casos la respuesta se valida exactamente igual después — el modo estricto reduce errores, no reemplaza la validación.
- **Antes de intentar parsear**, se comprueba `message.refusal` (un rechazo del proveedor es error, no una salida vacía) y `finish_reason == "stop"` (una respuesta truncada por el límite de tokens nunca se acepta como JSON completo, así "parseara" parcialmente). `json.loads` usa un `parse_constant` que rechaza `NaN`/`Infinity`/`-Infinity`, que `json.loads` acepta por defecto pero el esquema no permite (solo números finitos).
- **Dos capas de validación en `analitica/v2/validacion.py`**: `validar_esquema` (JSON Schema Draft 2020-12 completo, `jsonschema.Draft202012Validator`) y, si pasa, `validar_negocio` — porta y amplía `verificar_entrega.semantic_checks` de la entrega original: alcance idéntico a `entrada.solicitud`, cobertura con exactamente una fila por pregunta inventariada, IDs y referencias cruzadas válidas, citas que son subcadena literal exacta del texto localizado por `fuente_id`+JSON Pointer, porcentajes que cuadran con su numerador/denominador, y las reglas propias de cada tipo de visualización.
- **Un solo reintento de reparación** (`analitica/v2/procesar.py`): si la validación falla, se manda de nuevo la conversación completa (`assistant`: el JSON inválido devuelto, `user`: la lista de errores concretos + "devuelve el objeto completo corregido"). Si el segundo intento también falla, el trabajo termina en `estado="error"` con los primeros errores en `error_mensaje`, y **ambas** salidas descartadas junto con los errores y los metadatos de cada llamada quedan en `AnalisisV2.diagnostico` para auditoría — nunca se "arregla" una cifra a mano, se convierte un `null` en `0`, ni se borra una clave para que la validación pase; si algo no puede sustentarse con la entrada, la regla es que la IA lo elimine y registre la limitación, no que el backend lo maquille.
- 9 tests nuevos (`ValidacionEjemplosTests`: los cuatro pares de ejemplos de la entrega pasan las dos capas, y casos que deben fallar — clave extra, porcentaje que no cuadra, cita no literal, visualización huérfana/referencia rota, cobertura incompleta, cruce de fuentes entre momentos, resolución de JSON Pointer), 3 tests (`LlmEstructuradoTests`: esquema sin claves informativas, rechazo de `NaN`, error legible sin `OPENAI_API_KEY`) y 5 tests (`ProcesarAnalisisV2Tests`: flujo completo con salida válida, `sin_datos` sin llamar a OpenAI, dos fallos de validación seguidos terminan en error con diagnóstico, error del proveedor termina en error, y el pipeline `bertopic_llm` guarda las ejecuciones en la entrada) en `analitica/tests_v2.py`; la suite completa del proyecto no se corrió en esta entrega por decisión del dueño del repo.

### HU-76 — Pipeline `bertopic_llm`: BERTopic exportado como fuente verificable
Como equipo que quiere que el modelo de lenguaje razone sobre temas ya agrupados en vez de leer texto crudo sin estructura, quiero que el pipeline `bertopic_llm` ejecute BERTopic por pregunta de texto y exporte el resultado como una fuente más del contrato (tópicos, documentos y agregados verificables), para que la IA pueda citar "el tópico X agrupa Y respuestas" con una referencia real en vez de estimarlo de memoria.
- **Una ejecución de BERTopic por pregunta de texto (`abierta`/`audio`) con al menos 8 respuestas no vacías** (`MIN_RESPUESTAS_TOPICOS`, reutilizada de `analysis.py`) — menos que eso, o una ejecución que falle, simplemente no tiene ejecución: se anota en `AnalisisV2.diagnostico['bertopic']` (nunca en la salida de la IA) y el análisis sigue su curso con las preguntas restantes. Con cero ejecuciones, `entrada.bertopic = {"version_adaptador": "1.0", "ejecuciones": []}` — una entrada válida y declarada, no un error; así funcionaba también el stub que existía antes de esta fase (`pipeline=bertopic_llm` nunca rompió nada desde que se activó el endpoint, D8 del plan).
- **Misma configuración de UMAP/HDBSCAN/vectorizador/`nr_topics` que el pipeline local** (`analysis._descubrir_topicos_bertopic`), copiada en `analitica/v2/bertopic_adaptador.py::_ajustar_modelo` y no importada, porque esa función legacy no expone el modelo ya ajustado (solo palabras clave y ejemplos) — copiarla evita además cualquier riesgo de que un cambio en v2 afecte al pipeline local, que el plan prohíbe tocar.
- **Se exporta exactamente lo que BERTopic calcula, nada más**: `topicos` (con `conteo_documentos`, términos c-TF-IDF con `weight_type: "c_tf_idf"`, documentos representativos), `documentos` (asignación final por documento, con `localizador` apuntando a la fuente `respuestas` original) y `agregados` (conteos por tópico, con `denominador_n` = documentos procesados, outliers incluidos). `distribuciones`, `similitudes`, `coocurrencias` y `proyecciones` van siempre `[]` — inventar esos cálculos violaría el contrato, que exige que cada dato sea trazable a un cómputo real.
- **El tópico `-1` (outliers de HDBSCAN) se conserva como tal**, con la etiqueta `"Sin asignar (outliers de HDBSCAN)"`, nunca renombrado a "otros" ni descartado silenciosamente — es información real sobre cuánto del corpus no encajó en ningún tema.
- **IDs compuestos `run-p<pregunta_id>::<native_id>`**, con `urllib.parse.quote` sobre cada mitad (`bertopic_adaptador.id_topico`) — determinísticos y sin colisión entre preguntas distintas de la misma jornada.
- 2 tests nuevos (`BertopicAdaptadorTests` en `analitica/tests_v2.py`: `exportar_ejecucion` mapea tópicos/documentos/agregados correctamente con un modelo de prueba (doble, sin descargar el modelo de embeddings real), y `anexar_bertopic` omite preguntas con corpus insuficiente) más el test de integración ya contado en HU-75 (`ProcesarAnalisisV2Tests::test_bertopic_llm_guarda_ejecuciones_en_la_entrada`); la suite completa del proyecto no se corrió en esta entrega por decisión del dueño del repo.

### HU-77 — La infografía se genera también desde un `AnalisisV2`
Como administrador quiero poder pedir la infografía de un análisis v2 concreto, igual que ya puedo hacerlo con un `Reporte`/`AnalisisMomentoIA`/`AnalisisJornadaIA`, para no quedarme sin ese botón simplemente porque el análisis se generó con el contrato nuevo.
- **Cuarto FK `analisis_v2` en `InfografiaJornada`** (`on_delete=SET_NULL`, migración `0018`), mutuamente excluyente con los otros tres bajo la misma regla "exactamente uno" que ya impone `InfografiaJornadaCrearSerializer` desde HU-72 de este archivo (la de infografías aisladas por versión exacta — nótese que el código y `docs/INTEGRACION_FRONTEND_ANALISIS_GUIADO.md` la llaman internamente "HU-73" por una discrepancia histórica de numeración con el repo del frontend; en este archivo es HU-72, y no se renumera nada). Es la única pieza legacy que esta entrega toca, porque el frontend pide la infografía desde la tarjeta del análisis en la lista unificada y un `AnalisisV2` sin esa opción quedaría con la tarjeta incompleta frente a los otros tres tipos.
- **`jornada`/`momento` se derivan del `AnalisisV2` fijado**: `jornada` siempre; `momento` solo cuando es `por_momento` de EXACTAMENTE un momento (un `integral`, o un `por_momento` de varios, es "de la jornada" para efectos de la infografía, no de un momento puntual) — mismo criterio de "cuándo hay UN momento al que referirse" que ya usa `_item_analisis_v2` en la lista unificada.
- **`_obtener_datos_analitica` traduce el `resultado` v2 al mismo diccionario que ya consumen las tres láminas** (`resumen_ejecutivo`, `hallazgos[{titulo, descripcion, tipo_grafica, datos[{etiqueta, valor, unidad}]}]`): toma `resumen` del informe como `resumen_ejecutivo`, `afirmacion` (+ `implicacion` si existe) de cada hallazgo como `descripcion`, y `metricas` como `datos`. No cambia en nada el prompt de generación de imagen (`SYSTEM_PROMPT_PREFIJO`/`SLIDES`/`REGLA_DATOS` de `infografia_ia_openai.py` siguen siendo los mismos) — la única pieza nueva es de dónde sale el diccionario de entrada.
- **Solo aplica a un `AnalisisV2` completo con hallazgos reales**: si `estado != "completo"` o `resultado.estado` es `sin_datos`/`datos_insuficientes`, `400` con un mensaje explícito antes de crear el registro (misma validación previa que ya existe para los otros tres tipos) — no tendría sentido generar una lámina de hallazgos vacía.
- **Aislamiento por versión exacta, igual que los otros tres**: el `409` de "ya hay una infografía en curso" y el `?analisis_v2=<id>` en el listado siguen el mismo criterio de HU-72 de este archivo — dos infografías de dos `AnalisisV2` distintos, aunque sean de la misma jornada, corren en paralelo sin bloquearse ni compartir resultado.
- 4 tests nuevos (`InfografiaDesdeAnalisisV2Tests` en `analitica/tests_v2.py`: la traducción del resultado v2 al formato de las láminas, `400` cuando el análisis no está completo o es `sin_datos`, la API fija el `analisis_v2` y deriva `momento` correctamente, y dos FKs a la vez dan `400`); la suite completa del proyecto no se corrió en esta entrega por decisión del dueño del repo.

### HU-78 — Los endpoints existentes producen el contrato v2 (rediseño)
Como dueño del producto quiero que el contrato `kunsamu.analisis/v2` sea la salida de los tres endpoints que el frontend ya integraba (`analisis-jornada-ia/`, `analisis-momento-ia/`, `reportes/`), no una cuarta vía aparte, para no dejarle al frontend dos sistemas de análisis corriendo en paralelo indefinidamente cuando la intención siempre fue reemplazar uno por el otro.
- **La corrección de rumbo, explícita**: HU-73 a HU-77 (de este mismo archivo) construyeron el contrato v2 como `POST /api/admin/analisis-v2/`, un cuarto endpoint independiente de los tres de siempre. Terminada esa entrega, el dueño del repo aclaró que la lectura correcta del encargo original era otra: v2 debía **rediseñar** la salida de `analisis-jornada-ia/`, `analisis-momento-ia/` y `reportes/`, no sumarse como una opción más que el frontend tuviera que elegir entre mantener. Se corrigió de inmediato, en el mismo repo y sin descartar nada de lo ya construido: `analitica/v2/procesar.py::ejecutar_analisis_v2` (el núcleo que ya validaba, reintentaba reparación y guardaba diagnóstico para `AnalisisV2`) pasó a ser también el motor de los tres puntos de entrada existentes — `analizar_jornada_ia`/`analizar_momento_ia` (`analisis_ia_openai.py`) y `procesar_reporte` (`analysis.py`).
- **El frontend no cambia ni una llamada.** Es la condición que hace viable un rediseño en vez de una migración coordinada: los tres endpoints siguen aceptando exactamente el mismo cuerpo de petición, y el campo donde el frontend ya leía el resultado (`resultado` en los dos análisis IA, `analisis` en `Reporte`) sigue siendo ese mismo campo — solo cambia el JSON que hay adentro. `analisis-jornada-ia/` corre `llm`/`integral` (todos los momentos, un informe); `analisis-momento-ia/` corre `llm`/`por_momento` de ese momento, con `contexto_momento`/`instrucciones_momento` viajando como `personalizacion_momentos` hacia `entrada.personalizacion.instrucciones_por_momento`; `reportes/` corre `bertopic_llm`, con `momentos=[]` → `integral` y `momentos` con ids → `por_momento` (un informe independiente por cada uno), y `texto_reporte` pasa a ser el resumen de esos informes (`resumen_de_salida`) en vez de la síntesis del pipeline multiagente anterior.
- **`enfoque` (los tres) y `plantilla` (`reportes/`) se conservan por compatibilidad, no porque sigan haciendo algo.** El contrato v2 no tiene noción de enfoque cuantitativo/cualitativo — el modelo decide método y tipo de gráfica por hallazgo, hallazgo a hallazgo — así que reescribir esos dos campos como obligatorios o quitarlos habría roto formularios del frontend que ya los mandan sin necesidad real. Se siguen aceptando y guardando en el registro tal cual llegan; simplemente dejan de leerse en ningún punto del pipeline nuevo.
- **Auditoría idéntica a la de `AnalisisV2`, para no tener dos varas distintas de trazabilidad.** `Reporte`, `AnalisisMomentoIA` y `AnalisisJornadaIA` ganan `entrada`, `diagnostico`, `version_prompt` y `version_esquema` vía el mismo mixin `ResultadoV2Mixin` que ya tenía `AnalisisV2` (migración `0019_resultado_v2_en_analisis_existentes.py`). Los `GET` de detalle y de lista exponen `diagnostico`/`version_prompt`/`version_esquema` pero nunca `entrada` — mismo criterio de "no servir el corpus completo en cada polling" que ya regía en `AnalisisV2ListaSerializer`.
- **La lista unificada gana una señal explícita de qué renderer usar, en vez de depender de que el frontend adivine por la forma del JSON.** Todos los items de `GET /api/admin/analisis/` — los tres tipos legacy y `analisis_v2` — traen ahora `version` (`"kunsamu.analisis/v2"` en los generados con el contrato nuevo, `null` en los anteriores al rediseño) y `estado_analitico` (`_claves_v2` en `admin_views.py`). Es la pieza que hacía falta para que un mismo tipo de registro (un `AnalisisJornadaIA`, por ejemplo) pudiera tener, a la vez, análisis viejos con el formato jerárquico y análisis nuevos con el contrato v2, sin que el panel tuviera que abrir cada uno para saber cómo pintarlo.
- **Por qué `400` y no una traducción silenciosa en presentación/PDF.** `generar-presentacion` y `pdf` (`ReporteViewSet`) leen específicamente el formato jerárquico anterior de `Reporte.analisis` (`participacion` + `momentos` + `preguntas`); el contrato v2 no tiene esa forma. Traducir un JSON v2 a ese formato antiguo solo para no tocar esas dos capas habría sido forzar una estructura que el nuevo contrato deliberadamente no tiene (no hay `participacion` calculada aparte, los hallazgos no son "preguntas"), o peor, producir una página/PDF incompleto sin avisar. Se optó por un `400` con mensaje explícito (`MENSAJE_SIN_PRESENTACION_V2`) que sigue funcionando sin cambios para los reportes generados antes del rediseño — adaptar esas dos capas al contrato v2 es una HU aparte, deliberadamente fuera de esta.
- **Por qué los prompts y el pipeline anteriores se quedan en el código en vez de borrarse.** `SYSTEM_PROMPT`/`SYSTEM_PROMPT_JORNADA` (`analisis_ia_openai.py`), los agentes de `analysis.py` (`analizar_pregunta`/`_sintetizar_momento`/`analizar_jornada`) y `prompt_comun.py` ya no corren en ningún análisis nuevo, pero siguen siendo la referencia exacta de cómo se generaron TODOS los registros históricos anteriores al rediseño — borrarlos habría dejado esos registros sin una fuente legible de "con qué prompt salió esto", justo el tipo de trazabilidad que el proyecto viene cuidando desde HU-14. Quedan documentados como histórico (ver `docs/SYSTEM_PROMPTS.md`) en vez de vivos.
- **Transcripciones vinculadas a la jornada** (`incluir_en_analisis_jornada=True`) entraban al análisis de jornada anterior como resúmenes ya redactados (`_transcripciones_payload`); el análisis v2 de jornada (`analizar_jornada_ia`) todavía no las incluye como fuente. Limitación conocida y aceptada para esta entrega — no bloqueaba el rediseño porque el caso de uso principal (jornada sin transcripciones vinculadas) sigue funcionando igual; incorporarlas es una HU aparte.
- 8 tests nuevos en `analitica/tests_v2.py` (`EndpointsExistentesProducenV2Tests`: los tres puntos de entrada corren el pipeline v2 con el modo/pipeline correcto, `contexto_momento`/`instrucciones_momento` llegan a `personalizacion.instrucciones_por_momento`, `reportes/` por varios momentos genera un informe por cada uno, y un error del proveedor deja el registro en `error` con diagnóstico; `ListaUnificadaYPresentacionV2Tests`: la lista unificada distingue `version`/`estado_analitico` entre un registro legacy y uno v2 del mismo tipo, presentación y PDF responden `400` para un `Reporte` v2, y el detalle legacy expone `version_prompt`/`diagnostico`); la suite completa del proyecto no se corrió en esta entrega por decisión del dueño del repo.

### HU-79 — Diseño de presentación con IA a partir de los assets de la jornada
Como administrador quiero pedirle a un modelo con visión que diagrame la presentación (colores, tipografía, papel de cada asset, plantilla de cada diapositiva) a partir de los assets ya cargados en la jornada, para dejar de hacer esa llamada desde el frontend y no perder el resultado cada vez que alguien vuelve a abrir la presentación — brief completo en `docs/HU_BACKEND_DISENO_PRESENTACION.md`.
- **Modelo nuevo `PresentacionDiseno`**, mismo patrón "exactamente uno de `reporte`/`analisis_momento`/`analisis_jornada`" que `InfografiaJornada` (HU-73), pero como `OneToOneField` (no `ForeignKey`): un análisis tiene A LO SUMO un diseño guardado a la vez, y un `POST` repetido sobre el mismo análisis **actualiza** esa fila (`update_or_create`) en vez de crear una segunda — es el «Rediseñar» del usuario. La regla de "exactamente uno" se valida a mano en la vista, no con una constraint de base de datos, mismo criterio ya establecido para `InfografiaJornada`. Migración `0020_presentacion_diseno.py`, dependiente de `0019_resultado_v2_en_analisis_existentes`.
- **`presentacion-diseno` es opcional y bajo demanda por diseño**: nunca se genera sola. `GET /api/admin/presentacion-diseno/?<fuente>=<id>` sólo consulta (`200` con el diseño guardado, `404` si no hay ninguno) y **nunca** dispara una llamada al proveedor; `POST` genera o regenera; `DELETE /api/admin/presentacion-diseno/{id}/` descarta el diseño guardado y vuelve al institucional. El `GET` no es un `retrieve` por id — siempre se pide por análisis, nunca por el id propio del diseño, así que el `ViewSet` sólo implementa `list` (reinterpretado para devolver EL objeto de la fuente pedida, no un array), `create` y `destroy`; sin `retrieve`/`update` a propósito.
- **La llamada a OpenAI es SÍNCRONA**, a diferencia de todo el resto del módulo (`analisis_ia_openai.py`, `infografia_ia_openai.py`, `analitica/v2/llm.py`), que corre en un hilo de background con polling — la HU mide entre 7 y 20 segundos con tres imágenes en detalle bajo, tiempo que el frontend puede esperar directamente en el `POST` sin necesitar un estado `procesando`. Cascada de modelos: `KUNSAMU_DESIGN_MODEL` (si está configurado) → `gpt-5.1` → `gpt-4.1`, probando el siguiente sólo si el proveedor responde un `4xx` cuyo mensaje menciona "model"; cualquier otro error corta con `502`. Timeout de 60s vía el propio cliente de OpenAI (sin hilo manual, porque acá no hace falta liberar la petición HTTP mientras corre).
- **`modelo` guarda el nombre real del modelo que respondió** (`gpt-5.1`, `gpt-4.1`, o el de `KUNSAMU_DESIGN_MODEL`) — la única excepción documentada a la convención del proyecto de nunca exponer el proveedor/modelo real en un campo genérico; la HU lo pide explícitamente en su contrato de respuesta (§2.2).
- **Assets adjuntos con límites duros**: como máximo 6 imágenes, cada una ≤ 4 MB, sólo `image/png`/`image/jpeg`/`image/webp`/`image/gif` — el mime se detecta con PIL a partir de los BYTES reales de cada archivo, nunca de la extensión del nombre. PDF y SVG se listan por nombre en el JSON de contexto pero nunca se adjuntan como imagen (a diferencia de `infografia_ia_openai.py`, que sí rasteriza la primera página de un PDF — acá la HU lo excluye explícitamente). Si ningún asset de la jornada tiene ni imagen adjuntable ni guía de marca escrita (`JornadaAsset.texto` en un `system_design`), `422` sin llamar al modelo.
- **Esquema JSON estricto (`response_format: json_schema`, `strict: true`) y system prompt, ambos transcritos literalmente de la HU** (`analitica/presentacion_diseno_ia.py::JSON_SCHEMA`/`SYSTEM_PROMPT`) — verificados programáticamente byte a byte contra el texto de `docs/HU_BACKEND_DISENO_PRESENTACION.md` antes de cerrar la entrega, para que ningún ajuste de estilo del código (saltos de línea, comillas) alterara el contenido real que recibe el modelo.
- **Saneamiento en vez de rechazo**: el backend corrige cada valor inválido o incoherente del modelo contra un diseño institucional de respaldo (colores/tipografía/fondo fijos) y anota cada corrección como una frase corta en `correcciones` — nunca descarta el diseño completo salvo que falte la forma base del contrato (`version`/`tema`/`logo`/`assets`/`diapositivas`), en cuyo caso es `502`. Incluye: contraste WCAG (luminancia relativa sobre sRGB linealizado) para forzar fondo y texto legibles; reclasificación de `rol` de asset fuera de enum a `no_usar`; un asset con rol `logo`/`logo_secundario` inválido en `logo.asset_id` se reemplaza por el primer asset con rol `logo` si existe; y, por diapositiva, la plantilla se valida contra las admisibles por `tipo` (con su propio valor por defecto), la ilustración propuesta sólo se usa si su `rol` es realmente `ilustracion` (si no, se sustituye por la primera disponible distinta de la de la diapositiva anterior, o se cae a la variante sin imagen si no hay ninguna).
- **`diapositivas` viaja intacta**: la secuencia que manda el frontend en el `POST` se guarda tal cual y es la que se recorre para sanear (nunca la lista que devuelve el modelo, que sólo se consulta por `id` — cualquier id que el modelo haya inventado se ignora solo, al no buscarse nunca). Lista vacía o con un `tipo` de diapositiva fuera de `portada`\|`cobertura`\|`resumen`\|`hallazgo`\|`recomendaciones`\|`limitaciones`\|`cierre` → `400`, antes de resolver la fuente o llamar al modelo.
- **`assets` en la respuesta del `POST`/`GET`** (distinto de `diseno.assets`) son los ids de `JornadaAsset` que terminaron en `diseno.assets` tras el saneamiento — que por construcción es uno por cada asset real de la jornada — para que el frontend detecte que la jornada cambió de assets desde que se generó el diseño y ofrezca «Rediseñar».
- **Interpretación explícita de un campo ambiguo de la HU**: `analisis.titulo` (el contexto que recibe el modelo, HU §5.2) se documenta como "el título del análisis en la lista unificada", pero `GET /api/admin/analisis/` no expone ningún campo `titulo` propio (ver HU-71). Se usa en su lugar el `titulo` del primer informe del contrato v2 (`resultado.informes[0].titulo`), que sí existe siempre y es un dato ya calculado por el análisis — más defendible que inventar una heurística de título nueva sólo para este prompt.
- Endpoint documentado en `/api/schema/` vía `@extend_schema` (verificado con `manage.py spectacular`, sin errores nuevos atribuibles a este cambio) y en `docs/INTEGRACION_FRONTEND_PRESENTACION_DISENO.md` para el frontend. No se escribieron tests ni se corrió la suite en esta entrega, por decisión explícita del dueño del repo — se verificó manualmente `manage.py check`, `makemigrations --check --dry-run` ("No changes detected") y la generación del esquema OpenAPI.
