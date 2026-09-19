from django.contrib.auth import get_user_model
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from .banco import copiar_momento
from .models import (
    ColumnaMatrizPregunta, FilaMatrizPregunta, Jornada, JornadaAsset, Momento, OpcionPregunta,
    Pregunta, RolJornada,
)
from .permissions import EsAdminCompleto
from .scoping import (
    anotar_conteos_banco, es_dependencia, filtrar_por_propietario, jornadas_visibles,
    momentos_del_banco, verificar_acceso_jornada,
)
from .serializers import (
    BancoMomentoDetalleSerializer,
    BancoMomentoListaSerializer,
    ColumnaMatrizPreguntaSerializer,
    FilaMatrizPreguntaSerializer,
    JornadaAdminSerializer,
    JornadaAssetCrearSerializer,
    JornadaAssetSerializer,
    MomentoAdminSerializer,
    OpcionPreguntaSerializer,
    PreguntaAdminSerializer,
    RolJornadaSerializer,
    UsarMomentoSerializer,
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

    def _validar_jornada_propia(self, serializer):
        """Separado de perform_create para que MomentoAdminViewSet pueda reusar la validación
        y además pasar `creado_por` a serializer.save() (ver su propio perform_create)."""
        if es_dependencia(self.request.user):
            padre = serializer.validated_data[self.campo_padre]
            jornada = self._jornada_del_padre(padre)
            if not jornada.propietarios.filter(id=self.request.user.id).exists():
                raise PermissionDenied('No puedes crear contenido bajo una jornada que no es tuya.')

    def perform_create(self, serializer):
        self._validar_jornada_propia(serializer)
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


class RolJornadaAdminViewSet(ValidarPropietarioAlCrearMixin, ModelViewSet):
    serializer_class = RolJornadaSerializer
    permission_classes = [IsAdminUser]
    campo_padre = 'jornada'
    ruta_jornada = ''

    def get_queryset(self):
        queryset = filtrar_por_propietario(RolJornada.objects.all(), self.request.user, 'jornada__propietarios')
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        return queryset


class JornadaAssetAdminViewSet(ModelViewSet):
    """Assets (imágenes) y system design de una jornada — usados como referencia visual real al
    generar infografías (ver analitica.infografia_ia_openai). Solo list/create/destroy: un asset
    se reemplaza subiendo uno nuevo y borrando el viejo, nunca se edita in place."""
    http_method_names = ['get', 'post', 'delete', 'head', 'options']
    permission_classes = [IsAdminUser]

    def get_serializer_class(self):
        if self.action == 'create':
            return JornadaAssetCrearSerializer
        return JornadaAssetSerializer

    def get_queryset(self):
        queryset = filtrar_por_propietario(JornadaAsset.objects.all(), self.request.user, 'jornada__propietarios')
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        return queryset

    def create(self, request, *args, **kwargs):
        """Un POST crea un asset por cada archivo enviado, más uno por el `texto` si viene — por
        eso responde una **lista**, no un objeto."""
        entrada = self.get_serializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        jornada = entrada.validated_data['jornada']
        if es_dependencia(request.user) and not jornada.propietarios.filter(id=request.user.id).exists():
            raise PermissionDenied('No puedes crear contenido bajo una jornada que no es tuya.')
        creados = entrada.save(subido_por=request.user)
        salida = JornadaAssetSerializer(creados, many=True, context=self.get_serializer_context())
        return Response(salida.data, status=status.HTTP_201_CREATED)


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
        visibilidad = self.request.query_params.get('visibilidad')
        if visibilidad:
            queryset = queryset.filter(visibilidad=visibilidad)
        return queryset

    def perform_create(self, serializer):
        # Banco de instrumentos: quién lo creó es atribución, siempre desde la sesión — si viene
        # en el body se ignora (C04), por eso ni se mira serializer.validated_data acá.
        self._validar_jornada_propia(serializer)
        serializer.save(creado_por=self.request.user)


class BancoMomentoViewSet(ReadOnlyModelViewSet):
    """Banco de instrumentos (D1-A/D2-A): explorar, previsualizar, usar como plantilla y
    rastrear derivados de los `Momento` visibles para mí. De solo lectura a propósito — la
    edición del contenido sigue siendo `/api/admin/momentos/` (D4/D15); acá solo se decide qué
    entra en "mi banco visible" (públicos de cualquiera ∪ mis jornadas; admin ve todo, D5-A)."""
    permission_classes = [IsAdminUser]
    _ORDENAMIENTOS_VALIDOS = {'titulo', '-actualizado_en', '-veces_usado'}

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return BancoMomentoDetalleSerializer
        return BancoMomentoListaSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # Una sola query acá en vez de una por item en el serializer (es_mio/puedo_editar).
        context['jornadas_propias_ids'] = set(
            Jornada.objects.filter(propietarios=self.request.user).values_list('id', flat=True)
        )
        return context

    def get_queryset(self):
        queryset = momentos_del_banco(self.request.user)
        params = self.request.query_params

        alcance = params.get('alcance', 'todos')
        if alcance == 'publicos':
            queryset = queryset.filter(visibilidad=Momento.VISIBILIDAD_PUBLICO)
        elif alcance == 'mios':
            queryset = queryset.filter(jornada__propietarios=self.request.user)
        # 'todos' (default): sin filtro extra — momentos_del_banco ya es públicos ∪ míos para
        # dependencia, y todo para admin completo.

        q = params.get('q')
        if q:
            queryset = queryset.filter(Q(titulo__icontains=q) | Q(contexto__icontains=q))

        tipo = params.get('tipo')
        if tipo:
            queryset = queryset.filter(tipo=tipo)

        jornada_id = params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)

        if params.get('solo_originales') == '1':
            queryset = queryset.filter(momento_origen__isnull=True)

        # D12-B: el filtro de `activo` SOLO aplica en `list` — detalle/usar/derivados trabajan
        # sobre inactivos igual, porque siguen siendo plantillas usables.
        if self.action == 'list' and params.get('incluir_inactivos') != '1':
            queryset = queryset.filter(activo=True)

        ordering = params.get('ordering', '-actualizado_en')
        if ordering not in self._ORDENAMIENTOS_VALIDOS:
            ordering = '-actualizado_en'
        return queryset.order_by(ordering)

    @extend_schema(
        parameters=[
            OpenApiParameter('alcance', str, description='todos (default) | publicos | mios'),
            OpenApiParameter('q', str, description='Búsqueda (icontains) en título y contexto'),
            OpenApiParameter('tipo', str, description='individual | mesa'),
            OpenApiParameter('jornada', int, description='Filtra por id de jornada'),
            OpenApiParameter('solo_originales', str, description='1 = excluye copias (momento_origen no nulo)'),
            OpenApiParameter('incluir_inactivos', str, description='1 = incluye momentos con activo=False'),
            OpenApiParameter('ordering', str, description='titulo | -actualizado_en (default) | -veces_usado'),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=UsarMomentoSerializer,
        responses={201: inline_serializer(
            name='UsarMomentoRespuesta',
            fields={
                'momento': MomentoAdminSerializer(),
                'advertencias': serializers.ListField(child=serializers.CharField()),
            },
        )},
    )
    @action(detail=True, methods=['post'])
    def usar(self, request, pk=None):
        # get_object() ya filtra por get_queryset(): un privado ajeno da 404 acá mismo, sin
        # exponer que existe (misma convención que el resto del proyecto).
        origen = self.get_object()

        entrada = UsarMomentoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        jornada_destino = entrada.validated_data['jornada']
        verificar_acceso_jornada(request.user, jornada_destino)

        copia, advertencias = copiar_momento(
            origen,
            jornada_destino,
            request.user,
            orden=entrada.validated_data.get('orden'),
            titulo=entrada.validated_data.get('titulo'),
            visibilidad=entrada.validated_data.get('visibilidad', Momento.VISIBILIDAD_PRIVADO),
        )
        salida = MomentoAdminSerializer(copia, context=self.get_serializer_context())
        return Response(
            {'momento': salida.data, 'advertencias': advertencias},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(responses={200: BancoMomentoListaSerializer(many=True)})
    @action(detail=True, methods=['get'])
    def derivados(self, request, pk=None):
        origen = self.get_object()
        queryset = filtrar_por_propietario(
            origen.momentos_derivados.select_related('jornada', 'creado_por'),
            request.user,
            'jornada__propietarios',
        )
        queryset = anotar_conteos_banco(queryset)
        salida = BancoMomentoListaSerializer(queryset, many=True, context=self.get_serializer_context())
        return Response(salida.data)


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


class FilaMatrizAdminViewSet(ValidarPropietarioAlCrearMixin, ModelViewSet):
    serializer_class = FilaMatrizPreguntaSerializer
    permission_classes = [IsAdminUser]
    campo_padre = 'pregunta'
    ruta_jornada = 'momento.jornada'

    def get_queryset(self):
        queryset = filtrar_por_propietario(
            FilaMatrizPregunta.objects.all(), self.request.user, 'pregunta__momento__jornada__propietarios'
        )
        pregunta_id = self.request.query_params.get('pregunta')
        if pregunta_id:
            queryset = queryset.filter(pregunta_id=pregunta_id)
        return queryset


class ColumnaMatrizAdminViewSet(ValidarPropietarioAlCrearMixin, ModelViewSet):
    serializer_class = ColumnaMatrizPreguntaSerializer
    permission_classes = [IsAdminUser]
    campo_padre = 'pregunta'
    ruta_jornada = 'momento.jornada'

    def get_queryset(self):
        queryset = filtrar_por_propietario(
            ColumnaMatrizPregunta.objects.all(), self.request.user, 'pregunta__momento__jornada__propietarios'
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
    queryset = Usuario.objects.filter(is_staff=True).select_related('perfil').prefetch_related(
        'jornadas_propias', 'instrumentos_a_cargo', 'transcripciones_a_cargo'
    )
