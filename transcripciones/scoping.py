"""Mismo patrón que jornadas/scoping.py e instrumentos/scoping.py, mirando el propietario EFECTIVO
de una SesionTranscripcion: Jornada.propietarios cuando está vinculada a una jornada, si no sus
propios `encargados` (ver SesionTranscripcion.propietarios_efectivos())."""
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from jornadas.scoping import es_dependencia

from .models import SesionTranscripcion

__all__ = [
    'es_dependencia', 'sesiones_visibles', 'filtrar_por_encargado', 'verificar_acceso_sesion',
]


def _q_propietario_efectivo(user, prefix=''):
    p = f'{prefix}__' if prefix else ''
    return (
        Q(**{f'{p}jornada__isnull': False}) & Q(**{f'{p}jornada__propietarios': user})
    ) | (
        Q(**{f'{p}jornada__isnull': True}) & Q(**{f'{p}encargados': user})
    )


def sesiones_visibles(user):
    if es_dependencia(user):
        return SesionTranscripcion.objects.filter(_q_propietario_efectivo(user)).distinct()
    return SesionTranscripcion.objects.all()


def filtrar_por_encargado(queryset, user, prefix='sesion'):
    if es_dependencia(user):
        return queryset.filter(_q_propietario_efectivo(user, prefix)).distinct()
    return queryset


def verificar_acceso_sesion(user, sesion):
    if es_dependencia(user) and not sesion.propietarios_efectivos().filter(id=user.id).exists():
        raise PermissionDenied('Esta sesión de transcripción no te pertenece.')
