"""Ajuste de un análisis ya terminado (HU-102). Sin llamadas reales a OpenAI: la creación y la
consulta de la respuesta en segundo plano se mockean."""
import json
import shutil
import tempfile
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from jornadas.models import JornadaAsset

from .ajuste_analisis import entrada_del_ajuste, procesar_ajuste
from .models import AnalisisJornadaIA, AnalisisV2, SystemPrompt
from .tests import crear_admin_completo
from .tests_v2 import crear_jornada_completa
from .v2 import background
from .v2.contrato import MODO_INTEGRAL, VERSION
from .v2.entrada import construir_entrada
from .v2.sin_datos import construir_salida_sin_datos

MODULO = 'analitica.v2.background'
MEDIA_TEMPORAL = tempfile.mkdtemp(prefix='kunsamu-tests-ajuste-')


def _analisis_completo(jornada):
    """Un análisis integral terminado: la salida es la forma sin_datos (valida siempre contra su
    entrada) pero con estado analítico `completo`, que es lo que se puede ajustar."""
    entrada = construir_entrada(jornada, MODO_INTEGRAL, [])
    resultado = construir_salida_sin_datos(entrada, 'llm')
    resultado['estado'] = 'completo'
    return AnalisisJornadaIA.objects.create(
        jornada=jornada, estado=AnalisisJornadaIA.ESTADO_COMPLETO, entrada=entrada, resultado=resultado,
    )


def _respuesta(id_='resp_1', status='queued', salida=None):
    return SimpleNamespace(
        id=id_, status=status, service_tier='default', output=[], error=None, incomplete_details=None,
        output_text=json.dumps(salida) if salida is not None else '', usage=None,
    )


@override_settings(MEDIA_ROOT=MEDIA_TEMPORAL)
class ApiAjusteTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TEMPORAL, ignore_errors=True)

    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.client.force_authenticate(user=self.admin)
        self.d = crear_jornada_completa()
        self.origen = _analisis_completo(self.d['jornada'])

    def _post(self, cuerpo):
        with patch('analitica.admin_views.threading.Thread') as hilo:
            resp = self.client.post('/api/admin/analisis-v2/ajustar/', cuerpo, format='json')
        return resp, hilo

    def test_crea_un_analisis_v2_nuevo_marcado_como_ajuste(self):
        resp, hilo = self._post({'analisis_jornada': self.origen.id, 'instrucciones': 'Más foco en horarios', 'flex': True})
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.data['es_ajuste'])
        self.assertEqual(resp.data['ajuste_de'], {'tipo': 'analisis_jornada', 'id': self.origen.id})
        self.assertEqual((resp.data['modo'], resp.data['pipeline']), ('integral', 'llm'))
        self.assertEqual(resp.data['instrucciones'], 'Más foco en horarios')
        self.assertTrue(resp.data['flex'])
        hilo.return_value.start.assert_called_once()
        self.origen.refresh_from_db()
        self.assertEqual(self.origen.estado, AnalisisJornadaIA.ESTADO_COMPLETO)

    def test_aparece_en_la_lista_unificada_como_ajuste(self):
        resp, _ = self._post({'analisis_jornada': self.origen.id, 'instrucciones': 'x'})
        lista = self.client.get(f'/api/admin/analisis/?jornada={self.d["jornada"].id}')
        item = next(i for i in lista.data if i['tipo'] == 'analisis_v2' and i['id'] == resp.data['id'])
        self.assertTrue(item['es_ajuste'])
        self.assertEqual(item['ajuste_de'], {'tipo': 'analisis_jornada', 'id': self.origen.id})

    def test_rechazos(self):
        casos = [
            {'analisis_jornada': self.origen.id},  # sin instrucciones
            {'analisis_jornada': self.origen.id, 'instrucciones': '   '},
            {'instrucciones': 'x'},  # sin origen
        ]
        incompleto = AnalisisJornadaIA.objects.create(jornada=self.d['jornada'])
        casos.append({'analisis_jornada': incompleto.id, 'instrucciones': 'x'})
        sin_datos = _analisis_completo(self.d['jornada'])
        sin_datos.resultado['estado'] = 'sin_datos'
        sin_datos.save()
        casos.append({'analisis_jornada': sin_datos.id, 'instrucciones': 'x'})
        for cuerpo in casos:
            resp, _ = self._post(cuerpo)
            self.assertEqual(resp.status_code, 400, cuerpo)

    def test_409_si_ya_hay_un_ajuste_en_curso_del_mismo_analisis(self):
        self._post({'analisis_jornada': self.origen.id, 'instrucciones': 'x'})
        resp, _ = self._post({'analisis_jornada': self.origen.id, 'instrucciones': 'y'})
        self.assertEqual(resp.status_code, 409)

    def test_un_ajuste_en_curso_no_bloquea_ni_lo_marca_huerfano_un_analisis_nuevo(self):
        resp, _ = self._post({'analisis_jornada': self.origen.id, 'instrucciones': 'x'})
        AnalisisV2.objects.filter(pk=resp.data['id']).update(
            estado=AnalisisV2.ESTADO_PROCESANDO, actualizado_en=timezone.now() - timedelta(hours=1),
        )
        with patch('analitica.admin_views.threading.Thread'):
            nuevo = self.client.post('/api/admin/analisis-v2/', {
                'jornada': self.d['jornada'].id, 'modo': 'integral', 'pipeline': 'llm',
            }, format='json')
        self.assertEqual(nuevo.status_code, 201, nuevo.data)
        self.assertEqual(AnalisisV2.objects.get(pk=resp.data['id']).estado, AnalisisV2.ESTADO_PROCESANDO)

    def test_se_puede_ajustar_un_ajuste(self):
        resp, _ = self._post({'analisis_jornada': self.origen.id, 'instrucciones': 'x'})
        primero = AnalisisV2.objects.get(pk=resp.data['id'])
        primero.estado = AnalisisV2.ESTADO_COMPLETO
        primero.entrada = self.origen.entrada
        primero.resultado = self.origen.resultado
        primero.save()
        resp, _ = self._post({'analisis_v2': primero.id, 'instrucciones': 'otra vuelta'})
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['ajuste_de'], {'tipo': 'analisis_v2', 'id': primero.id})

    def test_adjunto_de_otra_jornada_se_rechaza(self):
        from .tests import crear_jornada

        ajeno = JornadaAsset.objects.create(
            jornada=crear_jornada('otra'), tipo=JornadaAsset.TIPO_DOCUMENTO,
            archivo=SimpleUploadedFile('x.txt', b'x'), nombre_archivo_original='x.txt',
        )
        resp, _ = self._post({'analisis_jornada': self.origen.id, 'instrucciones': 'x', 'adjuntos': [ajeno.id]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('adjuntos', resp.data)


@override_settings(MEDIA_ROOT=MEDIA_TEMPORAL)
class EntradaDelAjusteTests(TestCase):
    def setUp(self):
        self.d = crear_jornada_completa()
        self.origen = _analisis_completo(self.d['jornada'])

    def test_conserva_la_entrada_original_y_suma_el_bloque_ajuste(self):
        entrada = entrada_del_ajuste(self.origen, self.d['jornada'], 'Más foco', 'Contexto nuevo')
        self.assertEqual(entrada['fuentes'], self.origen.entrada['fuentes'])
        self.assertEqual(entrada['solicitud'], self.origen.entrada['solicitud'])
        self.assertEqual(entrada['ajuste']['instrucciones_ajuste'], 'Más foco')
        self.assertEqual(entrada['ajuste']['contexto_ajuste'], 'Contexto nuevo')
        self.assertEqual(entrada['ajuste']['analisis_previo']['informes'], self.origen.resultado['informes'])
        self.assertEqual(entrada['ajuste']['analisis_previo']['version'], VERSION)
        self.assertNotIn('ajuste', self.origen.entrada)

    def test_adjunto_nuevo_como_fuente_se_suma_al_final_y_no_se_duplica(self):
        doc = JornadaAsset.objects.create(
            jornada=self.d['jornada'], tipo=JornadaAsset.TIPO_DOCUMENTO,
            archivo=SimpleUploadedFile('a.txt', b'Texto del acuerdo'), nombre_archivo_original='a.txt',
        )
        pedido = [{'asset': doc.id, 'uso': 'fuente'}]
        entrada = entrada_del_ajuste(self.origen, self.d['jornada'], 'x', adjuntos=pedido)
        n = len(self.origen.entrada['fuentes'])
        self.assertEqual(entrada['fuentes'][:n], self.origen.entrada['fuentes'])
        self.assertEqual(entrada['fuentes'][n]['id'], f'f-adj{doc.id}')
        self.origen.entrada = entrada
        otra = entrada_del_ajuste(self.origen, self.d['jornada'], 'y', adjuntos=pedido)
        self.assertEqual([f['id'] for f in otra['fuentes']].count(f'f-adj{doc.id}'), 1)

    def test_demasiado_grande_falla_con_motivo(self):
        with patch('analitica.ajuste_analisis.MAX_CARACTERES_ENTRADA', 10):
            with self.assertRaisesRegex(ValueError, 'demasiado grande'):
                entrada_del_ajuste(self.origen, self.d['jornada'], 'x')


class ProcesarAjusteTests(TestCase):
    def setUp(self):
        self.d = crear_jornada_completa()
        self.origen = _analisis_completo(self.d['jornada'])
        self.ajuste = AnalisisV2.objects.create(
            jornada=self.d['jornada'], modo='integral', pipeline='llm', es_ajuste=True,
            ajuste_de_analisis_jornada=self.origen, instrucciones='Más foco en horarios',
        )
        self.creadas = []

    def _lanzar(self):
        def crear(system, user, modelo, esfuerzo, flex, reparacion=None, esquema=None):
            self.creadas.append({'system': system, 'user': user, 'esquema': esquema})
            return _respuesta(f'resp_{len(self.creadas)}'), {}
        with patch(f'{MODULO}.crear_respuesta', side_effect=crear), patch(f'{MODULO}.seguir_hasta_terminar'):
            procesar_ajuste(self.ajuste.id)
        self.ajuste.refresh_from_db()

    def test_lanza_con_el_prompt_del_analisis_mas_el_del_ajuste(self):
        self._lanzar()
        self.assertEqual(self.ajuste.estado, AnalisisV2.ESTADO_PROCESANDO, self.ajuste.error_mensaje)
        self.assertEqual(self.ajuste.respuesta_openai_id, 'resp_1')
        base = SystemPrompt.activo_de('analisis_llm')
        ajuste = SystemPrompt.activo_de('ajuste_analisis')
        self.assertEqual(self.ajuste.version_prompt, f'{base.referencia}+{ajuste.referencia}')
        [llamada] = self.creadas
        self.assertEqual(llamada['system'], base.contenido.rstrip() + '\n\n' + ajuste.contenido.rstrip())
        self.assertIsNone(llamada['esquema'])
        self.assertEqual(json.loads(llamada['user'])['ajuste']['instrucciones_ajuste'], 'Más foco en horarios')

    def test_salida_valida_se_publica(self):
        self._lanzar()
        salida = construir_salida_sin_datos(self.ajuste.entrada, 'llm')
        with patch(f'{MODULO}.consultar_respuesta', return_value=_respuesta(status='completed', salida=salida)):
            terminado = background.avanzar_en_segundo_plano(AnalisisV2, self.ajuste.id)
        self.ajuste.refresh_from_db()
        self.assertTrue(terminado)
        self.assertEqual(self.ajuste.estado, AnalisisV2.ESTADO_COMPLETO, self.ajuste.error_mensaje)
        self.assertEqual(self.ajuste.resultado['alcance'], self.origen.entrada['solicitud'])

    def test_salida_invalida_lanza_una_reparacion(self):
        self._lanzar()
        with patch(f'{MODULO}.consultar_respuesta', return_value=_respuesta(status='completed', salida={'version': VERSION})), \
                patch(f'{MODULO}.crear_respuesta', return_value=(_respuesta('resp_2'), {})) as crear:
            background.avanzar_en_segundo_plano(AnalisisV2, self.ajuste.id)
        self.ajuste.refresh_from_db()
        self.assertEqual(self.ajuste.fase_openai, AnalisisV2.FASE_REPARACION)
        self.assertIsNotNone(crear.call_args.kwargs['reparacion'])

    def test_origen_borrado_termina_en_error(self):
        self.origen.delete()
        self.ajuste.refresh_from_db()
        self._lanzar()
        self.assertEqual(self.ajuste.estado, AnalisisV2.ESTADO_ERROR)
        self.assertIn('ya no existe', self.ajuste.error_mensaje)
