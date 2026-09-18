from rest_framework import serializers

from .models import (
    AplicacionInstrumento, ColumnaMatrizInstrumento, FilaMatrizInstrumento, Instrumento,
    OpcionPreguntaInstrumento, PreguntaInstrumento, RespuestaInstrumento, SeccionInstrumento,
)


class OpcionPreguntaInstrumentoPublicaSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpcionPreguntaInstrumento
        fields = ['id', 'texto', 'orden']


class FilaMatrizInstrumentoPublicaSerializer(serializers.ModelSerializer):
    class Meta:
        model = FilaMatrizInstrumento
        fields = ['id', 'texto', 'orden']


class ColumnaMatrizInstrumentoPublicaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ColumnaMatrizInstrumento
        fields = ['id', 'texto', 'orden']


class PreguntaInstrumentoPublicaSerializer(serializers.ModelSerializer):
    opciones = OpcionPreguntaInstrumentoPublicaSerializer(many=True, read_only=True)
    filas = FilaMatrizInstrumentoPublicaSerializer(many=True, read_only=True)
    columnas = ColumnaMatrizInstrumentoPublicaSerializer(many=True, read_only=True)

    class Meta:
        model = PreguntaInstrumento
        fields = ['id', 'tipo', 'texto', 'orden', 'obligatoria', 'opciones', 'filas', 'columnas']


class SeccionInstrumentoPublicaSerializer(serializers.ModelSerializer):
    preguntas = serializers.SerializerMethodField()

    class Meta:
        model = SeccionInstrumento
        fields = ['id', 'orden', 'titulo', 'tipo', 'contenido', 'preguntas']

    def get_preguntas(self, seccion):
        if seccion.tipo != SeccionInstrumento.TIPO_PREGUNTAS:
            return []
        preguntas = seccion.preguntas.filter(activa=True).order_by('orden')
        return PreguntaInstrumentoPublicaSerializer(preguntas, many=True).data


class RespuestaInstrumentoPublicaSerializer(serializers.ModelSerializer):
    class Meta:
        model = RespuestaInstrumento
        fields = ['id', 'pregunta', 'fila', 'columna', 'texto_libre', 'opciones']


class MiAplicacionSerializer(serializers.ModelSerializer):
    estado_visible = serializers.CharField(read_only=True)
    respuestas = RespuestaInstrumentoPublicaSerializer(many=True, read_only=True)

    class Meta:
        model = AplicacionInstrumento
        fields = ['id', 'estado_visible', 'enviado_en', 'comentario_revision', 'respuestas']


class InstrumentoDetalleParticipanteSerializer(serializers.ModelSerializer):
    secciones = serializers.SerializerMethodField()
    mi_aplicacion = serializers.SerializerMethodField()

    class Meta:
        model = Instrumento
        fields = ['id', 'slug', 'nombre', 'descripcion', 'secciones', 'mi_aplicacion']

    def get_secciones(self, instrumento):
        secciones = instrumento.secciones.filter(activa=True).order_by('orden')
        return SeccionInstrumentoPublicaSerializer(secciones, many=True).data

    def get_mi_aplicacion(self, instrumento):
        preregistro = self.context['preregistro']
        aplicacion = getattr(preregistro, 'aplicacion', None)
        return MiAplicacionSerializer(aplicacion).data if aplicacion else None


class InstrumentoAsignadoSerializer(serializers.ModelSerializer):
    estado_visible = serializers.SerializerMethodField()

    class Meta:
        model = Instrumento
        fields = ['id', 'slug', 'nombre', 'descripcion', 'estado_visible']

    def get_estado_visible(self, instrumento):
        preregistro = instrumento._preregistro_actual
        aplicacion = getattr(preregistro, 'aplicacion', None)
        return aplicacion.estado_visible if aplicacion else 'sin_enviar'


class RespuestaInstrumentoEnvioItemSerializer(serializers.Serializer):
    pregunta = serializers.PrimaryKeyRelatedField(queryset=PreguntaInstrumento.objects.all())
    fila = serializers.PrimaryKeyRelatedField(queryset=FilaMatrizInstrumento.objects.all(), required=False)
    columna = serializers.PrimaryKeyRelatedField(queryset=ColumnaMatrizInstrumento.objects.all(), required=False)
    texto_libre = serializers.CharField(required=False, allow_blank=True, default='')
    opciones = serializers.PrimaryKeyRelatedField(
        queryset=OpcionPreguntaInstrumento.objects.all(), many=True, required=False, default=list,
    )


class RespuestaInstrumentoEnvioSerializer(serializers.Serializer):
    respuestas = RespuestaInstrumentoEnvioItemSerializer(many=True)
