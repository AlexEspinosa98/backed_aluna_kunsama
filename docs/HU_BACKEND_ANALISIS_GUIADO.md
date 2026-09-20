# HU-57 — Análisis guiado: método, enfoque, contexto e instrucciones

Brief para el backend. El frontend ya tiene implementado el flujo completo y hoy manda todos los
campos descritos aquí; el backend los ignora hasta que se implementen. Nada de esto rompe lo
actual: son campos y endpoints nuevos sobre los recursos que ya existen.

## Qué cambió en el panel

La pestaña **Analítica** de una jornada dejó de tener tres pestañas (reportes jerárquicos,
análisis integral, jornada completa). Ahora hay **una sola lista** con todos los análisis, vengan
del pipeline local (`Reporte`) o de la lectura con IA (`AnalisisMomentoIA`, `AnalisisJornadaIA`),
y un **asistente por pasos** para lanzar uno nuevo:

1. **Método**: `bertopic` (pipeline local) u `openai` (lectura integral con modelo de razonamiento).
2. **Enfoque**: `cualitativo`, `cuantitativo` o `mixto` (recomendado por defecto).
3. **Contexto**: texto libre, precargado con `Jornada.descripcion`, editable.
4. **Instrucciones**: texto libre (tono, público, cantidad de gráficos, frases textuales, idioma…).
5. **Alcance**: toda la jornada, o uno o varios momentos.
6. Si es por momento: **contexto e instrucciones propios de cada momento**, ambos opcionales.
7. **Resumen** con sugerencias de la IA para afinar, y **Iniciar análisis**.

La analítica se organiza **por jornada** y una jornada acumula **varios análisis**, de ambos
alcances, y así seguirá siendo. Al entrar a Analítica de la jornada elegida se listan todos, en dos
secciones: **Análisis integral** (los que abarcan la jornada entera) y **Análisis por momentos**
(cada momento con sus propias tarjetas, tituladas con el **título del momento**). Por eso todo
listado del backend debe permitir filtrar por jornada y traer el título y el orden del momento
resueltos (ver sección 4).

El frontend decide el endpoint según método y alcance; **el backend decide el prompt de sistema**
según método, alcance y enfoque, y le suma contexto e instrucciones.

| Método | Alcance | Endpoint que llama el frontend | Peticiones |
|---|---|---|---|
| `bertopic` | jornada | `POST /api/admin/reportes/` con `momentos: []` | 1 |
| `bertopic` | momentos | `POST /api/admin/reportes/` con `momentos: [<id>]` | 1 por momento |
| `openai` | jornada | `POST /api/admin/analisis-jornada-ia/` | 1 |
| `openai` | momentos | `POST /api/admin/analisis-momento-ia/` | 1 por momento |

---

## 1. Campos nuevos en las tres solicitudes de análisis

Se agregan a `POST /api/admin/reportes/`, `POST /api/admin/analisis-jornada-ia/` y
`POST /api/admin/analisis-momento-ia/`, y se **persisten y devuelven** en `GET` (listado y
detalle) de los tres modelos.

| Campo | Tipo | Default | Notas |
|---|---|---|---|
| `enfoque` | `"cualitativo" \| "cuantitativo" \| "mixto"` | `"mixto"` | Otro valor → `400` con la clave `enfoque`. |
| `contexto` | texto, hasta 4000 caracteres | `""` | Contexto general que escribió el usuario. Puede coincidir con `Jornada.descripcion` o no. |
| `instrucciones` | texto, hasta 4000 caracteres | `""` | Instrucciones adicionales del usuario. |
| `contexto_momento` | texto, hasta 4000 caracteres | `""` | Sólo en alcance por momento (`analisis-momento-ia` y `reportes` con un momento). |
| `instrucciones_momento` | texto, hasta 4000 caracteres | `""` | Ídem. |

Ejemplo de lo que manda hoy el frontend para un momento con IA:

```json
POST /api/admin/analisis-momento-ia/
{
  "momento": 61,
  "enfoque": "mixto",
  "contexto": "Estamos en un evento de participación con docentes y directivos…",
  "instrucciones": "Tono institucional. Máximo cinco gráficos. Incluye frases textuales.",
  "contexto_momento": "Este momento se trabajó en mesas de ocho personas.",
  "instrucciones_momento": "Destaca las tensiones entre programas."
}
```

Y para toda la jornada con el pipeline local:

```json
POST /api/admin/reportes/
{
  "jornada": 14,
  "momentos": [],
  "plantilla": null,
  "enfoque": "cuantitativo",
  "contexto": "…",
  "instrucciones": "…"
}
```

Criterios:

- Los campos de texto se guardan **tal cual** (sin normalizar) para poder mostrarlos en el detalle
  ("con qué se generó") y reutilizarlos como punto de partida.
- `plantilla` sigue aceptándose en `reportes`; `null` significa "la predeterminada del método".
- Los `GET` de listado y detalle devuelven además `metodo` (`"bertopic"` para `Reporte`,
  `"openai"` para los `Analisis*IA`) para que el frontend no lo deduzca del endpoint.

---

## 2. Composición del prompt de sistema

El backend arma el prompt final en este orden, para los tres métodos:

1. **Plantilla base** por método y alcance (`plantillas-analisis`, la predeterminada de su `tipo`).
2. **Bloque de enfoque**, fijo por valor:
   - `cualitativo`: priorizar sentido, matices, tensiones y voces representativas; citas textuales;
     porcentajes sólo si aportan.
   - `cuantitativo`: priorizar frecuencias, porcentajes y comparaciones; texto sólo para explicar
     los datos; gráficos.
   - `mixto`: cifras y lectura interpretativa a la par.
3. **Contexto** de la jornada (`contexto`) y, si aplica, **contexto del momento**
   (`contexto_momento`).
4. **Instrucciones** (`instrucciones` + `instrucciones_momento`), **con precedencia** sobre el
   estilo, la estructura y el contenido de la plantilla base.
5. **Regla de datos**, después de las instrucciones y no negociable: sólo cifras y citas que salgan
   de las respuestas; nunca inventar ni estimar.

Para `bertopic` el enfoque también cambia el pipeline, no sólo el texto:

- `cuantitativo`: más peso a conteos por tema, porcentajes y comparación entre grupos/mesas; el
  modelo local resume brevemente.
- `cualitativo`: más frases representativas por tema y una lectura narrativa; los conteos van al
  final.
- `mixto`: como hoy.

`contexto` e `instrucciones` entran al modelo local en el paso de nombrar temas y redactar el
resumen.

Auditoría: los tres modelos guardan `prompt_usado` con el prompt compuesto (los `Analisis*IA` ya
tienen campo equivalente; `Reporte` lo agrega), igual que hace `InfografiaJornada`.

---

## 3. Sugerencias para afinar — `POST /api/admin/analisis-sugerencias/`

En el paso de resumen, el frontend pide sugerencias con lo que el usuario escribió, y las muestra
como chips que se suman al contexto o a las instrucciones (al estilo de Claude Design). Es parte
del flujo, no una mejora futura.

```json
POST /api/admin/analisis-sugerencias/
{
  "jornada": 14,
  "momentos": [61, 62],
  "metodo": "openai",
  "enfoque": "mixto",
  "contexto": "…",
  "instrucciones": "…"
}
```

Respuesta `200`:

```json
{
  "sugerencias": [
    { "tipo": "contexto", "texto": "Las mesas mezclaron docentes de pregrado y posgrado." },
    { "tipo": "instruccion", "texto": "Compara las respuestas de directivos con las de docentes." },
    { "tipo": "instruccion", "texto": "Señala qué preguntas tuvieron menos respuestas." }
  ]
}
```

Criterios:

- Un modelo pequeño y rápido: **respuesta en menos de 10 segundos**; si el proveedor tarda más,
  devolver `200` con lista vacía en vez de error. El frontend nunca bloquea por esto.
- Entre **0 y 6** sugerencias, cortas (una frase), en español, sin repetir lo que el usuario ya
  escribió.
- La IA recibe el contexto de la jornada, los títulos y contextos de los momentos, el número de
  respuestas por momento y los tipos de pregunta; **no recibe respuestas** de participantes. Las
  sugerencias son sobre cómo enmarcar el análisis, no sobre resultados.
- `tipo` sólo admite `contexto` o `instruccion`.
- `momentos` vacío significa alcance de toda la jornada; con ids, el alcance son esos momentos.
- `metodo` admite `bertopic` u `openai`, igual que el resto del flujo.
- Mismo scoping por dependencia que el resto (`403` en jornada ajena). `404` mientras no exista:
  el frontend oculta la sección.

---

## 4. Lista unificada — `GET /api/admin/analisis/`

Hoy el frontend arma la lista con tres consultas (`reportes` del store, `analisis-jornada-ia?jornada=`
y `analisis-momento-ia` completo filtrado en el cliente) y las repite cada 8 segundos mientras haya
algo en curso. Un endpoint único es mejor para el sistema: una consulta, un orden y una forma.

```
GET /api/admin/analisis/?jornada=<id>
GET /api/admin/analisis/?momento=<id>
```

Cada item:

```json
{
  "tipo": "analisis_momento",
  "id": 8,
  "jornada": 14,
  "momento": 61,
  "momento_titulo": "Diálogos mesas",
  "momento_orden": 2,
  "metodo": "openai",
  "enfoque": "mixto",
  "alcance": "momento",
  "estado": "procesando",
  "error_mensaje": "",
  "creado_en": "2026-09-19T15:20:00Z",
  "completado_en": null
}
```

- `tipo`: `reporte` | `analisis_momento` | `analisis_jornada`.
- `alcance`: `jornada` | `momento` | `momentos` (reporte con varios momentos).
- `momento`, `momento_titulo` y `momento_orden` en `null` cuando el alcance es la jornada. Con
  esto el frontend titula y agrupa sin cruzar con otros recursos.
- Orden: `creado_en` descendente. Sin paginación mientras no supere unos cientos por jornada.
- Sólo lectura: abrir, borrar y consultar el detalle siguen en los endpoints propios de cada tipo.

Mientras no exista, el frontend sigue con las tres consultas.

---

## 5. Validaciones inmediatas

- **Sin respuestas en el alcance** → `400` al crear, con mensaje explícito ("El momento X no tiene
  respuestas todavía"), no un registro que termina en `error`.
- **Ya hay uno en curso** para el mismo alcance y método → `409` (los `Analisis*IA` ya lo hacen;
  `reportes` debe hacerlo igual por jornada+momentos).
- `enfoque` inválido, textos que superan el máximo → `400` con la clave del campo.

---

## 6. Infografías

Ya está resuelto en el backend y el frontend lo usa así; sólo confirmar que se mantiene:

- Alcance `{"momento": <id>}` desde el detalle de un análisis de momento, `{"jornada": <id>}`
  desde uno de jornada y `{"jornada": <id>, "reporte": <id>}` desde el detalle de un reporte del
  pipeline local. `instrucciones` en los tres casos.
- `GET /api/admin/infografias/?jornada=<id>&reporte=<id>` debería filtrar por reporte; hoy el
  frontend filtra en el cliente por `reporte`, así que no bloquea.
- La generación toma como referencia los assets y la guía de marca de la jornada; el frontend los
  muestra y permite cargar más dentro del mismo flujo (`jornada-assets`, ya existente).
- El frontend dejó de usar `POST /api/admin/reportes/{id}/generar-infografia/`.

---

## 7. Plantillas de sistema

`plantillas-analisis` se mantiene como está (tipo `local`, `gpt_momento`, `gpt_jornada`,
predeterminada por tipo). El asistente no elige plantilla: usa la predeterminada del método y
alcance, y le suma enfoque, contexto e instrucciones. Si más adelante conviene una plantilla por
enfoque, se agrega `enfoque` a la plantilla; no hace falta ahora.

---

## 8. Resumen del contrato

| Endpoint | Cambio |
|---|---|
| `POST /api/admin/reportes/` | Acepta `enfoque`, `contexto`, `instrucciones`, `contexto_momento`, `instrucciones_momento`. `409` si hay uno en curso con el mismo alcance. Guarda `prompt_usado`. |
| `POST /api/admin/analisis-jornada-ia/` | Acepta `enfoque`, `contexto`, `instrucciones`. |
| `POST /api/admin/analisis-momento-ia/` | Acepta `enfoque`, `contexto`, `instrucciones`, `contexto_momento`, `instrucciones_momento`. |
| `GET` de los tres (lista y detalle) | Devuelven los campos anteriores tal cual, más `metodo`. |
| `POST /api/admin/analisis-sugerencias/` | Nuevo. Sugerencias de contexto e instrucciones, rápido, 0–6 items. |
| `GET /api/admin/analisis/` | Nuevo. Lista unificada por `jornada` o `momento`. |
| `POST /api/admin/infografias/` | Sin cambios; confirmar filtro `?reporte=`. |

---

## 9. Checklist

- [ ] `enfoque`, `contexto`, `instrucciones` en los tres `POST`, persistidos y devueltos en `GET`.
- [ ] `contexto_momento` e `instrucciones_momento` en los `POST` por momento.
- [ ] Prompt de sistema compuesto según método, alcance y enfoque, con las instrucciones del
      usuario por encima de la plantilla y la regla de datos al final.
- [ ] `enfoque` cambia también el pipeline BERTopic (peso de conteos vs. frases).
- [ ] `prompt_usado` guardado en `Reporte`, como ya lo tienen los `Analisis*IA`.
- [ ] `400` inmediato sin respuestas en el alcance; `409` con uno en curso, también en `reportes`.
- [ ] `POST /api/admin/analisis-sugerencias/` con la forma y los límites de la sección 3.
- [ ] `GET /api/admin/analisis/` unificado con la forma de la sección 4, con `momento_titulo` y
      `momento_orden` resueltos.
- [ ] `metodo` en las respuestas de los tres modelos.
- [ ] `GET /api/admin/infografias/?reporte=` filtra por reporte.
