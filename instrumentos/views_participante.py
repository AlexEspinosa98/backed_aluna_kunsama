import threading
from collections import defaultdict

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from jornadas import emparejamiento

from .docx_aplicacion import respuesta_docx_http
from .extraccion_ia_openai import procesar_extraccion_instrumento
from .models import (
    AplicacionInstrumento, ExtraccionInstrumento, Instrumento, PreguntaInstrumento,
    PreregistroInstrumento, RespuestaInstrumento,
)
from .serializers import ExtraccionInstrumentoSerializer
from .permissions import EsPreregistradoDeInstrumento, EsUsuarioDelSistema
from .serializers_participante import (
    CargarArchivoInstrumentoSerializer, InstrumentoAsignadoSerializer,
    InstrumentoDetalleParticipanteSerializer, RespuestaInstrumentoEnvioSerializer,
    RespuestaInstrumentoPublicaSerializer,
)


class InstrumentoListaAsignadosView(generics.ListAPIView):
    """Instrumentos donde el usuario autenticado tiene PreregistroInstrumento — a diferencia de
    GET /api/jornadas/ (público), acá no hay autorregistro: si no aparece en la lista es porque
    ningún encargado lo preregistró."""
    serializer_class = InstrumentoAsignadoSerializer
    permission_classes = [EsUsuarioDelSistema]

    def get_queryset(self):
        preregistros = PreregistroInstrumento.objects.filter(
            usuario=self.request.user, instrumento__activo=True
        ).select_related('instrumento', 'aplicacion')
        instrumentos = []
        for preregistro in preregistros:
            instrumento = preregistro.instrumento
            instrumento._preregistro_actual = preregistro
            instrumentos.append(instrumento)
        return instrumentos


class InstrumentoDetalleParticipanteView(generics.RetrieveAPIView):
    serializer_class = InstrumentoDetalleParticipanteSerializer
    permission_classes = [EsPreregistradoDeInstrumento]
    lookup_field = 'slug'
    lookup_url_kwarg = 'instrumento_slug'
    queryset = Instrumento.objects.filter(activo=True)

    def retrieve(self, request, *args, **kwargs):
        instrumento = self.get_object()
        preregistro = get_object_or_404(
            PreregistroInstrumento.objects.select_related('aplicacion'),
            instrumento=instrumento, usuario=request.user,
        )
        context = self.get_serializer_context()
        context['preregistro'] = preregistro
        serializer = self.get_serializer(instrumento, context=context)
        return Response(serializer.data)


def _validar_entrada_instrumento(pregunta, item):
    fila = item.get('fila')
    columna = item.get('columna')
    opciones = item.get('opciones', [])
    texto_libre = item.get('texto_libre', '')

    if opciones and any(o.pregunta_id != pregunta.id for o in opciones):
        raise ValidationError(f'Una opción enviada no pertenece a la pregunta {pregunta.id}.')

    if pregunta.tipo == PreguntaInstrumento.TIPO_MATRIZ:
        if fila is None or columna is None:
            raise ValidationError(
                f'La pregunta {pregunta.id} es de tipo matriz: cada respuesta debe indicar fila y columna.'
            )
        if fila.pregunta_id != pregunta.id or columna.pregunta_id != pregunta.id:
            raise ValidationError(f'La fila/columna enviada no pertenece a la pregunta {pregunta.id}.')
        if opciones:
            raise ValidationError(f'La pregunta {pregunta.id} no acepta opciones.')
        return

    if fila is not None or columna is not None:
        raise ValidationError(f'La pregunta {pregunta.id} no es de tipo matriz, no acepta fila/columna.')

    if pregunta.tipo == PreguntaInstrumento.TIPO_ABIERTA:
        if opciones:
            raise ValidationError(f'La pregunta {pregunta.id} es abierta, no acepta opciones.')
    else:
        if texto_libre.strip():
            raise ValidationError(f'La pregunta {pregunta.id} no acepta texto libre.')
        if pregunta.tipo == PreguntaInstrumento.TIPO_UNICA and len(opciones) > 1:
            raise ValidationError(f'La pregunta {pregunta.id} solo acepta una opción.')


def _preguntas_obligatorias_faltantes(preguntas_obligatorias, entradas_por_pregunta):
    faltantes = []
    for pregunta in preguntas_obligatorias:
        items = entradas_por_pregunta.get(pregunta.id, [])
        if pregunta.tipo == PreguntaInstrumento.TIPO_MATRIZ:
            requeridas = {
                (f, c) for f in pregunta.filas.values_list('id', flat=True)
                for c in pregunta.columnas.values_list('id', flat=True)
            }
            respondidas = {
                (i['fila'].id, i['columna'].id) for i in items if i.get('texto_libre', '').strip()
            }
            if not requeridas.issubset(respondidas):
                faltantes.append(pregunta.id)
        elif not items:
            faltantes.append(pregunta.id)
    return faltantes


class InstrumentoRespuestasView(APIView):
    """Envío único de todas las respuestas (mismo estilo que RespuestasMomentoView en
    participantes/views.py: se puede volver a llamar mientras no esté 'aceptado', cada llamada
    sobreescribe y reinicia el flujo de revisión a 'pendiente' — así es como se modela un reenvío
    tras un rechazo)."""
    permission_classes = [EsPreregistradoDeInstrumento]

    @extend_schema(
        request=RespuestaInstrumentoEnvioSerializer,
        responses=RespuestaInstrumentoPublicaSerializer(many=True),
    )
    def post(self, request, instrumento_slug):
        instrumento = get_object_or_404(Instrumento, slug=instrumento_slug, activo=True)
        preregistro = get_object_or_404(
            PreregistroInstrumento, instrumento=instrumento, usuario=request.user
        )

        aplicacion, _ = AplicacionInstrumento.objects.get_or_create(preregistro=preregistro)
        if aplicacion.enviado_en and aplicacion.estado == AplicacionInstrumento.ESTADO_ACEPTADO:
            raise PermissionDenied('Esta aplicación ya fue aceptada, no se puede modificar.')

        entrada = RespuestaInstrumentoEnvioSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        preguntas_validas = {
            p.id: p for p in PreguntaInstrumento.objects.filter(
                seccion__instrumento=instrumento, seccion__activa=True, activa=True,
            )
        }

        entradas_por_pregunta = defaultdict(list)
        for item in entrada.validated_data['respuestas']:
            pregunta = item['pregunta']
            if pregunta.id not in preguntas_validas:
                raise ValidationError(f'La pregunta {pregunta.id} no pertenece a este instrumento.')
            _validar_entrada_instrumento(pregunta, item)
            entradas_por_pregunta[pregunta.id].append(item)

        preguntas_obligatorias = [p for p in preguntas_validas.values() if p.obligatoria]
        faltantes = _preguntas_obligatorias_faltantes(preguntas_obligatorias, entradas_por_pregunta)
        if faltantes:
            raise ValidationError({'faltantes': f'Preguntas obligatorias sin responder: {faltantes}'})

        respuestas_guardadas = []
        for items in entradas_por_pregunta.values():
            for item in items:
                respuesta, _ = RespuestaInstrumento.objects.update_or_create(
                    aplicacion=aplicacion,
                    pregunta=item['pregunta'],
                    fila=item.get('fila'),
                    columna=item.get('columna'),
                    defaults={'texto_libre': item.get('texto_libre', '')},
                )
                respuesta.opciones.set(item.get('opciones', []))
                respuestas_guardadas.append(respuesta)

        aplicacion.estado = AplicacionInstrumento.ESTADO_PENDIENTE
        aplicacion.enviado_en = timezone.now()
        aplicacion.revisado_por = None
        aplicacion.revisado_en = None
        aplicacion.save()

        return Response(
            RespuestaInstrumentoPublicaSerializer(respuestas_guardadas, many=True).data,
            status=status.HTTP_200_OK,
        )


class InstrumentoDescargarPropioView(APIView):
    permission_classes = [EsPreregistradoDeInstrumento]

    def get(self, request, instrumento_slug):
        instrumento = get_object_or_404(Instrumento, slug=instrumento_slug)
        preregistro = get_object_or_404(
            PreregistroInstrumento.objects.select_related('aplicacion'),
            instrumento=instrumento, usuario=request.user,
        )
        aplicacion = getattr(preregistro, 'aplicacion', None)
        if aplicacion is None or aplicacion.enviado_en is None:
            raise NotFound('Todavía no has enviado tus respuestas para este instrumento.')
        return respuesta_docx_http(aplicacion)


class InstrumentoCargarArchivoView(APIView):
    """El propio usuario sube su documento ya diligenciado y la IA lo transcribe (HU-56).

    Hasta ahora esto era solo de admin (ExtraccionInstrumentoViewSet). La diferencia de fondo con
    esa vista no es el permiso sino **de quién es el documento**: acá el dueño es siempre quien
    sube (`usuario=request.user`), no un dato del request. Alguien no puede subir a nombre de
    otro, así que tampoco hay responsable que emparejar ni usuarios que dar de alta.

    Se habilita instrumento por instrumento con `Instrumento.permite_carga_archivo` — apagado, un
    usuario preregistrado igual recibe 403, porque cada carga cuesta una llamada a OpenAI y deja
    una AplicacionInstrumento en revisión.

    El resultado NO se acepta solo: como cualquier extracción, la aplicación queda en estado
    pendiente con generado_por_ia=True, para que un encargado la revise."""
    permission_classes = [EsPreregistradoDeInstrumento]

    @extend_schema(
        request=CargarArchivoInstrumentoSerializer,
        responses=ExtraccionInstrumentoSerializer,
    )
    def post(self, request, instrumento_slug):
        instrumento = get_object_or_404(Instrumento, slug=instrumento_slug, activo=True)
        if not instrumento.permite_carga_archivo:
            raise PermissionDenied(
                'Este instrumento no tiene habilitada la carga de documentos. Diligéncialo en '
                'línea o pídele a un administrador que la habilite.'
            )

        entrada = CargarArchivoInstrumentoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        archivo = entrada.validated_data['archivo']

        extraccion = ExtraccionInstrumento.objects.create(
            instrumento=instrumento,
            usuario=request.user,
            archivo=archivo,
            nombre_archivo_original=archivo.name,
            solicitado_por=request.user,
            responsable_estado=emparejamiento.ESTADO_NO_BUSCADO,
        )
        threading.Thread(
            target=procesar_extraccion_instrumento, args=(extraccion.id,), daemon=True,
        ).start()

        return Response(
            ExtraccionInstrumentoSerializer(extraccion).data, status=status.HTTP_201_CREATED,
        )


class MisExtraccionesInstrumentoView(generics.ListAPIView):
    """Las cargas que hizo el propio usuario en este instrumento — para que el FE pueda mostrar
    "tu documento se está procesando / ya quedó / falló" después de subirlo, sin tener que pegarle
    al endpoint de admin (al que no tiene acceso)."""
    serializer_class = ExtraccionInstrumentoSerializer
    permission_classes = [EsPreregistradoDeInstrumento]

    def get_queryset(self):
        return ExtraccionInstrumento.objects.filter(
            instrumento__slug=self.kwargs['instrumento_slug'], usuario=self.request.user,
        )
