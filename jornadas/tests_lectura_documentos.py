"""Tests de `jornadas.lectura_documentos` — la lectura del documento diligenciado fuera de la web
y la partición del esquema en lotes. Nada de esto toca la base de datos ni OpenAI: se construye un
.docx en memoria con python-docx y se mira el texto que saldría hacia el modelo."""
import io

from django.test import SimpleTestCase

from . import lectura_documentos


def _docx_en_memoria(construir):
    """Un .docx armado al vuelo por `construir(documento)`, devuelto como buffer listo para leer."""
    from docx import Document

    documento = Document()
    construir(documento)
    buffer = io.BytesIO()
    documento.save(buffer)
    buffer.seek(0)
    return buffer


def _tabla(documento, filas):
    tabla = documento.add_table(rows=len(filas), cols=len(filas[0]))
    for i, fila in enumerate(filas):
        for j, celda in enumerate(fila):
            tabla.cell(i, j).text = celda
    return tabla


class ExtraerTextoDocxTests(SimpleTestCase):
    """El bug que motivó este módulo: el lector anterior recorría todos los párrafos y DESPUÉS
    todas las tablas, así que el modelo recibía los títulos de sección separados de sus tablas."""

    def test_respeta_el_orden_del_documento(self):
        def construir(documento):
            documento.add_paragraph('Sección A')
            _tabla(documento, [['Variable', 'Valor'], ['Créditos', '3']])
            documento.add_paragraph('Sección B')
            _tabla(documento, [['Variable', 'Valor'], ['Créditos', '4']])

        texto = lectura_documentos.extraer_texto_docx(_docx_en_memoria(construir))
        lineas = [l for l in texto.split('\n') if l]

        self.assertLess(lineas.index('Sección A'), lineas.index('Sección B'))
        # La tabla de A va ANTES del título de B — con el lector anterior las dos tablas caían
        # juntas al final, después de los dos títulos.
        self.assertLess(
            next(i for i, l in enumerate(lineas) if 'Créditos | 3' in l),
            lineas.index('Sección B'),
        )

    def test_cada_tabla_queda_rotulada_con_el_parrafo_que_la_precede(self):
        """Lo que hace transcribibles las tres tablas idénticas del formato de diagnóstico de
        articulación académica: solo las distingue el párrafo "Componente N" de arriba."""
        filas = [['Variable', 'Programa A'], ['Nombre', '']]

        def construir(documento):
            documento.add_paragraph('Componente 1')
            _tabla(documento, filas)
            documento.add_paragraph('Componente 2')
            _tabla(documento, filas)

        texto = lectura_documentos.extraer_texto_docx(_docx_en_memoria(construir))

        self.assertIn('[TABLA 1 — justo debajo de "Componente 1"]', texto)
        self.assertIn('[TABLA 2 — justo debajo de "Componente 2"]', texto)
        self.assertIn('[fin TABLA 1]', texto)

    def test_las_filas_totalmente_vacias_no_se_mandan(self):
        def construir(documento):
            _tabla(documento, [['Profesor', 'Área'], ['', ''], ['Ana', 'Física']])

        texto = lectura_documentos.extraer_texto_docx(_docx_en_memoria(construir))

        self.assertIn('Ana | Física', texto)
        self.assertNotIn('\n | \n', texto)

    def test_un_docx_sin_nada_devuelve_texto_vacio(self):
        """La señal que usan los dos extractores para cortar antes de gastar una llamada al
        proveedor (ver `procesar_extraccion_instrumento`)."""
        texto = lectura_documentos.extraer_texto_docx(_docx_en_memoria(lambda documento: None))
        self.assertEqual(texto.strip(), '')

    def test_rechaza_una_extension_no_soportada(self):
        with self.assertRaises(ValueError):
            lectura_documentos.leer_documento(io.BytesIO(b'x'), 'formato.xlsx')


class AgruparEnLotesTests(SimpleTestCase):
    """La partición que evita que la respuesta del modelo se trunque."""

    def test_agrupa_hasta_llenar_el_presupuesto_sin_reordenar(self):
        lotes = lectura_documentos.agrupar_en_lotes(
            ['a', 'b', 'c', 'd'], costo=lambda _item: 3, presupuesto=7,
        )
        self.assertEqual(lotes, [['a', 'b'], ['c', 'd']])

    def test_un_item_mas_grande_que_el_presupuesto_va_solo(self):
        """No se parte por dentro: una matriz de 14×4 es una sola pregunta y el prompt necesita
        verla completa con todas sus filas y columnas."""
        lotes = lectura_documentos.agrupar_en_lotes(
            ['chico', 'enorme', 'chico2'],
            costo=lambda item: 100 if item == 'enorme' else 1,
            presupuesto=10,
        )
        self.assertEqual(lotes, [['chico'], ['enorme'], ['chico2']])

    def test_sin_items_no_hay_lotes(self):
        self.assertEqual(lectura_documentos.agrupar_en_lotes([], lambda _i: 1, 10), [])
