from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from jornadas.models import ColumnaMatrizPregunta, FilaMatrizPregunta, Momento, OpcionPregunta, Pregunta

from .models import ExtraccionMomento, Participante, Respuesta


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


class ParticipanteLoginSerializer(serializers.Serializer):
    """El participante no tiene contraseña — su correo institucional (único por jornada, ver
    unique_together en el modelo) es la única prueba de identidad para recuperar su token si
    cerró la sesión o cambió de dispositivo."""
    correo_institucional = serializers.EmailField()


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


class FilaMatrizPreguntaSerializer(serializers.ModelSerializer):
    class Meta:
        model = FilaMatrizPregunta
        fields = ['id', 'texto', 'orden']


class ColumnaMatrizPreguntaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ColumnaMatrizPregunta
        fields = ['id', 'texto', 'orden']


class PreguntaSerializer(serializers.ModelSerializer):
    opciones = OpcionPreguntaSerializer(many=True, read_only=True)
    filas = FilaMatrizPreguntaSerializer(many=True, read_only=True)
    columnas = ColumnaMatrizPreguntaSerializer(many=True, read_only=True)

    class Meta:
        model = Pregunta
        fields = ['id', 'tipo', 'texto', 'orden', 'obligatoria', 'opciones', 'filas', 'columnas']


class MomentoIndiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Momento
        fields = ['id', 'orden', 'titulo', 'slug', 'tipo']


class MomentoDetalleSerializer(serializers.ModelSerializer):
    preguntas = serializers.SerializerMethodField()

    class Meta:
        model = Momento
        fields = ['id', 'orden', 'titulo', 'slug', 'contexto', 'tipo', 'preguntas']

    @extend_schema_field(PreguntaSerializer(many=True))
    def get_preguntas(self, momento):
        # Pregunta.mesas_permitidas (opcional) restringe una pregunta a ciertas mesas dentro de
        # un momento tipo mesa — vacía = visible para todas, igual que siempre. No aplica a
        # momentos individuales, donde no existe el concepto de "mesa" del participante.
        # Pregunta.roles_permitidos (opcional) hace lo mismo por rol — a diferencia de mesa, sí
        # aplica en cualquier tipo de momento, porque todo participante tiene un rol.
        participante = self.context['request'].user
        preguntas = [
            p for p in momento.preguntas.all()
            if not p.roles_permitidos or participante.rol in p.roles_permitidos
        ]
        if momento.tipo == Momento.TIPO_MESA:
            preguntas = [
                p for p in preguntas
                if not p.mesas_permitidas or participante.mesa in p.mesas_permitidas
            ]
        return PreguntaSerializer(preguntas, many=True).data


class RespuestaEntradaSerializer(serializers.Serializer):
    pregunta_id = serializers.PrimaryKeyRelatedField(source='pregunta', queryset=Pregunta.objects.all())
    texto_libre = serializers.CharField(required=False, allow_blank=True, default='')
    opcion_ids = serializers.PrimaryKeyRelatedField(
        source='opciones', queryset=OpcionPregunta.objects.all(), many=True, required=False, default=list
    )
    # Solo se usan en preguntas tipo matriz (una celda = una entrada). allow_null=True a propósito
    # (no solo required=False): así se puede mandar el campo en null en vez de tener que omitirlo,
    # que es justo lo que hace la extracción por IA para no tener que armar el payload distinto
    # según el tipo de cada pregunta — ver el bug ya corregido una vez en
    # instrumentos/extraccion_ia_openai.py por esto mismo.
    fila_id = serializers.PrimaryKeyRelatedField(
        source='fila', queryset=FilaMatrizPregunta.objects.all(), required=False, allow_null=True,
    )
    columna_id = serializers.PrimaryKeyRelatedField(
        source='columna', queryset=ColumnaMatrizPregunta.objects.all(), required=False, allow_null=True,
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
        fields = [
            'id', 'pregunta', 'participante', 'mesa', 'fila', 'columna', 'texto_libre', 'opciones',
            'actualizado_en',
        ]


class ExtraccionMomentoSerializer(serializers.ModelSerializer):
    momento_titulo = serializers.CharField(source='momento.titulo', read_only=True)
    participante_nombre = serializers.SerializerMethodField()

    class Meta:
        model = ExtraccionMomento
        fields = [
            'id', 'momento', 'momento_titulo', 'participante', 'participante_nombre',
            'nombre_archivo_original', 'estado', 'resultado', 'preguntas_omitidas',
            'error_mensaje', 'modelo_usado', 'aprobado_en', 'aprobado_por', 'solicitado_por',
            'creado_en', 'actualizado_en', 'completado_en',
        ]
        read_only_fields = fields

    def get_participante_nombre(self, extraccion):
        return f'{extraccion.participante.nombre} {extraccion.participante.apellido}'.strip()


class ExtraccionMomentoCrearSerializer(serializers.ModelSerializer):
    """Sube un .pdf o .docx ya diligenciado para dispararle la extracción con IA. Admite
    `participante_id` (persona ya registrada en la jornada) o los mismos campos que
    ParticipanteRegistroSerializer para dar de alta a alguien nuevo en el mismo request — el
    departamento que ya llenó el papel puede no haberse registrado nunca en el sistema."""
    participante_id = serializers.PrimaryKeyRelatedField(
        source='participante', queryset=Participante.objects.all(), required=False,
    )
    correo_institucional = serializers.EmailField(write_only=True, required=False)
    nombre = serializers.CharField(write_only=True, required=False)
    apellido = serializers.CharField(write_only=True, required=False)
    telefono = serializers.CharField(write_only=True, required=False, allow_blank=True)
    rol = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = ExtraccionMomento
        fields = [
            'id', 'momento', 'archivo', 'participante_id', 'correo_institucional', 'nombre',
            'apellido', 'telefono', 'rol', 'estado', 'creado_en',
        ]
        read_only_fields = ['id', 'estado', 'creado_en']

    def validate_archivo(self, archivo):
        extension = archivo.name.rsplit('.', 1)[-1].lower() if '.' in archivo.name else ''
        if extension not in ('pdf', 'docx'):
            raise serializers.ValidationError('Solo se aceptan archivos .pdf o .docx.')
        return archivo

    def validate(self, attrs):
        if 'participante' in attrs:
            if attrs['participante'].jornada_id != attrs['momento'].jornada_id:
                raise serializers.ValidationError(
                    {'participante_id': 'Ese participante no pertenece a la jornada de este momento.'}
                )
            return attrs
        faltantes = [c for c in ('correo_institucional', 'nombre', 'apellido', 'rol') if c not in attrs]
        if faltantes:
            raise serializers.ValidationError(
                'Debes indicar participante_id (de alguien ya registrado) o '
                'correo_institucional+nombre+apellido+rol (para registrar a alguien nuevo).'
            )
        return attrs

    def create(self, validated_data):
        participante = validated_data.pop('participante', None)
        if participante is None:
            jornada = validated_data['momento'].jornada
            correo = validated_data.pop('correo_institucional')
            existente = Participante.objects.filter(jornada=jornada, correo_institucional=correo).first()
            if existente:
                participante = existente
                for campo in ('nombre', 'apellido', 'telefono', 'rol'):
                    validated_data.pop(campo, None)
            else:
                participante = Participante.objects.create(
                    jornada=jornada, correo_institucional=correo,
                    nombre=validated_data.pop('nombre'), apellido=validated_data.pop('apellido'),
                    telefono=validated_data.pop('telefono', ''), rol=validated_data.pop('rol'),
                )
        else:
            for campo in ('correo_institucional', 'nombre', 'apellido', 'telefono', 'rol'):
                validated_data.pop(campo, None)
        validated_data['participante'] = participante
        validated_data['nombre_archivo_original'] = validated_data['archivo'].name
        return super().create(validated_data)
