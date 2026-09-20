from rest_framework import serializers

from jornadas.models import Jornada, Momento

from .models import (
    AnalisisJornadaIA, AnalisisMomentoIA, InfografiaImagen, InfografiaJornada, PlantillaAnalisis,
    Reporte,
)
from .prompt_comun import ENFOQUE_CHOICES, ENFOQUE_DEFAULT, MAX_LARGO_TEXTO_LIBRE

# Campos del análisis guiado (HU-57, ver docs/HU_BACKEND_ANALISIS_GUIADO.md §1) comunes a los
# tres serializers de creación — un solo lugar para no repetir la lista tres veces y que agregar
# un campo nuevo el día de mañana sea un cambio en un solo sitio.
CAMPOS_ANALISIS_GUIADO = ['enfoque', 'contexto', 'instrucciones']
CAMPOS_ANALISIS_GUIADO_MOMENTO = CAMPOS_ANALISIS_GUIADO + ['contexto_momento', 'instrucciones_momento']


class PlantillaAnalisisSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlantillaAnalisis
        fields = [
            'id', 'nombre', 'tipo', 'prompt_sistema', 'predeterminada', 'creada_por',
            'creado_en', 'actualizado_en',
        ]
        read_only_fields = ['creada_por', 'creado_en', 'actualizado_en']


class MomentoResumenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Momento
        fields = ['id', 'titulo', 'slug', 'orden']


class ReporteSerializer(serializers.ModelSerializer):
    jornada = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    momentos = MomentoResumenSerializer(many=True, read_only=True)
    plantilla_nombre = serializers.CharField(source='plantilla.nombre', read_only=True, default=None)
    # Constante por modelo, no una columna — el frontend la usa para no tener que deducir el
    # método a partir del endpoint por el que llegó cada item (HU-57 §1).
    metodo = serializers.SerializerMethodField()

    class Meta:
        model = Reporte
        fields = [
            'id', 'slug', 'jornada', 'momentos', 'alcance', 'metodo', 'plantilla', 'plantilla_nombre',
            'enfoque', 'contexto', 'instrucciones', 'contexto_momento', 'instrucciones_momento',
            'estado', 'error_mensaje', 'analisis', 'texto_reporte', 'modelo_usado', 'prompt_usado',
            'presentacion_html', 'presentacion_estado', 'presentacion_error',
            'presentacion_modelo', 'presentacion_generada_en',
            'solicitado_por', 'creado_en', 'actualizado_en', 'completado_en',
        ]
        read_only_fields = fields

    def get_metodo(self, obj):
        return 'bertopic'


class ReporteCrearSerializer(serializers.ModelSerializer):
    momentos = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Momento.objects.all(), required=False,
        help_text='Vacío = jornada completa. Uno = momento individual. Varios = momentos combinados.',
    )

    class Meta:
        model = Reporte
        fields = [
            'id', 'jornada', 'momentos', 'plantilla', 'alcance', 'estado', 'creado_en',
            *CAMPOS_ANALISIS_GUIADO_MOMENTO,
        ]
        read_only_fields = ['id', 'alcance', 'estado', 'creado_en']

    def validate(self, attrs):
        # El guard de "sin respuestas en el alcance" (HU-57 §5) vive en ReporteViewSet.create(),
        # DESPUÉS de verificar_acceso_jornada — acá, dentro de is_valid(), correría antes que el
        # 403 de jornada ajena y lo taparía con un 400 (un admin de otra dependencia sabría, solo
        # por el código de estado, si esa jornada ajena tiene respuestas o no).
        jornada = attrs['jornada']
        for momento in attrs.get('momentos') or []:
            if momento.jornada_id != jornada.id:
                raise serializers.ValidationError(
                    {'momentos': f'El momento "{momento.titulo}" no pertenece a la jornada seleccionada.'}
                )
        if attrs.get('plantilla') is None:
            attrs['plantilla'] = PlantillaAnalisis.objects.filter(
                tipo=PlantillaAnalisis.TIPO_LOCAL, predeterminada=True
            ).first()
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


class AnalisisMomentoIASerializer(serializers.ModelSerializer):
    momento_titulo = serializers.CharField(source='momento.titulo', read_only=True)
    momento_orden = serializers.IntegerField(source='momento.orden', read_only=True)
    metodo = serializers.SerializerMethodField()

    class Meta:
        model = AnalisisMomentoIA
        fields = [
            'id', 'momento', 'momento_titulo', 'momento_orden', 'metodo', 'estado', 'resultado',
            'error_mensaje', 'modelo_usado', 'prompt_usado', *CAMPOS_ANALISIS_GUIADO_MOMENTO,
            'solicitado_por', 'creado_en', 'actualizado_en', 'completado_en',
        ]
        read_only_fields = fields

    def get_metodo(self, obj):
        return 'openai'


class AnalisisMomentoIACrearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalisisMomentoIA
        fields = ['id', 'momento', 'estado', 'creado_en', *CAMPOS_ANALISIS_GUIADO_MOMENTO]
        read_only_fields = ['id', 'estado', 'creado_en']
        # El guard de "sin respuestas" (HU-57 §5) vive en AnalisisMomentoIAViewSet.create(),
        # después de verificar_acceso_jornada — ver el comentario en ReporteCrearSerializer.


class AnalisisJornadaIASerializer(serializers.ModelSerializer):
    jornada = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    metodo = serializers.SerializerMethodField()

    class Meta:
        model = AnalisisJornadaIA
        fields = [
            'id', 'jornada', 'metodo', 'estado', 'resultado', 'error_mensaje', 'modelo_usado',
            'prompt_usado', *CAMPOS_ANALISIS_GUIADO,
            'solicitado_por', 'creado_en', 'actualizado_en', 'completado_en',
        ]
        read_only_fields = fields

    def get_metodo(self, obj):
        return 'openai'


class AnalisisJornadaIACrearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalisisJornadaIA
        fields = ['id', 'jornada', 'estado', 'creado_en', *CAMPOS_ANALISIS_GUIADO]
        read_only_fields = ['id', 'estado', 'creado_en']
        # El guard de "sin respuestas" (HU-57 §5) vive en AnalisisJornadaIAViewSet.create(),
        # después de verificar_acceso_jornada — ver el comentario en ReporteCrearSerializer.


class InfografiaImagenSerializer(serializers.ModelSerializer):
    class Meta:
        model = InfografiaImagen
        fields = ['id', 'archivo', 'orden']


class InfografiaJornadaSerializer(serializers.ModelSerializer):
    imagenes = InfografiaImagenSerializer(many=True, read_only=True)
    jornada_slug = serializers.CharField(source='jornada.slug', read_only=True)
    momento_titulo = serializers.CharField(source='momento.titulo', read_only=True, default=None)

    class Meta:
        model = InfografiaJornada
        fields = [
            'id', 'jornada', 'jornada_slug', 'momento', 'momento_titulo', 'reporte',
            'analisis_momento', 'analisis_jornada', 'estado',
            'instrucciones', 'prompt_usado', 'error_mensaje', 'modelo_usado', 'imagenes',
            'solicitado_por', 'creado_en', 'actualizado_en', 'completado_en',
        ]
        read_only_fields = fields


class InfografiaJornadaCrearSerializer(serializers.ModelSerializer):
    """Se pide sobre UN alcance: la jornada completa (`jornada`) o un momento (`momento`), nunca
    ambos. Con `momento`, la jornada se deriva sola de `momento.jornada` — pedirla también sería
    darle al cliente la oportunidad de mandar una combinación incoherente.

    `reporte`/`analisis_jornada` (alcance jornada) y `analisis_momento` (alcance momento) fijan
    de qué análisis concreto salen los datos, en vez del más reciente completo de ese alcance —
    una jornada o un momento puede tener varios análisis a la vez (HU-71: distintos métodos y
    enfoques), y "el más reciente" no es necesariamente el que quien pide la infografía está
    mirando en ese momento. Todos opcionales: sin ninguno, cae al más reciente (comportamiento de
    siempre). Ver el comentario en `InfografiaJornada` (models.py) y en
    `infografia_ia_openai._obtener_datos_analitica`.

    `instrucciones` es texto libre que se integra al prompt con precedencia sobre el estilo y la
    estructura por defecto — ver `_construir_prompt` en infografia_ia_openai.py."""

    class Meta:
        model = InfografiaJornada
        fields = [
            'id', 'jornada', 'momento', 'reporte', 'analisis_momento', 'analisis_jornada',
            'instrucciones', 'estado', 'creado_en',
        ]
        read_only_fields = ['id', 'estado', 'creado_en']
        extra_kwargs = {'jornada': {'required': False}}

    def validate(self, attrs):
        jornada = attrs.get('jornada')
        momento = attrs.get('momento')
        reporte = attrs.get('reporte')
        analisis_momento = attrs.get('analisis_momento')
        analisis_jornada = attrs.get('analisis_jornada')

        if bool(jornada) == bool(momento):
            raise serializers.ValidationError(
                'Manda exactamente uno: "jornada" (para la jornada completa) o "momento" (para '
                'un momento). No ambos, y no ninguno.'
            )

        if momento is not None:
            if reporte is not None:
                raise serializers.ValidationError({'reporte': (
                    'Un reporte es de jornada completa, así que no se combina con "momento".'
                )})
            if analisis_jornada is not None:
                raise serializers.ValidationError({'analisis_jornada': (
                    'Un AnalisisJornadaIA es de jornada completa, así que no se combina con '
                    '"momento" — para fijar el análisis de un momento usa "analisis_momento".'
                )})
            if analisis_momento is not None and analisis_momento.momento_id != momento.id:
                raise serializers.ValidationError({'analisis_momento': (
                    'Ese análisis no pertenece al momento seleccionado.'
                )})
            # Derivada, no pedida: así no hay forma de mandar un momento de otra jornada.
            attrs['jornada'] = momento.jornada
        else:
            if analisis_momento is not None:
                raise serializers.ValidationError({'analisis_momento': (
                    'Un AnalisisMomentoIA es de un momento puntual — con alcance de jornada usa '
                    '"analisis_jornada" (o "reporte" para el pipeline local).'
                )})
            if reporte is not None and analisis_jornada is not None:
                raise serializers.ValidationError((
                    'Manda como mucho uno de "reporte" o "analisis_jornada" — son dos métodos '
                    'distintos, no se combinan en la misma infografía.'
                ))
            if reporte is not None and reporte.jornada_id != jornada.id:
                raise serializers.ValidationError(
                    {'reporte': 'Ese reporte no pertenece a la jornada seleccionada.'}
                )
            if analisis_jornada is not None and analisis_jornada.jornada_id != jornada.id:
                raise serializers.ValidationError(
                    {'analisis_jornada': 'Ese análisis no pertenece a la jornada seleccionada.'}
                )
        return attrs


class AnalisisSugerenciasSerializer(serializers.Serializer):
    """Entrada de `POST /api/admin/analisis-sugerencias/` (HU-57 §3). No hay modelo detrás — nada
    de esto se persiste, es un ayudante de un solo uso para llenar el formulario del asistente."""
    METODO_CHOICES = [('bertopic', 'Pipeline local'), ('openai', 'Lectura integral con IA')]

    jornada = serializers.PrimaryKeyRelatedField(queryset=Jornada.objects.all())
    momentos = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Momento.objects.all(), required=False, default=list,
        help_text='Vacío = alcance de toda la jornada.',
    )
    metodo = serializers.ChoiceField(choices=METODO_CHOICES)
    enfoque = serializers.ChoiceField(choices=ENFOQUE_CHOICES, required=False, default=ENFOQUE_DEFAULT)
    contexto = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=MAX_LARGO_TEXTO_LIBRE, trim_whitespace=False,
    )
    instrucciones = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=MAX_LARGO_TEXTO_LIBRE, trim_whitespace=False,
    )

    def validate(self, attrs):
        jornada = attrs['jornada']
        for momento in attrs.get('momentos') or []:
            if momento.jornada_id != jornada.id:
                raise serializers.ValidationError(
                    {'momentos': f'El momento "{momento.titulo}" no pertenece a la jornada seleccionada.'}
                )
        return attrs
