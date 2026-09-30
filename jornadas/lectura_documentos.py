"""Lectura del documento que alguien diligenció FUERA de la web (.docx o .pdf) y partición del
esquema en lotes, para las dos extracciones con IA del proyecto:
`instrumentos.extraccion_ia_openai` (módulo `instrumentos`) y
`participantes.extraccion_momento_ia_openai` (modelo clásico `jornadas.Momento`/`Pregunta`).

Vive en `jornadas` por lo mismo que `jornadas.emparejamiento`: es la app que las dos importan sin
armar un ciclo.

Este código estaba duplicado —idéntico— en los dos módulos, y esa duplicación costó un bug real:
el lector de .docx recorría `documento.paragraphs` primero y `documento.tables` después, así que
el texto que llegaba al modelo traía TODOS los títulos de sección al principio y TODAS las tablas
juntas al final, sin ninguna forma de saber cuál tabla iba debajo de cuál título. En el formato de
diagnóstico de articulación académica (UNIMAGDALENA) eso es fatal: sus tres tablas del análisis de
coherencia son IDÉNTICAS —mismos encabezados, mismas filas de variables— y lo único que las
distingue es el párrafo que las precede ("Componente 1", "Componente 2", "Componente 3"). Con el
orden perdido, transcribir esas 84 celdas al componente correcto era adivinar.

Ahora se recorre el cuerpo del documento en su orden real y cada tabla sale delimitada y rotulada
con el párrafo que la antecede."""

# Tope de páginas enviadas como imagen — un PDF escaneado de 90 preguntas rara vez pasa de esto, y
# limita el costo/tiempo de una sola llamada con visión.
MAX_PAGINAS_IMAGEN = 20
# Si el texto extraído de un PDF promedia menos que esto por página, se asume escaneado/a mano y se
# cae al modo visión en vez de mandar un texto casi vacío.
UMBRAL_CARACTERES_POR_PAGINA = 40
# Recorte del párrafo que rotula una tabla: alcanza para "Componente 2" o "3. Semáforo de
# articulación académica" sin arrastrar un párrafo de instrucciones completo dentro del rótulo.
MAX_CARACTERES_ROTULO = 120


def _bloques_en_orden(documento):
    """Recorre el cuerpo del .docx en su orden real, intercalando párrafos y tablas.

    `documento.paragraphs` y `documento.tables` son dos listas separadas: cada una respeta el orden
    entre sus propios elementos, pero no hay forma de saber cómo se intercalan entre sí. La única
    fuente de ese orden es el XML del cuerpo, donde `w:p` y `w:tbl` son hermanos."""
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for hijo in documento.element.body.iterchildren():
        if isinstance(hijo, CT_P):
            yield Paragraph(hijo, documento)
        elif isinstance(hijo, CT_Tbl):
            yield Table(hijo, documento)


def _filas_de_tabla(tabla):
    """Las filas con algún contenido, como `celda | celda | celda`.

    Las filas completamente vacías se omiten: en un formato en blanco son cientos de renglones de
    `| | | |` que no le dicen nada al modelo y sí le gastan contexto. Una fila realmente
    diligenciada tiene, por definición, al menos una celda con texto."""
    for fila in tabla.rows:
        celdas = [c.text.strip() for c in fila.cells]
        if any(celdas):
            yield ' | '.join(celdas)


def extraer_texto_docx(archivo):
    """Texto plano del .docx respetando el orden del documento, con cada tabla delimitada y
    rotulada con el párrafo que la precede.

    El rótulo es la pieza que le permite al modelo saber a qué pregunta del esquema corresponde una
    tabla cuando hay varias con encabezados idénticos (ver el docstring del módulo). Los
    delimitadores `[TABLA n]` / `[fin TABLA n]` cierran el otro agujero del formato plano anterior:
    sin ellos, dos tablas consecutivas con las mismas columnas se leen como una sola tabla larga."""
    from docx import Document

    documento = Document(archivo)
    partes = []
    rotulo_pendiente = ''
    numero_tabla = 0

    for bloque in _bloques_en_orden(documento):
        if hasattr(bloque, 'rows'):  # docx.table.Table
            numero_tabla += 1
            filas = list(_filas_de_tabla(bloque))
            if not filas:
                continue
            encabezado = f'[TABLA {numero_tabla}'
            if rotulo_pendiente:
                encabezado += f' — justo debajo de "{rotulo_pendiente}"'
            partes.append(encabezado + ']')
            partes.extend(filas)
            partes.append(f'[fin TABLA {numero_tabla}]')
            continue

        texto = bloque.text.strip()
        if not texto:
            continue
        partes.append(texto)
        # Solo el último párrafo no vacío antes de la tabla la rotula: en este tipo de formato ese
        # párrafo es siempre el título de la sección o el del bloque ("Componente 2").
        rotulo_pendiente = ' '.join(texto.split())[:MAX_CARACTERES_ROTULO]

    return '\n'.join(partes)


def extraer_texto_o_imagenes_pdf(archivo):
    """Devuelve `(texto, None)` si el PDF tiene texto seleccionable suficiente, o
    `(None, lista_de_imagenes_base64)` si hay que caer a visión (escaneado / diligenciado a mano)."""
    import base64

    import pdfplumber

    archivo.seek(0)
    paginas_texto = []
    with pdfplumber.open(archivo) as pdf:
        n_paginas = len(pdf.pages)
        for pagina in pdf.pages:
            paginas_texto.append(pagina.extract_text() or '')

    texto = '\n'.join(paginas_texto).strip()
    if n_paginas and len(texto) / n_paginas >= UMBRAL_CARACTERES_POR_PAGINA:
        return texto, None

    import fitz  # PyMuPDF

    archivo.seek(0)
    imagenes = []
    documento = fitz.open(stream=archivo.read(), filetype='pdf')
    for pagina in documento[:MAX_PAGINAS_IMAGEN]:
        pixmap = pagina.get_pixmap(dpi=150)
        imagenes.append(base64.b64encode(pixmap.tobytes('png')).decode('ascii'))
    documento.close()
    return None, imagenes


def leer_documento(archivo, nombre):
    """Despacha por extensión del nombre original. Devuelve `(texto_o_None, imagenes_o_None)`.

    El archivo lo abre y cierra quien llama: acá no se sabe si es un `FieldFile` de Django o un
    buffer en memoria."""
    extension = nombre.rsplit('.', 1)[-1].lower() if '.' in nombre else ''
    if extension == 'docx':
        return extraer_texto_docx(archivo), None
    if extension == 'pdf':
        return extraer_texto_o_imagenes_pdf(archivo)
    raise ValueError(f'Formato de archivo no soportado: .{extension} (solo .pdf o .docx).')


def agrupar_en_lotes(items, costo, presupuesto):
    """Parte `items` en lotes CONSECUTIVOS (sin reordenar) cuyo `costo(item)` sumado no pase de
    `presupuesto`. Un item que por sí solo lo excede se va en un lote propio — partirlo por dentro
    no le toca a esta función.

    Es lo que evita que una transcripción se trunque: el tope de tokens de salida de una llamada no
    depende del tamaño del documento sino de cuántas celdas se le piden transcribir en ella, así
    que el control tiene que estar acá y no en el prompt."""
    lotes = []
    actual = []
    acumulado = 0
    for item in items:
        costo_item = max(1, costo(item))
        if actual and acumulado + costo_item > presupuesto:
            lotes.append(actual)
            actual = []
            acumulado = 0
        actual.append(item)
        acumulado += costo_item
    if actual:
        lotes.append(actual)
    return lotes
