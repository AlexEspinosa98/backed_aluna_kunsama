"""Helpers para el rol "dependencia": qué puede ver/crear un usuario que no es admin completo.

Un usuario sin fila en PerfilUsuario (todo lo que existe hoy en producción) se trata como admin
completo — ver el docstring de PerfilUsuario en jornadas/models.py.
"""
from django.db.models import Count, Q
from rest_framework.exceptions import PermissionDenied

from .models import Jornada, Momento, PerfilUsuario


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


def anotar_conteos_banco(queryset):
    """`n_preguntas`/`n_preguntas_inactivas`/`veces_usado` para el banco de instrumentos — dos
    `Count` distintos sobre la misma relación reversa `preguntas` (uno por `activa`) más un
    tercero sobre `momentos_derivados`: cada uno es un JOIN independiente, así que sin
    `distinct=True` se multiplican entre sí (producto cartesiano) y los tres conteos salen
    inflados. Con `distinct=True` cada `Count` cuenta ids únicos de su propia tabla."""
    return queryset.annotate(
        n_preguntas=Count('preguntas', filter=Q(preguntas__activa=True), distinct=True),
        n_preguntas_inactivas=Count('preguntas', filter=Q(preguntas__activa=False), distinct=True),
        veces_usado=Count('momentos_derivados', distinct=True),
    )


def momentos_del_banco(user):
    """Queryset base del banco de instrumentos (D1-A). A propósito NO filtra por `activo`: ese
    filtro solo lo aplica el listado (D12-B) — detalle, `usar/` y `derivados/` trabajan sobre
    momentos inactivos igual, porque siguen siendo plantillas usables.

    Dependencia: públicos de cualquiera ∪ momentos de jornadas donde soy propietario (D3-A).
    Admin completo: todos, incluidos los privados de otros (D5-A)."""
    queryset = Momento.objects.select_related('jornada', 'creado_por')
    if es_dependencia(user):
        queryset = queryset.filter(
            Q(visibilidad=Momento.VISIBILIDAD_PUBLICO) | Q(jornada__propietarios=user)
        ).distinct()
    return anotar_conteos_banco(queryset)
