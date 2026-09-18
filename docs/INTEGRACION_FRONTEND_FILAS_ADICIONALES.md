# Integración frontend — `filas_adicionales` y el manejo de filas en `matriz` y `lista`

Guía para el equipo de frontend: qué cambia con el campo nuevo `filas_adicionales` (HU-53) y
cómo manejar las filas en los dos tipos de pregunta que son tablas — `matriz` y `lista`.

Resumen en una línea: **hay dos clases de fila**, las que define el admin (fijas) y las que
agrega quien responde (dinámicas), y ahora una misma `matriz` puede tener las dos a la vez.

---

## 1. El campo

`filas_adicionales` es un booleano que viene en **cada pregunta** del detalle del momento:

```
GET /api/jornadas/{slug}/momentos/{id}/
Authorization: Participant <uuid>
```
```json
{
  "id": 1200,
  "tipo": "matriz",
  "texto": "Capacidades por área",
  "obligatoria": true,
  "filas_adicionales": true,
  "filas":    [{ "id": 10, "texto": "Área A", "orden": 1 }],
  "columnas": [{ "id": 20, "texto": "Responsable", "orden": 1 },
               { "id": 21, "texto": "Meta", "orden": 2 }]
}
```

Viene en **todas** las preguntas, no solo en las de tabla. En las que no son `matriz`/`lista`
siempre llega en `false` y se ignora.

Qué hacer con él, según el tipo:

| `tipo`                          | `filas_adicionales` | Qué pinta el front                                        |
|---------------------------------|---------------------|-----------------------------------------------------------|
| `matriz`                        | `false` (default)   | Tabla de filas fijas. **Sin** botón "agregar fila".        |
| `matriz`                        | `true`              | Tabla de filas fijas **+** botón "agregar fila".           |
| `lista`                         | `true` (siempre)    | Tabla vacía, solo con botón "agregar fila".                |
| `abierta`/`unica`/`multiple`/`audio` | `false` (siempre) | No aplica, ignorarlo.                                      |

> No hardcodeen la regla por tipo: **lean el campo**. Una `matriz` puede tener el flag encendido
> o apagado, y un admin puede cambiárselo en cualquier momento desde el panel.

---

## 2. Las dos clases de fila

Esto es lo único que hay que entender bien; todo lo demás sale de acá.

|                     | Fila **fija**                          | Fila **dinámica** (agregada)                      |
|---------------------|----------------------------------------|---------------------------------------------------|
| Quién la crea       | El admin, al armar la pregunta         | Quien responde, en el formulario                  |
| De dónde sale       | `pregunta.filas[]` (trae `id` real)    | No existe hasta que se envía                      |
| Cómo se envía       | `fila_id: <id real>`                   | `fila_temporal: <número inventado por ustedes>`   |
| Cómo vuelve al leer | `"fila": 10, "fila_lista": null`       | `"fila": null, "fila_lista": 55`                  |
| ¿Se puede borrar?   | No                                     | Sí (ver §5)                                       |

Dónde aparece cada una:

- **`lista`** → `pregunta.filas` viene **siempre vacío**. Todas las filas son dinámicas.
- **`matriz` con `filas_adicionales: false`** → solo fijas. Es el comportamiento de siempre,
  no cambia nada de lo que ya tienen implementado.
- **`matriz` con `filas_adicionales: true`** → **las dos a la vez, en la misma tabla**. Las fijas
  de `pregunta.filas` arriba, y debajo las que agregue el usuario.

### `fila_temporal` no es un id

Es un número que **inventa el cliente** para decir "estas celdas van en la misma fila". Usen un
contador local (1, 2, 3…) o el índice del arreglo. Tres consecuencias:

1. No lo busquen en ninguna respuesta del backend: no existe ahí.
2. No es estable entre envíos. El `fila_temporal: 1` de hoy no es "la misma fila" que el de ayer.
3. Solo tiene que ser único **dentro de una misma pregunta en un mismo envío**. Dos preguntas
   distintas pueden usar `fila_temporal: 1` sin problema.

---

## 3. Enviar — `POST /api/jornadas/{slug}/momentos/{id}/respuestas/`

Mismo endpoint de siempre, una entrada **por celda**.

### `lista` — todas las filas dinámicas

```json
{ "respuestas": [
  { "pregunta_id": 1300, "fila_temporal": 1, "columna_id": 30, "texto_libre": "Juan Pérez" },
  { "pregunta_id": 1300, "fila_temporal": 1, "columna_id": 31, "texto_libre": "Magíster" },
  { "pregunta_id": 1300, "fila_temporal": 2, "columna_id": 30, "texto_libre": "Ana Gómez" },
  { "pregunta_id": 1300, "fila_temporal": 2, "columna_id": 31, "texto_libre": "Doctora" }
] }
```

### `matriz` con `filas_adicionales: true` — mixto, en el mismo envío

```json
{ "respuestas": [
  { "pregunta_id": 1200, "fila_id": 10,       "columna_id": 20, "texto_libre": "Ana" },
  { "pregunta_id": 1200, "fila_id": 10,       "columna_id": 21, "texto_libre": "Meta A" },
  { "pregunta_id": 1200, "fila_temporal": 1,  "columna_id": 20, "texto_libre": "Juan" },
  { "pregunta_id": 1200, "fila_temporal": 1,  "columna_id": 21, "texto_libre": "Meta extra" }
] }
```

**Nunca los dos en la misma celda.** Una celda lleva `fila_id` **o** `fila_temporal`, jamás
ambos — eso es `400`.

---

## 4. Leer lo ya guardado — `GET .../momentos/{id}/respuestas/`

Llega **plano, una entrada por celda**. Agrupen ustedes:

```json
[
  { "id": 5001, "pregunta": 1200, "fila": 10,   "fila_lista": null, "columna": 20, "texto_libre": "Ana" },
  { "id": 5002, "pregunta": 1200, "fila": 10,   "fila_lista": null, "columna": 21, "texto_libre": "Meta A" },
  { "id": 6001, "pregunta": 1200, "fila": null, "fila_lista": 55,   "columna": 20, "texto_libre": "Juan" },
  { "id": 6002, "pregunta": 1200, "fila": null, "fila_lista": 55,   "columna": 21, "texto_libre": "Meta extra" }
]
```

Para rehidratar el formulario:

1. Filtren por `pregunta`.
2. Las celdas con `fila != null` → van en la fila fija de ese `id` (que ya tienen en
   `pregunta.filas`).
3. Las celdas con `fila_lista != null` → agrúpenlas por ese valor. **Cada `fila_lista` distinto
   es una fila agregada.** Ordénenlas por `fila_lista` ascendente: los ids se crean en el orden
   en que se mandaron las filas, así que el orden se conserva.
4. Al rehidratar, **reasignen sus propios `fila_temporal`** (1, 2, 3… según el orden del punto
   anterior). No intenten reusar el `fila_lista` como `fila_temporal`: son cosas distintas y el
   backend no las empareja.

---

## 5. La regla que más fácil se pasa por alto: **el envío reemplaza todas las filas dinámicas**

Las celdas de fila **fija** se actualizan una por una (mandar solo una celda actualiza solo esa).

Las filas **dinámicas** no: **cada `POST` borra todas las filas dinámicas de esa pregunta y las
vuelve a crear con lo que venga en el envío.**

Consecuencias prácticas, y son importantes:

- **Manden siempre TODAS las filas dinámicas**, no solo las que cambiaron. Si el usuario tiene 5
  filas agregadas y ustedes mandan 1, quedan 1 — las otras 4 se borran.
- **Así se borra una fila**: el usuario le da a "eliminar fila" en la UI, ustedes la sacan del
  estado local y reenvían el resto.
- **Así se borran todas**: reenviar el momento sin ninguna celda con `fila_temporal`. En una
  `matriz` mixta eso borra las extra y **deja las fijas intactas**.
- Por lo mismo, el momento se envía **completo** en un `POST`, no celda por celda. Si van a hacer
  autoguardado, que el payload lleve siempre el estado completo de las preguntas de tabla.

El `POST` es **atómico**: si cualquier celda del envío es inválida, no se guarda nada de nada y
el estado anterior queda como estaba. No hay guardados a medias.

---

## 6. Obligatoriedad

- **`matriz` obligatoria** → el backend exige **todas** las celdas fijas (todo fila × columna del
  admin). Las filas extra **no cuentan**: agregar filas no sustituye una celda fija vacía.
- **`lista` obligatoria** → basta con **una** fila que tenga **todas** sus columnas llenas. No
  exige que todas las filas estén completas.

En ambos casos falla con `400` y `{"faltantes": [<pregunta_id>]}` — el id de la **pregunta**, no
de la celda. Si quieren marcar en rojo la celda exacta, esa validación la hacen ustedes en el
cliente.

---

## 7. Errores que devuelve el backend (`400`)

| Situación                                                            | Cuándo les va a pasar                                  |
|----------------------------------------------------------------------|--------------------------------------------------------|
| `fila_temporal` en una `matriz` con el flag apagado                   | No leyeron `filas_adicionales` antes de pintar el botón |
| `fila_id` **y** `fila_temporal` en la misma celda                     | Bug al construir el payload de una matriz mixta         |
| `fila_id` en una pregunta `lista`                                     | Una lista no tiene filas fijas                          |
| Celda de fila agregada sin `columna_id`                               | Falta la columna                                        |
| `fila_id`/`columna_id` de **otra** pregunta                           | Ids cruzados entre preguntas                            |
| Celda de tabla con `opcion_ids`                                       | Las tablas no llevan opciones                           |

---

## 8. Panel de administración

Al crear o editar una pregunta (`POST`/`PATCH /api/admin/preguntas/`, con
`Authorization: Token <token de admin>`):

```bash
POST /api/admin/preguntas/
{ "momento": 68, "tipo": "matriz", "texto": "...", "orden": 1, "filas_adicionales": true }

PATCH /api/admin/preguntas/1200/
{ "filas_adicionales": true }
```

- Si **no mandan** el campo, el backend pone el default según el tipo: `false` en `matriz`,
  `true` en `lista`, `false` en todo lo demás. No hace falta mandarlo.
- En una `lista` el checkbox debe ir **encendido y deshabilitado**: mandar `false` es `400`
  (sus filas son justamente las que agrega quien responde; apagarlo la dejaría sin forma de
  responderse).
- En los tipos que no son tabla, **no muestren el checkbox**: mandar `true` es `400`.
- Si un admin cambia el `tipo` de una pregunta, el backend reencuadra el flag solo — no hace
  falta que lo manden.

---

## 9. Checklist de implementación

- [ ] Leer `filas_adicionales` de cada pregunta; no deducirlo del tipo.
- [ ] `matriz` + flag encendido: pintar las filas fijas **y** el botón "agregar fila".
- [ ] Contador local de `fila_temporal` por pregunta (1, 2, 3…).
- [ ] Una celda lleva `fila_id` **o** `fila_temporal`, nunca los dos.
- [ ] Botón "eliminar fila" solo en las dinámicas; las fijas no se borran.
- [ ] Enviar **siempre todas** las filas dinámicas de la pregunta, no solo las editadas.
- [ ] Al rehidratar: agrupar por `fila_lista`, ordenar ascendente, reasignar `fila_temporal`.
- [ ] Validar en cliente las celdas fijas de una matriz obligatoria (el `400` solo da el id de la
      pregunta).
- [ ] Panel admin: checkbox encendido-y-bloqueado en `lista`, oculto en los tipos que no son tabla.

---

## Nota sobre autenticación

Dos esquemas distintos, no intercambiables:

| Quién         | Header                                    |
|---------------|-------------------------------------------|
| Admin/staff   | `Authorization: Token <hex de 40 chars>`  |
| Participante  | `Authorization: Participant <uuid>`       |

Ver `docs/ESTRUCTURA_PREGUNTAS.md` para la referencia completa de los 6 tipos de pregunta.
