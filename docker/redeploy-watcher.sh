#!/bin/sh
# Vigila `origin/$GIT_BRANCH` del propio repo y, apenas ve un commit nuevo, hace `git pull` +
# `docker compose up -d --build app` — automatiza exactamente los mismos dos comandos que hasta
# ahora se corrían a mano por SSH tras cada push.
#
# No usa el binario oficial de git-sync (registry.k8s.io/git-sync): esa imagen es deliberadamente
# mínima (sin shell, sin CLI de Docker), así que su exechook no tiene forma de disparar un rebuild
# real sin agregarle herramientas encima. En vez de pelear contra esa imagen, este contenedor
# (Dockerfile.redeploy-watcher) trae `git` + el CLI de Docker + este script — mismo
# comportamiento (vigilar, detectar, actuar) sin las limitaciones del binario oficial.
#
# Docker-fuera-de-Docker (DooD): este contenedor habla con el DAEMON del host a través del socket
# montado, no con un Docker propio — por eso `$REPO_DIR` tiene que ser la MISMA ruta absoluta
# adentro y afuera del contenedor (ver el volumen en docker-compose.yml). Si no coincidieran, la
# ruta relativa `./media` que docker-compose.yml usa para sus bind mounts se resolvería contra un
# directorio que no existe para el daemon real, y el rebuild fallaría o montaría lo que no es.
set -e

REPO_DIR="${REPO_DIR:?REPO_DIR es obligatorio — debe ser la ruta ABSOLUTA de este proyecto en el HOST}"
RAMA="${GIT_BRANCH:-develop}"
INTERVALO="${SYNC_PERIOD_SECONDS:-30}"

# Git >= 2.35 rechaza operar sobre un repo cuyo dueño (uid) no coincide con el proceso actual —
# este contenedor corre como root, el checkout en el host es de un usuario normal.
git config --global --add safe.directory "$REPO_DIR"

# OpenSSH rechaza un ~/.ssh/config (o una llave) que no sea dueño del usuario que corre ssh (acá,
# root) ni de root mismo — "Bad owner or permissions". El bind mount de solo lectura conserva el
# uid del HOST (un usuario normal, no root), así que ssh los rechaza tal cual quedan montados. En
# vez de pelear con permisos de un mount de solo lectura, se copian a una ruta propia del
# contenedor (efímera, se repuebla en cada arranque) donde sí se les puede fijar dueño/permisos.
if [ -d /ssh-host ]; then
    mkdir -p /root/.ssh
    cp -a /ssh-host/. /root/.ssh/
    # `cp -a` preserva el dueño original (el uid del host, no root) — hay que forzarlo aparte,
    # es justo lo que openssh viene a rechazar si se deja tal cual.
    chown -R root:root /root/.ssh
    chmod 700 /root/.ssh
    find /root/.ssh -type f -exec chmod 600 {} \;
fi

cd "$REPO_DIR"

echo "[redeploy-watcher] Vigilando origin/$RAMA en $REPO_DIR cada ${INTERVALO}s..."

while true; do
    if ! git fetch origin "$RAMA" --quiet; then
        echo "[redeploy-watcher] git fetch falló — reintento en el próximo ciclo."
        sleep "$INTERVALO"
        continue
    fi

    LOCAL=$(git rev-parse HEAD)
    REMOTO=$(git rev-parse "origin/$RAMA")

    if [ "$LOCAL" != "$REMOTO" ]; then
        echo "[redeploy-watcher] Nuevo commit en origin/$RAMA: $REMOTO (local: $LOCAL). Actualizando..."
        if git pull --ff-only origin "$RAMA"; then
            echo "[redeploy-watcher] Pull OK — reconstruyendo y reiniciando app..."
            # --no-deps: SOLO `app`, nunca sus dependencias. Sin esto, `up` reevalúa `db` como
            # parte del grafo de dependencias (por `depends_on`) y, según cómo compose recalcule
            # el hash de config en esta invocación, puede terminar recreándolo igual — pasó en
            # producción real (2026-09-20): el primer redeploy automático recreó `db` de paso. Los
            # datos no se pierden (viven en el volumen con nombre, no en el contenedor), pero un
            # redeploy de código no tiene ningún motivo para tocar la base — este flag lo hace
            # imposible de raíz, no solo improbable.
            # El stack con `app` vive en docker-compose.dev.yaml, no en el docker-compose.yml por
            # defecto (que en producción solo levanta Postgres) — ver la cabecera de ambos.
            if docker compose -f "$REPO_DIR/docker-compose.dev.yaml" up -d --build --no-deps app; then
                echo "[redeploy-watcher] Redeploy OK ($(git rev-parse --short HEAD))."
            else
                echo "[redeploy-watcher] 'docker compose up' falló — revisar logs del build."
            fi
        else
            echo "[redeploy-watcher] 'git pull --ff-only' falló (¿cambios locales sin commitear en el working dir del host?) — no se redeploya."
        fi
    fi

    sleep "$INTERVALO"
done
