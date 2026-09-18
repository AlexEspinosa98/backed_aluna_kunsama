"""Genera la infografía de una jornada como una SERIE de 3 láminas complementarias (portada,
hallazgos y cierre — ver `SYSTEM_PROMPT_PREFIJO`), vía el modelo de imágenes de OpenAI. Usa como referencia visual DIRECTA los `JornadaAsset` de la
jornada (fotos/logos + el system design más reciente, ver jornadas/models.py::JornadaAsset) y como
contenido la analítica ya calculada (el reporte integral `AnalisisJornadaIA` o un `Reporte`).

UNA sola llamada con `n=3`. `n` no admite un prompt por imagen, pero gpt-image-2 razona sobre el
conjunto cuando el prompt describe una SERIE (storyboard): por eso `SYSTEM_PROMPT_PREFIJO` enumera
las tres láminas y dice qué no debe repetirse entre ellas. Sin esa forma de pedirlo, `n=3` sí
devuelve tres variantes de lo mismo.

Mismo patrón de threading+timeout que el resto de módulos de IA del proyecto (ver
analitica/presentacion.py, instrumentos/extraccion_ia_openai.py): nunca lanza excepción hacia
afuera, corre en un hilo de background y deja `estado`/`error_mensaje` listos para que el
frontend haga polling.

El nombre del modelo y la forma exacta de su respuesta (b64_json vs url) quedan aislados detrás de
OPENAI_IMAGE_MODEL y de `_llamar_openai_imagen`, para que corregirlos sea un cambio de una función
y no de arquitectura.
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
# 16:9 real en píxeles. gpt-image-2 acepta resoluciones arbitrarias (no solo el enum que declara
# el SDK), pero con reglas: ambos lados múltiplos de 16, proporción entre 1:3 y 3:1, ningún lado
# sobre 3840 y entre 655.360 y 8.294.400 píxeles en total. Por eso NO se usa 1920x1080: 1080 no es
# múltiplo de 16 y la API lo rechaza. 2048x1152 es 16:9 exacto y cumple todas las reglas.
TAMANO_INFOGRAFIA = os.environ.get('OPENAI_IMAGE_SIZE', '2048x1152')
PROPORCION_INFOGRAFIA = '16:9'
NUM_LAMINAS = 3
# Tope de assets tipo 'asset' que se mandan como referencia (+ 1 system_design aparte) — controla
# costo/tiempo de la llamada, igual espíritu que MAX_PAGINAS_IMAGEN en extraccion_ia_openai.py.
MAX_ASSETS_REFERENCIA = 4
# Lado máximo (px) de una imagen de referencia antes de mandarla a la API — evita payloads gigantes.
MAX_LADO_IMAGEN_REFERENCIA = 2048

# UNA sola llamada con n=3 y un prompt de SECUENCIA. `n` no admite un prompt por imagen, pero
# gpt-image-2 razona sobre el conjunto cuando el prompt lo describe como una serie/storyboard: es
# el mecanismo documentado para obtener un set coherente y diferenciado. Por eso el prompt enumera
# las tres láminas y dice explícitamente qué NO debe repetirse entre ellas — sin esa instrucción
# el modelo devuelve tres variantes de lo mismo.
SYSTEM_PROMPT_PREFIJO = (
    f"Diseña una SERIE de {NUM_LAMINAS} láminas DISTINTAS y COMPLEMENTARIAS —como las "
    "diapositivas consecutivas de una misma presentación— que comuniquen los resultados reales de "
    "una jornada participativa universitaria. No son variantes de una misma lámina: cada una "
    "tiene un contenido propio y juntas cuentan la historia completa.\n\n"
    f"FORMATO: cada lámina es APAISADA en {PROPORCION_INFOGRAFIA} (pantalla ancha, tipo "
    "diapositiva para proyectar). La composición ocupa todo el ancho; nunca la maquetes en "
    "vertical ni en cuadrado.\n\n"
    f"LAS {NUM_LAMINAS} LÁMINAS, EN ESTE ORDEN:\n"
    "1. PORTADA — el nombre de la jornada como título dominante y, debajo, las cifras clave de "
    "participación (participantes, momentos, tasa de participación) en 2 a 4 bloques grandes. Sin "
    "gráficos ni listas de hallazgos: es la carátula, se lee de un vistazo desde lejos.\n"
    "2. HALLAZGOS — el cuerpo: los temas y hallazgos principales, cada uno con su dato real al "
    "lado, en columnas o tarjetas, con las visualizaciones (barras o porciones) construidas con "
    "los números exactos del JSON. Sin el título grande ni las cifras de la lámina 1.\n"
    "3. CIERRE — entre 3 y 5 mensajes accionables derivados únicamente del resumen y los "
    "hallazgos del JSON, en tipografía grande y con mucho aire. Sin cifras de participación y sin "
    "repetir los gráficos de la lámina 2.\n\n"
    "COHERENCIA: las tres comparten exactamente la misma paleta, tipografía y lenguaje visual, "
    "para que se vean como un mismo material y no como piezas de autores distintos.\n\n"
    "Usa EXCLUSIVAMENTE las cifras y hallazgos que se entregan abajo en JSON — nunca inventes "
    "números, porcentajes ni temas que no estén ahí. Si se adjuntan imágenes de referencia "
    "(fotos/logos de la jornada y/o una guía de marca), respeta su paleta de colores, tipografía "
    "y estilo visual real — no uses una paleta genérica distinta a la de esas imágenes. Todo el "
    "texto debe estar en español."
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
    por defecto del modelo) + el 'system_design' con archivo más reciente, si existe. Se excluyen
    las filas sin archivo (un system_design puede ser solo texto, ver `_texto_system_design`). Un
    archivo individual que falle al leerse/convertirse se omite (no debe tumbar toda la generación
    por un asset puntual corrupto)."""
    imagenes = []
    assets = jornada.assets.filter(tipo=JornadaAsset.TIPO_ASSET).exclude(archivo='')[:MAX_ASSETS_REFERENCIA]
    system_design = jornada.assets.filter(
        tipo=JornadaAsset.TIPO_SYSTEM_DESIGN,
    ).exclude(archivo='').first()
    for asset in list(assets) + ([system_design] if system_design else []):
        try:
            imagenes.append(_leer_imagen_referencia(asset))
        except Exception:  # noqa: BLE001 — un asset ilegible no debe abortar la generación entera
            continue
    return imagenes


def _texto_system_design(jornada):
    """Guía de marca escrita (colores, tipografía, tono) de la jornada, si la cargaron — el
    `system_design` con texto más reciente. Va al prompt, no como imagen: es una instrucción de
    estilo, no algo que el modelo deba copiar visualmente."""
    system_design = jornada.assets.filter(
        tipo=JornadaAsset.TIPO_SYSTEM_DESIGN,
    ).exclude(texto='').first()
    return system_design.texto if system_design else ''


def _obtener_datos_analitica(jornada, reporte=None):
    """(datos, error) — nunca lanza excepción. Si se disparó desde un `Reporte` con `analisis`, esa
    es la fuente (la más detallada). Si no, se usa el reporte integral más reciente de la jornada
    (`AnalisisJornadaIA`), que es la vía que usa el panel. Si no hay ninguno, error controlado."""
    if reporte is not None and reporte.analisis:
        return {
            'fuente': 'reporte',
            'jornada': jornada.nombre,
            'participacion': reporte.analisis.get('participacion'),
            'momentos': reporte.analisis.get('momentos'),
            'sintesis_narrativa': reporte.texto_reporte,
        }, None

    from .models import AnalisisJornadaIA, Reporte

    analisis_ia = AnalisisJornadaIA.objects.filter(
        jornada=jornada, estado=AnalisisJornadaIA.ESTADO_COMPLETO,
    ).order_by('-creado_en').first()
    if analisis_ia and analisis_ia.resultado:
        return {
            'fuente': 'analisis_jornada_ia',
            'jornada': jornada.nombre,
            'resumen_ejecutivo': analisis_ia.resultado.get('resumen_ejecutivo'),
            'hallazgos': analisis_ia.resultado.get('hallazgos'),
        }, None

    # Último recurso: cualquier reporte local ya completo de esta jornada. Cubre el caso de pedir
    # la infografía a nivel de jornada cuando lo que existe es un Reporte y no un análisis IA.
    reporte_completo = Reporte.objects.filter(
        jornada=jornada, estado=Reporte.ESTADO_COMPLETO,
    ).exclude(analisis={}).order_by('-creado_en').first()
    if reporte_completo:
        return {
            'fuente': 'reporte',
            'jornada': jornada.nombre,
            'participacion': reporte_completo.analisis.get('participacion'),
            'momentos': reporte_completo.analisis.get('momentos'),
            'sintesis_narrativa': reporte_completo.texto_reporte,
        }, None

    return None, (
        'No hay analítica calculada para esta jornada — no existe ni un reporte integral '
        '(AnalisisJornadaIA) completo ni un Reporte con análisis. Genera alguno antes de pedir '
        'la infografía.'
    )


def _construir_prompt(datos_analitica, texto_system_design=''):
    partes = [SYSTEM_PROMPT_PREFIJO]
    if texto_system_design:
        partes.append(
            'GUÍA DE MARCA (respétala por encima de cualquier criterio estético propio):\n'
            + texto_system_design
        )
    partes.append('DATOS REALES (JSON):\n' + json.dumps(datos_analitica, ensure_ascii=False, indent=2))
    return '\n\n'.join(partes)




def _llamar_openai_imagenes(prompt, imagenes_referencia_png):
    """Genera las NUM_LAMINAS láminas en UNA llamada — imagen-a-imagen (`images.edit`) si hay
    imágenes de referencia, texto-a-imagen (`images.generate`) si la jornada no tiene ningún
    asset/system design todavía. Devuelve (lista_de_bytes_png_o_None, error) — nunca lanza
    excepción, mismo contrato que el resto de módulos de IA del proyecto."""
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
                    n=NUM_LAMINAS, size=TAMANO_INFOGRAFIA,
                )
            else:
                respuesta = client.images.generate(
                    model=DEFAULT_IMAGE_MODEL, prompt=prompt,
                    n=NUM_LAMINAS, size=TAMANO_INFOGRAFIA,
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
    """Genera las láminas de una InfografiaJornada (una por SLIDE) y las guarda como
    InfografiaImagen. Corre en un hilo de background (ver
    ReporteViewSet.generar_infografia en admin_views.py), mismo patrón que
    presentacion.py::generar_presentacion_html."""
    from django.db import close_old_connections

    close_old_connections()
    from .models import InfografiaImagen, InfografiaJornada

    infografia = None
    try:
        infografia = InfografiaJornada.objects.select_related('jornada', 'reporte').get(pk=infografia_id)
        infografia.estado = InfografiaJornada.ESTADO_PROCESANDO
        infografia.save(update_fields=['estado'])

        jornada = infografia.jornada
        datos, error = _obtener_datos_analitica(jornada, infografia.reporte)
        if error:
            infografia.estado = InfografiaJornada.ESTADO_ERROR
            infografia.error_mensaje = error
            infografia.save(update_fields=['estado', 'error_mensaje'])
            return

        prompt = _construir_prompt(datos, _texto_system_design(jornada))
        infografia.prompt_usado = prompt
        imagenes_referencia = _reunir_imagenes_referencia(jornada)

        imagenes_png, error = _llamar_openai_imagenes(prompt, imagenes_referencia)

        if imagenes_png:
            for orden, png in enumerate(imagenes_png):
                InfografiaImagen.objects.create(
                    infografia=infografia, orden=orden,
                    archivo=ContentFile(png, name=f'infografia-{infografia.id}-{orden}.png'),
                )
            infografia.estado = InfografiaJornada.ESTADO_COMPLETO
            # Si el modelo devuelve menos láminas de las pedidas queda constancia, en vez de que
            # el FE tenga que deducirlo contando el arreglo.
            infografia.error_mensaje = (
                '' if len(imagenes_png) == NUM_LAMINAS else
                f'Se generaron {len(imagenes_png)} de {NUM_LAMINAS} láminas.'
            )
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
