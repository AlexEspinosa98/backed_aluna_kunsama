# Plan de implementación — contrato `kunsamu.analisis/v2` en el backend

Plan detallado y **autocontenido** para adaptar el backend (Django/DRF, app `analitica`) a lo que
el frontend espera según la entrega de `docs/mejora_promps/` (20 de septiembre de 2026). Está
escrito para que lo ejecuten modelos pequeños (Sonnet) **fase por fase, sin necesitar ningún otro
contexto** que el de esta carpeta: cada fase dice qué archivos crear o tocar, con el código o la
especificación exacta, cómo verificarlo y qué commit hacer.

> Si eres el modelo que va a ejecutar una fase: lee **este README completo**, después
> `01_contexto_y_estado_actual.md` y `02_decisiones_de_diseno.md`, y por último el archivo de la
> fase que te toca. No leas `docs/enfoque_analisis/` (es un plan viejo que nunca se implementó y
> confunde). No improvises un diseño distinto al de `02_decisiones_de_diseno.md`: las decisiones
> ya están tomadas y argumentadas.

## Índice

| Archivo | Contenido |
|---|---|
| [01_contexto_y_estado_actual.md](01_contexto_y_estado_actual.md) | Todo lo que hay que saber del repo y del contrato para trabajar sin leer nada más: modelos, endpoints, pipelines actuales, convenciones, reglas de trabajo, y la brecha exacta entre lo que hay y lo que el FE espera. |
| [02_decisiones_de_diseno.md](02_decisiones_de_diseno.md) | Las 12 decisiones de diseño (D1–D12) con su razón. Son obligatorias. |
| [03_fase_0_preparacion.md](03_fase_0_preparacion.md) | Fase 0 — dependencias, recursos congelados (esquema + prompts + ejemplos), `analitica/v2/contrato.py`. |
| [04_fase_1_validacion.md](04_fase_1_validacion.md) | Fase 1 — `analitica/v2/validacion.py` (esquema + reglas de negocio) y comando `validar_ejemplos_v2`. |
| [05_fase_2_entrada_y_sin_datos.md](05_fase_2_entrada_y_sin_datos.md) | Fase 2 — `analitica/v2/entrada.py` (sobre normalizado desde la base de datos) y `analitica/v2/sin_datos.py`. |
| [06_fase_3_llm_y_orquestador.md](06_fase_3_llm_y_orquestador.md) | Fase 3 — `analitica/v2/llm.py` (salida estructurada de OpenAI) y `analitica/v2/procesar.py` (orquestador con reintento de reparación). |
| [07_fase_4_modelo_y_api.md](07_fase_4_modelo_y_api.md) | Fase 4 — modelo `AnalisisV2`, migración, serializers, `AnalisisV2ViewSet`, lista unificada, admin, tests de API. Activa el flujo de punta a punta. |
| [08_fase_5_bertopic.md](08_fase_5_bertopic.md) | Fase 5 — `analitica/v2/bertopic_adaptador.py`: pipeline `bertopic_llm` real. |
| [09_fase_6_infografia.md](09_fase_6_infografia.md) | Fase 6 (recomendada, se puede diferir) — la infografía puede generarse a partir de un `AnalisisV2`. |
| [10_fase_7_documentacion_y_cierre.md](10_fase_7_documentacion_y_cierre.md) | Fase 7 — guía de integración para el frontend, HU en `USER_STORIES_COMPLETO.md`, `SYSTEM_PROMPTS.md`, `.env.example`. |
| [11_verificacion_y_smoke.md](11_verificacion_y_smoke.md) | Cómo verificar cada fase sin correr la suite, prueba de humo contra el servidor de `develop`, y plan de reversa. |

## Orden de ejecución y dependencias

```
Fase 0 ──► Fase 1 ──► Fase 2 ──► Fase 3 ──► Fase 4 ──► Fase 5 ──► Fase 6 (opcional) ──► Fase 7
(recursos) (validar)  (entrada)  (llm+orq)  (modelo+API) (bertopic)  (infografía)        (docs/HU)
```

- Las fases 1, 2 y 3 producen **funciones puras** (sin modelo nuevo, sin endpoint); se verifican
  con `py_compile` y con el comando de la fase 1. Nada de lo que hacen se ve desde la API hasta
  la fase 4.
- La fase 4 es la que "enciende" el flujo: crea el modelo, la migración y el endpoint. A partir de
  ahí, un `POST /api/admin/analisis-v2/` con `pipeline=llm` funciona de punta a punta.
- Hasta que se haga la fase 5, `pipeline=bertopic_llm` **funciona pero sin ejecuciones BERTopic**
  (el adaptador es un stub que declara `ejecuciones: []`, que es una entrada válida según el
  contrato). La fase 5 reemplaza el stub por el adaptador real.
- La fase 6 es independiente de la 5. La fase 7 va siempre al final.

## Reglas de trabajo (obligatorias, vienen del dueño del repo)

1. **Rama**: se trabaja y commitea directo en `develop` (la rama actual). Sin PR, sin ramas de
   feature, sin worktrees. **Cada push a `develop` despliega automáticamente** en el servidor de
   pruebas (`https://kunsamu.josec.ddns.net`, contenedor `git-sync`, ver `docs/DOCKER.md`).
   Pasar a `main` (producción) es decisión del dueño del repo, no de este plan.
2. **`git add` SIEMPRE con rutas explícitas, NUNCA `git add -A` ni `git add .`.** En el working
   directory hay cambios en `Dockerfile` y `docker-compose.yml` que el dueño pidió explícitamente
   **NO commitear ni pushear hasta que él lo diga**. Ningún commit de este plan debe incluirlos.
   Antes de cada commit: `git status --short` y confirmar que esos dos archivos siguen como ` M`
   sin estar en el stage.
3. **No correr la suite de tests** (`manage.py test`) salvo que el dueño lo pida explícitamente.
   Sí se escriben los tests que cada fase indica (quedan listos para cuando él decida correrlos).
   La verificación por defecto es `python -m py_compile <archivo>` sobre cada `.py` tocado, más
   los comandos concretos que indica cada fase. Al entregar una fase, decir en una línea qué quedó
   sin probar y cuál es el riesgo.
4. **Cada feature termina documentado como HU** en `docs/USER_STORIES_COMPLETO.md` (la fase 7 lo
   hace para todo el plan; no hace falta una HU por fase).
5. **Mensajes de commit** en español, en el estilo del repo: `feat: …` / `fix: …` / `docs: …`, con
   una primera línea corta y, si hace falta, un cuerpo que explique el *porqué*. Cerrar el mensaje
   con el pie de atribución que indique el entorno de la sesión (líneas `Co-Authored-By:` /
   `Claude-Session:`), si lo indica.
6. **Nunca exponer el nombre real del modelo de OpenAI** en nada que devuelva la API: el campo
   `modelo_usado` lleva la etiqueta genérica (`'Generado con IA'`), igual que en el resto del módulo.
7. **No tocar los pipelines legacy** (`analitica/analysis.py`, `analitica/analisis_ia_openai.py`,
   `analitica/prompt_comun.py`, `analitica/presentacion.py`, `analitica/pdf_presentacion.py`,
   `analitica/reporte_excel.py`, `analitica/sugerencias_ia_openai.py`) salvo lo que una fase
   indique explícitamente (solo la fase 4 toca `admin_views.py` para la lista unificada, y la fase
   6 toca `infografia_ia_openai.py`). Los resultados históricos deben seguir viéndose igual.
8. Python 3.12, Django 5.2, DRF. Estilo del repo: comillas simples, líneas ≤ 100 caracteres,
   comentarios en español que expliquen el **porqué**, no el qué. Sin `print` de depuración.

## Entorno local para verificar

```bash
cd /Users/jfcc/backed_aluna_kunsama
source .venv/bin/activate            # el venv ya tiene Django 5.2.17, openai 3.x, jsonschema 4.26, bertopic 0.17
python -m py_compile analitica/v2/validacion.py   # ejemplo de verificación por archivo
python manage.py validar_ejemplos_v2              # existe desde la fase 1
python manage.py makemigrations analitica --check --dry-run   # desde la fase 4: debe decir "No changes detected"
```

`manage.py` necesita `.env` (ya existe en el checkout) y una base Postgres accesible para los
comandos que tocan la base; `makemigrations --check`, `py_compile` y `validar_ejemplos_v2` (sin
`--analisis`) no la necesitan.

## Cómo reportar al terminar una fase

Un párrafo corto: qué archivos se crearon/modificaron, qué comando de verificación se corrió y
qué dio, hash del commit, y la línea de "qué quedó sin probar y cuál es el riesgo". Si algo del
plan resultó imposible o incorrecto contra el código real, **decirlo explícitamente en el
reporte** en vez de improvisar otra cosa en silencio.
