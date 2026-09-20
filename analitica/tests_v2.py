"""Tests del contrato kunsamu.analisis/v2 (analitica/v2/). Separados de tests.py para no tocar la
suite legacy. Sin OPENAI_API_KEY en el entorno de test: toda llamada al proveedor se mockea o cae
determinísticamente al error 'OPENAI_API_KEY no está configurada'."""
import copy
import json

from django.test import SimpleTestCase

from .v2.contrato import RECURSOS
from .v2.validacion import PunteroInvalido, resolver_puntero, validar_esquema, validar_negocio, validar_salida


def _ejemplo(nombre):
    return json.loads((RECURSOS / 'ejemplos' / nombre).read_text(encoding='utf-8'))


class ValidacionEjemplosTests(SimpleTestCase):
    """Los ejemplos de la entrega son el contrato: los cuatro pares pasan las dos capas y el
    catálogo visual pasa el esquema."""

    def test_pares_de_la_entrega_son_validos(self):
        for base in ('llm_integral', 'llm_por_momento', 'bertopic_integral', 'sin_datos'):
            salida, entrada = _ejemplo(f'{base}.salida.json'), _ejemplo(f'{base}.entrada.json')
            self.assertEqual(validar_salida(salida, entrada, pipeline_esperado=salida['pipeline']), [], base)

    def test_catalogo_visual_pasa_el_esquema(self):
        self.assertEqual(validar_esquema(_ejemplo('catalogo_visual.salida.json')), [])

    def test_rechaza_clave_extra_en_raiz(self):
        salida = _ejemplo('llm_integral.salida.json')
        salida['html'] = '<p>x</p>'
        self.assertTrue(any('[esquema]' in e for e in validar_esquema(salida)))

    def test_rechaza_porcentaje_que_no_cuadra(self):
        salida, entrada = _ejemplo('llm_integral.salida.json'), _ejemplo('llm_integral.entrada.json')
        salida['informes'][0]['hallazgos'][0]['metricas'][0]['valor'] = 90
        self.assertTrue(any('no corresponde a 100×' in e for e in validar_negocio(salida, entrada)))

    def test_rechaza_cita_no_literal(self):
        salida, entrada = _ejemplo('llm_integral.salida.json'), _ejemplo('llm_integral.entrada.json')
        salida['informes'][0]['hallazgos'][0]['citas'][0]['texto'] = 'Cita inventada'
        self.assertTrue(any('subcadena literal' in e for e in validar_negocio(salida, entrada)))

    def test_rechaza_visualizacion_huerfana_y_referencia_rota(self):
        salida, entrada = _ejemplo('llm_integral.salida.json'), _ejemplo('llm_integral.entrada.json')
        salida['informes'][0]['hallazgos'][0]['visualizacion_ids'] = ['no-existe']
        errores = validar_negocio(salida, entrada)
        self.assertTrue(any('inexistente' in e for e in errores))
        self.assertTrue(any('huérfanas' in e for e in errores))

    def test_rechaza_cobertura_incompleta_y_pipeline_distinto(self):
        salida, entrada = _ejemplo('llm_integral.salida.json'), _ejemplo('llm_integral.entrada.json')
        salida['cobertura'] = salida['cobertura'][:-1]
        errores = validar_negocio(salida, entrada, pipeline_esperado='bertopic_llm')
        self.assertTrue(any('cobertura: faltan' in e for e in errores))
        self.assertTrue(any(e.startswith('pipeline:') for e in errores))

    def test_por_momento_rechaza_cruce_de_fuentes_entre_momentos(self):
        salida, entrada = _ejemplo('llm_por_momento.salida.json'), _ejemplo('llm_por_momento.entrada.json')
        # El informe i2 (m2) usa la fuente f1, que es de m1.
        salida['informes'][1]['hallazgos'][0]['fuente_ids'] = ['f1', 'f2']
        self.assertTrue(any('cruce no permitido' in e for e in validar_negocio(salida, entrada)))

    def test_puntero_json(self):
        datos = {'respuestas': [{'valor': 'hola'}, {'valor': {'celdas': [{'valor': 'x'}]}}], 'a~b': {'c/d': 1}}
        self.assertEqual(resolver_puntero(datos, '/respuestas/0/valor'), 'hola')
        self.assertEqual(resolver_puntero(datos, '/respuestas/1/valor/celdas/0/valor'), 'x')
        self.assertEqual(resolver_puntero(datos, '/a~0b/c~1d'), 1)
        for ruta in ('respuestas/0', '/respuestas/9/valor', '/respuestas/0/valor/x'):
            with self.assertRaises(PunteroInvalido):
                resolver_puntero(datos, ruta)
