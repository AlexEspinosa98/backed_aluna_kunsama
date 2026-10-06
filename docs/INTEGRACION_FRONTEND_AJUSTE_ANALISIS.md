# Integración frontend — Ajustar un análisis ya terminado (HU-102)

Toma un análisis que ya respondió OpenAI y se lo vuelve a pasar, con instrucciones y contexto
nuevos, para obtener una versión mejorada. El resultado es un **análisis nuevo**. El original
no cambia.

Todas las rutas van bajo `/api/admin/` y requieren usuario admin.

---

## 1. Pedir el ajuste

`POST /api/admin/analisis-v2/ajustar/` (JSON)

| Campo | Obligatorio | Valor |
|---|---|---|
| `reporte` \| `analisis_momento` \| `analisis_jornada` \| `analisis_v2` | **exactamente uno** | id del análisis a ajustar. Usa el mismo `tipo` e `id` que trae la lista unificada (`GET analisis/`). Puede ser otro ajuste (`analisis_v2`). |
| `instrucciones` | sí | Qué cambiar: «profundiza en la brecha de conectividad», «reescríbelo para el Consejo Superior», «la recomendación 2 no aplica porque…», «agrega recomendaciones de corto plazo». Sin tope de largo. |
| `contexto` | no | Contexto nuevo que la IA debe tener en cuenta. Sirve para interpretar, nunca es evidencia. |
| `adjuntos` | no | Documentos o imágenes de la jornada, igual que al pedir un análisis: `[{"asset": 41, "uso": "fuente"}, {"asset": 42, "uso": "contexto"}]`. Ver `docs/CARGA_DOCUMENTOS_BASE.md` y `docs/INTEGRACION_FRONTEND_ADJUNTOS.md` §3. |
| `modelo`, `esfuerzo`, `flex` | no | Los mismos del análisis integral (HU-98). Sin ellos se usa la configuración del servidor. |

```json
{
  "analisis_jornada": 29,
  "instrucciones": "Profundiza en los hallazgos sobre horarios y agrega recomendaciones de corto plazo.",
  "contexto": "La rectoría ya aprobó abrir una franja al final de la tarde a partir de 2027-1.",
  "adjuntos": [{"asset": 41, "uso": "contexto"}]
}
```

Respuesta `201`: el análisis nuevo, en `estado: "pendiente"`, con la misma forma que `GET analisis-v2/{id}/`:

```json
{
  "id": 57,
  "es_ajuste": true,
  "ajuste_de": {"tipo": "analisis_jornada", "id": 29},
  "jornada_id": 9,
  "modo": "integral",
  "pipeline": "llm",
  "instrucciones": "Profundiza en los hallazgos sobre horarios…",
  "contexto": "La rectoría ya aprobó…",
  "adjuntos": [{"asset": 41, "uso": "contexto"}],
  "estado": "pendiente",
  "resultado": {},
  "…": "…"
}
```

El modo y el pipeline se copian del análisis original y no se pueden cambiar.

### Errores

| Código | Cuándo |
|---|---|
| `400` | Falta `instrucciones`, se mandaron cero o varios análisis de origen, el origen no está `completo`, es anterior al contrato v2 o no tenía datos (`sin_datos`), o algún adjunto no es válido (`adjuntos`). |
| `403` | La jornada no es del usuario. |
| `409` | Ya hay un ajuste en curso **del mismo análisis**. Hay que esperar a que termine (o falle) antes de pedir otro. |

## 2. Seguirlo

Corre en segundo plano y puede tardar varios minutos en una jornada grande (hasta 2 horas como máximo).

`GET /api/admin/analisis-v2/{id}/` hasta que `estado` pase de `pendiente`/`procesando` a:
- **`completo`**: `resultado` trae el análisis ajustado, completo, con el mismo contrato
  `kunsamu.analisis/v2.1`. Se renderiza con el mismo visor de siempre.
- **`error`**: el motivo viene en `error_mensaje`.

Conviene consultar cada 15 a 30 segundos. `fase_openai` dice si va en el primer intento (`intento`) o en
la reparación automática (`reparacion`).

`DELETE /api/admin/analisis-v2/{id}/` sobre un ajuste en curso lo cancela también en OpenAI.

## 3. Qué hace la IA con el ajuste

- Parte del análisis anterior y conserva lo que las instrucciones no piden cambiar.
- Aplica las instrucciones del ajuste. Si chocan con las instrucciones del análisis original, mandan
  las del ajuste.
- **Las instrucciones no cambian los datos.** Todo hallazgo, cifra y cita sigue saliendo de las
  respuestas de la jornada (y de los adjuntos marcados como fuente), y se valida igual que siempre. Si se
  pide algo que los datos no sostienen, la IA no lo afirma y lo dice en las limitaciones.
- Trabaja sobre **los mismos datos** del análisis original. Si después entraron respuestas nuevas, el
  ajuste no las ve: en ese caso hay que pedir un análisis nuevo.

## 4. Dónde aparece

- **Lista unificada** — `GET /api/admin/analisis/?jornada=<id>`: el ajuste es un item más con
  `tipo: "analisis_v2"`, más `es_ajuste: true` y `ajuste_de: {tipo, id}`. Sugerencia de UI: agrupar los
  ajustes bajo su original, o mostrar «Ajuste de #29».
- **Listado v2** — `GET /api/admin/analisis-v2/?jornada=<id>`: trae `es_ajuste` y `ajuste_de`.
- `ajuste_de.id` es `null` si el original se borró. El ajuste sigue siendo válido porque guarda su propia
  copia de los datos.

## 5. Qué se puede hacer con el ajuste

Lo mismo que con cualquier `AnalisisV2`:
- **Volver a ajustarlo**: `POST analisis-v2/ajustar/` con `"analisis_v2": <id del ajuste>`.
- **Infografía**: `POST infografias/` con `analisis_v2`.
- **Resumen para presentación**: `POST resumenes-presentacion/` con `analisis_v2`.

## 6. Checklist

- [ ] Botón «Ajustar» en el visor de un análisis `completo`, con un cuadro de instrucciones (obligatorio) y otro de contexto (opcional).
- [ ] Selector de adjuntos (fuente o contexto), el mismo del formulario de análisis.
- [ ] Polling de `GET analisis-v2/{id}/` hasta `completo` o `error`.
- [ ] Mostrar `es_ajuste` / `ajuste_de` en la lista y en el visor («Ajuste de #29»).
- [ ] Manejar el `409` («ya hay un ajuste en curso»).
