from rest_framework.permissions import BasePermission

from .scoping import es_dependencia


class EsAdminCompleto(BasePermission):
    """Para lo que un usuario de dependencia nunca debe poder tocar: gestión de otros usuarios y
    plantillas de análisis (configuración global, no de una jornada puntual)."""
    message = 'Esta acción requiere un administrador completo.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_staff and not es_dependencia(user))
