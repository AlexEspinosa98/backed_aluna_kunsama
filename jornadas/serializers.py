from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import (
    ColumnaMatrizPregunta, FilaMatrizPregunta, Jornada, JornadaAsset, Momento, OpcionPregunta,
    PerfilUsuario, Pregunta, RolJornada,
)
from .scoping import es_dependencia

Usuario = get_user_model()

EXTENSIONES_POR_TIPO_ASSET = {
    JornadaAsset.TIPO_ASSET: ('png', 'jpg', 'jpeg', 'webp', 'gif'),
    JornadaAsset.TIPO_SYSTEM_DESIGN: ('png', 'jpg', 'jpeg', 'webp', 'gif', 'pdf'),
}


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
            'id', 'momento', 'tipo', 'texto', 'orden', 'obligatoria', 'activa', 'filas_adicionales',
            'mesas_permitidas', 'roles_permitidos', 'depende_de_opcion', 'opciones', 'filas', 'columnas',
        ]

    def _validar_filas_adicionales(self, attrs):
        """`filas_adicionales` (ver Pregunta) no puede tener un único default a nivel de modelo
        porque el suyo depende del tipo: apagado en matriz, encendido en lista. Acá sí se puede,
        porque este es el único punto que distingue "no mandaron el campo" de "lo mandaron en
        False" — con el campo ausente se aplica el default del tipo, y con el campo presente se
        validan las dos combinaciones que no tienen sentido."""
        tipo = attrs.get('tipo') or getattr(self.instance, 'tipo', None)
        if tipo is None:
            return

        if 'filas_adicionales' not in attrs:
            if self.instance is None:
                attrs['filas_adicionales'] = tipo == Pregunta.TIPO_LISTA
                return
            # PATCH que no toca el campo: si cambió el tipo, el valor viejo puede haber quedado
            # en una combinación inválida, así que se re-encuadra en vez de dejarlo inconsistente.
            if tipo == Pregunta.TIPO_LISTA:
                attrs['filas_adicionales'] = True
            elif tipo != Pregunta.TIPO_MATRIZ and self.instance.filas_adicionales:
                attrs['filas_adicionales'] = False
            return

        filas_adicionales = attrs['filas_adicionales']
        if tipo == Pregunta.TIPO_LISTA and not filas_adicionales:
            raise serializers.ValidationError({'filas_adicionales': (
                'Una pregunta tipo lista no puede deshabilitar filas adicionales: sus filas son '
                'justamente las que agrega quien responde.'
            )})
        if filas_adicionales and tipo not in (Pregunta.TIPO_MATRIZ, Pregunta.TIPO_LISTA):
            raise serializers.ValidationError({'filas_adicionales': (
                f'Solo las preguntas tipo matriz o lista pueden permitir filas adicionales '
                f'(esta es tipo {tipo}).'
            )})

    def validate(self, attrs):
        self._validar_filas_adicionales(attrs)
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


class CreadoPorSerializer(serializers.ModelSerializer):
    """Atribución mínima (banco de instrumentos) — nunca el usuario completo: acá no importa el
    email ni si está activo, solo quién es para mostrarlo en el listado del banco."""
    nombre = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = ['id', 'username', 'nombre']

    def get_nombre(self, obj):
        return obj.get_full_name() or obj.username


class MomentoAdminSerializer(serializers.ModelSerializer):
    preguntas = PreguntaAdminSerializer(many=True, read_only=True)
    # `creado_por` lo fija perform_create desde request.user (ver MomentoAdminViewSet) — nunca
    # el body (C04). `momento_origen`/`origen_info` solo los escribe jornadas.banco.copiar_momento.
    creado_por = CreadoPorSerializer(read_only=True)

    class Meta:
        model = Momento
        fields = [
            'id', 'jornada', 'orden', 'titulo', 'slug', 'contexto', 'tipo', 'categorias_semilla',
            'mesas_permitidas', 'roles_permitidos', 'permite_carga_archivo', 'activo',
            'visibilidad', 'creado_por', 'momento_origen', 'origen_info', 'preguntas',
        ]
        read_only_fields = ['slug', 'momento_origen', 'origen_info']


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


class JornadaAssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = JornadaAsset
        fields = [
            'id', 'jornada', 'tipo', 'archivo', 'nombre_archivo_original', 'texto', 'subido_por',
            'creado_en',
        ]
        read_only_fields = ['nombre_archivo_original', 'subido_por', 'creado_en']


class JornadaAssetCrearSerializer(serializers.Serializer):
    """Carga **en bloque**: un solo POST con varios archivos (y/o un texto de guía de marca),
    todos de la misma jornada y el mismo `tipo` — que es como se cargan de verdad: se arrastran
    de una vez las fotos de la jornada, y la guía de marca va aparte. Un `tipo` por request y no
    por archivo porque mezclar fotos y guía de marca en la misma tanda no es un caso real, y
    mapear tipo-por-archivo en multipart es frágil.

    **Todo o nada**: si un archivo no pasa la validación no se crea ninguno. Una tanda a medias
    deja al cliente adivinando cuáles de los 5 entraron, que es peor que reintentar los 5."""
    jornada = serializers.PrimaryKeyRelatedField(queryset=Jornada.objects.all())
    tipo = serializers.ChoiceField(choices=JornadaAsset.TIPO_CHOICES, default=JornadaAsset.TIPO_ASSET)
    archivos = serializers.ListField(child=serializers.FileField(), required=False, default=list)
    texto = serializers.CharField(required=False, allow_blank=True, default='', trim_whitespace=True)

    def _mensaje_sin_archivos(self, mensaje):
        """Si mandaron `archivo` (singular) el problema no es que falte el archivo sino que el
        campo se llama distinto — decir "manda al menos un archivo" cuando la persona SÍ mandó uno
        manda a buscar el error al lado equivocado. Pasó de verdad al integrar el FE."""
        entrada = self.initial_data
        nombres = entrada.keys() if hasattr(entrada, 'keys') else []
        if 'archivo' in nombres:
            return (
                'El campo se llama "archivos" (en plural, repetido una vez por archivo), no '
                '"archivo": la carga es en bloque desde HU-59.'
            )
        return mensaje

    def validate(self, attrs):
        tipo = attrs['tipo']
        archivos = attrs['archivos']
        texto = attrs['texto']

        if tipo == JornadaAsset.TIPO_ASSET:
            if texto:
                raise serializers.ValidationError({'texto': (
                    'Solo un system_design puede ser texto — un asset es una imagen que se usa '
                    'como referencia visual.'
                )})
            if not archivos:
                raise serializers.ValidationError({'archivos': self._mensaje_sin_archivos(
                    'Manda al menos un archivo.'
                )})
        elif not archivos and not texto:
            raise serializers.ValidationError({'archivos': self._mensaje_sin_archivos(
                'Un system_design necesita al menos un archivo o un texto con la guía de marca.'
            )})

        permitidas = EXTENSIONES_POR_TIPO_ASSET[tipo]
        for archivo in archivos:
            extension = archivo.name.rsplit('.', 1)[-1].lower() if '.' in archivo.name else ''
            if extension not in permitidas:
                raise serializers.ValidationError({'archivos': (
                    f'"{archivo.name}": formato no soportado para tipo "{tipo}". Solo se aceptan '
                    f'{", ".join("." + ext for ext in permitidas)}.'
                )})
        return attrs

    def create(self, validated_data):
        comunes = {
            'jornada': validated_data['jornada'],
            'tipo': validated_data['tipo'],
            'subido_por': validated_data.get('subido_por'),
        }
        creados = [
            JornadaAsset.objects.create(
                archivo=archivo, nombre_archivo_original=archivo.name, **comunes,
            )
            for archivo in validated_data['archivos']
        ]
        # El texto va en su propia fila, no pegado a uno de los archivos: así cada referencia es
        # un recurso con id propio (se puede borrar el texto sin borrar la imagen) y no hay que
        # decidir a cuál de los N archivos "pertenece".
        if validated_data['texto']:
            creados.append(JornadaAsset.objects.create(texto=validated_data['texto'], **comunes))
        return creados


class JornadaPublicaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Jornada
        fields = ['slug', 'nombre', 'descripcion', 'fecha_inicio', 'fecha_fin', 'activa']


class JornadaResumenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Jornada
        fields = ['id', 'slug', 'nombre', 'activa']


class BancoMomentoListaSerializer(serializers.ModelSerializer):
    """Item del listado/derivados del banco de instrumentos — de solo lectura a propósito (sin
    ids "editables" que tienten al FE a mandar un PATCH acá; eso sigue siendo /momentos/{id}/)."""
    creado_por = CreadoPorSerializer(read_only=True)
    jornada = JornadaResumenSerializer(read_only=True)
    contexto = serializers.SerializerMethodField()
    # Las anotaciones (n_preguntas, n_preguntas_inactivas, veces_usado) las agrega el queryset —
    # ver jornadas.scoping.anotar_conteos_banco — acá solo se declaran para que entren al schema.
    n_preguntas = serializers.IntegerField(read_only=True)
    n_preguntas_inactivas = serializers.IntegerField(read_only=True)
    veces_usado = serializers.IntegerField(read_only=True)
    es_mio = serializers.SerializerMethodField()
    puedo_editar = serializers.SerializerMethodField()

    class Meta:
        model = Momento
        fields = [
            'id', 'titulo', 'slug', 'tipo', 'contexto', 'visibilidad', 'activo', 'creado_por',
            'jornada', 'n_preguntas', 'n_preguntas_inactivas', 'veces_usado', 'momento_origen',
            'es_mio', 'puedo_editar', 'creado_en', 'actualizado_en',
        ]

    def get_contexto(self, obj):
        return (obj.contexto or '')[:200]

    def _jornadas_propias_ids(self):
        # Precalculado por la vista (BancoMomentoViewSet.get_serializer_context) y pasado acá por
        # context, para no hacer una query "¿soy propietario de esta jornada?" por cada item.
        return self.context.get('jornadas_propias_ids', set())

    def get_es_mio(self, obj):
        return obj.jornada_id in self._jornadas_propias_ids()

    def get_puedo_editar(self, obj):
        # D4/D15: cualquier propietario de la jornada edita (igual que hoy); admin completo,
        # siempre. Terceros nunca — ni siquiera sobre un público ajeno.
        request = self.context.get('request')
        if request is not None and not es_dependencia(request.user):
            return True
        return self.get_es_mio(obj)


class BancoMomentoDetalleSerializer(BancoMomentoListaSerializer):
    """Igual que el listado, pero con `contexto` completo (sin recortar) y el árbol de
    preguntas — para previsualizar antes de usar/."""
    preguntas = PreguntaAdminSerializer(many=True, read_only=True)

    class Meta(BancoMomentoListaSerializer.Meta):
        fields = BancoMomentoListaSerializer.Meta.fields + ['preguntas']

    def get_contexto(self, obj):
        return obj.contexto


class UsarMomentoSerializer(serializers.Serializer):
    """Body de `POST /banco-momentos/{id}/usar/`. La jornada se valida como PK simple acá (404
    si no existe el id -> 400 'Objeto inválido' por DRF) y como "es mía" en la vista, vía
    verificar_acceso_jornada — acá no hay usuario en contexto para aplicar ese scoping."""
    jornada = serializers.PrimaryKeyRelatedField(queryset=Jornada.objects.all())
    titulo = serializers.CharField(required=False, allow_blank=False, max_length=255)
    orden = serializers.IntegerField(required=False, min_value=1)
    visibilidad = serializers.ChoiceField(choices=Momento.VISIBILIDAD_CHOICES, required=False)


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
