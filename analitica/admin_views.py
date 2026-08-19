import threading
from datetime import timedelta

from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from .analysis import procesar_reporte
from .models import PlantillaAnalisis, Reporte
from .pdf_presentacion import construir_pdf_response
from .presentacion import generar_presentacion_html
from .serializers import PlantillaAnalisisSerializer, ReporteCrearSerializer, ReporteSerializer

# Si el worker que procesaba un reporte muere (crash, redeploy, OOM), ese reporte se queda
# 'procesando' para siempre — nada vuelve a tocarlo. Sin este umbral, el guard de abajo lo
# tomaría por un reporte legítimo en curso y bloquearía la creación de reportes nuevos de forma
# permanente. Pasado este tiempo se asume huérfano y se marca error automáticamente.
UMBRAL_HUERFANO = timedelta(minutes=30)
# La presentación (OpenAI, ver analitica/presentacion.py) es mucho más rápida que el análisis
# local — su propio timeout interno es de 4 minutos — así que un umbral de huérfano más corto
# alcanza para no bloquear reintentos legítimos por mucho tiempo tras un redeploy a mitad de
# generación (nos pasó probando esto mismo: un restart del servicio dejó una presentación
# 'procesando' para siempre).
UMBRAL_HUERFANO_PRESENTACION = timedelta(minutes=10)


class PlantillaAnalisisViewSet(viewsets.ModelViewSet):
    queryset = PlantillaAnalisis.objects.all()
    serializer_class = PlantillaAnalisisSerializer
    permission_classes = [IsAdminUser]

    def perform_create(self, serializer):
        serializer.save(creada_por=self.request.user)


class ReporteViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = Reporte.objects.select_related('jornada', 'plantilla').prefetch_related('momentos')
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return ReporteCrearSerializer
        return ReporteSerializer

    def create(self, request, *args, **kwargs):
        # Auto-sanación: cualquier reporte "en curso" hace rato (ver UMBRAL_HUERFANO) está
        # huérfano — su worker murió y nada lo va a completar nunca. Se marca error antes de
        # decidir si hay que bloquear, para que un huérfano no tranque la creación de reportes
        # para siempre.
        Reporte.objects.filter(
            estado__in=[Reporte.ESTADO_PENDIENTE, Reporte.ESTADO_PROCESANDO],
            creado_en__lt=timezone.now() - UMBRAL_HUERFANO,
        ).update(
            estado=Reporte.ESTADO_ERROR,
            error_mensaje='El reporte quedó procesando más de 30 minutos sin completarse '
                          '(probablemente el worker que lo procesaba se reinició o falló) y se '
                          'marcó como error automáticamente.',
        )

        # El análisis corre sobre un único modelo de IA compartido por proceso; dos reportes
        # procesando a la vez pueden hacer que llama.cpp aborte con un crash nativo (ver el
        # comentario en analitica/analysis.py junto a _inference_lock). Se bloquea acá, a nivel
        # de API, para que nunca se llegue a disparar un segundo hilo mientras el primero sigue.
        if Reporte.objects.filter(
            estado__in=[Reporte.ESTADO_PENDIENTE, Reporte.ESTADO_PROCESANDO]
        ).exists():
            return Response(
                {'detail': 'Ya hay un reporte en proceso (pendiente o procesando). El análisis '
                           'usa un único modelo de IA compartido y no soporta más de un reporte '
                           'a la vez — espera a que termine (o falle) antes de pedir otro.'},
                status=status.HTTP_409_CONFLICT,
            )

        entrada = ReporteCrearSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        reporte = entrada.save(solicitado_por=request.user)

        threading.Thread(target=procesar_reporte, args=(reporte.id,), daemon=True).start()

        salida = ReporteSerializer(reporte)
        headers = self.get_success_headers(salida.data)
        return Response(salida.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=['post'], url_path='generar-presentacion')
    def generar_presentacion(self, request, pk=None):
        """Genera (o regenera) la presentación HTML de este reporte vía OpenAI, a partir del
        análisis YA calculado (`reporte.analisis`) — no vuelve a correr el pipeline local, así que
        no comparte el guard de `create()` ni el pool de LLM local: puede pedirse aunque haya otro
        reporte en `procesando`."""
        reporte = self.get_object()
        if reporte.estado != Reporte.ESTADO_COMPLETO:
            return Response(
                {'detail': 'El análisis de este reporte todavía no está completo — la '
                           'presentación se genera a partir de datos ya calculados.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Auto-sanación, mismo espíritu que en create(): si quedó 'procesando' hace más de
        # UMBRAL_HUERFANO_PRESENTACION, el worker que la generaba ya no existe (crash, redeploy) —
        # se marca error para no bloquear un reintento legítimo para siempre.
        if (
            reporte.presentacion_estado == Reporte.PRESENTACION_ESTADO_PROCESANDO
            and reporte.actualizado_en < timezone.now() - UMBRAL_HUERFANO_PRESENTACION
        ):
            reporte.presentacion_estado = Reporte.PRESENTACION_ESTADO_ERROR
            reporte.presentacion_error = (
                'La presentación quedó procesando más de 10 minutos sin completarse '
                '(probablemente el worker que la generaba se reinició o falló) y se marcó '
                'como error automáticamente.'
            )
            reporte.save(update_fields=['presentacion_estado', 'presentacion_error'])
        if reporte.presentacion_estado == Reporte.PRESENTACION_ESTADO_PROCESANDO:
            return Response(
                {'detail': 'Ya hay una presentación en proceso para este reporte.'},
                status=status.HTTP_409_CONFLICT,
            )

        threading.Thread(target=generar_presentacion_html, args=(reporte.id,), daemon=True).start()

        salida = ReporteSerializer(reporte)
        return Response(salida.data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf(self, request, pk=None):
        """PDF del reporte, armado 100% en el servidor con reportlab a partir de `analisis` —
        sin llamar a ningún servicio externo, así que es rápido y sale igual cada vez. A
        diferencia de `generar-presentacion` (OpenAI, asíncrono), esto responde en la misma
        petición: no hay nada que "generar" de antemano ni estado que consultar después."""
        reporte = self.get_object()
        if reporte.estado != Reporte.ESTADO_COMPLETO:
            return Response(
                {'detail': 'El análisis de este reporte todavía no está completo.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return construir_pdf_response(reporte)
