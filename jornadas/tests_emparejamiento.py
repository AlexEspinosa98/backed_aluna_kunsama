"""Pruebas del emparejador de responsables (jornadas/emparejamiento.py, HU-55). Funciones puras
sin modelos: los candidatos son tuplas `(objeto, nombre, correo)`, así que se prueban con objetos
cualquiera — lo que importa acá es la escalera de reglas, no de qué tabla salen."""
from django.test import SimpleTestCase

from . import emparejamiento


class NormalizarTests(SimpleTestCase):
    def test_quita_tildes_mayusculas_y_espacios_de_mas(self):
        self.assertEqual(emparejamiento.normalizar('  JOSÉ   Pérez  '), 'jose perez')

    def test_tolera_none_y_vacio(self):
        self.assertEqual(emparejamiento.normalizar(None), '')
        self.assertEqual(emparejamiento.normalizar('   '), '')


class EmparejarTests(SimpleTestCase):
    def setUp(self):
        self.ana = object()
        self.juan = object()
        self.otro_juan = object()
        self.candidatos = [
            (self.ana, 'Ana María Gómez', 'ana@uni.edu.co'),
            (self.juan, 'Juan Pérez', 'juan@uni.edu.co'),
        ]

    def test_correo_exacto_gana(self):
        # El nombre ni siquiera coincide: el correo es un identificador, no un parecido.
        objeto, estado = emparejamiento.emparejar(
            self.candidatos, nombre='Quien sea', correo='ANA@UNI.EDU.CO',
        )
        self.assertIs(objeto, self.ana)
        self.assertEqual(estado, emparejamiento.ESTADO_EMPAREJADO)

    def test_nombre_exacto_ignorando_tildes_y_mayusculas(self):
        objeto, estado = emparejamiento.emparejar(self.candidatos, nombre='juan perez')
        self.assertIs(objeto, self.juan)
        self.assertEqual(estado, emparejamiento.ESTADO_EMPAREJADO)

    def test_nombre_parcial_contenido_en_el_registro(self):
        # El documento dice "Ana Gómez", el registro es "Ana María Gómez".
        objeto, estado = emparejamiento.emparejar(self.candidatos, nombre='Ana Gómez')
        self.assertIs(objeto, self.ana)
        self.assertEqual(estado, emparejamiento.ESTADO_EMPAREJADO)

    def test_nombre_mas_largo_que_el_registro(self):
        # Al revés: el documento trae el nombre completo y el registro solo una parte.
        objeto, estado = emparejamiento.emparejar(self.candidatos, nombre='Juan Pérez Gómez Silva')
        self.assertIs(objeto, self.juan)
        self.assertEqual(estado, emparejamiento.ESTADO_EMPAREJADO)

    def test_dos_homonimos_quedan_ambiguos_y_no_devuelve_ninguno(self):
        """Lo importante no es solo el estado: es que NO devuelva un objeto. Desempatar por el
        primero le atribuiría el documento a quien salió antes en la consulta."""
        candidatos = self.candidatos + [(self.otro_juan, 'Juan Pérez', 'jperez@uni.edu.co')]
        objeto, estado = emparejamiento.emparejar(candidatos, nombre='Juan Pérez')
        self.assertIsNone(objeto)
        self.assertEqual(estado, emparejamiento.ESTADO_AMBIGUO)

    def test_correo_repetido_tambien_es_ambiguo(self):
        candidatos = self.candidatos + [(self.otro_juan, 'Otra Persona', 'juan@uni.edu.co')]
        objeto, estado = emparejamiento.emparejar(candidatos, correo='juan@uni.edu.co')
        self.assertIsNone(objeto)
        self.assertEqual(estado, emparejamiento.ESTADO_AMBIGUO)

    def test_sin_coincidencia(self):
        objeto, estado = emparejamiento.emparejar(self.candidatos, nombre='Carlos Restrepo')
        self.assertIsNone(objeto)
        self.assertEqual(estado, emparejamiento.ESTADO_SIN_COINCIDENCIA)

    def test_sin_dato_cuando_no_hay_nombre_ni_correo(self):
        objeto, estado = emparejamiento.emparejar(self.candidatos, nombre=None, correo=None)
        self.assertIsNone(objeto)
        self.assertEqual(estado, emparejamiento.ESTADO_SIN_DATO)

    def test_lista_de_candidatos_vacia(self):
        objeto, estado = emparejamiento.emparejar([], nombre='Ana Gómez')
        self.assertIsNone(objeto)
        self.assertEqual(estado, emparejamiento.ESTADO_SIN_COINCIDENCIA)

    def test_correo_que_no_existe_cae_al_nombre(self):
        objeto, estado = emparejamiento.emparejar(
            self.candidatos, nombre='Ana María Gómez', correo='noexiste@uni.edu.co',
        )
        self.assertIs(objeto, self.ana)
        self.assertEqual(estado, emparejamiento.ESTADO_EMPAREJADO)
