# Integración frontend — Diseño de presentación con IA (`kunsamu.presentacion/v1`)

Implementa `docs/HU_BACKEND_DISENO_PRESENTACION.md` (HU-79 en `docs/USER_STORIES_COMPLETO.md`).

Mueve al backend la llamada a OpenAI con visión que hoy hace el frontend para diagramar la
presentación (colores, tipografía, papel de cada asset, plantilla de cada diapositiva) — el
backend ya tiene los assets de la jornada a mano. Es **opcional y bajo demanda**: nunca se genera
sola, sólo cuando el usuario pulsa «Diagramar con IA», y el resultado se guarda para no volver a
gastar tokens cada vez que se abre la presentación.

---

## 0. URL base y autenticación

Igual que el resto del panel (ver §0 de
[INTEGRACION_FRONTEND_ANALISIS_V2.md](INTEGRACION_FRONTEND_ANALISIS_V2.md)): mismo prefijo, mismo
token de admin (`Authorization: Token <hex de 40 chars>`), mismo permiso `IsAdminUser` + scoping
por dependencia.

---

## 1. Flujo

1. Al abrir la presentación de un análisis: `GET /api/admin/presentacion-diseno/?<fuente>=<id>`.
   Con `200`, usa el diseño guardado. Con `404`, presenta con el diseño institucional y muestra
   el botón «Diagramar con IA». **Este `GET` nunca genera nada.**
2. Al pulsar el botón: `POST /api/admin/presentacion-diseno/` con el análisis y la secuencia de
   diapositivas que el frontend ya va a renderizar. Síncrono: tarda entre 7 y 20 segundos.
3. Si ya existía un diseño para ese análisis, el `POST` lo **reemplaza** (misma fila, es el
   «Rediseñar» del usuario) — nunca crea un segundo diseño para el mismo análisis.
4. `DELETE /api/admin/presentacion-diseno/{id}/` descarta el diseño guardado (vuelve al
   institucional).

Un diseño pertenece a **un análisis concreto** (`reporte` | `analisis_momento` |
`analisis_jornada`), igual patrón que las infografías (HU-73): exactamente uno de los tres, nunca
"la jornada" o "el momento" sueltos.

---

## 2. `GET /api/admin/presentacion-diseno/?reporte=<id>`

También `?analisis_momento=<id>` o `?analisis_jornada=<id>` — exactamente uno de los tres. No es
un listado: la respuesta es EL objeto (o el error), nunca un array.

- `200` con el diseño guardado (mismo cuerpo que el `POST`, ver §4).
- `404` si no hay un diseño guardado para ese análisis, o si el id de análisis no existe.
- `400` si no se manda ninguna de las tres query params, o se manda más de una.
- `403` si la jornada del análisis no pertenece a la dependencia del usuario.

---

## 3. `POST /api/admin/presentacion-diseno/`

```json
{
  "analisis_jornada": 12,
  "diapositivas": [
    {"id": "portada", "tipo": "portada", "titulo": "Portada", "tiene_visual": false, "tipo_visual": null, "tiene_citas": false, "tiene_metricas": false, "naturaleza": null},
    {"id": "i1-h1-v1", "tipo": "hallazgo", "titulo": "Una franja alternativa…", "tiene_visual": true, "tipo_visual": "barras", "tiene_citas": true, "tiene_metricas": true, "naturaleza": "mixto"}
  ]
}
```

| Campo | Notas |
|---|---|
| `reporte` \| `analisis_momento` \| `analisis_jornada` | Exactamente uno, con el id del análisis. Las tres ausentes o más de una presente → `400`. El id no existe → `404`. |
| `diapositivas` | La secuencia que el frontend va a renderizar — el backend la guarda tal cual y se la pasa al modelo, **nunca la reconstruye ni la altera**. `tipo` ∈ `portada`\|`cobertura`\|`resumen`\|`hallazgo`\|`recomendaciones`\|`limitaciones`\|`cierre`. Lista vacía o con un `tipo` desconocido → `400`. |

El análisis debe tener resultado en formato `kunsamu.analisis/v2` (el mismo contrato de
[INTEGRACION_FRONTEND_ANALISIS_V2.md](INTEGRACION_FRONTEND_ANALISIS_V2.md)) — si no, `409`:

```json
{"detail": "El análisis no está en formato v2"}
```

### Errores

| Código | Cuándo | Cuerpo |
|---|---|---|
| `400` | Fuente ausente o duplicada; `diapositivas` inválidas | `{"detail": "…"}` |
| `401` | Sin token de admin | Como el resto de la API |
| `403` | La jornada del análisis no es de la dependencia del usuario | `PermissionDenied` |
| `404` | Análisis inexistente | `{"detail": "No existe un análisis con ese id."}` |
| `409` | El análisis no es v2 | `{"detail": "El análisis no está en formato v2"}` |
| `422` | La jornada no tiene assets con imagen ni guía de marca escrita — nada que diagramar, sin llamar al modelo | `{"detail": "La jornada no tiene assets ni guía de marca"}` |
| `502` | El modelo falló, no devolvió JSON o la respuesta no tiene la forma base del contrato | `{"detail": "<mensaje del proveedor o motivo>"}` |
| `503` | Falta `OPENAI_API_KEY` en el servidor | `{"detail": "Falta OPENAI_API_KEY"}` |

---

## 4. Respuesta (`201` del `POST`, `200` del `GET` — misma forma)

```json
{
  "id": 7,
  "reporte": null,
  "analisis_momento": null,
  "analisis_jornada": 12,
  "version": "kunsamu.presentacion/v1",
  "modelo": "gpt-5.1",
  "correcciones": ["sin ilustración para resumen_ilustracion; se usa resumen"],
  "diseno": {
    "version": "kunsamu.presentacion/v1",
    "tema": {
      "estilo": "institucional",
      "colores": {
        "primario": "#14384a", "secundario": "#2fc2d6", "acento": "#c08a28",
        "fondo": "#f7f0e3", "superficie": "#ffffff", "texto": "#14384a", "texto_suave": "#4a6a7a"
      },
      "tipografia": {"titulos": "serif", "cuerpo": "sans"},
      "fondo": {"tipo": "plano", "colores": ["#f7f0e3"]},
      "justificacion": "Paleta de la guía de marca; fondo marfil cercano al de la ilustración para continuidad."
    },
    "logo": {"asset_id": "3", "posicion": "superior_derecha"},
    "assets": [
      {"id": "3", "rol": "logo", "fondo_recomendado": null, "notas": "Wordmark azul sobre transparente."},
      {"id": "4", "rol": "ilustracion", "fondo_recomendado": null, "notas": "Medusa plana, fondo transparente."}
    ],
    "diapositivas": [
      {"id": "portada", "plantilla": "portada_ilustracion", "acento": "#c08a28", "asset_id": "4", "lado_imagen": "derecha", "mostrar_logo": true}
    ]
  },
  "diapositivas": ["…la secuencia recibida en el POST, tal cual…"],
  "assets": [3, 4, 5, 9],
  "creado": "2026-09-20T18:40:12Z",
  "actualizado": "2026-09-20T18:40:12Z"
}
```

- `assets` (el campo de arriba, distinto de `diseno.assets`) son los ids de `JornadaAsset` de la
  jornada — sirven al frontend para saber si el diseño quedó viejo: si la jornada cambió de
  assets desde que se generó, ofrecer «Rediseñar».
- `modelo` sí trae el nombre real del modelo de OpenAI que respondió (`gpt-5.1`, `gpt-4.1`, o el
  valor de `KUNSAMU_DESIGN_MODEL` si estaba configurado) — a diferencia del resto de la API, esta
  HU lo pide explícitamente.
- `diseno` es el contrato completo (tema, logo, assets con su rol, diapositivas con su plantilla)
  — ya **saneado**: cualquier valor inválido o incoherente que haya devuelto el modelo fue
  corregido antes de guardar, y cada corrección queda anotada en `correcciones` como una frase
  corta (ver la sección 4.1 y 8 de la HU para la semántica completa de `rol`, `fondo_recomendado`
  y las plantillas admisibles por tipo de diapositiva).
- `diapositivas` (fuera de `diseno`) es exactamente la lista que se mandó en el `POST` — el
  frontend la sigue usando para renderizar el contenido; `diseno.diapositivas` sólo aporta la
  diagramación (plantilla, acento, asset, lado, logo) por cada `id` de esa misma lista.

---

## 5. `DELETE /api/admin/presentacion-diseno/{id}/`

`204` sin cuerpo. El `GET` siguiente para ese análisis vuelve a dar `404`.

---

## 6. Notas para el frontend

- El frontend sigue siendo responsable de medir el fondo real de cada ilustración en el
  navegador y de aplicar `fondo_recomendado` como sugerencia (el valor medido manda sobre el del
  modelo) — el backend no reprocesa las imágenes.
- Retirar la ruta interna de Next `POST /api/kunsamu/admin/presentacion-diseno` y la clave de
  OpenAI del `.env` del frontend: la llamada al proveedor ahora vive enteramente en el backend.
- Sin `retrieve` por id (no hay `GET /presentacion-diseno/{id}/`) — el diseño siempre se consulta
  por análisis (`?reporte=`/`?analisis_momento=`/`?analisis_jornada=`), nunca por su propio id.
