from django.contrib.auth import get_user_model
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAdminUser
from rest_framework.viewsets import ModelViewSet

from .models import Momento, OpcionPregunta, Pregunta
from .permissions import EsAdminCompleto
from .scoping import es_dependencia, filtrar_por_propietario, jornadas_visibles
from .serializers import (
    JornadaAdminSerializer,
    MomentoAdminSerializer,
    OpcionPreguntaSerializer,
    PreguntaAdminSerializer,
    UsuarioAdminSerializer,
)

Usuario = get_user_model()


class ValidarPropietarioAlCrearMixin:
    """Un usuario de dependencia solo puede crear contenido (momento/pregunta/opción) bajo una
    jornada que le pertenece — sin esto, el queryset scoping de get_queryset solo protegía la
    LECTURA; nada impedía crear, por ejemplo, un momento pasando el id de la jornada de otra
    dependencia en el body. `campo_padre` es el nombre del FK en validated_data (ej. 'jornada',
    'momento', 'pregunta'); `ruta_jornada` es cómo llegar de ese padre hasta su Jornada (ej. '',
    'jornada', 'momento.jornada')."""
    campo_padre = None
    ruta_jornada = ''

    def _jornada_del_padre(self, padre):
        objeto = padre
        for atributo in self.ruta_jornada.split('.'):
            if atributo:
                objeto = getattr(objeto, atributo)
        return objeto

    def perform_create(self, serializer):
        if es_dependencia(self.request.user):
            padre = serializer.validated_data[self.campo_padre]
            jornada = self._jornada_del_padre(padre)
            if not jornada.propietarios.filter(id=self.request.user.id).exists():
                raise PermissionDenied('No puedes crear contenido bajo una jornada que no es tuya.')
        serializer.save()


class JornadaAdminViewSet(ModelViewSet):
    serializer_class = JornadaAdminSerializer
    permission_classes = [IsAdminUser]
    lookup_field = 'slug'

    def get_queryset(self):
        return jornadas_visibles(self.request.user)

    def perform_create(self, serializer):
        if es_dependencia(self.request.user):
            serializer.save(creada_por=self.request.user, propietarios=[self.request.user])
        else:
            serializer.save(creada_por=self.request.user)

    def perform_update(self, serializer):
        if es_dependencia(self.request.user):
            # Los propietarios quedan fijos — solo un admin completo puede reasignarlos.
            serializer.save(propietarios=list(serializer.instance.propietarios.all()))
        else:
            serializer.save()


class MomentoAdminViewSet(ValidarPropietarioAlCrearMixin, ModelViewSet):
    serializer_class = MomentoAdminSerializer
    permission_classes = [IsAdminUser]
    campo_padre = 'jornada'
    ruta_jornada = ''

    def get_queryset(self):
        queryset = filtrar_por_propietario(Momento.objects.all(), self.request.user, 'jornada__propietarios')
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        return queryset


class PreguntaAdminViewSet(ValidarPropietarioAlCrearMixin, ModelViewSet):
    serializer_class = PreguntaAdminSerializer
    permission_classes = [IsAdminUser]
    campo_padre = 'momento'
    ruta_jornada = 'jornada'

    def get_queryset(self):
        queryset = filtrar_por_propietario(
            Pregunta.objects.all(), self.request.user, 'momento__jornada__propietarios'
        )
        momento_id = self.request.query_params.get('momento')
        if momento_id:
            queryset = queryset.filter(momento_id=momento_id)
        return queryset


class OpcionAdminViewSet(ValidarPropietarioAlCrearMixin, ModelViewSet):
    serializer_class = OpcionPreguntaSerializer
    permission_classes = [IsAdminUser]
    campo_padre = 'pregunta'
    ruta_jornada = 'momento.jornada'

    def get_queryset(self):
        queryset = filtrar_por_propietario(
            OpcionPregunta.objects.all(), self.request.user, 'pregunta__momento__jornada__propietarios'
        )
        pregunta_id = self.request.query_params.get('pregunta')
        if pregunta_id:
            queryset = queryset.filter(pregunta_id=pregunta_id)
        return queryset


class UsuarioAdminViewSet(ModelViewSet):
    """Gestión de usuarios admin/dependencia — exclusiva de EsAdminCompleto. `jornadas_propias`
    en la respuesta deja ver, para cada usuario, exactamente qué jornadas tiene asignadas sin
    tener que cruzarlo a mano contra /api/admin/jornadas/."""
    serializer_class = UsuarioAdminSerializer
    permission_classes = [EsAdminCompleto]
    queryset = Usuario.objects.filter(is_staff=True).select_related('perfil').prefetch_related('jornadas_propias')
