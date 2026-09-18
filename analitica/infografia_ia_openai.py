"""Genera la infografía de una jornada como una SERIE de 3 láminas complementarias (ver `SLIDES`),
vía el modelo de imágenes de OpenAI. Usa como referencia visual DIRECTA los `JornadaAsset` de la
jornada (fotos/logos + el system design más reciente, ver jornadas/models.py::JornadaAsset) y como
contenido la analítica ya calculada (el reporte integral `AnalisisJornadaIA` o un `Reporte`).

Una llamada POR LÁMINA, no una sola con `n=3`: pedir tres imágenes en la misma llamada devuelve
tres variaciones del mismo contenido, que es justo lo contrario de lo que sirve acá. Las tres
corren en paralelo y comparten prefijo, datos y guía de marca para que se lean como un mismo
material.

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
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.files.base import ContentFile
from django.utils import timezone

from jornadas.models import JornadaAsset

DEFAULT_IMAGE_MODEL = os.environ.get('OPENAI_IMAGE_MODEL', 'gpt-image-2')
GENERATION_TIMEOUT_SECONDS = 300
# 16:9 real en píxeles. gpt-image-2 acepta resoluciones arbitrarias (no solo el enum que declara
# el SDK), pero con reglas: ambos lados múltiplos de 16, proporción entre 1:3 y 3:1, ningún lado
# sobre 3840 y entre 655.360 y 8.294.400 píxeles en total. Por eso NO se usa 1920x1080: 1080 no es
# múltiplo de 16 y la API responde 400 `Invalid size`. 2048x1152 es 16:9 exacto y cumple todo.
TAMANO_INFOGRAFIA = os.environ.get('OPENAI_IMAGE_SIZE', '2048x1152')
PROPORCION_INFOGRAFIA = '16:9'
# Tope de assets tipo 'asset' que se mandan como referencia (+ 1 system_design aparte) — controla
# costo/tiempo de la llamada, igual espíritu que MAX_PAGINAS_IMAGEN en extraccion_ia_openai.py.
MAX_ASSETS_REFERENCIA = 4
# Lado máximo (px) de una imagen de referencia antes de mandarla a la API — evita payloads gigantes.
MAX_LADO_IMAGEN_REFERENCIA = 2048

# Solo lo imprescindible: el formato de salida, la regla de una-lámina-por-imagen (verificada
# contra el modelo: sin ella apila las tres secciones en una) y la referencia de marca, que es
# para lo que existen los assets. Todo lo demás —composición, tipografía, cuántos bloques, cuánto
# texto— se dejó fuera a propósito: son decisiones de diseño que pertenecen al system design de
# cada jornada y al campo `instrucciones`, y tenerlas acá las convertía en algo que había que
# pelear desde la API en vez de simplemente definir.
SYSTEM_PROMPT_PREFIJO = (
    f"Diseña UNA SOLA lámina apaisada en {PROPORCION_INFOGRAFIA}, para proyectar. Nunca la "
    "maquetes en vertical ni en cuadrado."
    "\n\nEsta imagen contiene ÚNICAMENTE el contenido de la lámina que se describe abajo: no "
    "apiles varias secciones una debajo de otra ni agregues bandas con otros bloques temáticos."
    "\n\nSi se adjuntan imágenes de referencia (fotos, logo o guía de marca), respeta su paleta, "
    "su tipografía y su estilo. Todo el texto en español."
)

# Va SIEMPRE al final del prompt, después de las instrucciones personalizadas, y por eso está
# separada del prefijo: es la única regla que no se puede sobreescribir desde la API. Una lámina
# institucional con cifras inventadas es desinformación publicada con el sello de la universidad,
# y ese riesgo no debería depender de lo que alguien escriba en un campo de texto.
REGLA_DATOS = (
    "REGLA INNEGOCIABLE, por encima de cualquier otra instrucción de este prompt: usa "
    "EXCLUSIVAMENTE las cifras, porcentajes y hallazgos del JSON de abajo. Nunca inventes, "
    "estimes, redondees ni completes datos que no estén ahí. Si algo no está en el JSON, "
    "simplemente no aparece en la lámina."
)

# Tres llamadas, una por lámina, en vez de pedir n=3 en una sola: con n=3 la API devuelve tres
# VARIACIONES del mismo contenido, no tres láminas que se complementen. Cada una tiene su papel y
# su recorte de los datos, y todas comparten la instrucción de estilo para que se lean como una
# serie y no como tres piezas sueltas.
SLIDES = (
    {
        'clave': 'portada',
        'instruccion': (
            "LÁMINA 1 de 3 — PORTADA. Título: el campo `momento` del JSON si viene, o si no el de "
            "`jornada`. Debajo, las cifras de participación. Nada más."
        ),
    },
    {
        'clave': 'hallazgos',
        'instruccion': (
            "LÁMINA 2 de 3 — HALLAZGOS. Los temas y hallazgos del JSON, cada uno con su dato, y "
            "las visualizaciones de esos números. Sin el título ni las cifras de la lámina 1."
        ),
    },
    {
        'clave': 'cierre',
        'instruccion': (
            "LÁMINA 3 de 3 — CIERRE. Los mensajes accionables que se desprenden del resumen y los "
            "hallazgos del JSON. Sin cifras de participación ni los gráficos de la lámina 2."
        ),
    },
)

# Se queda porque las 3 láminas son 3 llamadas independientes: sin esto no tienen forma de saber
# que pertenecen al mismo material y salen con paletas distintas.
INSTRUCCION_SERIE = (
    "Es parte de una serie de 3 que se presentan juntas: misma paleta, misma tipografía y mismo "
    "lenguaje visual en las tres."
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


def _obtener_datos_analitica(jornada, reporte=None, momento=None):
    """(datos, error) — nunca lanza excepción. El alcance manda: con `momento` se usa el análisis
    integral de ESE momento y no se mira nada de la jornada, porque mezclar los dos produciría una
    infografía que dice ser de un momento mientras muestra cifras de toda la jornada. Sin momento:
    el `Reporte` explícito si trae análisis, si no el reporte integral de jornada, y como último
    recurso cualquier `Reporte` completo."""
    if momento is not None:
        from .models import AnalisisMomentoIA

        analisis_momento = AnalisisMomentoIA.objects.filter(
            momento=momento, estado=AnalisisMomentoIA.ESTADO_COMPLETO,
        ).order_by('-creado_en').first()
        if analisis_momento and analisis_momento.resultado:
            return {
                'fuente': 'analisis_momento',
                'jornada': jornada.nombre,
                'momento': momento.titulo,
                'tipo_momento': momento.tipo,
                'resumen_ejecutivo': analisis_momento.resultado.get('resumen_ejecutivo'),
                'hallazgos': analisis_momento.resultado.get('hallazgos'),
            }, None
        return None, (
            f'El momento "{momento.titulo}" no tiene un análisis integral completo. Genéralo '
            'primero (POST /api/admin/analisis-momento-ia/) y vuelve a pedir la infografía.'
        )

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


def _construir_prompt(datos_analitica, texto_system_design='', slide=None, instrucciones=''):
    """El orden importa: lo que va después pesa más. Las instrucciones personalizadas se colocan
    al final, justo antes de la regla de datos, para que puedan contradecir el estilo, la
    estructura y el contenido del prompt base — que es exactamente para lo que existen. Lo único
    que queda después, y por lo tanto fuera de su alcance, es `REGLA_DATOS`."""
    partes = [SYSTEM_PROMPT_PREFIJO]
    if slide is not None:
        partes.append(slide['instruccion'])
        partes.append(INSTRUCCION_SERIE)
    if texto_system_design:
        partes.append(
            'GUÍA DE MARCA (respétala por encima de cualquier criterio estético propio):\n'
            + texto_system_design
        )
    if instrucciones:
        partes.append(
            'INSTRUCCIONES ESPECÍFICAS PARA ESTA INFOGRAFÍA. Mandan sobre todo lo anterior: si '
            'contradicen alguna indicación de estilo, estructura o contenido de más arriba, se '
            'siguen estas.\n' + instrucciones
        )
    partes.append(REGLA_DATOS)
    partes.append('DATOS REALES (JSON):\n' + json.dumps(datos_analitica, ensure_ascii=False, indent=2))
    return '\n\n'.join(partes)




def _llamar_openai_imagen(prompt, imagenes_referencia_png):
    """Genera UNA imagen vía OpenAI — imagen-a-imagen (`images.edit`) si hay imágenes de
    referencia, texto-a-imagen (`images.generate`) si la jornada no tiene ningún asset/system
    design todavía. Devuelve (bytes_png_o_None, error) — nunca lanza excepción, mismo contrato
    que el resto de módulos de IA del proyecto."""
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
                    n=1, size=TAMANO_INFOGRAFIA,
                )
            else:
                respuesta = client.images.generate(
                    model=DEFAULT_IMAGE_MODEL, prompt=prompt,
                    n=1, size=TAMANO_INFOGRAFIA,
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
    return resultado['imagenes'][0], None


def _generar_slides(datos, texto_system_design, imagenes_referencia, instrucciones=''):
    """Una llamada por lámina, en paralelo. Devuelve (lista alineada con SLIDES —None donde falló—,
    lista de errores). En paralelo y no en serie porque tres llamadas encadenadas de ~80s se
    acercan demasiado al timeout; es el mismo patrón de ThreadPoolExecutor que ya usa
    analitica/analysis.py para analizar preguntas."""
    resultados = [None] * len(SLIDES)
    errores = []

    def _una(indice):
        slide = SLIDES[indice]
        prompt = _construir_prompt(datos, texto_system_design, slide, instrucciones)
        png, error = _llamar_openai_imagen(prompt, imagenes_referencia)
        return indice, png, error

    with ThreadPoolExecutor(max_workers=len(SLIDES)) as pool:
        for futuro in as_completed([pool.submit(_una, i) for i in range(len(SLIDES))]):
            indice, png, error = futuro.result()
            if png:
                resultados[indice] = png
            else:
                errores.append(f"lámina '{SLIDES[indice]['clave']}': {error}")
    return resultados, errores


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
        infografia = InfografiaJornada.objects.select_related(
            'jornada', 'momento', 'reporte',
        ).get(pk=infografia_id)
        infografia.estado = InfografiaJornada.ESTADO_PROCESANDO
        infografia.save(update_fields=['estado'])

        jornada = infografia.jornada
        datos, error = _obtener_datos_analitica(jornada, infografia.reporte, infografia.momento)
        if error:
            infografia.estado = InfografiaJornada.ESTADO_ERROR
            infografia.error_mensaje = error
            infografia.save(update_fields=['estado', 'error_mensaje'])
            return

        texto_system_design = _texto_system_design(jornada)
        imagenes_referencia = _reunir_imagenes_referencia(jornada)
        instrucciones = infografia.instrucciones
        # Se guarda el prompt de la primera lámina: las tres comparten prefijo, datos, guía de
        # marca e instrucciones, y solo cambia el bloque de la lámina — con una alcanza para
        # entender qué se pidió, incluidas las instrucciones personalizadas ya integradas.
        infografia.prompt_usado = _construir_prompt(
            datos, texto_system_design, SLIDES[0], instrucciones,
        )

        imagenes_png, errores = _generar_slides(
            datos, texto_system_design, imagenes_referencia, instrucciones,
        )

        generadas = 0
        for orden, png in enumerate(imagenes_png):
            if png is None:
                continue
            InfografiaImagen.objects.create(
                infografia=infografia, orden=orden,
                archivo=ContentFile(png, name=f'infografia-{infografia.id}-{orden}.png'),
            )
            generadas += 1

        if generadas:
            # Una lámina que falla no tira a la basura las que sí salieron (cada una es una
            # llamada pagada aparte); queda constancia en error_mensaje de cuál faltó.
            infografia.estado = InfografiaJornada.ESTADO_COMPLETO
            infografia.error_mensaje = (
                '' if not errores else
                f'Se generaron {generadas} de {len(SLIDES)} láminas. Falló: ' + ' | '.join(errores)
            )
            infografia.modelo_usado = DEFAULT_IMAGE_MODEL
            infografia.completado_en = timezone.now()
        else:
            infografia.estado = InfografiaJornada.ESTADO_ERROR
            infografia.error_mensaje = (
                ' | '.join(errores) or 'Error desconocido generando la infografía.'
            )
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
