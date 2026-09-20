#!/usr/bin/env bash
# Respaldo completo de producción de backed_aluna_kunsama.
#
# Se ejecuta EN el servidor de producción (usuario hubambiental002).
# Produce en ~/backups/aluna_kunsama/<timestamp>/ :
#   db/aluna_kunsamu.dump        pg_dump formato custom (para pg_restore)
#   db/aluna_kunsamu.sql.gz      pg_dump formato plano (legible / psql)
#   db/globals.sql               roles y contraseñas (pg_dumpall --globals-only)
#   db/verificacion.txt          conteo por tabla origen vs restauración de prueba
#   app_data.tar.gz              media/, instrumentos/extracciones/, staticfiles/, .env,
#                                logs, docker-compose.yml, README, presentación suelta
#   sistema/                     unit de systemd, bloque nginx, pip freeze, git HEAD/status
#   modelos.tar.gz               analitica/.models (gguf) + modelo sentence-transformers
#   SHA256SUMS                   integridad de todo lo anterior
#   MANIFEST.txt                 resumen
#
# Uso:  bash backup_produccion.sh [--sin-modelos]
set -euo pipefail

APP_DIR="$HOME/backend_stacks/backed_aluna_kunsama"
CONTAINER="aluna_kunsama_db"
PGUSER="aluna_kunsamu"
PGDB="aluna_kunsamu"
HF_MODEL_DIR="$HOME/.cache/huggingface/hub/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
TS="$(date +%Y%m%d_%H%M%S)"
BK="$HOME/backups/aluna_kunsama/$TS"
SIN_MODELOS=0
[[ "${1:-}" == "--sin-modelos" ]] && SIN_MODELOS=1

log() { printf '\n==> %s\n' "$*"; }

mkdir -p "$BK/db" "$BK/sistema"
chmod 700 "$HOME/backups" "$HOME/backups/aluna_kunsama" "$BK"
cd "$APP_DIR"

# ---------------------------------------------------------------- base de datos
log "pg_dump (custom) de $PGDB"
docker exec "$CONTAINER" pg_dump -U "$PGUSER" -d "$PGDB" -Fc -Z 6 > "$BK/db/$PGDB.dump"

log "pg_dump (plano) de $PGDB"
docker exec "$CONTAINER" pg_dump -U "$PGUSER" -d "$PGDB" --format=plain | gzip -6 > "$BK/db/$PGDB.sql.gz"

log "pg_dumpall --globals-only (roles)"
docker exec "$CONTAINER" pg_dumpall -U "$PGUSER" --globals-only > "$BK/db/globals.sql"

log "Verificación: restaurar en base temporal y comparar conteos por tabla"
VERIFY_DB="${PGDB}_verify_$TS"
docker exec "$CONTAINER" psql -U "$PGUSER" -d postgres -qc "CREATE DATABASE \"$VERIFY_DB\";"
# El dump ya está en el host; se lo pasamos al contenedor por stdin.
docker exec -i "$CONTAINER" pg_restore -U "$PGUSER" -d "$VERIFY_DB" --no-owner --exit-on-error < "$BK/db/$PGDB.dump"

conteos() {
  # imprime "schema.tabla|filas" ordenado, para la base indicada
  local db="$1"
  docker exec "$CONTAINER" psql -U "$PGUSER" -d "$db" -Atc \
    "SELECT schemaname||'.'||tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1" \
  | while read -r t; do
      n=$(docker exec "$CONTAINER" psql -U "$PGUSER" -d "$db" -Atc "SELECT count(*) FROM $t")
      echo "$t|$n"
    done
}
conteos "$PGDB"      > "$BK/db/conteo_origen.txt"
conteos "$VERIFY_DB" > "$BK/db/conteo_restaurado.txt"
docker exec "$CONTAINER" psql -U "$PGUSER" -d postgres -qc "DROP DATABASE \"$VERIFY_DB\";"

{
  echo "Verificación de restauración ($TS)"
  echo "Tablas origen:      $(wc -l < "$BK/db/conteo_origen.txt")"
  echo "Tablas restauradas: $(wc -l < "$BK/db/conteo_restaurado.txt")"
  echo "Filas origen:       $(awk -F'|' '{s+=$2} END{print s}' "$BK/db/conteo_origen.txt")"
  echo "Filas restauradas:  $(awk -F'|' '{s+=$2} END{print s}' "$BK/db/conteo_restaurado.txt")"
  if diff -q "$BK/db/conteo_origen.txt" "$BK/db/conteo_restaurado.txt" >/dev/null; then
    echo "RESULTADO: OK — conteos idénticos en todas las tablas"
  else
    echo "RESULTADO: DIFERENCIAS"
    diff "$BK/db/conteo_origen.txt" "$BK/db/conteo_restaurado.txt" || true
  fi
  echo
  echo "Conteo por tabla (origen):"
  cat "$BK/db/conteo_origen.txt"
} > "$BK/db/verificacion.txt"
grep RESULTADO "$BK/db/verificacion.txt"

# ---------------------------------------------------------------- datos de la app
log "Configuración del sistema"
git rev-parse HEAD > "$BK/sistema/git_HEAD.txt"
git status --porcelain > "$BK/sistema/git_status.txt" || true
git diff > "$BK/sistema/git_diff_local.patch" || true
venv/bin/pip freeze > "$BK/sistema/pip_freeze.txt"
venv/bin/python --version > "$BK/sistema/python_version.txt" 2>&1
systemctl cat aluna-kunsama-backend.service > "$BK/sistema/aluna-kunsama-backend.service" 2>/dev/null || true
cp /etc/nginx/sites-enabled/backend "$BK/sistema/nginx_backend.conf" 2>/dev/null || true
docker exec "$CONTAINER" psql -U "$PGUSER" -d "$PGDB" -Atc "SELECT version()" > "$BK/sistema/postgres_version.txt"
docker inspect "$CONTAINER" > "$BK/sistema/docker_inspect_db.json"

log "app_data.tar.gz (media, extracciones, staticfiles, .env, logs, compose)"
# Lista explícita: todo lo que NO se reconstruye desde git.
tar -czf "$BK/app_data.tar.gz" \
  --ignore-failed-read \
  media \
  instrumentos/extracciones \
  staticfiles \
  .env \
  .env.example \
  docker-compose.yml \
  gunicorn-access.log \
  gunicorn-error.log \
  Presentacion_Tejiendo_saberes_M1-M3.html

# ---------------------------------------------------------------- modelos
if [[ $SIN_MODELOS -eq 0 ]]; then
  log "modelos.tar.gz (gguf local + sentence-transformers)"
  tar -czf "$BK/modelos.tar.gz" \
    --ignore-failed-read \
    -C "$APP_DIR" analitica/.models \
    -C "$HOME/.cache/huggingface/hub" "$(basename "$HF_MODEL_DIR")"
else
  log "Modelos omitidos (--sin-modelos)"
fi

# ---------------------------------------------------------------- integridad
log "SHA256SUMS y MANIFEST"
( cd "$BK" && find . -type f ! -name SHA256SUMS ! -name MANIFEST.txt -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
{
  echo "Respaldo backed_aluna_kunsama — $TS"
  echo "Host: $(hostname)   App: $APP_DIR   Git: $(cat "$BK/sistema/git_HEAD.txt")"
  echo "Postgres: $(cat "$BK/sistema/postgres_version.txt")"
  echo
  echo "Archivos media: $(find media -type f | wc -l)"
  echo "Extracciones sueltas: $(find instrumentos/extracciones -type f 2>/dev/null | wc -l)"
  echo
  grep RESULTADO "$BK/db/verificacion.txt"
  echo
  du -sh "$BK"/* | sed 's#'"$BK"'/##'
} > "$BK/MANIFEST.txt"

log "Listo: $BK"
cat "$BK/MANIFEST.txt"
