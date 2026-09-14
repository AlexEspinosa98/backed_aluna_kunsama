# Historias de usuario — Transcripciones (sesiones grabadas, informe con IA)

Formato: **Como** `<rol>` **quiero** `<acción>` **para** `<beneficio>`, con criterios de aceptación.
Complementa a [USER_STORIES.md](USER_STORIES.md) (jornadas/participantes) y
[USER_STORIES_INSTRUMENTOS.md](USER_STORIES_INSTRUMENTOS.md) con un tercer caso de uso
independiente: ver el contexto completo del módulo en `CLAUDE.md`.

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
