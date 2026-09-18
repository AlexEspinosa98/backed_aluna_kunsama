"""Genera 3 imágenes de infografía para un Reporte ya `completo`, vía el modelo de imágenes de
OpenAI — usa como referencia visual DIRECTA los `JornadaAsset` de la jornada (fotos/logos + el
system design más reciente, ver jornadas/models.py::JornadaAsset) y como contenido
`reporte.analisis` (o, si todavía no existe, el `AnalisisJornadaIA` más reciente de esa jornada).
Mismo patrón de threading+timeout que el resto de módulos de IA del proyecto (ver
analitica/presentacion.py, instrumentos/extraccion_ia_openai.py): nunca lanza excepción hacia
afuera, corre en un hilo de background y deja `estado`/`error_mensaje` listos para que el
frontend haga polling.

`gpt-image-2` (el modelo pedido) y la forma exacta de su respuesta (b64_json vs url) son un
supuesto sin verificar contra la documentación real de OpenAI — quedan aislados acá, detrás de
OPENAI_IMAGE_MODEL y de `_llamar_openai_imagenes`, para que corregirlos sea un cambio de una
función, no de arquitectura.
"""
import base64
import io
import json
import os
import threading
import urllib.request

from django.core.files.base import ContentFile
from django.utils import timezone

from jornadas.models import JornadaAsset

DEFAULT_IMAGE_MODEL = os.environ.get('OPENAI_IMAGE_MODEL', 'gpt-image-2')
GENERATION_TIMEOUT_SECONDS = 300
NUM_IMAGENES = 3
# Formato vertical, el habitual para una infografía pensada para compartirse en redes/impresión.
TAMANO_INFOGRAFIA = '1024x1536'
# Tope de assets tipo 'asset' que se mandan como referencia (+ 1 system_design aparte) — controla
# costo/tiempo de la llamada, igual espíritu que MAX_PAGINAS_IMAGEN en extraccion_ia_openai.py.
MAX_ASSETS_REFERENCIA = 4
# Lado máximo (px) de una imagen de referencia antes de mandarla a la API — evita payloads gigantes.
MAX_LADO_IMAGEN_REFERENCIA = 2048

SYSTEM_PROMPT_PREFIJO = (
    "Diseña una infografía vertical, lista para publicar, que resuma los resultados reales de "
    "una jornada participativa universitaria. Usa EXCLUSIVAMENTE las cifras y hallazgos que se "
    "entregan abajo en JSON — nunca inventes números, porcentajes ni temas que no estén ahí. Si "
    "se adjuntan imágenes de referencia (fotos/logos de la jornada y/o una guía de marca), "
    "respeta su paleta de colores, tipografía y estilo visual real — no uses una paleta genérica "
    "distinta a la de esas imágenes. Composición clara y legible: un título, entre 2 y 4 cifras "
    "clave destacadas, y los hallazgos o temas principales con su dato real al lado. Todo el "
    "texto de la infografía debe estar en español."
)


def _normalizar_imagen(bytes_imagen):
    """Convierte cualquier imagen a PNG RGBA, reescalada si excede MAX_LADO_IMAGEN_REFERENCIA —
    formato consistente para mandar como referencia a la API de imágenes. Devuelve bytes PNG."""
    from PIL import Image

    imagen = Image.open(io.BytesIO(bytes_imagen))
    imagen = imagen.convert('RGBA')
    if max(imagen.size) > MAX_LADO_IMAGEN_REFERENCIA:
        imagen.thumbnail((MAX_LADO_IMAGEN_REFERENCIA, MAX_LADO_IMAGEN_REFERENCIA))
    salida = io.BytesIO()
    imagen.save(salida, format='PNG')
    return salida.getvalue()


def _rasterizar_primera_pagina_pdf(archivo):
    """Primera página de un PDF (el system design puede subirse así) rasterizada a PNG — mismo
    mecanismo que instrumentos/extraccion_ia_openai.py::_extraer_texto_o_imagenes_pdf (PyMuPDF),
    pero solo la portada: es una guía de marca de referencia, no un documento a transcribir."""
    import fitz  # PyMuPDF

    archivo.seek(0)
    documento = fitz.open(stream=archivo.read(), filetype='pdf')
    try:
        pixmap = documento[0].get_pixmap(dpi=150)
        return pixmap.tobytes('png')
    finally:
        documento.close()


def _leer_imagen_referencia(asset):
    """Bytes PNG normalizados de un JornadaAsset, sea imagen o (solo para system_design) PDF."""
    nombre = asset.nombre_archivo_original or asset.archivo.name
    extension = nombre.rsplit('.', 1)[-1].lower() if '.' in nombre else ''

    asset.archivo.open('rb')
    try:
        if extension == 'pdf':
            return _normalizar_imagen(_rasterizar_primera_pagina_pdf(asset.archivo))
        return _normalizar_imagen(asset.archivo.read())
    finally:
        asset.archivo.close()


def _reunir_imagenes_referencia(jornada):
    """Hasta MAX_ASSETS_REFERENCIA assets tipo 'asset' (más recientes primero, ya es el ordering
    por defecto del modelo) + el 'system_design' más reciente, si existe. Un archivo individual
    que falle al leerse/convertirse se omite (no debe tumbar toda la generación por un asset
    puntual corrupto)."""
    imagenes = []
    assets = jornada.assets.filter(tipo=JornadaAsset.TIPO_ASSET)[:MAX_ASSETS_REFERENCIA]
    system_design = jornada.assets.filter(tipo=JornadaAsset.TIPO_SYSTEM_DESIGN).first()
    for asset in list(assets) + ([system_design] if system_design else []):
        try:
            imagenes.append(_leer_imagen_referencia(asset))
        except Exception:  # noqa: BLE001 — un asset ilegible no debe abortar la generación entera
            continue
    return imagenes


def _obtener_datos_analitica(reporte):
    """(datos, error) — nunca lanza excepción. Prefiere `reporte.analisis` (ya calculado, es la
    fuente más completa); si está vacío, cae al `AnalisisJornadaIA` completo más reciente de la
    misma jornada. Si ninguno existe, error controlado."""
    if reporte.analisis:
        return {
            'fuente': 'reporte',
            'jornada': reporte.jornada.nombre,
            'participacion': reporte.analisis.get('participacion'),
            'momentos': reporte.analisis.get('momentos'),
            'sintesis_narrativa': reporte.texto_reporte,
        }, None

    from .models import AnalisisJornadaIA

    analisis_ia = AnalisisJornadaIA.objects.filter(
        jornada=reporte.jornada, estado=AnalisisJornadaIA.ESTADO_COMPLETO,
    ).order_by('-creado_en').first()
    if analisis_ia and analisis_ia.resultado:
        return {
            'fuente': 'analisis_jornada_ia',
            'jornada': reporte.jornada.nombre,
            'resumen_ejecutivo': analisis_ia.resultado.get('resumen_ejecutivo'),
            'hallazgos': analisis_ia.resultado.get('hallazgos'),
        }, None

    return None, (
        'No hay analítica calculada para esta jornada — ni el reporte tiene `analisis`, ni existe '
        'un AnalisisJornadaIA completo. Genera alguno de los dos antes de pedir la infografía.'
    )


def _construir_prompt(datos_analitica):
    return SYSTEM_PROMPT_PREFIJO + '\n\nDATOS REALES (JSON):\n' + json.dumps(
        datos_analitica, ensure_ascii=False, indent=2,
    )


def _llamar_openai_imagenes(prompt, imagenes_referencia_png):
    """Genera NUM_IMAGENES imágenes vía OpenAI — imagen-a-imagen (`images.edit`) si hay imágenes
    de referencia, texto-a-imagen (`images.generate`) si la jornada no tiene ningún asset/system
    design todavía. Devuelve (lista_de_bytes_png_o_None, error) — nunca lanza excepción, mismo
    contrato que el resto de módulos de IA del proyecto."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None, 'OPENAI_API_KEY no está configurada en el entorno del servidor (.env).'

    resultado = {}

    def _run():
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            if imagenes_referencia_png:
                archivos = [
                    (f'referencia-{i}.png', io.BytesIO(png), 'image/png')
                    for i, png in enumerate(imagenes_referencia_png)
                ]
                respuesta = client.images.edit(
                    model=DEFAULT_IMAGE_MODEL, image=archivos, prompt=prompt,
                    n=NUM_IMAGENES, size=TAMANO_INFOGRAFIA,
                )
            else:
                respuesta = client.images.generate(
                    model=DEFAULT_IMAGE_MODEL, prompt=prompt,
                    n=NUM_IMAGENES, size=TAMANO_INFOGRAFIA,
                )
            imagenes = []
            for dato in respuesta.data:
                b64 = getattr(dato, 'b64_json', None)
                if b64:
                    imagenes.append(base64.b64decode(b64))
                elif getattr(dato, 'url', None):
                    with urllib.request.urlopen(dato.url, timeout=60) as descarga:
                        imagenes.append(descarga.read())
            if imagenes:
                resultado['imagenes'] = imagenes
            else:
                resultado['error'] = 'OpenAI no devolvió ninguna imagen.'
        except Exception as exc:  # noqa: BLE001 — cualquier falla de la API cae a error legible
            resultado['error'] = str(exc)

    hilo = threading.Thread(target=_run, daemon=True)
    hilo.start()
    hilo.join(timeout=GENERATION_TIMEOUT_SECONDS)

    if hilo.is_alive():
        return None, f'Tiempo de espera agotado ({GENERATION_TIMEOUT_SECONDS}s) esperando a OpenAI.'
    if not resultado.get('imagenes'):
        return None, resultado.get('error', 'OpenAI no devolvió imágenes.')
    return resultado['imagenes'], None


def generar_infografias(infografia_id):
    """Genera las NUM_IMAGENES imágenes de una InfografiaJornada y las guarda como
    InfografiaImagen. Corre en un hilo de background (ver
    ReporteViewSet.generar_infografia en admin_views.py), mismo patrón que
    presentacion.py::generar_presentacion_html."""
    from django.db import close_old_connections

    close_old_connections()
    from .models import InfografiaImagen, InfografiaJornada

    infografia = None
    try:
        infografia = InfografiaJornada.objects.select_related('reporte__jornada').get(pk=infografia_id)
        infografia.estado = InfografiaJornada.ESTADO_PROCESANDO
        infografia.save(update_fields=['estado'])

        reporte = infografia.reporte
        datos, error = _obtener_datos_analitica(reporte)
        if error:
            infografia.estado = InfografiaJornada.ESTADO_ERROR
            infografia.error_mensaje = error
            infografia.save(update_fields=['estado', 'error_mensaje'])
            return

        prompt = _construir_prompt(datos)
        infografia.prompt_usado = prompt
        imagenes_referencia = _reunir_imagenes_referencia(reporte.jornada)

        imagenes_png, error = _llamar_openai_imagenes(prompt, imagenes_referencia)

        if imagenes_png:
            for orden, png in enumerate(imagenes_png):
                InfografiaImagen.objects.create(
                    infografia=infografia, orden=orden,
                    archivo=ContentFile(png, name=f'infografia-{infografia.id}-{orden}.png'),
                )
            infografia.estado = InfografiaJornada.ESTADO_COMPLETO
            infografia.error_mensaje = ''
            infografia.modelo_usado = DEFAULT_IMAGE_MODEL
            infografia.completado_en = timezone.now()
        else:
            infografia.estado = InfografiaJornada.ESTADO_ERROR
            infografia.error_mensaje = error or 'Error desconocido generando la infografía.'
        infografia.save(update_fields=[
            'prompt_usado', 'estado', 'error_mensaje', 'modelo_usado', 'completado_en',
        ])
    except Exception as exc:  # noqa: BLE001 — nunca debe dejar el hilo morir en silencio
        if infografia is not None:
            infografia.estado = InfografiaJornada.ESTADO_ERROR
            infografia.error_mensaje = str(exc)
            infografia.save(update_fields=['estado', 'error_mensaje'])
    finally:
        close_old_connections()
