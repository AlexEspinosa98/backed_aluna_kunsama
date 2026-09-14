"""Mismo patrón que jornadas/scoping.py e instrumentos/scoping.py, mirando
SesionTranscripcion.encargados. Reutiliza jornadas.scoping.es_dependencia — es el mismo rol
admin/dependencia en toda la app."""
from rest_framework.exceptions import PermissionDenied

from jornadas.scoping import es_dependencia

from .models import SesionTranscripcion

__all__ = [
    'es_dependencia', 'sesiones_visibles', 'filtrar_por_encargado', 'verificar_acceso_sesion',
]


def sesiones_visibles(user):
    if es_dependencia(user):
        return SesionTranscripcion.objects.filter(encargados=user)
    return SesionTranscripcion.objects.all()


def filtrar_por_encargado(queryset, user, lookup='sesion__encargados'):
    if es_dependencia(user):
        return queryset.filter(**{lookup: user})
    return queryset


def verificar_acceso_sesion(user, sesion):
    if es_dependencia(user) and not sesion.encargados.filter(id=user.id).exists():
        raise PermissionDenied('Esta sesión de transcripción no te pertenece.')
