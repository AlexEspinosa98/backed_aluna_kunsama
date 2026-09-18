# Integración frontend — Infografía generada con IA

Guía del endpoint de infografías. Genera **3 láminas complementarias en 16:9** a partir de un
análisis ya calculado y de los assets visuales de la jornada.

Para la carga de assets y del system design (la marca que respetan las láminas), ver
[INTEGRACION_FRONTEND_ASSETS_INFOGRAFIA.md](INTEGRACION_FRONTEND_ASSETS_INFOGRAFIA.md).

---

## 1. URL base

La app está montada bajo un prefijo y nginx lo quita antes de llegar al backend:

```
Base URL (producción):  https://back.alunaia.co/api/aluna-kunsama
```

Todas las rutas de este documento son relativas a esa base, así que el `/api/` termina
apareciendo dos veces y **no es un error de tipeo**:

```
https://back.alunaia.co/api/aluna-kunsama/api/admin/infografias/
```

Omitir el prefijo da **404** — uno generado por nginx, que no deja rastro en los logs del backend
y hace parecer que el endpoint no existe. La barra final también importa: sin ella hay un `301`, y
varios clientes HTTP descartan el header `Authorization` al seguir la redirección.

Autenticación: `Authorization: Token <hex de 40 chars>`, el mismo token de admin del resto del
panel.

---

## 2. Los dos alcances

El endpoint es uno solo; lo que cambia es **sobre qué** se pide la infografía. Son excluyentes:

| Alcance | Cuerpo del POST | De dónde salen los datos | Dónde encaja en el panel |
|---|---|---|---|
| **Jornada completa** | `{"jornada": <id>}` | `AnalisisJornadaIA` completo más reciente | Pestaña "Jornada completa" |
| **Un momento** | `{"momento": <id>}` | `AnalisisMomentoIA` completo más reciente de ese momento | Pestaña "Análisis integral" |

**Manden exactamente uno.** Mandar ambos, o ninguno, es `400`. No hay precedencia silenciosa a
propósito: una infografía que dijera ser de un momento mientras muestra cifras de toda la jornada
sería un error que ustedes no podrían detectar desde el cliente.

Con `momento` **no hay que mandar `jornada`**: el backend la deriva del propio momento.

### Variante avanzada: forzar un reporte

Solo para el alcance de jornada, `{"jornada": <id>, "reporte": <id>}` fuerza que los datos salgan
de ese `Reporte` del pipeline local en vez del reporte integral. Es un caso de borde; la vía normal
es sin `reporte`. Combinarlo con `momento` es `400`.

---

## 3. Generar

```
POST /api/admin/infografias/
Authorization: Token <hex de 40 chars>
Content-Type: application/json

{"momento": 61}
```

Respuesta `201` — arranca en background, todavía sin imágenes:

```json
{
  "id": 8,
  "jornada": 14,
  "jornada_slug": "mujeres-al-mar",
  "momento": 61,
  "momento_titulo": "Diagnóstico de Articulación Académica",
  "reporte": null,
  "estado": "pendiente",
  "prompt_usado": "",
  "error_mensaje": "",
  "modelo_usado": "",
  "imagenes": [],
  "solicitado_por": 3,
  "creado_en": "2026-09-18T22:10:00Z",
  "actualizado_en": "2026-09-18T22:10:00Z",
  "completado_en": null
}
```

`momento` viene en **`null`** cuando la infografía es de la jornada completa. Sirve para saber, en
un listado mezclado, de qué es cada una.

### Códigos de error

| Código | Cuándo |
|---|---|
| `400` | Mandaron ambos alcances o ninguno; o el alcance elegido no tiene análisis completo |
| `403` | Cuenta *dependencia* y la jornada (o la del momento) no le pertenece |
| `409` | Ya hay una infografía en curso **para ese mismo alcance** |

El `400` por falta de análisis llega **de inmediato**, no después del polling: el backend no crea
un registro que ya sabe que va a fallar. El mensaje dice qué generar primero, por ejemplo
*"El momento X no tiene un análisis integral completo. Genéralo primero
(POST /api/admin/analisis-momento-ia/)"*.

El `409` es **por alcance**: generar la del momento 61 no bloquea la de la jornada ni la del
momento 62. Son trabajos independientes.

---

## 4. Esperar el resultado — es asíncrono

`estado` avanza `pendiente` → `procesando` → `completo` (o `error`). Hagan **polling** hasta un
estado final:

```
GET /api/admin/infografias/?momento=61     # sondeo del alcance de momento
GET /api/admin/infografias/?jornada=14     # sondeo del alcance de jornada
GET /api/admin/infografias/{id}/           # directo, si ya tienen el id
```

> **Ojo con esto, que ya pasó**: no basta con consultar una vez justo después del `201`. La
> generación tarda **~80 segundos**; si consultan al segundo siguiente y no vuelven a preguntar,
> nunca van a ver el `completo` y las imágenes quedan generadas pero invisibles en el panel.
> Intervalo recomendado: **3–5 s**, hasta `completo` o `error`.

| `estado` | Qué mostrar |
|---|---|
| `pendiente` | "En cola" |
| `procesando` | "Generando infografía…" (puede tardar un par de minutos) |
| `completo` | Las láminas de `imagenes`, en orden |
| `error` | `error_mensaje` y opción de reintentar con un `POST` nuevo |

---

## 5. Las 3 láminas

Cuando `estado` es `completo`, `imagenes` trae las láminas ordenadas por `orden`. **El orden
importa**: no son variaciones de lo mismo, son tres diapositivas complementarias.

| `orden` | Lámina | Contenido |
|---|---|---|
| 0 | Portada | Título (el del momento, o el de la jornada según el alcance) + cifras clave |
| 1 | Hallazgos | Temas principales con sus datos y las visualizaciones |
| 2 | Cierre | Conclusiones y mensajes accionables |

```json
"imagenes": [
  {"id": 30, "archivo": "https://back.alunaia.co/api/aluna-kunsama/media/analitica/infografias/2026/09/infografia-8-0.png", "orden": 0},
  {"id": 31, "archivo": "...infografia-8-1.png", "orden": 1},
  {"id": 32, "archivo": "...infografia-8-2.png", "orden": 2}
]
```

Cada una es **2048×1152 (16:9)**, pensada para proyectar. **`archivo` ya viene con el dominio y el
prefijo completos**: úsenlo tal cual en un `<img src>`; anteponerle la base lo rompe.

**Puede venir menos de 3.** Cada lámina es una llamada independiente al modelo; si una falla, las
otras se conservan y el `estado` queda en `completo` con un `error_mensaje` que dice cuál faltó.
Un `error_mensaje` no vacío con `estado: "completo"` es un resultado **parcial**, no un fallo:
muestren lo que llegó más un aviso.

Se puede pedir más de una vez sobre el mismo alcance: cada `POST` crea una corrida nueva y no
sobrescribe la anterior, así que regenerar no pierde la versión previa.

---

## 6. Checklist de integración

- [ ] Usar la base URL con el prefijo `/api/aluna-kunsama` y respetar la barra final.
- [ ] En la pestaña "Análisis integral", disparar con `{"momento": <id>}` — no con la jornada.
- [ ] En la pestaña "Jornada completa", disparar con `{"jornada": <id>}`.
- [ ] Nunca mandar los dos a la vez (es `400`).
- [ ] Deshabilitar el botón si el alcance elegido todavía no tiene su análisis integral completo,
      o mostrar el `400` que ya explica qué generar primero.
- [ ] **Hacer polling hasta `completo`/`error`**, no una sola consulta tras el `201`.
- [ ] Manejar el `409` sin permitir un segundo `POST` del mismo alcance mientras tanto.
- [ ] Mostrar las `imagenes` en orden (portada, hallazgos, cierre) y contemplar que vengan menos de 3.
- [ ] Usar `archivo` tal cual, sin anteponerle la base URL.

---

## 7. Auditar de dónde salió una infografía

`prompt_usado` conserva el prompt completo, incluido el bloque de datos con el campo `fuente`:

| Valor de `fuente` | Significa |
|---|---|
| `analisis_momento` | `AnalisisMomentoIA` del momento |
| `analisis_jornada_ia` | Reporte integral de la jornada |
| `reporte` | `Reporte` del pipeline local |

Sirve para confirmar, sin instrumentar nada nuevo, que una infografía se construyó sobre la fuente
que esperaban — que es exactamente como detectamos que el panel estaba usando el pipeline local sin
querer.
