from rest_framework.permissions import IsAdminUser
from rest_framework.viewsets import ModelViewSet

from .models import Jornada, Momento, OpcionPregunta, Pregunta
from .serializers import (
    JornadaAdminSerializer,
    MomentoAdminSerializer,
    OpcionPreguntaSerializer,
    PreguntaAdminSerializer,
)


class JornadaAdminViewSet(ModelViewSet):
    queryset = Jornada.objects.all()
    serializer_class = JornadaAdminSerializer
    permission_classes = [IsAdminUser]
    lookup_field = 'slug'

    def perform_create(self, serializer):
        serializer.save(creada_por=self.request.user)


class MomentoAdminViewSet(ModelViewSet):
    serializer_class = MomentoAdminSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = Momento.objects.all()
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        return queryset


class PreguntaAdminViewSet(ModelViewSet):
    serializer_class = PreguntaAdminSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = Pregunta.objects.all()
        momento_id = self.request.query_params.get('momento')
        if momento_id:
            queryset = queryset.filter(momento_id=momento_id)
        return queryset


class OpcionAdminViewSet(ModelViewSet):
    serializer_class = OpcionPreguntaSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = OpcionPregunta.objects.all()
        pregunta_id = self.request.query_params.get('pregunta')
        if pregunta_id:
            queryset = queryset.filter(pregunta_id=pregunta_id)
        return queryset
