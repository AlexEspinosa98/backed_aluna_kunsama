from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import (
    ColumnaMatrizPregunta, FilaMatrizPregunta, Jornada, Momento, OpcionPregunta, PerfilUsuario,
    Pregunta, RolJornada,
)
from .scoping import es_dependencia

Usuario = get_user_model()


class OpcionPreguntaSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpcionPregunta
        fields = ['id', 'pregunta', 'texto', 'orden']


class FilaMatrizPreguntaSerializer(serializers.ModelSerializer):
    class Meta:
        model = FilaMatrizPregunta
        fields = ['id', 'pregunta', 'texto', 'orden']


class ColumnaMatrizPreguntaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ColumnaMatrizPregunta
        fields = ['id', 'pregunta', 'texto', 'orden']


class PreguntaAdminSerializer(serializers.ModelSerializer):
    opciones = OpcionPreguntaSerializer(many=True, read_only=True)
    filas = FilaMatrizPreguntaSerializer(many=True, read_only=True)
    columnas = ColumnaMatrizPreguntaSerializer(many=True, read_only=True)

    class Meta:
        model = Pregunta
        fields = [
            'id', 'momento', 'tipo', 'texto', 'orden', 'obligatoria', 'activa',
            'mesas_permitidas', 'roles_permitidos', 'depende_de_opcion', 'opciones', 'filas', 'columnas',
        ]

    def validate(self, attrs):
        depende_de_opcion = attrs.get('depende_de_opcion')
        if depende_de_opcion is not None:
            momento = attrs.get('momento') or getattr(self.instance, 'momento', None)
            if depende_de_opcion.pregunta_id == getattr(self.instance, 'id', None):
                raise serializers.ValidationError(
                    {'depende_de_opcion': 'Una pregunta no puede depender de una opción de sí misma.'}
                )
            # Misma JORNADA, no necesariamente el mismo momento — un cuestionario real puede
            # tener un momento por bloque/letra (A, B, C...) y una pregunta condicionada por algo
            # respondido en un bloque anterior sigue siendo un caso válido (ej. "C5 depende de
            # A5"). condicion_cumplida (participantes/utils.py) ya soporta esto sin cambios: solo
            # consulta Respuesta por pregunta+opción, nunca asumió que fueran del mismo momento.
            if momento is not None and depende_de_opcion.pregunta.momento.jornada_id != momento.jornada_id:
                raise serializers.ValidationError(
                    {'depende_de_opcion': 'La opción de la que depende debe ser de una pregunta de la misma jornada.'}
                )
        return attrs


class MomentoAdminSerializer(serializers.ModelSerializer):
    preguntas = PreguntaAdminSerializer(many=True, read_only=True)

    class Meta:
        model = Momento
        fields = [
            'id', 'jornada', 'orden', 'titulo', 'slug', 'contexto', 'tipo', 'categorias_semilla',
            'mesas_permitidas', 'roles_permitidos', 'activo', 'preguntas',
        ]
        read_only_fields = ['slug']


class RolJornadaSerializer(serializers.ModelSerializer):
    class Meta:
        model = RolJornada
        fields = ['id', 'jornada', 'nombre', 'creado_en']


class JornadaAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Jornada
        fields = [
            'id', 'slug', 'nombre', 'descripcion', 'fecha_inicio', 'fecha_fin',
            'activa', 'creada_por', 'propietarios', 'creado_en', 'actualizado_en',
        ]
        read_only_fields = ['creada_por', 'creado_en', 'actualizado_en']

    def get_fields(self):
        # Un usuario de dependencia nunca puede asignar/reasignar propietarios por este medio —
        # la vista lo fuerza a sí mismo al crear (ver JornadaAdminViewSet.perform_create) y los
        # deja fijos al editar. Marcarlo read_only acá es solo para que quede reflejado en el
        # schema/response, la regla real vive en la vista.
        fields = super().get_fields()
        request = self.context.get('request')
        if request is not None and es_dependencia(request.user):
            fields['propietarios'].read_only = True
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
    `rol` no es un campo real de auth.User — vive en PerfilUsuario, ver create()/update(). El
    mismo rol "dependencia" aplica sin distinción a jornadas, instrumentos y transcripciones — un
    usuario puede estar a cargo de varias jornadas, varios instrumentos Y varias sesiones de
    transcripción a la vez (todos M2M independientes), así que esta es la vista "universal" de
    todo lo que un usuario tiene asignado en los tres módulos. instrumentos_a_cargo/
    transcripciones_a_cargo se resuelven por SerializerMethodField (en vez de importar los
    serializers de esas apps) para no acoplar esta app "base" a las apps de features — solo
    dependen del related_name que Instrumento.encargados/SesionTranscripcion.encargados ya dejan
    en el modelo User."""
    rol = serializers.ChoiceField(choices=PerfilUsuario.ROL_CHOICES, required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    jornadas_propias = JornadaResumenSerializer(many=True, read_only=True)
    instrumentos_a_cargo = serializers.SerializerMethodField()
    transcripciones_a_cargo = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'is_active',
            'rol', 'password', 'jornadas_propias', 'instrumentos_a_cargo',
            'transcripciones_a_cargo', 'date_joined',
        ]
        read_only_fields = ['id', 'date_joined']

    def get_instrumentos_a_cargo(self, instance):
        return [
            {'id': i.id, 'slug': i.slug, 'nombre': i.nombre, 'activo': i.activo}
            for i in instance.instrumentos_a_cargo.all()
        ]

    def get_transcripciones_a_cargo(self, instance):
        return [
            {'id': s.id, 'slug': s.slug, 'nombre': s.nombre, 'estado': s.estado}
            for s in instance.transcripciones_a_cargo.all()
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        perfil = getattr(instance, 'perfil', None)
        data['rol'] = perfil.rol if perfil else PerfilUsuario.ROL_ADMIN
        return data

    def validate_username(self, value):
        # El login ya no distingue mayúsculas/minúsculas (ver config/auth_backends.py) — sin este
        # chequeo se podrían crear "john" y "John" como cuentas distintas y el login quedaría
        # ambiguo entre ambas. El UniqueValidator automático de DRF solo compara exacto.
        queryset = Usuario.objects.filter(username__iexact=value)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                'Ya existe un usuario con ese nombre de usuario (sin distinguir mayúsculas/minúsculas).'
            )
        return value

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
