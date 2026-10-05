# Integración frontend — System prompts versionados (HU-92)

Los system prompts de la analítica ya no están en el código: viven en una tabla, con versiones.
Cada flujo usa **la versión activa de su tipo**, y desde esta pantalla se elige cuál.

## Tipos

| `tipo` | Lo usa |
|---|---|
| `analisis_llm` | Análisis v2, pipeline `llm` (análisis de momento, de jornada y `analisis-v2` con `llm`) |
| `analisis_bertopic` | Análisis v2, pipeline `bertopic_llm` (reportes y `analisis-v2` con `bertopic_llm`) |
| `infografia` | El prompt base de las láminas de infografía |
| `presentacion` | La presentación HTML de un reporte |
| `presentacion_diseno` | La diagramación de la presentación (colores, tipografía, plantillas) |
| `sugerencias` | Las sugerencias del asistente de análisis guiado |
| `resumen_presentacion` | El resumen de un análisis para presentación en diapositivas (HU-99) |

## Reglas

- **Una versión activa por tipo.** Activar una desactiva la anterior del mismo tipo; los demás
  tipos no se tocan. No existe "desactivar": para volver atrás se activa una versión anterior.
- **Una versión que estuvo activa alguna vez es inmutable**: no se edita ni se borra (`409`). Para
  cambiar un prompt se crea una versión nueva. Un análisis viejo dice "se generó con
  `analisis_llm#3`" y eso tiene que seguir significando lo mismo.
- **Un borrador** (creado y nunca activado) sí se puede editar y borrar.
- La versión la numera el backend, consecutiva por tipo.
- Leer: cualquier admin. Crear, editar, borrar y activar: solo admin completo (`403` para un
  usuario de dependencia).

## Endpoints

Base: `/api/admin/system-prompts/`

```
GET  ?tipo=analisis_llm            versiones de un tipo, sin `contenido` (trae `largo`)
GET  activos/                      la activa de cada tipo, con `contenido`
GET  {id}/                         una versión completa
POST                               crear la versión siguiente
PATCH {id}/                        editar un borrador (contenido, etiqueta, notas)
DELETE {id}/                       borrar un borrador
POST {id}/activar/                 dejarla activa
```

Crear (opcionalmente activándola en el mismo paso):

```json
POST /api/admin/system-prompts/
{ "tipo": "analisis_llm",
  "contenido": "…texto completo del prompt…",
  "etiqueta": "v2.3 — más énfasis en recomendaciones",
  "notas": "Qué cambia respecto de la anterior y por qué",
  "activar": false }
```

Una versión:

```json
{ "id": 9, "tipo": "analisis_llm", "tipo_nombre": "Análisis — pipeline LLM",
  "version": 2, "referencia": "analisis_llm#2",
  "etiqueta": "v2.3 — más énfasis en recomendaciones", "notas": "…",
  "contenido": "…",
  "activo": false, "inmutable": false,
  "activado_en": null, "activado_por": null,
  "creado_por": 3, "creado_en": "2026-10-05T14:02:11Z" }
```

## Pantalla sugerida

1. Una pestaña o selector por tipo, con la lista de versiones (`?tipo=`) y la activa destacada.
2. **Nueva versión** abre un editor precargado con el `contenido` de la activa: lo normal es partir
   de ella y cambiar algo, no escribir desde cero.
3. Un borrador se guarda (`PATCH`) cuantas veces haga falta; **Activar** pide confirmación, porque
   desde ese momento queda fija y es la que usan todos los análisis nuevos de ese tipo.
4. En una versión con `inmutable: true`, el editor es de solo lectura y el único botón es
   **Activar** (para volver a ella).

## Trazabilidad

Cada corrida guarda con qué versión se generó, en `version_prompt` (ej. `"analisis_llm#2"`):

| Dónde | Campo |
|---|---|
| Reportes, análisis de momento/jornada, `analisis-v2` | `version_prompt` |
| Infografías | `version_prompt` |
| Diseño de presentación | `version_prompt` |
| Presentación HTML de un reporte | `presentacion_version_prompt` |

Los registros anteriores a HU-92 tienen el valor viejo (`"v2.2"`) o vacío.

## Lo que no se puede cambiar desde acá

- **La regla de datos de la infografía** ("usa exclusivamente las cifras del JSON…") va siempre
  al final del prompt de imagen y no forma parte de ninguna versión: es la protección contra
  cifras inventadas en una lámina institucional y no debe depender de lo que diga un prompt.
- **La estructura de las tres láminas** (qué va en cada una) sigue en el código.
- **El esquema JSON de salida del análisis** (`kunsamu.analisis/v2`): el prompt puede cambiar,
  el contrato no. Un prompt que pida otra forma de salida produce análisis que no pasan la
  validación.
- Los prompts de **extracción de documentos y de transcripciones** no son parte de la analítica y
  siguen en el código.
