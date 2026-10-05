"""HU-98: el análisis integral de la jornada en el modo segundo plano de OpenAI. OpenAI se simula
a nivel de `crear_respuesta`/`consultar_respuesta`; todo lo demás es el código real."""
import json
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import openai
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from auditoria.openai_cliente import httpx

from .analisis_ia_openai import analizar_jornada_ia
from .models import AnalisisJornadaIA, SystemPrompt
from .tests import crear_admin_completo
from .tests_v2 import crear_jornada_completa
from .v2 import background
from .v2.sin_datos import construir_salida_sin_datos

MODULO = 'analitica.v2.background'


def respuesta(id_='resp_1', status='queued', salida=None, **extra):
    return SimpleNamespace(
        id=id_, status=status, service_tier=extra.pop('service_tier', 'default'), output=[],
        output_text=json.dumps(salida) if salida is not None else '',
        usage=SimpleNamespace(
            input_tokens=300000, output_tokens=20000,
            input_tokens_details=SimpleNamespace(cached_tokens=0),
            output_tokens_details=SimpleNamespace(reasoning_tokens=12000),
        ) if status == 'completed' else None,
        error=extra.pop('error', None), incomplete_details=extra.pop('incomplete_details', None),
    )


class BaseBackground(TestCase):
    def setUp(self):
        self.d = crear_jornada_completa()
        self.analisis = AnalisisJornadaIA.objects.create(jornada=self.d['jornada'], instrucciones='I')
        self.creadas = []

    def _crear(self, *ids):
        """Simula `crear_respuesta`: registra cada llamada y devuelve ids en orden."""
        ids = iter(ids or ('resp_1', 'resp_2'))

        def crear(system, user, modelo, esfuerzo, flex, reparacion=None):
            self.creadas.append({'system': system, 'user': user, 'modelo': modelo, 'esfuerzo': esfuerzo,
                                 'flex': flex, 'reparacion': reparacion})
            return respuesta(next(ids)), {}
        return patch(f'{MODULO}.crear_respuesta', side_effect=crear)

    def _lanzar(self):
        with self._crear(), patch(f'{MODULO}.seguir_hasta_terminar'):
            analizar_jornada_ia(self.analisis.id)
        self.analisis.refresh_from_db()

    def _avanzar_con(self, resp):
        with patch(f'{MODULO}.consultar_respuesta', return_value=resp):
            terminado = background.avanzar_analisis_background(self.analisis.id)
        self.analisis.refresh_from_db()
        return terminado

    def _valida(self):
        return construir_salida_sin_datos(self.analisis.entrada, 'llm')


class LanzarTests(BaseBackground):
    def test_lanza_en_segundo_plano_con_la_configuracion_por_defecto(self):
        self._lanzar()
        self.assertEqual(self.analisis.estado, AnalisisJornadaIA.ESTADO_PROCESANDO)
        self.assertEqual((self.analisis.respuesta_openai_id, self.analisis.fase_openai), ('resp_1', 'intento'))
        llamada = self.creadas[0]
        self.assertEqual(llamada['system'], SystemPrompt.activo_de('analisis_llm').contenido)
        self.assertEqual(json.loads(llamada['user']), self.analisis.entrada)
        self.assertEqual((llamada['modelo'], llamada['esfuerzo'], llamada['flex']),
                         (background.DEFAULT_MODEL, background.REASONING_EFFORT, False))
        self.assertEqual(self.analisis.diagnostico['modo'], 'background')
        self.assertFalse(self.analisis.diagnostico['store'])

    def test_usa_lo_que_pidio_quien_lo_lanzo(self):
        AnalisisJornadaIA.objects.filter(pk=self.analisis.pk).update(
            modelo_solicitado='gpt-5.6-terra', esfuerzo_solicitado='xhigh', flex=True,
        )
        self._lanzar()
        self.assertEqual((self.creadas[0]['modelo'], self.creadas[0]['esfuerzo'], self.creadas[0]['flex']),
                         ('gpt-5.6-terra', 'xhigh', True))

    def test_sin_datos_termina_sin_llamar_a_openai(self):
        from jornadas.models import Jornada, Momento, Pregunta

        vacia = Jornada.objects.create(slug='vacia', nombre='V', fecha_inicio='2026-09-01', fecha_fin='2026-09-01')
        Pregunta.objects.create(momento=Momento.objects.create(jornada=vacia, orden=1, titulo='M'),
                                tipo='abierta', texto='¿?', orden=1)
        self.analisis = AnalisisJornadaIA.objects.create(jornada=vacia)
        self._lanzar()
        self.assertEqual(self.creadas, [])
        self.assertEqual(self.analisis.estado, AnalisisJornadaIA.ESTADO_COMPLETO)
        self.assertEqual(self.analisis.resultado['estado'], 'sin_datos')


class AvanzarTests(BaseBackground):
    def setUp(self):
        super().setUp()
        self._lanzar()

    def test_en_curso_solo_registra_la_consulta(self):
        antes = self.analisis.consultado_en
        self.assertFalse(self._avanzar_con(respuesta(status='in_progress')))
        self.assertEqual(self.analisis.estado, AnalisisJornadaIA.ESTADO_PROCESANDO)
        self.assertGreaterEqual(self.analisis.consultado_en, antes)

    def test_completada_y_valida_se_publica(self):
        salida = self._valida()
        self.assertTrue(self._avanzar_con(respuesta(status='completed', salida=salida)))
        self.assertEqual(self.analisis.estado, AnalisisJornadaIA.ESTADO_COMPLETO, self.analisis.error_mensaje)
        self.assertEqual(self.analisis.resultado, salida)
        self.assertEqual(self.analisis.prompt_usado, SystemPrompt.activo_de('analisis_llm').contenido)
        uso = self.analisis.diagnostico['intentos'][0]['usage']
        self.assertEqual((uso['input_tokens'], uso['reasoning_tokens']), (300000, 12000))

    def test_invalida_lanza_la_reparacion_con_el_mismo_texto_de_entrada(self):
        with self._crear('resp_2'):
            terminado = self._avanzar_con(respuesta(status='completed', salida={'version': 'x'}))
        self.assertFalse(terminado)
        self.assertEqual((self.analisis.respuesta_openai_id, self.analisis.fase_openai), ('resp_2', 'reparacion'))
        intento, reparacion = self.creadas
        self.assertEqual(reparacion['reparacion']['salida_previa'], {'version': 'x'})
        self.assertTrue(reparacion['reparacion']['errores'])
        # Mismo texto exacto: es lo que permite que la reparación use la caché de OpenAI.
        self.assertEqual(intento['user'], reparacion['user'])

    def test_reparacion_invalida_termina_en_error(self):
        with self._crear('resp_2'):
            self._avanzar_con(respuesta(status='completed', salida={'version': 'x'}))
        self.assertTrue(self._avanzar_con(respuesta('resp_2', status='completed', salida={'version': 'x'})))
        self.assertEqual(self.analisis.estado, AnalisisJornadaIA.ESTADO_ERROR)
        self.assertIn('tras un reintento de reparación', self.analisis.error_mensaje)

    def test_reparacion_valida_se_publica(self):
        with self._crear('resp_2'):
            self._avanzar_con(respuesta(status='completed', salida={'version': 'x'}))
        self.assertTrue(self._avanzar_con(respuesta('resp_2', status='completed', salida=self._valida())))
        self.assertEqual(self.analisis.estado, AnalisisJornadaIA.ESTADO_COMPLETO, self.analisis.error_mensaje)
        self.assertEqual(len(self.analisis.diagnostico['intentos']), 2)

    def test_incompleta_por_tokens_explica_el_motivo(self):
        self._avanzar_con(respuesta(status='incomplete', incomplete_details={'reason': 'max_output_tokens'}))
        self.assertEqual(self.analisis.estado, AnalisisJornadaIA.ESTADO_ERROR)
        self.assertIn('max_output_tokens', self.analisis.error_mensaje)

    def test_si_openai_ya_la_borro_termina_en_error_explicito(self):
        no_existe = openai.NotFoundError(
            'not found', response=httpx.Response(404, request=httpx.Request('GET', 'https://x')), body=None,
        )
        with patch(f'{MODULO}.consultar_respuesta', side_effect=no_existe):
            self.assertTrue(background.avanzar_analisis_background(self.analisis.id))
        self.analisis.refresh_from_db()
        self.assertEqual(self.analisis.estado, AnalisisJornadaIA.ESTADO_ERROR)
        self.assertIn('ya no tiene la respuesta', self.analisis.error_mensaje)

    def test_una_falla_al_consultar_no_mata_el_analisis(self):
        with patch(f'{MODULO}.consultar_respuesta', side_effect=RuntimeError('red caída')):
            self.assertFalse(background.avanzar_analisis_background(self.analisis.id))
        self.analisis.refresh_from_db()
        self.assertEqual(self.analisis.estado, AnalisisJornadaIA.ESTADO_PROCESANDO)

    def test_pasado_el_maximo_se_cancela_en_openai(self):
        AnalisisJornadaIA.objects.filter(pk=self.analisis.pk).update(
            creado_en=timezone.now() - background.DURACION_MAXIMA - timedelta(minutes=1),
        )
        with patch(f'{MODULO}.cancelar_respuesta') as cancelar:
            self._avanzar_con(respuesta(status='in_progress'))
        cancelar.assert_called_once_with('resp_1')
        self.assertEqual(self.analisis.estado, AnalisisJornadaIA.ESTADO_ERROR)

    def test_el_cron_retoma_lo_que_nadie_consulto(self):
        AnalisisJornadaIA.objects.filter(pk=self.analisis.pk).update(
            consultado_en=timezone.now() - timedelta(minutes=5),
        )
        with patch(f'{MODULO}.consultar_respuesta', return_value=respuesta(status='completed', salida=self._valida())):
            call_command('consultar_analisis_background', stdout=StringIO())
        self.analisis.refresh_from_db()
        self.assertEqual(self.analisis.estado, AnalisisJornadaIA.ESTADO_COMPLETO)

    def test_el_cron_no_toca_lo_consultado_hace_menos_de_un_minuto(self):
        with patch(f'{MODULO}.consultar_respuesta') as consultar:
            call_command('consultar_analisis_background', stdout=StringIO())
        consultar.assert_not_called()


class FlexTests(TestCase):
    def test_sin_capacidad_flex_se_lanza_en_el_tier_normal_y_queda_anotado(self):
        sin_capacidad = openai.RateLimitError(
            'Resource unavailable', response=httpx.Response(429, request=httpx.Request('POST', 'https://x')),
            body=None,
        )
        cliente = SimpleNamespace(responses=SimpleNamespace())
        cliente.with_options = lambda **_: cliente
        llamadas = []

        def crear(**kwargs):
            llamadas.append(kwargs)
            if kwargs.get('service_tier') == 'flex':
                raise sin_capacidad
            return respuesta()
        cliente.responses.create = crear
        with patch(f'{MODULO}._cliente', return_value=cliente):
            resp, notas = background.crear_respuesta('S', 'U', 'gpt-6.1-sol', 'high', True)
        self.assertEqual([c.get('service_tier') for c in llamadas], ['flex', None])
        self.assertIn('flex_no_disponible', notas)
        self.assertEqual(llamadas[1]['reasoning'], {'effort': 'high'})
        self.assertTrue(llamadas[1]['background'])
        self.assertFalse(llamadas[1]['store'])
        self.assertEqual(llamadas[1]['text']['format']['type'], 'json_schema')


class ApiTests(APITestCase):
    URL = '/api/admin/analisis-jornada-ia/'

    def setUp(self):
        self.client.force_authenticate(user=crear_admin_completo('admin_bg'))
        self.d = crear_jornada_completa()

    def _post(self, **extra):
        with patch('analitica.admin_views.threading.Thread'):
            return self.client.post(self.URL, {'jornada': self.d['jornada'].id, **extra}, format='json')

    def test_sin_opciones_usa_la_configuracion(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 201, resp.data)
        detalle = self.client.get(f'{self.URL}{resp.data["id"]}/').data
        self.assertEqual((detalle['modelo'], detalle['esfuerzo'], detalle['flex']),
                         (background.DEFAULT_MODEL, background.REASONING_EFFORT, False))

    def test_con_modelo_esfuerzo_y_flex(self):
        resp = self._post(modelo='gpt-5.6-terra', esfuerzo='low', flex=True)
        self.assertEqual(resp.status_code, 201, resp.data)
        analisis = AnalisisJornadaIA.objects.get(pk=resp.data['id'])
        self.assertEqual((analisis.modelo_solicitado, analisis.esfuerzo_solicitado, analisis.flex),
                         ('gpt-5.6-terra', 'low', True))

    def test_modelo_o_esfuerzo_invalidos_son_400(self):
        self.assertEqual(self._post(modelo='gpt-inventado').status_code, 400)
        self.assertEqual(self._post(esfuerzo='altisimo').status_code, 400)

    def test_opciones(self):
        datos = self.client.get(f'{self.URL}opciones/').data
        self.assertIn(background.DEFAULT_MODEL, datos['modelos'])
        self.assertIn('high', datos['esfuerzos'])
        self.assertTrue(datos['segundo_plano'])

    def test_la_regla_de_huerfanos_no_mata_al_que_espera_a_openai(self):
        en_curso = AnalisisJornadaIA.objects.create(
            jornada=self.d['jornada'], estado=AnalisisJornadaIA.ESTADO_PROCESANDO, respuesta_openai_id='resp_x',
        )
        AnalisisJornadaIA.objects.filter(pk=en_curso.pk).update(actualizado_en=timezone.now() - timedelta(hours=1))
        self.assertEqual(self._post().status_code, 409)
        en_curso.refresh_from_db()
        self.assertEqual(en_curso.estado, AnalisisJornadaIA.ESTADO_PROCESANDO)

    def test_borrar_uno_en_curso_lo_cancela_en_openai(self):
        en_curso = AnalisisJornadaIA.objects.create(
            jornada=self.d['jornada'], estado=AnalisisJornadaIA.ESTADO_PROCESANDO, respuesta_openai_id='resp_x',
        )
        with patch(f'{MODULO}.cancelar_respuesta') as cancelar:
            self.assertEqual(self.client.delete(f'{self.URL}{en_curso.id}/').status_code, 204)
        cancelar.assert_called_once_with('resp_x')
