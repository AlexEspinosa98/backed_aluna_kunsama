# 11 — Verificación, prueba de humo en `develop` y plan de reversa

## 1. Verificación por fase, sin correr la suite

| Fase | Comando(s) | Resultado esperado |
|---|---|---|
| 0 | `python -m py_compile analitica/v2/contrato.py` + script del paso 0.4 | `OK recursos` |
| 1 | `python manage.py validar_ejemplos_v2` | 5 `OK`, 6 `OK rechazada`, línea final en verde |
| 2 | script del paso 2.4 | `OK sin_datos` |
| 3 | script del paso 3.4 | `OK llm` |
| 4 | `python manage.py makemigrations analitica --check --dry-run`; `python manage.py check` | `No changes detected`; `no issues` |
| 5 | script del paso 5.3 | `OK adaptador` |
| 6 | `makemigrations --check`; `manage.py check` | limpio |
| 7 | enlaces de los `.md` resuelven | — |

Siempre, para cada `.py` tocado: `python -m py_compile <ruta>`.

Si el dueño del repo pide correr la suite: `python manage.py test analitica.tests_v2` (solo los
nuevos, ~segundos sin base pesada) o `python manage.py test` (completa, 329+ tests, ~40 s).
Necesita Postgres accesible según `.env` (crea una base de test).

## 2. Prueba de humo contra el servidor de pruebas (`develop`)

Cada push a `develop` reconstruye el contenedor `app` en `https://kunsamu.josec.ddns.net`
(tarda 1–3 min). Hace falta un token de admin (`POST /api/admin/login/` con usuario/contraseña
staff → `{"token": "..."}`).

```bash
BASE=https://kunsamu.josec.ddns.net
TOKEN=<token>
H="Authorization: Token $TOKEN"

# 0. El servidor y la migración 0017 están arriba
curl -s $BASE/                                  # {"status":"ok","database":"ok",...}
curl -s -H "$H" "$BASE/api/admin/analisis-v2/"  # [] o lista

# 1. Elegir una jornada con respuestas y ver sus momentos
curl -s -H "$H" "$BASE/api/admin/jornadas/" | python -m json.tool | head -40
JORNADA=<id>

# 2. Pedir un análisis integral con pipeline llm
curl -s -H "$H" -H 'Content-Type: application/json' -X POST "$BASE/api/admin/analisis-v2/" \
  -d "{\"jornada\": $JORNADA, \"modo\": \"integral\", \"pipeline\": \"llm\", \"contexto\": \"Prueba de humo v2\"}"
# → 201 con "estado": "pendiente". Guardar el id:
ID=<id>

# 3. Polling hasta completo|error (un integral grande con modelo de razonamiento puede tardar 3–8 min)
watch -n 10 "curl -s -H '$H' '$BASE/api/admin/analisis-v2/$ID/' | python -c 'import json,sys; d=json.load(sys.stdin); print(d[\"estado\"], d[\"estado_analitico\"], d[\"error_mensaje\"][:200])'"

# 4. Con estado completo: inspeccionar
curl -s -H "$H" "$BASE/api/admin/analisis-v2/$ID/" | python -c '
import json,sys; d=json.load(sys.stdin); r=d["resultado"]
print("estado analitico:", r["estado"]); print("informes:", len(r["informes"]), "cobertura:", len(r["cobertura"]), "visualizaciones:", len(r["visualizaciones"]))
for i in r["informes"]:
    print("-", i["titulo"], "| hallazgos:", len(i["hallazgos"]), "| recomendaciones:", len(i["recomendaciones"]))
print("diagnostico intentos:", [(x["n"], x.get("error"), (x.get("meta") or {}).get("modo_salida"), (x.get("meta") or {}).get("finish_reason")) for x in d["diagnostico"]["intentos"]])
print("modelo_usado:", d["modelo_usado"], "| versiones:", d["version_prompt"], d["version_esquema"])'

# 5. Los mismos datos en la lista unificada
curl -s -H "$H" "$BASE/api/admin/analisis/?jornada=$JORNADA" | python -c 'import json,sys; print([ (i["tipo"], i["id"], i["estado"], i.get("estado_analitico")) for i in json.load(sys.stdin)])'

# 6. Repetir con por_momento (dos momentos) y con pipeline bertopic_llm (fase 5)
curl -s -H "$H" -H 'Content-Type: application/json' -X POST "$BASE/api/admin/analisis-v2/" \
  -d "{\"jornada\": $JORNADA, \"modo\": \"por_momento\", \"momentos\": [<m1>, <m2>], \"pipeline\": \"bertopic_llm\"}"

# 7. Un alcance sin respuestas debe terminar `completo` con estado_analitico `sin_datos` sin gastar llamada
#    (diagnostico.intentos == [] y modelo_usado == "Sin datos — generado por el backend sin IA")

# 8. Errores esperados
#    - mismo alcance dos veces seguidas mientras procesa → 409
#    - integral con "momentos": [x] → 400 {"momentos": [...]}
#    - por_momento sin momentos → 400
```

Validar una respuesta real guardada, desde dentro del contenedor:

```bash
ssh <servidor>
cd <ruta del proyecto> && docker compose exec app python manage.py validar_ejemplos_v2 --analisis $ID
# OK AnalisisV2 <id>: esquema y reglas de negocio   (si terminó completo, DEBE pasar: es lo que se validó antes de publicar)
```

Logs del hilo de background (errores de OpenAI, BERTopic, tiempos):

```bash
docker compose logs --since 30m app | grep -iE "analisis|v2|error|traceback" | tail -50
```

## 3. Qué mirar en la primera respuesta real del modelo (QA de calidad, no de forma)

La validación garantiza forma y consistencia, no calidad analítica. Revisar a mano en 1–2
análisis reales:

- `cobertura`: que las preguntas con datos estén `analizada` y las sin datos `sin_datos` (no
  `no_recibida`, que significaría que el modelo cree que faltó una fuente).
- `citas`: abrir 3–4 localizadores contra `entrada` y confirmar que son textos de participantes.
- `metricas` con `origen: reportado`: que las rutas apunten a `f-agg-m…/distribuciones/…` y las
  cifras coincidan con esa distribución.
- `visualizaciones`: que no haya adornos (una dona con 8 categorías, un radar sin rango) —
  si aparecen, el validador debería haberlas rechazado; si pasaron, es una regla que falta.
- `limitaciones`: pocas y concretas, no advertencias genéricas.
- Que `diagnostico.intentos` tenga 1 entrada (sin reparación) en la mayoría de los casos. Si casi
  todos necesitan la reparación, anotar qué errores se repiten: probablemente hay que ajustar una
  regla (o es un patrón del modelo que vale la pena reportar al dueño).

## 4. Plan de reversa

Cada fase es un commit independiente en `develop`. Para revertir:

```bash
git revert <hash>               # una fase; revertir en orden inverso si son varias
git push origin develop         # redeploy automático
```

Las migraciones `0017`/`0018` **no** se revierten solas con `git revert`: si se revierte la fase
4 o 6 hay que, además, en el servidor, `docker compose exec app python manage.py migrate analitica
0016` (o `0017` si solo se revierte la 6) ANTES de que arranque el código sin esas migraciones —
si no, Django arrancará igual (las tablas sobrantes no molestan) pero `makemigrations --check`
quedará inconsistente. Las tablas nuevas no afectan a nada legacy: dejar `0017` aplicada mientras
se decide es seguro.

Nada de este plan modifica datos existentes: no hay migraciones de datos ni cambios en tablas
legacy (la fase 6 solo agrega una columna nullable a `analitica_infografiajornada`).

## 5. Riesgos conocidos y cómo se mitigan

| Riesgo | Mitigación |
|---|---|
| El proveedor rechaza `response_format: json_schema` con el esquema (p. ej. límite de tamaño o keyword no soportada) | Respaldo automático a `json_object` + esquema en el system (D6); se ve en `diagnostico.intentos[].meta.modo_salida`. Si pasa siempre, reportarlo: conviene revisar el esquema contra la documentación de Structured Outputs. |
| Salida truncada por `max_completion_tokens` en jornadas grandes | Error explícito `finish_reason=length`; subir `KUNSAMU_V2_MAX_OUTPUT_TOKENS` o pedir `por_momento`. |
| Entrada mayor al contexto del modelo | Guard `KUNSAMU_V2_MAX_CARACTERES_ENTRADA` → `error` con mensaje que pide `por_momento`. Codificación por lotes queda fuera de alcance (D10). |
| El modelo no logra pasar la validación ni con reparación | `estado=error`, todo en `diagnostico`. Es el comportamiento pedido por la entrega ("no publicar"). Revisar los errores repetidos. |
| BERTopic lento/fallando en una pregunta | Solo esa pregunta queda sin ejecución (nota en `diagnostico.bertopic`); el análisis sigue. Primera corrida descarga embeddings. |
| Dos análisis v2 pesados en paralelo en un servidor chico | Permitido por diseño (alcances distintos); si el servidor sufre, el dueño puede bajar `KUNSAMU_OPENAI_CONCURRENCIA_MAXIMA` (legacy) — para v2 no hay pool: es una llamada por análisis. |
| Se olvida `git add` explícito y entra `Dockerfile`/`docker-compose.yml` | `git status --short` antes de cada commit; si pasó, `git reset HEAD~1 --soft` y rehacer el commit sin esos archivos, ANTES de pushear. |
