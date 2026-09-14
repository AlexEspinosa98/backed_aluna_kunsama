"""Mismo patrón que jornadas/scoping.py, pero mirando el propietario EFECTIVO de un Instrumento:
Jornada.propietarios cuando está vinculado a una jornada, si no sus propios `encargados` (ver
Instrumento.propietarios_efectivos()). Reutiliza jornadas.scoping.es_dependencia — es el mismo rol
admin/dependencia en toda la app, no uno nuevo por módulo."""
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from jornadas.scoping import es_dependencia

from .models import Instrumento

__all__ = ['es_dependencia', 'instrumentos_visibles', 'filtrar_por_encargado', 'verificar_acceso_instrumento']


def _q_propietario_efectivo(user, prefix=''):
    """Q que matchea un Instrumento (o algo que cuelga de uno) donde `user` es propietario
    efectivo. `prefix` es el camino desde el modelo consultado hasta el campo `instrumento` (ej.
    '' si se consulta Instrumento directamente, 'instrumento' para SeccionInstrumento,
    'seccion__instrumento' para PreguntaInstrumento, etc.)."""
    p = f'{prefix}__' if prefix else ''
    return (
        Q(**{f'{p}jornada__isnull': False}) & Q(**{f'{p}jornada__propietarios': user})
    ) | (
        Q(**{f'{p}jornada__isnull': True}) & Q(**{f'{p}encargados': user})
    )


def instrumentos_visibles(user):
    if es_dependencia(user):
        return Instrumento.objects.filter(_q_propietario_efectivo(user)).distinct()
    return Instrumento.objects.all()


def filtrar_por_encargado(queryset, user, prefix='instrumento'):
    if es_dependencia(user):
        return queryset.filter(_q_propietario_efectivo(user, prefix)).distinct()
    return queryset


def verificar_acceso_instrumento(user, instrumento):
    if es_dependencia(user) and not instrumento.propietarios_efectivos().filter(id=user.id).exists():
        raise PermissionDenied('Este instrumento no te pertenece.')
