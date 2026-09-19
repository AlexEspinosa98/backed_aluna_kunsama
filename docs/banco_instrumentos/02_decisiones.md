# 02 — Decisiones y preguntas abiertas

Cada decisión trae: contexto, opciones, **recomendación** y si **bloquea** el arranque. Para
cerrar una, basta con responder "Dn: opción X" (o proponer otra). Las no bloqueantes se toman
con la recomendación si nadie dice lo contrario.

Estado global: **todas pendientes**.

---

## D1 — ¿El momento *es* la plantilla, o el banco guarda una copia (snapshot)? — **BLOQUEANTE**

**Contexto.** Hay dos maneras de materializar "subir al banco":

| | **A. El momento es la plantilla** (recomendada) | **B. Snapshot en el banco** |
|---|---|---|
| Qué hay en el banco | Los propios `Momento` de las jornadas, filtrados por `visibilidad`. | Copias con `jornada=NULL` (o un modelo `PlantillaMomento` aparte). |
| "Publicar" | Poner `visibilidad=publico`. Instantáneo, reversible. | Copiar el momento al banco. Si luego edito el momento, debo "republicar". |
| Modelos nuevos | Ninguno. 3–4 campos en `Momento`. | O bien `Momento.jornada` nullable + ajustes en todo lo que asume jornada, o bien 4 modelos nuevos duplicando el árbol. |
| Editar la plantilla | Es editar el momento en su jornada con los endpoints de siempre. | Endpoints nuevos para el árbol del banco (o reutilizar los de momento con `jornada=NULL`). |
| Ciclo de vida | Si se borra la jornada, la plantilla desaparece del banco. Las copias no se ven afectadas. | La plantilla sobrevive a la jornada. |
| Estabilidad para terceros | Lo que ven en el banco es el momento "vivo": cambia si el dueño lo edita durante su jornada. | Lo que ven es fijo hasta que el dueño republique. |
| Ruido en el banco | Cada copia es también un momento con visibilidad. Se mitiga: las copias nacen `privado` (D8) y se puede filtrar `solo_originales`. | El banco solo tiene lo que se publicó a propósito. |
| Esfuerzo | ~1 semana. | ~2–3 semanas. |

**Recomendación: A.** Cumple literalmente el enunciado ("al crear un momento defino si es público
o privado"), no duplica el árbol, y la regla "editar el original no afecta a las copias" se cumple
igual porque las copias son copias profundas. B se puede añadir después si aparece la necesidad de
plantillas que sobrevivan a su jornada, sin deshacer nada de A (sería agregar `jornada=NULL` a lo
ya construido).

**Pregunta concreta:** ¿te sirve que la plantilla pública sea el momento "vivo" de la jornada, o
necesitas que lo que ven los demás quede congelado hasta que decidas republicar?

---

## D2 — Nomenclatura: cómo llamar al feature en código y API — **BLOQUEANTE**

**Contexto.** `instrumentos.Instrumento` ya existe y es otra cosa (ver [01_contexto.md](01_contexto.md) §6).

Opciones:
- **A (recomendada).** En **código y API**: "banco de momentos" (`/api/admin/banco-momentos/`,
  `visibilidad`, `momento_origen`, `BancoMomentoSerializer`). En **UI y HU**: "banco de
  instrumentos", aclarando una vez que instrumento = momento.
- **B.** "banco de instrumentos" en todo (`/api/admin/banco-instrumentos/`). Riesgo: el FE va a
  confundirlo con `/api/admin/instrumentos/`, que ya existe.
- **C.** "plantillas" (`/api/admin/plantillas-momento/`). Choca con `plantillas-analisis/`.

---

## D3 — ¿Qué significa "mío" para un instrumento privado?

**Contexto.** Hoy el acceso a un momento es por `jornada.propietarios` (puede haber varios). El
enunciado dice "solo lo podré utilizar **yo**".

Opciones:
- **A (recomendada).** "Mío" = momentos de jornadas donde soy propietario. Coherente con todo el
  scoping actual: si un co-propietario ya ve y edita ese momento en la jornada, ocultárselo en el
  banco no protege nada. `creado_por` se guarda igual, para atribución y para D4.
- **B.** "Mío" = `creado_por == yo`, estricto. Un co-propietario ve el momento en la jornada pero
  no lo puede usar como plantilla. Más literal, menos coherente.

---

## D4 — ¿Quién puede editar una plantilla?

**Contexto.** Enunciado: "solo su creador y un administrador". Hoy cualquier propietario de la
jornada edita sus momentos. Restringir a `creado_por` sería una **regresión** para jornadas con
varios propietarios.

Opciones:
- **A (recomendada).** Mantener la regla actual: propietarios de la jornada + admin completo.
  El creador es propietario, así que queda cubierto; los co-propietarios también (igual que hoy).
  Terceros nunca pueden editar: el banco es de solo lectura y el `PATCH /momentos/{id}/` les da
  404 porque no está en su queryset.
- **B.** Restringir `PATCH/DELETE` de un momento con `visibilidad=publico` a `creado_por` + admin.
  Cambia el comportamiento actual solo para momentos públicos.
- **C.** Restringir siempre a `creado_por` + admin. Regresión clara; no recomendada.

---

## D5 — Alcance del rol "administrador" en el banco

- **A (recomendada).** Admin completo ve **todo** en el banco, incluidos los privados de otros
  (igual que hoy ve todas las jornadas), y puede editar cualquiera. Un usuario `dependencia` con
  sus jornadas es "el usuario" del enunciado.
- **B.** Admin ve solo públicos + propios en el banco, aunque pueda editar cualquier momento por
  los endpoints normales. Inconsistente; no recomendada.

---

## D6 — Visibilidad por defecto de un momento nuevo

- **A (recomendada).** `privado`. Nada se comparte sin decisión explícita; los momentos
  existentes quedan privados en la migración y nadie ve de golpe contenido ajeno.
- **B.** `publico`. El banco se llena solo, pero expone contenido que no se pensó como plantilla.

---

## D7 — Backfill de `creado_por` para los momentos existentes

Los momentos actuales no tienen creador. Opciones para la migración de datos:
- **A (recomendada).** `creado_por = jornada.creada_por` si existe; si no, `NULL`. Con D3-A
  esto no afecta a la visibilidad (que va por propietarios), solo a la atribución mostrada.
- **B.** Dejar `NULL` en todos y que un admin lo asigne a mano si le importa.

---

## D8 — Visibilidad de la copia recién creada

- **A (recomendada).** Siempre nace `privado`, salvo que el body de `usar` diga otra cosa. Evita
  que el banco público se llene de duplicados de la misma plantilla.
- **B.** Hereda la visibilidad del origen.

---

## D9 — Qué hacer con `depende_de_opcion` que apunta fuera del momento copiado

Ver [01_contexto.md](01_contexto.md) §4.
- **A (recomendada).** Si la opción está dentro del árbol copiado → remapear al id nuevo. Si
  apunta a otro momento → dejar `NULL` en la copia y devolver una **advertencia** en la respuesta
  (`advertencias: ["La pregunta 3 dependía de una opción de otro momento; la dependencia se
  quitó."]`). La copia queda válida y el usuario decide.
- **B.** Rechazar la copia con 400. Bloquea un caso legítimo por un detalle menor.

---

## D10 — `mesas_permitidas` y `roles_permitidos` al copiar a otra jornada

Son listas de números de mesa y de nombres de rol **de la jornada origen**. En la jornada
destino esos roles pueden no existir (`RolJornada` es por jornada).
- **A (recomendada).** Copiar tal cual (son contenido) y, si algún rol no existe como
  `RolJornada` en la jornada destino, agregar una advertencia en la respuesta. Nada se rompe:
  `roles_permitidos` se compara contra `Participante.rol` como texto libre.
- **B.** Vaciar ambas listas en la copia. Pierde información que costó configurar.

---

## D11 — Preguntas inactivas (`activa=False`) al copiar

- **A (recomendada).** No copiarlas. Una pregunta inactiva es una pregunta "quitada" del
  formulario; la copia debe reflejar lo que ve un participante. (Si la opción de la que dependía
  otra pregunta estaba en una inactiva, aplica D9.)
- **B.** Copiarlas conservando `activa=False`.

---

## D12 — Momentos inactivos y jornadas inactivas en el banco

- **A (recomendada).** El banco lista solo momentos `activo=True`. La `Jornada.activa` **no**
  filtra: reutilizar momentos de jornadas pasadas es justamente el caso de uso principal.
  Desactivar un momento equivale a "retirarlo del banco" sin borrarlo.
- **B.** Listar también inactivos con un filtro `?incluir_inactivos=1`.

---

## D13 — Usar varias plantillas de una vez

- **A (recomendada, fase 1).** Un `POST …/usar/` por plantilla; el FE encadena llamadas. Simple,
  sin semántica de "todo o nada" que definir.
- **B (fase 2, opcional).** `POST /api/admin/jornadas/{slug}/momentos/desde-banco/` con
  `{"plantillas": [id, id, …]}`, atómico, asignando `orden` consecutivo. Se agrega solo si el FE
  lo pide.

---

## D14 — Registro documental cuando el origen desaparece

`momento_origen` va con `on_delete=SET_NULL`. Si borran el original, la copia pierde el rastro.
- **A (recomendada).** Además de la FK, guardar `origen_info` (JSON) con `{id, titulo,
  jornada_slug, jornada_nombre, creado_por_username, copiado_en}` en el momento copiado. Es lo que
  hace que la relación sea *documental* de verdad: sobrevive al borrado.
- **B.** Solo la FK.

---

## D15 — ¿Cambiar la visibilidad requiere ser el creador?

Con D4-A, cualquier propietario de la jornada puede cambiar `visibilidad`. Si prefieres que
publicar/despublicar sea exclusivo del creador + admin (aunque editar el contenido no lo sea),
se implementa como validación en el serializer. **Recomendación:** misma regla que D4.

---

## D16 — Fuera de alcance (confirmar)

Doy por **fuera de alcance** de esta iteración, salvo que digas lo contrario:
- Banco de **jornadas completas** (copiar una jornada con todos sus momentos).
- Banco para `instrumentos.Instrumento` (el otro módulo).
- Versionado de plantillas ("actualizar mi copia con los cambios del original"). El enunciado dice
  explícitamente que las copias son aisladas, así que no se contempla.
- Favoritos, calificaciones, categorías/etiquetas del banco. Solo búsqueda por texto y tipo.
- Analítica comparada entre momentos hermanos (misma plantilla en varias jornadas). La relación
  `momento_origen` lo deja posible para después.

---

## Resumen para responder rápido

| Decisión | Recomendación | Bloquea |
|---|---|---|
| D1 modelo | A: el momento es la plantilla | **sí** |
| D2 nombre | A: `banco-momentos` en API, "banco de instrumentos" en UI | **sí** |
| D3 "mío" | A: jornadas donde soy propietario | no |
| D4 editar | A: regla actual (propietarios + admin) | no |
| D5 admin | A: ve y edita todo | no |
| D6 default | A: `privado` | no |
| D7 backfill | A: `jornada.creada_por` | no |
| D8 copia | A: nace `privado` | no |
| D9 dependencias | A: remapear o anular con advertencia | no |
| D10 mesas/roles | A: copiar tal cual con advertencia | no |
| D11 inactivas | A: no copiar | no |
| D12 filtro activo | A: solo `activo=True`, jornada no filtra | no |
| D13 varias | A: una llamada por plantilla | no |
| D14 origen_info | A: sí, JSON snapshot | no |
| D15 visibilidad | A: misma regla que editar | no |
| D16 alcance | confirmar lista | no |
