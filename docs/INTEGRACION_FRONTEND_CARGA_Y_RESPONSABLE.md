# Integración frontend — Carga de documentos diligenciados

Guía completa de las tres vías por las que entra un formato diligenciado fuera de la web. Estado
al **2026-10-04** (HU-55, 56, 84, 86, 87, 88, 89).

**Lo primero, porque condiciona todo lo demás:** las tres vías se parecen pero ya **no** se
comportan igual. Los cambios de octubre tocaron solo la carga de **momentos**; la de
**instrumentos** quedó como estaba. Si se construye una sola pantalla asumiendo que son lo mismo,
va a estar mal en la mitad de los casos.

| | A · El participante sube lo suyo | B · Admin sube de un **momento** | C · Admin sube un **instrumento** |
|---|---|---|---|
| Endpoint | `.../momentos/{id}/cargar-archivo/` | `/api/admin/momento-extracciones/` | `/api/admin/instrumento-extracciones/` |
| ¿Se guarda solo? | No — devuelve sugerencias y el participante envía | **Sí**, al terminar | No — la aplicación queda `pendiente` de revisión |
| ¿Hay que aprobar? | No | **No** (el endpoint quedó obsoleto) | Sí, el encargado revisa la aplicación |
| ¿Carga masiva? | No | **Sí** | No |
| ¿Se crea al responsable si no existe? | No aplica (es quien sube) | **Sí**, con el nombre del documento | **No** — hay que elegir de los que existen |
| ¿Se puede corregir lo guardado? | Sí, reenviando el momento | **Sí**, `PATCH` por respuesta | No, es de solo lectura |

---

## Autenticación

| Quién | Header |
|---|---|
| Admin/staff | `Authorization: Token <hex de 40 chars>` |
| Usuario de instrumento | `Authorization: Token <hex de 40 chars>` |
| Participante de jornada | `Authorization: Participant <uuid>` |

El usuario de instrumento es un `User` de Django con `is_staff=false` y usa el mismo esquema
`Token` que el admin — lo que cambia es a qué endpoints llega, no el header. Se autentica en
`POST /api/instrumentos/login/`.

---

# Vía A · El participante sube su propio documento

Sin cambios desde HU-56. Acá la revisión pasa **antes** de escribir, así que nunca hubo un trámite
que quitar: el participante ve lo que la IA leyó, lo corrige en pantalla y lo envía él.

## Cuándo mostrar el botón

```
GET /api/jornadas/{jornada_slug}/momentos/                  (índice)
GET /api/jornadas/{jornada_slug}/momentos/{momento_id}/     (detalle)
Authorization: Participant <token del participante>
```
```json
{ "id": 61, "titulo": "Diagnóstico de Articulación Académica",
  "tipo": "individual", "permite_carga_archivo": true, "preguntas": [ ... ] }
```

**Mostrar el botón solo si `permite_carga_archivo` es `true`.** Viene apagado por defecto y se
habilita momento por momento; si está en `false` y se intenta subir igual, el backend responde
`403`. No lo deduzcan de ninguna otra cosa — es el único dato que lo dice.

## Subir

```
POST /api/jornadas/{jornada_slug}/momentos/{momento_id}/cargar-archivo/
Content-Type: multipart/form-data

archivo: <el .pdf o .docx>
```

Solo `.pdf` y `.docx` (`400` con la clave `archivo` si es otra cosa — validen también en cliente
para no gastar la subida). El documento queda **siempre a nombre de quien sube**: no manden
`participante_id`, el backend lo ignora y usa la sesión.

## Polling

```
GET /api/jornadas/{jornada_slug}/momentos/{momento_id}/mis-cargas/
```

Devuelve solo las cargas del propio participante (el endpoint de admin no les va a responder).
Un intervalo de 3–5 s está bien; un documento largo escaneado puede tardar minutos.

| `estado` | Qué mostrar |
|---|---|
| `pendiente` | "En cola" |
| `procesando` | "Leyendo tu documento…" |
| `completo` | Precargar la pantalla del momento con `respuestas_sugeridas` |
| `error` | Mostrar `error_mensaje` y ofrecer volver a intentar |

## Precargar y enviar

Cuando `estado` llega a `completo`, `respuestas_sugeridas` trae el arreglo ya en el **mismo formato
que espera** `POST /api/jornadas/{jornada_slug}/momentos/{momento_id}/respuestas/`:

```json
"respuestas_sugeridas": [
  {"pregunta_id": 101, "texto_libre": "Buena, aunque con retos", "opcion_ids": [], "fila_id": null, "columna_id": null, "fila_temporal": null},
  {"pregunta_id": 104, "texto_libre": "", "opcion_ids": [37], "fila_id": null, "columna_id": null, "fila_temporal": null}
]
```

1. Precarguen con eso los mismos controles que ya usan para renderizar el momento — el
   `pregunta_id` de cada item dice a cuál control corresponde.
2. Dejen que el participante corrija, igual que corregiría una respuesta escrita a mano.
3. Al enviar, manden ese arreglo con las correcciones como `{"respuestas": [...]}` a
   `POST .../momentos/{id}/respuestas/` — **el mismo endpoint del envío normal**. Ahí es donde de
   verdad se guardan las respuestas.
4. Una pregunta que no aparezca en `respuestas_sugeridas` es una que la IA no pudo transcribir
   (queda también en `preguntas_omitidas`): muéstrenla vacía para que la complete a mano.

Copy sugerido: *"Revisa lo que encontramos en tu documento y corrige lo que haga falta antes de
enviar"* — nunca "Momento enviado" hasta que confirme el envío en el paso 3.

Al enviar se sobrescribe lo que el participante tuviera guardado de antes, con el mismo criterio
de siempre (`RespuestasMomentoView`).

---

# Vía B · Un admin sube documentos de un momento

Es la vía que cambió. Tres cosas nuevas: se guarda sin aprobación, se puede subir una tanda, y lo
guardado se puede corregir.

## Qué hay que implementar

1. **Quitar el botón «Aprobar».** Cuando el polling devuelve `estado: "completo"` con
   `aprobado_en` lleno, las respuestas ya están guardadas.
2. **Pantalla de carga masiva** con progreso por archivo y los rechazados a la vista.
3. **Pantalla de corrección** de respuestas guardadas.
4. **Dos advertencias antes de subir** (ver "Sobrescribe lo anterior").
5. **El diálogo de asignar responsable deja de ser una lista cerrada**: si la persona no está, se
   escribe el nombre y se crea.

## Subir uno

```
POST /api/admin/momento-extracciones/
Content-Type: multipart/form-data

momento: 61
archivo: <el .pdf o .docx>
```

`participante_id` es **opcional**. Los tres caminos siguen válidos:

| Qué mandan | Qué pasa |
|---|---|
| `participante_id` | Se usa esa persona. La IA **no** la pisa (`responsable_estado: "no_buscado"`). |
| Los campos de alta completos (`nombre`, `apellido`, `correo_institucional`, `rol`) | Se crea/reutiliza la persona. |
| **Nada** | La IA lee el responsable del documento y el backend lo resuelve. |

Mandar **media** ficha de alta (solo `nombre`, por ejemplo) sigue siendo `400`: omitir todo es
delegarle la detección a la IA, mandar la mitad es un error del cliente.

## Subir una tanda

```
POST /api/admin/momento-extracciones/masiva/
Content-Type: multipart/form-data

momento:  61
archivos: <archivo 1>
archivos: <archivo 2>
archivos: <archivo N>
```

El campo `archivos` se repite, uno por archivo. **Hasta 30 por request**, solo `.pdf` y `.docx`.

**No manden `participante_id`.** La masiva existe para la pila de formatos de departamentos
distintos: a cada archivo le corresponde una persona distinta y se lee del propio documento.

Respuesta `201`:

```json
{
  "creadas": [
    { "id": 50, "estado": "pendiente", "nombre_archivo_original": "antropologia.docx", ... },
    { "id": 51, "estado": "pendiente", "nombre_archivo_original": "biologia.pdf", ... }
  ],
  "rechazadas": [
    { "archivo": "notas.xlsx", "error": "Solo se aceptan archivos .pdf o .docx." }
  ]
}
```

**Un archivo inválido no tumba la tanda**: los buenos se crean y los malos vuelven en
`rechazadas`. Muéstrenlos — es la única señal de que ese archivo no entró. Si no sirve ninguno,
`400`.

## El polling de la tanda

Los documentos se procesan **uno después de otro**, no todos a la vez: cada uno son entre cinco y
nueve llamadas al proveedor de IA, y treinta en paralelo darían contra el límite de tasa. Una
tanda grande tarda, y los archivos van cambiando de estado de a uno.

```
GET /api/admin/momento-extracciones/?momento=61
```

El índice que ya usan. Cada item trae su propio `estado` y su propio `error_mensaje`; 5–10 s de
intervalo está bien. **Una que falle no detiene a las demás**: para reintentar solo esa, se vuelve
a subir ese archivo, suelto o en otra tanda.

## Cuando termina, ya está guardado

```json
{
  "id": 42,
  "estado": "completo",
  "aprobado_en": "2026-10-04T15:32:11Z",
  "aprobado_por": 3,
  "participante": 88,
  "resultado": { "respuestas": [ ... ] },
  "preguntas_omitidas": []
}
```

`aprobado_en` con fecha significa que las respuestas **ya se escribieron**. Los nombres de esos dos
campos quedaron del flujo anterior y hoy significan "cuándo se escribieron las respuestas y a
cuenta de quién", no "un humano lo aprobó".

`aprobar/` **sigue existiendo y responde `200`** por compatibilidad —es idempotente y no duplica
nada— pero ya no hace falta y conviene sacarlo del flujo.

## De quién es el documento

En la mayoría de los casos no hace falta intervenir:

| `responsable_estado` | Significa | ¿Intervenir? |
|---|---|---|
| `no_buscado` | Se indicó la persona a mano al subir | No |
| `emparejado` | Coincidió exactamente con una persona de la jornada | No |
| `creado` | No coincidió con nadie y **se dio de alta** con el nombre del documento | No |
| `ambiguo` | Coinciden **varias** personas registradas | **Sí** |
| `sin_coincidencia` | El documento traía correo pero **ningún nombre legible** | **Sí** |
| `sin_dato` | El documento no traía responsable | **Sí** |

`responsable_detectado` es **lo que la IA leyó**, tal cual, sin normalizar:

```json
{ "responsable_detectado": {
    "nombre": "Rosa Elena Pardo Lince", "correo": null,
    "cargo": "Jefa de Departamento", "dependencia": "Biología" },
  "responsable_estado": "creado" }
```

**Sobre `creado`:** vale mostrarlo distinto de `emparejado`. Son personas nuevas nacidas de un
papel, con `rol` en `"sin rol"` y —si el documento no traía correo— un correo de relleno en
`@sin-registro.local` con el que **no pueden entrar a la plataforma**. Si después se registran de
verdad, son las que hay que reconciliar.

El segundo documento de esa misma persona **no la duplica**: llega como `emparejado` apuntando al
participante ya creado, incluso si el nombre viene con otras mayúsculas o tildes.

**Sobre los tres que piden intervención:** `estado` queda `completo` pero `aprobado_en` viene en
`null` y `participante` en `null`. La transcripción está lista; lo único que falta es a nombre de
quién guardarla.

> **No "resuelvan" ustedes una ambigüedad tomando el primero.** El backend deliberadamente no lo
> hace: una respuesta atribuida a quien no la dio es peor que una que espera un clic. Muestren
> `responsable_detectado` para que quien revisa decida con el dato a la vista.

## Asignar la persona que faltó

```
POST /api/admin/momento-extracciones/{id}/asignar-responsable/

{ "participante_id": 17 }                     // elegir de los que ya existen

{ "nombre": "Rosa Elena Pardo Lince" }        // darlo de alta en el acto

{ "nombre": "Rosa Elena Pardo Lince",         // ídem, con correo si lo tienen
  "correo_institucional": "rosa.pardo@unimagdalena.edu.co" }
```

Hay que mandar **exactamente una** de las dos formas; las dos juntas, o ninguna, es `400`.

- **No vuelve a llamar a la IA**: usa la transcripción ya guardada. Es instantáneo.
- **Este mismo llamado escribe las respuestas.** La respuesta vuelve con `aprobado_en` lleno; no
  hay que aprobar después.
- Si el nombre que escriben ya corresponde a alguien de la jornada, se asigna a esa persona en vez
  de crear una homónima — un dedazo no deja dos fichas de la misma persona.
- `responsable_estado` **sí** se actualiza: queda en `creado` o `emparejado` según qué pasó.

## ⚠️ Sobrescribe lo anterior

Si el participante ya tenía respuestas en ese momento —porque las mandó por la web, o porque ya se
le cargó otro documento— la carga las reemplaza:

- **celdas y preguntas sueltas**: se pisa el contenido de cada una que el documento mencione. Las
  que el documento no menciona quedan intactas.
- **tablas de filas agregadas** (mapa de capacidades profesorales, asuntos para decisión
  institucional, compromisos inmediatos): se borran **todas** las filas de esa pregunta y se
  recrean con las del documento. Si había diez profesores cargados por la web y el documento trae
  tres, **quedan tres**.

Es el mismo criterio que el envío normal desde la web: el documento es *la* versión buena de esa
tabla, no un anexo. Pero el usuario tiene que saberlo antes de arrastrar treinta archivos, y desde
que la escritura es automática ya no hay un paso donde alguien pueda notarlo.

**Dos advertencias que pedimos poner:**

1. En la pantalla de carga, individual y masiva: que los documentos reemplazan lo que esas personas
   hubieran respondido en ese momento.
2. Si en una misma tanda hay dos documentos del mismo responsable, el segundo pisa al primero y el
   backend no avisa. Si se puede detectar en cliente —dos archivos que terminan con el mismo
   `participante`— vale advertirlo.

## Corregir una respuesta guardada

Es la contraparte de haber quitado la aprobación: si la IA leyó mal una celda, quien subió el
documento la arregla.

```
PATCH /api/admin/respuestas/{id}/
{ "texto_libre": "lo que de verdad decía el formato" }

PATCH /api/admin/respuestas/{id}/
{ "opcion_ids": [37] }

DELETE /api/admin/respuestas/{id}/
```

**Solo `texto_libre` y `opcion_ids`.** Mandar `pregunta`, `fila` o `columna` no hace nada: mover
una celda no es corregir una transcripción, y dejarlo abierto sería una forma de pisar la
respuesta de otra persona por error. Si hay que mover algo, se borra la celda y se crea por la vía
normal.

**No hay `POST`** a `/api/admin/respuestas/`: una respuesta nace del envío del participante o de
una carga, nunca de un admin escribiéndola a mano.

La validación es la misma del envío normal, así que un `400` acá significa lo mismo que allá: una
matriz no acepta opciones, una pregunta de opción única no acepta dos marcadas.

En filas dinámicas (las que el grupo agregó a mano, con `fila_lista` en vez de `fila`): si se
borran **todas** las celdas de una fila, la fila se borra también. No queda una fila vacía
colgando.

### De dónde salen los ids

```
GET /api/admin/respuestas/?momento=61
```

Cada item trae `id`, `pregunta`, `participante`, `fila`, `fila_lista`, `columna` y `texto_libre`.
Para armar la pantalla de revisión, cruzarlo con `GET /api/admin/momentos/{id}/` —que da las
preguntas con sus filas y columnas— es lo mismo que ya hacen para pintar un momento.

---

# Vía C · Un admin sube un instrumento

**Esta vía NO cambió.** Sigue como quedó en HU-55, y por eso se comporta distinto de la de
momentos. Las diferencias importan al construir la pantalla:

```
POST /api/admin/instrumento-extracciones/
{ "instrumento": 3, "archivo": <file> }
```

`usuario_id` es opcional, igual que en momentos: si no se manda, la IA lee el responsable.

## Estados propios

| `estado` | Significa |
|---|---|
| `pendiente` | En cola |
| `procesando` | La IA está leyendo |
| `sin_responsable` | **Transcrito, pero falta asignar la persona** — pide acción, no es un error |
| `completo` | Escrito; la aplicación quedó en revisión |
| `error` | Falló (ver `error_mensaje`) |

A diferencia de momentos, acá **sí hay un estado propio** para la falta de responsable, y
`sin_coincidencia` lleva a él: en instrumentos **no se crea la persona** a partir del nombre leído.

## Asignar

```
POST /api/admin/instrumento-extracciones/{id}/asignar-responsable/
{ "usuario_id": 17 }
```

- **Solo acepta usuarios que ya existen.** No hay forma de darlos de alta por acá, y es
  deliberado: un usuario de instrumento es una cuenta con credenciales de acceso, no una ficha
  dentro de una jornada, así que fabricarla desde un nombre leído por IA es una decisión distinta
  —y más seria— que crear un `Participante`. Si el responsable no tiene cuenta, hay que crearla
  por la vía normal y después asignarla.
- Solo funciona sobre una extracción en `sin_responsable` (`400` si no).
- `responsable_estado` **no cambia** al asignar: queda como registro de por qué hubo que hacerlo a
  mano. Para saber si está resuelto, miren `usuario` y `estado`.

## Lo demás que falta en esta vía

- **No hay carga masiva.** Un archivo por request.
- **La aplicación queda `pendiente` de revisión** del encargado (acepta o rechaza): acá no se
  quitó el paso de aprobación, porque ese estado lo usan *todas* las aplicaciones del instrumento,
  no solo las que vinieron de una carga.
- **Las respuestas del instrumento son de solo lectura** por la API
  (`AplicacionInstrumentoAdminViewSet`): no hay `PATCH` equivalente al de momentos.

---

# Checklist

**Vía A — participante**

- [ ] Leer `permite_carga_archivo` antes de pintar el botón (no deducirlo).
- [ ] Validar extensión en cliente (`.pdf` / `.docx`).
- [ ] No mandar `participante_id`: el dueño es quien sube.
- [ ] Polling con `mis-cargas/`.
- [ ] Al llegar a `completo`, precargar con `respuestas_sugeridas` y dejar corregir. **No hay
      `aprobar/` en esta vía**: el envío final es el `POST .../respuestas/` de siempre.

**Vía B — admin, momentos**

- [ ] Quitar el botón «Aprobar».
- [ ] Dejar de exigir la persona antes de subir.
- [ ] Pantalla de carga masiva, con los `rechazadas` a la vista.
- [ ] Polling por tanda con el índice filtrado por momento.
- [ ] Manejar los **6** valores de `responsable_estado`, no solo `emparejado`.
- [ ] Mostrar `responsable_detectado` siempre que haya que elegir a mano.
- [ ] No auto-seleccionar en `ambiguo`.
- [ ] Permitir escribir un nombre nuevo en el diálogo de asignar.
- [ ] Advertir que una carga sobrescribe lo anterior.
- [ ] Pantalla de corrección (`PATCH` / `DELETE` por respuesta).

**Vía C — admin, instrumentos**

- [ ] Tratar `sin_responsable` como un estado que **pide acción**, no como error.
- [ ] En el diálogo de asignar, **solo** personas que ya existen (no ofrecer crear).
- [ ] No esperar carga masiva ni corrección de respuestas: no existen en esta vía.
- [ ] Recordar que la aplicación queda `pendiente` de revisión del encargado.

---

## Lo que no cambia el contrato

Los arreglos del lector de documentos (HU-80 a 83) y el cambio de modelo de transcripción (HU-87)
no tocan la API. Lo único observable es que los `error_mensaje` son más claros y que la
transcripción sale más completa, sobre todo en PDF.

Los endpoints de este documento están verificados contra el esquema que genera
`manage.py spectacular`, que el backend expone en `/api/schema/`.
