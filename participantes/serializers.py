from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from jornadas.models import Momento, OpcionPregunta, Pregunta

from .models import Participante, Respuesta


def _validar_vocero_unico(jornada, mesa, es_vocero, excluir_id=None):
    """Como máximo un vocero por (jornada, mesa) — sin esto, dos participantes podían quedar
    marcados es_vocero=True para la misma mesa sin ningún aviso, y RespuestasMomentoView no tiene
    forma de saber cuál de los dos 'es' el vocero real de esa mesa."""
    if not es_vocero or mesa is None:
        return
    qs = Participante.objects.filter(jornada=jornada, mesa=mesa, es_vocero=True)
    if excluir_id is not None:
        qs = qs.exclude(pk=excluir_id)
    if qs.exists():
        raise serializers.ValidationError(
            {'es_vocero': f'La mesa {mesa} ya tiene un vocero asignado en esta jornada.'}
        )


class ParticipanteRegistroSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participante
        fields = ['correo_institucional', 'nombre', 'apellido', 'telefono', 'rol', 'mesa', 'es_vocero']

    def validate_correo_institucional(self, value):
        jornada = self.context['jornada']
        if Participante.objects.filter(jornada=jornada, correo_institucional=value).exists():
            raise serializers.ValidationError('Este correo ya está registrado en esta jornada.')
        return value

    def validate(self, attrs):
        _validar_vocero_unico(
            self.context['jornada'], attrs.get('mesa'), attrs.get('es_vocero', False)
        )
        return attrs

    def create(self, validated_data):
        return Participante.objects.create(jornada=self.context['jornada'], **validated_data)


class ParticipanteSerializer(serializers.ModelSerializer):
    jornada = serializers.SlugRelatedField(slug_field='slug', read_only=True)

    class Meta:
        model = Participante
        fields = [
            'id', 'jornada', 'correo_institucional', 'nombre', 'apellido', 'telefono', 'rol',
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

    def validate(self, attrs):
        # PATCH puede mandar solo uno de los dos campos (ej. solo {"es_vocero": true}) — el
        # chequeo necesita el valor EFECTIVO tras el cambio, así que usa el del registro actual
        # para el campo que no vino en este request.
        instance = self.instance
        mesa = attrs.get('mesa', instance.mesa if instance else None)
        es_vocero = attrs.get('es_vocero', instance.es_vocero if instance else False)
        if instance is not None:
            _validar_vocero_unico(instance.jornada, mesa, es_vocero, excluir_id=instance.pk)
        return attrs


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
