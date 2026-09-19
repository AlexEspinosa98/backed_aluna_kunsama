# 01 — Contexto: qué existe hoy y qué condiciona el diseño

Todo lo que sigue sale del código actual (`main` en `1bc50d8`). Son hechos, no decisiones.

## 1. El "instrumento" del banco es `jornadas.Momento`

Árbol de contenido (todo clonable, sin datos de ejecución):

```
Jornada
└── Momento                       jornadas/models.py:129-195
    └── Pregunta                  jornadas/models.py:198-280
        ├── OpcionPregunta        jornadas/models.py:283-293
        ├── FilaMatrizPregunta    jornadas/models.py:296-309
        └── ColumnaMatrizPregunta jornadas/models.py:312-322
```

Campos de `Momento` que son **contenido** y por tanto deben copiarse al usar una plantilla:
`titulo`, `contexto`, `tipo` (`individual`|`mesa`), `categorias_semilla`, `mesas_permitidas`,
`roles_permitidos`, `permite_carga_archivo`, `activo`.

Campos de `Momento` que **no** son contenido: `jornada`, `orden`, `slug`, `creado_en`,
`actualizado_en`.

Campos de `Pregunta` a copiar: `tipo`, `texto`, `orden`, `obligatoria`, `activa`,
`filas_adicionales`, `mesas_permitidas`, `roles_permitidos`, `depende_de_opcion` (ver §4).

Datos de **ejecución** que cuelgan de un momento y que **nunca** se copian: `Respuesta`,
`FilaListaRespuesta`, `ExtraccionMomento` (app `participantes`), `AnalisisMomentoIA`,
`InfografiaJornada`, `Reporte.momentos` (app `analitica`).

## 2. Quién es "el usuario" y cómo se controla el acceso

- No hay custom user: `django.contrib.auth.User`. Quien crea momentos es siempre un usuario con
  `is_staff=True` (los participantes de jornada son otro modelo, `participantes.Participante`, y
  nunca tocan `/api/admin/**`).
- Dos roles de panel (`jornadas/models.py:6-25`): `admin` (completo) y `dependencia`. Un usuario
  **sin** `PerfilUsuario` es admin completo (`jornadas/scoping.py:11-13`).
- **Un momento no tiene dueño propio.** El acceso se deriva de `Momento.jornada.propietarios`
  (M2M). `Jornada.creada_por` es solo auditoría.
- El control de acceso es por **filtrado de queryset** (`filtrar_por_propietario`,
  `jornadas/scoping.py:22-28`): un usuario de dependencia nunca ve momentos de jornadas ajenas
  (404), y `ValidarPropietarioAlCrearMixin` (`jornadas/views.py:30-53`) impide crear contenido
  bajo una jornada ajena (403). No hay permisos por objeto ni django-guardian.
- Consecuencia directa: **hoy es imposible que un usuario de dependencia vea un momento de otra
  dependencia**. El banco necesita un camino de lectura nuevo que salte ese filtro solo para lo
  público.

## 3. Constraints que condicionan la copia

| Constraint | Dónde | Efecto en la copia |
|---|---|---|
| `unique_together ('jornada','orden')` | `Momento.Meta` | Hay que calcular `orden` en la jornada destino (`max+1`). |
| `unique_together ('jornada','slug')` | `Momento.Meta` | `save()` regenera el slug solo si viene vacío (`models.py:186-195`): la copia debe crearse con `slug=''`. |
| `unique_together ('momento','orden')` | `Pregunta.Meta` | Se conserva el `orden` original: el momento nuevo está vacío, no hay choque. |
| `unique_together ('pregunta','orden')` | Opción/Fila/Columna | Igual, se conserva. |
| `Pregunta.depende_de_opcion` → `OpcionPregunta` | `models.py:257-263` | FK interna al árbol: hay que **remapear** al id de la opción copiada (§4). |

## 4. `depende_de_opcion` cruza momentos

`PreguntaAdminSerializer.validate` (`jornadas/serializers.py:83-101`) exige que la opción esté
en la **misma jornada**, no en el mismo momento. Así que una pregunta del momento A puede
depender de una opción del momento B de la misma jornada. Al copiar solo A, esa dependencia no
tiene a dónde apuntar en la jornada destino. Hay que decidir qué hacer (decisión **D9**).

## 5. Lo que NO existe hoy

Búsqueda de `duplicar|clonar|copiar|plantilla|template|banco|publico|privado|reutiliz` en el
código: no hay nada para momentos. Lo único parecido:

- `analitica.PlantillaAnalisis`: plantillas de **prompts** de IA, no de contenido.
- Management commands que siembran momentos con `update_or_create` (`seed_jornada_agil2`,
  `migrar_diagnostico_a_momentos`): sirven de referencia de cómo se arma el árbol por código,
  pero no son reutilizables por API.
- Ningún serializer de `jornadas` tiene escritura anidada: el árbol se arma con N requests
  (momento → preguntas → opciones). El patrón de la casa es "recurso hijo con FK explícita".

## 6. Colisión de nombres con la app `instrumentos`

Ya existe `instrumentos.Instrumento` (documentos de reflexión con preregistro y revisión,
HU-26 a HU-33). Es otro módulo y **no** es el banco. Cualquier nombre de modelo, endpoint o
serializer que diga "instrumento" a secas va a confundir a quien lea el código o la API. Ver
decisión **D2**.

## 7. Patrones de la casa a respetar

- Acciones sobre un recurso: `@action(detail=True, methods=['post'], url_path='…')` en el
  ViewSet (ej. `aprobar`, `asignar-responsable` en `participantes/admin_views.py:108-139`).
- Errores: 404 cuando el objeto no está en el queryset visible, 403 (`PermissionDenied`) cuando
  se intenta crear bajo una jornada ajena, 400 con clave de campo para validación.
- Todo lo que muta varias tablas va en `transaction.atomic()`.
- Cada feature deja HU en `docs/USER_STORIES_COMPLETO.md` (variante "decisión de diseño", con
  el porqué de cada elección) y, si afecta al front, una guía `docs/INTEGRACION_FRONTEND_*.md`.
- Tests con `APITestCase` (unittest), un `tests.py` por app, helpers `crear_jornada` y
  `crear_dependencia` en `jornadas/tests.py:13-25`. Requieren Postgres.
