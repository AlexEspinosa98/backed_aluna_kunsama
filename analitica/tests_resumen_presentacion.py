"""HU-99: resumen de un análisis terminado para presentarlo en diapositivas. OpenAI se simula a
nivel de `crear_respuesta`/`consultar_respuesta`; el resto es el código real."""
import json
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import AnalisisJornadaIA, ResumenPresentacion, SystemPrompt
from .resumen_presentacion import generar_resumen_presentacion
from .tests import crear_admin_completo
from .tests_v2 import crear_jornada_completa
from .v2 import background
from .v2.contrato import MODO_INTEGRAL
from .v2.entrada import construir_entrada
from .v2.sin_datos import construir_salida_sin_datos

MODULO = 'analitica.v2.background'


def _respuesta(id_='resp_1', status='queued', salida=None):
    return SimpleNamespace(
        id=id_, status=status, service_tier='default', output=[], error=None, incomplete_details=None,
        output_text=json.dumps(salida) if salida is not None else '', usage=None,
    )


def _analisis_completo(jornada, **extra):
    """Un análisis integral terminado con salida v2 válida (la forma sin_datos, que valida siempre
    contra su propia entrada) y su entrada guardada."""
    entrada = construir_entrada(jornada, MODO_INTEGRAL, [])
    return AnalisisJornadaIA.objects.create(
        jornada=jornada, estado=AnalisisJornadaIA.ESTADO_COMPLETO, entrada=entrada,
        resultado=construir_salida_sin_datos(entrada, 'llm'), **extra,
    )


class BaseResumen(TestCase):
    def setUp(self):
        self.d = crear_jornada_completa()
        self.analisis = _analisis_completo(self.d['jornada'])
        self.resumen = ResumenPresentacion.objects.create(
            analisis_jornada=self.analisis, jornada=self.d['jornada'], instrucciones='Para rectoría, 6 diapositivas',
        )
        self.creadas = []

    def _crear(self, *ids):
        ids = iter(ids or ('resp_1', 'resp_2'))

        def crear(system, user, modelo, esfuerzo, flex, reparacion=None, esquema=None):
            self.creadas.append({'system': system, 'user': user, 'reparacion': reparacion, 'esquema': esquema})
            return _respuesta(next(ids)), {}
        return patch(f'{MODULO}.crear_respuesta', side_effect=crear)

    def _lanzar(self):
        with self._crear(), patch(f'{MODULO}.seguir_hasta_terminar'):
            generar_resumen_presentacion(self.resumen.id)
        self.resumen.refresh_from_db()

    def _avanzar_con(self, resp):
        with patch(f'{MODULO}.consultar_respuesta', return_value=resp):
            terminado = background.avanzar_en_segundo_plano(ResumenPresentacion, self.resumen.id)
        self.resumen.refresh_from_db()
        return terminado

    def _parte_valida(self):
        original = self.analisis.resultado
        return {k: original[k] for k in ('informes', 'visualizaciones', 'limitaciones')}


class LanzarTests(BaseResumen):
    def test_manda_el_analisis_sin_cobertura_y_pide_solo_la_parte_editorial(self):
        self._lanzar()
        self.assertEqual(self.resumen.estado, ResumenPresentacion.ESTADO_PROCESANDO)
        llamada = self.creadas[0]
        self.assertEqual(llamada['system'], SystemPrompt.activo_de('resumen_presentacion').contenido)
        enviado = json.loads(llamada['user'])
        self.assertEqual(enviado['instrucciones_usuario'], 'Para rectoría, 6 diapositivas')
        self.assertEqual(enviado['jornada']['nombre'], self.d['jornada'].nombre)
        self.assertIn('informes', enviado['analisis'])
        self.assertNotIn('cobertura', enviado['analisis'])
        self.assertEqual(set(llamada['esquema']['properties']), {'informes', 'visualizaciones', 'limitaciones'})
        self.assertIn('$defs', llamada['esquema'])
        self.assertEqual(self.resumen.version_prompt, 'resumen_presentacion#1')


class AvanzarTests(BaseResumen):
    def setUp(self):
        super().setUp()
        self._lanzar()

    def test_completa_el_contrato_con_lo_del_original_y_valida(self):
        parte = self._parte_valida()
        self.assertTrue(self._avanzar_con(_respuesta(status='completed', salida=parte)))
        self.assertEqual(self.resumen.estado, ResumenPresentacion.ESTADO_COMPLETO, self.resumen.error_mensaje)
        original = self.analisis.resultado
        for clave in ('version', 'pipeline', 'estado', 'alcance', 'fuentes', 'cobertura'):
            self.assertEqual(self.resumen.resultado[clave], original[clave], clave)
        self.assertEqual(self.resumen.resultado['informes'], parte['informes'])
        self.assertEqual(self.resumen.prompt_usado, SystemPrompt.activo_de('resumen_presentacion').contenido)

    def test_lo_que_no_valida_contra_la_entrada_original_se_repara(self):
        parte = self._parte_valida()
        parte['informes'][0]['momento_ids'] = ['999']  # informes distintos a los del original
        with self._crear('resp_2'):
            self.assertFalse(self._avanzar_con(_respuesta(status='completed', salida=parte)))
        self.assertEqual(self.resumen.fase_openai, ResumenPresentacion.FASE_REPARACION)
        reparacion = self.creadas[-1]['reparacion']
        self.assertEqual(reparacion['salida_previa'], parte)  # lo que escribió el modelo, no lo completado
        self.assertTrue(any('momento_ids' in e for e in reparacion['errores']))
        self.assertEqual(self.creadas[0]['user'], self.creadas[-1]['user'])

    def test_el_cron_tambien_retoma_resumenes(self):
        ResumenPresentacion.objects.filter(pk=self.resumen.pk).update(consultado_en=timezone.now() - timedelta(minutes=5))
        with patch(f'{MODULO}.consultar_respuesta',
                   return_value=_respuesta(status='completed', salida=self._parte_valida())):
            call_command('consultar_analisis_background', stdout=StringIO())
        self.resumen.refresh_from_db()
        self.assertEqual(self.resumen.estado, ResumenPresentacion.ESTADO_COMPLETO)


class ApiTests(APITestCase):
    URL = '/api/admin/resumenes-presentacion/'

    def setUp(self):
        self.client.force_authenticate(user=crear_admin_completo('admin_resumen'))
        self.d = crear_jornada_completa()
        self.analisis = _analisis_completo(self.d['jornada'])

    def _post(self, cuerpo):
        with patch('analitica.admin_views.threading.Thread') as hilo:
            return self.client.post(self.URL, cuerpo, format='json'), hilo

    def test_crea_y_lanza(self):
        resp, hilo = self._post({'analisis_jornada': self.analisis.id, 'instrucciones': 'Breve', 'flex': True})
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['estado'], 'pendiente')
        self.assertEqual(resp.data['fuente'], {'tipo': 'analisis_jornada', 'id': self.analisis.id})
        self.assertTrue(resp.data['flex'])
        hilo.return_value.start.assert_called_once()

    def test_el_detalle_devuelve_la_salida_estructurada(self):
        resumen = ResumenPresentacion.objects.create(
            analisis_jornada=self.analisis, jornada=self.d['jornada'],
            estado=ResumenPresentacion.ESTADO_COMPLETO, resultado=self.analisis.resultado,
        )
        datos = self.client.get(f'{self.URL}{resumen.id}/').data
        self.assertEqual(datos['resultado']['version'], 'kunsamu.analisis/v2')
        self.assertNotIn('resultado', self.client.get(self.URL).data[0])

    def test_origen_invalido_es_400(self):
        self.assertEqual(self._post({})[0].status_code, 400)
        otro = _analisis_completo(self.d['jornada'])
        self.assertEqual(self._post({'analisis_jornada': self.analisis.id, 'analisis_v2': None,
                                     'reporte': None})[0].status_code, 201)
        self.assertEqual(self._post({'analisis_jornada': otro.id, 'modelo': 'gpt-inventado'})[0].status_code, 400)

    def test_un_analisis_sin_terminar_o_anterior_al_v2_no_se_resume(self):
        en_curso = AnalisisJornadaIA.objects.create(jornada=self.d['jornada'], estado=AnalisisJornadaIA.ESTADO_PROCESANDO)
        self.assertEqual(self._post({'analisis_jornada': en_curso.id})[0].status_code, 400)
        viejo = AnalisisJornadaIA.objects.create(
            jornada=self.d['jornada'], estado=AnalisisJornadaIA.ESTADO_COMPLETO, resultado={'hallazgos': []},
        )
        resp = self._post({'analisis_jornada': viejo.id})[0]
        self.assertEqual(resp.status_code, 400)
        self.assertIn('anterior al contrato', str(resp.data))

    def test_uno_en_curso_por_analisis(self):
        self.assertEqual(self._post({'analisis_jornada': self.analisis.id})[0].status_code, 201)
        self.assertEqual(self._post({'analisis_jornada': self.analisis.id})[0].status_code, 409)

    def test_borrar_uno_en_curso_lo_cancela_en_openai(self):
        resumen = ResumenPresentacion.objects.create(
            analisis_jornada=self.analisis, jornada=self.d['jornada'],
            estado=ResumenPresentacion.ESTADO_PROCESANDO, respuesta_openai_id='resp_x',
        )
        with patch(f'{MODULO}.cancelar_respuesta') as cancelar:
            self.assertEqual(self.client.delete(f'{self.URL}{resumen.id}/').status_code, 204)
        cancelar.assert_called_once_with('resp_x')
