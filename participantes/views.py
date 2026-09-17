from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from jornadas.models import Jornada, Momento, Pregunta, RolJornada
from jornadas.serializers import JornadaPublicaSerializer, RolJornadaSerializer

from .models import Participante, Respuesta
from .permissions import EsParticipanteDeLaJornada
from .serializers import (
    MomentoDetalleSerializer,
    MomentoIndiceSerializer,
    ParticipanteLoginSerializer,
    ParticipanteRegistroSerializer,
    ParticipanteSerializer,
    RespuestaEnvioSerializer,
    RespuestaSalidaSerializer,
)


class JornadaListaView(generics.ListAPIView):
    queryset = Jornada.objects.all()
    serializer_class = JornadaPublicaSerializer
    permission_classes = [AllowAny]


class JornadaDetalleView(generics.RetrieveAPIView):
    queryset = Jornada.objects.filter(activa=True)
    serializer_class = JornadaPublicaSerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'
    lookup_url_kwarg = 'jornada_slug'


class RolesJornadaView(generics.ListAPIView):
    """Catálogo de roles que un admin definió para esta jornada (RolJornada) — público y sin
    autenticación, igual que JornadaDetalleView, para que el front pueda mostrarlos como opciones
    en el formulario de registro (HU-17). Una jornada sin roles definidos devuelve una lista
    vacía; el registro (Participante.rol) sigue aceptando texto libre de todas formas."""
    serializer_class = RolJornadaSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return RolJornada.objects.filter(jornada__slug=self.kwargs['jornada_slug'])


class RegistroParticipanteView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=ParticipanteRegistroSerializer, responses=ParticipanteSerializer)
    def post(self, request, jornada_slug):
        jornada = get_object_or_404(Jornada, slug=jornada_slug, activa=True)

        entrada = ParticipanteRegistroSerializer(data=request.data, context={'jornada': jornada})
        entrada.is_valid(raise_exception=True)
        participante = entrada.save()

        return Response(ParticipanteSerializer(participante).data, status=status.HTTP_201_CREATED)


class LoginParticipanteView(APIView):
    """El participante no tiene contraseña — si perdió su token (cerró el navegador, cambió de
    dispositivo), este endpoint se lo devuelve con solo su correo institucional, que es único por
    jornada. No es una autenticación fuerte (cualquiera que sepa el correo puede recuperar el
    token), pero es el nivel de seguridad correcto para una jornada participativa sin datos
    sensibles ni contraseñas que gestionar."""
    permission_classes = [AllowAny]

    @extend_schema(request=ParticipanteLoginSerializer, responses=ParticipanteSerializer)
    def post(self, request, jornada_slug):
        jornada = get_object_or_404(Jornada, slug=jornada_slug, activa=True)

        entrada = ParticipanteLoginSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        correo = entrada.validated_data['correo_institucional']

        participante = Participante.objects.filter(
            jornada=jornada, correo_institucional=correo
        ).first()
        if participante is None:
            return Response(
                {'detail': 'No hay ningún participante registrado con ese correo en esta jornada.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(ParticipanteSerializer(participante).data, status=status.HTTP_200_OK)


class MeParticipanteView(APIView):
    """El front guarda el token del participante (localStorage) tras el registro (HU-17) o el
    login por correo (HU-18b) — este endpoint le deja recuperar los datos completos de ese
    participante mandando solo el token ya guardado, sin volver a pedir el correo. Devuelve
    exactamente el mismo cuerpo que login/registro, para que el front pueda reusar el mismo
    parseo en los tres casos."""
    permission_classes = [EsParticipanteDeLaJornada]

    @extend_schema(responses=ParticipanteSerializer)
    def get(self, request, jornada_slug):
        return Response(ParticipanteSerializer(request.user).data, status=status.HTTP_200_OK)


def _momento_visible_para(momento, participante):
    # roles_permitidos vacía = visible para todos los roles — aplica siempre (a diferencia de
    # mesa, todo participante tiene un rol, sea el momento individual o de mesa).
    if momento.roles_permitidos and participante.rol not in momento.roles_permitidos:
        return False
    # mesas_permitidas vacía = visible para todas las mesas, igual que en Pregunta. Solo aplica
    # en momentos tipo mesa — un momento individual no tiene noción de "mesa" del participante.
    return (
        momento.tipo != Momento.TIPO_MESA
        or not momento.mesas_permitidas
        or participante.mesa in momento.mesas_permitidas
    )


class MomentosIndiceView(generics.ListAPIView):
    serializer_class = MomentoIndiceSerializer
    permission_classes = [EsParticipanteDeLaJornada]

    def get_queryset(self):
        momentos = Momento.objects.filter(jornada__slug=self.kwargs['jornada_slug'], activo=True)
        participante = self.request.user
        return [m for m in momentos if _momento_visible_para(m, participante)]


class MomentoDetalleView(generics.RetrieveAPIView):
    serializer_class = MomentoDetalleSerializer
    permission_classes = [EsParticipanteDeLaJornada]
    lookup_url_kwarg = 'momento_id'

    def get_queryset(self):
        return Momento.objects.filter(jornada__slug=self.kwargs['jornada_slug'], activo=True)

    def get_object(self):
        momento = super().get_object()
        if not _momento_visible_para(momento, self.request.user):
            raise NotFound('Este momento no está disponible para tu mesa.')
        return momento


def _validar_entrada(pregunta, texto_libre, opciones, fila=None, columna=None):
    if opciones and any(opcion.pregunta_id != pregunta.id for opcion in opciones):
        raise ValidationError(f'Una opción enviada no pertenece a la pregunta {pregunta.id}.')

    if pregunta.tipo == Pregunta.TIPO_MATRIZ:
        if fila is None or columna is None:
            raise ValidationError(
                f'La pregunta {pregunta.id} es de tipo matriz: cada respuesta debe indicar fila y columna.'
            )
        if fila.pregunta_id != pregunta.id or columna.pregunta_id != pregunta.id:
            raise ValidationError(f'La fila/columna enviada no pertenece a la pregunta {pregunta.id}.')
        if opciones:
            raise ValidationError(f'La pregunta {pregunta.id} no acepta opciones.')
        return

    if fila is not None or columna is not None:
        raise ValidationError(f'La pregunta {pregunta.id} no es de tipo matriz, no acepta fila/columna.')

    if pregunta.tipo == Pregunta.TIPO_ABIERTA:
        if opciones:
            raise ValidationError(f'La pregunta {pregunta.id} es abierta, no acepta opciones.')
        if pregunta.obligatoria and not texto_libre.strip():
            raise ValidationError(f'La pregunta {pregunta.id} es obligatoria.')
    else:
        if texto_libre.strip():
            raise ValidationError(f'La pregunta {pregunta.id} no acepta texto libre.')
        if pregunta.tipo == Pregunta.TIPO_UNICA and len(opciones) > 1:
            raise ValidationError(f'La pregunta {pregunta.id} solo acepta una opción.')
        if pregunta.obligatoria and not opciones:
            raise ValidationError(f'La pregunta {pregunta.id} es obligatoria.')


def _preguntas_obligatorias_faltantes(preguntas_obligatorias, entradas_por_pregunta):
    faltantes = []
    for pregunta in preguntas_obligatorias:
        items = entradas_por_pregunta.get(pregunta.id, [])
        if pregunta.tipo == Pregunta.TIPO_MATRIZ:
            requeridas = {
                (f, c) for f in pregunta.filas.values_list('id', flat=True)
                for c in pregunta.columnas.values_list('id', flat=True)
            }
            respondidas = {
                (i['fila'].id, i['columna'].id) for i in items
                if i.get('fila') is not None and i.get('columna') is not None
                and i.get('texto_libre', '').strip()
            }
            if not requeridas.issubset(respondidas):
                faltantes.append(pregunta.id)
        elif not items:
            faltantes.append(pregunta.id)
    return faltantes


class RespuestasMomentoView(APIView):
    permission_classes = [EsParticipanteDeLaJornada]

    @extend_schema(responses=RespuestaSalidaSerializer(many=True))
    def get(self, request, jornada_slug, momento_id):
        """Las respuestas YA GUARDADAS del participante (o de su mesa, en momentos tipo mesa)
        para este momento — para que el front pueda pre-llenar el formulario cuando alguien
        vuelve a un momento a medio responder o a corregir algo, en vez de partir en blanco.
        Antes de esto no existía ningún GET de respuestas: MomentoDetalleView solo devuelve la
        estructura (preguntas/opciones/filas/columnas), nunca lo que ya se respondió."""
        momento = get_object_or_404(
            Momento, pk=momento_id, jornada__slug=jornada_slug, activo=True
        )
        participante = request.user
        if not _momento_visible_para(momento, participante):
            raise NotFound('Este momento no está disponible para tu mesa.')

        if momento.tipo == Momento.TIPO_MESA:
            # Mismo criterio de dueño que en el POST: en un momento de mesa, las respuestas son
            # de la mesa, no de la persona — así que cualquier integrante de la mesa (no solo el
            # vocero, que es el único que puede escribir) puede ver lo que ya se respondió.
            if participante.mesa is None:
                return Response([], status=status.HTTP_200_OK)
            respuestas = Respuesta.objects.filter(pregunta__momento=momento, mesa=participante.mesa)
        else:
            respuestas = Respuesta.objects.filter(pregunta__momento=momento, participante=participante)

        respuestas = respuestas.select_related('pregunta').prefetch_related('opciones')
        return Response(RespuestaSalidaSerializer(respuestas, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(request=RespuestaEnvioSerializer, responses=RespuestaSalidaSerializer(many=True))
    def post(self, request, jornada_slug, momento_id):
        momento = get_object_or_404(
            Momento, pk=momento_id, jornada__slug=jornada_slug, activo=True
        )
        participante = request.user
        if not _momento_visible_para(momento, participante):
            raise NotFound('Este momento no está disponible para tu mesa.')

        entrada = RespuestaEnvioSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data

        mesa = None
        if momento.tipo == Momento.TIPO_MESA:
            if not participante.es_vocero:
                raise PermissionDenied(
                    'Solo el vocero de la mesa puede enviar respuestas en este momento.'
                )
            mesa = participante.mesa
            if mesa is None:
                raise ValidationError(
                    {'mesa': 'No tienes una mesa asignada — pídele a un administrador que te la '
                              'asigne antes de responder.'}
                )

        def _pregunta_visible_para(pregunta):
            # mesas_permitidas/roles_permitidas vacías = aplica a todas las mesas/todos los
            # roles, igual que siempre. Esto se revalida acá (no solo se oculta en el listado,
            # ver MomentoDetalleSerializer) para que un vocero no pueda colar una respuesta a una
            # pregunta que no le corresponde pegándole directo a la API.
            if pregunta.roles_permitidos and participante.rol not in pregunta.roles_permitidos:
                return False
            return momento.tipo != Momento.TIPO_MESA or not pregunta.mesas_permitidas or mesa in pregunta.mesas_permitidas

        # dict de listas (no un único item por pregunta): una pregunta tipo matriz manda una
        # entrada POR CELDA (fila×columna), todas con el mismo pregunta_id.
        entradas_por_pregunta = {}
        for item in datos['respuestas']:
            pregunta = item['pregunta']
            if pregunta.momento_id != momento.id:
                raise ValidationError(f'La pregunta {pregunta.id} no pertenece a este momento.')
            if not _pregunta_visible_para(pregunta):
                raise ValidationError(f'La pregunta {pregunta.id} no está habilitada para ti.')
            entradas_por_pregunta.setdefault(pregunta.id, []).append(item)

        preguntas_obligatorias = [
            p for p in momento.preguntas.filter(activa=True, obligatoria=True) if _pregunta_visible_para(p)
        ]
        faltantes = _preguntas_obligatorias_faltantes(preguntas_obligatorias, entradas_por_pregunta)
        if faltantes:
            raise ValidationError({'faltantes': f'Preguntas obligatorias sin responder: {faltantes}'})

        respuestas_guardadas = []
        for items in entradas_por_pregunta.values():
            for item in items:
                pregunta = item['pregunta']
                texto_libre = item.get('texto_libre', '')
                opciones = item.get('opciones', [])
                fila = item.get('fila')
                columna = item.get('columna')
                _validar_entrada(pregunta, texto_libre, opciones, fila, columna)

                lookup = {'pregunta': pregunta, 'fila': fila, 'columna': columna}
                if momento.tipo == Momento.TIPO_MESA:
                    lookup['mesa'] = mesa
                else:
                    lookup['participante'] = participante

                respuesta, _ = Respuesta.objects.update_or_create(
                    **lookup,
                    defaults={
                        'texto_libre': texto_libre,
                        'registrado_por': participante,
                    },
                )
                respuesta.opciones.set(opciones)
                respuestas_guardadas.append(respuesta)

        return Response(
            RespuestaSalidaSerializer(respuestas_guardadas, many=True).data,
            status=status.HTTP_200_OK,
        )
