# 02 — Decisiones y preguntas abiertas

Cada decisión trae: contexto, opciones, **recomendación** y si **bloquea** el arranque. Para
cerrar una, basta con responder "Dn: opción X" (o proponer otra). Las no bloqueantes se toman
con la recomendación si nadie dice lo contrario.

Estado global: **todas cerradas el 2026-09-19** (respondidas en este mismo archivo: se
conservó solo la opción elegida en cada una). El resumen al final es la fuente de verdad.

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
 Me sirve que
---

## D2 — Nomenclatura: cómo llamar al feature en código y API — **BLOQUEANTE**

**Contexto.** `instrumentos.Instrumento` ya existe y es otra cosa (ver [01_contexto.md](01_contexto.md) §6).

Opciones:
- **A (recomendada).** En **código y API**: "banco de momentos" (`/api/admin/banco-momentos/`,
  `visibilidad`, `momento_origen`, `BancoMomentoSerializer`). En **UI y HU**: "banco de
  instrumentos", aclarando una vez que instrumento = momento.


---

## D3 — ¿Qué significa "mío" para un instrumento privado?

**Contexto.** Hoy el acceso a un momento es por `jornada.propietarios` (puede haber varios). El
enunciado dice "solo lo podré utilizar **yo**".

Opciones:
- **A (recomendada).** "Mío" = momentos de jornadas donde soy propietario. Coherente con todo el
  scoping actual: si un co-propietario ya ve y edita ese momento en la jornada, ocultárselo en el
  banco no protege nada. `creado_por` se guarda igual, para atribución y para D4.
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
---

## D5 — Alcance del rol "administrador" en el banco

- **A (recomendada).** Admin completo ve **todo** en el banco, incluidos los privados de otros
  (igual que hoy ve todas las jornadas), y puede editar cualquiera. Un usuario `dependencia` con
  sus jornadas es "el usuario" del enunciado.
---

## D6 — Visibilidad por defecto de un momento nuevo

- **A (recomendada).** `privado`. Nada se comparte sin decisión explícita; los momentos
  existentes quedan privados en la migración y nadie ve de golpe contenido ajeno.

---

## D7 — Backfill de `creado_por` para los momentos existentes

Los momentos actuales no tienen creador. Opciones para la migración de datos:
- **A (recomendada).** `creado_por = jornada.creada_por` si existe; si no, `NULL`. Con D3-A
  esto no afecta a la visibilidad (que va por propietarios), solo a la atribución mostrada.
---

## D8 — Visibilidad de la copia recién creada

- **A (recomendada).** Siempre nace `privado`, salvo que el body de `usar` diga otra cosa. Evita
  que el banco público se llene de duplicados de la misma plantilla.

---

## D9 — Qué hacer con `depende_de_opcion` que apunta fuera del momento copiado

Ver [01_contexto.md](01_contexto.md) §4.
- **A (recomendada).** Si la opción está dentro del árbol copiado → remapear al id nuevo. Si
  apunta a otro momento → dejar `NULL` en la copia y devolver una **advertencia** en la respuesta
  (`advertencias: ["La pregunta 3 dependía de una opción de otro momento; la dependencia se
  quitó."]`). La copia queda válida y el usuario decide.

---

## D10 — `mesas_permitidas` y `roles_permitidos` al copiar a otra jornada

Son listas de números de mesa y de nombres de rol **de la jornada origen**. En la jornada
destino esos roles pueden no existir (`RolJornada` es por jornada).
- **A (recomendada).** Copiar tal cual (son contenido) y, si algún rol no existe como
  `RolJornada` en la jornada destino, agregar una advertencia en la respuesta. Nada se rompe:
  `roles_permitidos` se compara contra `Participante.rol` como texto libre.

---

## D11 — Preguntas inactivas (`activa=False`) al copiar

- **B.** Copiarlas conservando `activa=False`.

---

## D12 — Momentos inactivos y jornadas inactivas en el banco

- **B.** Listar también inactivos con un filtro `?incluir_inactivos=1`.

---

## D13 — Usar varias plantillas de una vez

- **A (recomendada, fase 1).** Un `POST …/usar/` por plantilla; el FE encadena llamadas. Simple, sin semántica de "todo o nada" que definir.

---

## D14 — Registro documental cuando el origen desaparece

`momento_origen` va con `on_delete=SET_NULL`. Si borran el original, la copia pierde el rastro.
- **A (recomendada).** Además de la FK, guardar `origen_info` (JSON) con `{id, titulo,
  jornada_slug, jornada_nombre, creado_por_username, copiado_en}` en el momento copiado. Es lo que
  hace que la relación sea *documental* de verdad: sobrevive al borrado.

---

## D15 — ¿Cambiar la visibilidad requiere ser el creador?

Con D4-A, cualquier propietario de la jornada puede cambiar `visibilidad`. Si prefieres que
publicar/despublicar sea exclusivo del creador + admin (aunque editar el contenido no lo sea),
se implementa como validación en el serializer. **Descicion:** misma regla que D4.

---

## D16 — Fuera de alcance (confirmar)

Doy por **fuera de alcance** de esta iteración, salvo que digas lo contrario:
- Banco de **jornadas completas** (copiar una jornada con todos sus momentos). ESTO ES LA SIGUIENTE FASE. 
- Banco para `instrumentos.Instrumento` (el otro módulo).
- Versionado de plantillas ("actualizar mi copia con los cambios del original"). El enunciado dice
  explícitamente que las copias son aisladas, así que no se contempla.
- Favoritos, calificaciones, categorías/etiquetas del banco. Solo búsqueda por texto y tipo.
- Analítica comparada entre momentos hermanos (misma plantilla en varias jornadas). La relación
  `momento_origen` lo deja posible para después.

---

## Resumen — decisiones cerradas (2026-09-19)

| Decisión | Decisión tomada | Estado |
|---|---|---|
| D1 modelo | **A**: el momento *es* la plantilla; el banco es una vista filtrada. Lo que ven los demás es el momento "vivo". | cerrada |
| D2 nombre | **A**: `banco-momentos` en código y API; "banco de instrumentos" en UI y HU. | cerrada |
| D3 "mío" | **A**: momentos de jornadas donde soy propietario. | cerrada |
| D4 editar | **A**: regla actual (propietarios de la jornada + admin completo). | cerrada |
| D5 admin | **A**: admin completo ve y edita todo, incluidos privados ajenos. | cerrada |
| D6 default | **A**: `privado`. | cerrada |
| D7 backfill | **A**: `creado_por = jornada.creada_por` o `NULL`. | cerrada |
| D8 copia | **A**: la copia nace `privado` salvo que el body diga otra cosa. | cerrada |
| D9 dependencias | **A**: remapear dentro del árbol; fuera del árbol → `NULL` + advertencia. | cerrada |
| D10 mesas/roles | **A**: copiar tal cual; roles inexistentes en destino → advertencia. | cerrada |
| D11 inactivas | **B**: se copian **todas** las preguntas conservando `activa=False` donde aplique. | cerrada (difiere de la recomendación) |
| D12 inactivos | **B**: el listado del banco excluye `activo=False` por defecto y los incluye con `?incluir_inactivos=1`. Detalle, `usar/` y `derivados/` funcionan sobre inactivos sin flag. `Jornada.activa` no filtra. | cerrada (difiere de la recomendación) |
| D13 varias | **A**: una llamada `usar/` por plantilla. | cerrada |
| D14 origen_info | **A**: FK `SET_NULL` + snapshot JSON `origen_info`. | cerrada |
| D15 visibilidad | misma regla que D4. | cerrada |
| D16 alcance | Fuera de esta iteración: banco de `Instrumento`, versionado, favoritos/etiquetas, analítica comparada. **El banco de jornadas completas es la siguiente fase** (ver [06_plan_de_desarrollo.md](06_plan_de_desarrollo.md), Fase 5). | cerrada |

### Consecuencias de D11-B y D12-B sobre el resto del plan

- Copia: se copian todas las `Pregunta` del origen con su flag `activa` tal cual. Una
  dependencia (`depende_de_opcion`) hacia una opción de una pregunta inactiva **sí** se remapea,
  porque esa pregunta ahora existe en la copia (antes era el caso U16; queda absorbido por U14).
- El `Momento` copiado nace siempre `activo=True`, aunque el origen esté inactivo: es un momento
  nuevo en la jornada destino y el usuario decide su estado ahí.
- Banco: el queryset base **no** filtra `activo`. El listado aplica `activo=True` salvo
  `?incluir_inactivos=1`. Detalle, `usar/` y `derivados/` no filtran por `activo`.
- `n_preguntas` en el listado cuenta solo `activa=True` (lo que ve un participante); se agrega
  `n_preguntas_inactivas` para que el usuario sepa que la copia traerá más.
