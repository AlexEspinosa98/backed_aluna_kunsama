# 05 — API

Todo bajo `/api/admin/` con `Authorization: Token <token>` de un usuario `is_staff`. Nombres
según **D2-A** (`banco-momentos`). Refleja las decisiones cerradas el 2026-09-19 (D11-B y
D12-B incluidas).

## 1. Cambios en endpoints existentes

### `POST /api/admin/momentos/` y `PATCH /api/admin/momentos/{id}/`

Campos nuevos en `MomentoAdminSerializer`:

| Campo | Tipo | Escritura | Notas |
|---|---|---|---|
| `visibilidad` | `"privado"` \| `"publico"` | sí | Default `privado`. |
| `creado_por` | `{id, username, nombre}` \| `null` | **read-only** | Lo fija `perform_create` desde `request.user`. |
| `momento_origen` | `int` \| `null` | **read-only** | Solo lo fija el servicio de copia. |
| `origen_info` | `object` | **read-only** | `{}` si no viene del banco. |

Ejemplo de respuesta `201` de `POST /api/admin/momentos/`:

```json
{
  "id": 88, "jornada": 9, "orden": 1,
  "titulo": "Reflexión inicial", "slug": "reflexion-inicial",
  "contexto": "…", "tipo": "individual",
  "categorias_semilla": [], "mesas_permitidas": [], "roles_permitidos": [],
  "permite_carga_archivo": false, "activo": true,
  "visibilidad": "publico",
  "creado_por": {"id": 5, "username": "mgarcia", "nombre": "María García"},
  "momento_origen": null,
  "origen_info": {},
  "preguntas": []
}
```

### `GET /api/admin/momentos/`

Sin cambios de comportamiento: sigue mostrando solo momentos de jornadas visibles. Los campos
nuevos aparecen en cada item. Filtro opcional `?visibilidad=publico|privado`.

## 2. Endpoints nuevos: `/api/admin/banco-momentos/`

`ReadOnlyModelViewSet` + dos acciones. **No** acepta `POST` en la raíz ni `PATCH/DELETE` en
el detalle: la edición se hace por `/momentos/`.

### `GET /api/admin/banco-momentos/`

Query params:

| Param | Valores | Default |
|---|---|---|
| `alcance` | `todos` \| `publicos` \| `mios` | `todos` |
| `q` | texto | — (busca en `titulo`, `contexto`) |
| `tipo` | `individual` \| `mesa` | — |
| `jornada` | id | — |
| `solo_originales` | `1` | — (excluye los que tienen `momento_origen`) |
| `incluir_inactivos` | `1` | — (por defecto el listado excluye `activo=False`; D12-B) |
| `ordering` | `titulo` \| `-actualizado_en` \| `-veces_usado` | `-actualizado_en` |

Queryset base (dependencia), **sin** filtro de `activo` (lo aplica solo el listado):

```python
Momento.objects.filter(
    Q(visibilidad=Momento.VISIBILIDAD_PUBLICO) | Q(jornada__propietarios=user)
).distinct()
```

Admin completo: `Momento.objects.all()`. El listado añade `.filter(activo=True)` salvo
`?incluir_inactivos=1`; detalle, `usar/` y `derivados/` usan el queryset base tal cual.

Respuesta `200` (item):

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

- `n_preguntas`: solo `activa=True` (lo que ve un participante). `n_preguntas_inactivas`: las
  que también se copiarán pero llegarán con `activa=False` (D11-B).
- `veces_usado`: `COUNT(momentos_derivados)`.
- `es_mio`: soy propietario de su jornada. `puedo_editar`: `es_mio or admin`. El FE usa esto
  para mostrar u ocultar el botón de editar (que lleva a la pantalla normal del momento).

### `GET /api/admin/banco-momentos/{id}/`

Mismo item que arriba más `contexto` completo y `preguntas` con el árbol de solo lectura:

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

Errores: `404` si no está en mi banco visible (privado ajeno o inexistente). Un momento
inactivo visible para mí responde `200` con `activo: false` (D12-B).

### `POST /api/admin/banco-momentos/{id}/usar/`

Crea la copia en una jornada mía.

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
| `jornada` | sí | Debe ser visible para mí (403 si no). |
| `titulo` | no | Default: título del origen. |
| `orden` | no | Default: `max(orden)+1` en la jornada. 400 si ya está ocupado. |
| `visibilidad` | no | Default `privado` (D8). |

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

Errores:

| Código | Cuándo |
|---|---|
| `404` | El origen no está en mi banco visible. |
| `403` | `jornada` no me pertenece (dependencia). Mensaje: `"Esta jornada no te pertenece."` |
| `400` | `jornada` inexistente, `orden` ocupado, `visibilidad` inválida. |

### `GET /api/admin/banco-momentos/{id}/derivados/`

Lista los momentos que se copiaron de `{id}` **y que yo puedo ver** (mis jornadas; admin todos).
Formato: lista de items del banco (mismo serializer del listado, sin `preguntas`). `200 []` si no
hay ninguno visible.

## 3. Ejemplo de secuencia completa para el FE

```bash
# 1. Explorar
GET /api/admin/banco-momentos/?alcance=publicos&q=diagn

# 2. Previsualizar
GET /api/admin/banco-momentos/61/

# 3. Usar en mi jornada 9
POST /api/admin/banco-momentos/61/usar/
{"jornada": 9}
# → 201 {"momento": {"id": 88, …}, "advertencias": []}

# 4. Editar la copia como cualquier momento
PATCH /api/admin/momentos/88/
{"titulo": "Diagnóstico adaptado"}

# 5. (Opcional) publicar la copia adaptada
PATCH /api/admin/momentos/88/
{"visibilidad": "publico"}
```

## 4. OpenAPI

Los ViewSets nuevos entran solos en el esquema de drf-spectacular. Añadir `@extend_schema` con
`parameters` para los query params del listado y `request`/`responses` para `usar/`, para que
`/api/schema/` documente el body y la forma `{momento, advertencias}`.
