import threading
from datetime import timedelta

from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from jornadas.permissions import EsAdminCompleto
from jornadas.scoping import filtrar_por_propietario, verificar_acceso_jornada

from .analisis_ia_openai import analizar_jornada_ia, analizar_momento_ia
from .analysis import _estadisticas_pregunta, procesar_reporte
from .infografia_ia_openai import _obtener_datos_analitica, generar_infografias
from .models import (
    AnalisisJornadaIA, AnalisisMomentoIA, AnalisisV2, InfografiaJornada, PlantillaAnalisis, Reporte,
)
from .pdf_presentacion import construir_pdf_response
from .presentacion import generar_presentacion_html
from .reporte_excel import construir_excel_response_por_momento, construir_excel_response_por_pregunta
from .serializers import (
    AnalisisJornadaIACrearSerializer, AnalisisJornadaIASerializer, AnalisisMomentoIACrearSerializer,
    AnalisisMomentoIASerializer, AnalisisSugerenciasSerializer, AnalisisV2CrearSerializer,
    AnalisisV2ListaSerializer, AnalisisV2Serializer, InfografiaJornadaCrearSerializer,
    InfografiaJornadaSerializer, PlantillaAnalisisSerializer, ReporteCrearSerializer, ReporteSerializer,
)
from .sugerencias_ia_openai import generar_sugerencias
from .v2.contrato import VERSION as VERSION_V2
from .v2.procesar import procesar_analisis_v2

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
# Mismo espíritu: una llamada a OpenAI (analitica/analisis_ia_openai.py) es independiente del
# pipeline local, así que un umbral corto alcanza para no bloquear reintentos legítimos tras un
# redeploy a mitad de generación.
UMBRAL_HUERFANO_ANALISIS_IA = timedelta(minutes=10)
# Mismo espíritu que UMBRAL_HUERFANO_PRESENTACION: la generación de infografía (OpenAI, ver
# analitica/infografia_ia_openai.py) es independiente del pipeline local, así que un umbral corto
# alcanza para no bloquear reintentos legítimos tras un redeploy a mitad de generación.
UMBRAL_HUERFANO_INFOGRAFIA = timedelta(minutes=10)
# La llamada v2 es una sola pero grande (salida de hasta ~24k tokens con un modelo de razonamiento)
# y en bertopic_llm va precedida de embeddings + clustering por pregunta — más margen que las vías
# legacy antes de dar por muerto al worker.
UMBRAL_HUERFANO_ANALISIS_V2 = timedelta(minutes=45)


def _sin_respuestas(momentos):
    """True si NINGUNA pregunta de estos momentos tiene una sola `Respuesta` real — el guard de
    HU-57 §5 (docs/HU_BACKEND_ANALISIS_GUIADO.md): "sin respuestas en el alcance → 400 al crear,
    nunca un registro que termine en estado 'error'" después de gastar tiempo de cómputo real por
    nada. Vive acá (capa de vista) y no en los serializers de creación: tiene que evaluarse
    DESPUÉS de `verificar_acceso_jornada` — antes, un 400 de "sin respuestas" en `is_valid()`
    taparía el 403 de jornada ajena y le revelaría a un admin de otra dependencia si esa jornada
    ajena tiene respuestas o no, solo por el código de estado."""
    from participantes.models import Respuesta

    return not Respuesta.objects.filter(pregunta__momento__in=momentos).exists()


def _filtro_fuente_infografia(reporte=None, analisis_momento=None, analisis_jornada=None, analisis_v2=None):
    """Cuál de los cuatro FK identifica la versión exacta de análisis de esta infografía —
    EXACTAMENTE uno, garantizado por `InfografiaJornadaCrearSerializer.validate()` (HU-73). Se usa
    para acotar el guard de "ya hay una en curso"/huérfanas a esa versión puntual, nunca a la
    jornada o al momento en general: dos versiones de análisis del mismo momento/jornada
    (distintos métodos o enfoques, HU-71) son trabajos completamente independientes entre sí,
    generar la infografía de una nunca debe bloquear ni confundirse con la de la otra."""
    if analisis_v2 is not None:
        return {'analisis_v2': analisis_v2}
    if analisis_momento is not None:
        return {'analisis_momento': analisis_momento}
    if analisis_jornada is not None:
        return {'analisis_jornada': analisis_jornada}
    return {'reporte': reporte}


def _infografias_en_curso(reporte=None, analisis_momento=None, analisis_jornada=None, analisis_v2=None):
    return InfografiaJornada.objects.filter(
        estado__in=[InfografiaJornada.ESTADO_PENDIENTE, InfografiaJornada.ESTADO_PROCESANDO],
        **_filtro_fuente_infografia(reporte, analisis_momento, analisis_jornada, analisis_v2=analisis_v2),
    )


def sanar_infografias_huerfanas(reporte=None, analisis_momento=None, analisis_jornada=None, analisis_v2=None):
    """Una infografía cuyo worker murió a mitad de generación (crash, redeploy) se queda en
    'procesando' para siempre y bloquearía pedir otra — pasado el umbral se marca error."""
    _infografias_en_curso(reporte, analisis_momento, analisis_jornada, analisis_v2=analisis_v2).filter(
        actualizado_en__lt=timezone.now() - UMBRAL_HUERFANO_INFOGRAFIA,
    ).update(
        estado=InfografiaJornada.ESTADO_ERROR,
        error_mensaje='La infografía quedó procesando más de 10 minutos sin completarse '
                      '(probablemente el worker que la generaba se reinició o falló) y se marcó '
                      'como error automáticamente.',
    )


def hay_infografia_en_curso(reporte=None, analisis_momento=None, analisis_jornada=None, analisis_v2=None):
    return _infografias_en_curso(reporte, analisis_momento, analisis_jornada, analisis_v2=analisis_v2).exists()


class PlantillaAnalisisViewSet(viewsets.ModelViewSet):
    """Son prompts de sistema globales (no por jornada) — una dependencia puede leerlas para
    elegir cuál usar al pedir un reporte, pero solo un admin completo puede crear/editar/borrar."""
    serializer_class = PlantillaAnalisisSerializer
    permission_classes = [IsAdminUser]

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [EsAdminCompleto()]
        return super().get_permissions()

    def get_queryset(self):
        # ?tipo=gpt_momento&predeterminada=true deja pedir en una sola llamada "el prompt activo
        # de este motor de análisis puntual", sin que el frontend tenga que traer todas las
        # plantillas y filtrar del lado del cliente — útil para una ventana de edición dedicada a
        # un solo tipo (ver HU-14e/HU-14f en docs/USER_STORIES.md).
        queryset = PlantillaAnalisis.objects.all()
        tipo = self.request.query_params.get('tipo')
        if tipo:
            queryset = queryset.filter(tipo=tipo)
        predeterminada = self.request.query_params.get('predeterminada')
        if predeterminada is not None:
            queryset = queryset.filter(predeterminada=predeterminada.lower() in ('true', '1'))
        return queryset

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
        queryset = filtrar_por_propietario(queryset, self.request.user, 'jornada__propietarios')
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
        jornada = entrada.validated_data['jornada']
        verificar_acceso_jornada(request.user, jornada)

        # HU-57 §5, ver el comentario de `_sin_respuestas` arriba.
        momentos = entrada.validated_data.get('momentos') or []
        scope = momentos or list(jornada.momentos.all())
        if _sin_respuestas(scope):
            detalle = (
                f'El momento "{momentos[0].titulo}" no tiene respuestas todavía.' if len(momentos) == 1
                else 'La jornada no tiene respuestas todavía.'
            )
            return Response({'momentos': [detalle]}, status=status.HTTP_400_BAD_REQUEST)

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

    @action(detail=True, methods=['post'], url_path='generar-infografia')
    def generar_infografia(self, request, pk=None):
        """Atajo para pedir la infografía a partir de ESTE reporte. La vía general es
        `POST /api/admin/infografias/` con la jornada o el momento, que no exige reporte alguno —
        esta se mantiene para cuando se quiere forzar que los datos salgan de un reporte concreto.

        Acepta `{"instrucciones": "..."}` en el cuerpo, igual que la vía general."""
        reporte = self.get_object()
        if reporte.estado != Reporte.ESTADO_COMPLETO:
            return Response(
                {'detail': 'El análisis de este reporte todavía no está completo — la '
                           'infografía se genera a partir de datos ya calculados.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        sanar_infografias_huerfanas(reporte=reporte)
        if hay_infografia_en_curso(reporte=reporte):
            return Response(
                {'detail': 'Ya hay una infografía en proceso para este reporte.'},
                status=status.HTTP_409_CONFLICT,
            )

        infografia = InfografiaJornada.objects.create(
            jornada=reporte.jornada, reporte=reporte, solicitado_por=request.user,
            instrucciones=(request.data.get('instrucciones') or '').strip(),
        )
        threading.Thread(target=generar_infografias, args=(infografia.id,), daemon=True).start()

        salida = InfografiaJornadaSerializer(infografia)
        headers = self.get_success_headers(salida.data)
        return Response(salida.data, status=status.HTTP_202_ACCEPTED, headers=headers)

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


class AnalisisMomentoIAViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Vía de análisis alternativa a `ReporteViewSet`: una sola llamada a OpenAI analiza un
    `Momento` completo de una vez (ver `analitica/analisis_ia_openai.py`), en vez del pipeline
    local multiagente pregunta por pregunta. No depende de crear un `Reporte` primero."""
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = AnalisisMomentoIA.objects.select_related('momento')
        queryset = filtrar_por_propietario(queryset, self.request.user, 'momento__jornada__propietarios')
        momento_id = self.request.query_params.get('momento')
        if momento_id:
            queryset = queryset.filter(momento_id=momento_id)
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return AnalisisMomentoIACrearSerializer
        return AnalisisMomentoIASerializer

    def create(self, request, *args, **kwargs):
        entrada = AnalisisMomentoIACrearSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        momento = entrada.validated_data['momento']
        verificar_acceso_jornada(request.user, momento.jornada)

        # Auto-sanación, mismo espíritu que en ReporteViewSet.create: si el análisis IA anterior
        # de ESTE momento quedó 'procesando' hace más de UMBRAL_HUERFANO_ANALISIS_IA, su worker ya
        # no existe (crash, redeploy) — se marca error para no bloquear un reintento legítimo.
        AnalisisMomentoIA.objects.filter(
            momento=momento,
            estado__in=[AnalisisMomentoIA.ESTADO_PENDIENTE, AnalisisMomentoIA.ESTADO_PROCESANDO],
            actualizado_en__lt=timezone.now() - UMBRAL_HUERFANO_ANALISIS_IA,
        ).update(
            estado=AnalisisMomentoIA.ESTADO_ERROR,
            error_mensaje='El análisis quedó procesando más de 10 minutos sin completarse '
                          '(probablemente el worker se reinició o falló) y se marcó como error '
                          'automáticamente.',
        )

        # Cada llamada es independiente de OpenAI (no comparte el modelo local ni su pool), así
        # que distintos momentos sí pueden analizarse en paralelo sin riesgo — el bloqueo es solo
        # por momento, para no lanzar dos análisis del mismo momento a la vez.
        if AnalisisMomentoIA.objects.filter(
            momento=momento,
            estado__in=[AnalisisMomentoIA.ESTADO_PENDIENTE, AnalisisMomentoIA.ESTADO_PROCESANDO],
        ).exists():
            return Response(
                {'detail': 'Ya hay un análisis con IA en proceso para este momento — espera a '
                           'que termine (o falle) antes de pedir otro.'},
                status=status.HTTP_409_CONFLICT,
            )

        # HU-57 §5, ver el comentario de `_sin_respuestas` arriba. Después del 409, mismo criterio
        # que en AnalisisJornadaIAViewSet.create.
        if _sin_respuestas([momento]):
            return Response(
                {'momento': [f'El momento "{momento.titulo}" no tiene respuestas todavía.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        analisis = entrada.save(solicitado_por=request.user)
        threading.Thread(target=analizar_momento_ia, args=(analisis.id,), daemon=True).start()

        salida = AnalisisMomentoIASerializer(analisis)
        headers = self.get_success_headers(salida.data)
        return Response(salida.data, status=status.HTTP_201_CREATED, headers=headers)


class AnalisisJornadaIAViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Mismo mecanismo que `AnalisisMomentoIAViewSet`, a escala de jornada completa: una sola
    llamada a OpenAI analiza TODOS los momentos activos de una `Jornada` de una vez (ver
    `analitica/analisis_ia_openai.py`), para encontrar hallazgos que cruzan momentos distintos."""
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = AnalisisJornadaIA.objects.select_related('jornada')
        queryset = filtrar_por_propietario(queryset, self.request.user, 'jornada__propietarios')
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return AnalisisJornadaIACrearSerializer
        return AnalisisJornadaIASerializer

    def create(self, request, *args, **kwargs):
        entrada = AnalisisJornadaIACrearSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        jornada = entrada.validated_data['jornada']
        verificar_acceso_jornada(request.user, jornada)

        # Auto-sanación, mismo espíritu que en AnalisisMomentoIAViewSet.create.
        AnalisisJornadaIA.objects.filter(
            jornada=jornada,
            estado__in=[AnalisisJornadaIA.ESTADO_PENDIENTE, AnalisisJornadaIA.ESTADO_PROCESANDO],
            actualizado_en__lt=timezone.now() - UMBRAL_HUERFANO_ANALISIS_IA,
        ).update(
            estado=AnalisisJornadaIA.ESTADO_ERROR,
            error_mensaje='El análisis quedó procesando más de 10 minutos sin completarse '
                          '(probablemente el worker se reinició o falló) y se marcó como error '
                          'automáticamente.',
        )

        if AnalisisJornadaIA.objects.filter(
            jornada=jornada,
            estado__in=[AnalisisJornadaIA.ESTADO_PENDIENTE, AnalisisJornadaIA.ESTADO_PROCESANDO],
        ).exists():
            return Response(
                {'detail': 'Ya hay un análisis con IA en proceso para esta jornada — espera a '
                           'que termine (o falle) antes de pedir otro.'},
                status=status.HTTP_409_CONFLICT,
            )

        # HU-57 §5, ver el comentario de `_sin_respuestas` arriba. Después del 409: si ya hay uno
        # en curso, eso es lo que importa reportar primero, sin importar si además faltan
        # respuestas. Mismo alcance que `_construir_payload_jornada` en analisis_ia_openai.py —
        # TODOS los momentos, sin filtrar por `activo` (ese campo es de visibilidad para
        # participantes, no dice nada sobre si hay respuestas reales que analizar — bug reportado
        # en producción, 2026-09-20: bloqueaba analizar una jornada con respuestas reales solo
        # porque sus momentos ya estaban desactivados). "Sin respuestas" y "lo que de verdad se le
        # manda al modelo" siguen siendo la misma definición de alcance.
        if _sin_respuestas(list(jornada.momentos.all())):
            return Response(
                {'jornada': ['La jornada no tiene respuestas todavía en ningún momento.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        analisis = entrada.save(solicitado_por=request.user)
        threading.Thread(target=analizar_jornada_ia, args=(analisis.id,), daemon=True).start()

        salida = AnalisisJornadaIASerializer(analisis)
        headers = self.get_success_headers(salida.data)
        return Response(salida.data, status=status.HTTP_201_CREATED, headers=headers)


class AnalisisV2ViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Análisis bajo el contrato kunsamu.analisis/v2 (ver `AnalisisV2` en models.py y el plan en
    docs/mejora_promps/plan_implementacion/). Orden de guards en `create` (D4 del plan): 400 de
    forma → 403 de jornada ajena → sanar huérfanos → 409 si hay otro en curso con el MISMO alcance
    (jornada + modo + conjunto de momentos) → 400 si la jornada no tiene momentos. Sin guard de
    "sin respuestas": `sin_datos` es un estado analítico válido del contrato y lo produce el
    backend sin gastar una llamada (D11)."""
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = AnalisisV2.objects.select_related('jornada').prefetch_related('momentos')
        queryset = filtrar_por_propietario(queryset, self.request.user, 'jornada__propietarios')
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        momento_id = self.request.query_params.get('momento')
        if momento_id:
            queryset = queryset.filter(momentos__id=momento_id).distinct()
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return AnalisisV2CrearSerializer
        if self.action == 'list':
            return AnalisisV2ListaSerializer
        return AnalisisV2Serializer

    def create(self, request, *args, **kwargs):
        entrada = AnalisisV2CrearSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        jornada = entrada.validated_data['jornada']
        verificar_acceso_jornada(request.user, jornada)
        modo = entrada.validated_data['modo']
        momentos = entrada.validated_data.get('momentos') or []

        AnalisisV2.objects.filter(
            jornada=jornada,
            estado__in=[AnalisisV2.ESTADO_PENDIENTE, AnalisisV2.ESTADO_PROCESANDO],
            actualizado_en__lt=timezone.now() - UMBRAL_HUERFANO_ANALISIS_V2,
        ).update(
            estado=AnalisisV2.ESTADO_ERROR,
            error_mensaje='El análisis quedó procesando más de 45 minutos sin completarse '
                          '(probablemente el worker se reinició o falló) y se marcó como error '
                          'automáticamente.',
        )

        ids_alcance = {m.id for m in momentos}
        en_curso = AnalisisV2.objects.filter(
            jornada=jornada, modo=modo,
            estado__in=[AnalisisV2.ESTADO_PENDIENTE, AnalisisV2.ESTADO_PROCESANDO],
        ).prefetch_related('momentos')
        for otro in en_curso:
            if {m.id for m in otro.momentos.all()} == ids_alcance:
                return Response(
                    {'detail': 'Ya hay un análisis v2 en proceso para este mismo alcance — espera a '
                               'que termine (o falle) antes de pedir otro.'},
                    status=status.HTTP_409_CONFLICT,
                )

        if modo == AnalisisV2.MODO_INTEGRAL and not jornada.momentos.exists():
            return Response(
                {'jornada': ['La jornada no tiene momentos: no hay nada que analizar.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        analisis = entrada.save(solicitado_por=request.user)
        threading.Thread(target=procesar_analisis_v2, args=(analisis.id,), daemon=True).start()

        salida = AnalisisV2Serializer(analisis)
        headers = self.get_success_headers(salida.data)
        return Response(salida.data, status=status.HTTP_201_CREATED, headers=headers)


class AnalisisSugerenciasView(APIView):
    """`POST /api/admin/analisis-sugerencias/` — HU-57 §3 (docs/HU_BACKEND_ANALISIS_GUIADO.md).
    Sin modelo detrás: nada de esto se persiste. Valida la entrada, confirma acceso a la jornada
    (403 en jornada ajena, mismo scoping que el resto del módulo) y siempre responde `200` — si
    `generar_sugerencias` no pudo generar nada (sin API key, timeout, respuesta no interpretable),
    la lista simplemente viene vacía; nunca es un error que el asistente tenga que manejar."""
    permission_classes = [IsAdminUser]

    def post(self, request):
        entrada = AnalisisSugerenciasSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        verificar_acceso_jornada(request.user, datos['jornada'])

        sugerencias = generar_sugerencias(
            jornada=datos['jornada'],
            momento_ids=[momento.id for momento in datos['momentos']],
            metodo=datos['metodo'], enfoque=datos['enfoque'],
            contexto=datos['contexto'], instrucciones=datos['instrucciones'],
        )
        return Response({'sugerencias': sugerencias})


def _item_reporte(reporte):
    # Un `Reporte` con exactamente UN momento (alcance=momento) sí tiene "el" momento al que
    # titular la tarjeta; con la jornada completa (alcance=jornada) o varios combinados
    # (alcance=momentos) no hay un único momento al que referirse — igual que pide HU-57 §4 para
    # el resto de tipos, esos tres campos quedan en `None`.
    momentos = list(reporte.momentos.all())
    momento = momentos[0] if len(momentos) == 1 else None
    return {
        'tipo': 'reporte',
        'id': reporte.id,
        'jornada': reporte.jornada_id,
        'momento': momento.id if momento else None,
        'momento_titulo': momento.titulo if momento else None,
        'momento_orden': momento.orden if momento else None,
        'metodo': 'bertopic',
        'enfoque': reporte.enfoque,
        'alcance': reporte.alcance,
        'estado': reporte.estado,
        'error_mensaje': reporte.error_mensaje,
        'creado_en': reporte.creado_en,
        'completado_en': reporte.completado_en,
    }


def _item_analisis_momento(analisis):
    return {
        'tipo': 'analisis_momento',
        'id': analisis.id,
        'jornada': analisis.momento.jornada_id,
        'momento': analisis.momento_id,
        'momento_titulo': analisis.momento.titulo,
        'momento_orden': analisis.momento.orden,
        'metodo': 'openai',
        'enfoque': analisis.enfoque,
        'alcance': 'momento',
        'estado': analisis.estado,
        'error_mensaje': analisis.error_mensaje,
        'creado_en': analisis.creado_en,
        'completado_en': analisis.completado_en,
    }


def _item_analisis_jornada(analisis):
    return {
        'tipo': 'analisis_jornada',
        'id': analisis.id,
        'jornada': analisis.jornada_id,
        'momento': None,
        'momento_titulo': None,
        'momento_orden': None,
        'metodo': 'openai',
        'enfoque': analisis.enfoque,
        'alcance': 'jornada',
        'estado': analisis.estado,
        'error_mensaje': analisis.error_mensaje,
        'creado_en': analisis.creado_en,
        'completado_en': analisis.completado_en,
    }


def _item_analisis_v2(analisis):
    momentos = list(analisis.momentos.all())
    momento = momentos[0] if len(momentos) == 1 else None
    if analisis.modo == AnalisisV2.MODO_INTEGRAL:
        alcance = 'jornada'
    else:
        alcance = 'momento' if len(momentos) == 1 else 'momentos'
    return {
        'tipo': 'analisis_v2',
        'id': analisis.id,
        'jornada': analisis.jornada_id,
        'momento': momento.id if momento else None,
        'momento_titulo': momento.titulo if momento else None,
        'momento_orden': momento.orden if momento else None,
        # Derivado del pipeline para que la agrupación actual del panel siga funcionando.
        'metodo': 'bertopic' if analisis.pipeline == AnalisisV2.PIPELINE_BERTOPIC_LLM else 'openai',
        'enfoque': None,
        'alcance': alcance,
        'estado': analisis.estado,
        'error_mensaje': analisis.error_mensaje,
        'creado_en': analisis.creado_en,
        'completado_en': analisis.completado_en,
        # Solo los items v2 traen estas cuatro claves: es lo que le dice al frontend qué renderer usar.
        'version': VERSION_V2,
        'modo': analisis.modo,
        'pipeline': analisis.pipeline,
        'estado_analitico': (analisis.resultado or {}).get('estado'),
    }


class AnalisisUnificadoView(APIView):
    """`GET /api/admin/analisis/?jornada=<id>` o `?momento=<id>` — HU-57 §4. Une `Reporte` +
    `AnalisisMomentoIA` + `AnalisisJornadaIA` + `AnalisisV2` de una jornada (o de un momento) en
    una sola lista, para que el panel arme la pestaña Analítica con una consulta en vez de varias
    repetidas cada pocos segundos mientras algo procesa. Solo lectura: abrir, borrar y el detalle
    siguen en los endpoints propios de cada tipo (`ReporteViewSet`, `AnalisisMomentoIAViewSet`,
    `AnalisisJornadaIAViewSet`, `AnalisisV2ViewSet`) — acá no hay ni `get_object` ni acción por id.

    Sin paginación (mismo criterio que el resto del módulo): no se espera que una sola jornada
    acumule más de unos cientos de análisis."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        jornada_id = request.query_params.get('jornada')
        momento_id = request.query_params.get('momento')
        if not jornada_id and not momento_id:
            return Response(
                {'detail': 'Manda "jornada" o "momento" como query param.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        items = []

        reportes = filtrar_por_propietario(
            Reporte.objects.select_related('jornada').prefetch_related('momentos'),
            request.user, 'jornada__propietarios',
        )
        if jornada_id:
            reportes = reportes.filter(jornada_id=jornada_id)
        if momento_id:
            reportes = reportes.filter(momentos__id=momento_id)
        items.extend(_item_reporte(r) for r in reportes)

        analisis_momento = filtrar_por_propietario(
            AnalisisMomentoIA.objects.select_related('momento', 'momento__jornada'),
            request.user, 'momento__jornada__propietarios',
        )
        if jornada_id:
            analisis_momento = analisis_momento.filter(momento__jornada_id=jornada_id)
        if momento_id:
            analisis_momento = analisis_momento.filter(momento_id=momento_id)
        items.extend(_item_analisis_momento(a) for a in analisis_momento)

        # Un análisis de JORNADA completa nunca es "de" un momento puntual — filtrar por
        # `?momento=` lo excluye del todo, no tendría sentido devolverlo.
        if not momento_id:
            analisis_jornada = filtrar_por_propietario(
                AnalisisJornadaIA.objects.select_related('jornada'),
                request.user, 'jornada__propietarios',
            )
            if jornada_id:
                analisis_jornada = analisis_jornada.filter(jornada_id=jornada_id)
            items.extend(_item_analisis_jornada(a) for a in analisis_jornada)

        analisis_v2 = filtrar_por_propietario(
            AnalisisV2.objects.select_related('jornada').prefetch_related('momentos'),
            request.user, 'jornada__propietarios',
        )
        if jornada_id:
            analisis_v2 = analisis_v2.filter(jornada_id=jornada_id)
        if momento_id:
            # Un v2 integral abarca todos los momentos pero no es "de" uno puntual — mismo criterio
            # que analisis_jornada: con ?momento= solo entran los por_momento que lo incluyen.
            analisis_v2 = analisis_v2.filter(momentos__id=momento_id).distinct()
        items.extend(_item_analisis_v2(a) for a in analisis_v2)

        items.sort(key=lambda item: item['creado_en'], reverse=True)
        return Response(items)


class InfografiaJornadaViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Infografías: se piden acá (`POST`) y se consultan acá mismo por polling.

    HU-73: cada infografía queda ATADA a una versión exacta de análisis — manda EXACTAMENTE uno
    de `reporte` (pipeline local), `analisis_momento` (lectura IA de un momento),
    `analisis_jornada` (lectura IA de jornada completa) o `analisis_v2` (contrato
    `kunsamu.analisis/v2`); `jornada`/`momento` se derivan solos de esa versión y no se aceptan
    sueltos. Antes de esta HU, mandar solo `{"jornada": id}` o `{"momento": id}` caía al análisis
    más reciente completo de ese alcance — con HU-71 una jornada/momento acumula varias VERSIONES
    de análisis a la vez, y esa caída silenciosa a "la más reciente" significaba que dos versiones
    podían terminar compartiendo la misma infografía (o peor, una infografía generada para ver la
    versión A mostrando en realidad datos de la versión B que se volvió "la más reciente" mientras
    tanto). Eso ya no puede pasar: sin un id exacto de análisis, `400`."""
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = InfografiaJornada.objects.select_related(
            'jornada', 'momento', 'reporte', 'analisis_momento', 'analisis_jornada', 'analisis_v2',
        ).prefetch_related('imagenes')
        queryset = filtrar_por_propietario(queryset, self.request.user, 'jornada__propietarios')
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        momento_id = self.request.query_params.get('momento')
        if momento_id:
            queryset = queryset.filter(momento_id=momento_id)
        reporte_id = self.request.query_params.get('reporte')
        if reporte_id:
            queryset = queryset.filter(reporte_id=reporte_id)
        analisis_momento_id = self.request.query_params.get('analisis_momento')
        if analisis_momento_id:
            queryset = queryset.filter(analisis_momento_id=analisis_momento_id)
        analisis_jornada_id = self.request.query_params.get('analisis_jornada')
        if analisis_jornada_id:
            queryset = queryset.filter(analisis_jornada_id=analisis_jornada_id)
        analisis_v2_id = self.request.query_params.get('analisis_v2')
        if analisis_v2_id:
            queryset = queryset.filter(analisis_v2_id=analisis_v2_id)
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return InfografiaJornadaCrearSerializer
        return InfografiaJornadaSerializer

    def create(self, request, *args, **kwargs):
        entrada = InfografiaJornadaCrearSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        jornada = entrada.validated_data['jornada']
        momento = entrada.validated_data.get('momento')
        reporte = entrada.validated_data.get('reporte')
        analisis_momento = entrada.validated_data.get('analisis_momento')
        analisis_jornada = entrada.validated_data.get('analisis_jornada')
        analisis_v2 = entrada.validated_data.get('analisis_v2')
        verificar_acceso_jornada(request.user, jornada)

        # Acotado a la versión EXACTA (HU-73), no a la jornada/momento en general: generar la
        # infografía de una versión nunca debe bloquearse ni confundirse con la de otra versión
        # del mismo alcance.
        sanar_infografias_huerfanas(reporte, analisis_momento, analisis_jornada, analisis_v2=analisis_v2)
        if hay_infografia_en_curso(reporte, analisis_momento, analisis_jornada, analisis_v2=analisis_v2):
            return Response(
                {'detail': 'Ya hay una infografía en proceso para esta versión del análisis — '
                           'espera a que termine (o falle) antes de pedir otra.'},
                status=status.HTTP_409_CONFLICT,
            )

        # Se valida acá y no solo dentro del hilo para que el frontend se entere de inmediato, en
        # vez de crear un registro que va a fallar y tener que descubrirlo haciendo polling. Los
        # cinco argumentos, siempre los cinco: antes de HU-73 esta llamada no mandaba
        # `analisis_momento`/`analisis_jornada`, así que el chequeo previo evaluaba "la más
        # reciente" mientras la generación real (`generar_infografias`) ya usaba la fijada —
        # podían no ser la misma.
        _, error = _obtener_datos_analitica(
            jornada, reporte, momento, analisis_momento, analisis_jornada, analisis_v2=analisis_v2,
        )
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)

        infografia = entrada.save(solicitado_por=request.user)
        threading.Thread(target=generar_infografias, args=(infografia.id,), daemon=True).start()

        salida = InfografiaJornadaSerializer(infografia)
        headers = self.get_success_headers(salida.data)
        return Response(salida.data, status=status.HTTP_201_CREATED, headers=headers)


class EstadisticasPreguntasView(APIView):
    """Conteos reales por pregunta (total de respuestas y, para unica/multiple, conteo por
    opción) — sin IA, sin narrativa, solo los números tal cual están en la base de datos ahora
    mismo. Reusa `_estadisticas_pregunta`, la misma función que ya usan los reportes (local y vía
    OpenAI) como fuente de verdad de las cifras, así que nunca puede desalinearse de lo que
    terminan mostrando esos reportes."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        from jornadas.models import Pregunta

        momento_id = request.query_params.get('momento')
        jornada_id = request.query_params.get('jornada')
        if not momento_id and not jornada_id:
            return Response(
                {'detail': 'Debes indicar ?momento=<id> o ?jornada=<id>.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        preguntas = Pregunta.objects.filter(activa=True).select_related('momento')
        preguntas = filtrar_por_propietario(preguntas, request.user, 'momento__jornada__propietarios')
        if momento_id:
            preguntas = preguntas.filter(momento_id=momento_id)
        if jornada_id:
            preguntas = preguntas.filter(momento__jornada_id=jornada_id)
        preguntas = preguntas.order_by('momento__orden', 'orden')

        data = [
            {
                'pregunta_id': pregunta.id,
                'momento_id': pregunta.momento_id,
                'texto': pregunta.texto,
                'tipo': pregunta.tipo,
                'obligatoria': pregunta.obligatoria,
                'estadisticas': _estadisticas_pregunta(pregunta),
            }
            for pregunta in preguntas
        ]
        return Response(data, status=status.HTTP_200_OK)


class ProgresoParticipantesView(APIView):
    """Avance de una jornada completa, con dos niveles:
    - `resumen_momentos`: un reporte por momento (cuántas preguntas tiene, cuántas son
      obligatorias, y cuántos participantes/mesas ya lo completaron) — la foto agregada de
      "cómo va" cada momento.
    - `participantes`: el detalle individual — para cada participante, el estado de CADA
      pregunta de CADA momento (respondida o no), no solo un conteo. Para momentos tipo mesa
      el estado es el de la mesa entera — solo el vocero envía, pero todos sus compañeros de
      mesa comparten ese mismo avance, porque la respuesta es de la mesa, no de la persona
      (ver RespuestasMomentoView).

    Deliberadamente NO filtra por `momento.activo` — ese flag solo controla si un participante
    puede VER/enviar el momento ahora mismo (ver MomentosIndiceView/RespuestasMomentoView); una
    jornada ya cerrada, con todos sus momentos desactivados, sigue necesitando este reporte para
    el cierre y las estadísticas finales."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        from collections import defaultdict

        from jornadas.models import Momento
        from participantes.models import Participante, Respuesta

        jornada_id = request.query_params.get('jornada')
        if not jornada_id:
            return Response(
                {'detail': 'Debes indicar ?jornada=<id>.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        momentos_qs = filtrar_por_propietario(
            Momento.objects.filter(jornada_id=jornada_id), request.user, 'jornada__propietarios'
        )
        momentos = list(momentos_qs.order_by('orden'))
        if not momentos:
            return Response(
                {'detail': 'Esta jornada no tiene momentos.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        preguntas_por_momento = {
            momento.id: list(momento.preguntas.filter(activa=True).order_by('orden'))
            for momento in momentos
        }

        respondidas_por_participante = defaultdict(set)
        for participante_id, pregunta_id in Respuesta.objects.filter(
            pregunta__momento__jornada_id=jornada_id,
            pregunta__activa=True,
            pregunta__momento__tipo=Momento.TIPO_INDIVIDUAL,
            participante__isnull=False,
        ).values_list('participante_id', 'pregunta_id'):
            respondidas_por_participante[participante_id].add(pregunta_id)

        respondidas_por_mesa = defaultdict(set)
        for mesa, pregunta_id in Respuesta.objects.filter(
            pregunta__momento__jornada_id=jornada_id,
            pregunta__activa=True,
            pregunta__momento__tipo=Momento.TIPO_MESA,
            mesa__isnull=False,
        ).values_list('mesa', 'pregunta_id'):
            respondidas_por_mesa[mesa].add(pregunta_id)

        participantes = list(Participante.objects.filter(jornada_id=jornada_id).order_by('nombre', 'apellido'))
        mesas_registradas = {p.mesa for p in participantes if p.mesa is not None}

        # --- reporte por momento, agregado para toda la jornada ---
        resumen_momentos = []
        for momento in momentos:
            preguntas = preguntas_por_momento[momento.id]
            obligatorias_ids = {p.id for p in preguntas if p.obligatoria}
            if momento.tipo == Momento.TIPO_MESA:
                universo = len(mesas_registradas)
                completaron = sum(
                    1 for mesa in mesas_registradas
                    if obligatorias_ids <= respondidas_por_mesa.get(mesa, set())
                )
            else:
                universo = len(participantes)
                completaron = sum(
                    1 for p in participantes
                    if obligatorias_ids <= respondidas_por_participante.get(p.id, set())
                )
            resumen_momentos.append({
                'momento_id': momento.id,
                'titulo': momento.titulo,
                'tipo': momento.tipo,
                'total_preguntas': len(preguntas),
                'total_obligatorias': len(obligatorias_ids),
                'universo': universo,
                'completaron': completaron,
                'porcentaje_completado': round(100 * completaron / universo) if universo else 0,
            })

        # --- detalle por participante, pregunta a pregunta ---
        data_participantes = []
        for participante in participantes:
            momentos_progreso = []
            total_preguntas = 0
            total_obligatorias = 0
            total_respondidas_total = 0
            total_respondidas_obligatorias = 0
            for momento in momentos:
                preguntas = preguntas_por_momento[momento.id]
                if momento.tipo == Momento.TIPO_MESA:
                    respondidas_ids = (
                        respondidas_por_mesa.get(participante.mesa, set())
                        if participante.mesa is not None else set()
                    )
                else:
                    respondidas_ids = respondidas_por_participante.get(participante.id, set())

                obligatorias_ids = {p.id for p in preguntas if p.obligatoria}
                respondidas_obligatorias = len(obligatorias_ids & respondidas_ids)
                respondidas_total = len({p.id for p in preguntas} & respondidas_ids)

                total_preguntas += len(preguntas)
                total_obligatorias += len(obligatorias_ids)
                total_respondidas_total += respondidas_total
                total_respondidas_obligatorias += respondidas_obligatorias

                momentos_progreso.append({
                    'momento_id': momento.id,
                    'titulo': momento.titulo,
                    'tipo': momento.tipo,
                    'total_preguntas': len(preguntas),
                    'total_obligatorias': len(obligatorias_ids),
                    'respondidas_obligatorias': respondidas_obligatorias,
                    'respondidas_total': respondidas_total,
                    'completado': obligatorias_ids <= respondidas_ids,
                    'preguntas': [
                        {
                            'pregunta_id': p.id,
                            'texto': p.texto,
                            'tipo': p.tipo,
                            'obligatoria': p.obligatoria,
                            'respondida': p.id in respondidas_ids,
                        }
                        for p in preguntas
                    ],
                })

            data_participantes.append({
                'participante_id': participante.id,
                'nombre': participante.nombre,
                'apellido': participante.apellido,
                'correo_institucional': participante.correo_institucional,
                'rol': participante.rol,
                'mesa': participante.mesa,
                'es_vocero': participante.es_vocero,
                'momentos': momentos_progreso,
                'total_preguntas': total_preguntas,
                'total_obligatorias': total_obligatorias,
                'total_respondidas_total': total_respondidas_total,
                'total_respondidas_obligatorias': total_respondidas_obligatorias,
                'completado_instrumento': total_respondidas_obligatorias >= total_obligatorias,
            })

        solo_completados = request.query_params.get('solo_completados')
        if solo_completados in ('true', '1', 'True'):
            data_participantes = [f for f in data_participantes if f['completado_instrumento']]

        return Response(
            {
                'jornada_id': int(jornada_id) if jornada_id.isdigit() else jornada_id,
                'resumen_momentos': resumen_momentos,
                'participantes': data_participantes,
            },
            status=status.HTTP_200_OK,
        )


class MesasView(APIView):
    """Cuántas mesas hay en una jornada y quién está en cada una — para que el admin vea de un
    vistazo cómo quedó la distribución (y quién es el vocero de cada mesa) sin tener que armar
    esa agrupación a mano a partir del listado plano de participantes."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        from participantes.models import Participante
        from participantes.utils import agrupar_por_mesa

        jornada_id = request.query_params.get('jornada')
        if not jornada_id or not jornada_id.isdigit():
            return Response(
                {'detail': 'Debes indicar ?jornada=<id>.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        jornada_id = int(jornada_id)

        participantes = filtrar_por_propietario(
            Participante.objects.filter(jornada_id=jornada_id), request.user, 'jornada__propietarios'
        ).order_by('mesa', 'nombre', 'apellido')

        def _resumen_participante(p):
            return {
                'participante_id': p.id,
                'nombre': p.nombre,
                'apellido': p.apellido,
                'correo_institucional': p.correo_institucional,
                'rol': p.rol,
                'es_vocero': p.es_vocero,
            }

        mesas, sin_mesa_objs = agrupar_por_mesa(participantes)
        sin_mesa = [_resumen_participante(p) for p in sin_mesa_objs]

        data_mesas = []
        for numero_mesa in sorted(mesas.keys()):
            integrantes = mesas[numero_mesa]
            vocero = next((p for p in integrantes if p.es_vocero), None)
            data_mesas.append({
                'mesa': numero_mesa,
                'total_participantes': len(integrantes),
                'vocero': _resumen_participante(vocero) if vocero else None,
                'participantes': [_resumen_participante(p) for p in integrantes],
            })

        return Response(
            {
                'jornada_id': jornada_id,
                'total_mesas': len(data_mesas),
                'mesas': data_mesas,
                'sin_mesa_asignada': sin_mesa,
            },
            status=status.HTTP_200_OK,
        )


class _ReporteExcelJornadaViewBase(APIView):
    """Base común de los dos EP de descarga de Excel — solo cambia qué función de
    `analitica/reporte_excel.py` arma el workbook. Ambos son 100% determinísticos, sin IA, y no
    filtran por `momento.activo`: funcionan igual con la jornada en curso o ya cerrada."""
    permission_classes = [IsAdminUser]
    constructor_respuesta = None  # se define en cada subclase

    def get(self, request):
        from jornadas.models import Jornada

        jornada_id = request.query_params.get('jornada')
        if not jornada_id or not jornada_id.isdigit():
            return Response(
                {'detail': 'Debes indicar ?jornada=<id>.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            jornada = Jornada.objects.get(pk=int(jornada_id))
        except Jornada.DoesNotExist:
            return Response({'detail': 'No existe una jornada con ese id.'}, status=status.HTTP_404_NOT_FOUND)
        verificar_acceso_jornada(request.user, jornada)

        return self.constructor_respuesta(jornada)


class ReporteExcelPorPreguntaView(_ReporteExcelJornadaViewBase):
    """Descarga el resultado completo de una jornada en un .xlsx con una hoja por PREGUNTA:
    Resumen, Índice, Participantes, Mesas, y una hoja por cada pregunta con su caracterización
    (fórmulas, no cifras pegadas) y el detalle de cada respuesta."""
    constructor_respuesta = staticmethod(construir_excel_response_por_pregunta)


class ReporteExcelPorMomentoView(_ReporteExcelJornadaViewBase):
    """Descarga el resultado completo de una jornada en un .xlsx con una hoja por MOMENTO:
    Resumen, Índice, Participantes, Mesas, y una hoja por cada momento con TODAS sus preguntas
    apiladas (cada una con su caracterización vía fórmulas y el detalle de cada respuesta)."""
    constructor_respuesta = staticmethod(construir_excel_response_por_momento)
