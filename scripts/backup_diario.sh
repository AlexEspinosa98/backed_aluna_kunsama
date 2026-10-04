#!/usr/bin/env bash
# Respaldo DIARIO de la base de producción de backed_aluna_kunsama (solo la base).
#
# Complementa a backup_produccion.sh, que es el respaldo completo (media, .env, modelos de IA…)
# y es demasiado pesado para correr todos los días. Este es un pg_dump en formato custom, que es
# lo que hizo falta para recuperar las respuestas pisadas en HU-91 — y en ese momento el único
# respaldo que existía era uno manual de dos semanas antes.
#
# Corre por cron en el servidor de producción (usuario hubambiental002):
#   0 8 * * * $HOME/backend_stacks/backed_aluna_kunsama/scripts/backup_diario.sh
# (08:00 UTC = 03:00 en Colombia). Deja:
#   ~/backups/aluna_kunsama/diario/aluna_kunsamu_<fecha>.dump    los últimos 14
#   ~/backups/aluna_kunsama/semanal/aluna_kunsamu_<fecha>.dump   los últimos 8 (copia del domingo)
#   ~/backups/aluna_kunsama/backup_diario.log                   una línea por corrida
#
# Restaurar en una base aparte (para comparar o rescatar datos, como en HU-91):
#   docker exec aluna_kunsama_db createdb -U aluna_kunsamu aluna_respaldo
#   docker exec -i aluna_kunsama_db pg_restore -U aluna_kunsamu -d aluna_respaldo --no-owner --no-acl < <archivo>.dump
#
# OJO: los respaldos quedan en el mismo servidor que la base. Protegen de un error humano (un
# borrado, una carga que pisa datos), no de perder la máquina.
set -euo pipefail

CONTAINER="aluna_kunsama_db"
PGUSER="aluna_kunsamu"
PGDB="aluna_kunsamu"
BASE="$HOME/backups/aluna_kunsama"
DIARIO="$BASE/diario"
SEMANAL="$BASE/semanal"
LOG="$BASE/backup_diario.log"
RETENER_DIARIOS=14
RETENER_SEMANALES=8

mkdir -p "$DIARIO" "$SEMANAL"
chmod 700 "$BASE" "$DIARIO" "$SEMANAL"

FECHA="$(date +%Y%m%d_%H%M%S)"
DESTINO="$DIARIO/${PGDB}_${FECHA}.dump"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }
trap 'log "ERROR: el respaldo falló (línea $LINENO)"; rm -f "$DESTINO.tmp"' ERR

# Se escribe a un .tmp y se renombra solo si terminó bien: un dump a medias nunca queda con el
# nombre de uno bueno ni cuenta para la rotación.
docker exec "$CONTAINER" pg_dump -U "$PGUSER" -d "$PGDB" -Fc -Z 6 > "$DESTINO.tmp"
# Verificación: que pg_restore pueda leer el índice del archivo (detecta un dump truncado).
docker exec -i "$CONTAINER" pg_restore --list < "$DESTINO.tmp" > /dev/null
mv "$DESTINO.tmp" "$DESTINO"
chmod 600 "$DESTINO"

# Domingo: copia semanal.
if [ "$(date +%u)" = "7" ]; then
    cp "$DESTINO" "$SEMANAL/"
fi

# Rotación: se ordena por nombre (lleva la fecha), los más nuevos primero.
ls -1 "$DIARIO"/*.dump 2>/dev/null | sort -r | tail -n +$((RETENER_DIARIOS + 1)) | xargs -r rm -f
ls -1 "$SEMANAL"/*.dump 2>/dev/null | sort -r | tail -n +$((RETENER_SEMANALES + 1)) | xargs -r rm -f

log "OK $(basename "$DESTINO") $(du -h "$DESTINO" | cut -f1) — diarios: $(ls -1 "$DIARIO" | wc -l), semanales: $(ls -1 "$SEMANAL" | wc -l)"
