from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Jornada, Momento, OpcionPregunta, PerfilUsuario, Pregunta
from .scoping import es_dependencia

Usuario = get_user_model()


class OpcionPreguntaSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpcionPregunta
        fields = ['id', 'pregunta', 'texto', 'orden']


class PreguntaAdminSerializer(serializers.ModelSerializer):
    opciones = OpcionPreguntaSerializer(many=True, read_only=True)

    class Meta:
        model = Pregunta
        fields = [
            'id', 'momento', 'tipo', 'texto', 'orden', 'obligatoria', 'activa',
            'mesas_permitidas', 'opciones',
        ]


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
            'activa', 'creada_por', 'propietario', 'creado_en', 'actualizado_en',
        ]
        read_only_fields = ['creada_por', 'creado_en', 'actualizado_en']

    def get_fields(self):
        # Un usuario de dependencia nunca puede asignar/reasignar propietario por este medio —
        # la vista lo fuerza a sí mismo al crear (ver JornadaAdminViewSet.perform_create) y lo
        # deja fijo al editar. Marcarlo read_only acá es solo para que quede reflejado en el
        # schema/response, la regla real vive en la vista.
        fields = super().get_fields()
        request = self.context.get('request')
        if request is not None and es_dependencia(request.user):
            fields['propietario'].read_only = True
        return fields


class JornadaPublicaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Jornada
        fields = ['slug', 'nombre', 'descripcion', 'fecha_inicio', 'fecha_fin', 'activa']


class JornadaResumenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Jornada
        fields = ['id', 'slug', 'nombre', 'activa']


class UsuarioAdminSerializer(serializers.ModelSerializer):
    """CRUD de usuarios admin/dependencia para EsAdminCompleto (ver jornadas/permissions.py).
    `rol` no es un campo real de auth.User — vive en PerfilUsuario, ver create()/update()."""
    rol = serializers.ChoiceField(choices=PerfilUsuario.ROL_CHOICES, required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    jornadas_propias = JornadaResumenSerializer(many=True, read_only=True)

    class Meta:
        model = Usuario
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'is_active',
            'rol', 'password', 'jornadas_propias', 'date_joined',
        ]
        read_only_fields = ['id', 'date_joined']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        perfil = getattr(instance, 'perfil', None)
        data['rol'] = perfil.rol if perfil else PerfilUsuario.ROL_ADMIN
        return data

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        rol = validated_data.pop('rol', PerfilUsuario.ROL_DEPENDENCIA)
        password = validated_data.pop('password', None)
        if not password:
            raise serializers.ValidationError({'password': 'La contraseña es obligatoria al crear un usuario.'})
        usuario = Usuario(is_staff=True, **validated_data)
        usuario.set_password(password)
        usuario.save()
        PerfilUsuario.objects.create(user=usuario, rol=rol)
        return usuario

    def update(self, instance, validated_data):
        rol = validated_data.pop('rol', None)
        password = validated_data.pop('password', None)
        for atributo, valor in validated_data.items():
            setattr(instance, atributo, valor)
        if password:
            instance.set_password(password)
        instance.save()
        if rol is not None:
            PerfilUsuario.objects.update_or_create(user=instance, defaults={'rol': rol})
        return instance
