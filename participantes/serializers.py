from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from jornadas.models import Momento, OpcionPregunta, Pregunta

from .models import Participante, Respuesta


class ParticipanteRegistroSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participante
        fields = ['correo_institucional', 'nombre', 'apellido', 'telefono', 'mesa', 'es_vocero']

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
        fields = [
            'id', 'jornada', 'correo_institucional', 'nombre', 'apellido', 'telefono',
            'mesa', 'es_vocero', 'slug', 'token', 'creado_en',
        ]
        read_only_fields = fields


class ParticipanteMesaVoceroSerializer(serializers.ModelSerializer):
    """Superficie de edición reducida para el admin (HU-10b) — a propósito solo deja tocar
    `mesa`/`es_vocero`, nunca datos personales del registro (correo, nombre, teléfono)."""
    class Meta:
        model = Participante
        fields = ['id', 'mesa', 'es_vocero']
        read_only_fields = ['id']


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
    # La mesa ya no se manda en el body: es un dato fijo del participante (asignado en el
    # registro, ver Participante.mesa) — se toma de request.user.mesa en la vista, nunca del
    # cliente, para que un vocero no pueda enviar a nombre de otra mesa por error o a propósito.
    respuestas = RespuestaEntradaSerializer(many=True)


class RespuestaSalidaSerializer(serializers.ModelSerializer):
    opciones = OpcionPreguntaSerializer(many=True, read_only=True)

    class Meta:
        model = Respuesta
        fields = ['id', 'pregunta', 'participante', 'mesa', 'texto_libre', 'opciones', 'actualizado_en']
