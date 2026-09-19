# 06 — Plan de desarrollo

Cuatro fases, cada una entregable y desplegable por separado. Estimaciones para una persona.

## Fase 0 — Cerrar decisiones ✅ (2026-09-19)

- [x] D1 y D2 cerradas (ambas con la opción A).
- [x] D3–D16 cerradas; D11 y D12 se apartaron de la recomendación (B en ambas) y D16 convierte
      el banco de jornadas completas en la Fase 5.
- [x] Plan ajustado; el resumen de [02_decisiones.md](02_decisiones.md) es la fuente de verdad.

## Fase 1 — Modelo, migración y visibilidad al crear (1 día) → **HU-67**

Objetivo: un momento sabe quién lo creó, si es público o privado, y de dónde salió. Todavía no
hay banco ni copia; solo se sientan las bases y el FE ya puede pintar el selector
público/privado.

Tareas:
- [ ] `jornadas/models.py`: campos `visibilidad`, `creado_por`, `momento_origen`,
      `origen_info` en `Momento` (ver [03_modelo_de_datos.md](03_modelo_de_datos.md) §1).
- [ ] `jornadas/migrations/0016_momento_banco.py` (esquema) y
      `0017_momento_backfill_creado_por.py` (datos, D7).
- [ ] `jornadas/serializers.py` → `MomentoAdminSerializer`: `visibilidad` escribible;
      `creado_por` (nested `{id, username, nombre}`), `momento_origen`, `origen_info` read-only.
- [ ] `jornadas/views.py` → `MomentoAdminViewSet.perform_create`: fijar
      `creado_por=request.user`. Filtro opcional `?visibilidad=`.
- [ ] `jornadas/admin.py`: mostrar los campos nuevos en el admin de Django (si hay `ModelAdmin`
      de Momento).
- [ ] HU-67 en `docs/USER_STORIES_COMPLETO.md`.

Tests (`jornadas/tests.py`, clase `MomentoVisibilidadTests`): C01, C03, C04, C09.

## Fase 2 — Servicio de copia (1 día) → **HU-68**

Objetivo: `copiar_momento()` funciona y está probado sin exponer aún ningún endpoint. Es la
pieza con más casos borde, así que va sola.

Tareas:
- [ ] `jornadas/banco.py`: `copiar_momento(origen, jornada_destino, usuario, *, orden, titulo,
      visibilidad)` según [03_modelo_de_datos.md](03_modelo_de_datos.md) §4. `bulk_create` por
      nivel para preguntas, opciones, filas y columnas; segunda pasada para `depende_de_opcion`.
- [ ] Función auxiliar `siguiente_orden(jornada)` con `select_for_update`.
- [ ] Función auxiliar `advertencias_roles(momento_copia, jornada_destino)`.
- [ ] HU-68 en `docs/USER_STORIES_COMPLETO.md` (explica por qué copia profunda y no referencia,
      por qué las inactivas **sí** se copian conservando su flag (D11-B), por qué las dependencias
      cruzadas se anulan en vez de fallar).

Tests (`jornadas/tests_banco.py`, clase `CopiarMomentoTests`, sin API): U02, U04, U13–U15,
U17–U21, U24, U25, U27–U31, U32 (con un momento de 90 preguntas y 3 matrices, medir tiempo).

## Fase 3 — Endpoints del banco (1–1½ días) → **HU-69**

Objetivo: el FE puede explorar, previsualizar, usar y rastrear.

Tareas:
- [ ] `jornadas/serializers.py`: `BancoMomentoListaSerializer` (item del listado con
      `n_preguntas`, `veces_usado`, `es_mio`, `puedo_editar`, `jornada` nested, `creado_por`
      nested), `BancoMomentoDetalleSerializer` (+ `preguntas` read-only, reutilizando
      `PreguntaAdminSerializer` o una variante sin `momento`), `UsarMomentoSerializer` (body de
      `usar/`).
- [ ] `jornadas/scoping.py`: `momentos_del_banco(user)` con el queryset de
      [05_api.md](05_api.md) §2 (sin filtro de `activo`), anotado con
      `Count('preguntas', filter=Q(preguntas__activa=True))`,
      `Count('preguntas', filter=Q(preguntas__activa=False))` y `Count('momentos_derivados')`.
- [ ] `jornadas/views.py`: `BancoMomentoViewSet(ReadOnlyModelViewSet)` con filtros `alcance`,
      `q`, `tipo`, `jornada`, `solo_originales`, `incluir_inactivos` (solo en `list`),
      `ordering`; acciones `usar` (POST) y `derivados` (GET).
- [ ] `jornadas/urls.py`: `router.register('banco-momentos', BancoMomentoViewSet,
      basename='banco-momento')`.
- [ ] `@extend_schema` para el listado y `usar/`.
- [ ] HU-69 en `docs/USER_STORIES_COMPLETO.md`.

Tests (`jornadas/tests_banco.py`, clase `BancoMomentoAPITests`): B01–B12 (incluidos B02b y
B10b), B15, U01, U03, U05–U12, U22 (con `TransactionTestCase` y dos hilos, o al menos documentar que
`select_for_update` lo cubre), U26, T01–T05, y la matriz de permisos completa de
[04_flujos_y_casos.md](04_flujos_y_casos.md) §3 (una prueba por celda).

## Fase 4 — Documentación para el frontend y cierre (½ día) → **HU-70**

- [ ] `docs/INTEGRACION_FRONTEND_BANCO_INSTRUMENTOS.md`: pantallas sugeridas (selector
      público/privado al crear; explorador del banco con filtros; previsualización; botón "Usar
      en jornada…" con selector de jornada; mostrar `advertencias`; badge "creado desde
      plantilla" con `origen_info`), checklist y tabla de errores.
- [ ] HU-70: trazabilidad (`derivados/`, `origen_info`) si no cupo en HU-69.
- [ ] Actualizar `README.md` del repo (sección de endpoints) y `CLAUDE.md` si describe el módulo
      de jornadas.
- [ ] Correr la suite completa una sola vez (`python manage.py test`), según la regla de ritmo
      del proyecto.
- [ ] Commit y push directo a `main`; luego el despliegue de producción
      (`migrate` obligatorio por las migraciones 0016/0017).

## Fase 5 — Banco de jornadas completas (siguiente iteración, decidido en D16)

Se planifica en detalle cuando cierre la Fase 4, pero el diseño ya queda encaminado:

- `Jornada` recibe los mismos campos que `Momento` (`visibilidad`, `jornada_origen`,
  `origen_info`; `creada_por` ya existe).
- Servicio `copiar_jornada(origen, usuario, *, nombre, slug, fechas, visibilidad)` que crea la
  jornada nueva, copia `RolJornada` y `JornadaAsset` (archivos incluidos) y llama a
  `copiar_momento` por cada momento del origen, en una sola transacción. Como copia **todos** los
  momentos de la jornada, las dependencias `depende_de_opcion` entre momentos de la misma jornada
  se remapean completas (ya no aplica la advertencia de D9).
- Endpoints `GET /api/admin/banco-jornadas/`, `GET …/{id}/`, `POST …/{id}/usar/`.
- No se copian participantes, respuestas, transcripciones, reportes ni infografías.
- Estimación: 2 días, porque reutiliza `copiar_momento` y el patrón del banco de momentos.

## Opcionales, solo si se piden

| Item | Decisión asociada | Esfuerzo |
|---|---|---|
| `POST /jornadas/{slug}/momentos/desde-banco/` con lista de plantillas, atómico | D13-B | ½ día |
| Snapshot en el banco (plantillas que sobreviven a su jornada) | D1-B | 2–3 días |
| Paginación en el listado del banco | B14 | 1 h |
| Etiquetas/categorías del banco para búsqueda | D16 | 1 día |

## Archivos que se tocan (resumen)

| Archivo | Fase | Tipo de cambio |
|---|---|---|
| `jornadas/models.py` | 1 | 4 campos en `Momento` |
| `jornadas/migrations/0016_*.py`, `0017_*.py` | 1 | nuevas |
| `jornadas/serializers.py` | 1, 3 | campos en `MomentoAdminSerializer`; 3 serializers nuevos |
| `jornadas/views.py` | 1, 3 | `perform_create`; `BancoMomentoViewSet` |
| `jornadas/scoping.py` | 3 | `momentos_del_banco(user)` |
| `jornadas/banco.py` | 2 | nuevo: servicio de copia |
| `jornadas/urls.py` | 3 | registro del router |
| `jornadas/admin.py` | 1 | campos en admin |
| `jornadas/tests.py`, `jornadas/tests_banco.py` | 1–3 | tests |
| `docs/USER_STORIES_COMPLETO.md` | 1–4 | HU-67 a HU-70 |
| `docs/INTEGRACION_FRONTEND_BANCO_INSTRUMENTOS.md` | 4 | nueva |

Ningún archivo de `participantes`, `analitica`, `transcripciones` ni `instrumentos` cambia.

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| El banco expone contenido que alguien no quería compartir | Alto | Default `privado` (D6); la migración no publica nada; publicar es un acto explícito por momento. |
| Un tercero edita una plantilla ajena | Alto | El banco es de solo lectura; los endpoints de edición siguen filtrados por propietario (404). Cubierto por la matriz de permisos en tests. |
| `depende_de_opcion` mal remapeada deja una copia con lógica condicional rota | Medio | Segunda pasada con mapa de ids; test U14/U15/U16. La advertencia hace visible cualquier pérdida. |
| Carrera en `orden` al copiar en paralelo | Bajo | `select_for_update` sobre la jornada destino (U22). |
| Confusión de nombres con `instrumentos.Instrumento` | Medio | D2: `banco-momentos` en código/API; "instrumento" solo en UI y HU con la aclaración. |
| El backfill asigna `creado_por` a quien no creó el momento | Bajo | Es solo atribución (no controla acceso, D3-A); un admin lo puede corregir por PATCH si se decide exponer el campo como escribible para admin (no previsto en fase 1). |
| Copias de copias llenan el banco público | Bajo | Copias nacen `privado` (D8) y `?solo_originales=1` en el listado. |
| La copia trae preguntas inactivas que el usuario no esperaba (D11-B) | Bajo | `n_preguntas_inactivas` visible en el banco antes de usar; en la copia siguen `activa=False`, así que el participante no las ve. |

## Definición de hecho

- Todas las decisiones de [02_decisiones.md](02_decisiones.md) con estado cerrado.
- Migraciones aplicadas en producción sin errores.
- La matriz de permisos de [04_flujos_y_casos.md](04_flujos_y_casos.md) §3 tiene un test por
  celda y pasa.
- HU-67 a HU-70 en `docs/USER_STORIES_COMPLETO.md` con el porqué de cada decisión.
- Guía de frontend publicada y validada con el equipo de FE (al menos el flujo de
  [05_api.md](05_api.md) §3 ejecutado de punta a punta contra staging).
