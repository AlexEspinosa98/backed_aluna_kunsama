from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from .docx_aplicacion import respuesta_docx_http
from .models import (
    AplicacionInstrumento, ColumnaMatrizInstrumento, FilaMatrizInstrumento,
    OpcionPreguntaInstrumento, PreguntaInstrumento, PreregistroInstrumento, SeccionInstrumento,
)
from .scoping import es_dependencia, filtrar_por_encargado, instrumentos_visibles, verificar_acceso_instrumento
from .serializers import (
    AplicacionInstrumentoAdminSerializer, ColumnaMatrizInstrumentoSerializer,
    FilaMatrizInstrumentoSerializer, InstrumentoAdminSerializer, OpcionPreguntaInstrumentoSerializer,
    PreguntaInstrumentoAdminSerializer, PreregistroInstrumentoAdminSerializer,
    RevisionAplicacionSerializer, SeccionInstrumentoAdminSerializer,
)


class ValidarEncargadoAlCrearMixin:
    """Mismo patrón que jornadas.views.ValidarPropietarioAlCrearMixin, pero mirando
    Instrumento.encargados: un usuario de dependencia solo puede crear contenido bajo un
    instrumento que le pertenece."""
    campo_padre = None
    ruta_instrumento = ''

    def _instrumento_del_padre(self, padre):
        objeto = padre
        for atributo in self.ruta_instrumento.split('.'):
            if atributo:
                objeto = getattr(objeto, atributo)
        return objeto

    def perform_create(self, serializer):
        if es_dependencia(self.request.user):
            padre = serializer.validated_data[self.campo_padre]
            instrumento = self._instrumento_del_padre(padre)
            if not instrumento.encargados.filter(id=self.request.user.id).exists():
                raise PermissionDenied('No puedes crear contenido bajo un instrumento que no es tuyo.')
        serializer.save()


class InstrumentoAdminViewSet(ModelViewSet):
    serializer_class = InstrumentoAdminSerializer
    permission_classes = [IsAdminUser]
    lookup_field = 'slug'

    def get_queryset(self):
        return instrumentos_visibles(self.request.user)

    def perform_create(self, serializer):
        if es_dependencia(self.request.user):
            serializer.save(creado_por=self.request.user, encargados=[self.request.user])
        else:
            serializer.save(creado_por=self.request.user)

    def perform_update(self, serializer):
        if es_dependencia(self.request.user):
            serializer.save(encargados=list(serializer.instance.encargados.all()))
        else:
            serializer.save()

    @action(detail=True, methods=['get'], url_path='dashboard')
    def dashboard(self, request, slug=None):
        instrumento = self.get_object()
        preregistros = instrumento.preregistrados.select_related('usuario', 'aplicacion')

        conteos = {'sin_enviar': 0, 'pendiente': 0, 'aceptado': 0, 'rechazado': 0}
        listado = []
        for preregistro in preregistros:
            aplicacion = getattr(preregistro, 'aplicacion', None)
            estado_visible = aplicacion.estado_visible if aplicacion else 'sin_enviar'
            conteos[estado_visible] += 1
            listado.append({
                'preregistro_id': preregistro.id,
                'usuario_id': preregistro.usuario_id,
                'username': preregistro.usuario.username,
                'nombre': f'{preregistro.usuario.first_name} {preregistro.usuario.last_name}'.strip(),
                'estado_visible': estado_visible,
                'enviado_en': aplicacion.enviado_en if aplicacion else None,
                'revisado_en': aplicacion.revisado_en if aplicacion else None,
                'aplicacion_id': aplicacion.id if aplicacion else None,
            })

        total = len(listado)
        respondidos = total - conteos['sin_enviar']
        return Response({
            'instrumento': instrumento.slug,
            'total_preregistrados': total,
            'conteos': conteos,
            'porcentaje_avance': round(respondidos / total * 100, 1) if total else 0.0,
            'preregistrados': listado,
        })


class SeccionInstrumentoAdminViewSet(ValidarEncargadoAlCrearMixin, ModelViewSet):
    serializer_class = SeccionInstrumentoAdminSerializer
    permission_classes = [IsAdminUser]
    campo_padre = 'instrumento'
    ruta_instrumento = ''

    def get_queryset(self):
        queryset = filtrar_por_encargado(SeccionInstrumento.objects.all(), self.request.user, 'instrumento__encargados')
        instrumento_id = self.request.query_params.get('instrumento')
        if instrumento_id:
            queryset = queryset.filter(instrumento_id=instrumento_id)
        return queryset


class PreguntaInstrumentoAdminViewSet(ValidarEncargadoAlCrearMixin, ModelViewSet):
    serializer_class = PreguntaInstrumentoAdminSerializer
    permission_classes = [IsAdminUser]
    campo_padre = 'seccion'
    ruta_instrumento = 'instrumento'

    def get_queryset(self):
        queryset = filtrar_por_encargado(
            PreguntaInstrumento.objects.all(), self.request.user, 'seccion__instrumento__encargados'
        )
        seccion_id = self.request.query_params.get('seccion')
        if seccion_id:
            queryset = queryset.filter(seccion_id=seccion_id)
        return queryset


class OpcionInstrumentoAdminViewSet(ValidarEncargadoAlCrearMixin, ModelViewSet):
    serializer_class = OpcionPreguntaInstrumentoSerializer
    permission_classes = [IsAdminUser]
    campo_padre = 'pregunta'
    ruta_instrumento = 'seccion.instrumento'

    def get_queryset(self):
        queryset = filtrar_por_encargado(
            OpcionPreguntaInstrumento.objects.all(), self.request.user,
            'pregunta__seccion__instrumento__encargados',
        )
        pregunta_id = self.request.query_params.get('pregunta')
        if pregunta_id:
            queryset = queryset.filter(pregunta_id=pregunta_id)
        return queryset


class FilaMatrizAdminViewSet(ValidarEncargadoAlCrearMixin, ModelViewSet):
    serializer_class = FilaMatrizInstrumentoSerializer
    permission_classes = [IsAdminUser]
    campo_padre = 'pregunta'
    ruta_instrumento = 'seccion.instrumento'

    def get_queryset(self):
        queryset = filtrar_por_encargado(
            FilaMatrizInstrumento.objects.all(), self.request.user,
            'pregunta__seccion__instrumento__encargados',
        )
        pregunta_id = self.request.query_params.get('pregunta')
        if pregunta_id:
            queryset = queryset.filter(pregunta_id=pregunta_id)
        return queryset


class ColumnaMatrizAdminViewSet(ValidarEncargadoAlCrearMixin, ModelViewSet):
    serializer_class = ColumnaMatrizInstrumentoSerializer
    permission_classes = [IsAdminUser]
    campo_padre = 'pregunta'
    ruta_instrumento = 'seccion.instrumento'

    def get_queryset(self):
        queryset = filtrar_por_encargado(
            ColumnaMatrizInstrumento.objects.all(), self.request.user,
            'pregunta__seccion__instrumento__encargados',
        )
        pregunta_id = self.request.query_params.get('pregunta')
        if pregunta_id:
            queryset = queryset.filter(pregunta_id=pregunta_id)
        return queryset


class PreregistroInstrumentoAdminViewSet(ModelViewSet):
    serializer_class = PreregistroInstrumentoAdminSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        queryset = filtrar_por_encargado(
            PreregistroInstrumento.objects.select_related('usuario', 'aplicacion', 'instrumento'),
            self.request.user,
        )
        instrumento_id = self.request.query_params.get('instrumento')
        if instrumento_id:
            queryset = queryset.filter(instrumento_id=instrumento_id)
        return queryset

    def perform_create(self, serializer):
        instrumento = serializer.validated_data['instrumento']
        verificar_acceso_instrumento(self.request.user, instrumento)
        serializer.save(creado_por=self.request.user)


class AplicacionInstrumentoAdminViewSet(ReadOnlyModelViewSet):
    serializer_class = AplicacionInstrumentoAdminSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = filtrar_por_encargado(
            AplicacionInstrumento.objects.select_related('preregistro__usuario', 'preregistro__instrumento')
            .prefetch_related('respuestas'),
            self.request.user,
            'preregistro__instrumento__encargados',
        )
        instrumento_id = self.request.query_params.get('instrumento')
        if instrumento_id:
            queryset = queryset.filter(preregistro__instrumento_id=instrumento_id)
        return queryset

    @action(detail=True, methods=['post'], url_path='revisar')
    def revisar(self, request, pk=None):
        aplicacion = self.get_object()
        if aplicacion.enviado_en is None:
            raise ValidationError('Esta aplicación todavía no ha sido enviada, no hay nada que revisar.')

        entrada = RevisionAplicacionSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        aplicacion.estado = entrada.validated_data['estado']
        aplicacion.comentario_revision = entrada.validated_data.get('comentario_revision', '')
        aplicacion.revisado_por = request.user
        aplicacion.revisado_en = timezone.now()
        aplicacion.save()

        return Response(AplicacionInstrumentoAdminSerializer(aplicacion).data)

    @action(detail=True, methods=['get'], url_path='descargar')
    def descargar(self, request, pk=None):
        aplicacion = self.get_object()
        return respuesta_docx_http(aplicacion)
