# Integración frontend — Análisis integral de la jornada en segundo plano (HU-98)

Aplica **solo** al análisis integral de la jornada:
`POST /api/admin/analisis-jornada-ia/`. Los análisis por momento, los reportes y `analisis-v2` no
cambian.

## Qué cambió en el backend

Antes, el servidor abría una conexión con OpenAI y esperaba la respuesta; si pasaban 9 minutos,
cortaba y el análisis terminaba en error ("Tiempo de espera agotado (540s)…"), aunque OpenAI
siguiera trabajando y cobrando. Con `gpt-6.1-sol` en esfuerzo alto y jornadas grandes eso pasaba
seguido.

Ahora el análisis corre en el **modo segundo plano de OpenAI**: el backend lo lanza, OpenAI lo
procesa por su cuenta y el backend recoge la respuesta cuando está lista. Ya no hay corte a los
9 minutos. Además, al lanzarlo se puede elegir **modelo**, **esfuerzo** y **Flex** (mitad de precio,
más lento).

## Qué tiene que cambiar en el frontend

| # | Cambio | ¿Obligatorio? |
|---|---|---|
| 1 | El polling no debe rendirse a los ~10 minutos | **Sí** |
| 2 | Selector de modelo, esfuerzo y Flex al lanzar | No (si no se envían, se usa la configuración) |
| 3 | Mostrar "revisando" cuando el modelo está corrigiendo su primera respuesta | No |
| 4 | Avisar que borrar un análisis en curso lo cancela | No |

Los estados **no cambian**: `pendiente` → `procesando` → `completo` | `error`. El endpoint de
consulta tampoco. Si hoy la pantalla funciona, va a seguir funcionando — salvo el punto 1.

---

## 1. Polling: los análisis ahora pueden tardar mucho más (obligatorio)

Un análisis integral grande puede tardar **varios minutos y hasta más de media hora**, sobre todo
con esfuerzo alto o con Flex. El backend tiene un tope de seguridad de **2 horas**: si OpenAI no
terminó para entonces, se cancela y el análisis queda en `error`.

Si el frontend tiene un tiempo máximo de espera, un número máximo de reintentos de polling, o
muestra "algo salió mal" cuando un análisis lleva mucho rato en `procesando`, **hay que quitarlo o
llevarlo a más de 2 horas**. Mientras `estado` sea `pendiente` o `procesando`, el análisis está vivo.

Recomendado:

- Consultar cada **15–30 segundos** (el backend le pregunta a OpenAI cada 30 s; consultar más seguido
  no lo acelera).
- Mostrar el **tiempo transcurrido** desde `creado_en`, para que quien espera vea que avanza.
- Seguir mostrando el progreso si el usuario sale y vuelve a la pantalla: el análisis no depende de
  que la pantalla esté abierta.

```
GET /api/admin/analisis-jornada-ia/{id}/
```

```json
{
  "id": 24,
  "estado": "procesando",
  "fase_openai": "intento",
  "consultado_en": "2026-10-05T01:46:12Z",
  "creado_en": "2026-10-05T00:56:41Z",
  "modelo": "gpt-6.1-sol",
  "esfuerzo": "high",
  "flex": true,
  "...": "…el resto de campos de siempre (resultado, error_mensaje, etc.)"
}
```

## 2. Modelo, esfuerzo y Flex al lanzar (opcional)

Los tres campos son opcionales. Si no se envían, el backend usa su configuración (hoy:
`gpt-6.1-sol`, esfuerzo `high`, sin Flex).

```json
POST /api/admin/analisis-jornada-ia/
{
  "jornada": 9,
  "enfoque": "mixto",
  "contexto": "…",
  "instrucciones": "…",
  "modelo": "gpt-6.1-sol",
  "esfuerzo": "high",
  "flex": true
}
```

Para armar el selector, pedir las opciones válidas y los valores por defecto (no los escriban fijos
en el frontend: cambian por configuración del servidor):

```
GET /api/admin/analisis-jornada-ia/opciones/
```

```json
{
  "modelos": ["gpt-5.6-terra", "gpt-6.1-sol"],
  "modelo_por_defecto": "gpt-6.1-sol",
  "esfuerzos": ["low", "medium", "high", "xhigh", "max"],
  "esfuerzo_por_defecto": "high",
  "flex_por_defecto": false,
  "segundo_plano": true
}
```

| Campo | Valores | Qué hace |
|---|---|---|
| `modelo` | uno de `opciones.modelos` | Modelo de OpenAI. Otro valor → `400`. |
| `esfuerzo` | `low` · `medium` · `high` · `xhigh` · `max` | Cuánto razona el modelo. Más esfuerzo = análisis más cuidadoso, más lento y más caro. Otro valor → `400`. |
| `flex` | `true` / `false` | Tier Flex de OpenAI: **cuesta la mitad**, a cambio de que tarde más. Si OpenAI no tiene capacidad Flex en ese momento, el análisis corre igual en el tier normal (precio normal). |

Sugerencia de textos para la pantalla:

- **Esfuerzo** — "Más esfuerzo: análisis más cuidadoso, pero más lento y costoso."
- **Flex** — "Modo económico: cuesta la mitad, pero puede tardar bastante más."

El detalle del análisis devuelve `modelo`, `esfuerzo` y `flex` **efectivos** (lo que se pidió, o la
configuración si no se pidió nada), para mostrar con qué se generó.

Errores al lanzar (los mismos de siempre, más los nuevos de validación):

| Código | Cuándo |
|---|---|
| `400` | `modelo` o `esfuerzo` fuera de la lista; o la jornada no tiene respuestas. |
| `409` | Ya hay un análisis integral en curso para esa jornada. |

## 3. "Revisando" durante la reparación (opcional)

Si la primera respuesta del modelo no pasa la validación del backend, se le pide que la corrija.
Eso se ve en `fase_openai`:

| `fase_openai` | Sugerencia de texto |
|---|---|
| `intento` | "Analizando…" |
| `reparacion` | "Revisando el análisis…" |
| `""` (vacío) | Todavía no se lanzó, o ya terminó. |

`estado` sigue en `procesando` durante las dos fases.

## 4. Borrar un análisis en curso (opcional)

`DELETE /api/admin/analisis-jornada-ia/{id}/` sobre un análisis `procesando` ahora **también lo
cancela en OpenAI**, para no pagar algo que ya nadie va a ver. Si el diálogo de confirmación lo
menciona ("Se cancelará el análisis en curso"), mejor.

## Mensajes de error nuevos

Llegan en `error_mensaje` con `estado: "error"`, igual que los de siempre. No requieren manejo
especial, pero conviene mostrarlos completos:

| Empieza con | Qué pasó | Qué hacer |
|---|---|---|
| "El análisis superó el máximo de 120 minutos…" | OpenAI no terminó en 2 horas; se canceló. | Relanzar, quizá con menos esfuerzo o sin Flex. |
| "OpenAI ya no tiene la respuesta de este análisis…" | La respuesta terminó pero no se alcanzó a recoger (por ejemplo, el servidor estuvo caído). | Relanzar. |
| "OpenAI terminó la respuesta en estado…" | OpenAI falló o cortó la salida. | Relanzar; si se repite, avisar al backend. |
| "La respuesta de la IA no pasó la validación tras un reintento de reparación…" | Igual que antes. | Relanzar. |

## Campos nuevos en el detalle

| Campo | Tipo | Para qué |
|---|---|---|
| `modelo` | string | Modelo efectivo con que se generó. |
| `esfuerzo` | string | Esfuerzo efectivo. |
| `flex` | bool | Si se pidió Flex. |
| `fase_openai` | `"intento"` \| `"reparacion"` \| `""` | Ver punto 3. |
| `respuesta_openai_id` | string | Id de la respuesta en OpenAI. Informativo (soporte). |
| `consultado_en` | fecha ISO o null | Última vez que el backend le preguntó a OpenAI. Si está muy viejo (más de 10 minutos) con el análisis en `procesando`, algo anda mal en el servidor. |

## Checklist

- [ ] El polling del análisis integral no se rinde antes de 2 horas mientras el estado sea
      `pendiente` o `procesando`.
- [ ] Se muestra el tiempo transcurrido mientras está `procesando`.
- [ ] (Opcional) Selector de modelo y esfuerzo, y opción Flex, alimentados por `GET .../opciones/`.
- [ ] (Opcional) "Revisando…" cuando `fase_openai` es `reparacion`.
- [ ] (Opcional) La confirmación de borrar un análisis en curso avisa que se cancela.
- [ ] Mostrar `modelo`, `esfuerzo` y `flex` en el detalle de un análisis terminado.
