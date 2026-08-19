from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from jornadas.models import Momento, OpcionPregunta, Pregunta

from .models import Participante, Respuesta


class ParticipanteRegistroSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participante
        fields = ['correo_institucional', 'nombre', 'apellido', 'telefono']

    def validate_correo_institucional(self, value):
        jornada = self.context['jornada']
        if Participante.objects.filter(jornada=jornada, correo_institucional=value).exists():
            raise serializers.ValidationError('Este correo ya está registrado en esta jornada.')
        return value

    def create(self, validated_data):
        return Participante.objects.create(jornada=self.context['jornada'], **validated_data)


class ParticipanteSerializer(serializers.ModelSerializer):
    jornada = serializers.SlugRelatedField(slug_field='slug', read_only=True)

    class Meta:
        model = Participante
        fields = ['id', 'jornada', 'correo_institucional', 'nombre', 'apellido', 'telefono', 'slug', 'token', 'creado_en']
        read_only_fields = fields


@extend_schema_serializer(component_name='ParticipanteOpcionPregunta')
class OpcionPreguntaSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpcionPregunta
        fields = ['id', 'texto', 'orden']


class PreguntaSerializer(serializers.ModelSerializer):
    opciones = OpcionPreguntaSerializer(many=True, read_only=True)

    class Meta:
        model = Pregunta
        fields = ['id', 'tipo', 'texto', 'orden', 'obligatoria', 'opciones']


class MomentoIndiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Momento
        fields = ['id', 'orden', 'titulo', 'slug', 'tipo']


class MomentoDetalleSerializer(serializers.ModelSerializer):
    preguntas = PreguntaSerializer(many=True, read_only=True)

    class Meta:
        model = Momento
        fields = ['id', 'orden', 'titulo', 'slug', 'contexto', 'tipo', 'preguntas']


class RespuestaEntradaSerializer(serializers.Serializer):
    pregunta_id = serializers.PrimaryKeyRelatedField(source='pregunta', queryset=Pregunta.objects.all())
    texto_libre = serializers.CharField(required=False, allow_blank=True, default='')
    opcion_ids = serializers.PrimaryKeyRelatedField(
        source='opciones', queryset=OpcionPregunta.objects.all(), many=True, required=False, default=list
    )


class RespuestaEnvioSerializer(serializers.Serializer):
    mesa = serializers.CharField(required=False, allow_blank=False)
    respuestas = RespuestaEntradaSerializer(many=True)


class RespuestaSalidaSerializer(serializers.ModelSerializer):
    opciones = OpcionPreguntaSerializer(many=True, read_only=True)

    class Meta:
        model = Respuesta
        fields = ['id', 'pregunta', 'participante', 'mesa', 'texto_libre', 'opciones', 'actualizado_en']
