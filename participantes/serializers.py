from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from jornadas.models import ColumnaMatrizPregunta, FilaMatrizPregunta, Momento, OpcionPregunta, Pregunta

from .models import ExtraccionMomento, Participante, Respuesta
from .utils import condicion_cumplida


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
        # `filas_adicionales` viaja acá porque es lo único que le dice al front si debe pintar el
        # botón de "agregar fila" en una matriz (en una lista siempre va encendido).
        fields = [
            'id', 'tipo', 'texto', 'orden', 'obligatoria', 'filas_adicionales', 'opciones',
            'filas', 'columnas',
        ]


class MomentoIndiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Momento
        fields = ['id', 'orden', 'titulo', 'slug', 'tipo', 'permite_carga_archivo']


class MomentoDetalleSerializer(serializers.ModelSerializer):
    preguntas = serializers.SerializerMethodField()

    class Meta:
        model = Momento
        # `permite_carga_archivo` es lo único que le dice al FE si mostrar el botón de subir un
        # documento diligenciado para este momento (ver MomentoCargarArchivoView).
        fields = [
            'id', 'orden', 'titulo', 'slug', 'contexto', 'tipo', 'permite_carga_archivo',
            'preguntas',
        ]

    @extend_schema_field(PreguntaSerializer(many=True))
    def get_preguntas(self, momento):
        # Pregunta.mesas_permitidas (opcional) restringe una pregunta a ciertas mesas dentro de
        # un momento tipo mesa — vacía = visible para todas, igual que siempre. No aplica a
        # momentos individuales, donde no existe el concepto de "mesa" del participante.
        # Pregunta.roles_permitidos (opcional) hace lo mismo por rol — a diferencia de mesa, sí
        # aplica en cualquier tipo de momento, porque todo participante tiene un rol.
        # depende_de_opcion (opcional) oculta la pregunta hasta que el participante ya haya
        # marcado esa opción específica en la pregunta de la que depende (condicion_cumplida).
        participante = self.context['request'].user
        preguntas = [
            p for p in momento.preguntas.all()
            if (not p.roles_permitidos or participante.rol in p.roles_permitidos)
            and condicion_cumplida(p, participante)
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
    # Solo se usa en preguntas tipo lista (ver Pregunta.TIPO_LISTA). NO es el id de una fila que
    # ya existe en la base — es un número que el propio cliente inventa para decir "estas celdas
    # van juntas, en la misma fila que agregué yo" (ej. fila_temporal=1 para el primer profesor
    # que reporta, =2 para el segundo...). El backend usa esto solo para agrupar las celdas del
    # envío antes de crear las FilaListaRespuesta reales — no se guarda tal cual en ningún lado.
    fila_temporal = serializers.IntegerField(required=False, allow_null=True, default=None)


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
            'id', 'pregunta', 'participante', 'mesa', 'version', 'fila', 'fila_lista', 'columna',
            'texto_libre', 'opciones', 'actualizado_en',
        ]


class ExtraccionMomentoSerializer(serializers.ModelSerializer):
    momento_titulo = serializers.CharField(source='momento.titulo', read_only=True)
    participante_nombre = serializers.SerializerMethodField()
    respuestas_sugeridas = serializers.SerializerMethodField()
    participante_sugerido_nombre = serializers.SerializerMethodField()
    requiere_decision = serializers.SerializerMethodField()
    versiones_existentes = serializers.SerializerMethodField()

    class Meta:
        model = ExtraccionMomento
        fields = [
            'id', 'momento', 'momento_titulo', 'participante', 'participante_nombre',
            'participante_sugerido', 'participante_sugerido_nombre', 'requiere_decision',
            'versiones_existentes', 'version_escrita',
            'nombre_archivo_original', 'estado', 'resultado', 'respuestas_sugeridas',
            'preguntas_omitidas', 'responsable_detectado', 'responsable_estado',
            'error_mensaje', 'modelo_usado', 'aprobado_en', 'aprobado_por', 'solicitado_por',
            'creado_en', 'actualizado_en', 'completado_en',
        ]
        read_only_fields = fields

    def get_participante_nombre(self, extraccion):
        # Puede no haber participante todavía: desde HU-55 se puede subir sin decir de quién es
        # el documento y que la IA lo detecte — si no se logró emparejar, queda en null hasta que
        # un admin lo asigne.
        if extraccion.participante_id is None:
            return None
        return f'{extraccion.participante.nombre} {extraccion.participante.apellido}'.strip()

    def get_participante_sugerido_nombre(self, extraccion):
        sugerido = extraccion.participante_sugerido
        if sugerido is None:
            return None
        return f'{sugerido.nombre} {sugerido.apellido}'.strip()

    def get_requiere_decision(self, extraccion):
        """HU-91: el documento es de alguien que ya respondió este momento y no se escribió nada.
        El frontend ofrece las tres salidas: sobrescribir, versión nueva u otra persona (todas por
        `asignar-responsable`)."""
        return (
            extraccion.estado == ExtraccionMomento.ESTADO_COMPLETO
            and extraccion.participante_id is None
            and extraccion.participante_sugerido_id is not None
        )

    def get_versiones_existentes(self, extraccion):
        """Las versiones que ya tiene en el momento la persona sugerida (o, ya escrita, la
        asignada). Sirve para el diálogo: con más de una, sobrescribir pide elegir cuál."""
        from .extraccion_momento_ia_openai import versiones_existentes

        persona = extraccion.participante or extraccion.participante_sugerido
        return versiones_existentes(persona, extraccion.momento_id)

    def get_respuestas_sugeridas(self, extraccion):
        """`resultado['respuestas']` tal cual queda guardado (ver `_limpiar_y_validar` en
        extraccion_momento_ia_openai.py) ya usa casi el mismo formato que
        `RespuestaEnvioSerializer` — el único cambio es la clave `pregunta` → `pregunta_id`. Se
        expone así (en vez de `resultado` crudo) para que el FE pueda tomar este arreglo,
        dejar que el participante lo corrija, y mandarlo TAL CUAL como body de
        `POST .../momentos/{id}/respuestas/` — sin necesidad de que un admin apruebe nada antes
        (a diferencia de la carga que hace un admin a nombre de otra persona, que sí requiere
        `aprobar/` porque ahí nadie más puede corregir lo que la IA transcribió)."""
        respuestas = (extraccion.resultado or {}).get('respuestas') or []
        return [
            {
                'pregunta_id': item.get('pregunta'),
                'texto_libre': item.get('texto_libre', ''),
                'opcion_ids': item.get('opcion_ids') or [],
                'fila_id': item.get('fila_id'),
                'columna_id': item.get('columna_id'),
                'fila_temporal': item.get('fila_temporal'),
            }
            for item in respuestas
        ]


class CargarArchivoMomentoSerializer(serializers.Serializer):
    """Subida de un documento diligenciado por el PROPIO participante (HU-56). A diferencia del
    serializer de admin (ExtraccionMomentoCrearSerializer), acá no se puede indicar a quién
    pertenece el documento: el dueño es siempre quien sube, se fuerza en la vista. Tampoco se dan
    de alta participantes — quien sube ya está registrado, por el permiso de la vista."""
    archivo = serializers.FileField()

    def validate_archivo(self, archivo):
        extension = archivo.name.rsplit('.', 1)[-1].lower() if '.' in archivo.name else ''
        if extension not in ('pdf', 'docx'):
            raise serializers.ValidationError('Solo se aceptan archivos .pdf o .docx.')
        return archivo


class AsignarResponsableMomentoSerializer(serializers.Serializer):
    """Asigna a mano el participante de una extracción que la IA no pudo emparejar (HU-55).

    Dos formas, y hay que mandar EXACTAMENTE una (HU-88):

    - `participante_id`: elegir a alguien que ya está en la jornada;
    - `nombre` (y opcionalmente `correo_institucional`): darlo de alta en el acto.

    El segundo modo existe porque el diálogo de asignación obligaba a elegir de una lista, y la
    persona que firmó un formato en papel muchas veces no está en ninguna lista — había que salir
    a registrarla por otra pantalla y volver. El serializer de SUBIDA ya permitía crear en el mismo
    request, así que el de asignación era la única pieza que no.
    """
    participante_id = serializers.PrimaryKeyRelatedField(
        source='participante', queryset=Participante.objects.all(), required=False,
    )
    nombre = serializers.CharField(required=False)
    correo_institucional = serializers.EmailField(required=False)
    # HU-91 — solo hacen falta si la persona elegida YA tiene respuestas en el momento (si no, se
    # escribe en la versión 1 y se ignoran). Sin `modo` en ese caso la respuesta es un 409.
    modo = serializers.ChoiceField(choices=['sobrescribir', 'nueva_version'], required=False)
    version = serializers.IntegerField(required=False, min_value=1)
    # Con `nombre`: crear SIEMPRE una persona nueva, sin intentar emparejar con alguien existente.
    # Es la tercera salida del conflicto — "no es la misma persona" — que el emparejamiento por
    # nombre de HU-88 no permitiría, porque volvería a dar con la misma.
    nuevo = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        trae_id = 'participante' in attrs
        trae_nombre = bool((attrs.get('nombre') or '').strip())
        if trae_id == trae_nombre:
            raise serializers.ValidationError(
                'Manda `participante_id` para elegir a alguien que ya existe, o `nombre` para '
                'darlo de alta — uno de los dos, no los dos ni ninguno.'
            )
        if attrs.get('nuevo') and not trae_nombre:
            raise serializers.ValidationError({'nuevo': '`nuevo` va con `nombre`: es para dar de alta.'})
        if 'version' in attrs and attrs.get('modo') != 'sobrescribir':
            raise serializers.ValidationError(
                {'version': '`version` solo aplica con `modo` = "sobrescribir".'}
            )
        return attrs


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
        # Desde HU-55 también vale no mandar NINGUNO de los dos: la IA lee el responsable del
        # propio documento y se intenta emparejar contra los participantes de la jornada al
        # procesar. Solo se exige el paquete completo si mandaron parte de él — mandar media
        # ficha de alta sí es un error del cliente, no una decisión de delegarle esto a la IA.
        campos_alta = ('correo_institucional', 'nombre', 'apellido', 'rol')
        presentes = [c for c in campos_alta if c in attrs]
        if presentes and len(presentes) < len(campos_alta):
            raise serializers.ValidationError(
                'Para registrar a alguien nuevo hacen falta correo_institucional+nombre+apellido+rol. '
                'También puedes mandar participante_id, o no mandar nada y dejar que la IA '
                'detecte el responsable en el documento.'
            )
        return attrs

    def create(self, validated_data):
        participante = validated_data.pop('participante', None)
        if participante is None and 'correo_institucional' not in validated_data:
            # Sin responsable indicado: queda en null y lo resuelve la IA al procesar (ver
            # emparejar_responsable_momento). La extracción no se puede aprobar hasta que haya uno.
            for campo in ('nombre', 'apellido', 'telefono', 'rol'):
                validated_data.pop(campo, None)
            validated_data['nombre_archivo_original'] = validated_data['archivo'].name
            return super().create(validated_data)
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


# Tope de archivos por carga masiva. No es un límite técnico sino de costo y de tiempo: cada
# documento son hoy entre 5 y 9 llamadas a OpenAI (ver lectura_documentos.agrupar_en_lotes), así
# que 30 archivos pueden ser más de 200 llamadas en una sola tanda.
MAX_ARCHIVOS_POR_CARGA = 30


class ExtraccionMomentoMasivaSerializer(serializers.Serializer):
    """Carga masiva: un momento y varios documentos ya diligenciados en un solo request (HU-84).

    NO acepta `participante_id` a propósito. La carga masiva existe para la pila de formatos de
    departamentos distintos, así que a cada archivo le corresponde una persona distinta y
    forzosamente hay que leerla del propio documento (el emparejamiento de responsable de HU-55).
    Un `participante_id` aquí solo podría significar "todos estos documentos son de la misma
    persona", que no es el caso de uso."""
    momento = serializers.PrimaryKeyRelatedField(queryset=Momento.objects.all())
    archivos = serializers.ListField(
        child=serializers.FileField(), min_length=1, max_length=MAX_ARCHIVOS_POR_CARGA,
    )


class RespuestaAdminEdicionSerializer(serializers.ModelSerializer):
    """Corrección de una Respuesta ya guardada (HU-84).

    Solo `texto_libre` y las opciones. Mover una celda de pregunta, fila o columna no es corregir
    una transcripción —es escribir otra respuesta en otro lugar— y dejarlo abierto convertiría
    este endpoint en una forma de pisar la respuesta de otra persona por descuido: para eso se
    borra la celda y se crea por la vía normal.

    Valida con el MISMO `_validar_entrada` que usa el envío normal, así que una matriz no puede
    quedar con opciones ni una pregunta de opción única con dos marcadas."""
    opcion_ids = serializers.PrimaryKeyRelatedField(
        source='opciones', many=True, required=False, queryset=OpcionPregunta.objects.all(),
    )

    class Meta:
        model = Respuesta
        fields = ['id', 'texto_libre', 'opcion_ids']

    def validate(self, attrs):
        from .views import _validar_entrada

        respuesta = self.instance
        texto = attrs.get('texto_libre', respuesta.texto_libre)
        opciones = attrs.get('opciones', list(respuesta.opciones.all()))
        _validar_entrada(
            respuesta.pregunta, texto, opciones,
            fila=respuesta.fila, columna=respuesta.columna,
            # Una celda de fila dinámica no tiene `fila` pero sí `fila_lista`; el validador espera
            # un `fila_temporal` para reconocer ese caso (el número en sí no se usa acá).
            fila_temporal=1 if respuesta.fila_lista_id else None,
        )
        return attrs
