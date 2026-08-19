from rest_framework import serializers

from .models import Jornada, Momento, OpcionPregunta, Pregunta


class OpcionPreguntaSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpcionPregunta
        fields = ['id', 'pregunta', 'texto', 'orden']


class PreguntaAdminSerializer(serializers.ModelSerializer):
    opciones = OpcionPreguntaSerializer(many=True, read_only=True)

    class Meta:
        model = Pregunta
        fields = ['id', 'momento', 'tipo', 'texto', 'orden', 'obligatoria', 'activa', 'opciones']


class MomentoAdminSerializer(serializers.ModelSerializer):
    preguntas = PreguntaAdminSerializer(many=True, read_only=True)

    class Meta:
        model = Momento
        fields = [
            'id', 'jornada', 'orden', 'titulo', 'slug', 'contexto', 'tipo', 'categorias_semilla',
            'activo', 'preguntas',
        ]
        read_only_fields = ['slug']


class JornadaAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Jornada
        fields = [
            'id', 'slug', 'nombre', 'descripcion', 'fecha_inicio', 'fecha_fin',
            'activa', 'creada_por', 'creado_en', 'actualizado_en',
        ]
        read_only_fields = ['creada_por', 'creado_en', 'actualizado_en']


class JornadaPublicaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Jornada
        fields = ['slug', 'nombre', 'descripcion', 'fecha_inicio', 'fecha_fin', 'activa']
