"""Mismo patrón que jornadas/scoping.py, pero mirando Instrumento.encargados en vez de
Jornada.propietarios. Reutiliza jornadas.scoping.es_dependencia — es el mismo rol admin/dependencia
en toda la app, no uno nuevo por módulo."""
from rest_framework.exceptions import PermissionDenied

from jornadas.scoping import es_dependencia

from .models import Instrumento

__all__ = ['es_dependencia', 'instrumentos_visibles', 'filtrar_por_encargado', 'verificar_acceso_instrumento']


def instrumentos_visibles(user):
    if es_dependencia(user):
        return Instrumento.objects.filter(encargados=user)
    return Instrumento.objects.all()


def filtrar_por_encargado(queryset, user, lookup='instrumento__encargados'):
    if es_dependencia(user):
        return queryset.filter(**{lookup: user})
    return queryset


def verificar_acceso_instrumento(user, instrumento):
    if es_dependencia(user) and not instrumento.encargados.filter(id=user.id).exists():
        raise PermissionDenied('Este instrumento no te pertenece.')
