# Integración frontend — Resumen de un análisis para presentación (HU-99)

Un endpoint nuevo que toma un análisis **ya terminado** y genera una versión resumida para
presentarla en diapositivas: pocos hallazgos por informe (normalmente entre 3 y 6), cada uno pensado como una
diapositiva, con un titular que es una conclusión, una o dos cifras, a lo sumo una cita y una
visualización.

**La salida tiene el mismo contrato que el análisis completo** (`kunsamu.analisis/v2`): la pantalla
que hoy pinta un análisis puede pintar un resumen sin cambios. Lo que cambia es el contenido: menos
y más corto.

## Endpoints

Base: `/api/admin/resumenes-presentacion/`

```
POST   /api/admin/resumenes-presentacion/            pedir un resumen (responde 201 en "pendiente")
GET    /api/admin/resumenes-presentacion/{id}/       seguirlo y, al terminar, leer `resultado`
GET    /api/admin/resumenes-presentacion/?analisis_jornada=24   los resúmenes de un análisis
DELETE /api/admin/resumenes-presentacion/{id}/       borrarlo (si está en curso, se cancela)
```

Filtros del listado: `jornada`, `reporte`, `analisis_momento`, `analisis_jornada`, `analisis_v2`.

## Pedir un resumen

```json
POST /api/admin/resumenes-presentacion/
{
  "analisis_jornada": 24,
  "instrucciones": "Para el consejo académico, 15 minutos, máximo 6 diapositivas de hallazgos.",
  "modelo": "gpt-6.1-sol",
  "esfuerzo": "medium",
  "flex": true
}
```

| Campo | Obligatorio | Qué es |
|---|---|---|
| `reporte` · `analisis_momento` · `analisis_jornada` · `analisis_v2` | **Exactamente uno** | El id del análisis a resumir. |
| `instrucciones` | No | Público, duración, cantidad de diapositivas, énfasis. Sin límite de largo. |
| `modelo` · `esfuerzo` · `flex` | No | Igual que en el análisis integral; sus opciones salen de `GET /api/admin/analisis-jornada-ia/opciones/`. Sin ellos, la configuración del servidor. |

Respuestas:

| Código | Cuándo |
|---|---|
| `201` | Creado en `pendiente`; se genera en segundo plano. |
| `400` | Ninguno o más de un análisis de origen; el análisis no está `completo`; es un análisis antiguo, anterior al contrato v2 (no se puede resumir — hay que generar uno nuevo); `modelo` o `esfuerzo` inválidos. |
| `409` | Ya hay un resumen en curso para ese mismo análisis. |

## Seguirlo

Igual que un análisis: polling a `GET .../{id}/` mientras `estado` sea `pendiente` o
`procesando`, hasta `completo` o `error`. Un resumen tarda bastante menos que un análisis (le llega
el análisis ya hecho, no las respuestas), pero corre en el mismo modo segundo plano: **no pongan un
límite de espera menor a 2 horas**. `fase_openai` = `reparacion` significa que el modelo está
corrigiendo una primera versión que no pasó la validación ("Revisando…").

```json
{
  "id": 3,
  "jornada": 9,
  "fuente": {"tipo": "analisis_jornada", "id": 24},
  "instrucciones": "Para el consejo académico…",
  "modelo": "gpt-6.1-sol", "esfuerzo": "medium", "flex": true,
  "estado": "completo",
  "resultado": { "version": "kunsamu.analisis/v2", "informes": [ … ], "visualizaciones": [ … ], "…": "…" },
  "error_mensaje": "",
  "version_prompt": "resumen_presentacion#1",
  "fase_openai": "intento",
  "creado_en": "…", "completado_en": "…"
}
```

El listado trae lo mismo **sin** `resultado`, `prompt_usado` ni `diagnostico` (son pesados); el
detalle los trae completos.

## Cómo leer `resultado` para armar diapositivas

Es el contrato de siempre. Una lectura sugerida:

| Diapositiva | De dónde sale |
|---|---|
| Portada | `informes[0].titulo` |
| Lo esencial | `informes[0].resumen` |
| Una por hallazgo, en el orden en que vienen (ya están ordenados por importancia) | `hallazgos[i].titulo` como titular, `afirmacion` como bajada, la primera de `metricas` como cifra destacada, `citas[0]` si hay, y la visualización de `visualizacion_ids[0]` buscada en `resultado.visualizaciones` |
| Recomendaciones | `informes[0].recomendaciones` (a lo sumo 5, con `prioridad`) |
| Notas o limitaciones | `resultado.limitaciones` |

Garantías que da el backend (las valida antes de publicar el resumen):

- Cada cifra, cita y visualización del resumen está **copiada idéntica** del análisis original y
  sigue apuntando a los datos reales: no hay números nuevos ni frases inventadas.
- Todo `visualizacion_ids` existe en `visualizaciones`, y no hay visualizaciones sueltas.
- Los `id` de hallazgos, recomendaciones y visualizaciones son los del análisis original: se puede
  enlazar cada diapositiva con el análisis completo.

## Checklist

- [ ] Botón "Generar presentación" en un análisis `completo` (no ofrecerlo en análisis antiguos: el
      backend responde `400`).
- [ ] Campo de instrucciones opcional y, si quieren, los mismos selectores de modelo, esfuerzo y
      Flex que en el análisis integral.
- [ ] Polling hasta `completo` o `error`, sin límite menor a 2 horas.
- [ ] Pintar `resultado` con el mismo componente del análisis, o como diapositivas según la tabla
      de arriba.
- [ ] Listar los resúmenes de un análisis (`?analisis_jornada=…`): se puede pedir más de uno con
      instrucciones distintas.
