#!/bin/sh
# Punto de entrada del contenedor de la app. Corre SIEMPRE antes del comando real (gunicorn, o
# `manage.py` suelto para un comando puntual — ver docs/DOCKER.md) porque está en ENTRYPOINT, no
# en CMD: así `docker compose run app python manage.py shell` también espera a la base y aplica
# migraciones antes de darte la shell, en vez de fallar contra un esquema desactualizado.
set -e

if [ -n "$POSTGRES_HOST" ]; then
    echo "Esperando a Postgres en ${POSTGRES_HOST}:${POSTGRES_PORT:-5432}..."
    # Un chequeo de socket basta acá: el healthcheck real (pg_isready, que sí valida que el
    # servidor terminó de arrancar y no solo que el puerto está abierto) ya lo exige
    # `depends_on.condition: service_healthy` en docker-compose.yml antes de crear este
    # contenedor. Esto es solo la red de seguridad para cuando el contenedor se corre suelto
    # (`docker run`, sin compose) y ese `depends_on` no aplica.
    hasta=$(($(date +%s) + 60))
    until python -c "
import os, socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2)
try:
    s.connect((os.environ['POSTGRES_HOST'], int(os.environ.get('POSTGRES_PORT', 5432))))
except OSError:
    sys.exit(1)
"; do
        if [ "$(date +%s)" -ge "$hasta" ]; then
            echo "Postgres no respondió tras 60s — abortando." >&2
            exit 1
        fi
        sleep 1
    done
    echo "Postgres disponible."
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput --clear

exec "$@"
