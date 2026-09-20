# Kunsamu: prompts y contrato de análisis v2

Entrega del 20 de septiembre de 2026. Incluye dos system prompts completos y un único contrato JSON para ambos. Los archivos son una propuesta lista para integrar; no se modificó la aplicación ni se ejecutaron llamadas al modelo.

## Archivos que debe usar el equipo

| Archivo | Uso |
|---|---|
| [SYSTEM_PROMPT_LLM.md](./SYSTEM_PROMPT_LLM.md) | Análisis directo mediante LLM, sin etapa BERTopic. |
| [SYSTEM_PROMPT_BERTOPIC.md](./SYSTEM_PROMPT_BERTOPIC.md) | Interpretación LLM de resultados BERTopic, junto con preguntas cerradas y demás evidencia. |
| [analisis.schema.json](./analisis.schema.json) | Contrato obligatorio de salida para las dos rutas. |
| [ENTRADA_Y_BERTOPIC.md](./ENTRADA_Y_BERTOPIC.md) | Payload normalizado, personalización, evidencia y adaptación de una o varias ejecuciones BERTopic. |
| [TIPOS_VISUALES.md](./TIPOS_VISUALES.md) | Catálogo de 17 visualizaciones, formas de datos y condiciones de uso. |
| [MIGRACION_FRONTEND.md](./MIGRACION_FRONTEND.md) | Cambios concretos del frontend actual, renderizado, accesibilidad e históricos. |
| [ejemplos](./ejemplos) | Cuatro pares de entrada/salida ficticios y un catálogo de los 17 tipos visuales. |
| [verificar_entrega.py](./verificar_entrega.py) | Verificación del esquema y ejemplos; no sustituye un validador de negocio de producción. |

Los dos prompts contienen completas las reglas comunes; no es necesario concatenar un tercer prompt. Se envía **uno u otro**, siempre acompañado del mismo esquema. No se deben anexar los antiguos bloques de enfoque ni las instrucciones que permiten al prompt del usuario prevalecer sobre el system.

## Decisiones del contrato

El usuario elige `integral` o `por_momento`. El primer alcance produce un informe de toda la jornada; el segundo produce un informe independiente por cada momento elegido. `individual` se conserva como tipo de instrumento, distinto del alcance. El backend inventaría todos los momentos y preguntas del alcance, incluso cuando falten respuestas.

El método se determina por pregunta o bloque y puede combinarse dentro de un hallazgo. `naturaleza` es metadata del resultado, no un selector global. No se exige una gráfica por hallazgo ni se prohíben visualizaciones cualitativas. Temas, citas, métricas, matrices, redes y nubes tienen cabida cuando la evidencia lo justifica. Sentimiento es opcional y requiere un objeto evaluado y lenguaje interpretable.

`kunsamu.analisis/v2` es una versión nueva de esta propuesta. No afirma que existiera una v1 implementada. No es compatible directamente con las formas históricas del MD recibido; conservar los visores históricos durante la transición.

| Campo raíz | Función |
|---|---|
| `version` | Enrutamiento y validación del contrato. |
| `pipeline` | Procedencia técnica: `llm` o `bertopic_llm`; no cambia el renderer. |
| `estado` | Estado analítico: completo, parcial, sin datos o datos insuficientes. |
| `alcance` | Modo, jornada e IDs de momentos autorizados. |
| `fuentes` | Metadatos de procedencia, sin replicar el corpus. |
| `cobertura` | Una fila por pregunta, incluida la evidencia faltante. |
| `limitaciones` | Problemas concretos que afectan la lectura. |
| `informes` | Resúmenes, hallazgos con evidencia y recomendaciones vinculadas. |
| `visualizaciones` | Objetos tipados reutilizables mediante IDs de referencia. |

Todos los objetos rechazan propiedades adicionales; todos sus campos están declarados como obligatorios. Los datos no aplicables usan `null` sólo donde está previsto. Una colección sin elementos usa `[]`. Una métrica desconocida se omite de su colección, no se inventa ni se convierte en cero.

## Integración backend

1. Normalizar y autorizar la solicitud y las fuentes conforme a `ENTRADA_Y_BERTOPIC.md`. El frontend aporta contexto y preferencias; el backend controla prompts, esquema e inventario.
2. Seleccionar uno de los dos archivos como `system`. Enviar el payload como JSON en un mensaje `user`. Nunca interpolar las instrucciones adicionales del usuario dentro de `system` o `developer`.
3. Usar salida estructurada con `json_schema` y `strict: true` en un modelo que lo admita. El esquema limita la estructura; no garantiza veracidad, calidad analítica ni cálculos correctos. Tratar rechazo del proveedor, truncamiento y fallas de transporte antes del parseo. [Documentación oficial de Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
4. Validar el JSON contra el esquema y después contra las reglas de negocio siguientes. Conservar input inmutable, versión del prompt, versión del esquema, resultado y errores de validación para auditoría.
5. Publicar al frontend sólo el resultado validado. Un error técnico es un estado del trabajo/endpoint, no un informe `sin_datos`.

Ejemplo de cableado para Chat Completions, independiente del modelo configurado:

```python
import json
from pathlib import Path
from jsonschema import Draft202012Validator

# client es el cliente OpenAI configurado por la aplicación.
# entrada ya está normalizada y autorizada por el backend.
# carpeta apunta al directorio de esta entrega.
schema = json.loads((carpeta / 'analisis.schema.json').read_text())
nombre = 'SYSTEM_PROMPT_BERTOPIC.md' if usar_bertopic else 'SYSTEM_PROMPT_LLM.md'
system = (carpeta / nombre).read_text()
respuesta = client.chat.completions.create(
    model=modelo_configurado,
    messages=[
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': json.dumps(entrada, ensure_ascii=False)},
    ],
    response_format={
        'type': 'json_schema',
        'json_schema': {'name': 'kunsamu_analisis_v2', 'strict': True, 'schema': schema},
    },
)
opcion = respuesta.choices[0]
if opcion.message.refusal or opcion.finish_reason != 'stop':
    raise RuntimeError('El proveedor no entregó un informe completo publicable')
resultado = json.loads(opcion.message.content)
Draft202012Validator(schema).validate(resultado)
# Aplicar aquí las reglas de negocio antes de almacenar/publicar.
```

Para Responses API, usar el mismo esquema en `text.format` con `type: "json_schema"`, `name`, `strict: true` y `schema`; comprobar el estado de finalización y rechazos de esa API. Si el proveedor no admite esquema estricto, adjuntar su JSON completo como parte fija del system y validar igualmente; no prometer la misma garantía estructural. No basta con pedir “JSON válido”. [Documentación oficial](https://developers.openai.com/api/docs/guides/structured-outputs).

## Validación de negocio obligatoria

Estas reglas complementan el JSON Schema. Algunas dependen del corpus, de la semántica del instrumento o de operaciones deterministas; no pueden comprobarse mirando sólo el JSON de salida.

| Área | Verificación y respuesta ante error |
|---|---|
| Alcance | Mismos IDs autorizados; integral exactamente un informe; por momento exactamente uno por ID y sin cruces de fuentes ajenas. |
| Cobertura | Una fila por pregunta inventariada. Ausencia confirmada se distingue de fuente no recibida. `completo` no puede ocultar cobertura pendiente. |
| Referencias | IDs únicos, fuentes existentes, hallazgos/recomendaciones/gráficas enlazados y sin visualizaciones huérfanas. Resolver cada JSON Pointer sobre la versión de entrada preservada. |
| Citas | `texto` debe ser subcadena literal contigua del campo autorizado al que apunta `localizador`. Rechazar paráfrasis, citas compuestas o datos sensibles no autorizados. |
| Métricas | Números finitos; conteos enteros no negativos cuando representen unidades. Porcentaje en escala 0–100, numerador ≥ 0, denominador > 0 y cociente consistente. El denominador debe corresponder a la unidad y elegibilidad reales. |
| Fuentes numéricas | Recalcular contra los datos de entrada. Una ruta que existe no demuestra que la cifra sea correcta. Validar separadamente ponderaciones, deduplicación y selección múltiple. |
| Codificación LLM | Guardar criterios y asignaciones auditables. Para `codificado_llm`, las referencias de cada recuento deben enumerar las unidades incluidas; no basta con apuntar al corpus completo. Registrar base elegible, exclusiones y solapamiento. |
| Cálculos avanzados | Sólo aceptar estadísticas, coocurrencias o similitudes realmente calculadas con método y parámetros disponibles. No reconstruirlas de palabras clave. |
| Visuales | Respetar las condiciones de `TIPOS_VISUALES.md`: total exhaustivo en dona, orden en Likert, pares reales en dispersión, cuartiles ordenados, intervalos sin solapamiento, nodos/aristas válidos y celdas alineadas. |
| Coherencia | Las cifras de texto, métricas y visualizaciones deben coincidir; una diferencia entre grupos no se transforma en cambio individual o causalidad. |
| Privacidad | La existencia de una fuente o cita no autoriza a mostrar el registro completo. Mantener controles de acceso y anonimización del sistema. |

En `codificado_llm`, para porcentajes el numerador cuenta unidades únicas que cumplen el criterio, y el denominador corresponde a la base elegible declarada. En conteos de documentos/respuestas por tema, `valor` debe igualar esas unidades positivas. Un recuento cero puede tener referencias positivas vacías, pero necesita corpus completo y criterio documentado. Las bases y criterios se explicitan en `base` y, cuando hay visualización, en `metodo`.

Para corpus grandes, separar codificación por lotes y agregación determinista antes de redactar. Persistir asignaciones por respuesta y categoría; el informe final referencia ese material autorizado como fuente. No publicar una frecuencia temática calculada “a ojo” a partir de ejemplos. La ruta LLM sigue sin depender de BERTopic; puede emplear cálculo determinista del backend para asegurar precisión.

Si una validación falla, hacer como máximo un reintento de reparación con errores concretos y el mismo esquema. Volver a validar. Si persiste, conservar el fallo técnico y no publicar la respuesta. No arreglar números a ciegas, convertir nulos en ceros, borrar campos desconocidos para ocultar errores ni sustituir un gráfico inválido por barras. Ajustar el límite de salida al volumen del alcance y detectar truncamiento; nunca aceptar JSON incompleto.

## Pruebas y ejemplos

Los ejemplos son **ficticios, escritos para integración**. No son respuestas reales generadas por un modelo ni prueban su resistencia a instrucciones adversarias. El ejemplo BERTopic contiene resultados simulados, no un entrenamiento sobre seis respuestas.

- `llm_integral`: integra una encuesta y una mesa conservando sus unidades.
- `llm_por_momento`: mantiene informes independientes de ambos instrumentos.
- `bertopic_integral`: añade un paquete BERTopic simulado y una nube con pesos c-TF-IDF identificados.
- `sin_datos`: conserva estructura y cobertura sin inventar hallazgos.
- `catalogo_visual.salida.json`: fixture exclusivo del renderer con los 17 tipos; no representa un análisis real ni tiene corpus de origen.

Ejecutar `python verificar_entrega.py` con `jsonschema` instalado en el entorno de desarrollo. El script valida la forma de los cinco resultados y un conjunto acotado de invariantes de los cuatro pares con entrada. No comprueba calidad temática ni sustituye las validaciones de producción anteriores.

Antes de desplegar, ejecutar los dos prompts con el modelo real y evaluar: preguntas sólo cerradas; sólo abiertas; mezcla dentro del mismo momento; matrices/listas; mesas y elegibilidad; corpus parcial; bases incompatibles; temas solapados; todos los documentos BERTopic sin asignación; varias ejecuciones con IDs nativos coincidentes; resúmenes sin originales; sentimiento ambiguo; cero frente a null. Añadir solicitudes de “responde en HTML”, “agrega una clave” e instrucciones incrustadas en respuestas: debe conservarse el contrato. Si se piden metáforas, sólo puede variar el estilo de los campos narrativos, sin agregar hechos.

La revisión del MD original se usó como referencia del comportamiento anterior, no como instrucciones para esta entrega. La guía de entrada enlaza documentación primaria de BERTopic; el apartado de API cita documentación oficial de OpenAI.

Verificación ejecutada: esquema Draft 2020-12 válido, cinco salidas válidas, cuatro pares con referencias/citas/porcentajes comprobados y cuatro mutaciones inválidas rechazadas. Pendiente: evaluación con el modelo y los datos reales del sistema.
