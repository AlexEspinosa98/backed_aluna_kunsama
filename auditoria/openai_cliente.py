"""Cliente de OpenAI que registra cada petición completa en `LlamadaOpenAI` (HU-95).

Uso en un módulo que llama a OpenAI — en vez de `OpenAI(api_key=...)`:

    from auditoria.openai_cliente import cliente_openai, hilo_con_contexto
    client = cliente_openai('extraccion_momento', api_key=api_key)
    hilo = hilo_con_contexto(_run)          # en vez de threading.Thread(target=_run, daemon=True)

y en el flujo que dispara la llamada, una vez, para que quede asociada a su jornada y su registro:

    with contexto_llamada(origen=extraccion, jornada=..., usuario=...):
        ...

**Por qué en la capa HTTP y no alrededor de `chat.completions.create`.** El transporte ve el
cuerpo exacto que sale (los mensajes, los prompts, las imágenes en base64, cada parámetro) y la
respuesta exacta que vuelve, para cualquier endpoint (chat, imágenes, lo que se agregue), sin
reconstruir nada a mano. Y ve también lo que el SDK hace por su cuenta: cada reintento automático
es una petición HTTP más y queda como una fila más.

**Por qué un contextvar.** Las llamadas salen de funciones profundas (`llamar_openai_estructurado`)
que no saben de qué jornada ni de qué análisis vienen; quien sí lo sabe es el flujo de arriba. El
contexto se fija una vez ahí y viaja solo hasta el cliente. Los hilos NO heredan contextvars en
Python, por eso los hilos internos se crean con `hilo_con_contexto` y las tareas de un pool con
`con_contexto`.

**Nunca rompe la llamada.** Si guardar el registro falla, se escribe un warning en el log y la
llamada sigue como si nada: auditar no puede costar un análisis.
"""
import contextvars
import json
import logging
import re
import threading
import time
from contextlib import contextmanager

try:
    # openai >= 3 trae su propia copia renombrada de httpx y sus tipos no se mezclan con los del
    # httpx normal: el transporte tiene que ser de la misma librería que usa el SDK.
    import httpx2 as httpx
except ImportError:  # pragma: no cover — SDK anterior
    import httpx

logger = logging.getLogger(__name__)

_contexto = contextvars.ContextVar('auditoria_openai_contexto', default=None)

# Encabezados que nunca se guardan: la API key viaja en Authorization.
_HEADERS_EXCLUIDOS = {'authorization', 'cookie', 'set-cookie', 'openai-organization', 'openai-project'}
# La parte `model` de un multipart: su línea de encabezado, otros encabezados opcionales (líneas no
# vacías), la línea en blanco y el valor. `[^\r\n]+` impide saltar a la parte siguiente.
_MODELO_MULTIPART = re.compile(rb'name="model"[^\r\n]*\r\n(?:[^\r\n]+\r\n)*?\r\n([^\r\n]*)')


# --- contexto -----------------------------------------------------------------------------------
def _contexto_de(origen=None, jornada=None, momento=None, usuario=None):
    datos = {}
    if origen is not None:
        from django.contrib.contenttypes.models import ContentType

        datos['origen_tipo_id'] = ContentType.objects.get_for_model(type(origen)).id
        datos['origen_id'] = str(origen.pk)
        # Lo que el propio registro ya dice, si nadie lo indicó explícito.
        if jornada is None:
            jornada = getattr(origen, 'jornada_id', None)
        if momento is None:
            momento = getattr(origen, 'momento_id', None)
        if usuario is None:
            usuario = getattr(origen, 'solicitado_por_id', None)
    momento_id = getattr(momento, 'pk', momento)
    jornada_id = getattr(jornada, 'pk', jornada)
    if jornada_id is None and momento_id is not None:
        from jornadas.models import Momento

        jornada_id = Momento.objects.filter(pk=momento_id).values_list('jornada_id', flat=True).first()
    for clave, valor in (('jornada_id', jornada_id), ('momento_id', momento_id),
                         ('usuario_id', getattr(usuario, 'pk', usuario))):
        if valor is not None:
            datos[clave] = valor
    return datos


@contextmanager
def contexto_llamada(origen=None, jornada=None, momento=None, usuario=None):
    """Asocia toda llamada a OpenAI hecha dentro del bloque (incluidos los hilos creados con
    `hilo_con_contexto`/`con_contexto`) con el registro que la origina. `jornada`, `momento` y
    `usuario` se deducen de `origen` si tiene `jornada_id`/`momento_id`/`solicitado_por_id`.
    Nunca lanza: si no puede armar el contexto, las llamadas se registran igual, sin relaciones."""
    try:
        datos = {**(_contexto.get() or {}), **_contexto_de(origen, jornada, momento, usuario)}
    except Exception:  # noqa: BLE001
        logger.warning('No se pudo armar el contexto de auditoría de OpenAI', exc_info=True)
        datos = _contexto.get() or {}
    token = _contexto.set(datos)
    try:
        yield
    finally:
        _contexto.reset(token)


def auditar_llamadas(modelo, jornada=None, momento=None):
    """Decorador para las funciones de segundo plano que reciben el id de un registro
    (`procesar_extraccion_momento(extraccion_id)`, `analizar_jornada_ia(analisis_id)`…): carga ese
    registro y corre la función dentro de `contexto_llamada(origen=registro)`, así toda llamada a
    OpenAI que haga queda asociada a él sin tocar su cuerpo.

    `modelo` es 'app.Modelo'. `jornada`/`momento` son rutas del ORM para cuando el registro no tiene
    `jornada_id`/`momento_id` propios (ej. 'sesion__jornada_id'). Si no se puede cargar el
    registro, la función corre igual — sin relaciones en la auditoría, nunca sin ejecutarse."""
    import functools

    def decorador(funcion):
        @functools.wraps(funcion)
        def envuelta(objeto_id, *args, **kwargs):
            datos = {}
            try:
                from django.apps import apps

                consulta = apps.get_model(modelo).objects.filter(pk=objeto_id)
                datos['origen'] = consulta.first()
                if jornada:
                    datos['jornada'] = consulta.values_list(jornada, flat=True).first()
                if momento:
                    datos['momento'] = consulta.values_list(momento, flat=True).first()
            except Exception:  # noqa: BLE001
                logger.warning('No se pudo cargar %s %s para la auditoría', modelo, objeto_id, exc_info=True)
            with contexto_llamada(**datos):
                return funcion(objeto_id, *args, **kwargs)
        return envuelta
    return decorador


def hilo_con_contexto(target, *args):
    """`threading.Thread(target=..., daemon=True)` que conserva el contexto de auditoría."""
    return threading.Thread(target=contextvars.copy_context().run, args=(target, *args), daemon=True)


def con_contexto(funcion):
    """Envuelve una función para un pool de hilos: cada ejecución corre con una copia del contexto
    de auditoría vigente al envolverla (una copia por ejecución: un mismo `Context` no se puede
    usar en dos hilos a la vez)."""
    contexto = contextvars.copy_context()

    def envuelta(*args, **kwargs):
        return contexto.copy().run(funcion, *args, **kwargs)
    return envuelta


# --- cliente ------------------------------------------------------------------------------------
def cliente_openai(flujo, transporte_base=None, **kwargs):
    """`openai.OpenAI(**kwargs)` con el transporte que registra cada petición bajo `flujo`.
    `transporte_base` existe para los tests (un `httpx.MockTransport`); en producción es el HTTP real."""
    import openai

    transporte = _TransporteRegistrado(
        transporte_base or httpx.HTTPTransport(), flujo, dict(_contexto.get() or {}),
    )
    return openai.OpenAI(http_client=openai.DefaultHttpxClient(transport=transporte), **kwargs)


class _TransporteRegistrado(httpx.BaseTransport):
    def __init__(self, base, flujo, contexto):
        self._base = base
        self._flujo = flujo
        self._contexto = contexto

    def handle_request(self, request):
        from django.utils import timezone

        cuerpo = request.read()
        iniciado_en = timezone.now()
        inicio = time.monotonic()
        try:
            original = self._base.handle_request(request)
            # El cuerpo se lee crudo (tal como llegó, quizá comprimido) y se devuelve al cliente una
            # respuesta nueva con esos mismos bytes: leerlo sobre la original la deja inservible
            # para httpx. Para el registro se decodifica una copia aparte.
            crudo = b''.join(original.stream)
            original.close()
        except Exception as exc:
            self._registrar(request, cuerpo, iniciado_en, inicio, None, b'', exc)
            raise
        respuesta = httpx.Response(
            original.status_code, headers=original.headers, stream=httpx.ByteStream(crudo),
            extensions=original.extensions, request=request,
        )
        try:
            contenido = httpx.Response(
                original.status_code, headers=original.headers, stream=httpx.ByteStream(crudo),
            ).read()
        except Exception:  # noqa: BLE001 — una codificación rara no impide registrar
            contenido = crudo
        self._registrar(request, cuerpo, iniciado_en, inicio, respuesta, contenido, None)
        return respuesta

    def close(self):
        self._base.close()

    def _registrar(self, request, cuerpo, iniciado_en, inicio, respuesta, contenido, error):
        try:
            _guardar(self._flujo, self._contexto, request, cuerpo, iniciado_en, inicio,
                     respuesta, contenido, error)
        except Exception:  # noqa: BLE001 — auditar nunca rompe la llamada
            logger.warning('No se pudo registrar la llamada a OpenAI (%s)', self._flujo, exc_info=True)
        finally:
            _soltar_conexion()


def _headers(headers):
    return {k.lower(): v for k, v in headers.items() if k.lower() not in _HEADERS_EXCLUIDOS}


def _json_o_none(contenido):
    """El cuerpo como JSON, o None si no lo es. PostgreSQL (jsonb) rechaza el carácter nulo
    `\\u0000`, que puede venir en texto extraído de un PDF: se quita antes, o el registro entero
    fallaría y esa llamada quedaría sin auditar."""
    try:
        if isinstance(contenido, bytes):
            contenido = contenido.replace(b'\\u0000', b'')
        return json.loads(contenido)
    except (ValueError, TypeError):
        return None


def _guardar(flujo, contexto, request, cuerpo, iniciado_en, inicio, respuesta, contenido, error):
    from django.utils import timezone

    from .models import LlamadaOpenAI

    duracion_ms = int((time.monotonic() - inicio) * 1000)
    content_type = request.headers.get('content-type', '')
    peticion = _json_o_none(cuerpo) if 'json' in content_type else None
    modelo = ''
    if isinstance(peticion, dict):
        modelo = str(peticion.get('model') or '')
    else:
        encontrado = _MODELO_MULTIPART.search(cuerpo or b'')
        modelo = encontrado.group(1).decode('utf-8', 'replace') if encontrado else ''

    cuerpo_respuesta = _json_o_none(contenido) if contenido else None
    usage = (cuerpo_respuesta or {}).get('usage') if isinstance(cuerpo_respuesta, dict) else None
    usage = usage if isinstance(usage, dict) else {}

    if respuesta is None:
        estado = LlamadaOpenAI.ESTADO_ERROR_RED
    elif respuesta.status_code < 400:
        estado = LlamadaOpenAI.ESTADO_OK
    else:
        estado = LlamadaOpenAI.ESTADO_ERROR_HTTP

    LlamadaOpenAI.objects.create(
        flujo=flujo,
        jornada_id=contexto.get('jornada_id'),
        momento_id=contexto.get('momento_id'),
        origen_tipo_id=contexto.get('origen_tipo_id'),
        origen_id=contexto.get('origen_id', ''),
        usuario_id=contexto.get('usuario_id'),
        metodo=request.method,
        url=str(request.url)[:500],
        endpoint=request.url.path[:120],
        modelo=modelo[:80],
        peticion=peticion,
        peticion_cruda=None if peticion is not None else bytes(cuerpo or b''),
        peticion_content_type=content_type[:200],
        peticion_headers=_headers(request.headers),
        peticion_bytes=len(cuerpo or b''),
        estado=estado,
        status_code=getattr(respuesta, 'status_code', None),
        respuesta=cuerpo_respuesta,
        respuesta_cruda='' if cuerpo_respuesta is not None else (contenido or b'').decode('utf-8', 'replace').replace('\x00', ''),
        respuesta_headers=_headers(respuesta.headers) if respuesta is not None else {},
        respuesta_bytes=len(contenido or b''),
        error=f'{type(error).__name__}: {error}' if error else '',
        request_id=(respuesta.headers.get('x-request-id', '') if respuesta is not None else '')[:120],
        tokens_entrada=usage.get('prompt_tokens', usage.get('input_tokens')),
        tokens_salida=usage.get('completion_tokens', usage.get('output_tokens')),
        tokens_total=usage.get('total_tokens'),
        iniciado_en=iniciado_en,
        finalizado_en=timezone.now(),
        duracion_ms=duracion_ms,
    )


def _soltar_conexion():
    """Los hilos internos que hacen las llamadas no cierran su conexión a la base: la abrió este
    registro, así que la cierra él. Nunca en el hilo principal (el de una petición web) ni dentro
    de una transacción, donde cerrarla rompería lo que está en curso."""
    from django.db import connection

    if threading.current_thread() is not threading.main_thread() and not connection.in_atomic_block:
        connection.close()
