"""Healthcheck en la URL raíz — sin el prefijo `/api/`, para poder confirmar que el servidor
responde entrando directo a `https://<dominio>/`, sin tener que recordar ninguna ruta de la API.

Comprueba la base de datos, no solo que gunicorn esté vivo: un proceso arriba con Postgres caído
(contenedor de `db` detenido, credenciales vencidas, etc.) es exactamente el caso que un
healthcheck que solo devuelva "200 fijo" no detectaría. Sin autenticación a propósito — es lo que
un balanceador, un monitor externo o una persona entrando por el navegador necesitan poder pedir
sin token."""
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.utils import timezone


def healthcheck(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except DatabaseError as exc:
        return JsonResponse(
            {'status': 'error', 'database': 'error', 'detalle': str(exc)},
            status=503,
        )
    return JsonResponse({
        'status': 'ok',
        'database': 'ok',
        'hora_servidor': timezone.now().isoformat(),
    })
