import threading

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from jornadas.scoping import filtrar_por_propietario, verificar_acceso_jornada

from .extraccion_momento_ia_openai import (
    escribir_extraccion_momento, procesar_extracciones_en_serie, procesar_extraccion_momento,
)
from .models import ExtraccionMomento, FilaListaRespuesta, Participante, Respuesta
from .serializers import (
    MAX_ARCHIVOS_POR_CARGA, AsignarResponsableMomentoSerializer,
    ExtraccionMomentoCrearSerializer, ExtraccionMomentoMasivaSerializer,
    ExtraccionMomentoSerializer, ParticipanteMesaVoceroSerializer, ParticipanteSerializer,
    RespuestaAdminEdicionSerializer, RespuestaSalidaSerializer,
)


class ParticipanteAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """DELETE elimina el registro por completo — útil para dar de baja duplicados o registros
    de prueba (ej. correo mal escrito). Las respuestas individuales del participante se borran
    en cascada (`Respuesta.participante` es CASCADE); las respuestas de mesa NO, porque están
    ligadas al número de mesa, no a la persona — la mesa conserva lo ya respondido aunque se
    elimine a quien era su vocero (ver HU-22: alguien más deberá quedar como vocero para poder
    seguir enviando)."""
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = Participante.objects.select_related('jornada').all()
        queryset = filtrar_por_propietario(queryset, self.request.user, 'jornada__propietarios')
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        return queryset

    def get_serializer_class(self):
        # PATCH/PUT solo puede tocar mesa/es_vocero (ver HU-10b) — nunca datos personales del
        # registro, que se hacen por otra vía si hace falta corregirlos.
        if self.action in ('update', 'partial_update'):
            return ParticipanteMesaVoceroSerializer
        return ParticipanteSerializer


class RespuestaAdminViewSet(
    mixins.UpdateModelMixin, mixins.DestroyModelMixin, ReadOnlyModelViewSet,
):
    """Las respuestas guardadas de una jornada, y desde HU-84 también su CORRECCIÓN.

    Era de solo lectura, y eso era justamente lo que obligaba a que una extracción por IA esperara
    la aprobación de un admin antes de escribirse: si no se podía corregir una Respuesta, la única
    ventana de revisión posible era antes de guardarla. Ahora que el criterio es "quien sube el
    documento es quien revisa", la corrección tiene que existir o los errores de la IA quedarían
    fijos para siempre.

    No hay `create` a propósito: una respuesta nace del envío del participante o de una extracción,
    nunca de un admin escribiendo a mano en el panel. Y `partial_update` solo toca el contenido
    (ver RespuestaAdminEdicionSerializer)."""
    serializer_class = RespuestaSalidaSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_serializer_class(self):
        if self.action in ('update', 'partial_update'):
            return RespuestaAdminEdicionSerializer
        return RespuestaSalidaSerializer

    def perform_destroy(self, instance):
        """Borra la celda y, si era la última de una fila dinámica, también la fila.

        Sin esto quedaría una `FilaListaRespuesta` sin ninguna celda: una fila fantasma que el
        frontend pinta vacía y que nadie puede quitar."""
        fila_lista = instance.fila_lista
        instance.delete()
        # `fila_lista` no define related_name, así que el accesor inverso es el de Django.
        if fila_lista is not None and not fila_lista.respuesta_set.exists():
            fila_lista.delete()

    def get_queryset(self):
        queryset = Respuesta.objects.select_related('pregunta', 'participante').prefetch_related('opciones').all()
        queryset = filtrar_por_propietario(queryset, self.request.user, 'pregunta__momento__jornada__propietarios')
        momento_id = self.request.query_params.get('momento')
        pregunta_id = self.request.query_params.get('pregunta')
        if momento_id:
            queryset = queryset.filter(pregunta__momento_id=momento_id)
        if pregunta_id:
            queryset = queryset.filter(pregunta_id=pregunta_id)
        return queryset


class ExtraccionMomentoViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Sube uno o varios .pdf/.docx ya diligenciados fuera de la web y dispara su transcripción
    con IA (ver participantes/extraccion_momento_ia_openai.py) — mismo mecanismo asíncrono que
    instrumentos.ExtraccionInstrumentoViewSet.

    Desde HU-84 la transcripción **se escribe sola** en cuanto termina: ya no espera el action
    `aprobar`. La espera existía porque no se podía corregir una Respuesta ya guardada; ahora
    `RespuestaAdminViewSet` admite PATCH y DELETE, así que quien sube el documento puede revisar y
    arreglar lo que la IA leyó mal, que es de quien es la responsabilidad.

    `masiva/` sube una pila de documentos en un request — el caso real: treinta formatos de
    treinta departamentos, cada uno a nombre de quien lo firma (lo lee la IA, ver HU-55)."""
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = ExtraccionMomento.objects.select_related('momento', 'participante')
        queryset = filtrar_por_propietario(queryset, self.request.user, 'momento__jornada__propietarios')
        momento_id = self.request.query_params.get('momento')
        if momento_id:
            queryset = queryset.filter(momento_id=momento_id)
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return ExtraccionMomentoCrearSerializer
        return ExtraccionMomentoSerializer

    def create(self, request, *args, **kwargs):
        entrada = ExtraccionMomentoCrearSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        momento = entrada.validated_data['momento']
        verificar_acceso_jornada(request.user, momento.jornada)

        extraccion = entrada.save(solicitado_por=request.user)
        threading.Thread(target=procesar_extraccion_momento, args=(extraccion.id,), daemon=True).start()

        salida = ExtraccionMomentoSerializer(extraccion)
        headers = self.get_success_headers(salida.data)
        return Response(salida.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=False, methods=['post'], url_path='masiva')
    def masiva(self, request):
        """Carga masiva (HU-84): un momento y hasta MAX_ARCHIVOS_POR_CARGA documentos.

        Los archivos válidos se crean y se procesan; los inválidos se devuelven en `rechazadas`
        con el motivo, en vez de tumbar el request completo. Rechazar la tanda entera por un
        .xlsx suelto obligaría a volver a subir los otros veintinueve, y descartarlo en silencio
        sería peor: así queda explícito qué entró y qué no.

        El procesamiento es EN SERIE, no un hilo por archivo: cada documento son hoy entre 5 y 9
        llamadas a OpenAI, así que treinta en paralelo serían más de doscientas llamadas
        simultáneas — límite de tasa garantizado, y sin reintento por 429 en el pipeline."""
        entrada = ExtraccionMomentoMasivaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        momento = entrada.validated_data['momento']
        verificar_acceso_jornada(request.user, momento.jornada)

        creadas, rechazadas = [], []
        for archivo in entrada.validated_data['archivos']:
            extension = archivo.name.rsplit('.', 1)[-1].lower() if '.' in archivo.name else ''
            if extension not in ('pdf', 'docx'):
                rechazadas.append({'archivo': archivo.name,
                                   'error': 'Solo se aceptan archivos .pdf o .docx.'})
                continue
            creadas.append(ExtraccionMomento.objects.create(
                momento=momento, archivo=archivo, nombre_archivo_original=archivo.name,
                solicitado_por=request.user,
            ))

        if not creadas:
            raise ValidationError({'archivos': rechazadas or 'Ningún archivo válido.'})

        threading.Thread(
            target=procesar_extracciones_en_serie,
            args=([e.id for e in creadas],), daemon=True,
        ).start()

        return Response(
            {'creadas': ExtraccionMomentoSerializer(creadas, many=True).data,
             'rechazadas': rechazadas},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='aprobar')
    def aprobar(self, request, pk=None):
        """Compatibilidad. Desde HU-84 la transcripción se escribe sola, así que esto ya no
        aprueba nada: si las respuestas ya están escritas devuelve el estado tal cual (idempotente,
        para no romper un frontend que todavía llame acá), y solo escribe si por alguna razón
        quedó sin escribir — el caso real es una extracción vieja, de antes del cambio."""
        extraccion = self.get_object()
        if extraccion.aprobado_en is not None:
            return Response(ExtraccionMomentoSerializer(extraccion).data)
        if extraccion.estado != ExtraccionMomento.ESTADO_COMPLETO:
            raise ValidationError(
                'Esta extracción no está en estado "completo", así que no hay nada que escribir.'
            )

        escribir_extraccion_momento(extraccion, request.user)
        extraccion.refresh_from_db()
        return Response(ExtraccionMomentoSerializer(extraccion).data)

    @action(detail=True, methods=['post'], url_path='asignar-responsable')
    def asignar_responsable(self, request, pk=None):
        """Asigna a mano el participante que la IA no pudo emparejar (HU-55) — la transcripción
        ya está en `resultado`, lo único que falta es a nombre de quién se va a escribir. No toca
        `responsable_estado`: ese campo deja constancia de POR QUÉ hubo que asignar a mano."""
        extraccion = self.get_object()
        if extraccion.aprobado_en is not None:
            raise PermissionDenied('Esta extracción ya fue aprobada, no se puede reasignar.')

        entrada = AsignarResponsableMomentoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        participante = entrada.validated_data['participante']
        if participante.jornada_id != extraccion.momento.jornada_id:
            raise ValidationError(
                {'participante_id': 'Ese participante no pertenece a la jornada de este momento.'}
            )

        extraccion.participante = participante
        extraccion.save(update_fields=['participante'])
        # Asignar el responsable es lo único que faltaba para poder escribir: se escribe acá mismo
        # en vez de dejar una extracción completa esperando un paso que ya no existe (HU-84).
        if extraccion.estado == ExtraccionMomento.ESTADO_COMPLETO:
            escribir_extraccion_momento(extraccion, request.user)
            extraccion.refresh_from_db()
        return Response(ExtraccionMomentoSerializer(extraccion).data)
