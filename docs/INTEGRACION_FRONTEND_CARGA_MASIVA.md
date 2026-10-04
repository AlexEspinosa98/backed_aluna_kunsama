# Integración frontend — Carga masiva y corrección de respuestas (HU-84)

Tres cambios en la carga de documentos que hace un **administrador**. La carga que hace el propio
participante (HU-56) **no cambia en nada** — ver `INTEGRACION_FRONTEND_CARGA_Y_RESPONSABLE.md`.

---

## 1. Ya no hay que aprobar nada

Antes: se subía el documento, se esperaba `estado: "completo"`, y había que llamar a
`POST .../momento-extracciones/{id}/aprobar/` para que la transcripción se escribiera como
respuestas reales.

**Ahora la transcripción se escribe sola** en cuanto termina. Cuando el polling devuelve
`estado: "completo"`, las respuestas **ya están guardadas**: `aprobado_en` viene con fecha.

```json
{
  "id": 42,
  "estado": "completo",
  "aprobado_en": "2026-10-04T15:32:11Z",   // ya se escribió, no hay que hacer nada más
  "aprobado_por": 3,
  "resultado": { "respuestas": [ ... ] },
  "preguntas_omitidas": []
}
```

**Qué hacer en el FE:** quitar el botón "Aprobar". Cuando `estado` llega a `completo`, mostrar
"listo, N respuestas guardadas" y un acceso a revisarlas (punto 3).

`aprobar/` **sigue existiendo y responde 200**, por si todavía le pegan desde algún flujo: es
idempotente y no duplica nada. Pero ya no hace falta y conviene sacarlo.

### El único caso que sigue necesitando un paso humano

Si la IA no pudo identificar de quién es el documento, no hay a nombre de quién guardar las
respuestas. Ahí `estado` queda `completo` pero `aprobado_en` viene en `null`:

```json
{ "estado": "completo", "aprobado_en": null,
  "responsable_detectado": {"nombre": "María Elena Vargas"},
  "responsable_estado": "sin_coincidencia" }
```

Se resuelve igual que antes, con `asignar-responsable` — pero **ese mismo llamado ya escribe las
respuestas**, no hace falta aprobar después:

```
POST /api/admin/momento-extracciones/{id}/asignar-responsable/
{ "participante_id": 17 }
```

La respuesta vuelve con `aprobado_en` lleno. Valores posibles de `responsable_estado`:
`sin_dato` (el documento no traía responsable), `sin_coincidencia` (lo leyó pero no coincide con
nadie de la jornada), `ambiguo` (coincide con más de una persona).

---

## 2. Carga masiva

```
POST /api/admin/momento-extracciones/masiva/
Content-Type: multipart/form-data

momento:  61
archivos: <archivo 1>
archivos: <archivo 2>
archivos: <archivo N>
```

El campo `archivos` se repite, uno por archivo. **Hasta 30 por request.** Solo `.pdf` y `.docx`.

**No manden `participante_id`.** La carga masiva existe para la pila de formatos de departamentos
distintos: a cada archivo le corresponde una persona distinta, y se lee del propio documento.

Respuesta `201`:

```json
{
  "creadas": [
    { "id": 50, "estado": "pendiente", "nombre_archivo_original": "antropologia.docx", ... },
    { "id": 51, "estado": "pendiente", "nombre_archivo_original": "biologia.pdf", ... }
  ],
  "rechazadas": [
    { "archivo": "notas.xlsx", "error": "Solo se aceptan archivos .pdf o .docx." }
  ]
}
```

**Un archivo inválido no tumba la tanda**: los buenos se crean y los malos vuelven en
`rechazadas`. Muéstrenlos — no los oculten, es la única señal de que ese archivo no entró. Si no
sirve ninguno, es `400`.

### El polling

Los documentos se procesan **uno después de otro**, no todos a la vez (cada uno son varias
llamadas al proveedor de IA). Con 30 archivos la tanda puede tardar bastante, y van cambiando de
estado de a uno.

Hagan polling al índice filtrado por momento, que ya existe:

```
GET /api/admin/momento-extracciones/?momento=61
```

Cada item trae su propio `estado` y su propio `error_mensaje`. Un intervalo de 5–10 s está bien.
Muestren una lista con el progreso por archivo: `pendiente` → `procesando` → `completo` / `error`.

**Una que falle no detiene a las demás.** Para reintentar solo esa, vuelvan a subir ese archivo
(suelto o en otra tanda); no hay que repetir la tanda completa.

---

## 3. Corregir una respuesta ya guardada

Es la contraparte de haber quitado la aprobación: si la IA leyó mal una celda, el que subió el
documento la arregla.

```
PATCH /api/admin/respuestas/{id}/
{ "texto_libre": "lo que de verdad decía el formato" }
```

Para preguntas de opción:

```
PATCH /api/admin/respuestas/{id}/
{ "opcion_ids": [37] }
```

Y para borrar una celda que la IA inventó:

```
DELETE /api/admin/respuestas/{id}/
```

**Solo se pueden cambiar `texto_libre` y `opcion_ids`.** Mandar `pregunta`, `fila` o `columna` no
hace nada: mover una celda no es corregir una transcripción, y dejarlo abierto sería una forma de
pisar la respuesta de otra persona por error. Si de verdad hay que mover algo, se borra la celda y
se crea por la vía normal.

**No hay `POST`** a `/api/admin/respuestas/`: una respuesta nace del envío del participante o de
una carga, nunca de un admin escribiéndola a mano.

La validación es la misma del envío normal, así que un `400` acá significa lo mismo que allá: una
matriz no acepta opciones, una pregunta de opción única no acepta dos marcadas, etc.

### De dónde salen los ids para corregir

Las respuestas escritas por una carga se listan con el endpoint que ya usan:

```
GET /api/admin/respuestas/?momento=61
```

Cada item trae `id`, `pregunta`, `participante`, `fila`, `fila_lista`, `columna` y `texto_libre`.
Para armar la pantalla de revisión, cruzar con `GET /api/admin/momentos/{id}/` (que da las
preguntas con sus filas y columnas) es lo mismo que ya hacen para pintar un momento.

Nota sobre filas dinámicas (las que el grupo agregó a mano, con `fila_lista` en vez de `fila`):
si borran **todas** las celdas de una fila, la fila se borra también. No queda una fila vacía
colgando.
