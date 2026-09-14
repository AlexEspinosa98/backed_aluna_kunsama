import threading
from datetime import timedelta

from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from jornadas.scoping import verificar_acceso_jornada

from .informe_ia import generar_informe_transcripcion
from .models import FragmentoTranscripcion, InformeTranscripcion, SesionTranscripcion
from .pdf_informe import construir_pdf_response
from .presentacion import generar_presentacion_html
from .scoping import es_dependencia, filtrar_por_encargado, sesiones_visibles, verificar_acceso_sesion
from .serializers import (
    FragmentoIngestaSerializer, FragmentoTranscripcionSerializer, InformeTranscripcionCrearSerializer,
    InformeTranscripcionSerializer, SesionTranscripcionAdminSerializer,
)

# Igual que analitica/admin_views.py: una llamada a OpenAI es independiente por sesión (no
# comparte modelo local ni pool), así que el guard de "ya hay uno en proceso" es por sesión, no
# global — distintas sesiones sí pueden generar su informe en paralelo.
# El mapa-reducción de una sesión larga (hasta 4h, varios tramos en paralelo + síntesis final)
# tarda más que un AnalisisJornadaIA normal — umbral de huérfano un poco mayor.
UMBRAL_HUERFANO_INFORME = timedelta(minutes=15)
UMBRAL_HUERFANO_PRESENTACION = timedelta(minutes=10)


class SesionTranscripcionAdminViewSet(viewsets.ModelViewSet):
    serializer_class = SesionTranscripcionAdminSerializer
    permission_classes = [IsAdminUser]
    lookup_field = 'slug'

    def get_queryset(self):
        queryset = sesiones_visibles(self.request.user)
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        return queryset

    def perform_create(self, serializer):
        if not es_dependencia(self.request.user):
            serializer.save(creado_por=self.request.user)
            return

        jornada = serializer.validated_data.get('jornada')
        if jornada is not None:
            verificar_acceso_jornada(self.request.user, jornada)
            serializer.save(creado_por=self.request.user)
        else:
            serializer.save(creado_por=self.request.user, encargados=[self.request.user])

    def perform_update(self, serializer):
        if not es_dependencia(self.request.user):
            serializer.save()
            return

        instancia = serializer.instance
        jornada_anterior = instancia.jornada
        jornada_nueva = serializer.validated_data.get('jornada', jornada_anterior)

        if jornada_nueva is not None:
            verificar_acceso_jornada(self.request.user, jornada_nueva)
            serializer.save()
        elif jornada_anterior is not None:
            serializer.save(encargados=[self.request.user])
        else:
            serializer.save(encargados=list(instancia.encargados.all()))

    @action(detail=True, methods=['post'], url_path='fragmentos')
    def fragmentos(self, request, slug=None):
        """Ingesta en tiempo real desde el front: update_or_create por (sesion, secuencia), así
        que reenviar el mismo fragmento (reintento de red) nunca lo duplica ni depende de en qué
        orden llegaron los paquetes."""
        sesion = self.get_object()
        if sesion.estado != SesionTranscripcion.EN_CURSO:
            return Response(
                {'detail': 'Esta sesión ya está cerrada — no se aceptan más fragmentos.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        entrada = FragmentoIngestaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        guardados = []
        for item in entrada.validated_data['fragmentos']:
            fragmento, _ = FragmentoTranscripcion.objects.update_or_create(
                sesion=sesion, secuencia=item['secuencia'],
                defaults={
                    'texto': item['texto'],
                    'hablante': item.get('hablante', ''),
                    'inicio_ms': item.get('inicio_ms'),
                    'fin_ms': item.get('fin_ms'),
                },
            )
            guardados.append(fragmento)

        return Response(
            FragmentoTranscripcionSerializer(guardados, many=True).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='cerrar')
    def cerrar(self, request, slug=None):
        sesion = self.get_object()
        if sesion.estado == SesionTranscripcion.CERRADA:
            return Response(
                {'detail': 'Esta sesión ya está cerrada.'}, status=status.HTTP_400_BAD_REQUEST,
            )
        sesion.estado = SesionTranscripcion.CERRADA
        sesion.cerrada_en = timezone.now()
        sesion.save(update_fields=['estado', 'cerrada_en'])
        return Response(SesionTranscripcionAdminSerializer(sesion, context={'request': request}).data)

    @action(detail=True, methods=['get'], url_path='transcripcion')
    def transcripcion(self, request, slug=None):
        """Texto completo reconstruido — sirve tanto para ver la transcripción en vivo mientras
        la sesión está en curso, como para revisarla antes de generar el informe."""
        sesion = self.get_object()
        lista = list(sesion.fragmentos.order_by('secuencia'))
        texto_completo = '\n'.join(
            (f'[{f.hablante}] {f.texto}' if f.hablante else f.texto) for f in lista
        )
        return Response({
            'sesion': sesion.slug,
            'estado': sesion.estado,
            'texto_completo': texto_completo,
            'fragmentos': FragmentoTranscripcionSerializer(lista, many=True).data,
        })


class FragmentoTranscripcionAdminViewSet(
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Solo listar/editar/borrar — la ingesta en tiempo real va por
    SesionTranscripcionAdminViewSet.fragmentos (upsert idempotente), no por acá. Editar/borrar un
    fragmento puntual solo se habilita una vez la sesión está `cerrada` (revisión antes de
    generar el informe) — mientras está en curso, el streaming en tiempo real es la única vía."""
    serializer_class = FragmentoTranscripcionSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = filtrar_por_encargado(
            FragmentoTranscripcion.objects.select_related('sesion'), self.request.user
        )
        sesion_id = self.request.query_params.get('sesion')
        if sesion_id:
            queryset = queryset.filter(sesion_id=sesion_id)
        return queryset

    def _validar_editable(self, fragmento):
        if fragmento.sesion.estado != SesionTranscripcion.CERRADA:
            raise ValidationError(
                'Solo se pueden editar o eliminar fragmentos de una sesión ya cerrada.'
            )

    def perform_update(self, serializer):
        self._validar_editable(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._validar_editable(instance)
        instance.delete()


class InformeTranscripcionAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = InformeTranscripcion.objects.select_related('sesion')
        queryset = filtrar_por_encargado(queryset, self.request.user, 'sesion')
        sesion_id = self.request.query_params.get('sesion')
        if sesion_id:
            queryset = queryset.filter(sesion_id=sesion_id)
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return InformeTranscripcionCrearSerializer
        return InformeTranscripcionSerializer

    def create(self, request, *args, **kwargs):
        entrada = InformeTranscripcionCrearSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        sesion = entrada.validated_data['sesion']
        verificar_acceso_sesion(request.user, sesion)

        if sesion.estado != SesionTranscripcion.CERRADA:
            return Response(
                {'detail': 'La sesión debe estar cerrada antes de poder generar su informe.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Auto-sanación, mismo espíritu que AnalisisJornadaIAViewSet.create en analitica.
        InformeTranscripcion.objects.filter(
            sesion=sesion,
            estado__in=[InformeTranscripcion.ESTADO_PENDIENTE, InformeTranscripcion.ESTADO_PROCESANDO],
            actualizado_en__lt=timezone.now() - UMBRAL_HUERFANO_INFORME,
        ).update(
            estado=InformeTranscripcion.ESTADO_ERROR,
            error_mensaje='El informe quedó procesando más de 15 minutos sin completarse '
                          '(probablemente el worker se reinició o falló) y se marcó como error '
                          'automáticamente.',
        )

        if InformeTranscripcion.objects.filter(
            sesion=sesion,
            estado__in=[InformeTranscripcion.ESTADO_PENDIENTE, InformeTranscripcion.ESTADO_PROCESANDO],
        ).exists():
            return Response(
                {'detail': 'Ya hay un informe con IA en proceso para esta sesión — espera a que '
                           'termine (o falle) antes de pedir otro.'},
                status=status.HTTP_409_CONFLICT,
            )

        informe = entrada.save(solicitado_por=request.user)
        threading.Thread(target=generar_informe_transcripcion, args=(informe.id,), daemon=True).start()

        salida = InformeTranscripcionSerializer(informe)
        headers = self.get_success_headers(salida.data)
        return Response(salida.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=['post'], url_path='generar-presentacion')
    def generar_presentacion(self, request, pk=None):
        informe = self.get_object()
        if informe.estado != InformeTranscripcion.ESTADO_COMPLETO:
            return Response(
                {'detail': 'El informe todavía no está completo — la presentación se genera a '
                           'partir de datos ya calculados.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (
            informe.presentacion_estado == InformeTranscripcion.PRESENTACION_ESTADO_PROCESANDO
            and informe.actualizado_en < timezone.now() - UMBRAL_HUERFANO_PRESENTACION
        ):
            informe.presentacion_estado = InformeTranscripcion.PRESENTACION_ESTADO_ERROR
            informe.presentacion_error = (
                'La presentación quedó procesando más de 10 minutos sin completarse '
                '(probablemente el worker se reinició o falló) y se marcó como error '
                'automáticamente.'
            )
            informe.save(update_fields=['presentacion_estado', 'presentacion_error'])
        if informe.presentacion_estado == InformeTranscripcion.PRESENTACION_ESTADO_PROCESANDO:
            return Response(
                {'detail': 'Ya hay una presentación en proceso para este informe.'},
                status=status.HTTP_409_CONFLICT,
            )

        threading.Thread(target=generar_presentacion_html, args=(informe.id,), daemon=True).start()

        return Response(InformeTranscripcionSerializer(informe).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf(self, request, pk=None):
        informe = self.get_object()
        if informe.estado != InformeTranscripcion.ESTADO_COMPLETO:
            return Response(
                {'detail': 'El informe todavía no está completo.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return construir_pdf_response(informe)
