# Tipos de salida visual de Kunsamu v2

Esta guía acompaña a `analisis.schema.json`. Ambos pipelines usan las mismas 17 variantes. El discriminante del frontend es `visualizacion.tipo`; cada variante tiene metadatos comunes y un objeto `datos` propio.

Los ejemplos siguientes son **sintéticos e independientes**. Ilustran la forma de `datos`; no son resultados de una jornada ni objetos de respuesta completos.

## 1. Selección de la visualización

| `tipo` exacto | Uso que justifica la salida | Condición de uso |
|---|---|---|
| `barras` | Comparar frecuencias, porcentajes o medidas entre categorías. | Categorías y base definidas. Adecuado también para frecuencias temáticas o sentimiento codificado. |
| `barras_agrupadas` | Comparar grupos o momentos dentro de las mismas categorías. | Misma medida y escalas compatibles; informar bases por grupo. |
| `barras_apiladas` | Mostrar composición y tamaño total simultáneamente. | Componentes aditivos, no solapados; no apilar temas multietiqueta como un total de personas. |
| `barras_100` | Comparar composiciones porcentuales. | Cada barra tiene una base única conocida y categorías mutuamente excluyentes y exhaustivas dentro de esa base. |
| `dona` | Mostrar una composición simple de un total. | Una sola serie, valores no negativos y categorías exhaustivas sin solapamiento. Preferir pocas categorías. |
| `radar` | Comparar perfiles en dimensiones alineadas. | Escalas equivalentes, sentido de mejora consistente y normalización documentada, si existe. |
| `lineas` | Mostrar evolución en tiempo o variable numérica ordenada. | Orden real; no unir categorías nominales con líneas. |
| `areas` | Mostrar la magnitud de una evolución. | Mismas condiciones de `lineas`. El relleno representa cada serie de forma independiente; no implica apilamiento. |
| `dispersion` | Examinar asociación entre dos variables numéricas. | Pares observados compatibles; una asociación no prueba causalidad. |
| `pendientes` | Mostrar cambios entre dos mediciones comparables. | Dos puntos por serie y correspondencia explícita entre mediciones. Distinguir comparación agregada y seguimiento de las mismas personas. |
| `histograma` | Mostrar distribución de una variable numérica. | Observaciones o intervalos reportados suficientes; intervalos no solapados con límites conocidos. |
| `caja_bigotes` | Comparar distribución, mediana y dispersión. | Estadísticos recibidos o calculados verificablemente; nunca reconstruidos desde una media. |
| `mapa_calor` | Mostrar una matriz de magnitudes. | Celdas comparables, unidades comunes y ausencia distinguible de cero. |
| `nube_palabras` | Explorar términos presentes o relevantes en un corpus. | Tipo de peso y preprocesamiento explícitos. La nube no sustituye la interpretación temática. |
| `red_semantica` | Mostrar relaciones entre conceptos o temas. | Relación, unidad de cálculo y evidencia declaradas. No atribuir relaciones a BERTopic si no vienen calculadas. |
| `tabla` | Mostrar valores exactos, bases, excepciones o información heterogénea. | Columnas tipadas y unidades visibles. |
| `matriz_cualitativa` | Comparar temas, evidencias, tensiones o necesidades entre grupos o momentos. | Separar interpretación y evidencia; el tipo visual no implica cuantificación. |

No se requiere un gráfico para cada hallazgo. Una matriz, una cita contextualizada o una afirmación breve pueden comunicar mejor una evidencia cualitativa. No añadir visualizaciones redundantes.

## 2. Metadatos comunes obligatorios

Todas las visualizaciones incluyen estas claves además de `datos`:

| Clave | Tipo | Contenido |
|---|---|---|
| `id` | string | Identificador único dentro de `visualizaciones`; lo referencian los hallazgos. |
| `tipo` | enum | Uno de los 17 tipos de la tabla anterior. |
| `titulo` | string | Descripción breve de lo representado, sin una conclusión no sustentada. |
| `fuente_ids` | string[] | Identificadores existentes en `fuentes`. |
| `metodo` | string | Procedimiento concreto: conteo, denominador, codificación, transformación, relación o estadístico utilizado. |
| `unidad_analisis` | string | Qué cuenta cada observación: persona, respuesta, documento, fragmento, mención, etc. |
| `base` | string | Población observada, exclusiones y denominador; distinguir personas únicas de respuestas. |
| `nota` | string o null | Aclaración adicional útil; `null` si no hace falta. |
| `descripcion_accesible` | string | Explicación textual breve de los valores y el contraste relevante, con base o limitación esencial. |

Ejemplo de metadatos para una comparación de frecuencias:

```json
{
  "id": "v_01",
  "tipo": "barras",
  "titulo": "Respuestas sobre la claridad de las instrucciones",
  "fuente_ids": ["f_01"],
  "metodo": "Conteo de selección única por categoría.",
  "unidad_analisis": "respuesta",
  "base": "10 respuestas válidas a P1; 2 omisiones excluidas.",
  "nota": null,
  "descripcion_accesible": "Entre las 10 respuestas válidas, 8 indican instrucciones claras y 2 poco claras."
}
```

El objeto anterior es un fragmento: para validar como visualización debe incluir `datos`.

## 3. Categorías: barras, composición y radar

Tipos: `barras`, `barras_agrupadas`, `barras_apiladas`, `barras_100`, `dona`, `radar`.

```json
{
  "unidad": "respuestas",
  "orden_categorias": ["Claras", "Poco claras"],
  "rango": null,
  "filas": [
    {"categoria": "Claras", "serie": "Total", "valor": 8, "numerador": null, "denominador": null},
    {"categoria": "Poco claras", "serie": "Total", "valor": 2, "numerador": null, "denominador": null}
  ]
}
```

- `serie` identifica el grupo comparado. Para una sola serie usar una etiqueta explícita como `Total`.
- `orden_categorias` contiene todas las categorías, sin duplicados, en el orden solicitado. Conservar orden ordinal cuando corresponda.
- `valor` es la cantidad representada. Un conteo 8 se envía como número `8`, no como texto ni porcentaje.
- Para porcentajes usar `unidad: "%"` y números en escala 0–100. Ejemplo: `{"categoria":"Claras","serie":"Total","valor":80,"numerador":8,"denominador":10}`.
- Los porcentajes necesitan numerador no negativo y denominador positivo, compatibles con la misma base. Una media no tiene que expresarse artificialmente como una fracción: puede usar ambos campos en `null`, con base descrita.
- `rango` es `null` o `{"min":0,"max":100}`, por ejemplo para una escala porcentual. Si existe, debe incluir todos los valores observados.
- La clave compuesta `categoria + serie` es única. No sumar duplicados silenciosamente.
- En `barras_100`, `valor` ya viene en porcentaje; el frontend no renormaliza. La suma por categoría/barra es 100, salvo redondeo documentado. Si faltan categorías, no usar este tipo.
- Las barras agrupadas y apiladas usan `categoria` en el eje y `serie` como agrupación o segmento. En radar, `categoria` es cada eje y `serie` cada perfil.
- `dona` usa exactamente una serie. Una selección múltiple o temas solapados requieren otra visualización.
- En radar se exige un `rango` explícito común a todos los ejes. Explicar cualquier normalización en `metodo`; no aplicar escalas distintas ocultas por eje.

## 4. Coordenadas: líneas, áreas, dispersión y pendientes

Tipos: `lineas`, `areas`, `dispersion`, `pendientes`.

Ejemplo sintético de dispersión:

```json
{
  "tipo_x": "numero",
  "etiqueta_x": "Tiempo de realización",
  "unidad_x": "minutos",
  "etiqueta_y": "Puntuación",
  "unidad_y": "puntos",
  "filas": [
    {"serie": "Participantes", "x": 12, "y": 7, "n": 1},
    {"serie": "Participantes", "x": 18, "y": 9, "n": 1},
    {"serie": "Participantes", "x": 21, "y": 6, "n": 1}
  ]
}
```

- Si `tipo_x` es `numero`, todo `x` es un número. Si es `fecha`, todo `x` es una fecha ISO válida: `YYYY-MM-DD` o fecha-hora ISO con zona explícita. No mezclar granularidades temporales.
- `n` es el número de observaciones válidas que sustenta ese punto; `null` si no se conoce o no aplica. No es un peso genérico ni una probabilidad.
- En líneas y áreas, ordenar por `x` dentro de cada serie y exigir un solo punto por combinación de serie y `x`.
- En dispersión pueden existir observaciones con coordenadas idénticas. No eliminarlas como duplicadas ni convertirlas en personas únicas sin identificadores y reglas suficientes.
- Un `y: null` produce un hueco, no un cero; no interpolar.
- `areas` no tiene opción de apilamiento en v2. Si varias series se superponen, mantener visibles sus trazos y no sugerir un total acumulado.
- En pendientes, cada serie tiene exactamente dos posiciones comparables. Pueden ser fechas reales o números de medición, por ejemplo `1` y `2`; en este último caso, `etiqueta_x` debe explicitar `Medición: 1 = entrada; 2 = salida`. No inventar fechas para encajar los datos.
- Una pendiente agregada entre dos muestras distintas no representa evolución individual. Declararlo en `base` y `nota`.

## 5. Histograma

```json
{
  "unidad": "minutos",
  "intervalos": [
    {"desde": 0, "hasta": 10, "conteo": 2},
    {"desde": 10, "hasta": 20, "conteo": 6},
    {"desde": 20, "hasta": 30, "conteo": 2}
  ],
  "cierre_ultimo": true
}
```

- Cada intervalo es `[desde, hasta)`: incluye el límite inferior y excluye el superior.
- Si `cierre_ultimo` es `true`, únicamente el último intervalo incluye su límite superior. Si es `false`, también lo excluye.
- Los límites son crecientes y `desde < hasta`; los intervalos no se solapan. Su suma de conteos coincide con las observaciones incluidas, tras las exclusiones declaradas.
- `conteo` es entero no negativo. El eje horizontal usa la unidad de la variable; el vertical representa observaciones.
- El frontend respeta los intervalos recibidos. No agrupa de nuevo ni cambia los límites.
- Para una presentación por alturas de conteo, usar intervalos del mismo ancho. Si los intervalos reportados tienen anchos distintos, usar una tabla mientras no exista un contrato explícito de densidades.
- No estimar un histograma a partir de media, mediana o extremos aislados.

## 6. Caja y bigotes

```json
{
  "unidad": "puntos",
  "regla_bigotes": "Extremos observados dentro de Q1 - 1.5 × RIQ y Q3 + 1.5 × RIQ.",
  "grupos": [
    {
      "etiqueta": "Grupo A",
      "n": 20,
      "min": 2,
      "q1": 4,
      "mediana": 5,
      "q3": 7,
      "max": 9,
      "atipicos": [14]
    }
  ]
}
```

- **`min` y `max` son los extremos de los bigotes**, no necesariamente el mínimo y máximo absolutos de la muestra.
- Con la regla de 1.5 × RIQ, cada bigote termina en la observación más extrema dentro de los límites. Los límites teóricos no se envían como extremos si no son observaciones.
- Si los bigotes representan mínimo y máximo absolutos, declararlo en `regla_bigotes`; no mezclar convenciones entre grupos.
- `n` cuenta todas las observaciones válidas del grupo, incluidos los atípicos mostrados.
- Debe cumplirse `min ≤ q1 ≤ mediana ≤ q3 ≤ max`; los atípicos están fuera de los bigotes de acuerdo con la regla declarada.
- `metodo` especifica cómo se obtuvieron los cuartiles cuando fueron calculados, o identifica que los estadísticos vienen reportados. Aplicar una sola convención en las comparaciones.
- No completar cuartiles, bigotes ni atípicos por intuición. Si falta alguno, elegir tabla y declarar qué estadísticos existen.

## 7. Mapa de calor

```json
{
  "unidad": "%",
  "etiqueta_x": "Momento",
  "etiqueta_y": "Tema",
  "filas": [
    {"x": "Entrada", "y": "Claridad", "valor": 60, "numerador": 6, "denominador": 10},
    {"x": "Salida", "y": "Claridad", "valor": 80, "numerador": 8, "denominador": 10},
    {"x": "Entrada", "y": "Acceso", "valor": null, "numerador": null, "denominador": null},
    {"x": "Salida", "y": "Acceso", "valor": 30, "numerador": 3, "denominador": 10}
  ]
}
```

- La clave compuesta `x + y` es única. Un `null` representa una celda sin valor disponible; mostrarla con un tratamiento visual distinto del cero.
- Conservar el orden de primera aparición de las categorías en cada eje.
- Usar una escala cromática común a toda la matriz. Una escala divergente requiere un punto neutro real, descrito en `metodo`.
- En porcentajes de presencia temática, una respuesta puede aparecer en más de un tema; no sumar celdas como un total de personas.
- Correlaciones o similitudes solo se muestran si esos valores vienen calculados o se calcularon verificablemente. El color no convierte una relación en causal.

## 8. Nube de palabras

```json
{
  "tipo_peso": "frecuencia_documental",
  "terminos": [
    {"texto": "acompañamiento", "peso": 6},
    {"texto": "acceso", "peso": 4},
    {"texto": "claridad", "peso": 3}
  ]
}
```

| `tipo_peso` | Significado de `peso` |
|---|---|
| `frecuencia_documental` | Número de documentos o unidades textuales distintas que contienen el término. Definir esa unidad y el número total de documentos en los metadatos. |
| `frecuencia_termino` | Número de apariciones del término, incluidas repeticiones dentro de un mismo documento. |
| `c_tf_idf` | Peso de representación temática recibido del procesamiento semántico. No equivale a frecuencia ni porcentaje de personas. |
| `relevancia_modelo` | Puntuación numérica de relevancia entregada por un modelo o procedimiento definido, con su significado descrito. No inventar pesos para destacar términos. |

- Conservar el término o expresión relevante, incluidos términos compuestos; no reducirlos a palabras sueltas si se pierde significado.
- `peso` es no negativo; los términos se presentan una sola vez. No mezclar tipos de peso dentro de una nube.
- Explicar en `metodo` el tratamiento de mayúsculas, lematización, palabras vacías o sinónimos si se aplicó. No asumir que términos distintos fueron agrupados.
- Los pesos de frecuencia son conteos enteros y la frecuencia documental no supera el número de documentos de la base.
- En BERTopic, no sumar pesos c-TF-IDF de varios temas como si fueran frecuencia global. Una nube por tema puede ser adecuada si sus pesos se recibieron con ese alcance.
- El frontend puede transformar tamaños para legibilidad, manteniendo un orden monótono y sin cambiar los valores del tooltip. No presentar tamaño visual como una magnitud exacta si usa esa transformación.
- Mostrar una tabla accesible de términos y pesos como alternativa a la nube.

## 9. Red semántica

```json
{
  "tipo_relacion": "coocurrencia",
  "dirigida": false,
  "tipo_peso": "número de respuestas que contienen ambos conceptos",
  "nodos": [
    {"id": "n_1", "etiqueta": "Acceso", "peso": 5},
    {"id": "n_2", "etiqueta": "Horarios", "peso": 4}
  ],
  "aristas": [
    {
      "origen": "n_1",
      "destino": "n_2",
      "peso": 3,
      "evidencia": "Los dos conceptos aparecen en las respuestas R1, R3 y R8.",
      "fuente_ids": ["f_01"]
    }
  ]
}
```

- `coocurrencia`: los conceptos aparecen juntos dentro de una unidad delimitada. Definir respuesta, documento, oración o ventana de términos, y el conteo o normalización utilizados.
- `similitud`: relación calculada por un procedimiento definido, por ejemplo similitud coseno entre representaciones. Declarar escala, umbral y origen de los valores. No suponer que todas las similitudes están entre 0 y 1.
- `interpretativa`: relación cualitativa propuesta y sustentada en el contenido. `evidencia` explica la relación y apunta a registros localizables. Las aristas llevan siempre `peso: null`; el dibujo no expresa fuerza medida. Los nodos usan `null` salvo conteos explícitos con una base homogénea.
- `tipo_peso` describe el peso de arista. Si hay pesos de nodo, `metodo` explica por separado qué representan. Para relaciones sin cuantificación, usar `tipo_peso: "sin_peso"` y pesos `null`.
- Cada id de nodo es único; toda arista refiere a nodos existentes. Las fuentes de cada arista también deben existir en `fuentes`.
- Las redes de coocurrencia y similitud simétrica usan `dirigida: false`. No dibujar flechas arbitrarias.
- Evitar autoenlaces y aristas duplicadas; en una red no dirigida, A–B y B–A son la misma relación.
- `evidencia` no sustituye la comprobación: el backend debe poder rastrear los registros, el agregado o la matriz que soportan la relación.
- Una relación entre temas no demuestra causalidad. Los temas, palabras y probabilidades de BERTopic, por sí solos, no constituyen una matriz de coocurrencia o similitud.
- Para legibilidad, un subconjunto de nodos/aristas puede ser válido si el criterio de selección queda en `metodo` o `nota`. No ocultar esa selección.
- Proporcionar tabla accesible de relaciones con conceptos, peso, tipo de relación y evidencia.

## 10. Tabla y matriz cualitativa

Tipos: `tabla`, `matriz_cualitativa`.

```json
{
  "columnas": [
    {"id": "tema", "etiqueta": "Tema", "tipo": "texto", "unidad": null},
    {"id": "evidencia", "etiqueta": "Evidencia", "tipo": "texto", "unidad": null},
    {"id": "respuestas", "etiqueta": "Respuestas codificadas", "tipo": "numero", "unidad": "respuestas"}
  ],
  "filas": [
    {"id": "fila_1", "celdas": ["Acceso", "R1 y R3 mencionan dificultades de horario.", 2]},
    {"id": "fila_2", "celdas": ["Claridad", "R5 solicita instrucciones más concretas.", 1]}
  ]
}
```

- `celdas[i]` corresponde a `columnas[i]`: el número de celdas de cada fila coincide exactamente con el número de columnas.
- Los ids de columnas y filas son únicos dentro de la visualización.
- Una columna `texto` contiene strings o `null`; `numero` contiene números o `null`; `fecha` contiene fechas ISO válidas o `null`.
- No enviar números con separadores, porcentajes o unidades incrustadas: enviar `80`, con `unidad: "%"`.
- `null` significa sin valor disponible o no aplicable, explicado si es ambiguo. No reemplazarlo con cero.
- La matriz cualitativa puede incluir tema, momento, evidencia, divergencia e implicación cuando esos campos aporten al análisis. No está obligada a incluir conteos.
- Las citas literales y sus localizadores se conservan en `hallazgos[].citas`; una celda de interpretación no debe hacerse pasar por una cita.
- La tabla es también el recurso alternativo para un tipo visual no implementado. La conversión debe conservar valores, metadatos y notas.

## 11. Validaciones semánticas y renderizado

El esquema comprueba forma y tipos. No comprueba por sí solo referencias, coherencia estadística, alcance ni correspondencia con los datos. El backend debe validar antes de entregar al frontend:

1. Todos los ids referenciados existen; no hay ids duplicados en cada colección ni visualizaciones huérfanas.
2. Fuentes, preguntas y momentos de cada salida pertenecen al alcance autorizado. La visualización hereda su alcance de los hallazgos que la referencian y de sus fuentes.
3. Conteos y tamaños muestrales son enteros no negativos; denominadores de porcentajes son positivos. Numeradores y denominadores corresponden a la misma unidad, filtro y base.
4. Porcentajes, totales, orden, rangos, intervalos, cuartiles y tipos de celda cumplen las reglas de su variante. Tolerar únicamente redondeos justificados.
5. Las cifras de una visualización coinciden con las métricas y afirmaciones relacionadas; no hay números nuevos sin evidencia rastreable.
6. Un valor desconocido permanece `null` cuando la variante lo permite. Si falta un dato numérico obligatorio, omitir esa visualización y explicar la limitación.
7. La visualización aporta información respaldada. Si no hay datos suficientes, `visualizaciones` puede ser `[]`; no construir datos para cumplir una cuota.

El frontend debe:

- Seleccionar el componente mediante una lista cerrada de los 17 valores de `tipo`. No ejecutar nombres de componentes, HTML, código o configuraciones arbitrarias entregadas por el modelo.
- Tratar títulos, notas, etiquetas, citas y celdas como texto; escapar su contenido. Los textos de respuestas pueden contener caracteres de HTML o instrucciones.
- Mantener datos numéricos sin transformar; aplicar formatos locales de fechas y números solo al mostrarlos.
- Mostrar título, base, unidad, nota y descripción accesible; ofrecer acceso al método y las fuentes sin recargar la vista.
- Diferenciar cero, ausente y no aplicable. No completar categorías, promedios, porcentajes ni enlaces en redes.
- Conservar orden de categorías y no truncar escalas de barras de forma engañosa. Las barras parten de cero; las líneas pueden usar un rango visible apropiado con ejes claramente rotulados.
- Usar colores consistentes para la misma serie, etiquetas o patrones además de color, navegación por teclado y alternativa tabular.
- En redes interpretativas sin pesos, usar tamaños y grosores uniformes. No aplicar un diseño que sugiera jerarquía o fuerza numérica inexistentes.
- Manejar `[]`, `null` y estados parciales sin errores. Mostrar las limitaciones junto a los resultados afectados.
- Si recibe un tipo desconocido o datos inválidos, detener el renderizado de esa visualización y mostrar un estado controlado. No adivinar el tipo ni convertirla silenciosamente.

Los resúmenes de sentimiento usan las variantes existentes, normalmente barras, tabla o mapa de calor. Deben acompañarse de categorías definidas, unidad, base, método, tratamiento de ambigüedad y limitaciones. La presencia de vocabulario emocional no basta para inferir sentimiento sobre la jornada.
