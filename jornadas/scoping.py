"""Helpers para el rol "dependencia": qué puede ver/crear un usuario que no es admin completo.

Un usuario sin fila en PerfilUsuario (todo lo que existe hoy en producción) se trata como admin
completo — ver el docstring de PerfilUsuario en jornadas/models.py.
"""
from rest_framework.exceptions import PermissionDenied

from .models import Jornada, PerfilUsuario


def es_dependencia(user):
    perfil = getattr(user, 'perfil', None)
    return perfil is not None and perfil.rol == PerfilUsuario.ROL_DEPENDENCIA


def jornadas_visibles(user):
    if es_dependencia(user):
        return Jornada.objects.filter(propietarios=user)
    return Jornada.objects.all()


def filtrar_por_propietario(queryset, user, lookup='jornada__propietarios'):
    """Aplica el filtro de dependencia a cualquier queryset que llegue a una jornada por
    `lookup` (ej. 'jornada__propietarios', 'momento__jornada__propietarios',
    'pregunta__momento__jornada__propietarios'). Admin completo: sin filtro, ve todo."""
    if es_dependencia(user):
        return queryset.filter(**{lookup: user})
    return queryset


def verificar_acceso_jornada(user, jornada):
    """Para vistas que resuelven UNA jornada puntual por id (ej. descarga de Excel) en vez de
    filtrar un queryset — ahí no hay 'devolver vacío' posible, así que se rechaza explícito."""
    if es_dependencia(user) and not jornada.propietarios.filter(id=user.id).exists():
        raise PermissionDenied('Esta jornada no te pertenece.')
