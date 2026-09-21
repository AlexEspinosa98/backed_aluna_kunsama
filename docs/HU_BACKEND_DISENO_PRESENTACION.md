# HU · Diseño de presentación con IA a partir de los assets de la jornada

**Módulo:** Kunsamu (backend Django) · **Consumidor:** frontend Aluna (Next.js)
**Contrato de salida:** `kunsamu.presentacion/v1` · **Fecha:** 2026-09-20

## 0. Resumen en tres líneas

El frontend proyecta los resultados de un análisis v2 como presentación por diapositivas. Hoy la
diagramación (colores, tipografía, papel de cada asset, plantilla de cada diapositiva) la decide un
modelo de OpenAI con visión llamado desde el propio frontend. Esta HU mueve esa llamada al backend,
que ya tiene los assets a mano, y la vuelve **opcional y bajo demanda**: nunca se genera sola, sólo
cuando el usuario pulsa «Diagramar con IA», y el resultado se guarda para no volver a gastar tokens.

## 1. Comportamiento esperado

1. Al abrir la presentación de un análisis, el frontend consulta si ya existe un diseño guardado
   (`GET`). Si existe, lo usa. Si no, presenta con el diseño institucional y muestra el botón
   «Diagramar con IA». **Ese `GET` nunca genera nada.**
2. Cuando el usuario pulsa el botón, el frontend hace `POST` con el análisis y la secuencia de
   diapositivas. El backend carga los assets de la jornada, llama al modelo, sanea la respuesta, la
   guarda y la devuelve.
3. Si ya existía un diseño, el `POST` lo reemplaza (es el «Rediseñar» del usuario).
4. Si la jornada no tiene assets con imagen ni guía de marca escrita, el backend responde `422`
   sin llamar al modelo: no hay nada que diagramar y el frontend sigue con el diseño institucional.
5. `DELETE` descarta el diseño guardado (vuelve al institucional).

Un diseño pertenece a **un análisis concreto** (reporte, análisis por momento o análisis de
jornada), igual que las infografías (HU-73): exactamente uno de `reporte | analisis_momento |
analisis_jornada`.

## 2. Endpoints

Todos bajo el prefijo actual de la API de administración y con el mismo token de admin que el
resto de endpoints de análisis.

| Método | Ruta | Uso |
|---|---|---|
| `GET` | `/presentacion-diseno/?reporte=ID` (o `?analisis_momento=ID`, o `?analisis_jornada=ID`) | Devuelve el diseño guardado del análisis. `200` con el objeto, `404` si no hay. No genera. |
| `POST` | `/presentacion-diseno/` | Genera (o regenera) el diseño con el modelo y lo guarda. Síncrono: tarda entre 7 y 20 segundos. |
| `DELETE` | `/presentacion-diseno/{id}/` | Elimina el diseño guardado. `204`. |

### 2.1 Cuerpo del `POST`

```json
{
  "analisis_jornada": 12,
  "diapositivas": [
    { "id": "portada", "tipo": "portada", "titulo": "Portada", "tiene_visual": false, "tipo_visual": null, "tiene_citas": false, "tiene_metricas": false, "naturaleza": null },
    { "id": "cobertura", "tipo": "cobertura", "titulo": "Alcance y cobertura", "tiene_visual": false, "tipo_visual": null, "tiene_citas": false, "tiene_metricas": false, "naturaleza": null },
    { "id": "i1-resumen-0", "tipo": "resumen", "titulo": "Horarios del taller · resumen 1/1", "tiene_visual": false, "tipo_visual": null, "tiene_citas": false, "tiene_metricas": false, "naturaleza": null },
    { "id": "i1-h1-v1", "tipo": "hallazgo", "titulo": "Una franja alternativa atendería las restricciones reportadas", "tiene_visual": true, "tipo_visual": "barras", "tiene_citas": true, "tiene_metricas": true, "naturaleza": "mixto" },
    { "id": "i1-recomendaciones-0", "tipo": "recomendaciones", "titulo": "Recomendaciones · Horarios del taller", "tiene_visual": false, "tipo_visual": null, "tiene_citas": false, "tiene_metricas": false, "naturaleza": null },
    { "id": "limitaciones", "tipo": "limitaciones", "titulo": "Limitaciones del análisis", "tiene_visual": false, "tipo_visual": null, "tiene_citas": false, "tiene_metricas": false, "naturaleza": null },
    { "id": "cierre", "tipo": "cierre", "titulo": "Cierre", "tiene_visual": false, "tipo_visual": null, "tiene_citas": false, "tiene_metricas": false, "naturaleza": null }
  ]
}
```

- Exactamente una de `reporte`, `analisis_momento`, `analisis_jornada`. Faltan las tres o hay más
  de una → `400`. El id no existe → `404`.
- El análisis debe tener resultado en formato `kunsamu.analisis/v2` (campo `resultado` con
  `version: "kunsamu.analisis/v2"`). Si no → `409 {"detail": "El análisis no está en formato v2"}`.
- `diapositivas`: la secuencia que el frontend va a renderizar. **La manda el frontend** porque él
  la deriva del contenido (una diapositiva por visualización, resúmenes largos en partes, etc.); el
  backend no la reconstruye ni la altera, sólo la guarda y se la pasa al modelo. `tipo` es uno de
  `portada | cobertura | resumen | hallazgo | recomendaciones | limitaciones | cierre`. Lista vacía
  o con un `tipo` desconocido → `400`.

### 2.2 Respuesta del `POST` (`201`) y del `GET` (`200`)

```json
{
  "id": 7,
  "analisis_jornada": 12,
  "reporte": null,
  "analisis_momento": null,
  "version": "kunsamu.presentacion/v1",
  "modelo": "gpt-5.1",
  "correcciones": ["sin ilustración para resumen_ilustracion; se usa resumen"],
  "diseno": { "…": "objeto del contrato, sección 4" },
  "diapositivas": [ "…la secuencia recibida en el POST, tal cual…" ],
  "assets": [ 3, 4, 5, 9 ],
  "creado": "2026-09-20T18:40:12Z",
  "actualizado": "2026-09-20T18:40:12Z"
}
```

`assets` son los ids de `JornadaAsset` que se enviaron al modelo. Sirven al frontend para saber
si el diseño quedó viejo (si la jornada cambió de assets, el frontend ofrece «Rediseñar»).

### 2.3 Errores

| Código | Cuándo | Cuerpo |
|---|---|---|
| `400` | Fuente ausente o duplicada; `diapositivas` inválidas | `{"detail": "…"}` |
| `401` | Sin token de admin | como el resto de la API |
| `404` | Análisis inexistente (`POST`) o sin diseño guardado (`GET`) | `{"detail": "…"}` |
| `409` | El análisis no es v2 | `{"detail": "El análisis no está en formato v2"}` |
| `422` | La jornada no tiene assets con imagen ni guía escrita | `{"detail": "La jornada no tiene assets ni guía de marca"}` |
| `502` | El modelo falló, no devolvió JSON o la respuesta no tiene la forma base | `{"detail": "<mensaje del proveedor o motivo>"}` |
| `503` | Falta `OPENAI_API_KEY` | `{"detail": "Falta OPENAI_API_KEY"}` |

## 3. Modelo de datos

```python
class PresentacionDiseno(models.Model):
    reporte = models.OneToOneField("Reporte", null=True, blank=True, on_delete=models.CASCADE, related_name="presentacion_diseno")
    analisis_momento = models.OneToOneField("AnalisisMomentoIA", null=True, blank=True, on_delete=models.CASCADE, related_name="presentacion_diseno")
    analisis_jornada = models.OneToOneField("AnalisisJornadaIA", null=True, blank=True, on_delete=models.CASCADE, related_name="presentacion_diseno")
    version = models.CharField(max_length=40, default="kunsamu.presentacion/v1")
    modelo = models.CharField(max_length=60)
    diapositivas = models.JSONField()      # secuencia recibida en el POST
    diseno = models.JSONField()            # contrato saneado (sección 4)
    correcciones = models.JSONField(default=list)
    assets = models.JSONField(default=list)  # ids de JornadaAsset enviados al modelo
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)
```

Regla de integridad (validación en `clean()` o constraint): exactamente una FK no nula. Usen los
nombres reales de sus modelos de análisis; los de arriba son orientativos. Un `POST` sobre un
análisis que ya tiene diseño **actualiza** esa fila (no crea otra).

## 4. Contrato `kunsamu.presentacion/v1` (lo que se guarda y se devuelve en `diseno`)

```json
{
  "version": "kunsamu.presentacion/v1",
  "tema": {
    "estilo": "institucional",
    "colores": {
      "primario": "#14384a", "secundario": "#2fc2d6", "acento": "#c08a28",
      "fondo": "#f7f0e3", "superficie": "#ffffff", "texto": "#14384a", "texto_suave": "#4a6a7a"
    },
    "tipografia": { "titulos": "serif", "cuerpo": "sans" },
    "fondo": { "tipo": "plano", "colores": ["#f7f0e3"] },
    "justificacion": "Paleta de la guía de marca; fondo marfil cercano al de la ilustración para continuidad."
  },
  "logo": { "asset_id": "3", "posicion": "superior_derecha" },
  "assets": [
    { "id": "3", "rol": "logo", "fondo_recomendado": null, "notas": "Wordmark azul sobre transparente." },
    { "id": "4", "rol": "ilustracion", "fondo_recomendado": null, "notas": "Medusa plana, fondo transparente." },
    { "id": "5", "rol": "ilustracion", "fondo_recomendado": "#f7f0e3", "notas": "Olas sobre fondo marfil opaco." },
    { "id": "9", "rol": "no_usar", "fondo_recomendado": null, "notas": "Guía de marca escrita." }
  ],
  "diapositivas": [
    { "id": "portada", "plantilla": "portada_ilustracion", "acento": "#c08a28", "asset_id": "4", "lado_imagen": "derecha", "mostrar_logo": true },
    { "id": "i1-resumen-0", "plantilla": "resumen_ilustracion", "acento": null, "asset_id": "5", "lado_imagen": "izquierda", "mostrar_logo": true },
    { "id": "i1-h1-v1", "plantilla": "hallazgo_visual", "acento": "#2fc2d6", "asset_id": null, "lado_imagen": "derecha", "mostrar_logo": true },
    { "id": "cierre", "plantilla": "cierre_ilustracion", "acento": null, "asset_id": "4", "lado_imagen": "izquierda", "mostrar_logo": true }
  ]
}
```

### 4.1 Semántica

- **`asset_id`** es siempre el id de `JornadaAsset` **como texto** (`"3"`), en `logo`, en `assets`
  y en `diapositivas`.
- **Papeles de asset (`rol`)**
  - `logo`: va entero, pequeño, en la esquina `logo.posicion` de todas las diapositivas; grande
    junto al título en `portada_color`. Sin fondo, sin marco, sin recorte.
  - `logo_secundario`: reservado; el frontend hoy no lo pinta.
  - `ilustracion`: figura, ilustración o foto de identidad. Va **entera**, al lado del texto
    (`lado_imagen`), sólo en `portada_ilustracion`, `resumen_ilustracion` y `cierre_ilustracion`.
    Nunca recortada, nunca a sangre, nunca dentro de un marco ni con velo.
  - `no_usar`: no se muestra.
- **`fondo_recomendado`**: color del fondo propio de la imagen cuando es opaco (crema, blanco, un
  plano); la diapositiva lo adopta para que la imagen se funda sin bordes. `null` si es
  transparente. El frontend además mide ese fondo en los bordes reales de la imagen y lo medido
  manda; el valor del modelo es una sugerencia.
- **Plantillas admisibles por tipo de diapositiva**

  | `tipo` | Plantillas |
  |---|---|
  | `portada` | `portada_ilustracion` (requiere ilustración), `portada_color` |
  | `cobertura` | `cobertura` |
  | `resumen` | `resumen`, `resumen_ilustracion` (requiere ilustración) |
  | `hallazgo` | `hallazgo_visual`, `hallazgo_visual_invertido` (requieren `tiene_visual`), `hallazgo_cita` (requiere `tiene_citas`), `hallazgo_texto` |
  | `recomendaciones` | `recomendaciones` |
  | `limitaciones` | `limitaciones` |
  | `cierre` | `cierre_ilustracion` (requiere ilustración), `cierre_color` |

- `acento` es opcional por diapositiva (`null` usa el del tema). `mostrar_logo` se ignora en
  `portada_color` (allí el logo va grande en el cuerpo).

## 5. Lo que el backend construye para el modelo

### 5.1 Assets

Cargar los `JornadaAsset` de la jornada del análisis, del más reciente al más antiguo. Para cada
uno: `id` (texto), `tipo` (`asset` | `system_design`), `nombre` (nombre de archivo o título),
`texto` (la guía de marca escrita, sólo en `system_design`; `null` en los demás).

Imágenes adjuntas: como máximo **6**, cada una ≤ **4 MB**, sólo `image/png`, `image/jpeg`,
`image/webp`, `image/gif`. Se descartan PDF y SVG (se mencionan por nombre pero no se adjuntan).
Cada imagen va como `data:<mime>;base64,…` con `detail: "low"`. Si ningún asset tiene imagen
adjuntable ni `texto`, responder `422` sin llamar al modelo.

### 5.2 Contexto del análisis

Del análisis y su jornada: `jornada.nombre`, `jornada.descripcion` (o `""`), y del `resultado`
v2: `titulo` (el título del análisis en la lista unificada), `estado`, `alcance.modo`, el
`resumen` del primer informe, número total de hallazgos y de recomendaciones.

### 5.3 Mensajes

`messages`:

1. `system`: el prompt de la sección 6, literal.
2. `user`, contenido multipart:
   - Un bloque `text` con este JSON (indentado, sin más texto):

     ```json
     {
       "jornada": { "nombre": "…", "descripcion": "…" },
       "analisis": { "titulo": "…", "estado": "completo", "modo": "integral", "resumen": "…", "hallazgos": 4, "recomendaciones": 3 },
       "diapositivas": [ "…la lista recibida en el POST…" ],
       "assets": [
         { "id": "3", "tipo": "asset", "nombre": "logo.png", "texto": null, "imagen_adjunta": true },
         { "id": "9", "tipo": "system_design", "nombre": "Guía de marca", "texto": "Paleta #14384A…", "imagen_adjunta": false }
       ]
     }
     ```

   - Por cada imagen adjunta, un bloque `text` con `Asset <id>:` seguido de un bloque `image_url`
     con la `data:` URL y `detail: "low"`.

### 5.4 Llamada

`POST https://api.openai.com/v1/chat/completions` con:

```json
{
  "model": "<KUNSAMU_DESIGN_MODEL o gpt-5.1>",
  "messages": [ "…" ],
  "response_format": {
    "type": "json_schema",
    "json_schema": { "name": "kunsamu_presentacion_v1", "strict": true, "schema": { "…sección 7…" } }
  },
  "max_completion_tokens": 6000
}
```

- Orden de modelos: `KUNSAMU_DESIGN_MODEL` si está definido, luego `gpt-5.1`, luego `gpt-4.1`. Si
  el proveedor responde `4xx` cuyo mensaje menciona `model` (modelo no disponible para la clave),
  probar el siguiente; cualquier otro error corta y devuelve `502`.
- Timeout de 60 s hacia el proveedor. Guardar en `modelo` el que respondió.
- Verificar `choices[0].finish_reason == "stop"` y que no haya `refusal`; parsear el `content` como
  JSON. Si falla, `502`.

## 6. System prompt (literal)

```text
Eres el director de arte de Kunsamu, la plataforma de análisis participativo de Aluna I.A. (Universidad del Magdalena). Diagramas la presentación con la que un equipo proyecta ante directivos y comunidades los resultados de una jornada. Recibes: el contexto de la jornada, un resumen del análisis, la lista de diapositivas ya definida (id, tipo y contenido disponible) y los assets visuales de la jornada, cada uno como imagen adjunta precedida de su id, más la guía de marca escrita si existe. Devuelves únicamente un JSON conforme al esquema kunsamu.presentacion/v1.

## Cómo se tratan los assets (regla central)

Los assets acompañan la identidad visual de la jornada. Se muestran siempre completos: sin recortar, sin estirar, sin marco, sin tarjeta, sin sombra, sin velo de color y nunca como fondo a sangre. El frontend los coloca enteros, con aire, al lado del texto o en una esquina; tú decides cuál va dónde. Hay tres papeles:
- "logo" (el principal) o "logo_secundario": imagotipo, wordmark, escudo, lettering. Va pequeño en una esquina de todas las diapositivas y, en la portada sin ilustración, grande junto al título.
- "ilustracion": una figura, ilustración, fotografía o pieza gráfica que acompaña la identidad (un animal, un objeto, un paisaje, un patrón con motivo claro). Va entera al lado del texto en portada, resumen y cierre, ocupando cerca de la mitad de la diapositiva. Si la imagen tiene fondo opaco (crema, blanco, un color plano), indica ese color exacto en "fondo_recomendado": la diapositiva lo adopta y la imagen se funde sin bordes; si el fondo es transparente, "fondo_recomendado" es null.
- "no_usar": lo que no aporta (borroso, duplicado, captura de pantalla, documento, la guía de marca en imagen, un asset con texto pequeño incrustado). Es válido no usar la mayoría; usa sólo lo que mejora la presentación.

## Qué decides

1. Tema: estilo, siete colores, tipografía y fondo. Los colores salen de la guía de marca si trae códigos; si no, de los colores reales de los assets (logo primero, ilustraciones después); si no hay nada, elige una paleta sobria institucional (azules profundos con un acento cálido). Si las ilustraciones tienen fondo opaco, elige como "fondo" del tema ese mismo color o uno muy cercano, para que toda la presentación se sienta continua. Contraste mínimo 4.5:1 entre texto y fondo, y entre texto y superficie. El fondo y la superficie siempre claros: encima van gráficas con sus propios colores de datos. Tipografía: serif en títulos para lo editorial e institucional; sans para jornadas tecnológicas, juveniles o dinámicas. Fondo: halos para lo institucional, plano para lo sobrio (y siempre que haya ilustraciones con fondo opaco), gradiente sólo si la marca es vibrante.

2. Assets, uno por uno, mirando la imagen: rol, fondo recomendado y una nota con lo que viste y por qué le diste ese papel.

3. Logo global: el asset con rol "logo" y su esquina. Sin logo, asset_id null.

4. Diapositivas: para cada id de la lista, una plantilla admisible por su tipo, un acento opcional, la ilustración que la acompaña y el lado en que va.
- portada: "portada_ilustracion" si hay una ilustración; si no, "portada_color". Elige "lado_imagen" según la composición de la figura (una figura que cuelga o mira hacia la izquierda suele ir a la derecha del título).
- resumen: "resumen_ilustracion" con una segunda ilustración distinta de la de portada; con una sola ilustración, "resumen" sin imagen para no repetirla en diapositivas seguidas.
- hallazgo con visualización: alterna "hallazgo_visual" y "hallazgo_visual_invertido" para que no se vean todas iguales. Sin visualización pero con citas: "hallazgo_cita". Sin visualización ni citas: "hallazgo_texto". Un hallazgo nunca lleva ilustración ni logo dentro del contenido.
- cobertura, recomendaciones y limitaciones tienen una sola plantilla.
- cierre: "cierre_ilustracion" (puede repetir la de portada, invirtiendo el lado) o "cierre_color".
- acento: puedes rotar entre primario, secundario y acento del tema para distinguir hallazgos; nunca un color que no esté en el tema.
- mostrar_logo: true en todas si hay logo; los fondos son siempre claros y el logo se lee bien. El frontend ya lo omite en "portada_color", donde el logo va grande junto al título.

## Reglas que no se negocian
- Usa sólo los ids de assets y de diapositivas recibidos; no inventes ni omitas diapositivas.
- No escribas texto para las diapositivas: el contenido ya existe. Sólo diseñas.
- Sobrio antes que llamativo: es un informe de decisiones, no publicidad. Variedad con criterio, no caos.
- Explica en "justificacion" (una o dos frases) de dónde salieron los colores y por qué esa tipografía.
- Responde sólo con el JSON.
```

## 7. JSON Schema para la salida estructurada estricta

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["version", "tema", "logo", "assets", "diapositivas"],
  "properties": {
    "version": { "type": "string", "enum": ["kunsamu.presentacion/v1"] },
    "tema": {
      "type": "object",
      "additionalProperties": false,
      "required": ["estilo", "colores", "tipografia", "fondo", "justificacion"],
      "properties": {
        "estilo": { "type": "string", "enum": ["institucional", "editorial", "sobrio", "vibrante"] },
        "colores": {
          "type": "object",
          "additionalProperties": false,
          "required": ["primario", "secundario", "acento", "fondo", "superficie", "texto", "texto_suave"],
          "properties": {
            "primario": { "type": "string", "pattern": "^#[0-9a-fA-F]{6}$" },
            "secundario": { "type": "string", "pattern": "^#[0-9a-fA-F]{6}$" },
            "acento": { "type": "string", "pattern": "^#[0-9a-fA-F]{6}$" },
            "fondo": { "type": "string", "pattern": "^#[0-9a-fA-F]{6}$" },
            "superficie": { "type": "string", "pattern": "^#[0-9a-fA-F]{6}$" },
            "texto": { "type": "string", "pattern": "^#[0-9a-fA-F]{6}$" },
            "texto_suave": { "type": "string", "pattern": "^#[0-9a-fA-F]{6}$" }
          }
        },
        "tipografia": {
          "type": "object",
          "additionalProperties": false,
          "required": ["titulos", "cuerpo"],
          "properties": {
            "titulos": { "type": "string", "enum": ["serif", "sans"] },
            "cuerpo": { "type": "string", "enum": ["sans", "serif"] }
          }
        },
        "fondo": {
          "type": "object",
          "additionalProperties": false,
          "required": ["tipo", "colores"],
          "properties": {
            "tipo": { "type": "string", "enum": ["halos", "plano", "gradiente"] },
            "colores": { "type": "array", "items": { "type": "string", "pattern": "^#[0-9a-fA-F]{6}$" } }
          }
        },
        "justificacion": { "type": "string" }
      }
    },
    "logo": {
      "type": "object",
      "additionalProperties": false,
      "required": ["asset_id", "posicion"],
      "properties": {
        "asset_id": { "type": ["string", "null"] },
        "posicion": { "type": "string", "enum": ["superior_izquierda", "superior_derecha", "inferior_izquierda", "inferior_derecha"] }
      }
    },
    "assets": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "rol", "fondo_recomendado", "notas"],
        "properties": {
          "id": { "type": "string" },
          "rol": { "type": "string", "enum": ["logo", "logo_secundario", "ilustracion", "no_usar"] },
          "fondo_recomendado": { "type": ["string", "null"], "pattern": "^#[0-9a-fA-F]{6}$" },
          "notas": { "type": "string" }
        }
      }
    },
    "diapositivas": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "plantilla", "acento", "asset_id", "lado_imagen", "mostrar_logo"],
        "properties": {
          "id": { "type": "string" },
          "plantilla": {
            "type": "string",
            "enum": [
              "portada_ilustracion", "portada_color", "cobertura", "resumen", "resumen_ilustracion",
              "hallazgo_visual", "hallazgo_visual_invertido", "hallazgo_texto", "hallazgo_cita",
              "recomendaciones", "limitaciones", "cierre_ilustracion", "cierre_color"
            ]
          },
          "acento": { "type": ["string", "null"], "pattern": "^#[0-9a-fA-F]{6}$" },
          "asset_id": { "type": ["string", "null"] },
          "lado_imagen": { "type": "string", "enum": ["izquierda", "derecha"] },
          "mostrar_logo": { "type": "boolean" }
        }
      }
    }
  }
}
```

Este esquema ya está probado con `strict: true` en `gpt-5.1` (incluido `pattern` sobre tipos
nullable).

## 8. Saneamiento antes de guardar

El esquema garantiza la forma; el saneamiento garantiza el sentido. **Corrige en vez de
rechazar** y acumula cada corrección como frase corta en `correcciones`. Sólo se responde `502` si
falta la forma base (`version` distinta, `tema`/`logo` no objetos, `assets`/`diapositivas` no
listas).

Diseño institucional de respaldo (para rellenar lo inválido):
`primario #033659`, `secundario #0f3c5f`, `acento #2fc2d6`, `fondo #fbfcfd`, `superficie #ffffff`,
`texto #0f3c5f`, `texto_suave #64748b`, tipografía `serif`/`sans`, fondo `halos`.

Luminancia relativa (WCAG) sobre sRGB linealizado; «claro» = luminancia ≥ 0.5.

1. **Tema**
   - Cada color no hex válido → el institucional (`color X inválido; se usa el institucional`).
   - `fondo` con luminancia < 0.5 → `fondo` y `superficie` institucionales (`el fondo era oscuro;
     se aclara para mantener legibilidad de gráficas`).
   - Si el fondo es claro y `texto` tiene luminancia > 0.35 → `texto` institucional (`texto poco
     legible sobre el fondo; se oscurece`).
   - `estilo`, `tipografia.titulos`, `tipografia.cuerpo`, `fondo.tipo` fuera del enum → valor por
     defecto (`institucional`, `serif`, `sans`, `halos`).
   - `fondo.colores`: sólo hex válidos, máximo 2; si queda vacío, `[acento, secundario]`.
2. **Assets**
   - Entradas con `id` que no sea un asset de la jornada → descartadas (`asset desconocido
     descartado`). Duplicados → se conserva la primera.
   - Assets de la jornada que el modelo no mencionó → se añaden con `rol: "no_usar"`,
     `fondo_recomendado: null`, `notas: ""`.
   - `rol` fuera del enum → `no_usar`.
   - `fondo_recomendado` con luminancia < 0.5 → `null` (`fondo recomendado oscuro para <id>; se
     ignora`).
3. **Logo**
   - `logo.asset_id` que no exista o cuyo `rol` no sea `logo` ni `logo_secundario` → `null` (`el
     asset elegido como logo no tiene rol de logo; se omite`). Si queda `null` y hay un asset con
     `rol: "logo"`, se toma el primero.
   - `posicion` fuera del enum → `superior_derecha`.
4. **Diapositivas**: se recorre **la secuencia recibida en el POST** (no la del modelo). Para cada
   id, se toma la entrada del modelo con ese id (si no hay, se crea por defecto). Ids que el modelo
   inventó se ignoran.
   - Plantilla por defecto por tipo: `portada → portada_color`, `resumen → resumen`, `hallazgo →
     hallazgo_visual` si `tiene_visual`, si no `hallazgo_cita` si `tiene_citas`, si no
     `hallazgo_texto`; `cierre → cierre_color`; los demás, su único valor.
   - Plantilla que no aplica al `tipo` → la de defecto (`plantilla X no aplica a <tipo>`).
   - `hallazgo` con `hallazgo_visual*` y sin `tiene_visual` → `hallazgo_cita` si `tiene_citas`,
     si no `hallazgo_texto` (`hallazgo <id> sin visualización; plantilla de texto`).
     `hallazgo_cita` sin `tiene_citas` → `hallazgo_texto`.
   - Plantillas `_ilustracion`: el `asset_id` propuesto sólo vale si su `rol` es `ilustracion`; si
     no lo es, se anota (`<asset> no es una ilustración; no se usa en <slide>`) y se toma la
     primera ilustración disponible distinta de la usada en la diapositiva con ilustración
     anterior (o la primera si sólo hay una). Sin ninguna ilustración → variante sin imagen
     (`portada_color`, `resumen`, `cierre_color`) con `asset_id: null` (`sin ilustración para X;
     se usa Y`).
   - Cualquier otra plantilla → `asset_id: null` siempre (los hallazgos nunca llevan imagen).
   - `acento` no hex → `null`. `lado_imagen` fuera del enum → `derecha`. `mostrar_logo` no
     booleano → `true` si hay logo, si no `false`.

## 9. Configuración

| Variable | Uso |
|---|---|
| `OPENAI_API_KEY` | Obligatoria. Sin ella, `503`. |
| `KUNSAMU_DESIGN_MODEL` | Opcional. Modelo a intentar primero; por defecto `gpt-5.1` y luego `gpt-4.1`. |

Costo de referencia medido: entre 7 y 15 segundos por generación con tres imágenes en detalle
bajo. Por eso la generación es sólo bajo demanda y el resultado se guarda.

## 10. Qué hará el frontend cuando esto exista (contexto, no tarea del backend)

- Al abrir la presentación: `GET /presentacion-diseno/?<fuente>=ID` vía su proxy. Con `200`, usa
  el diseño; con `404`, diseño institucional y botón «Diagramar con IA».
- El botón hace el `POST` con la secuencia de diapositivas y muestra «Diagramando…» mientras
  responde. Después ofrece «Rediseñar» (mismo `POST`) y «Quitar diseño» (`DELETE`).
- El frontend seguirá saneando lo que reciba con las mismas reglas y midiendo el fondo real de
  cada ilustración en el navegador; nada de eso lo necesita el backend.
- Se retirará la ruta interna de Next `POST /api/kunsamu/admin/presentacion-diseno` y la clave de
  OpenAI del `.env` del frontend.

## 11. Checklist de aceptación

- [ ] `GET` nunca dispara una generación; con diseño responde `200`, sin diseño `404`.
- [ ] `POST` sobre un análisis v2 con assets genera, sanea, guarda y responde `201` con `diseno`,
      `correcciones`, `modelo`, `assets` y la `diapositivas` recibida.
- [ ] `POST` repetido sobre el mismo análisis reemplaza el diseño (misma fila, `actualizado` nuevo).
- [ ] `POST` con jornada sin imágenes ni guía escrita → `422` y ninguna llamada al proveedor.
- [ ] `POST` sobre análisis histórico (no v2) → `409`.
- [ ] Fuente ausente o doble → `400`; token ausente → `401`; análisis inexistente → `404`.
- [ ] Un logo devuelto por el modelo como `ilustracion` de un hallazgo termina con
      `asset_id: null` y una corrección anotada.
- [ ] Un `fondo` oscuro del modelo se aclara y queda anotado.
- [ ] Todos los `asset_id` en `diseno` son ids de `JornadaAsset` de esa jornada, como texto.
- [ ] La respuesta del `GET` es idéntica en forma a la del `POST`.
- [ ] `DELETE` responde `204` y el `GET` siguiente `404`.
- [ ] Endpoints documentados en el schema público (`/api/schema/`).
