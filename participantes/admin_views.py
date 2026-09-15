import threading

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from jornadas.scoping import filtrar_por_propietario, verificar_acceso_jornada

from .extraccion_momento_ia_openai import aprobar_extraccion_momento, procesar_extraccion_momento
from .models import ExtraccionMomento, Participante, Respuesta
from .serializers import (
    ExtraccionMomentoCrearSerializer, ExtraccionMomentoSerializer, ParticipanteMesaVoceroSerializer,
    ParticipanteSerializer, RespuestaSalidaSerializer,
)


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
        queryset = filtrar_por_propietario(queryset, self.request.user, 'jornada__propietarios')
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
        queryset = filtrar_por_propietario(queryset, self.request.user, 'pregunta__momento__jornada__propietarios')
        momento_id = self.request.query_params.get('momento')
        pregunta_id = self.request.query_params.get('pregunta')
        if momento_id:
            queryset = queryset.filter(pregunta__momento_id=momento_id)
        if pregunta_id:
            queryset = queryset.filter(pregunta_id=pregunta_id)
        return queryset


class ExtraccionMomentoViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Sube un .pdf o .docx ya diligenciado fuera de la web y dispara su transcripción con IA
    (ver participantes/extraccion_momento_ia_openai.py) — mismo mecanismo asíncrono que
    instrumentos.ExtraccionInstrumentoViewSet, pero acá el resultado NO se escribe solo: queda en
    `resultado` hasta que el action `aprobar` lo confirma, porque en este módulo no existe forma
    de corregir una Respuesta ya guardada (RespuestaAdminViewSet es de solo lectura)."""
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = ExtraccionMomento.objects.select_related('momento', 'participante')
        queryset = filtrar_por_propietario(queryset, self.request.user, 'momento__jornada__propietarios')
        momento_id = self.request.query_params.get('momento')
        if momento_id:
            queryset = queryset.filter(momento_id=momento_id)
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return ExtraccionMomentoCrearSerializer
        return ExtraccionMomentoSerializer

    def create(self, request, *args, **kwargs):
        entrada = ExtraccionMomentoCrearSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        momento = entrada.validated_data['momento']
        verificar_acceso_jornada(request.user, momento.jornada)

        extraccion = entrada.save(solicitado_por=request.user)
        threading.Thread(target=procesar_extraccion_momento, args=(extraccion.id,), daemon=True).start()

        salida = ExtraccionMomentoSerializer(extraccion)
        headers = self.get_success_headers(salida.data)
        return Response(salida.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=['post'], url_path='aprobar')
    def aprobar(self, request, pk=None):
        extraccion = self.get_object()
        if extraccion.estado != ExtraccionMomento.ESTADO_COMPLETO:
            raise ValidationError('Solo se puede aprobar una extracción en estado "completo".')
        if extraccion.aprobado_en is not None:
            raise PermissionDenied('Esta extracción ya fue aprobada.')

        aprobar_extraccion_momento(extraccion, request.user)
        extraccion.refresh_from_db()
        return Response(ExtraccionMomentoSerializer(extraccion).data)
