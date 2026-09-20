# Migración de producción a otro servidor físico

Objetivo: mover `backed_aluna_kunsama` a un servidor nuevo **sin perder ningún dato**,
ni de base de datos ni de archivos generados.

## 1. Qué hay que llevarse (inventario de producción, 2026-09-20)

Todo lo que **no** se reconstruye clonando el repo:

| Qué | Dónde en el servidor viejo | Tamaño | Cómo viaja |
|---|---|---|---|
| Base de datos Postgres 16 (`aluna_kunsamu`, 49 tablas) | Docker `aluna_kunsama_db`, volumen `aluna_kunsama_pg_data`, puerto `127.0.0.1:5433` | 17 MB | `db/aluna_kunsamu.dump` (custom) + `db/aluna_kunsamu.sql.gz` (plano) + `db/globals.sql` (roles) |
| Archivos subidos y generados (`MEDIA_ROOT`) | `media/` → `jornadas/assets`, `analitica/infografias`, `participantes/extracciones` | 163 MB, 56 archivos | `app_data.tar.gz` |
| Extracciones sueltas fuera de `media/` | `instrumentos/extracciones/2026/09/*.docx` (2 archivos, no versionados) | 92 KB | `app_data.tar.gz` |
| Secretos y configuración | `.env` (SECRET_KEY, POSTGRES_*, OPENAI_API_KEY, MEDIA_URL, CORS…) | — | `app_data.tar.gz` (permisos 600 al restaurar) |
| Estáticos compilados | `staticfiles/` (regenerable con `collectstatic`) | 3.4 MB | `app_data.tar.gz` |
| Logs históricos de gunicorn | `gunicorn-access.log`, `gunicorn-error.log` | 3.6 MB | `app_data.tar.gz` |
| Presentación suelta no versionada | `Presentacion_Tejiendo_saberes_M1-M3.html` | 1.7 MB | `app_data.tar.gz` |
| Modelo LLM local | `analitica/.models/qwen2.5-3b-instruct-q4_k_m.gguf` (gitignored) | 2.0 GB | `modelos.tar.gz` |
| Modelo de embeddings | `~/.cache/huggingface/hub/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2` | ~0.5 GB | `modelos.tar.gz` |
| Unit de systemd | `/etc/systemd/system/aluna-kunsama-backend.service` | — | `sistema/` |
| Bloque nginx (prefijo `/api/aluna-kunsama/`) | `/etc/nginx/sites-enabled/backend` | — | `sistema/nginx_backend.conf` |
| Versiones exactas | `pip freeze`, versión de Python y Postgres, `git HEAD` | — | `sistema/` |

Lo que **sí** se reconstruye y no hace falta copiar: el código (git), `venv/` (5.7 GB,
`pip install -r requirements.txt`), `__pycache__`. Los modelos son descargables de nuevo,
pero se incluyen para que el servidor nuevo funcione sin internet ni espera.

La app **no** usa el Mongo ni las otras bases que corren en el mismo servidor; son de
otros proyectos (`agrohub`, `aluna_propositos_backend`).

## 2. Cómo se garantiza que no se pierde nada

- `pg_dump` toma una **instantánea transaccional**: la base queda consistente aunque haya
  escrituras durante el volcado.
- El script de respaldo **restaura el dump en una base temporal** dentro del mismo
  contenedor y compara el conteo de filas de las 49 tablas contra el origen antes de
  declarar el respaldo válido (`db/verificacion.txt`).
- Todo el respaldo lleva `SHA256SUMS`; se verifica al descargarlo y otra vez antes de
  restaurar.
- El script de restauración vuelve a comparar los conteos de la base nueva contra
  `db/conteo_origen.txt` y cuenta los archivos de `media/` extraídos.
- **Ventana de escrituras**: entre el respaldo y el arranque en el servidor nuevo alguien
  podría subir un archivo o crear un registro en el viejo. Para que sea imposible, el
  respaldo *definitivo* se hace con el servicio detenido (paso 4).

## 3. Respaldo preliminar (ya hecho, sin cortar servicio)

Sirve para preparar y probar el servidor nuevo con datos reales.

```
# en el servidor viejo
scp -P 16022 scripts/backup_produccion.sh hubambiental002@45.65.200.111:~/
ssh -p 16022 hubambiental002@45.65.200.111 'bash ~/backup_produccion.sh'
# → ~/backups/aluna_kunsama/<timestamp>/

# descargar y verificar en la máquina local
rsync -a -e "ssh -p 16022" hubambiental002@45.65.200.111:backups/aluna_kunsama/<timestamp> ~/Backups/aluna_kunsama/
cd ~/Backups/aluna_kunsama/<timestamp> && shasum -a 256 -c SHA256SUMS
```

Respaldo preliminar existente: `20260920_032349` (commit `e12e418`), copiado a
`~/Backups/aluna_kunsama/20260920_032349` en la máquina local y también en el servidor.

## 4. Día del corte (cutover)

1. **Avisar** a los usuarios y **detener el servicio** en el servidor viejo, para congelar
   la base y `media/` (requiere sudo, lo hace el usuario):
   ```
   sudo systemctl stop aluna-kunsama-backend.service
   ```
   El contenedor de Postgres sigue arriba: hace falta para el dump.
2. **Respaldo definitivo** (ya nada escribe):
   ```
   ssh -p 16022 hubambiental002@45.65.200.111 'bash ~/backup_produccion.sh --sin-modelos'
   ```
   `--sin-modelos` porque los modelos ya viajaron con el preliminar y no cambian. Comprobar
   que `MANIFEST.txt` diga `RESULTADO: OK`.
3. **Copiar** el respaldo al servidor nuevo (directo servidor→servidor si hay ruta, o vía
   la máquina local) y verificar `sha256sum -c SHA256SUMS`.
4. **Restaurar** en el servidor nuevo (sección 5).
5. **Apuntar DNS / nginx** de `back.alunaia.co` al servidor nuevo.
6. **No borrar nada del servidor viejo** hasta llevar al menos una semana operando en el
   nuevo. Conservar también la copia local.

## 5. Preparar y restaurar el servidor nuevo

Precondiciones: Ubuntu con Docker (usuario en el grupo `docker`), Python 3 con `venv`,
nginx, git con acceso al repo.

```
# 1. clonar en la misma ruta (o exportar APP_DIR con la nueva)
git clone <repo> ~/backend_stacks/backed_aluna_kunsama
cd ~/backend_stacks/backed_aluna_kunsama
git checkout <commit de sistema/git_HEAD.txt o main>

# 2. copiar el respaldo al servidor nuevo, p. ej. a ~/backups/aluna_kunsama/<timestamp>

# 3. restaurar datos, base, modelos, venv, migrate, collectstatic
bash scripts/restaurar_produccion.sh ~/backups/aluna_kunsama/<timestamp>
```

El script:
- verifica `SHA256SUMS`,
- extrae `.env`, `media/`, `instrumentos/extracciones/`, `staticfiles/`, logs y modelos,
- levanta `docker compose up -d db` (lee `POSTGRES_*` del `.env` restaurado),
- recrea el esquema `public` desde `db/aluna_kunsamu.dump` con `pg_restore`,
- compara conteos por tabla contra el origen y falla si difieren,
- crea el `venv`, instala dependencias, corre `migrate` y `collectstatic`.

Luego, con sudo:

```
sudo cp ~/backups/aluna_kunsama/<timestamp>/sistema/aluna-kunsama-backend.service /etc/systemd/system/
#   revisar User=, WorkingDirectory=, EnvironmentFile= y las rutas de ExecStart si cambia el home
sudo systemctl daemon-reload
sudo systemctl enable --now aluna-kunsama-backend.service
```

nginx: copiar del archivo `sistema/nginx_backend.conf` los dos `location` de
`/api/aluna-kunsama/` (el de `static/` con `alias` a `staticfiles/` y el `proxy_pass` a
`127.0.0.1:8004` con `X-Script-Name`), mantener `client_max_body_size 20M` y el
certificado de `back.alunaia.co`. Recargar con `sudo nginx -t && sudo systemctl reload nginx`.

Cosas del `.env` a revisar si cambia el dominio o el prefijo: `ALLOWED_HOSTS`,
`CORS_ALLOWED_ORIGINS`, `MEDIA_URL` (lleva el prefijo completo porque nginx no sirve
`media/`, la sirve Django).

## 6. Comprobación final en el servidor nuevo

```
curl -s https://back.alunaia.co/api/aluna-kunsama/api/schema/ | head -3
# un asset de media conocido (tomar la URL de un registro en la base):
curl -sI https://back.alunaia.co/api/aluna-kunsama/media/jornadas/assets/2026/09/<archivo>
# conteo desde Django, debe coincidir con db/conteo_origen.txt
venv/bin/python manage.py shell -c "from jornadas.models import Jornada; print(Jornada.objects.count())"
```

Y en el servidor viejo, tras la semana de gracia: `docker compose down` (sin `-v`) y
archivar; el volumen `aluna_kunsama_pg_data` no se borra.

## 7. Restauración alternativa sin los scripts

Si algo del script no aplica, el equivalente manual de la base es:

```
docker compose up -d db
docker exec -i aluna_kunsama_db pg_restore -U aluna_kunsamu -d aluna_kunsamu --no-owner --clean --if-exists < db/aluna_kunsamu.dump
# o con el volcado plano:
gunzip -c db/aluna_kunsamu.sql.gz | docker exec -i aluna_kunsama_db psql -U aluna_kunsamu -d aluna_kunsamu
```

y para los archivos, `tar -xzf app_data.tar.gz -C ~/backend_stacks/backed_aluna_kunsama`.
