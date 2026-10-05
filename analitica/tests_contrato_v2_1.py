"""HU-100: contrato `kunsamu.analisis/v2.1` — colores con significado y los tipos grafo, sankey y
treemap. Lo que se genera es v2.1; lo guardado en v2 se sigue leyendo."""
import copy
import json

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APITestCase

from .models import AnalisisJornadaIA
from .tests import crear_admin_completo
from .tests_v2 import crear_jornada_completa
from .v2.contrato import RECURSOS, VERSION, es_contrato_v2
from .v2.migracion_contrato import salida_a_v2_1
from .v2.validacion import _validar_datos_visual, validar_esquema


def _catalogo():
    return json.loads((RECURSOS / 'ejemplos' / 'catalogo_visual.salida.json').read_text(encoding='utf-8'))


def _visual(tipo):
    return copy.deepcopy(next(v for v in _catalogo()['visualizaciones'] if v['tipo'] == tipo))


def _errores(visual):
    errores = []
    _validar_datos_visual(errores, visual['id'], visual, {'f-catalogo'})
    return errores


class ContratoTests(SimpleTestCase):
    def test_el_catalogo_de_20_tipos_es_valido(self):
        catalogo = _catalogo()
        self.assertEqual(catalogo['version'], 'kunsamu.analisis/v2.1')
        self.assertEqual(len({v['tipo'] for v in catalogo['visualizaciones']}), 20)
        self.assertEqual(validar_esquema(catalogo), [])
        for visual in catalogo['visualizaciones']:
            self.assertEqual(_errores(visual), [], visual['tipo'])

    def test_se_leen_las_dos_versiones(self):
        self.assertTrue(es_contrato_v2({'version': 'kunsamu.analisis/v2'}))
        self.assertTrue(es_contrato_v2({'version': 'kunsamu.analisis/v2.1'}))
        self.assertFalse(es_contrato_v2({'hallazgos': []}))
        self.assertEqual(VERSION, 'kunsamu.analisis/v2.1')

    def test_un_color_mal_escrito_lo_rechaza_el_esquema(self):
        catalogo = _catalogo()
        barras = next(v for v in catalogo['visualizaciones'] if v['tipo'] == 'barras')
        barras['datos']['colores_categorias'][0]['color'] = 'verde'
        self.assertTrue(validar_esquema(catalogo))

    def test_migrar_una_salida_v2_no_inventa_colores(self):
        v2 = json.loads((RECURSOS / 'ejemplos' / 'llm_integral.salida.json').read_text(encoding='utf-8'))
        v2['version'] = 'kunsamu.analisis/v2'
        for visual in v2['visualizaciones']:
            visual['datos'].pop('colores_series', None)
            visual['datos'].pop('colores_categorias', None)
        nueva = salida_a_v2_1(v2)
        self.assertEqual(nueva['version'], VERSION)
        self.assertEqual(validar_esquema(nueva), [])
        for visual in nueva['visualizaciones']:
            self.assertFalse(visual['datos'].get('colores_series'))
            self.assertFalse(visual['datos'].get('colores_categorias'))


class ReglasTiposNuevosTests(SimpleTestCase):
    def test_sankey_sin_ciclos_ni_valores_negativos(self):
        sankey = _visual('sankey')
        flujo = sankey['datos']['flujos'][0]
        sankey['datos']['flujos'].append({'origen': flujo['destino'], 'destino': flujo['origen'], 'valor': 1, 'color': None})
        self.assertTrue(any('ciclo' in e for e in _errores(sankey)))

        sankey = _visual('sankey')
        sankey['datos']['flujos'][0]['valor'] = -3
        self.assertTrue(any('no negativo' in e for e in _errores(sankey)))

        sankey = _visual('sankey')
        sankey['datos']['flujos'][0]['destino'] = 'no-existe'
        self.assertTrue(any('nodos existentes' in e for e in _errores(sankey)))

    def test_treemap_hojas_con_valor_y_ramas_en_null(self):
        treemap = _visual('treemap')
        hoja = next(n for n in treemap['datos']['nodos'] if n['valor'] is not None)
        hoja['valor'] = None
        self.assertTrue(any('hoja necesita valor' in e for e in _errores(treemap)))

        treemap = _visual('treemap')
        rama = next(n for n in treemap['datos']['nodos'] if n['padre'] is None)
        rama['valor'] = 10
        self.assertTrue(any('valor null' in e for e in _errores(treemap)))

    def test_treemap_sin_raiz_o_con_ciclo(self):
        treemap = _visual('treemap')
        nodos = treemap['datos']['nodos']
        raiz = next(n for n in nodos if n['padre'] is None)
        hijo = next(n for n in nodos if n['padre'] == raiz['id'])
        for nodo in nodos:
            if nodo['padre'] is None:
                nodo['padre'] = hijo['id']
        errores = _errores(treemap)
        self.assertTrue(any('ninguna raíz' in e for e in errores))
        self.assertTrue(any('ciclo' in e for e in errores))

    def test_grafo_con_grupos_inexistentes(self):
        grafo = _visual('grafo')
        grafo['datos']['nodos'][0]['grupo'] = 'g_inventado'
        self.assertTrue(any('no existe en datos.grupos' in e for e in _errores(grafo)))

    def test_la_red_semantica_no_usa_relaciones_de_entidades(self):
        red = _visual('red_semantica')
        red['datos']['tipo_relacion'] = 'influencia'
        self.assertTrue(any("usa 'grafo'" in e for e in _errores(red)))
        grafo = _visual('grafo')
        grafo['datos']['tipo_relacion'] = 'influencia'
        self.assertEqual(_errores(grafo), [])


class AnalisisV2GuardadosTests(APITestCase):
    """Lo guardado en v2 no se toca y se sigue pudiendo usar."""

    def setUp(self):
        self.client.force_authenticate(user=crear_admin_completo('admin_v21'))
        self.d = crear_jornada_completa()

    def test_un_analisis_v2_guardado_se_puede_resumir(self):
        from unittest.mock import patch

        from .v2.contrato import MODO_INTEGRAL
        from .v2.entrada import construir_entrada
        from .v2.sin_datos import construir_salida_sin_datos

        entrada = construir_entrada(self.d['jornada'], MODO_INTEGRAL, [])
        resultado = construir_salida_sin_datos(entrada, 'llm')
        resultado['version'] = 'kunsamu.analisis/v2'
        viejo = AnalisisJornadaIA.objects.create(
            jornada=self.d['jornada'], estado='completo', entrada=entrada, resultado=resultado,
        )
        with patch('analitica.admin_views.threading.Thread'):
            resp = self.client.post('/api/admin/resumenes-presentacion/', {'analisis_jornada': viejo.id}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)


class ResumenSaleEnV21Tests(TestCase):
    def test_el_resumen_de_un_analisis_v2_sale_en_v2_1(self):
        from .models import ResumenPresentacion
        from .v2.background import adaptador_de
        from .v2.contrato import MODO_INTEGRAL
        from .v2.entrada import construir_entrada
        from .v2.sin_datos import construir_salida_sin_datos

        d = crear_jornada_completa()
        entrada = construir_entrada(d['jornada'], MODO_INTEGRAL, [])
        original = construir_salida_sin_datos(entrada, 'llm')
        original['version'] = 'kunsamu.analisis/v2'
        analisis = AnalisisJornadaIA.objects.create(jornada=d['jornada'], estado='completo', entrada=entrada, resultado=original)
        resumen = ResumenPresentacion.objects.create(analisis_jornada=analisis, jornada=d['jornada'], diagnostico={'intentos': [{}]})
        parte = {k: original[k] for k in ('informes', 'visualizaciones', 'limitaciones')}
        completa, errores = adaptador_de(ResumenPresentacion).evaluar(resumen, parte, {}, ultimo=True)
        self.assertEqual(errores, [])
        self.assertEqual(completa['version'], VERSION)


class ActualizarPromptsTests(TestCase):
    def test_crea_y_activa_las_versiones_v2_1_y_es_idempotente(self):
        from io import StringIO

        from django.core.management import call_command

        from .models import SystemPrompt

        antes = {t: SystemPrompt.activo_de(t).version for t in ('analisis_llm', 'analisis_bertopic', 'resumen_presentacion')}
        call_command('actualizar_prompts_v2_1', '--activar', stdout=StringIO())
        for tipo, version in antes.items():
            nuevo = SystemPrompt.activo_de(tipo)
            self.assertEqual(nuevo.version, version + 1, tipo)
            self.assertIn('kunsamu.analisis/v2.1', nuevo.contenido)
            self.assertNotRegex(nuevo.contenido, r'kunsamu\.analisis/v2(?![.\d])')
            self.assertIn('contrato v2.1', nuevo.contenido)
        llm = SystemPrompt.activo_de('analisis_llm').contenido
        self.assertIn('Entre 5 y 8 hallazgos', llm)
        self.assertNotIn('Habitualmente bastan de 3 a 6', llm)
        self.assertIn('sankey', llm)
        call_command('actualizar_prompts_v2_1', '--activar', stdout=StringIO())
        self.assertEqual(SystemPrompt.activo_de('analisis_llm').version, antes['analisis_llm'] + 1)
