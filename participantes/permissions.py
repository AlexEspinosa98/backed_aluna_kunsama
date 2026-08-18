from rest_framework.permissions import BasePermission

from .models import Participante


class EsParticipanteDeLaJornada(BasePermission):
    message = 'Debes autenticarte como participante de esta jornada.'

    def has_permission(self, request, view):
        if not isinstance(request.user, Participante):
            return False

        jornada_slug = view.kwargs.get('jornada_slug')
        return request.user.jornada.slug == jornada_slug
