# 01 — Plan de desarrollo

Índice: [§1 Inventario de lo afectado](#1-inventario-qué-toca-el-cambio) · [§2 Decisiones](#2-decisiones) ·
[§3 Modelo de datos y API](#3-modelo-de-datos-y-api) · [§4 Fases](#4-fases) · [§5 Riesgos](#5-riesgos-y-cómo-se-mitigan) ·
[§6 HU a documentar](#6-hu-a-documentar)

---

## 1. Inventario: qué toca el cambio

### 1.1 Puntos de prompt (los 8 que hay que modificar)

| # | Módulo | Constante / función | Qué produce hoy | Cambio |
|---|---|---|---|---|
| P1 | `analitica/analisis_ia_openai.py` | `SYSTEM_PROMPT` | `AnalisisMomentoIA.resultado` (hallazgos con `tipo_grafica` + `datos`) | Variante por enfoque + salida `aluna.analisis/v1` |
| P2 | `analitica/analisis_ia_openai.py` | `SYSTEM_PROMPT_JORNADA` | `AnalisisJornadaIA.resultado` | Variante por enfoque + salida v1 |
| P3 | `analitica/infografia_ia_openai.py` | `SYSTEM_PROMPT_PREFIJO`, `SLIDES` (3 láminas), `REGLA_DATOS` | Prompt de imagen por lámina | Láminas y regla de datos por enfoque; consume v1 |
| P4 | `analitica/presentacion.py` | `SYSTEM_PROMPT` | HTML de un `Reporte` local | Variante por enfoque (sin gráficos SVG ni mosaico de cifras en cualitativo) |
| P5 | `analitica/analysis.py` | `_agente_pregunta_abierta` (system inline) | Descripción por pregunta abierta + `GRAFICA:`/`NIVEL_ACUERDO:` | Variante cualitativa: temas y citas, sin `GRAFICA:`, sin cifras |
| P6 | `analitica/analysis.py` | `_agente_pregunta_cerrada` (system inline) | Descripción por pregunta cerrada con conteos | Variante cualitativa: la pregunta cerrada se describe como tendencia sin cifras (o se omite del narrativo, ver D6) |
| P7 | `analitica/analysis.py` | `_sintetizar_momento` (system inline) y `BASE_SYSTEM_PROMPT` (jornada) | `descripcion_general` de momento y `texto_reporte` | Variante cualitativa: prosa sin cifras |
| P8 | `transcripciones/informe_ia.py` + `transcripciones/presentacion.py` | `SYSTEM_PROMPT_SINTESIS`, `SYSTEM_PROMPT` (HTML) | `InformeTranscripcion.resultado` (ya cualitativo) | **No cambia de enfoque** (una transcripción siempre es diálogo); se alinea al formato v1 para que el FE lo pinte con el mismo componente |

`SYSTEM_PROMPT_TRAMO` (transcripciones) no se toca: es un paso intermedio del mapa-reducción,
nunca llega al frontend.

### 1.2 Renderizadores que consumen la salida (no tienen prompt, pero deben aceptar "sin gráfica")

| Módulo | Qué hace | Cambio |
|---|---|---|
| `analitica/pdf_presentacion.py` | PDF del `Reporte` local: portada con mosaico de cifras, un gráfico por pregunta | Portada sin mosaico en cualitativo; `_bloque_valores` pinta chips de tema / citas cuando no hay `grafica` |
| `transcripciones/pdf_informe.py` | PDF del informe de transcripción | Lee `hallazgos[].evidencia.citas` (v1) en vez de `hallazgos[].citas` |
| `analitica/infografia_ia_openai.py::_obtener_datos_analitica` | Arma el JSON que va en el prompt de imagen | Pasa el v1 completo (recortado) en vez de un subconjunto ad hoc |
| `analitica/reporte_excel.py` | Exporta **respuestas crudas** por pregunta/momento | **Sin cambio**: es una exportación de datos, no un reporte analítico; en cualitativo sigue siendo útil como respaldo |

### 1.3 Dónde se lee el enfoque

Un solo origen: `Jornada.enfoque_analisis`. Todo lo demás lo deriva:

- `AnalisisMomentoIA` → `momento.jornada.enfoque_analisis`
- `AnalisisJornadaIA`, `Reporte`, `InfografiaJornada` → `jornada.enfoque_analisis`
- `InformeTranscripcion` → no lo lee (siempre cualitativo, D5)

---

## 2. Decisiones

Formato: opciones, recomendación, si bloquea. Se cierran editando este archivo (mismo mecanismo
que `docs/banco_instrumentos/02_decisiones.md`).

### D1 — Cómo se modela el campo · **bloquea Fase 1**

| Opción | Descripción | Pros | Contras |
|---|---|---|---|
| **A (recomendada)** | `Jornada.enfoque_analisis = CharField(choices=['cuantitativo','cualitativo'], default='cuantitativo')` | Extensible (un `mixto` futuro es agregar un choice), el nombre dice qué controla, `default` reproduce el comportamiento actual sin backfill | Un choice de 2 valores parece un booleano disfrazado |
| B | `Jornada.es_percepcion_general = BooleanField(default=False)` | Mapea literal al enunciado | Un booleano no crece; el nombre habla del tipo de jornada, no de lo que cambia (el análisis); habría que renombrar cuando aparezca un tercer modo |

En la API y en el frontend el valor `cualitativo` se etiqueta **"Percepción general (cualitativo)"**
y `cuantitativo` **"Instrumentos con datos (cuantitativo)"**, así el enunciado y el campo dicen lo
mismo.

### D2 — ¿Se puede cambiar el enfoque de una jornada que ya tiene análisis? · no bloquea

**Recomendación: sí, sin restricción.** El enfoque afecta solo a los análisis que se generen
**después** del cambio. Los ya generados conservan su `enfoque` propio dentro del JSON v1
(campo `enfoque` en el sobre), así que el frontend nunca tiene que cruzar "la jornada hoy" con "el
análisis de ayer". Bloquearlo obligaría a borrar análisis para poder corregir un error de
configuración al crear la jornada, que es justo el caso más común.

### D3 — Override por corrida (`enfoque` en el POST de análisis/infografía) · no bloquea

| Opción | Descripción |
|---|---|
| **A (recomendada)** | El POST de `AnalisisMomentoIA`, `AnalisisJornadaIA`, `Reporte` e `InfografiaJornada` acepta un campo opcional `enfoque`; si viene, manda para esa corrida; si no, se hereda de la jornada. Se guarda en el sobre v1 (`enfoque`) y en un campo `enfoque` del modelo de la corrida para poder filtrar. |
| B | Solo el campo de la jornada. |

A cuesta un `ChoiceField(required=False)` por serializer y un campo por modelo, y resuelve
literalmente "en configuración tener algo que diga si se quiere análisis más cualitativo o más
cuantitativo" a dos niveles: el default de la jornada y el ajuste puntual de una corrida (probar
cómo se ve el mismo material de las dos formas sin tocar la jornada, igual que hoy se hace con
`instrucciones` en la infografía).

### D4 — Un solo formato de salida para todas las vías (`aluna.analisis/v1`) · **bloquea Fase 2**

**Recomendación: sí.** Hoy hay 4 formas distintas: `AnalisisMomentoIA.resultado`,
`AnalisisJornadaIA.resultado` (difieren en ids de fuente), `InformeTranscripcion.resultado`
(`citas` en vez de `datos`) y `Reporte.analisis` (jerarquía momento→pregunta). El frontend ya
tiene código distinto para cada una. El contrato v1 ([03_formato_salida_estandar.md](03_formato_salida_estandar.md))
las unifica con un **sobre** (`esquema`, `enfoque`, `alcance`, `cifras_clave`, `meta`) que pone el
backend y un **cuerpo** (`resumen_ejecutivo`, `temas`, `hallazgos`, `recomendaciones`) que
produce el modelo. La forma de cada hallazgo es la misma en todas las vías; lo que varía por
enfoque es qué trae `evidencia` (gráfica vs. citas), y eso va **discriminado** (`evidencia.tipo`).

Compatibilidad: los `resultado` ya guardados con la forma vieja **no se migran en base**; el
serializer los pasa por `normalizar_v1()` al leer (D7), así el frontend solo conoce v1.

### D5 — El informe de transcripción no depende del enfoque de la jornada · no bloquea

**Recomendación: siempre cualitativo.** Una `SesionTranscripcion` puede no tener jornada, y
aunque la tenga, una transcripción es diálogo por definición — pedirle cifras a una conferencia
es el problema que este cambio viene a corregir. Cambio en P8: solo alinear la salida a v1
(`evidencia.tipo = "citas"`), no cambiar el fondo del prompt.

### D6 — Qué hace el pipeline local (`Reporte`) con preguntas cerradas en cualitativo · **bloquea Fase 6**

Una jornada de percepción general puede igual tener alguna pregunta de opción (ej. "¿en qué
sede estás?"). Opciones:

| Opción | Descripción |
|---|---|
| **A (recomendada)** | Las preguntas cerradas **se siguen analizando** pero con el prompt P6 cualitativo: se describe la tendencia en prosa ("la mayoría se inclina por…", "hay división entre…") **sin cifras ni porcentajes**, `tipo_grafica = null`. Los conteos siguen guardados en `valores_caracteristicos` (son datos reales) pero `analisis_estandar` (D8) no los expone como gráfica. |
| B | Las preguntas cerradas se omiten del narrativo en cualitativo. |

A porque omitir información real es peor que describirla sin números, y porque un momento con
una sola pregunta cerrada quedaría vacío con B.

Para preguntas **abiertas** en cualitativo (P5): BERTopic sigue descubriendo temas (es lo que
alimenta `temas` del v1), pero **no se corre la clasificación con conteo** (`_etiquetar_y_clasificar`) —
`metodo_valores = 'temas_cualitativos'`, `valores_caracteristicos = [{'tema': …, 'citas': […]}]`.
Ahorra la mitad de las llamadas al LLM local y elimina de raíz la posibilidad de que un modelo
de 3B invente "(100%)" (ver el comentario sobre `CIFRA_FALSA_RE` en `analysis.py`).

### D7 — Normalización de resultados viejos al leer · no bloquea

**Recomendación: sí**, función pura `analitica/esquema_analisis.py::normalizar_v1(resultado, *, alcance, enfoque)`
que detecta por presencia de `esquema`: si ya es v1 lo devuelve tal cual; si es la forma vieja
(`tipo_grafica`+`datos`, o `citas`) la traduce. Sin migración de datos, sin doble código en el
frontend. Costo: una función con tests, ~80 líneas.

### D8 — ¿`Reporte.analisis` (pipeline local) también entrega v1? · no bloquea

**Recomendación: sí, como campo derivado read-only `analisis_estandar`** en `ReporteSerializer`,
calculado por `reporte_a_estandar(reporte)` a partir de `analisis` + `texto_reporte` +
`participacion`. `analisis` se mantiene intacto (el PDF y la presentación HTML lo siguen leyendo
por ahora; se migran en Fase 6). El frontend puede entonces pintar un `Reporte` con el mismo
componente que un `AnalisisJornadaIA`: cada pregunta se convierte en un hallazgo con `fuentes.preguntas=[id]`
y `evidencia.grafica` cuando `metodo_valores ∈ {conteo, bertopic_llm}`.

### D9 — `PlantillaAnalisis` por enfoque · no bloquea

**Recomendación: no cambiar.** Las "instrucciones adicionales del equipo" se siguen anexando al
final del prompt sea cual sea el enfoque. Si más adelante hace falta una plantilla distinta por
enfoque, es agregar un campo `enfoque` nullable a `PlantillaAnalisis` y filtrar; no condiciona
nada de este plan.

### D10 — `cifras_clave` en el sobre las pone el backend, nunca el modelo · no bloquea

**Recomendación: sí.** Participantes, respondieron, tasa, número de momentos/preguntas/sesiones
se calculan en código (ya existe `procesar_reporte` haciéndolo). El modelo no las produce ni las
repite: así no hay dos versiones de "cuántos participaron". En cualitativo el sobre lleva
`cifras_clave: []` **siempre**, aunque los números existan — es la regla que el frontend puede
dar por sentada.

### Resumen (rellenar al cerrar)

| Decisión | Cerrada | Opción |
|---|---|---|
| D1 Modelo del campo | ☐ | |
| D2 Cambiar enfoque con análisis existentes | ☐ | |
| D3 Override por corrida | ☐ | |
| D4 Formato único v1 | ☐ | |
| D5 Transcripciones siempre cualitativas | ☐ | |
| D6 Pipeline local con cerradas en cualitativo | ☐ | |
| D7 Normalizar al leer | ☐ | |
| D8 `analisis_estandar` en Reporte | ☐ | |
| D9 Plantillas por enfoque | ☐ | |
| D10 `cifras_clave` desde código | ☐ | |

---

## 3. Modelo de datos y API

### 3.1 `jornadas/models.py`

```python
class Jornada(models.Model):
    ENFOQUE_CUANTITATIVO = 'cuantitativo'
    ENFOQUE_CUALITATIVO = 'cualitativo'
    ENFOQUE_CHOICES = [
        (ENFOQUE_CUANTITATIVO, 'Instrumentos con datos (cuantitativo)'),
        (ENFOQUE_CUALITATIVO, 'Percepción general (cualitativo)'),
    ]
    # ...
    # Qué tipo de material recoge la jornada y, por lo tanto, cómo se analiza. `cuantitativo` es
    # todo lo que existía antes de este campo: instrumentos con opciones/escalas, conteos,
    # porcentajes y gráficas. `cualitativo` es una jornada de percepción general — diálogos,
    # transcripciones, intervenciones — donde contar no significa nada: los reportes y las
    # infografías salen sin una sola cifra, respaldados por citas textuales. Lo leen TODOS los
    # módulos que arman un prompt de reporte o infografía (ver docs/enfoque_analisis/). Se
    # puede cambiar en cualquier momento: solo afecta a los análisis que se generen después.
    enfoque_analisis = models.CharField(
        max_length=15, choices=ENFOQUE_CHOICES, default=ENFOQUE_CUANTITATIVO,
    )
```

Migración `jornadas/migrations/0018_jornada_enfoque_analisis.py` — solo esquema; el `default`
cubre las filas existentes, no hay backfill.

### 3.2 Campo `enfoque` en las corridas (D3)

En `AnalisisMomentoIA`, `AnalisisJornadaIA`, `Reporte` e `InfografiaJornada`:

```python
    # Con qué enfoque se generó ESTA corrida. Se copia de la jornada al crear (o del override del
    # POST) y no cambia después, para que un análisis viejo siga diciendo cómo se hizo aunque la
    # jornada haya cambiado de enfoque (D2). Redundante con resultado['enfoque'] a propósito:
    # esto es filtrable en el ORM, aquello es lo que viaja al frontend.
    enfoque = models.CharField(max_length=15, choices=Jornada.ENFOQUE_CHOICES, blank=True)
```

Migración `analitica/migrations/0014_enfoque_por_corrida.py`. Sin backfill: `blank` = "anterior
a este cambio", y `normalizar_v1()` lo trata como `cuantitativo` (que es lo que era).

### 3.3 Módulo nuevo `analitica/esquema_analisis.py`

Único lugar que sabe la forma de v1. Funciones puras, sin ORM:

| Función | Qué hace |
|---|---|
| `ESQUEMA = 'aluna.analisis/v1'` | Constante. |
| `envolver(cuerpo, *, enfoque, alcance, cifras_clave, meta)` | Pone el sobre alrededor del cuerpo que devolvió el modelo. |
| `validar_y_limpiar(doc)` | Fuerza invariantes: en cualitativo borra `grafica`, vacía `cifras_clave`, purga cifras del texto (`_purgar_cifras_falsas` ya existe); en ambos calcula `evidencia.tipo` a partir de lo que hay, asigna `id` a hallazgos que no lo traigan, limpia etiquetas de estructura. **Nunca confía en que el modelo respetó el formato porque se le pidió.** |
| `normalizar_v1(resultado, *, alcance, enfoque)` | D7: forma vieja → v1. |
| `reporte_a_estandar(reporte)` | D8: `Reporte.analisis` → v1. |
| `recortar_para_infografia(doc, lamina)` | Subconjunto del v1 para cada lámina (P3). |

### 3.4 Selección de prompt por enfoque

Cada módulo con prompt deja de tener una constante y pasa a tener un **ensamblador**:

```python
# analitica/analisis_ia_openai.py
def system_prompt_momento(enfoque):
    return _ensamblar(
        ROL_MOMENTO, FUENTES_MOMENTO, COMO_PENSAR_MOMENTO,
        ENFOQUE[enfoque]['analisis'],          # bloque que cambia
        FORMATO_SALIDA_V1_MOMENTO,             # compartido, ver 03_formato_salida_estandar.md
        ENFOQUE[enfoque]['reglas_evidencia'],  # bloque que cambia
        ESTILO, CIERRE,
    )
```

Los textos completos de cada bloque, en las dos variantes, están en
[02_system_prompts.md](02_system_prompts.md). Se escriben así (partes + ensamblador) y no como
dos constantes gigantes por prompt porque el 70 % es común, y tener dos copias es la receta para
que la próxima corrección se aplique en una sola.

### 3.5 API

**Jornadas** (`/api/admin/jornadas/`): `enfoque_analisis` entra y sale en `JornadaAdminSerializer`
(escribible en POST/PATCH, default `cuantitativo`). `400` si el valor no es un choice.

**Corridas** (`/api/admin/analisis-momento-ia/`, `/analisis-jornada-ia/`, `/reportes/`,
`/infografias/`): campo opcional `enfoque` en el POST (D3). Respuesta: `enfoque` (el efectivo)
y `resultado` / `analisis_estandar` ya en v1 (D4, D7, D8).

**Transcripciones** (`/api/admin/informes-transcripcion/`): `resultado` en v1 con
`alcance.tipo = "sesion"` y `enfoque = "cualitativo"` (D5).

Ningún endpoint nuevo. Ningún cambio de ruta.

---

## 4. Fases

Cada fase es entregable y desplegable por separado; el orden minimiza el tiempo en que el
frontend ve dos formatos. Estimaciones para una persona.

### Fase 0 — Cerrar decisiones (½ día)

- [ ] D1, D4 y D6 (las que bloquean). El resto puede quedar en la recomendación.
- [ ] Pasar [03_formato_salida_estandar.md](03_formato_salida_estandar.md) al frontend y
      recoger ajustes **antes** de la Fase 2 — es más barato cambiar un nombre de campo en el
      documento que en 5 módulos.

### Fase 1 — Campo en la jornada (½ día) → **HU-71**

Objetivo: la jornada sabe su enfoque; el FE ya puede pintar el selector. Nada más cambia.

- [ ] `jornadas/models.py`: `enfoque_analisis` (§3.1) + migración `0018`.
- [ ] `jornadas/serializers.py` → `JornadaAdminSerializer.fields += ['enfoque_analisis']`.
- [ ] `jornadas/admin.py`: `list_filter` y campo visible.
- [ ] `analitica/models.py`: campo `enfoque` en las 4 corridas (§3.2) + migración `0014`.
      Se rellena al crear con `jornada.enfoque_analisis` (en `perform_create`/`create` de cada
      viewset, ya centralizados en `admin_views.py`).
- [ ] HU-71.

Tests (`jornadas/tests.py`, clase `JornadaEnfoqueTests`): default al crear sin el campo; POST con
`cualitativo`; PATCH cambia; valor inválido → 400; `AnalisisJornadaIA` creado hereda el enfoque.

### Fase 2 — Formato estándar v1 y normalización (1 día) → **HU-72**

Objetivo: el frontend recibe v1 en **todas** las vías, aunque los prompts todavía no lo
produzcan (lo produce `normalizar_v1`). A partir de aquí el FE puede migrar a un componente.

- [ ] `analitica/esquema_analisis.py` (§3.3) con `envolver`, `validar_y_limpiar`,
      `normalizar_v1`, `reporte_a_estandar`.
- [ ] Serializers: `AnalisisMomentoIASerializer.resultado`, `AnalisisJornadaIASerializer.resultado`,
      `InformeTranscripcionSerializer.resultado` → `SerializerMethodField` que llama `normalizar_v1`.
      `ReporteSerializer.analisis_estandar` (D8).
- [ ] `cifras_clave` desde código (D10): helper `cifras_clave_jornada(jornada)` /
      `cifras_clave_momento(momento)` reutilizando `_estadisticas_pregunta` y la lógica de
      participación de `procesar_reporte`.
- [ ] `docs/INTEGRACION_FRONTEND_ANALISIS_V1.md` = copia limpia de
      [03_formato_salida_estandar.md](03_formato_salida_estandar.md) con la URL base y los
      ejemplos de los 4 endpoints.
- [ ] HU-72.

Tests (`analitica/tests_esquema.py`, sin API ni OpenAI): normalizar cada forma vieja (momento,
jornada, transcripción, reporte) → v1 válido; `validar_y_limpiar` en cualitativo borra gráficas y
cifras; `evidencia.tipo` calculado correctamente para las 4 combinaciones; idempotencia
(normalizar un v1 devuelve el mismo objeto); `reporte_a_estandar` con `metodo_valores` de cada tipo.

### Fase 3 — Análisis integral de momento y jornada por enfoque (1 día) → **HU-73**

P1 y P2. Es donde más se nota el cambio y donde más material de prueba hay.

- [ ] `analisis_ia_openai.py`: partes + `system_prompt_momento(enfoque)` /
      `system_prompt_jornada(enfoque)` (§3.4) con los textos de
      [02_system_prompts.md](02_system_prompts.md) §1 y §2.
- [ ] El modelo devuelve solo el **cuerpo** v1; `analizar_momento_ia` / `analizar_jornada_ia`
      envuelven con `envolver(...)` y pasan por `validar_y_limpiar`.
- [ ] Override `enfoque` en `AnalisisMomentoIACrearSerializer` / `AnalisisJornadaIACrearSerializer` (D3).
- [ ] En cualitativo, `_preguntas_payload` sigue mandando `opciones` (conteos) — el prompt dice
      cómo tratarlas; no se ocultan porque el modelo necesita el contexto.
- [ ] HU-73.

Tests (`analitica/tests.py`, mock de `_llamar_openai_json`): con jornada cualitativa el system
prompt contiene el bloque cualitativo y no el cuantitativo (y viceversa); un cuerpo devuelto
con `grafica` en cualitativo sale sin ella tras `validar_y_limpiar`; override por POST manda
sobre la jornada; `resultado.enfoque` y `analisis.enfoque` coinciden.

### Fase 4 — Infografía por enfoque (½ día) → **HU-74**

P3. Depende de Fase 3 (consume v1).

- [ ] `infografia_ia_openai.py`: `SLIDES` y `REGLA_DATOS` pasan a `SLIDES[enfoque]` /
      `REGLA_DATOS[enfoque]` (textos en [02_system_prompts.md](02_system_prompts.md) §3).
- [ ] `_obtener_datos_analitica` devuelve el v1 (ya normalizado) y `recortar_para_infografia`
      arma el JSON de cada lámina — reemplaza el diccionario ad hoc actual.
- [ ] `prompt_usado` guarda el de la lámina 1, como hoy.
- [ ] Override `enfoque` en el POST de infografías (D3); `instrucciones` sigue igual.
- [ ] Actualizar `docs/INTEGRACION_FRONTEND_INFOGRAFIA.md` (§ "Instrucciones personalizadas":
      en cualitativo la regla innegociable es "sin cifras", no "solo estas cifras").
- [ ] HU-74.

Tests: el prompt de cada lámina en cualitativo no contiene la palabra "porcentaje" ni el bloque
de participación; en cuantitativo sí; `recortar_para_infografia` entrega a la lámina 2 solo
hallazgos y a la 3 solo recomendaciones.

### Fase 5 — Transcripciones al formato v1 (½ día) → **HU-75**

P8. Independiente de las fases 3–4; puede ir en paralelo.

- [ ] `transcripciones/informe_ia.py::SYSTEM_PROMPT_SINTESIS`: sección de formato → cuerpo v1
      con `evidencia.citas` (texto en [02_system_prompts.md](02_system_prompts.md) §6).
      `generar_informe_transcripcion` envuelve con `envolver(enfoque='cualitativo', alcance={'tipo':'sesion',…})`.
- [ ] `transcripciones/presentacion.py::SYSTEM_PROMPT`: lee v1 (mismo contenido, nombres nuevos).
- [ ] `transcripciones/pdf_informe.py`: lee `evidencia.citas`.
- [ ] `analisis_ia_openai._transcripciones_payload`: pasa el v1 de cada sesión (el prompt P2
      ya lo describe como "resumen ya redactado").
- [ ] HU-75.

Tests (`transcripciones/tests.py`): resultado nuevo es v1 con `enfoque='cualitativo'` y todos
los hallazgos con `evidencia.tipo='citas'`; un informe viejo se sirve normalizado; el PDF se
construye con ambos.

### Fase 6 — Pipeline local (`Reporte`), presentación HTML y PDF por enfoque (1½ días) → **HU-76**

P4, P5, P6, P7 y los dos renderizadores de `analitica`. Es la fase más invasiva porque el
pipeline local tiene cuatro prompts inline y un flujo BERTopic → clasificación con conteo que
en cualitativo se corta (D6).

- [ ] `analysis.py`: `BASE_SYSTEM_PROMPT` → `system_prompt_jornada_local(enfoque)`; los system
      inline de `_agente_pregunta_abierta`, `_agente_pregunta_cerrada` y `_sintetizar_momento`
      → funciones por enfoque (textos en [02_system_prompts.md](02_system_prompts.md) §5).
- [ ] `analizar_pregunta`: rama cualitativa para abiertas (`metodo_valores='temas_cualitativos'`,
      sin `_etiquetar_y_clasificar`, con 1–2 citas por tema tomadas literal de las respuestas) y
      para cerradas (`tipo_grafica=None`, descripción sin cifras). `procesar_reporte` pasa el
      enfoque a todo el árbol.
- [ ] `presentacion.py`: `system_prompt_presentacion(enfoque)` (§4 del doc de prompts).
- [ ] `pdf_presentacion.py`: `_portada` sin mosaico en cualitativo; `_bloque_valores` con rama
      `temas_cualitativos` (chips + citas). Ambos leen `reporte.enfoque`.
- [ ] `reporte_a_estandar` cubre `temas_cualitativos`.
- [ ] Override `enfoque` en `ReporteCrearSerializer` (D3).
- [ ] HU-76.

Tests (`analitica/tests.py`, mock de `_llamar_llm` y de BERTopic como ya se hace): en
cualitativo no se llama `_etiquetar_y_clasificar`; `analizar_pregunta` de una cerrada devuelve
`tipo_grafica=None`; el system de cada agente contiene el bloque correcto; `construir_pdf` no
falla con un `analisis` cualitativo; `_purgar_cifras_falsas` se aplica a todos los textos en
cualitativo.

### Fase 7 — Despliegue y validación (½ día)

- [ ] `migrate` en producción (ver `project_despliegue` en memoria del proyecto).
- [ ] Una jornada cualitativa real de prueba con ≥1 transcripción y ≥1 momento con abiertas:
      generar análisis de jornada, infografía y reporte local; revisar que ninguna salida tenga
      cifras.
- [ ] Una jornada cuantitativa existente: regenerar el análisis y comparar contra el anterior —
      el contenido debe ser equivalente, solo cambia la forma (v1).
- [ ] Frontend confirma que pinta las 4 vías con el componente único.

**Total: ~6 días.** Camino crítico: 0 → 1 → 2 → 3 → 4; 5 y 6 en paralelo desde que termine 2.

---

## 5. Riesgos y cómo se mitigan

| Riesgo | Mitigación |
|---|---|
| El modelo mete cifras en cualitativo aunque el prompt lo prohíba ("la mayoría (68 %)…") | `validar_y_limpiar` aplica `_purgar_cifras_falsas` a todo texto en cualitativo y borra `grafica`; el prompt es la primera línea, el código la última. Ya está probado que con un modelo pequeño el prompt solo no alcanza. |
| El modelo devuelve la forma vieja aunque se le pida v1 | `normalizar_v1` acepta ambas; se loguea `esquema` faltante como advertencia para medir con qué frecuencia pasa. |
| El frontend tiene que soportar dos formatos durante la transición | No: desde Fase 2 **todo** sale v1 por normalización. La transición es solo del backend. |
| Cambiar el enfoque de una jornada con análisis viejos confunde | Cada corrida guarda su `enfoque` (D2/D3); el FE muestra el del análisis, no el de la jornada. |
| Fase 6 rompe reportes cuantitativos existentes | El enfoque por defecto reproduce el flujo actual línea por línea; los tests actuales de `analysis.py` deben seguir pasando sin tocarlos. |
| Costos: una jornada cualitativa con muchas abiertas | D6 **reduce** llamadas (sin clasificación con conteo). |

---

## 6. HU a documentar

Numeración continúa desde HU-70 en `docs/USER_STORIES_COMPLETO.md`:

| HU | Fase | Título propuesto |
|---|---|---|
| HU-71 | 1 | Definir al crear la jornada si es de percepción general (enfoque cualitativo) o de instrumentos con datos |
| HU-72 | 2 | Un solo formato JSON (`aluna.analisis/v1`) para todos los análisis con IA, con evidencia discriminada |
| HU-73 | 3 | Análisis integral de momento y de jornada sin cifras cuando la jornada es cualitativa |
| HU-74 | 4 | Infografía cualitativa: citas y temas en vez de participación y gráficas |
| HU-75 | 5 | Informe de transcripción en el formato estándar |
| HU-76 | 6 | Reporte local, presentación HTML y PDF sin cifras en jornadas cualitativas |
