# Despliegue con Docker

El stack (`docker-compose.yml`) levanta **Postgres + gunicorn**, es decir toda la app. **No
incluye nginx a propósito**: el proxy/TLS de cara al público lo resuelve cada servidor por fuera
del compose (nginx a secas en producción, `nginx-proxy-manager` en el servidor de casa) apuntando
a `127.0.0.1:${APP_PORT}` — exactamente el mismo patrón que ya usa producción con gunicorn detrás
de systemd (ver `project_despliegue` en la memoria del proyecto).

## 1. Qué corre

| Servicio | Imagen | Puerto en el host |
|---|---|---|
| `db` | `postgres:16` | `127.0.0.1:${POSTGRES_PORT:-5432}` |
| `app` | build local (`Dockerfile`) — Django + gunicorn | `127.0.0.1:${APP_PORT:-8000}` |

`app` espera a que `db` pase su healthcheck (`depends_on: condition: service_healthy`) y, en su
arranque (`docker/entrypoint.sh`), corre `migrate` y `collectstatic` **antes** de exec'ar
gunicorn — así un contenedor nuevo nunca sirve tráfico contra un esquema desactualizado.

## 2. Primer arranque (cualquier servidor)

```bash
cp .env.example .env   # y completar SECRET_KEY, POSTGRES_PASSWORD, OPENAI_API_KEY, etc.
docker compose up -d --build
```

El modelo LLM local (2 GB, `analitica/.models/*.gguf`) **no** se descarga solo — se monta desde
`./analitica/.models` (bind mount, ver `docker-compose.yml`). Si el servidor no lo tiene todavía:

```bash
docker compose run --rm app python manage.py download_llm_model
```

(usa el `entrypoint.sh`, así que de paso corre `migrate`; es normal que tarde por la descarga).

## 3. Variables de `.env` propias de Docker

```
APP_PORT=8000          # puerto del HOST donde queda gunicorn — el proxy externo apunta aquí
GUNICORN_WORKERS=3
GUNICORN_TIMEOUT=120
```

El resto de `.env` es el mismo de siempre (`SECRET_KEY`, `POSTGRES_*`, `OPENAI_*`, `MEDIA_URL`,
`ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`…) — **una sola excepción**: dentro del compose,
`POSTGRES_HOST`/`POSTGRES_PORT` los pisa `docker-compose.yml` (`db`/`5432`, el nombre del
servicio en la red interna) sin importar lo que diga `.env`, porque ese archivo normalmente trae
`localhost`, pensado para correr sin Docker.

## 4. Elegir puertos en un servidor con otros proyectos

Antes del primer `up`, revisa qué puertos ya están tomados (`docker ps` en el servidor) y fija
`APP_PORT`/`POSTGRES_PORT` en `.env` a algo libre — los defaults (`8000`/`5432`) casi siempre
chocan con algo si el servidor aloja más de un proyecto.

## 5. Restaurar una jornada de producción completa (base + media + modelo)

Con un respaldo hecho con `scripts/backup_produccion.sh` (ver
`docs/migracion_servidor/RUNBOOK.md`) ya copiado al servidor destino:

```bash
BACKUP=~/backups/aluna_kunsama/<timestamp>

# 1. Base de datos — con el stack ya levantado (`docker compose up -d db`)
docker exec -i aluna_kunsama_db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --no-owner --clean --if-exists < "$BACKUP/db/aluna_kunsamu.dump"

# 2. Archivos: media/, extracciones sueltas, el modelo GGUF y la caché de sentence-transformers
tar -xzf "$BACKUP/app_data.tar.gz" -C .                 # trae media/ y instrumentos/extracciones/
mkdir -p analitica/.models
tar -xzf "$BACKUP/modelos.tar.gz" -C .                  # trae analitica/.models/ y el caché de HF
# si modelos.tar.gz vació el caché fuera de analitica/.models, revisar su estructura interna
# (varía según qué versión del script lo generó) y copiar cada pieza a donde este compose la monta.

# 3. Levantar la app (corre migrate/collectstatic solo) y verificar
docker compose up -d --build
curl -s 127.0.0.1:${APP_PORT:-8000}/api/schema/ | head -3
docker compose exec app python manage.py shell -c \
    "from jornadas.models import Jornada; print(Jornada.objects.count())"
# comparar contra db/conteo_origen.txt del respaldo
```

No hay que crear un `venv` ni instalar nada a mano — todo lo que antes hacía
`scripts/restaurar_produccion.sh` (crear venv, `pip install`, `migrate`, `collectstatic`) ya lo
cubre la imagen + `docker/entrypoint.sh`. Ese script sigue vigente solo para un despliegue **sin**
Docker.

## 6. Comandos sueltos de Django

```bash
docker compose exec app python manage.py <comando>      # con el stack ya arriba
docker compose run --rm app python manage.py <comando>  # sin necesidad de que esté arriba
```

## 7. Logs

```bash
docker compose logs -f app
docker compose logs -f db
```
