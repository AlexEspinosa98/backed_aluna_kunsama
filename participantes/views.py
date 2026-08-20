from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from jornadas.models import Jornada, Momento, Pregunta
from jornadas.serializers import JornadaPublicaSerializer

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


class MomentosIndiceView(generics.ListAPIView):
    serializer_class = MomentoIndiceSerializer
    permission_classes = [EsParticipanteDeLaJornada]

    def get_queryset(self):
        return Momento.objects.filter(jornada__slug=self.kwargs['jornada_slug'], activo=True)


class MomentoDetalleView(generics.RetrieveAPIView):
    serializer_class = MomentoDetalleSerializer
    permission_classes = [EsParticipanteDeLaJornada]
    lookup_url_kwarg = 'momento_id'

    def get_queryset(self):
        return Momento.objects.filter(jornada__slug=self.kwargs['jornada_slug'], activo=True)


def _validar_entrada(pregunta, texto_libre, opciones):
    if opciones and any(opcion.pregunta_id != pregunta.id for opcion in opciones):
        raise ValidationError(f'Una opción enviada no pertenece a la pregunta {pregunta.id}.')

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


class RespuestasMomentoView(APIView):
    permission_classes = [EsParticipanteDeLaJornada]

    @extend_schema(request=RespuestaEnvioSerializer, responses=RespuestaSalidaSerializer(many=True))
    def post(self, request, jornada_slug, momento_id):
        momento = get_object_or_404(
            Momento, pk=momento_id, jornada__slug=jornada_slug, activo=True
        )
        participante = request.user

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

        entradas_por_pregunta = {}
        for item in datos['respuestas']:
            pregunta = item['pregunta']
            if pregunta.momento_id != momento.id:
                raise ValidationError(f'La pregunta {pregunta.id} no pertenece a este momento.')
            entradas_por_pregunta[pregunta.id] = item

        preguntas_obligatorias = momento.preguntas.filter(activa=True, obligatoria=True)
        faltantes = [p.id for p in preguntas_obligatorias if p.id not in entradas_por_pregunta]
        if faltantes:
            raise ValidationError({'faltantes': f'Preguntas obligatorias sin responder: {faltantes}'})

        respuestas_guardadas = []
        for pregunta_id, item in entradas_por_pregunta.items():
            pregunta = item['pregunta']
            texto_libre = item.get('texto_libre', '')
            opciones = item.get('opciones', [])
            _validar_entrada(pregunta, texto_libre, opciones)

            lookup = {'pregunta': pregunta}
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
