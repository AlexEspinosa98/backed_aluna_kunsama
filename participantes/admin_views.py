from rest_framework.permissions import IsAdminUser
from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import Participante, Respuesta
from .serializers import ParticipanteSerializer, RespuestaSalidaSerializer


class ParticipanteAdminViewSet(ReadOnlyModelViewSet):
    serializer_class = ParticipanteSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = Participante.objects.select_related('jornada').all()
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        return queryset


class RespuestaAdminViewSet(ReadOnlyModelViewSet):
    serializer_class = RespuestaSalidaSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = Respuesta.objects.select_related('pregunta', 'participante').prefetch_related('opciones').all()
        momento_id = self.request.query_params.get('momento')
        pregunta_id = self.request.query_params.get('pregunta')
        if momento_id:
            queryset = queryset.filter(pregunta__momento_id=momento_id)
        if pregunta_id:
            queryset = queryset.filter(pregunta_id=pregunta_id)
        return queryset
