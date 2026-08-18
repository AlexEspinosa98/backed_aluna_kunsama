from rest_framework import serializers

from jornadas.models import Momento

from .models import PlantillaAnalisis, Reporte


class PlantillaAnalisisSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlantillaAnalisis
        fields = ['id', 'nombre', 'prompt_sistema', 'predeterminada', 'creada_por', 'creado_en', 'actualizado_en']
        read_only_fields = ['creada_por', 'creado_en', 'actualizado_en']


class MomentoResumenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Momento
        fields = ['id', 'titulo', 'orden']


class ReporteSerializer(serializers.ModelSerializer):
    jornada = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    momentos = MomentoResumenSerializer(many=True, read_only=True)
    plantilla_nombre = serializers.CharField(source='plantilla.nombre', read_only=True, default=None)

    class Meta:
        model = Reporte
        fields = [
            'id', 'jornada', 'momentos', 'alcance', 'plantilla', 'plantilla_nombre', 'estado',
            'error_mensaje', 'analisis', 'texto_reporte', 'modelo_usado',
            'solicitado_por', 'creado_en', 'actualizado_en', 'completado_en',
        ]
        read_only_fields = fields


class ReporteCrearSerializer(serializers.ModelSerializer):
    momentos = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Momento.objects.all(), required=False,
        help_text='Vacío = jornada completa. Uno = momento individual. Varios = momentos combinados.',
    )

    class Meta:
        model = Reporte
        fields = ['id', 'jornada', 'momentos', 'plantilla', 'alcance', 'estado', 'creado_en']
        read_only_fields = ['id', 'alcance', 'estado', 'creado_en']

    def validate(self, attrs):
        jornada = attrs['jornada']
        for momento in attrs.get('momentos') or []:
            if momento.jornada_id != jornada.id:
                raise serializers.ValidationError(
                    {'momentos': f'El momento "{momento.titulo}" no pertenece a la jornada seleccionada.'}
                )
        if attrs.get('plantilla') is None:
            attrs['plantilla'] = PlantillaAnalisis.objects.filter(predeterminada=True).first()
        return attrs

    def create(self, validated_data):
        momentos = validated_data.pop('momentos', [])
        if not momentos:
            alcance = Reporte.ALCANCE_JORNADA
        elif len(momentos) == 1:
            alcance = Reporte.ALCANCE_MOMENTO
        else:
            alcance = Reporte.ALCANCE_MOMENTOS
        reporte = Reporte.objects.create(alcance=alcance, **validated_data)
        if momentos:
            reporte.momentos.set(momentos)
        return reporte
