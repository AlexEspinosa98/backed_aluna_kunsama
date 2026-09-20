from rest_framework import serializers

from jornadas.models import Jornada, Momento

from .models import (
    AnalisisJornadaIA, AnalisisMomentoIA, AnalisisV2, InfografiaImagen, InfografiaJornada,
    PlantillaAnalisis, Reporte,
)
from .prompt_comun import ENFOQUE_CHOICES, ENFOQUE_DEFAULT, MAX_LARGO_TEXTO_LIBRE
from .v2.contrato import VERSION

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
            'analisis_momento', 'analisis_jornada', 'analisis_v2', 'estado',
            'instrucciones', 'prompt_usado', 'error_mensaje', 'modelo_usado', 'imagenes',
            'solicitado_por', 'creado_en', 'actualizado_en', 'completado_en',
        ]
        read_only_fields = fields


class InfografiaJornadaCrearSerializer(serializers.ModelSerializer):
    """HU-73: cada infografía queda ATADA a una versión EXACTA de análisis — manda
    EXACTAMENTE uno de `reporte` (pipeline local), `analisis_momento` (lectura IA de un momento),
    `analisis_jornada` (lectura IA de jornada completa) o `analisis_v2` (contrato
    `kunsamu.analisis/v2`). `jornada`/`momento` se DERIVAN solos de esa versión (read-only en la
    salida, ignorados si vienen en el POST) — nunca se aceptan sueltos, porque desde HU-71 una
    jornada o un momento acumulan varias versiones de análisis a la vez (distintos métodos y
    enfoques) y aceptar solo "la jornada"/"el momento" obligaba a caer en el más reciente completo
    de ese alcance: dos versiones distintas podían terminar compartiendo o confundiéndose de
    infografía, exactamente lo que esta HU prohíbe. Ver el comentario en `InfografiaJornada`
    (models.py).

    `instrucciones` es texto libre que se integra al prompt con precedencia sobre el estilo y la
    estructura por defecto — ver `_construir_prompt` en infografia_ia_openai.py."""

    class Meta:
        model = InfografiaJornada
        fields = [
            'id', 'jornada', 'momento', 'reporte', 'analisis_momento', 'analisis_jornada',
            'analisis_v2', 'instrucciones', 'estado', 'creado_en',
        ]
        read_only_fields = ['id', 'jornada', 'momento', 'estado', 'creado_en']

    def validate(self, attrs):
        reporte = attrs.get('reporte')
        analisis_momento = attrs.get('analisis_momento')
        analisis_jornada = attrs.get('analisis_jornada')
        analisis_v2 = attrs.get('analisis_v2')

        elegidos = [v for v in (reporte, analisis_momento, analisis_jornada, analisis_v2) if v is not None]
        if len(elegidos) != 1:
            raise serializers.ValidationError(
                'Manda EXACTAMENTE uno de "reporte", "analisis_momento", "analisis_jornada" o '
                '"analisis_v2" — la infografía queda atada a esa versión exacta del análisis, nunca '
                'a "la jornada" o "el momento" en general (ver HU-73).'
            )

        if analisis_v2 is not None:
            momentos = list(analisis_v2.momentos.all())
            # Un por_momento de UN momento es "de" ese momento (título de portada, filtros); un
            # integral o un por_momento de varios es de la jornada.
            attrs['momento'] = momentos[0] if (
                analisis_v2.modo == analisis_v2.MODO_POR_MOMENTO and len(momentos) == 1
            ) else None
            attrs['jornada'] = analisis_v2.jornada
        elif analisis_momento is not None:
            attrs['momento'] = analisis_momento.momento
            attrs['jornada'] = analisis_momento.momento.jornada
        elif analisis_jornada is not None:
            attrs['momento'] = None
            attrs['jornada'] = analisis_jornada.jornada
        else:
            attrs['momento'] = None
            attrs['jornada'] = reporte.jornada
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


class PersonalizacionMomentoSerializer(serializers.Serializer):
    momento = serializers.PrimaryKeyRelatedField(queryset=Momento.objects.all())
    contexto = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=MAX_LARGO_TEXTO_LIBRE, trim_whitespace=False,
    )
    instrucciones = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=MAX_LARGO_TEXTO_LIBRE, trim_whitespace=False,
    )


class _AnalisisV2CamposDerivados(serializers.ModelSerializer):
    """Campos derivados comunes a la lectura de lista y de detalle."""
    jornada = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    jornada_id = serializers.IntegerField(read_only=True)
    momentos = MomentoResumenSerializer(many=True, read_only=True)
    version = serializers.SerializerMethodField()
    metodo = serializers.SerializerMethodField()
    estado_analitico = serializers.SerializerMethodField()

    def get_version(self, obj):
        return VERSION

    def get_metodo(self, obj):
        # Para que la agrupación actual del panel (bertopic / openai) siga funcionando sin cambios.
        return 'bertopic' if obj.pipeline == AnalisisV2.PIPELINE_BERTOPIC_LLM else 'openai'

    def get_estado_analitico(self, obj):
        return (obj.resultado or {}).get('estado')


class AnalisisV2ListaSerializer(_AnalisisV2CamposDerivados):
    """Sin `entrada`, `resultado`, `diagnostico` ni `prompt_usado`: la entrada contiene el corpus
    completo y el resultado puede pesar cientos de KB — en un listado que el panel consulta cada
    pocos segundos sería un desperdicio. El detalle (`retrieve`) sí trae todo."""
    class Meta:
        model = AnalisisV2
        fields = [
            'id', 'version', 'jornada', 'jornada_id', 'momentos', 'modo', 'pipeline', 'metodo',
            'contexto', 'instrucciones', 'personalizacion_momentos', 'estado', 'estado_analitico',
            'error_mensaje', 'version_prompt', 'version_esquema', 'modelo_usado', 'solicitado_por',
            'creado_en', 'actualizado_en', 'completado_en',
        ]
        read_only_fields = fields


class AnalisisV2Serializer(_AnalisisV2CamposDerivados):
    class Meta:
        model = AnalisisV2
        fields = AnalisisV2ListaSerializer.Meta.fields + ['resultado', 'entrada', 'diagnostico', 'prompt_usado']
        read_only_fields = fields


class AnalisisV2CrearSerializer(serializers.ModelSerializer):
    momentos = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Momento.objects.all(), required=False,
        help_text='Obligatorio y no vacío en por_momento; no se acepta en integral.',
    )
    personalizacion_momentos = PersonalizacionMomentoSerializer(many=True, required=False)

    class Meta:
        model = AnalisisV2
        fields = [
            'id', 'jornada', 'modo', 'pipeline', 'momentos', 'contexto', 'instrucciones',
            'personalizacion_momentos', 'estado', 'creado_en',
        ]
        read_only_fields = ['id', 'estado', 'creado_en']

    def validate(self, attrs):
        jornada = attrs['jornada']
        modo = attrs['modo']
        momentos = attrs.get('momentos') or []
        for momento in momentos:
            if momento.jornada_id != jornada.id:
                raise serializers.ValidationError(
                    {'momentos': f'El momento "{momento.titulo}" no pertenece a la jornada seleccionada.'}
                )
        if modo == AnalisisV2.MODO_INTEGRAL and momentos:
            raise serializers.ValidationError(
                {'momentos': 'En modo integral no se mandan momentos: el alcance es toda la jornada.'}
            )
        if modo == AnalisisV2.MODO_POR_MOMENTO:
            if not momentos:
                raise serializers.ValidationError({'momentos': 'En modo por_momento hay que indicar al menos un momento.'})
            if len({m.id for m in momentos}) != len(momentos):
                raise serializers.ValidationError({'momentos': 'Hay momentos repetidos.'})

        if modo == AnalisisV2.MODO_POR_MOMENTO:
            alcance_ids = {m.id for m in momentos}
        else:
            alcance_ids = set(jornada.momentos.values_list('id', flat=True))
        vistos = set()
        for item in attrs.get('personalizacion_momentos') or []:
            momento = item['momento']
            if momento.id not in alcance_ids:
                raise serializers.ValidationError(
                    {'personalizacion_momentos': f'El momento "{momento.titulo}" no está en el alcance del análisis.'}
                )
            if momento.id in vistos:
                raise serializers.ValidationError({'personalizacion_momentos': 'Un momento aparece más de una vez.'})
            vistos.add(momento.id)
        return attrs

    def create(self, validated_data):
        momentos = validated_data.pop('momentos', [])
        personalizacion = validated_data.pop('personalizacion_momentos', [])
        validated_data['personalizacion_momentos'] = [
            {
                'momento': item['momento'].id,
                'contexto': item.get('contexto') or '',
                'instrucciones': item.get('instrucciones') or '',
            }
            for item in personalizacion
        ]
        analisis = AnalisisV2.objects.create(**validated_data)
        if momentos:
            analisis.momentos.set(momentos)
        return analisis
