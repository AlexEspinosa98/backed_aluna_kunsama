# Backend Aluna Kunsamu

API REST en Django + DRF para administrar jornadas, sus momentos y preguntas, e inscribir/recorrer momentos como participante. El frontend consume esta API por separado.

## Puesta en marcha

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # y completa credenciales de Postgres

python manage.py migrate
python manage.py createsuperuser   # usuario staff para /api/admin/**
python manage.py runserver
```

Requiere una instancia de PostgreSQL accesible con los datos de `.env` (`POSTGRES_*`). También se puede definir `DATABASE_URL` directamente (formato `postgres://user:pass@host:port/db`).

## Correr los tests

```bash
python manage.py test
```

## Autenticación

- **Administrador (staff)**: `POST /api/admin/login/` con `username`/`password` devuelve un token. Se usa como header `Authorization: Token <token>` en todo `/api/admin/**`.
- **Participante**: se obtiene un token UUID al registrarse en una jornada (`POST /api/jornadas/<slug>/registro/`). Se usa como header `Authorization: Participant <token>` en los endpoints de esa jornada.

## Documentación de la API (Swagger/OpenAPI)

- `GET /api/schema/` — esquema OpenAPI 3 en crudo
- `GET /api/docs/` — Swagger UI
- `GET /api/redoc/` — Redoc

## Endpoints principales

Ver [docs/USER_STORIES.md](docs/USER_STORIES.md) para el detalle funcional completo.

**Administración** (`IsAdminUser`):
- `GET/POST /api/admin/jornadas/`, `GET/PATCH/DELETE /api/admin/jornadas/<slug>/`
- `GET/POST/PATCH/DELETE /api/admin/momentos/` (filtrable `?jornada=<id>`)
- `GET/POST/PATCH/DELETE /api/admin/preguntas/` (filtrable `?momento=<id>`)
- `GET/POST/PATCH/DELETE /api/admin/opciones/` (filtrable `?pregunta=<id>`)
- `GET /api/admin/participantes/` (filtrable `?jornada=<id>`)
- `GET /api/admin/respuestas/` (filtrable `?momento=<id>` o `?pregunta=<id>`)

**Análisis con IA** (`IsAdminUser`) — ver [docs/REPORTE_ANALITICA_SCHEMA.html](docs/REPORTE_ANALITICA_SCHEMA.html) para el esquema completo del JSON de respuesta:
- `GET/POST /api/admin/plantillas-analisis/`, `GET/PATCH/DELETE /api/admin/plantillas-analisis/<id>/`
- `POST /api/admin/reportes/` — dispara un análisis (`jornada`, `momentos` opcional, `plantilla` opcional); responde de inmediato con el reporte en `procesando`
- `GET /api/admin/reportes/` (filtrable `?jornada=<id>`), `GET/DELETE /api/admin/reportes/<id>/` — hacer polling hasta `estado=completo`

**Público / participante**:
- `GET /api/jornadas/` — jornadas activas
- `GET /api/jornadas/<slug>/` — detalle de jornada
- `POST /api/jornadas/<slug>/registro/` — momento 0: inscripción, devuelve token
- `GET /api/jornadas/<slug>/momentos/` — índice de momentos (requiere token de participante)
- `GET /api/jornadas/<slug>/momentos/<id>/` — detalle con contexto y preguntas
- `POST /api/jornadas/<slug>/momentos/<id>/respuestas/` — enviar/actualizar respuestas del momento
