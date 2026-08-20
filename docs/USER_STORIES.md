# Historias de usuario

Formato: **Como** `<rol>` **quiero** `<acción>` **para** `<beneficio>`, con criterios de aceptación.

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

### HU-10 — Ver participantes inscritos
Como administrador quiero ver la lista de participantes inscritos en una jornada, para hacer seguimiento de la asistencia.
- `GET /api/admin/participantes/?jornada=<id>` lista nombre, apellido, correo, teléfono y fecha de registro.
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
    "slug": "camila-gomez",
    "token": "b058878f-5797-40ac-ab56-9779902ab300",
    "creado_en": "2026-08-18T19:11:58.251917-05:00"
  }
]
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
    "mesa": "",
    "texto_libre": "",
    "opciones": [16],
    "actualizado_en": "2026-08-19T21:15:03.112Z"
  }
]
```
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
Como usuario quiero registrarme en una jornada indicando mi correo institucional, nombre, apellido y teléfono, para inscribirme.
- `POST /api/jornadas/{slug}/registro/` crea el `Participante`.
- Si el correo ya está registrado en esa jornada, la API responde 400 sin crear un duplicado.
- Se genera automáticamente un `slug` a partir de nombre y apellido (con sufijo si hay colisión).

<details><summary>Ejemplo — <code>POST /api/jornadas/jornada-agil-2/registro/</code></summary>

Request:
```json
{
  "correo_institucional": "camila.gomez@unimagdalena.edu.co",
  "nombre": "Camila",
  "apellido": "Gómez",
  "telefono": "3000000000"
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
  "slug": "camila-gomez",
  "token": "b058878f-5797-40ac-ab56-9779902ab300",
  "creado_en": "2026-08-18T19:11:58.251917-05:00"
}
```

Error (correo ya registrado en esta jornada), `400`:
```json
{ "correo_institucional": ["Ya existe un participante con este correo en esta jornada."] }
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

### HU-19 — Listar los momentos de mi jornada
Como usuario ya registrado quiero consultar el índice de momentos de la jornada a la que pertenezco, para saber qué pasos debo recorrer.
- `GET /api/jornadas/{slug}/momentos/` requiere el token del paso anterior y devuelve `id`, `orden`, `título`, `slug` (autogenerado del título, único dentro de la jornada) y `tipo` de cada momento activo, ordenados por `orden`.

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
  { "id": 501, "pregunta": 38, "participante": 13, "mesa": "", "texto_libre": "", "opciones": [16], "actualizado_en": "2026-08-19T21:15:03.112Z" },
  { "id": 502, "pregunta": 45, "participante": 13, "mesa": "", "texto_libre": "Debe existir consentimiento previo, libre e informado antes de iniciar cualquier trabajo con comunidades.", "opciones": [], "actualizado_en": "2026-08-19T21:15:03.118Z" }
]
```
</details>

### HU-22 — Responder un momento de tipo "mesa"
Como usuario en un momento `mesa` quiero indicar el identificador de mi mesa y enviar una respuesta compartida, para que el resultado represente a todo el grupo.
- El body debe incluir `mesa` (texto libre); la API responde 400 si falta.
- Si otro participante de la misma mesa vuelve a responder, la respuesta se actualiza (no se duplica); se registra quién la envió por última vez (`registrado_por`) para trazabilidad.

<details><summary>Ejemplo — <code>POST /api/jornadas/jornada-agil-2/momentos/5/respuestas/</code></summary>

Request:
```json
{
  "mesa": "Mesa 3",
  "respuestas": [
    { "pregunta_id": 20, "opcion_ids": [4] },
    { "pregunta_id": 17, "texto_libre": "Cuidar la confianza y el consentimiento informado de las comunidades." }
  ]
}
```

Response `200`:
```json
[
  { "id": 610, "pregunta": 20, "participante": null, "mesa": "Mesa 3", "texto_libre": "", "opciones": [4], "actualizado_en": "2026-08-19T21:20:00.000Z" },
  { "id": 611, "pregunta": 17, "participante": null, "mesa": "Mesa 3", "texto_libre": "Cuidar la confianza y el consentimiento informado de las comunidades.", "opciones": [], "actualizado_en": "2026-08-19T21:20:00.005Z" }
]
```

Error (falta `mesa` en un momento tipo mesa), `400`:
```json
{ "mesa": "Este momento requiere identificar la mesa." }
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

## Documentación técnica (pública, sin rol)

No son historias de usuario en sentido estricto, pero son endpoints que expone la API y conviene tener presentes:

- `GET /api/schema/` — esquema OpenAPI 3 en crudo.
- `GET /api/docs/` — Swagger UI interactivo.
- `GET /api/redoc/` — Redoc (documentación de solo lectura).
