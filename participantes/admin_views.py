from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAdminUser
from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import Participante, Respuesta
from .serializers import ParticipanteMesaVoceroSerializer, ParticipanteSerializer, RespuestaSalidaSerializer


class ParticipanteAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """DELETE elimina el registro por completo — útil para dar de baja duplicados o registros
    de prueba (ej. correo mal escrito). Las respuestas individuales del participante se borran
    en cascada (`Respuesta.participante` es CASCADE); las respuestas de mesa NO, porque están
    ligadas al número de mesa, no a la persona — la mesa conserva lo ya respondido aunque se
    elimine a quien era su vocero (ver HU-22: alguien más deberá quedar como vocero para poder
    seguir enviando)."""
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
