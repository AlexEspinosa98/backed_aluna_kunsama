#!/usr/bin/env bash
# Restaura un respaldo producido por scripts/backup_produccion.sh en un servidor NUEVO.
#
# Precondiciones en el servidor nuevo (ver docs/migracion_servidor/RUNBOOK.md):
#   - Docker instalado y el usuario en el grupo docker.
#   - Repo clonado en $APP_DIR con el MISMO commit que sistema/git_HEAD.txt del respaldo.
#   - El directorio del respaldo copiado al servidor (p. ej. ~/backups/aluna_kunsama/<ts>).
#
# Uso:  bash restaurar_produccion.sh /ruta/al/respaldo/<timestamp>
#
# Es idempotente sobre la base: DESTRUYE el esquema public de la base destino y lo
# vuelve a crear desde el dump. Solo debe correrse en el servidor nuevo, nunca en el viejo.
set -euo pipefail

BK="${1:?Uso: $0 /ruta/al/respaldo/<timestamp>}"
APP_DIR="${APP_DIR:-$HOME/backend_stacks/backed_aluna_kunsama}"
CONTAINER="aluna_kunsama_db"
PGUSER="aluna_kunsamu"
PGDB="aluna_kunsamu"

log() { printf '\n==> %s\n' "$*"; }

[[ -f "$BK/SHA256SUMS" ]] || { echo "No parece un respaldo válido: falta $BK/SHA256SUMS"; exit 1; }
[[ -d "$APP_DIR/.git" ]] || { echo "No existe el repo en $APP_DIR"; exit 1; }

log "Integridad del respaldo"
( cd "$BK" && sha256sum -c --quiet SHA256SUMS ) && echo "SHA256 OK"

log "Commit del respaldo vs. repo"
ESPERADO="$(cat "$BK/sistema/git_HEAD.txt")"
ACTUAL="$(git -C "$APP_DIR" rev-parse HEAD)"
if [[ "$ESPERADO" != "$ACTUAL" ]]; then
  echo "AVISO: el respaldo se hizo en $ESPERADO y el repo está en $ACTUAL."
  echo "       Si el repo es más nuevo, 'manage.py migrate' aplicará lo que falte. Continúo."
fi

cd "$APP_DIR"

log "Restaurando .env y datos de la app (media, extracciones, staticfiles, logs)"
tar -xzf "$BK/app_data.tar.gz" -C "$APP_DIR"
chmod 600 .env

if [[ -f "$BK/modelos.tar.gz" ]]; then
  log "Restaurando modelos (analitica/.models y caché de sentence-transformers)"
  mkdir -p "$HOME/.cache/huggingface/hub"
  # El tar tiene dos raíces: analitica/.models (relativo a APP_DIR) y models--sentence-transformers--...
  tar -xzf "$BK/modelos.tar.gz" -C "$APP_DIR" --wildcards 'analitica/*'
  tar -xzf "$BK/modelos.tar.gz" -C "$HOME/.cache/huggingface/hub" --wildcards 'models--*'
fi

log "Levantando Postgres (docker compose)"
docker compose up -d db
for i in $(seq 1 30); do
  docker exec "$CONTAINER" pg_isready -U "$PGUSER" >/dev/null 2>&1 && break
  sleep 2
done
docker exec "$CONTAINER" pg_isready -U "$PGUSER"

log "Roles (globals)"
# El rol aluna_kunsamu ya existe porque lo crea la imagen con POSTGRES_USER; los errores
# 'already exists' son esperados. Se aplica igual por si hubiera otros roles.
docker exec -i "$CONTAINER" psql -U "$PGUSER" -d postgres -q < "$BK/db/globals.sql" 2>&1 | grep -v 'already exists' || true

log "Restaurando base $PGDB (esquema public recreado desde cero)"
docker exec "$CONTAINER" psql -U "$PGUSER" -d "$PGDB" -qc "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"
docker exec -i "$CONTAINER" pg_restore -U "$PGUSER" -d "$PGDB" --no-owner --exit-on-error < "$BK/db/$PGDB.dump"

log "Verificación: conteo por tabla vs. origen"
docker exec "$CONTAINER" psql -U "$PGUSER" -d "$PGDB" -Atc \
  "SELECT schemaname||'.'||tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1" \
| while read -r t; do
    n=$(docker exec "$CONTAINER" psql -U "$PGUSER" -d "$PGDB" -Atc "SELECT count(*) FROM $t")
    echo "$t|$n"
  done > "$BK/db/conteo_destino.txt"
if diff -q "$BK/db/conteo_origen.txt" "$BK/db/conteo_destino.txt" >/dev/null; then
  echo "RESULTADO: OK — la base restaurada tiene exactamente las mismas filas por tabla que el origen"
else
  echo "RESULTADO: DIFERENCIAS entre origen y destino:"
  diff "$BK/db/conteo_origen.txt" "$BK/db/conteo_destino.txt" || true
  exit 1
fi

log "Verificación: archivos media"
echo "media en respaldo: $(tar -tzf "$BK/app_data.tar.gz" | grep -c '^media/.*[^/]$')"
echo "media en disco:    $(find media -type f | wc -l)"

log "Entorno Python"
if [[ ! -x venv/bin/python ]]; then
  python3 -m venv venv
fi
venv/bin/pip install -q -r requirements.txt
venv/bin/python manage.py migrate --noinput
venv/bin/python manage.py collectstatic --noinput
venv/bin/python manage.py check --deploy || true

cat <<EOF

Restauración de datos terminada. Falta (con sudo, ver RUNBOOK):
  1. sudo cp $BK/sistema/aluna-kunsama-backend.service /etc/systemd/system/
     (ajustar rutas si el usuario/home cambian) y sudo systemctl daemon-reload
  2. Bloque nginx de $BK/sistema/nginx_backend.conf (locations /api/aluna-kunsama/...)
  3. sudo systemctl enable --now aluna-kunsama-backend.service
  4. Probar: curl -s https://<host>/api/aluna-kunsama/api/schema/ | head
EOF
