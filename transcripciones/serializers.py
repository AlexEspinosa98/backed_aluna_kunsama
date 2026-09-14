from rest_framework import serializers

from .models import FragmentoTranscripcion, InformeTranscripcion, SesionTranscripcion
from .scoping import es_dependencia


class SesionTranscripcionAdminSerializer(serializers.ModelSerializer):
    jornada_nombre = serializers.CharField(source='jornada.nombre', read_only=True, default=None)

    class Meta:
        model = SesionTranscripcion
        fields = [
            'id', 'slug', 'nombre', 'descripcion', 'estado', 'jornada', 'jornada_nombre',
            'incluir_en_analisis_jornada', 'encargados', 'creado_por', 'creado_en',
            'actualizado_en', 'cerrada_en',
        ]
        read_only_fields = ['slug', 'estado', 'creado_por', 'creado_en', 'actualizado_en', 'cerrada_en']

    def get_fields(self):
        # Igual que InstrumentoAdminSerializer/JornadaAdminSerializer: dependencia nunca asigna/
        # reasigna encargados por acá — la vista lo fuerza a sí mismo al crear y lo deja fijo al
        # editar.
        fields = super().get_fields()
        request = self.context.get('request')
        if request is not None and es_dependencia(request.user):
            fields['encargados'].read_only = True
        return fields


class FragmentoTranscripcionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FragmentoTranscripcion
        fields = [
            'id', 'sesion', 'secuencia', 'texto', 'hablante', 'inicio_ms', 'fin_ms',
            'creado_en', 'actualizado_en',
        ]
        read_only_fields = ['id', 'sesion', 'creado_en', 'actualizado_en']


class FragmentoIngestaItemSerializer(serializers.Serializer):
    """Un fragmento tal como lo manda el front mientras la sesión está en curso. `secuencia` es
    el índice que el front le asigna a este pedazo en su propio stream (0, 1, 2, ...) — la ingesta
    hace update_or_create por (sesion, secuencia), así que reenviar el mismo fragmento (por un
    reintento de red) nunca lo duplica."""
    secuencia = serializers.IntegerField(min_value=0)
    texto = serializers.CharField(allow_blank=False)
    hablante = serializers.CharField(required=False, allow_blank=True, default='')
    inicio_ms = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=0)
    fin_ms = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=0)


class FragmentoIngestaSerializer(serializers.Serializer):
    fragmentos = FragmentoIngestaItemSerializer(many=True)


class InformeTranscripcionSerializer(serializers.ModelSerializer):
    sesion = serializers.SlugRelatedField(slug_field='slug', read_only=True)

    class Meta:
        model = InformeTranscripcion
        fields = [
            'id', 'sesion', 'estado', 'resultado', 'error_mensaje', 'modelo_usado',
            'presentacion_html', 'presentacion_estado', 'presentacion_error',
            'presentacion_modelo', 'presentacion_generada_en',
            'solicitado_por', 'creado_en', 'actualizado_en', 'completado_en',
        ]
        read_only_fields = fields


class InformeTranscripcionCrearSerializer(serializers.ModelSerializer):
    class Meta:
        model = InformeTranscripcion
        fields = ['id', 'sesion', 'estado', 'creado_en']
        read_only_fields = ['id', 'estado', 'creado_en']
