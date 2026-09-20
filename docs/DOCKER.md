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

# 2a. Archivos: media/, extracciones sueltas, staticfiles/, .env real de producción
tar -xzf "$BACKUP/app_data.tar.gz" -C .

# 2b. Modelo GGUF + caché de sentence-transformers — el tar mezcla dos raíces distintas
# (analitica/.models/ relativo al proyecto, y el caché de HF relativo a ~/.cache/huggingface/hub/),
# así que se extrae a un lugar de paso y cada pieza se mueve a donde este compose la monta:
rm -rf /tmp/modelos_kunsama && mkdir -p /tmp/modelos_kunsama analitica/.models .hf_cache/hub
tar -xzf "$BACKUP/modelos.tar.gz" -C /tmp/modelos_kunsama
cp -a /tmp/modelos_kunsama/analitica/.models/. analitica/.models/
cp -a /tmp/modelos_kunsama/models--*/. .hf_cache/hub/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2/ 2>/dev/null \
    || cp -a /tmp/modelos_kunsama/models--* .hf_cache/hub/
rm -rf /tmp/modelos_kunsama
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

## 8. Auto-deploy — redeploy automático al cambiar `develop`

Servicio opcional `git-sync` (nombre por lo que hace, no el binario oficial — ver el comentario
al inicio de `docker/redeploy-watcher.sh` de por qué esa imagen oficial no sirve acá sin
agregarle herramientas: es deliberadamente mínima, sin shell ni CLI de Docker, así que no puede
disparar un rebuild real por sí sola). Cada `${GIT_SYNC_PERIOD_SECONDS:-30}`s hace `git fetch` de
`origin/${GIT_SYNC_BRANCH:-develop}` y, si hay un commit nuevo, `git pull --ff-only` +
`docker compose up -d --build app` — automatiza lo que hasta ahora se corría a mano por SSH tras
cada push.

**⚠️ Antes de activarlo, pesar esto:** el contenedor necesita el socket de Docker del host
montado (`/var/run/docker.sock`) para poder reconstruir `app` sin que nadie entre por SSH — eso
le da la MISMA capacidad que cualquier proceso con acceso a ese socket, es decir, control total
sobre **todo** Docker en ese servidor, no solo los contenedores de este proyecto. En un servidor
compartido con otros proyectos (como el de casa), es una decisión real de seguridad, no un
detalle — por eso está detrás de un profile y nunca arranca con un `up -d` a secas.

**No está pensado para producción tal cual.** Este servicio asume acceso de escritura al repo por
SSH y ningún gate de aprobación entre "hay un commit en `develop`" y "se reconstruye la app en
este servidor" — perfecto para un servidor de pruebas donde quien empuja a `develop` ya tiene
control del servidor de todos modos, mal encaje para un entorno donde el despliegue debería pasar
por una revisión o un pipeline de CI antes de tocar producción.

Requisitos antes de activarlo:

```bash
# En .env de ESE servidor:
HOST_REPO_PATH=/ruta/absoluta/en/el/host/a/este/proyecto   # ej. /home/usuario/projects/kunsama
GIT_SYNC_BRANCH=develop
GIT_SYNC_PERIOD_SECONDS=30
```

`HOST_REPO_PATH` tiene que ser la ruta **tal como existe en el disco del host**, no una ruta
dentro de un contenedor — el contenedor habla con el daemon de Docker del host a través del
socket (docker-fuera-de-docker), así que cualquier ruta que le pase a `docker compose` tiene que
poder resolverse en el disco real; por eso el volumen monta el working directory en la MISMA ruta
adentro y afuera, en vez de en algo como `/repo`.

También usa la llave SSH ya autorizada del usuario del sistema (`${HOME}/.ssh`, de solo lectura)
para el `git fetch`/`pull` de un repo privado — la misma que se generó en
`docs/migracion_servidor/` o al configurar este servidor, no una nueva.

Activarlo:

```bash
docker compose --profile auto-deploy up -d
```

Desactivarlo (para todo lo demás sigue funcionando igual, sin el vigilante):

```bash
docker compose stop git-sync
docker compose rm -f git-sync
```

Logs:

```bash
docker compose logs -f git-sync
```
