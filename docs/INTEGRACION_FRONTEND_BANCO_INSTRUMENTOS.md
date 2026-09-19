# Integración frontend — Banco de instrumentos (plantillas de momentos)

Guía para el equipo de frontend sobre el banco de instrumentos: cómo marcar un momento
público/privado, explorar y previsualizar el banco, usar una plantilla en una jornada, y mostrar
la trazabilidad entre el original y sus copias.

**Nota de nombres**: en la interfaz esto se llama "banco de instrumentos" (un instrumento, acá, es
un momento de jornada con su árbol de preguntas). En el backend y en la API se llama
`banco-momentos` — `instrumentos.Instrumento` ya es **otro módulo** del sistema (aplicaciones
restringidas por preregistro, con su propio login), y usar el mismo nombre en el código habría
generado colisiones y confusión entre módulos. Usen "instrumento" al hablar con el usuario y
`banco-momentos` al hablar con la API; son la misma cosa vista desde dos lugares.

---

## 1. Selector público/privado al crear o editar un momento

Un momento **siempre** está en el banco: privado (solo lo reutilizan los propietarios de su
jornada) o público (cualquier usuario del panel). No existe un estado "fuera del banco".

```
POST /api/admin/momentos/
PATCH /api/admin/momentos/{id}/
Authorization: Token <token de admin/dependencia>
```

Campo nuevo escribible: `visibilidad` (`"privado"` | `"publico"`, default `"privado"` si no se
manda). Pinten un selector simple (radio o switch) en la pantalla de crear/editar momento.

```json
{ "visibilidad": "publico" }
```

Tres campos más viajan en la respuesta, **de solo lectura** (mandarlos en el body no hace nada,
el backend los ignora):

| Campo | Forma | Para qué |
|---|---|---|
| `creado_por` | `{id, username, nombre}` \| `null` | Quién lo creó — atribución, no permiso. |
| `momento_origen` | `int` \| `null` | Id del momento del que se copió, si aplica. |
| `origen_info` | objeto | Snapshot del origen (ver §5), `{}` si el momento no vino del banco. |

**Badge "creado desde plantilla"**: si `origen_info` no es `{}`, muestren un badge o nota en el
detalle del momento con `origen_info.titulo` y `origen_info.jornada_nombre` (ej. "Creado desde
«Diagnóstico de Articulación Académica» — Jornada Ágil 2026"). Si `momento_origen` es `null` pero
`origen_info` no está vacío, el original ya no existe — igual muestren el snapshot, es la razón
de que exista.

---

## 2. Explorador del banco

```
GET /api/admin/banco-momentos/
Authorization: Token <token de admin/dependencia>
```

Devuelve los momentos públicos de cualquiera, más los de las jornadas propias (sin duplicados).
Un administrador completo ve además los privados de otros usuarios.

### Query params

| Param | Valores | Default | Qué hace |
|---|---|---|---|
| `alcance` | `todos` \| `publicos` \| `mios` | `todos` | `publicos` = solo `visibilidad=publico`; `mios` = solo momentos de jornadas propias (cualquier visibilidad); `todos` = unión de ambos (para admin completo, literalmente todos). |
| `q` | texto | — | Busca por `icontains` en `titulo` y `contexto`. |
| `tipo` | `individual` \| `mesa` | — | Filtro exacto. |
| `jornada` | id | — | Solo momentos de esa jornada. Si la jornada no tiene nada visible para mí, la lista sale vacía (no da error). |
| `solo_originales` | `1` | — | Excluye momentos con `momento_origen` no nulo (oculta copias de copias). |
| `incluir_inactivos` | `1` | — | Incluye también momentos con `activo=False`. Sin este flag, **no aparecen**. |
| `ordering` | `titulo` \| `-actualizado_en` \| `-veces_usado` | `-actualizado_en` | Orden del listado. |

**El toggle `incluir_inactivos` es importante**: por defecto el listado excluye los momentos
desactivados (`activo=False`) para no ensuciar el banco con contenido que su dueño apagó, pero
esos momentos siguen siendo perfectamente usables como plantilla — el detalle y `usar/` funcionan
sobre ellos igual, con o sin el flag. Pónganlo como un filtro explícito ("mostrar también
inactivos"), no como algo automático.

### Forma de cada item

```json
{
  "id": 61,
  "titulo": "Diagnóstico de Articulación Académica",
  "slug": "diagnostico-articulacion",
  "tipo": "individual",
  "contexto": "Primeros 200 caracteres…",
  "visibilidad": "publico",
  "creado_por": {"id": 5, "username": "mgarcia", "nombre": "María García"},
  "jornada": {"id": 4, "slug": "jornada-agil-2026", "nombre": "Jornada Ágil 2026", "activa": false},
  "activo": true,
  "n_preguntas": 12,
  "n_preguntas_inactivas": 1,
  "veces_usado": 3,
  "momento_origen": null,
  "es_mio": true,
  "puedo_editar": true,
  "creado_en": "2026-03-02T10:00:00Z",
  "actualizado_en": "2026-09-01T18:22:00Z"
}
```

Qué mostrar con cada campo:

- **`n_preguntas`**: cuántas preguntas verá un participante hoy (solo `activa=True`). Muéstrenlo
  como "12 preguntas" en la tarjeta del instrumento.
- **`n_preguntas_inactivas`**: cuántas preguntas más trae la plantilla pero desactivadas. Si es
  mayor a 0, avisen algo como "+1 pregunta inactiva se copiará también" — porque **al usar la
  plantilla se copian todas**, activas e inactivas, conservando su estado (ver §4).
- **`veces_usado`**: cuántas copias existen de este momento en total (no solo las que el usuario
  actual puede ver). Útil como señal de "instrumento probado".
- **`es_mio`**: soy propietario de la jornada de este momento. Úsenlo para distinguir "lo mío" de
  "lo de otros" visualmente (ej. una pestaña o badge "Mío").
- **`puedo_editar`** (`es_mio` o admin completo): muestren el botón "Editar" (que lleva a la
  pantalla normal de edición del momento, `PATCH /api/admin/momentos/{id}/`) solo si es `true`.
  Con `false`, el momento en el banco es de solo lectura para este usuario.
- **`activo`**: si es `false`, marquen visualmente el instrumento como desactivado (solo aparece
  si se pidió `incluir_inactivos`), pero el botón "Usar" sigue funcionando igual.

---

## 3. Previsualización

```
GET /api/admin/banco-momentos/{id}/
Authorization: Token <token de admin/dependencia>
```

Trae el mismo item de §2 más el árbol completo:

```json
{
  "…": "…",
  "preguntas": [
    {
      "id": 101, "tipo": "unica", "texto": "¿Cómo evalúa la articulación?", "orden": 1,
      "obligatoria": true, "filas_adicionales": false,
      "mesas_permitidas": [], "roles_permitidos": [],
      "depende_de_opcion": null,
      "opciones": [{"id": 37, "texto": "Buena", "orden": 1}, {"id": 38, "texto": "Regular", "orden": 2}],
      "filas": [], "columnas": []
    }
  ]
}
```

**Es de solo lectura — NO manden `PATCH` a este endpoint ni a ninguna URL bajo
`/banco-momentos/`.** No existe: `/banco-momentos/` solo acepta `GET` (raíz, detalle, `derivados/`)
y `POST` en `usar/`. Úsenlo únicamente para pintar una vista previa (modal o panel lateral) antes
de que el usuario decida usar el instrumento. Los ids que trae (`preguntas[].id`,
`opciones[].id`, …) son los de la **plantilla**, no de una copia futura — no sirven para nada
editable, solo para renderizar el árbol.

`404` si el momento no está en el banco visible para mí (privado ajeno, o no existe).

---

## 4. "Usar en jornada…"

```
POST /api/admin/banco-momentos/{id}/usar/
Authorization: Token <token de admin/dependencia>
```

Request:

```json
{
  "jornada": 9,
  "titulo": "Diagnóstico — sede norte",
  "orden": 3,
  "visibilidad": "privado"
}
```

| Campo | Obligatorio | Notas |
|---|---|---|
| `jornada` | sí | Debe ser una jornada mía (propietario). |
| `titulo` | no | Default: el título del origen. |
| `orden` | no | Default: `max(orden)+1` en la jornada destino. |
| `visibilidad` | no | Default `"privado"` — la copia no publica nada por sí sola. |

Pantalla sugerida: un selector de jornada (solo las mías) y, opcionalmente, título/orden si
quieren dejarlos editar antes de crear la copia. `visibilidad` puede quedar oculto la primera vez
(default privado) y dejarse para "publicar" después, desde la edición normal del momento ya
copiado.

Respuesta `201`:

```json
{
  "momento": { "…MomentoAdminSerializer completo de la copia, con preguntas…" },
  "advertencias": [
    "La pregunta «¿Cuál fue el principal obstáculo?» dependía de una opción de otro momento; la dependencia se quitó.",
    "Los roles «Jefe de programa», «Decano» no existen en la jornada destino; se conservaron en roles_permitidos igual."
  ]
}
```

**`advertencias` siempre viene en la respuesta, aunque sea `[]`. Muéstrenla al usuario — no la
oculten ni la traguen en silencio.** Es la única forma de que se entere de que una dependencia
condicional se quitó o de que un rol de la plantilla no existe todavía en la jornada destino. Un
toast o un panel con la lista de advertencias inmediatamente después del `201` es suficiente; no
hace falta bloquear el flujo, la copia ya se creó y es válida.

### Errores

| Código | Cuándo | Mensaje / forma |
|---|---|---|
| `404` | El `{id}` de origen no está en mi banco visible (privado ajeno o no existe). | — |
| `403` | `jornada` es válida pero no me pertenece. | `"Esta jornada no te pertenece."` |
| `400` | `jornada` no existe, `orden` ya está ocupado en la jornada destino, o `visibilidad` inválida. | ej. `{"orden": ["Ya existe un momento con ese orden en la jornada."]}` |

### Después de usar la plantilla

La copia es un momento normal desde el segundo cero: se edita con los endpoints de siempre
(`PATCH /api/admin/momentos/{id}/`, `/preguntas/`, `/opciones/`, …), no hay ningún endpoint
especial para "editar una copia". El original nunca se entera de nada de lo que se haga después.

**Usar varias plantillas en la misma jornada es una llamada `usar/` por plantilla.** No hay un
endpoint para usar varias de una vez — si el usuario elige 3 instrumentos, encadenen 3 `POST
…/usar/` (uno por uno, mostrando las advertencias de cada uno por separado).

---

## 5. Trazabilidad

```
GET /api/admin/momentos/{id}/
```

Trae `momento_origen` (id del momento del que se copió, o `null`) y `origen_info`:

```json
{
  "momento_id": 61,
  "titulo": "Diagnóstico de Articulación Académica",
  "jornada_id": 4,
  "jornada_slug": "jornada-agil-2026",
  "jornada_nombre": "Jornada Ágil 2026",
  "creado_por": "mgarcia",
  "copiado_en": "2026-09-18T15:04:00Z",
  "copiado_por": "jperez"
}
```

`origen_info` es un snapshot congelado al momento de copiar — no una consulta en vivo al
original. Si el original o su jornada se borran después, `origen_info` **no cambia**: sigue
mostrando de dónde salió la copia aunque `momento_origen` ya sea `null`. Úsenlo así: si
`momento_origen` es `null` pero `origen_info` no está vacío, el original ya no existe pero el
dato de dónde vino se sigue mostrando igual (por ejemplo sin enlace activo, o con el enlace
deshabilitado).

```
GET /api/admin/banco-momentos/{id}/derivados/
```

Lista las copias que se hicieron de `{id}` **que el usuario actual puede ver** (mis jornadas; un
admin completo ve todas). Mismo formato que el listado de §2, sin el árbol de `preguntas`. `200
[]` si no hay ninguna visible, aunque existan copias que no puedo ver. Útil como pestaña "Usado
en" dentro del detalle de un instrumento propio, para que el dueño sepa el alcance de lo que edita
antes de cambiarlo.

---

## 6. Flujo sugerido de pantalla

1. **Crear/editar un momento**: mostrar el selector público/privado (§1). Si el momento tiene
   `origen_info`, mostrar el badge "creado desde plantilla".
2. **Explorador del banco** (pantalla nueva o pestaña dentro de "momentos"): lista con los
   filtros de §2, toggle "mostrar inactivos", y una tarjeta por instrumento con `n_preguntas`,
   `veces_usado` y el badge "Mío" si `es_mio`.
3. **Clic en un instrumento** → previsualizar (§3): modal o panel con el árbol de preguntas de
   solo lectura, y el botón "Usar en jornada…".
4. **"Usar en jornada…"** (§4): selector de jornada propia, campos opcionales de título/orden, y
   confirmar. Al volver el `201`, mostrar `advertencias` si las hay y llevar al usuario a la
   copia recién creada (ya editable normalmente).
5. **Repetir el paso 3–4** por cada instrumento adicional que se quiera usar en la misma jornada
   (una llamada por plantilla).
6. **Detalle de un momento propio**: pestaña o sección "Usado en" con `derivados/` (§5), para ver
   cuántas copias existen antes de decidir editar o despublicar el original.

---

## 7. Checklist

- [ ] Selector público/privado (`visibilidad`) en crear y editar momento; default `privado` si no
      se toca.
- [ ] Badge "creado desde plantilla" cuando `origen_info` no está vacío, aunque `momento_origen`
      sea `null`.
- [ ] Explorador con los filtros `alcance`, `q`, `tipo`, `jornada`, `solo_originales`,
      `incluir_inactivos`, `ordering`.
- [ ] Toggle explícito para `incluir_inactivos` (no mostrar inactivos por defecto).
- [ ] Usar `puedo_editar` para decidir si se muestra el botón "Editar" sobre un item del banco.
- [ ] Previsualización de solo lectura (`GET /banco-momentos/{id}/`) — **nunca** mandar `PATCH`
      a esa URL.
- [ ] "Usar en jornada…" con selector de jornada propia y campos opcionales de título/orden.
- [ ] Mostrar siempre `advertencias` de la respuesta de `usar/`, aunque el array venga vacío.
- [ ] Manejar 404 (origen no visible), 403 (jornada ajena) y 400 (`jornada`/`orden`/`visibilidad`
      inválidos) de `usar/` con mensajes distintos.
- [ ] Usar varias plantillas = una llamada `usar/` por plantilla, encadenadas por el frontend.
- [ ] Editar la copia con los endpoints normales de momento — no hay endpoints especiales para
      "editar una copia".
- [ ] Pestaña o sección de trazabilidad (`derivados/`) en el detalle de un momento propio.

---

## Nota sobre autenticación

Todo este documento es exclusivamente `/api/admin/**`, con `Authorization: Token <token>` de un
usuario `is_staff` (administrador completo o de dependencia). **Los participantes de jornada no
ven nada del banco de instrumentos**: no hay ningún endpoint del banco bajo `/api/jornadas/**`, y
los campos `visibilidad`, `creado_por`, `momento_origen` y `origen_info` no se exponen en los
serializers que consume el participante. Un token `Participant <uuid>` recibe `403` si intenta
llamar a cualquier URL de `/api/admin/banco-momentos/**`, igual que con cualquier otro endpoint
de admin.
