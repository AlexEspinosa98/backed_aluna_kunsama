from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import (
    AplicacionInstrumento, ColumnaMatrizInstrumento, FilaMatrizInstrumento, Instrumento,
    OpcionPreguntaInstrumento, PreguntaInstrumento, PreregistroInstrumento, RespuestaInstrumento,
    SeccionInstrumento,
)
from .scoping import es_dependencia

Usuario = get_user_model()


class OpcionPreguntaInstrumentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpcionPreguntaInstrumento
        fields = ['id', 'pregunta', 'texto', 'orden']


class FilaMatrizInstrumentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = FilaMatrizInstrumento
        fields = ['id', 'pregunta', 'texto', 'orden']


class ColumnaMatrizInstrumentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ColumnaMatrizInstrumento
        fields = ['id', 'pregunta', 'texto', 'orden']


class PreguntaInstrumentoAdminSerializer(serializers.ModelSerializer):
    opciones = OpcionPreguntaInstrumentoSerializer(many=True, read_only=True)
    filas = FilaMatrizInstrumentoSerializer(many=True, read_only=True)
    columnas = ColumnaMatrizInstrumentoSerializer(many=True, read_only=True)

    class Meta:
        model = PreguntaInstrumento
        fields = [
            'id', 'seccion', 'tipo', 'texto', 'orden', 'obligatoria', 'activa',
            'opciones', 'filas', 'columnas',
        ]


class SeccionInstrumentoAdminSerializer(serializers.ModelSerializer):
    preguntas = PreguntaInstrumentoAdminSerializer(many=True, read_only=True)

    class Meta:
        model = SeccionInstrumento
        fields = ['id', 'instrumento', 'orden', 'titulo', 'tipo', 'contenido', 'activa', 'preguntas']


class InstrumentoAdminSerializer(serializers.ModelSerializer):
    secciones = SeccionInstrumentoAdminSerializer(many=True, read_only=True)

    class Meta:
        model = Instrumento
        fields = [
            'id', 'slug', 'nombre', 'descripcion', 'activo', 'encargados', 'creado_por',
            'creado_en', 'actualizado_en', 'secciones',
        ]
        read_only_fields = ['slug', 'creado_por', 'creado_en', 'actualizado_en']

    def get_fields(self):
        # Igual que JornadaAdminSerializer: un usuario de dependencia nunca asigna/reasigna
        # encargados por este medio — la vista lo fuerza a sí mismo al crear y lo deja fijo al
        # editar (ver InstrumentoAdminViewSet).
        fields = super().get_fields()
        request = self.context.get('request')
        if request is not None and es_dependencia(request.user):
            fields['encargados'].read_only = True
        return fields


class InstrumentoResumenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instrumento
        fields = ['id', 'slug', 'nombre', 'activo']


class PreregistroInstrumentoAdminSerializer(serializers.ModelSerializer):
    """Crea un preregistro a partir de un usuario_id existente, o de los datos para dar de alta un
    User nuevo (mismo patrón que jornadas.serializers.UsuarioAdminSerializer.create, pero
    is_staff=False y sin fila en PerfilUsuario — un preregistrado no es admin ni dependencia)."""
    usuario_id = serializers.PrimaryKeyRelatedField(
        source='usuario', queryset=Usuario.objects.all(), required=False,
    )
    username = serializers.CharField(write_only=True, required=False)
    email = serializers.EmailField(write_only=True, required=False, allow_blank=True)
    first_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    last_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    estado_visible = serializers.SerializerMethodField()

    class Meta:
        model = PreregistroInstrumento
        fields = [
            'id', 'instrumento', 'usuario_id', 'username', 'email', 'first_name', 'last_name',
            'password', 'creado_por', 'creado_en', 'estado_visible',
        ]
        read_only_fields = ['creado_por', 'creado_en']

    def get_unique_together_validators(self):
        # DRF exige que todo campo de un unique_together esté 'required' salvo que declaremos acá
        # que no lo validamos automáticamente — 'usuario_id' es opcional a propósito (se puede
        # crear el User en el mismo request), así que la duplicidad se valida a mano en validate().
        return []

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['usuario_id'] = instance.usuario_id
        data['username'] = instance.usuario.username
        data['email'] = instance.usuario.email
        data['first_name'] = instance.usuario.first_name
        data['last_name'] = instance.usuario.last_name
        return data

    def get_estado_visible(self, instance):
        aplicacion = getattr(instance, 'aplicacion', None)
        return aplicacion.estado_visible if aplicacion else 'sin_enviar'

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        if 'usuario' not in attrs and 'username' not in attrs:
            raise serializers.ValidationError(
                'Debes indicar usuario_id (de un usuario existente) o username+password (para '
                'crear uno nuevo).'
            )
        if 'usuario' in attrs and PreregistroInstrumento.objects.filter(
            instrumento=attrs['instrumento'], usuario=attrs['usuario']
        ).exists():
            raise serializers.ValidationError('Este usuario ya está preregistrado en este instrumento.')
        return attrs

    def create(self, validated_data):
        usuario = validated_data.pop('usuario', None)
        if usuario is None:
            username = validated_data.pop('username', None)
            password = validated_data.pop('password', None)
            if not username or not password:
                raise serializers.ValidationError(
                    {'password': 'La contraseña es obligatoria al crear un usuario nuevo.'}
                )
            usuario = Usuario(
                username=username,
                email=validated_data.pop('email', ''),
                first_name=validated_data.pop('first_name', ''),
                last_name=validated_data.pop('last_name', ''),
                is_staff=False,
            )
            usuario.set_password(password)
            usuario.save()
        else:
            for campo in ['username', 'email', 'first_name', 'last_name', 'password']:
                validated_data.pop(campo, None)
        validated_data['usuario'] = usuario
        return super().create(validated_data)


class RespuestaInstrumentoSalidaSerializer(serializers.ModelSerializer):
    class Meta:
        model = RespuestaInstrumento
        fields = ['id', 'pregunta', 'fila', 'columna', 'texto_libre', 'opciones']


class AplicacionInstrumentoAdminSerializer(serializers.ModelSerializer):
    estado_visible = serializers.CharField(read_only=True)
    respuestas = RespuestaInstrumentoSalidaSerializer(many=True, read_only=True)
    instrumento = serializers.SlugRelatedField(source='preregistro.instrumento', slug_field='slug', read_only=True)
    usuario = serializers.CharField(source='preregistro.usuario.username', read_only=True)

    class Meta:
        model = AplicacionInstrumento
        fields = [
            'id', 'preregistro', 'instrumento', 'usuario', 'estado', 'estado_visible',
            'enviado_en', 'revisado_por', 'revisado_en', 'comentario_revision', 'respuestas',
        ]
        read_only_fields = fields


class RevisionAplicacionSerializer(serializers.Serializer):
    estado = serializers.ChoiceField(
        choices=[AplicacionInstrumento.ESTADO_ACEPTADO, AplicacionInstrumento.ESTADO_RECHAZADO]
    )
    comentario_revision = serializers.CharField(required=False, allow_blank=True)
