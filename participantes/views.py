import threading

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from jornadas import emparejamiento
from jornadas.models import Jornada, Momento, Pregunta, RolJornada
from jornadas.serializers import JornadaPublicaSerializer, RolJornadaSerializer

from .extraccion_momento_ia_openai import procesar_extraccion_momento
from .models import ExtraccionMomento, FilaListaRespuesta, Participante, Respuesta
from .permissions import EsParticipanteDeLaJornada
from .serializers import (
    CargarArchivoMomentoSerializer,
    ExtraccionMomentoSerializer,
    MomentoDetalleSerializer,
    MomentoIndiceSerializer,
    ParticipanteLoginSerializer,
    ParticipanteRegistroSerializer,
    ParticipanteSerializer,
    RespuestaEnvioSerializer,
    RespuestaSalidaSerializer,
)
from .utils import condicion_cumplida


class JornadaListaView(generics.ListAPIView):
    queryset = Jornada.objects.all()
    serializer_class = JornadaPublicaSerializer
    permission_classes = [AllowAny]


class JornadaDetalleView(generics.RetrieveAPIView):
    queryset = Jornada.objects.filter(activa=True)
    serializer_class = JornadaPublicaSerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'
    lookup_url_kwarg = 'jornada_slug'


class RolesJornadaView(generics.ListAPIView):
    """Catálogo de roles que un admin definió para esta jornada (RolJornada) — público y sin
    autenticación, igual que JornadaDetalleView, para que el front pueda mostrarlos como opciones
    en el formulario de registro (HU-17). Una jornada sin roles definidos devuelve una lista
    vacía; el registro (Participante.rol) sigue aceptando texto libre de todas formas."""
    serializer_class = RolJornadaSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return RolJornada.objects.filter(jornada__slug=self.kwargs['jornada_slug'])


class RegistroParticipanteView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=ParticipanteRegistroSerializer, responses=ParticipanteSerializer)
    def post(self, request, jornada_slug):
        jornada = get_object_or_404(Jornada, slug=jornada_slug, activa=True)

        entrada = ParticipanteRegistroSerializer(data=request.data, context={'jornada': jornada})
        entrada.is_valid(raise_exception=True)
        participante = entrada.save()

        return Response(ParticipanteSerializer(participante).data, status=status.HTTP_201_CREATED)


class LoginParticipanteView(APIView):
    """El participante no tiene contraseña — si perdió su token (cerró el navegador, cambió de
    dispositivo), este endpoint se lo devuelve con solo su correo institucional, que es único por
    jornada. No es una autenticación fuerte (cualquiera que sepa el correo puede recuperar el
    token), pero es el nivel de seguridad correcto para una jornada participativa sin datos
    sensibles ni contraseñas que gestionar."""
    permission_classes = [AllowAny]

    @extend_schema(request=ParticipanteLoginSerializer, responses=ParticipanteSerializer)
    def post(self, request, jornada_slug):
        jornada = get_object_or_404(Jornada, slug=jornada_slug, activa=True)

        entrada = ParticipanteLoginSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        correo = entrada.validated_data['correo_institucional']

        participante = Participante.objects.filter(
            jornada=jornada, correo_institucional=correo
        ).first()
        if participante is None:
            return Response(
                {'detail': 'No hay ningún participante registrado con ese correo en esta jornada.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(ParticipanteSerializer(participante).data, status=status.HTTP_200_OK)


class MeParticipanteView(APIView):
    """El front guarda el token del participante (localStorage) tras el registro (HU-17) o el
    login por correo (HU-18b) — este endpoint le deja recuperar los datos completos de ese
    participante mandando solo el token ya guardado, sin volver a pedir el correo. Devuelve
    exactamente el mismo cuerpo que login/registro, para que el front pueda reusar el mismo
    parseo en los tres casos."""
    permission_classes = [EsParticipanteDeLaJornada]

    @extend_schema(responses=ParticipanteSerializer)
    def get(self, request, jornada_slug):
        return Response(ParticipanteSerializer(request.user).data, status=status.HTTP_200_OK)


def _momento_visible_para(momento, participante):
    # roles_permitidos vacía = visible para todos los roles — aplica siempre (a diferencia de
    # mesa, todo participante tiene un rol, sea el momento individual o de mesa).
    if momento.roles_permitidos and participante.rol not in momento.roles_permitidos:
        return False
    # mesas_permitidas vacía = visible para todas las mesas, igual que en Pregunta. Solo aplica
    # en momentos tipo mesa — un momento individual no tiene noción de "mesa" del participante.
    return (
        momento.tipo != Momento.TIPO_MESA
        or not momento.mesas_permitidas
        or participante.mesa in momento.mesas_permitidas
    )


class MomentosIndiceView(generics.ListAPIView):
    serializer_class = MomentoIndiceSerializer
    permission_classes = [EsParticipanteDeLaJornada]

    def get_queryset(self):
        momentos = Momento.objects.filter(jornada__slug=self.kwargs['jornada_slug'], activo=True)
        participante = self.request.user
        return [m for m in momentos if _momento_visible_para(m, participante)]


class MomentoDetalleView(generics.RetrieveAPIView):
    serializer_class = MomentoDetalleSerializer
    permission_classes = [EsParticipanteDeLaJornada]
    lookup_url_kwarg = 'momento_id'

    def get_queryset(self):
        return Momento.objects.filter(jornada__slug=self.kwargs['jornada_slug'], activo=True)

    def get_object(self):
        momento = super().get_object()
        if not _momento_visible_para(momento, self.request.user):
            raise NotFound('Este momento no está disponible para tu mesa.')
        return momento


class MomentoCargarArchivoView(APIView):
    """El propio participante sube su documento ya diligenciado para este momento y la IA lo
    transcribe (HU-56). Mismo mecanismo que participantes.admin_views.ExtraccionMomentoViewSet,
    pero acá el dueño es siempre quien sube (`participante=request.user`), no un dato del
    request: no hay responsable que emparejar ni participantes que dar de alta.

    Se habilita momento por momento con `Momento.permite_carga_archivo` — apagado, un
    participante igual recibe 403, porque cada carga cuesta una llamada a OpenAI. El resultado NO
    se aprueba solo: como cualquier extracción de este módulo, queda en `resultado` hasta que un
    admin la revise y llame `aprobar/`."""
    permission_classes = [EsParticipanteDeLaJornada]

    @extend_schema(
        request=CargarArchivoMomentoSerializer,
        responses=ExtraccionMomentoSerializer,
    )
    def post(self, request, jornada_slug, momento_id):
        momento = get_object_or_404(
            Momento, pk=momento_id, jornada__slug=jornada_slug, activo=True
        )
        if not _momento_visible_para(momento, request.user):
            raise NotFound('Este momento no está disponible para tu mesa.')
        if not momento.permite_carga_archivo:
            raise PermissionDenied(
                'Este momento no tiene habilitada la carga de documentos. Diligéncialo en línea '
                'o pídele a un administrador que la habilite.'
            )

        entrada = CargarArchivoMomentoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        archivo = entrada.validated_data['archivo']

        extraccion = ExtraccionMomento.objects.create(
            momento=momento,
            participante=request.user,
            archivo=archivo,
            nombre_archivo_original=archivo.name,
            responsable_estado=emparejamiento.ESTADO_NO_BUSCADO,
        )
        threading.Thread(
            target=procesar_extraccion_momento, args=(extraccion.id,), daemon=True,
        ).start()

        return Response(
            ExtraccionMomentoSerializer(extraccion).data, status=status.HTTP_201_CREATED,
        )


class MisExtraccionesMomentoView(generics.ListAPIView):
    """Las cargas que hizo el propio participante en este momento — para que el FE pueda mostrar
    "tu documento se está procesando / ya quedó / falló" después de subirlo, sin tener que
    pegarle al endpoint de admin (al que no tiene acceso)."""
    serializer_class = ExtraccionMomentoSerializer
    permission_classes = [EsParticipanteDeLaJornada]

    def get_queryset(self):
        return ExtraccionMomento.objects.filter(
            momento_id=self.kwargs['momento_id'],
            momento__jornada__slug=self.kwargs['jornada_slug'],
            participante=self.request.user,
        )


def _validar_entrada(pregunta, texto_libre, opciones, fila=None, columna=None, fila_temporal=None):
    if opciones and any(opcion.pregunta_id != pregunta.id for opcion in opciones):
        raise ValidationError(f'Una opción enviada no pertenece a la pregunta {pregunta.id}.')

    if pregunta.tipo == Pregunta.TIPO_MATRIZ:
        if fila_temporal is not None:
            # Celda de una fila EXTRA, agregada por quien responde. Solo existe si el admin
            # encendió filas_adicionales; si no, la matriz es de filas fijas y esto es un error
            # del cliente, igual que siempre (ver Pregunta.filas_adicionales).
            if not pregunta.filas_adicionales:
                raise ValidationError(
                    f'La pregunta {pregunta.id} es una matriz de filas fijas: no admite '
                    f'fila_temporal (usa fila_id, o pide que se habiliten filas adicionales).'
                )
            if fila is not None:
                raise ValidationError(
                    f'La celda de la pregunta {pregunta.id} no puede traer fila_id y '
                    f'fila_temporal a la vez: o es una fila fija o es una agregada.'
                )
            if columna is None:
                raise ValidationError(
                    f'La pregunta {pregunta.id}: cada celda de una fila agregada debe indicar columna.'
                )
            if columna.pregunta_id != pregunta.id:
                raise ValidationError(f'La columna enviada no pertenece a la pregunta {pregunta.id}.')
            if opciones:
                raise ValidationError(f'La pregunta {pregunta.id} no acepta opciones.')
            return
        if fila is None or columna is None:
            raise ValidationError(
                f'La pregunta {pregunta.id} es de tipo matriz: cada respuesta debe indicar fila y columna.'
            )
        if fila.pregunta_id != pregunta.id or columna.pregunta_id != pregunta.id:
            raise ValidationError(f'La fila/columna enviada no pertenece a la pregunta {pregunta.id}.')
        if opciones:
            raise ValidationError(f'La pregunta {pregunta.id} no acepta opciones.')
        return

    if pregunta.tipo == Pregunta.TIPO_LISTA:
        if fila is not None:
            raise ValidationError(f'La pregunta {pregunta.id} es de tipo lista, no usa fila_id (usa fila_temporal).')
        if columna is None or fila_temporal is None:
            raise ValidationError(
                f'La pregunta {pregunta.id} es de tipo lista: cada celda debe indicar columna y fila_temporal.'
            )
        if columna.pregunta_id != pregunta.id:
            raise ValidationError(f'La columna enviada no pertenece a la pregunta {pregunta.id}.')
        if opciones:
            raise ValidationError(f'La pregunta {pregunta.id} no acepta opciones.')
        return

    if fila is not None or columna is not None or fila_temporal is not None:
        raise ValidationError(f'La pregunta {pregunta.id} no es de tipo matriz/lista, no acepta fila/columna.')

    # `abierta` y `audio` se validan y se guardan idéntico: la respuesta es texto_libre y nada
    # más. En `audio` ese texto es la transcripción que el propio cliente generó a partir de la
    # grabación — acá nunca llega el archivo de audio, así que no hay nada extra que validar
    # (ver Pregunta.TIPOS_TEXTO_LIBRE).
    if pregunta.tipo in Pregunta.TIPOS_TEXTO_LIBRE:
        if opciones:
            raise ValidationError(f'La pregunta {pregunta.id} es de texto libre, no acepta opciones.')
        if pregunta.obligatoria and not texto_libre.strip():
            raise ValidationError(f'La pregunta {pregunta.id} es obligatoria.')
    else:
        if texto_libre.strip():
            raise ValidationError(f'La pregunta {pregunta.id} no acepta texto libre.')
        if pregunta.tipo == Pregunta.TIPO_UNICA and len(opciones) > 1:
            raise ValidationError(f'La pregunta {pregunta.id} solo acepta una opción.')
        if pregunta.obligatoria and not opciones:
            raise ValidationError(f'La pregunta {pregunta.id} es obligatoria.')


def _preguntas_obligatorias_faltantes(preguntas_obligatorias, entradas_por_pregunta):
    faltantes = []
    for pregunta in preguntas_obligatorias:
        items = entradas_por_pregunta.get(pregunta.id, [])
        if pregunta.tipo == Pregunta.TIPO_MATRIZ:
            requeridas = {
                (f, c) for f in pregunta.filas.values_list('id', flat=True)
                for c in pregunta.columnas.values_list('id', flat=True)
            }
            respondidas = {
                (i['fila'].id, i['columna'].id) for i in items
                if i.get('fila') is not None and i.get('columna') is not None
                and i.get('texto_libre', '').strip()
            }
            if not requeridas.issubset(respondidas):
                faltantes.append(pregunta.id)
        elif pregunta.tipo == Pregunta.TIPO_LISTA:
            # Obligatoria en una lista = al menos UNA fila con TODAS sus columnas respondidas —
            # no exige que todas las filas estén completas, solo que exista al menos un registro
            # real (ej. al menos un profesor con sus datos completos), igual de estricto que
            # matriz pero sin conocer de antemano cuántas filas habrá.
            columnas_ids = set(pregunta.columnas.values_list('id', flat=True))
            columnas_por_fila = {}
            for i in items:
                if i.get('fila_temporal') is None or i.get('columna') is None:
                    continue
                if not i.get('texto_libre', '').strip():
                    continue
                columnas_por_fila.setdefault(i['fila_temporal'], set()).add(i['columna'].id)
            if not any(cols >= columnas_ids for cols in columnas_por_fila.values()):
                faltantes.append(pregunta.id)
        elif not items:
            faltantes.append(pregunta.id)
    return faltantes


def _guardar_filas_dinamicas(pregunta, items, participante, dueño):
    """Guarda las celdas que van en filas creadas por quien responde (`fila_temporal`): todas las
    de una pregunta tipo lista, o las filas EXTRA de una matriz con `filas_adicionales`.

    A diferencia de matriz/abierta/única (que hacen update_or_create celda por celda), acá cada
    envío REEMPLAZA por completo las filas dinámicas existentes de esta pregunta para este dueño
    — más simple y predecible que tratar de emparejar filas de un envío con filas de otro, dado
    que `fila_temporal` es un número que el cliente inventa en cada envío (fila_temporal=1 hoy no
    es necesariamente la misma fila que fila_temporal=1 en un envío anterior). Por eso se llama
    también con `items` vacío: es lo que permite borrar todas las filas extra reenviando el
    momento sin ninguna. Las filas FIJAS de una matriz no se tocan acá, van por el otro camino."""
    FilaListaRespuesta.objects.filter(pregunta=pregunta, **dueño).delete()

    ordenes_temporales = sorted({item['fila_temporal'] for item in items})
    filas_por_temporal = {
        ft: FilaListaRespuesta.objects.create(pregunta=pregunta, orden=i, **dueño)
        for i, ft in enumerate(ordenes_temporales, start=1)
    }

    guardadas = []
    for item in items:
        texto_libre = item.get('texto_libre', '')
        opciones = item.get('opciones', [])
        columna = item.get('columna')
        fila_temporal = item.get('fila_temporal')
        # `fila` se pasa aunque una lista nunca la use, por el mismo motivo que en el camino
        # normal de guardado: sin esto la validación "una lista no usa fila_id (usa
        # fila_temporal)" nunca se ejecuta y un fila_id mandado a una pregunta lista se acepta
        # en silencio.
        _validar_entrada(
            pregunta, texto_libre, opciones, fila=item.get('fila'), columna=columna,
            fila_temporal=fila_temporal,
        )

        respuesta = Respuesta.objects.create(
            pregunta=pregunta,
            fila_lista=filas_por_temporal[fila_temporal],
            columna=columna,
            texto_libre=texto_libre,
            registrado_por=participante,
            **dueño,
        )
        guardadas.append(respuesta)
    return guardadas


class RespuestasMomentoView(APIView):
    permission_classes = [EsParticipanteDeLaJornada]

    @extend_schema(responses=RespuestaSalidaSerializer(many=True))
    def get(self, request, jornada_slug, momento_id):
        """Las respuestas YA GUARDADAS del participante (o de su mesa, en momentos tipo mesa)
        para este momento — para que el front pueda pre-llenar el formulario cuando alguien
        vuelve a un momento a medio responder o a corregir algo, en vez de partir en blanco.
        Antes de esto no existía ningún GET de respuestas: MomentoDetalleView solo devuelve la
        estructura (preguntas/opciones/filas/columnas), nunca lo que ya se respondió."""
        momento = get_object_or_404(
            Momento, pk=momento_id, jornada__slug=jornada_slug, activo=True
        )
        participante = request.user
        if not _momento_visible_para(momento, participante):
            raise NotFound('Este momento no está disponible para tu mesa.')

        if momento.tipo == Momento.TIPO_MESA:
            # Mismo criterio de dueño que en el POST: en un momento de mesa, las respuestas son
            # de la mesa, no de la persona — así que cualquier integrante de la mesa (no solo el
            # vocero, que es el único que puede escribir) puede ver lo que ya se respondió.
            if participante.mesa is None:
                return Response([], status=status.HTTP_200_OK)
            respuestas = Respuesta.objects.filter(pregunta__momento=momento, mesa=participante.mesa)
        else:
            respuestas = Respuesta.objects.filter(pregunta__momento=momento, participante=participante)

        respuestas = respuestas.select_related('pregunta').prefetch_related('opciones')
        return Response(RespuestaSalidaSerializer(respuestas, many=True).data, status=status.HTTP_200_OK)

    # Atómico porque el guardado de un momento no es celda a celda independiente: las filas
    # dinámicas (lista, y las filas extra de una matriz) se borran y se recrean, así que si una
    # celda posterior no valida, sin transacción el envío quedaría a medias — con las filas
    # viejas ya borradas y las nuevas a medio escribir. Con esto, o entra el momento completo o
    # no entra nada, que es como el cliente ya lo manda.
    @transaction.atomic
    @extend_schema(request=RespuestaEnvioSerializer, responses=RespuestaSalidaSerializer(many=True))
    def post(self, request, jornada_slug, momento_id):
        momento = get_object_or_404(
            Momento, pk=momento_id, jornada__slug=jornada_slug, activo=True
        )
        participante = request.user
        if not _momento_visible_para(momento, participante):
            raise NotFound('Este momento no está disponible para tu mesa.')

        entrada = RespuestaEnvioSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data

        mesa = None
        if momento.tipo == Momento.TIPO_MESA:
            if not participante.es_vocero:
                raise PermissionDenied(
                    'Solo el vocero de la mesa puede enviar respuestas en este momento.'
                )
            mesa = participante.mesa
            if mesa is None:
                raise ValidationError(
                    {'mesa': 'No tienes una mesa asignada — pídele a un administrador que te la '
                              'asigne antes de responder.'}
                )

        # Un momento se responde completo en un solo POST — si la pregunta disparadora y la
        # condicionada van en el mismo envío, la disparadora todavía no está guardada cuando se
        # valida la condicionada (ver condicion_cumplida), así que estas opciones del propio
        # envío también cuentan como "ya marcadas".
        opciones_en_este_envio = {
            opcion.id for item in datos['respuestas'] for opcion in item.get('opciones', [])
        }

        def _pregunta_visible_para(pregunta):
            # mesas_permitidas/roles_permitidas vacías = aplica a todas las mesas/todos los
            # roles, igual que siempre. Esto se revalida acá (no solo se oculta en el listado,
            # ver MomentoDetalleSerializer) para que un vocero no pueda colar una respuesta a una
            # pregunta que no le corresponde pegándole directo a la API — incluida una
            # condicionada (depende_de_opcion) que todavía no debería estar habilitada.
            if pregunta.roles_permitidos and participante.rol not in pregunta.roles_permitidos:
                return False
            if not condicion_cumplida(pregunta, participante, opciones_en_este_envio):
                return False
            return momento.tipo != Momento.TIPO_MESA or not pregunta.mesas_permitidas or mesa in pregunta.mesas_permitidas

        # dict de listas (no un único item por pregunta): una pregunta tipo matriz manda una
        # entrada POR CELDA (fila×columna), todas con el mismo pregunta_id.
        entradas_por_pregunta = {}
        for item in datos['respuestas']:
            pregunta = item['pregunta']
            if pregunta.momento_id != momento.id:
                raise ValidationError(f'La pregunta {pregunta.id} no pertenece a este momento.')
            if not _pregunta_visible_para(pregunta):
                raise ValidationError(f'La pregunta {pregunta.id} no está habilitada para ti.')
            entradas_por_pregunta.setdefault(pregunta.id, []).append(item)

        preguntas_obligatorias = [
            p for p in momento.preguntas.filter(activa=True, obligatoria=True) if _pregunta_visible_para(p)
        ]
        faltantes = _preguntas_obligatorias_faltantes(preguntas_obligatorias, entradas_por_pregunta)
        if faltantes:
            raise ValidationError({'faltantes': f'Preguntas obligatorias sin responder: {faltantes}'})

        dueño = {'mesa': mesa} if momento.tipo == Momento.TIPO_MESA else {'participante': participante}

        respuestas_guardadas = []
        for items in entradas_por_pregunta.values():
            pregunta = items[0]['pregunta']
            if pregunta.acepta_filas_dinamicas:
                # Una lista trae solo celdas dinámicas; una matriz con filas_adicionales trae las
                # dos clases mezcladas en el mismo envío (las fijas por fila_id, las extra por
                # fila_temporal) y cada grupo se guarda por su camino. El grupo dinámico se
                # procesa aunque venga vacío: así, reenviar el momento sin filas extra las borra.
                dinamicos = [i for i in items if i.get('fila_temporal') is not None]
                items = [i for i in items if i.get('fila_temporal') is None]
                respuestas_guardadas.extend(
                    _guardar_filas_dinamicas(pregunta, dinamicos, participante, dueño)
                )
            for item in items:
                texto_libre = item.get('texto_libre', '')
                opciones = item.get('opciones', [])
                fila = item.get('fila')
                columna = item.get('columna')
                # fila_temporal también se pasa acá, aunque solo las preguntas tipo lista lo
                # usen: es lo que hace que las validaciones de "esta pregunta NO usa
                # fila_temporal" (matriz y el resto de tipos) se apliquen de verdad — antes se
                # omitía en esta llamada y un fila_temporal mandado a una pregunta que no es
                # lista se aceptaba en silencio.
                _validar_entrada(pregunta, texto_libre, opciones, fila, columna, item.get('fila_temporal'))

                lookup = {'pregunta': pregunta, 'fila': fila, 'columna': columna, **dueño}
                respuesta, _ = Respuesta.objects.update_or_create(
                    **lookup,
                    defaults={
                        'texto_libre': texto_libre,
                        'registrado_por': participante,
                    },
                )
                respuesta.opciones.set(opciones)
                respuestas_guardadas.append(respuesta)

        return Response(
            RespuestaSalidaSerializer(respuestas_guardadas, many=True).data,
            status=status.HTTP_200_OK,
        )
