# Imagen de la app Django+gunicorn — es una copia viva del despliegue de producción
# (venv + systemd + gunicorn en 127.0.0.1:8004, ver docs/ y la memoria del proyecto), solo que acá
# gunicorn lo arranca este contenedor en vez de systemd. nginx queda deliberadamente FUERA: cada
# servidor donde se despliegue ya resuelve el proxy/TLS a su manera (nginx a secas en producción,
# nginx-proxy-manager en el servidor de casa) — meterlo en la imagen o en compose acoplaría el
# contenedor a una topología de proxy concreta que no le corresponde.
#
# Python 3.12 para calzar con la versión real de producción (ver sistema/python_version.txt del
# respaldo). bertopic/umap-learn/hdbscan/scikit-learn compilan extensiones nativas en la primera
# instalación — de ahí build-essential — así que ese toolchain de build se necesita sí o sí, no es
# opcional.
FROM python:3.12-slim

# PYTHONDONTWRITEBYTECODE: no ensucia los volúmenes montados con .pyc de una versión de Python
# que puede no coincidir entre imagen y host. PYTHONUNBUFFERED: los logs de Django/gunicorn salen
# a stdout/stderr al instante, que es donde `docker logs`/`docker compose logs` los recogen.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# build-essential + git: compilar las extensiones nativas de hdbscan/umap-learn (BERTopic, ver
# analitica/analysis.py — clustering local, determinístico, sin LLM). poppler-utils: pdfplumber lo
# usa para algunos PDFs con capas de texto complejas (instrumentos/extraccion_ia_openai.py).
# fonts-dejavu-core: reportlab necesita al menos una fuente con soporte de acentos/ñ para los PDFs
# en español (analitica/pdf_presentacion.py, transcripciones/pdf_informe.py) — sin ella el texto
# sale con glifos rotos.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git poppler-utils fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Torch CPU-only ANTES del resto de requirements: pip por defecto instala la build con CUDA
# (varios GB) aunque nunca se use GPU acá, y sentence-transformers/bertopic la arrastran como
# dependencia transitiva si no está ya satisfecha. Instalarla aparte desde el índice CPU evita esa
# descarga y deja el resto de la instalación determinista.
COPY requirements.txt .
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt

COPY . .

# Usuario sin privilegios para correr gunicorn — nunca root en un proceso que recibe tráfico HTTP,
# aunque sea detrás de un proxy. uid/gid 1000 porque es lo habitual en la primera cuenta no-root
# de la mayoría de hosts Linux (facilita que un bind mount del host quede legible sin ajustes).
RUN useradd -m -u 1000 kunsama && chown -R kunsama:kunsama /app
USER kunsama

# HF_HOME fija dónde caen los modelos que descarga sentence-transformers (si no, usa
# ~/.cache/huggingface del usuario del proceso, que es lo mismo pero mejor dejarlo explícito para
# que docker-compose.yml pueda montarlo como volumen sin adivinar la ruta).
ENV HF_HOME=/home/kunsama/.cache/huggingface
# NUMBA_CACHE_DIR: por defecto numba (dependencia de umap-learn, que usa BERTopic para el
# clustering de tópicos) intenta guardar la caché de sus funciones JIT junto al código fuente del
# paquete (site-packages/umap/__pycache__) — eso quedó instalado por `pip` corriendo como root
# (paso anterior a `USER kunsama`), así que `kunsama` no tiene permiso de escritura ahí. Sin este
# override, la primera vez que corre un análisis con volumen suficiente para activar BERTopic
# (`MIN_RESPUESTAS_TOPICOS`, ver analitica/analysis.py) numba lanza `RuntimeError: cannot cache
# function ...: no locator available` y tumba ese hilo de análisis — pasó en producción real
# (2026-09-20, Reporte #41). Redirigido a una ruta propia del usuario de la app, igual que HF_HOME.
ENV NUMBA_CACHE_DIR=/home/kunsama/.cache/numba

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
# Mismos parámetros que el ExecStart de systemd en producción (ver
# sistema/aluna-kunsama-backend.service del respaldo) salvo el bind, que acá es 0.0.0.0 porque
# quien limita el acceso a loopback es el mapeo de puertos de compose
# (`127.0.0.1:${APP_PORT}:8000`), no gunicorn. Logs a stdout/stderr (`-`) en vez de a archivo:
# es lo que un contenedor debe hacer para que `docker logs` funcione sin tener que exec'ar adentro.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
