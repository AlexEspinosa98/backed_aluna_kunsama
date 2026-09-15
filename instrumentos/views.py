import threading

from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from jornadas.scoping import verificar_acceso_jornada

from .docx_aplicacion import respuesta_docx_http
from .extraccion_ia_openai import procesar_extraccion_instrumento
from .models import (
    AplicacionInstrumento, ColumnaMatrizInstrumento, ExtraccionInstrumento, FilaMatrizInstrumento,
    OpcionPreguntaInstrumento, PreguntaInstrumento, PreregistroInstrumento, SeccionInstrumento,
)
from .scoping import es_dependencia, filtrar_por_encargado, instrumentos_visibles, verificar_acceso_instrumento
from .serializers import (
    AplicacionInstrumentoAdminSerializer, ColumnaMatrizInstrumentoSerializer,
    ExtraccionInstrumentoCrearSerializer, ExtraccionInstrumentoSerializer,
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
            if not instrumento.propietarios_efectivos().filter(id=self.request.user.id).exists():
                raise PermissionDenied('No puedes crear contenido bajo un instrumento que no es tuyo.')
        serializer.save()


class InstrumentoAdminViewSet(ModelViewSet):
    serializer_class = InstrumentoAdminSerializer
    permission_classes = [IsAdminUser]
    lookup_field = 'slug'

    def get_queryset(self):
        queryset = instrumentos_visibles(self.request.user)
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        return queryset

    def perform_create(self, serializer):
        if not es_dependencia(self.request.user):
            serializer.save(creado_por=self.request.user)
            return

        jornada = serializer.validated_data.get('jornada')
        if jornada is not None:
            # Vinculado desde el vamos a una jornada propia: encargados queda sin uso, la
            # propiedad pasa por Jornada.propietarios (ver Instrumento.propietarios_efectivos()).
            verificar_acceso_jornada(self.request.user, jornada)
            serializer.save(creado_por=self.request.user)
        else:
            serializer.save(creado_por=self.request.user, encargados=[self.request.user])

    def perform_update(self, serializer):
        if not es_dependencia(self.request.user):
            serializer.save()
            return

        instancia = serializer.instance
        jornada_anterior = instancia.jornada
        jornada_nueva = serializer.validated_data.get('jornada', jornada_anterior)

        if jornada_nueva is not None:
            verificar_acceso_jornada(self.request.user, jornada_nueva)
            serializer.save()
        elif jornada_anterior is not None:
            # Se está desvinculando de la jornada: sin esto quedaría sin ningún encargado propio
            # (encargados nunca se usó mientras estuvo vinculado) y desaparecería del scoping de
            # todo el mundo, incluido quien lo está desvinculando.
            serializer.save(encargados=[self.request.user])
        else:
            # Ya era suelto y sigue siéndolo: encargados fijos, mismo comportamiento de siempre.
            serializer.save(encargados=list(instancia.encargados.all()))

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
        queryset = filtrar_por_encargado(SeccionInstrumento.objects.all(), self.request.user, 'instrumento')
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
            PreguntaInstrumento.objects.all(), self.request.user, 'seccion__instrumento'
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
            'pregunta__seccion__instrumento',
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
            'pregunta__seccion__instrumento',
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
            'pregunta__seccion__instrumento',
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
            'preregistro__instrumento',
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


class ExtraccionInstrumentoViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Sube un .pdf o .docx ya diligenciado fuera de la web y dispara su transcripción con IA
    (ver instrumentos/extraccion_ia_openai.py) — mismo mecanismo asíncrono que
    analitica.AnalisisMomentoIAViewSet (hilo de background, estado pendiente→procesando→completo/
    error), pero acá el resultado alimenta una AplicacionInstrumento en vez de un reporte."""
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = filtrar_por_encargado(ExtraccionInstrumento.objects.all(), self.request.user, 'instrumento')
        instrumento_id = self.request.query_params.get('instrumento')
        if instrumento_id:
            queryset = queryset.filter(instrumento_id=instrumento_id)
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return ExtraccionInstrumentoCrearSerializer
        return ExtraccionInstrumentoSerializer

    def create(self, request, *args, **kwargs):
        entrada = ExtraccionInstrumentoCrearSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        instrumento = entrada.validated_data['instrumento']
        verificar_acceso_instrumento(request.user, instrumento)

        extraccion = entrada.save(solicitado_por=request.user)
        threading.Thread(target=procesar_extraccion_instrumento, args=(extraccion.id,), daemon=True).start()

        salida = ExtraccionInstrumentoSerializer(extraccion)
        headers = self.get_success_headers(salida.data)
        return Response(salida.data, status=status.HTTP_201_CREATED, headers=headers)
