from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication

from .models import Participante


class ParticipanteTokenAuthentication(BaseAuthentication):
    keyword = 'Participant'

    def authenticate(self, request):
        header = request.META.get('HTTP_AUTHORIZATION', '')
        if not header:
            return None

        parts = header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            return None

        try:
            participante = Participante.objects.select_related('jornada').get(token=parts[1])
        except (Participante.DoesNotExist, ValueError):
            raise exceptions.AuthenticationFailed('Token de participante inválido.')

        return (participante, None)
