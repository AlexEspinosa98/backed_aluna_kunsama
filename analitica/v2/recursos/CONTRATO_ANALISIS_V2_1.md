# Contrato de análisis `kunsamu.analisis/v2.1` — colores con significado y tres tipos visuales más

**Módulo:** Kunsamu (backend Django) · **Sustituye a:** `analisis.schema.json` de la entrega del 20-09-2026 · **Fecha:** 2026-10-04

Adjunto: `analisis.schema.json` (v2.1, listo para `json_schema` + `strict: true`) y
`catalogo_visual.v2_1.json` (ejemplo válido con los 20 tipos y colores declarados).

## Por qué

1. Hay gráficas donde el color **es** dato (semáforo, Sí/No, escala Likert, sectores de actores, un
   color por tema). Hasta ahora el frontend ponía su paleta por posición y el significado se perdía.
   El modelo, que sí sabe qué significa cada serie, ahora puede declararlo.
2. Faltaban tipos para lo que más pide el análisis cualitativo mixto: **grafos** de actores con
   grupos y relaciones rotuladas, **flujos** (de qué actor sale cada propuesta y a qué tema llega) y
   **jerarquías** de temas con peso.

El frontend ya lee v2.1 (y sigue leyendo v2, así que los análisis guardados no se tocan). Un color
inválido no tumba nada: se ignora con aviso y se usa la paleta.

## Qué cambia en el esquema

- `version` pasa a `"kunsamu.analisis/v2.1"`.
- **Todos los campos nuevos son obligatorios para el modelo** (modo estricto) y "vacío" se expresa
  con `null` o `[]`, igual que el resto del contrato.
- Color: siempre `#rrggbb` (seis dígitos). Definido en `$defs.color` con `pattern`.

### Colores por tipo

| Tipo | Campo nuevo | Cuándo usarlo |
|---|---|---|
| `barras_agrupadas`, `barras_apiladas`, `barras_100`, `radar` | `datos.colores_series: [{serie, color}]` | Cada serie tiene color propio (Sí/No, Likert, grupos). |
| `barras`, `dona` (una sola serie) | `datos.colores_categorias: [{categoria, color}]` | Cada categoría tiene color propio (semáforo, estados). |
| `lineas`, `areas`, `dispersion`, `pendientes` | `datos.colores_series: [{serie, color}]` | Igual que arriba. |
| `histograma` | `datos.color: color \| null` | Rara vez; `null` normalmente. |
| `caja_bigotes` | `grupos[].color: color \| null` | Grupos con identidad propia. |
| `mapa_calor` | `datos.escala: {color_min, color_medio \| null, color_max} \| null` | Con `color_medio` la escala es divergente (el medio cae en cero si el rango lo cruza). |
| `nube_palabras` | `datos.colores_terminos: [{texto, color}]` | Un color por tema al que pertenece el término. |
| `red_semantica`, `grafo` | `datos.grupos: [{id, etiqueta, color \| null}]`, `nodos[].grupo`, `nodos[].color`, `aristas[].etiqueta` | Ver abajo. |
| `sankey`, `treemap` | `nodos[].color`, `flujos[].color` | Ver abajo. |

Regla para el prompt: **declarar color sólo cuando tiene significado**. Si no lo tiene, lista vacía
o `null`: el visor pone una paleta accesible y consistente con el resto de Kunsamu. Cuando se declara,
mantener el mismo color para el mismo concepto en todas las visualizaciones del informe (Sí siempre
verde, el mismo actor siempre del mismo color).

### Tipos nuevos (20 en total)

**`grafo`** (comparte `datos_red` con `red_semantica`): actores, entidades o procesos y sus
relaciones. Novedades en `datos_red`:

- `grupos: [{id, etiqueta, color | null}]` — comunidades, sectores, tipos de actor. `[]` si no agrupa.
- `nodos[].grupo: string | null` (id de `grupos`) y `nodos[].color: color | null` (manda sobre el del grupo).
- `aristas[].etiqueta: string | null` — rótulo corto de la relación («financia», «depende de»).
- `tipo_relacion` admite además `flujo`, `jerarquia`, `influencia`, `pertenencia`. Las tres de
  siempre (`coocurrencia`, `similitud`, `interpretativa`) siguen siendo para `red_semantica`.
- Reglas iguales a la red: ids únicos, sin autoenlaces, sin aristas duplicadas, `interpretativa` sin pesos.

**`sankey`** (`datos_flujo`): cuánto pasa de cada origen a cada destino.

```json
{ "unidad": "menciones",
  "nodos": [{"id": "a1", "etiqueta": "Autoridades", "color": "#0072b2"}, {"id": "t1", "etiqueta": "Infraestructura", "color": null}],
  "flujos": [{"origen": "a1", "destino": "t1", "valor": 14, "color": null}] }
```

Reglas: ids de nodo únicos; todo flujo apunta a nodos existentes; `valor ≥ 0`; sin flujo de un nodo a
sí mismo; **sin ciclos** (origen → destino sin volver atrás). `flujos[].color: null` = color del origen.

**`treemap`** (`datos_arbol`): jerarquía de partes con el peso de cada hoja.

```json
{ "unidad": "menciones",
  "nodos": [{"id": "t1", "etiqueta": "Infraestructura", "padre": null, "valor": null, "color": "#0072b2"},
            {"id": "t1a", "etiqueta": "Vías de acceso", "padre": "t1", "valor": 12, "color": null}] }
```

Reglas: ids únicos; `padre` existe o es `null` (raíz); al menos una raíz; sin ciclos; **las hojas
traen `valor ≥ 0`** y los nodos con hijos llevan `valor: null` (el visor suma); `color: null` en una
hoja = color de su rama de primer nivel.

Los tres tipos llevan los metadatos comunes de siempre (`fuente_ids`, `metodo`, `unidad_analisis`,
`base`, `nota`, `descripcion_accesible`).

## Texto sugerido para los system prompts (`analisis_llm` y `analisis_bertopic`)

> **Colores.** Declara colores (`#rrggbb`) sólo cuando el color tiene significado: semáforos, Sí/No,
> escalas ordenadas, grupos de actores o temas. Usa el mismo color para el mismo concepto en todo el
> informe. Si el color no significa nada, deja `[]` o `null`: el visor aplica su paleta.
>
> **Grafos y flujos.** Para actores, entidades o procesos y sus relaciones usa `grafo` con `grupos`
> (sector, tipo de actor) y `etiqueta` en cada arista; reserva `red_semantica` para términos del
> texto. Para «cuánto va de A a B» usa `sankey` (sin ciclos). Para «de qué se compone y con qué
> peso» usa `treemap` (hojas con valor, ramas con `valor: null`).
>
> `version` siempre es `kunsamu.analisis/v2.1`.

Y sustituir «Catálogo de 17 visualizaciones» por 20 donde el prompt los enumere.

## Extensión del informe (sugerido, aparte del esquema)

El esquema no limita la extensión y el visor tampoco. Si las salidas llegan cortas, es el prompt o
el presupuesto de salida. Funciona mejor pedir cifras que adjetivos: entre cinco y ocho hallazgos por
informe, afirmación de tres a cinco oraciones, implicación siempre, al menos dos citas en cada
hallazgo cualitativo y una o dos métricas en cada cuantitativo, una visualización por hallazgo
cuantitativo, de tres a seis recomendaciones. Conviene registrar `usage.output_tokens` y el estado de
la respuesta para saber si el tope de salida está apretando.

## Checklist

- [ ] `analisis.schema.json` sustituido por el adjunto en los dos pipelines (`json_schema`, `strict: true`).
- [ ] Validador de negocio: reglas de `sankey` (acíclico, `valor ≥ 0`) y `treemap` (raíz, hojas con valor, sin ciclos) y `grafo` (igual que la red).
- [ ] Prompts activos de `analisis_llm` y `analisis_bertopic` con el párrafo de colores y tipos nuevos; `version` = `v2.1`.
- [ ] `catalogo_visual.v2_1.json` pasa el validador.
- [ ] Los análisis v2 guardados siguen sirviéndose tal cual (el front los lee).
