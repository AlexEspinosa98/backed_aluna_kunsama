# System prompts — estado real del código

Referencia viva de los prompts que de verdad corren hoy en producción, por módulo, con el texto
**literal** tal como está en el código (no resumido). Se actualiza cuando el código cambia — si
un texto de acá no coincide con el archivo que cita, el código manda, no este documento.

**Esto NO es lo mismo que `docs/enfoque_analisis/`.** Esa carpeta es un plan de diseño (HU-71 a
HU-76, fechado 2026-09-19) que describe un formato de salida elaborado —`aluna.analisis/v1`, con
`hallazgos[]` que traen `evidencia.grafica`/`evidencia.citas`/`naturaleza`/`fuentes`,
`recomendaciones[]`, láminas de infografía separadas por enfoque, un `catalogo` para la
presentación HTML, etc.— que **nunca se implementó**: el string `aluna.analisis/v1` no existe en
ningún `.py` del repo, y ningún módulo produce ese schema. Lo que sí se construyó, bajo el mismo
esfuerzo, es algo más simple: un mecanismo compartido de **bloques de enfoque** (§1 abajo) que se
**anexa** a los prompts que ya existían antes de HU-71, sin reescribirlos. Si en algún momento se
retoma el plan de `docs/enfoque_analisis/`, este documento es el punto de partida real, no el de
llegada.

Todos los módulos de IA del proyecto usan OpenAI (`OPENAI_MODEL`, default `gpt-4o`; algunos leen
también `OPENAI_REASONING_EFFORT`). El pipeline local (`analitica/analysis.py`) usó hasta
2026-09-20 un LLM local (Qwen2.5-3B-Instruct GGUF vía `llama-cpp-python`) para la parte de
redacción — se migró a OpenAI ese día (ver git log de `analitica/analysis.py`); lo único que sigue
siendo 100% local y determinístico ahí es BERTopic + los embeddings de sentence-transformers
(clustering, no es un LLM).

---

## 1. Mecanismo compartido de enfoque (`analitica/prompt_comun.py`)

Usado por **`analysis.py`** y **`analisis_ia_openai.py`** — ningún otro módulo (infografía,
presentación HTML, transcripciones) lo usa; ver la nota en cada sección de abajo.

`enfoque` es uno de `cualitativo` / `cuantitativo` / `mixto` (`ENFOQUE_DEFAULT = mixto`), un campo
que quien pide el análisis elige. `bloque_enfoque(enfoque)` devuelve uno de estos tres bloques
completos, que se anexa al `system` base de cada agente/llamada:

**`cualitativo`:**
```
=== ENFOQUE: CUALITATIVO ===
Prioriza el sentido, los matices, las tensiones y las voces representativas por encima de los
números — usa citas o frases textuales de las respuestas cuando ayuden a mostrar un patrón.
Menciona porcentajes o conteos en la prosa solo cuando de verdad aporten a la lectura, nunca como
el eje del texto.
SIN GRÁFICAS: en este enfoque NUNCA generes una gráfica. `tipo_grafica` va SIEMPRE en `null` y
`datos` SIEMPRE en `[]` (lista vacía), en TODOS los hallazgos, sin excepción — ni siquiera cuando
una pregunta cerrada tenga una distribución clara y "sería fácil graficarla". La evidencia de este
análisis son las palabras, no los números.
```

**`cuantitativo`** (el bloque "CIFRAS RELEVANTES, NO RELLENO" se agregó el 2026-09-20, en esta
misma sesión, porque el texto generado tenía relleno alrededor de las cifras sin aportar nada
nuevo):
```
=== ENFOQUE: CUANTITATIVO ===
Prioriza las frecuencias, los porcentajes y las comparaciones entre grupos, mesas u opciones — el
texto en prosa es para explicar esos datos, no para reemplazarlos. Apóyate en cifras exactas y en
las gráficas; el detalle narrativo queda en segundo plano.
CIFRAS RELEVANTES, NO RELLENO (importante): cada `descripcion` debe llevar la(s) cifra(s) exacta(s)
que sostienen el hallazgo y una conclusión que se derive DIRECTAMENTE de esa cifra — no prosa
interpretativa alrededor de un dato suelto. Prioriza densidad sobre extensión: 2 a 3 frases con una
cifra real y su lectura valen más que un párrafo largo que solo rodea el número sin decir nada
nuevo. Nunca repitas la misma cifra dos veces con otras palabras, nunca describas el método
(BERTopic, clasificación, etc.), y nunca agregues contexto genérico que no cambie con el dato — si
dos hallazgos podrían intercambiar su párrafo de conclusión sin que se note, ese párrafo no está
anclado a la cifra y hay que reescribirlo.
GRÁFICA POR HALLAZGO (obligatorio): casi ningún hallazgo debería quedar sin `datos` graficables —
incluso uno que nazca de respuestas de texto se puede cuantificar: extrae las palabras clave o
categorías temáticas que mejor resuman el patrón y CUENTA cuántas respuestas reales tocan cada una.
Deja `datos` vacío solo en el caso raro de un hallazgo puramente contextual sin ningún conteo
posible detrás.
```

**`mixto`** (default):
```
=== ENFOQUE: MIXTO ===
Da el mismo peso a las cifras y a la lectura interpretativa: cada hallazgo debe traer su dato
exacto Y la explicación de qué revela, sin que ninguno de los dos domine el texto.
GRÁFICA POR HALLAZGO (obligatorio): casi ningún hallazgo debería quedar sin `datos` graficables —
incluso uno que nazca de respuestas de texto se puede cuantificar: extrae las palabras clave o
categorías temáticas que mejor resuman el patrón y CUENTA cuántas respuestas reales tocan cada una.
Deja `datos` vacío solo en el caso raro de un hallazgo puramente contextual sin ningún conteo
posible detrás.
```

No existen bloques separados de "reglas de evidencia gráfica" ni de "citas obligatorias" como
entidades propias — eso es parte del plan no construido. El único refuerzo de código real para
`cualitativo` es que `analysis.py` fuerza `tipo_grafica = None` después de la llamada al modelo,
sin importar lo que haya devuelto (ver §2).

`ensamblar_system(base, plantilla_extra, enfoque, contexto, instrucciones, regla_datos,
contexto_momento='', instrucciones_momento='')` compone, en orden fijo: `base + plantilla_extra` →
`bloque_enfoque` → `bloque_contexto` → `bloque_instrucciones` (manda sobre lo anterior) →
`regla_datos` (siempre al final, no negociable). `analysis.py` arma este mismo orden a mano en
cada función en vez de llamar a `ensamblar_system` directamente, pero con la misma secuencia.

---

## 2. Pipeline local — `analitica/analysis.py`

BERTopic (clustering de tópicos) + estadísticas son 100% determinísticos, locales, sin LLM. La
redacción de cada agente sí llama a OpenAI vía `_llamar_llm(system, user, max_tokens, temperature)`
(mismo patrón threading+timeout que el resto del proyecto, ver `analisis_ia_openai.py`), desde el
2026-09-20 — antes de esa fecha llamaba a un LLM local (Qwen2.5-3B-Instruct GGUF).

**Red de seguridad heredada del modelo local, todavía activa:** `CIFRA_FALSA_RE` /
`_purgar_cifras_falsas` (L119-129) limpian cualquier cifra que aparezca cuando NO hay conteo real
por tema (`metodo_valores in ('llm', 'bertopic_sin_clasificar')`, ver `_agente_pregunta_abierta`
L698-701) — el comentario en el código todavía dice literalmente *"un modelo de 3B instruido a
'priorizar cifras' inventa una igual"*, una referencia al modelo viejo que ya no aplica tal cual,
pero la purga en sí se mantiene como defensa en profundidad (no depender de que el prompt baste).
Se aplica solo en ese método/caso puntual, **no** a toda salida cualitativa.

### 2.1 `_agente_pregunta_abierta` (system base, antes de `bloque_enfoque`)

```
Eres un analista de datos senior interpretando los resultados de UNA pregunta de encuesta abierta
para un informe institucional que va a leer la Rectoría. El informe debe ser profesional, conciso
y muy descriptivo a nivel de cifras: la gráfica ya muestra la distribución, tu texto es un
complemento breve, no el protagonista. Escribe máximo 2 a 3 frases cortas, en español, priorizando
los números concretos (porcentajes, tamaños) sobre interpretación extensa. Ve directo al dato:
nunca empieces con muletillas como 'Resultados de la encuesta:', 'Los resultados indican que' o
'Descripción de los resultados:' — esas frases no aportan nada y suenan robóticas. Escribe en
prosa corrida, NUNCA con etiquetas o numeración como '(1)', '(2)', 'Hallazgo:' o 'Conclusión:' —
esas palabras no deben aparecer en el texto. Lee primero el enunciado exacto de la pregunta (te lo
doy abajo) y ANCLA tu interpretación a ese contenido específico — de qué trata realmente, qué
principio/tema/decisión plantea — nunca generalices con frases sobre 'satisfacción general',
'experiencia de los estudiantes' o cualquier otro tema que la pregunta no esté planteando. En una
o dos frases menciona SOLO el tema principal (el que domina, con su cifra exacta) — no enumeres
cada tema de la lista uno por uno. Cierra con una frase corta de conclusión — razona genuinamente,
como lo haría un analista real pensando qué le recomendaría a la Universidad específicamente sobre
ESTE planteamiento, no una fórmula que aplicarías igual a cualquier otra pregunta. Nunca te quedes
solo citando el número, nunca repitas la misma idea dos veces, y nunca caigas en frases genéricas
que servirían para cualquier informe ('es fundamental', 'es crucial'). Usa EXCLUSIVAMENTE los
datos entregados a continuación — nunca inventes cifras ni ideas que no estén ahí. Si a un tema NO
se le da un porcentaje o número de respuestas explícito, es porque no hay conteo real disponible
para él — en ese caso menciónalo solo por su nombre, SIN inventarle ni asignarle ninguna cifra.
```

Si `graficable` (método `bertopic_llm` con 2+ temas), se anexa la instrucción de cerrar con una
línea `GRAFICA: pastel|barras|radar`; si además el momento es de tipo `mesa`, se anexa la de
`NIVEL_ACUERDO: consenso_fuerte|consenso_moderado|tension_estrategica|tema_emergente|
asunto_pendiente`. Ambos tags se parsean del texto con regex (`GRAFICA_TAG_RE`/`NIVEL_ACUERDO_RE`)
y se remueven antes de guardar la descripción final. Orden de anexado: `system` base → tags
condicionales → `bloque_enfoque(enfoque)` → `bloque_contexto` → `bloque_instrucciones` →
`REGLA_DATOS_ANALISIS`.

Si `normalizar_enfoque(enfoque) == 'cualitativo'`, el código fuerza `tipo_grafica = None` **después**
de la llamada, sin importar el tag que haya devuelto el modelo (refuerzo de código, no solo de
prompt).

### 2.2 `_agente_pregunta_cerrada` (system base)

```
Eres un analista de datos senior interpretando los resultados de UNA pregunta de encuesta de
opción cerrada para un informe institucional que va a leer la Rectoría. El informe debe ser
profesional, conciso y muy descriptivo a nivel de cifras: la gráfica ya muestra la distribución,
tu texto es un complemento breve. Escribe máximo 2 a 3 frases cortas, en español, priorizando los
números concretos (conteos, porcentajes) sobre la prosa. Ve directo al dato: nunca empieces con
muletillas como 'Resultados de la encuesta:', 'Los resultados indican que' o 'Descripción de los
resultados:' — esas frases no aportan nada y suenan robóticas. Escribe en prosa corrida, NUNCA con
etiquetas o numeración como '(1)', '(2)', 'Hallazgo:' o 'Conclusión:' — esas palabras no deben
aparecer en el texto. Lee primero el enunciado exacto de la pregunta (te lo doy abajo) y ANCLA tu
interpretación a ese contenido específico — de qué trata realmente, qué principio/tema/decisión
plantea — nunca generalices con frases sobre 'satisfacción general', 'experiencia de los
estudiantes' o cualquier otro tema que la pregunta no esté planteando. Menciona qué opción domina
(o si está dividido, citando las cifras exactas) y cierra con una frase corta de conclusión —
razona genuinamente, como lo haría un analista real pensando qué le recomendaría a la Universidad
específicamente sobre ESTE planteamiento, no una fórmula que aplicarías igual a cualquier otra
pregunta. Nunca te quedes solo citando el número, nunca repitas la misma idea dos veces, y nunca
caigas en frases genéricas que servirían para cualquier informe ('es fundamental', 'es crucial').
Usa EXCLUSIVAMENTE los datos entregados — nunca inventes cifras. La elección de gráfica es un dato
técnico aparte, NUNCA la menciones ni la justifiques dentro de tu texto narrativo (nada de
'recomiendo la gráfica de barras' en la prosa) — va solo en su propia línea al final. Luego, en
una última línea aparte, recomienda la gráfica que mejor muestre hacia dónde se inclina el público
entre las opciones, escribiendo EXACTAMENTE una de estas tres líneas: 'GRAFICA: pastel' (pocas
opciones mutuamente excluyentes), 'GRAFICA: barras' (comparación simple de conteos), o 'GRAFICA:
radar' (varias opciones — 4 o más — donde interesa ver la forma general de la inclinación entre
todas a la vez). Si se te da una nota con una recomendación, síguela salvo que los datos digan
claramente lo contrario.
```

Si ninguna opción tiene conteo real (`sum(conteos) == 0`), el código ni siquiera llama al modelo —
devuelve directo `'No se recibieron respuestas.'` (mismo principio que `CIFRA_FALSA_RE`: no confiar
en que el modelo razone bien la ausencia de datos). Orden de anexado igual que en §2.1 (sin tags
condicionales aquí, `NIVEL_ACUERDO`/`GRAFICA` es siempre aplicable en preguntas cerradas).

### 2.3 `_sintetizar_momento` (system base)

```
Eres un analista de datos senior presentando a directivos — escribe como lo haría un profesional
real con experiencia, no un generador de texto institucional. Redacta una síntesis de 2 a 4 frases
(nunca más), en prosa clara, de UN momento de una jornada participativa, integrando las
descripciones ya redactadas de sus preguntas — no repitas pregunta por pregunta, ve directo al
dato/tema más relevante del conjunto (qué domina, dónde hay consenso o división, citando cifras
concretas cuando estén disponibles). Evita relleno institucional y frases genéricas repetidas
como 'es fundamental que', 'es crucial', 'recomiendo implementar programas de formación'; nunca
repitas la misma idea dos veces ni uses etiquetas como '(1)', '(2)', 'Hallazgo:' o 'Conclusión:'.
Cierra con UNA recomendación — razónala genuinamente, como lo haría un analista real pensando qué
le sugeriría a la Universidad a partir de ESTE conjunto de datos puntual, no una fórmula que
aplicarías igual en cualquier otro momento. Nunca empieces con muletillas como 'Resultados de la
encuesta:' o 'Los resultados indican que'. No agregues datos que no estén en las descripciones
dadas. Español.
```

Si ninguna pregunta del momento tiene respuestas reales, tampoco se llama al modelo (mismo guard).

### 2.4 `analizar_jornada` (`BASE_SYSTEM_PROMPT`)

```
Eres un analista de datos que redacta el reporte de una jornada participativa para su equipo
organizador. El informe debe ser profesional, conciso y centrado en cifras: prioriza números y
porcentajes concretos sobre prosa interpretativa, evita relleno y frases genéricas — máximo 2
párrafos cortos. Usa EXCLUSIVAMENTE los datos que se te entregan a continuación — nunca inventes
cifras, porcentajes, temas ni citas que no estén en esos datos. Si un dato no está disponible, no
lo menciones. Escribe en español, en prosa clara y directa, sin viñetas innecesarias.
```

Este es el prompt que `procesar_reporte` guarda en `Reporte.prompt_usado` (el system ya compuesto
completo, con enfoque/contexto/instrucciones/regla de datos incluidos) — es la síntesis de más
alto nivel del reporte, por eso es la que se conserva cuando hay decenas de otros prompts (uno por
pregunta y por momento) que sería excesivo guardar todos.

### 2.5 Formato de salida real de `Reporte.analisis`

**Jerárquico, NO el "v1" del plan.** `procesar_reporte` arma:
```python
reporte.analisis = {'participacion': participacion, 'momentos': momentos_analisis}
```
donde cada item de `momentos_analisis` es `{'momento_id', 'tipo', 'descripcion_general',
'preguntas': [...]}` y cada pregunta trae su propia descripción, `tipo_grafica`, `nivel_acuerdo`
(si aplica) y los datos cuantificados por BERTopic. Nada de `hallazgos[]`, `evidencia`,
`naturaleza`, `fuentes` ni `recomendaciones[]`.

`reporte.modelo_usado = 'Generado con IA' if texto else ''` (desde 2026-09-20) — antes exponía el
nombre del archivo del modelo local (`qwen2.5-3b-instruct-q4_k_m.gguf`); ahora sigue la misma
convención de no exponer el proveedor/modelo real que ya usaba `analisis_ia_openai.py`
(`MODELO_USADO_LABEL`).

---

## 3. Análisis integral vía OpenAI — `analitica/analisis_ia_openai.py`

Una sola llamada por momento o por jornada completa (a diferencia de §2, que hace una llamada por
pregunta + una por momento + una de cierre). Usa `ensamblar_system()` de `prompt_comun.py` — mismo
mecanismo de enfoque que §2.

### 3.1 `SYSTEM_PROMPT` (momento) — formato de salida real

```json
{
  "momento_id": <int, el mismo que te dieron>,
  "tipo": "<individual|mesa, el mismo que te dieron>",
  "resumen_ejecutivo": "<panorama general del instrumento completo, 4 a 7 frases>",
  "hallazgos": [
    {
      "titulo": "<título corto y natural del hallazgo, no un identificador técnico>",
      "descripcion": "<la deducción en sí, 2 a 5 frases, con sus cifras exactas>",
      "preguntas_relacionadas": [<pregunta_id>, ...],
      "tipo_grafica": "<pastel|barras|radar|null>",
      "datos": [ {"etiqueta": "<string>", "valor": <número>, "unidad": "conteo"|"porcentaje"} ]
    }
  ]
}
```

Sin `evidencia`, sin `naturaleza`, sin `citas`/`hablante`/`fuente`, sin `recomendaciones[]`, sin
`temas[]`, sin `id` tipo `"h1"` — es un schema plano. El texto completo del prompt (rol, cómo
pensar el análisis, reglas de los datos de cada hallazgo, estilo de redacción) está en
`analisis_ia_openai.py` L34-139; no se transcribe completo acá porque no cambió nada relevante
para esta comparación, solo el schema de salida (arriba) y el punto donde entra `bloque_enfoque`
(ver el comentario en el propio archivo, L70-79, sobre el bug real de producción que motivó mover
la regla de "graficar o no" al bloque de enfoque).

### 3.2 `SYSTEM_PROMPT_JORNADA` — formato de salida real

Igual estructura que §3.1 más:
```json
{
  "jornada_id": "<int>",
  "momentos_relacionados": ["<momento_id>", "..."],
  "transcripciones_relacionadas": ["<sesion_id>", "... (vacío si no aplica)"]
}
```
Puede recibir además una lista `transcripciones`: el resumen YA REDACTADO
(`resumen_ejecutivo`/`temas_discutidos`/`hallazgos`) de cada `InformeTranscripcion` completo
vinculado con `incluir_en_analisis_jornada=True` — nunca la transcripción cruda (reutiliza el
pipeline de mapa-reducción de §5).

---

## 4. Infografía — `analitica/infografia_ia_openai.py`

**No usa `bloque_enfoque` ni distingue por enfoque en absoluto** — la infografía es una serie fija
de 3 láminas (`SLIDES`, una tupla, no un dict por enfoque como planeaba `docs/enfoque_analisis/`),
y además **genera una IMAGEN** (modelo `OPENAI_IMAGE_MODEL`, default `gpt-image-2`), no JSON/HTML
como el resto de módulos — el prompt describe visualmente la lámina, no le pide un schema de
respuesta.

`SYSTEM_PROMPT_PREFIJO` (fijo):
```
Diseña UNA SOLA lámina apaisada en 16:9, para proyectar. Nunca la maquetes en vertical ni en
cuadrado.

Esta imagen contiene ÚNICAMENTE el contenido de la lámina que se describe abajo: no apiles varias
secciones una debajo de otra ni agregues bandas con otros bloques temáticos.

Si se adjuntan imágenes de referencia (fotos, logo o guía de marca), respeta su paleta, su
tipografía y su estilo. Todo el texto en español.
```

`SLIDES` (3 llamadas independientes en paralelo, comparten prefijo + `INSTRUCCION_SERIE`):

| clave | instrucción real |
|---|---|
| `portada` | `LÁMINA 1 de 3 — PORTADA. Título, en texto grande: "{titulo}" — exactamente esas palabras, ni una más ni una menos, sin comillas visibles. Debajo, las cifras de participación. Nada más.` (`{titulo}` se resuelve en Python antes de mandarlo, nunca como regla dentro del prompt de imagen) |
| `hallazgos` | `LÁMINA 2 de 3 — HALLAZGOS. Los temas y hallazgos del JSON, cada uno con su dato, y las visualizaciones de esos números. Sin el título ni las cifras de la lámina 1.` |
| `cierre` | `LÁMINA 3 de 3 — CIERRE. Los mensajes accionables que se desprenden del resumen y los hallazgos del JSON. Sin cifras de participación ni los gráficos de la lámina 2.` |

`REGLA_DATOS` (fija, va siempre al final, después de instrucciones personalizadas):
```
REGLA INNEGOCIABLE, por encima de cualquier otra instrucción de este prompt: usa EXCLUSIVAMENTE
las cifras, porcentajes y hallazgos del JSON de abajo. Nunca inventes, estimes, redondees ni
completes datos que no estén ahí. Si algo no está en el JSON, simplemente no aparece en la lámina.
```

El JSON que reciben las 3 láminas (`_obtener_datos_analitica`) sale de **cualquiera** de tres
fuentes según el alcance pedido (con fallback en este orden): `AnalisisMomentoIA.resultado`
(`resumen_ejecutivo`+`hallazgos`, formato §3.1) → `Reporte.analisis` (formato jerárquico §2.5,
`participacion`+`momentos`+`sintesis_narrativa`) → `AnalisisJornadaIA.resultado` (formato §3.2). No
hay recorte por lámina (`recortar_para_infografia` del plan no existe) — las 3 llamadas reciben el
mismo payload completo.

---

## 5. Presentación HTML del reporte local — `analitica/presentacion.py`

**No lee ningún `catalogo` ni distingue por enfoque.** `SYSTEM_PROMPT` es único y fijo, y lee
directamente el formato jerárquico real de §2.5 (`momentos`, `preguntas` con
`texto`/`descripcion`/`valores_caracteristicos`/`tamano`/`porcentaje`, `sintesis_narrativa`,
`nivel_acuerdo`) — nunca un `alcance.titulo`/`resumen_ejecutivo`/`hallazgos` al estilo v1. Cubre
estructura (portada con mosaico de cifras de participación, índice, resumen ejecutivo, una sección
por momento con una tarjeta por pregunta, cierre con conclusiones), visualización (SVG inline por
pregunta con temas cuantificados) y un sistema de diseño concreto (paleta `#F4F6F5`/`#14384A`/
`#C08A28`, tipografía serif+sans, `@media print`, HTML autocontenido) — ver el archivo completo
(L21-99) para el texto exacto, no se transcribe entero acá por longitud.

---

## 6. Transcripciones — `transcripciones/informe_ia.py` y `transcripciones/presentacion.py`

Siempre cualitativo por diseño fijo — **no existe el concepto `enfoque` en ningún punto de
`transcripciones/`** (no es un switch, es la única forma en que este módulo redacta).

### 6.1 Mapa-reducción (`informe_ia.py`)

Sesiones largas (hasta ~4h) se resumen por tramos cronológicos en paralelo (`SYSTEM_PROMPT_TRAMO`,
hasta `MAX_TRAMOS_EN_PARALELO=4` a la vez) y luego se sintetizan en una sola llamada final
(`SYSTEM_PROMPT_SINTESIS`) — mismo principio jerárquico que `analysis.py` (pregunta→momento→jornada)
para que el contexto no escale con la duración de la sesión.

`SYSTEM_PROMPT_TRAMO`:
```
Eres un analista leyendo UN TRAMO de la transcripción de una sesión (reunión, entrevista o taller)
universitaria — este tramo es solo una parte de una conversación más larga, así que NO redactes un
resumen ejecutivo ni conclusiones finales todavía, eso lo hace otro paso después con todos los
tramos juntos. Tu trabajo acá es extraer, de ESTE tramo únicamente: los temas que se discutieron, y
los puntos concretos (acuerdos, desacuerdos, decisiones, preocupaciones, datos mencionados) con una
cita textual real que los respalde — nunca resumas de más ni inventes algo que no esté literalmente
dicho en el texto. Si el tramo incluye la etiqueta de quién habla (entre corchetes al inicio de
cada línea), úsala para identificar a quién citas; si no aparece, cita sin atribuir a nadie en
particular.
```
Formato de salida del tramo: `{"temas": [...], "puntos": [{"descripcion", "cita"}]}`.

`SYSTEM_PROMPT_SINTESIS` — formato de salida real (**`citas` es un array plano de strings, no
objetos `{texto, hablante, fuente}`** como en el plan; sin `naturaleza`, sin `evidencia`, sin
`recomendaciones`):
```json
{
  "resumen_ejecutivo": "<panorama general de toda la sesión, 4 a 7 frases>",
  "temas_discutidos": ["<tema>", "..."],
  "hallazgos": [
    {
      "titulo": "<título corto y natural del hallazgo, no un identificador técnico>",
      "descripcion": "<la deducción en sí, 2 a 5 frases>",
      "citas": ["<cita textual real que lo respalda>", "..."]
    }
  ]
}
```
Entrega entre 5 y 12 hallazgos según lo que la sesión realmente dé (nunca fuerza un número fijo).

### 6.2 `transcripciones/presentacion.py::SYSTEM_PROMPT`

HTML fijo, sin enfoque, que lee el formato de §6.1 (`resumen_ejecutivo`, `temas_discutidos`,
`hallazgos` con `citas` planas): portada con nombre de sesión + fecha, resumen ejecutivo destacado,
temas como chips, una tarjeta por hallazgo con sus citas (comillas/cursiva/borde lateral, nunca
parafraseadas). Sin gráficos, sin números — igual que `analitica/presentacion.py` en su tratamiento
de cualitativo puro, pero acá es la única variante que existe (no hay una versión cuantitativa).

---

## Resumen: qué mecanismo usa cada módulo

| Módulo | Llama a | `bloque_enfoque`/`ensamblar_system` | Formato de salida |
|---|---|---|---|
| `analysis.py` (pipeline local) | OpenAI (desde 2026-09-20; antes LLM local 3B) | Sí | Jerárquico viejo (`participacion`+`momentos`) |
| `analisis_ia_openai.py` (momento/jornada) | OpenAI, 1 llamada | Sí | Plano: `resumen_ejecutivo`+`hallazgos[]` (`tipo_grafica`/`datos`, sin `evidencia`/`naturaleza`) |
| `infografia_ia_openai.py` | OpenAI, modelo de IMAGEN | No | N/A (imagen, no JSON) |
| `presentacion.py` (reporte local → HTML) | OpenAI | No | Lee el jerárquico viejo, produce HTML |
| `transcripciones/informe_ia.py` | OpenAI, mapa-reducción | No (siempre cualitativo, sin switch) | `resumen_ejecutivo`+`temas_discutidos`+`hallazgos[]` con `citas` planas |
| `transcripciones/presentacion.py` | OpenAI | No | Lee el formato de arriba, produce HTML |

El formato `aluna.analisis/v1` de `docs/enfoque_analisis/` no aparece en ninguna fila de esta
tabla porque no se implementó en ningún módulo.
