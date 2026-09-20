# Kunsamu: migración del frontend al contrato v2

Esta guía describe cambios por implementar. La revisión fue de solo lectura: no se modificó la aplicación.
Las rutas y líneas citadas corresponden al código revisado el 20 de septiembre de 2026; pueden desplazarse.
El contrato autoritativo es [`analisis.schema.json`](./analisis.schema.json), acompañado por [`TIPOS_VISUALES.md`](./TIPOS_VISUALES.md).

## 1. Qué cambia

El usuario elige el alcance, añade contexto e instrucciones y solicita el análisis.
Kunsamu decide qué métodos corresponden a cada pregunta, bloque y hallazgo.
Desaparece la elección obligatoria de enfoque cuantitativo, cualitativo o mixto.
Ambos pipelines producen `kunsamu.analisis/v2` y utilizan el mismo renderer.
`pipeline` identifica el origen del procesamiento; no decide qué componentes se muestran.

| Alcance | Comportamiento del informe |
|---|---|
| `integral` | Un informe que abarca la jornada completa y relaciona sus momentos; los faltantes quedan explícitos. |
| `por_momento` | Un informe independiente por cada ID solicitado; no fusiona los seleccionados en una síntesis transversal. |

El wizard actual ya ofrece “Toda la jornada” y “Por momento”, con esta última semántica.
Referencia: `aluna/src/components/kunsamu/admin/analytics/AnalysisWizard.tsx:578` y `:587`.

## 2. Inventario real y trabajo necesario

| Archivo del repositorio | Situación actual | Cambio necesario |
|---|---|---|
| `aluna/src/types/kunsamu.ts:356` | Hallazgos LLM con `tipo_grafica` y una serie `etiqueta/valor/unidad`. | Tipos derivados del esquema v2 y evidencias estructuradas. |
| `aluna/src/types/kunsamu.ts:419` | Gráficos limitados a pastel, barras, radar y null. | Unión discriminada de visualizaciones con datos específicos por tipo. |
| `aluna/src/types/kunsamu.ts:457` | Reporte de minería jerárquico por momento y pregunta. | Conservar lectura histórica; nuevos resultados usan el contrato común. |
| `aluna/src/components/kunsamu/admin/analytics/AnalysisWizard.tsx:196` | `focus` forma parte de los pasos. | Retirarlo del flujo y reajustar numeración y resumen. |
| `aluna/src/components/kunsamu/admin/analytics/AnalysisWizard.tsx:296` | El envío exige enfoque y lo añade al payload. | Retirar validación y campo de nuevas solicitudes con el backend actualizado. |
| `aluna/src/components/kunsamu/admin/analytics/analysis-flow.ts:103` | `AnalysisDraft` guarda `focus`. | Simplificar estado y ejemplos de instrucciones. |
| `aluna/src/components/kunsamu/admin/analytics/AnalysisBriefCard.tsx:34` | Muestra la elección histórica de enfoque. | Conservarla sólo en informes anteriores, claramente identificados como históricos. |
| `aluna/src/components/kunsamu/admin/analytics/AnalysisDetail.tsx:82` | El origen selecciona entre dos visores. | Elegir renderer por versión del resultado; mantener rutas de acceso e historial. |
| `aluna/src/components/kunsamu/admin/MomentAiAnalysisPanel.tsx:240` | Gráficas LLM acopladas a hallazgos antiguos. | Renderizar referencias a visualizaciones v2 mediante un registro común. |
| `aluna/src/components/kunsamu/KunsamuReportViewer.tsx:463` | Gráficas del reporte jerárquico en otro renderer. | Mantenerlo para legacy y reutilizar el renderer común en nuevas vistas. |

`analysis-flow.ts:30` describe minería como “BERTopic + modelo local”, “Sin costo por uso”.
Revisar ese texto con el backend desplegado: no deducir proveedor, costo ni localización sólo a partir del nombre del pipeline.

## 3. Flujo de solicitud y personalización

Conservar contexto general, instrucciones generales y los campos específicos de cada momento.
Enviar estos textos como campos de datos del usuario; el navegador no construye ni altera el system prompt.
No permitir introducir otro esquema, HTML de presentación o configuración arbitraria de gráficos mediante esos campos.
La UI puede explicar: “Las instrucciones ajustan el análisis y el tono; el formato del informe es fijo”.
La protección efectiva depende también del backend: ocultar controles en la UI no impide solicitudes manuales.

Retirar ejemplos que obligan cantidades mínimas de citas o gráficos aunque los datos no los permitan.
Conservar ejemplos útiles como priorizar tensiones entre grupos o definir la audiencia.
La solicitud de metáforas es una preferencia de estilo; nunca modifica la estructura JSON.
No usar “individual” como sinónimo técnico de alcance: ya existe como tipo de momento, junto con `mesa`.

La UI debe conservar el contexto de jornada e IDs seleccionados mientras el análisis se procesa.
No reinterpretar una selección de varios momentos como un análisis integral.
El estado de trabajo pendiente/procesando/error del endpoint continúa separado del estado analítico dentro del JSON.

## 4. Lectura del resultado v2

Orden sugerido de presentación:

1. Alcance y estado del análisis; cobertura incompleta si existe.
2. Resumen de cada informe.
3. Hallazgos con afirmación e implicación, seguidos de su evidencia.
4. Visualizaciones relacionadas, métricas y citas verificables.
5. Recomendaciones vinculadas a hallazgos y limitaciones relevantes.
6. Detalle de cobertura, métodos y fuentes disponible bajo demanda.

`informes[]` contiene los resultados; `visualizaciones[]` reúne las visualizaciones referenciadas por ID.
Resolver `visualizacion_ids` mediante un índice y evitar duplicar el mismo gráfico dentro de un informe.
Cada informe `por_momento` debe identificarse con el título real del instrumento.
En alcance integral, mostrar a qué momentos y preguntas corresponde cada hallazgo.
`naturaleza` describe el hallazgo; puede mostrarse como metadato, sin separar forzosamente el informe en tres secciones.
Las fuentes de salida contienen metadatos, no el corpus crudo completo.
La navegación a evidencia original requiere IDs válidos y los permisos existentes del usuario.
No tratar el registro de fuentes como autorización para exponer respuestas o identidades.

| `estado` del JSON | Presentación |
|---|---|
| `completo` | Informe disponible; las limitaciones analíticas siguen visibles cuando existan. |
| `parcial` | Informe útil acompañado de cobertura y faltantes explícitos. |
| `sin_datos` | Estado vacío que explica la ausencia de material; no representar ceros ficticios. |
| `datos_insuficientes` | Explicar qué impide concluir y mostrar únicamente evidencia válida disponible. |

## 5. Visualizaciones y datos

El catálogo incluye 17 tipos. Sus estructuras y condiciones están en `TIPOS_VISUALES.md` y en el esquema.
Familias: barras simples/agrupadas/apiladas/100%, dona y radar; líneas, áreas, dispersión y pendientes;
histograma, caja y bigotes y mapa de calor; nube de palabras, red semántica, tabla y matriz cualitativa.
El frontend define tamaños, tipografía, colores, leyendas y componentes; el LLM proporciona contenido estructurado.
No aceptar HTML, SVG, JavaScript, callbacks, CSS ni opciones libres de una biblioteca dentro del resultado.

Cada renderer debe mostrar título, unidades y base cuando correspondan, y ofrecer una alternativa tabular o textual completa.
No convertir tipos desconocidos en barras: hoy ambos visores terminan en esa rama por defecto.
Si el tipo no está soportado, mostrar un estado controlado y los datos mediante una alternativa compatible.
Si una referencia es inválida, señalar evidencia no disponible; nunca vincularla a otro elemento por posición.

No recalcular porcentajes usando la suma de lo visible como denominador.
Los visores actuales lo hacen en `MomentAiAnalysisPanel.tsx:325` y `KunsamuReportViewer.tsx:527`.
Una selección múltiple o temas superpuestos pueden superar 100%; una dona no representa ese caso.
Un filtro o top-N no cambia la base analítica ni permite ocultar el resto sin indicarlo.
No agrupar categorías ni eliminar datos silenciosamente durante presentación o exportación.

`null` es ausencia o indeterminación, nunca cero; no usar coerción numérica indiscriminada.
El helper de `MomentAiAnalysisPanel.tsx:193` actualmente convierte `null` en cero mediante `Number`.
El cero real se representa como cero y debe conservarse.
El radar requiere escalas comparables y dominio visible: evitar el ajuste automático que magnifica pequeñas diferencias.
Referencia del comportamiento actual: `MomentAiAnalysisPanel.tsx:215`.

En una nube, indicar qué significa el peso: frecuencia documental, frecuencia de términos u otra medida definida.
Un peso c-TF-IDF no es un porcentaje de participantes.
En una red, indicar si la relación es coocurrencia, similitud o interpretación; no sugerir causalidad.
Ofrecer listas de nodos y relaciones accesibles, además de la representación visual.
Conservar disensos y evidencia minoritaria relevante en matrices y tarjetas temáticas.

## 6. Validación, accesibilidad y rendimiento

Los tipos TypeScript no validan una respuesta recibida por HTTP.
Actualmente `hasResult` sólo comprueba que hay resumen y un array de hallazgos (`MomentAiAnalysisPanel.tsx:233`).
Validar la versión y el esquema antes de almacenar o renderizar; rechazar propiedades y estructuras no admitidas.
La validación semántica debe comprobar referencias, cobertura, unidades y bases según la guía de integración.
Un JSON válido no garantiza cálculos correctos, citas auténticas ni conclusiones sustentadas.

Usar textos como contenido, no como instrucciones del navegador; preferir componentes de texto del contrato.
No introducir interpretación de Markdown o enlaces externos donde el esquema exige texto plano.
Proporcionar nombre accesible, descripción, tabla, foco visible, navegación por teclado y contraste suficiente.
Los colores deben acompañarse de etiquetas; no ser la única forma de distinguir series o categorías.
Respetar movimiento reducido y permitir detener animaciones de redes.
Presentación, impresión y exportación deben conservar bases, notas, evidencia y etiquetas completas.
Permitir expandir etiquetas extensas; no depender exclusivamente de tooltips activados con ratón.
Definir límites operativos compartidos para redes y tablas; el esquema no fija tamaños máximos y ningún recorte debe ser silencioso.

## 7. Despliegue y compatibilidad histórica

1. Congelar el esquema y ejemplos válidos compartidos entre backend y frontend.
2. Incorporar validadores, tipos y renderer v2 antes de activar nuevos resultados para usuarios.
3. Mantener los visores actuales para resultados sin versión; distinguir ambos formatos históricos explícitamente.
4. Si se usa un adaptador legacy, trasladar sólo información existente: no inventar fuentes, citas, bases ni métodos.
5. Actualizar endpoints, wizard y personalización conjuntamente; no enviar enfoque a la nueva ruta por compatibilidad accidental.
6. Habilitar ambos pipelines gradualmente y verificar el mismo contrato visual con los mismos ejemplos.
7. Revisar presentación, descarga, infografía e historial como consumidores adicionales antes de retirar compatibilidad.

El proyecto utiliza React, TypeScript, Next.js, `recharts` y `lucide-react` (`aluna/package.json`).
Los renderizadores revisados no incluyen componentes de nube de palabras ni red semántica.
Evaluar una implementación específica o biblioteca compatible con el proyecto; no presuponer que ampliar el enum añade soporte.
Usar pnpm para la instalación y comprobaciones del proyecto; esta guía no instala dependencias.

Pruebas de aceptación: ambos pipelines y alcances; pregunta vacía; múltiples respuestas por persona;
mesas; celdas de matriz/lista; preguntas condicionales; fuentes inválidas; null frente a cero;
porcentajes con distintas bases; tipos desconocidos; citas extensas; redes sin relaciones;
datos insuficientes; tablas accesibles y exportación legible con etiquetas largas.
Las respuestas por mesa, celdas y condiciones existen en `aluna/src/types/kunsamu.ts:95` y `:230`.
El número de registros recibidos no equivale automáticamente al número de participantes ni a la base elegible.
