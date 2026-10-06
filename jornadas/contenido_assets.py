"""Lo que un análisis lee de un `JornadaAsset` adjunto (HU-101): siempre TEXTO.

- Documento .docx/.pdf con texto seleccionable → el texto extraído (`lectura_documentos`, el mismo
  lector de las extracciones, que respeta el orden real de párrafos y tablas).
- .txt/.md → el archivo tal cual.
- PDF escaneado → transcripción con visión, página por página.
- Imagen (foto de un papelógrafo, una gráfica, un afiche) → descripción con visión: transcribe todo
  el texto visible y describe lo que muestra, sin interpretar.
- Guía de marca escrita (`system_design` con `texto`) → ese texto.

Por qué texto y no la imagen misma en cada análisis: el contrato del análisis cita evidencia con un
JSON Pointer a un texto y el backend verifica que la cita sea una subcadena literal de él. Una
imagen no se puede citar ni verificar; su descripción sí. Además el análisis manda la entrada como
un JSON que se reenvía idéntico en la reparación (caché de OpenAI): una imagen ahí la encarecería
en cada intento. La lectura se hace una vez, se guarda en `contenido_texto` y se reutiliza.
"""
import base64
import io
import logging
import os

from django.db import close_old_connections

from . import lectura_documentos
from .models import JornadaAsset

logger = logging.getLogger(__name__)

MODELO_VISION = os.environ.get(
    'OPENAI_MODEL_LECTURA_ADJUNTOS', os.environ.get('OPENAI_MODEL_TRANSCRIPCION', 'gpt-6-luna'),
)
TIMEOUT_SEGUNDOS = int(os.environ.get('KUNSAMU_LECTURA_ADJUNTOS_TIMEOUT', '600'))
MAX_TOKENS_SALIDA = int(os.environ.get('KUNSAMU_LECTURA_ADJUNTOS_MAX_TOKENS', '16000'))
# Lado mayor con que se manda una imagen al modelo: más no mejora la lectura y sí el costo.
LADO_MAXIMO_IMAGEN = 2048

EXTENSIONES_TEXTO_PLANO = ('txt', 'md')

PROMPT_IMAGEN = (
    'Vas a leer una imagen que un equipo adjuntó como insumo para analizar una jornada '
    'participativa universitaria. Tu salida reemplaza a la imagen: quien la lea no la va a ver.\n\n'
    '1. Transcribe LITERALMENTE todo el texto visible (títulos, notas adhesivas, rótulos, tablas, '
    'cifras), en el orden en que se lee, conservando la ortografía original. Si una parte es '
    'ilegible, escribe [ilegible].\n'
    '2. Si hay una gráfica o una tabla, da sus valores tal como aparecen.\n'
    '3. Después, en un párrafo aparte que empiece con «Descripción:», describe lo que muestra la '
    'imagen (qué es, cómo está organizada) sin interpretarla ni sacar conclusiones.\n\n'
    'Responde solo con texto plano, sin markdown ni comentarios sobre la tarea.'
)
PROMPT_PDF_ESCANEADO = (
    'Estas son las páginas de un documento escaneado que un equipo adjuntó como insumo para '
    'analizar una jornada participativa universitaria. Transcríbelo LITERALMENTE, página por '
    'página, en el orden de lectura y conservando la ortografía original. Las tablas van como '
    'filas `celda | celda | celda`. Si una parte es ilegible, escribe [ilegible]. Responde solo con '
    'el texto transcrito, sin comentarios.'
)


class ErrorLecturaAsset(Exception):
    pass


def _extension(asset):
    nombre = asset.nombre_archivo_original or asset.archivo.name or ''
    return nombre.rsplit('.', 1)[-1].lower() if '.' in nombre else ''


def _imagen_como_data_url(asset):
    """La imagen normalizada (RGB, lado mayor ≤ LADO_MAXIMO_IMAGEN) como data URL PNG/JPEG. El
    formato se detecta por los bytes, no por la extensión."""
    from PIL import Image

    asset.archivo.open('rb')
    try:
        imagen = Image.open(io.BytesIO(asset.archivo.read()))
        imagen.load()
    except Exception as exc:  # noqa: BLE001
        raise ErrorLecturaAsset(f'No se pudo abrir la imagen: {exc}') from exc
    finally:
        asset.archivo.close()
    imagen.thumbnail((LADO_MAXIMO_IMAGEN, LADO_MAXIMO_IMAGEN))
    salida = io.BytesIO()
    if imagen.mode in ('RGBA', 'LA', 'P'):
        imagen.convert('RGBA').save(salida, format='PNG')
        mime = 'image/png'
    else:
        imagen.convert('RGB').save(salida, format='JPEG', quality=90)
        mime = 'image/jpeg'
    return f'data:{mime};base64,{base64.b64encode(salida.getvalue()).decode("ascii")}'


def _leer_con_vision(prompt, data_urls):
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise ErrorLecturaAsset('OPENAI_API_KEY no está configurada en el entorno del servidor (.env).')
    from auditoria.openai_cliente import cliente_openai

    contenido = [{'type': 'text', 'text': prompt}] + [
        {'type': 'image_url', 'image_url': {'url': url, 'detail': 'high'}} for url in data_urls
    ]
    cliente = cliente_openai('lectura_adjunto', api_key=api_key, timeout=TIMEOUT_SEGUNDOS)
    try:
        respuesta = cliente.chat.completions.create(
            model=MODELO_VISION, messages=[{'role': 'user', 'content': contenido}],
            max_completion_tokens=MAX_TOKENS_SALIDA,
        )
    except Exception as exc:  # noqa: BLE001
        raise ErrorLecturaAsset(f'Falló la lectura con visión: {exc}') from exc
    eleccion = respuesta.choices[0]
    if eleccion.finish_reason == 'length':
        raise ErrorLecturaAsset(
            f'La lectura con visión se truncó por el tope de {MAX_TOKENS_SALIDA} tokens de salida.'
        )
    texto = (eleccion.message.content or '').strip()
    if not texto:
        raise ErrorLecturaAsset('El modelo de visión no devolvió texto.')
    return texto


def leer_contenido(asset):
    """`(texto, metodo)` del asset. Lanza `ErrorLecturaAsset` con un motivo legible."""
    if not asset.archivo:
        if asset.texto:
            return asset.texto, JornadaAsset.METODO_TEXTO_ESCRITO
        raise ErrorLecturaAsset('El asset no tiene archivo ni texto.')

    extension = _extension(asset)
    if extension in EXTENSIONES_TEXTO_PLANO:
        asset.archivo.open('rb')
        try:
            return asset.archivo.read().decode('utf-8', errors='replace'), JornadaAsset.METODO_TEXTO
        finally:
            asset.archivo.close()
    if extension in ('pdf', 'docx'):
        asset.archivo.open('rb')
        try:
            texto, imagenes = lectura_documentos.leer_documento(asset.archivo, asset.nombre_archivo_original or asset.archivo.name)
        except Exception as exc:  # noqa: BLE001
            raise ErrorLecturaAsset(f'No se pudo leer el documento: {exc}') from exc
        finally:
            asset.archivo.close()
        if texto is not None:
            if not texto.strip():
                raise ErrorLecturaAsset('El documento no tiene texto.')
            return texto, JornadaAsset.METODO_TEXTO
        urls = [f'data:image/png;base64,{b64}' for b64 in imagenes or []]
        return _leer_con_vision(PROMPT_PDF_ESCANEADO, urls), JornadaAsset.METODO_VISION
    return _leer_con_vision(PROMPT_IMAGEN, [_imagen_como_data_url(asset)]), JornadaAsset.METODO_VISION


def asegurar_contenido(asset, forzar=False):
    """El `contenido_texto` del asset, leyéndolo si todavía no está (o si `forzar`). Deja el estado
    guardado en cualquier caso; si falla, lanza `ErrorLecturaAsset`."""
    if asset.contenido_estado == JornadaAsset.CONTENIDO_LISTO and asset.contenido_texto and not forzar:
        return asset.contenido_texto
    asset.contenido_estado = JornadaAsset.CONTENIDO_LEYENDO
    asset.save(update_fields=['contenido_estado'])
    try:
        texto, metodo = leer_contenido(asset)
    except ErrorLecturaAsset as exc:
        asset.contenido_estado = JornadaAsset.CONTENIDO_ERROR
        asset.contenido_error = str(exc)[:2000]
        asset.save(update_fields=['contenido_estado', 'contenido_error'])
        raise
    except Exception as exc:  # noqa: BLE001 — cualquier otra falla queda igual de explicada
        asset.contenido_estado = JornadaAsset.CONTENIDO_ERROR
        asset.contenido_error = f'Error inesperado leyendo el asset: {exc}'[:2000]
        asset.save(update_fields=['contenido_estado', 'contenido_error'])
        raise ErrorLecturaAsset(asset.contenido_error) from exc
    asset.contenido_texto = texto
    asset.contenido_metodo = metodo
    asset.contenido_estado = JornadaAsset.CONTENIDO_LISTO
    asset.contenido_error = ''
    asset.save(update_fields=['contenido_texto', 'contenido_metodo', 'contenido_estado', 'contenido_error'])
    return texto


def leer_en_segundo_plano(asset_ids, forzar=False):
    """Para un hilo: lee los assets indicados uno tras otro. Nunca lanza."""
    from auditoria.openai_cliente import contexto_llamada

    close_old_connections()
    try:
        for asset in JornadaAsset.objects.filter(id__in=asset_ids).select_related('jornada'):
            try:
                with contexto_llamada(jornada=asset.jornada, usuario=asset.subido_por):
                    asegurar_contenido(asset, forzar=forzar)
            except Exception:  # noqa: BLE001 — el motivo ya quedó en el asset
                logger.info('No se pudo leer el asset %s', asset.id, exc_info=True)
    finally:
        close_old_connections()
