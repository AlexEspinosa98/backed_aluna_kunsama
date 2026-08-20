from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAdminUser
from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import Participante, Respuesta
from .serializers import ParticipanteMesaVoceroSerializer, ParticipanteSerializer, RespuestaSalidaSerializer


class ParticipanteAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = Participante.objects.select_related('jornada').all()
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        return queryset

    def get_serializer_class(self):
        # PATCH/PUT solo puede tocar mesa/es_vocero (ver HU-10b) — nunca datos personales del
        # registro, que se hacen por otra vía si hace falta corregirlos.
        if self.action in ('update', 'partial_update'):
            return ParticipanteMesaVoceroSerializer
        return ParticipanteSerializer


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
