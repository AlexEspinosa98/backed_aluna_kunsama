"""HU-95: cada petición a OpenAI queda registrada completa en `LlamadaOpenAI`. Sin red: el SDK real
de OpenAI habla con un `httpx.MockTransport`."""
import datetime
import json
import threading
from unittest.mock import patch

import openai
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase

from jornadas.models import Jornada, Momento
from participantes.models import ExtraccionMomento

from .models import LlamadaOpenAI
from .openai_cliente import auditar_llamadas, cliente_openai, contexto_llamada, hilo_con_contexto, httpx

RESPUESTA_CHAT = {
    'id': 'chatcmpl-1', 'object': 'chat.completion', 'created': 1, 'model': 'gpt-prueba',
    'choices': [{'index': 0, 'finish_reason': 'stop',
                 'message': {'role': 'assistant', 'content': '{"ok": true}'}}],
    'usage': {'prompt_tokens': 120, 'completion_tokens': 30, 'total_tokens': 150},
}


def _transporte(estado=200, cuerpo=None):
    def responder(request):
        return httpx.Response(estado, json=cuerpo if cuerpo is not None else RESPUESTA_CHAT,
                              headers={'x-request-id': 'req_abc'})
    return httpx.MockTransport(responder)


def _chat(cliente):
    return cliente.chat.completions.create(
        model='gpt-prueba', max_completion_tokens=500,
        messages=[{'role': 'system', 'content': 'SYSTEM COMPLETO'},
                  {'role': 'user', 'content': 'USER COMPLETO'}],
    )


def _jornada():
    jornada = Jornada.objects.create(
        slug='j-aud', nombre='J', fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 2),
    )
    momento = Momento.objects.create(jornada=jornada, orden=1, titulo='M')
    return jornada, momento


class RegistroTests(TestCase):
    def test_guarda_la_peticion_y_la_respuesta_completas(self):
        cliente = cliente_openai('prueba', api_key='sk-secreta', transporte_base=_transporte())
        _chat(cliente)

        llamada = LlamadaOpenAI.objects.get()
        self.assertEqual(llamada.flujo, 'prueba')
        self.assertEqual(llamada.endpoint, '/v1/chat/completions')
        self.assertEqual(llamada.modelo, 'gpt-prueba')
        self.assertEqual(llamada.peticion['messages'][0]['content'], 'SYSTEM COMPLETO')
        self.assertEqual(llamada.peticion['messages'][1]['content'], 'USER COMPLETO')
        self.assertEqual(llamada.peticion['max_completion_tokens'], 500)
        self.assertEqual(llamada.respuesta['choices'][0]['message']['content'], '{"ok": true}')
        self.assertEqual((llamada.estado, llamada.status_code), ('ok', 200))
        self.assertEqual((llamada.tokens_entrada, llamada.tokens_salida, llamada.tokens_total), (120, 30, 150))
        self.assertEqual(llamada.request_id, 'req_abc')
        self.assertGreaterEqual(llamada.duracion_ms, 0)
        self.assertLessEqual(llamada.iniciado_en, llamada.finalizado_en)

    def test_nunca_guarda_la_api_key(self):
        _chat(cliente_openai('prueba', api_key='sk-secreta', transporte_base=_transporte()))
        llamada = LlamadaOpenAI.objects.get()
        self.assertNotIn('authorization', llamada.peticion_headers)
        self.assertNotIn('sk-secreta', json.dumps(llamada.peticion_headers))

    def test_un_error_de_openai_queda_registrado_y_la_excepcion_sigue(self):
        cliente = cliente_openai('prueba', api_key='k', max_retries=0, transporte_base=_transporte(
            400, {'error': {'message': 'context_length_exceeded', 'type': 'invalid_request_error'}},
        ))
        with self.assertRaises(openai.BadRequestError):
            _chat(cliente)
        llamada = LlamadaOpenAI.objects.get()
        self.assertEqual((llamada.estado, llamada.status_code), ('error_http', 400))
        self.assertEqual(llamada.respuesta['error']['message'], 'context_length_exceeded')

    def test_un_error_de_red_queda_registrado(self):
        def caer(request):
            raise httpx.ConnectError('sin red')
        cliente = cliente_openai('prueba', api_key='k', max_retries=0, transporte_base=httpx.MockTransport(caer))
        with self.assertRaises(openai.APIConnectionError):
            _chat(cliente)
        llamada = LlamadaOpenAI.objects.get()
        self.assertEqual(llamada.estado, 'error_red')
        self.assertIn('sin red', llamada.error)
        self.assertEqual(llamada.peticion['messages'][1]['content'], 'USER COMPLETO')

    def test_cada_reintento_del_sdk_es_una_fila(self):
        respuestas = iter([httpx.Response(500, json={'error': {'message': 'x'}}),
                           httpx.Response(200, json=RESPUESTA_CHAT)])
        cliente = cliente_openai('prueba', api_key='k', max_retries=1,
                                 transporte_base=httpx.MockTransport(lambda r: next(respuestas)))
        with patch('openai._base_client.time.sleep'):
            _chat(cliente)
        self.assertEqual(list(LlamadaOpenAI.objects.order_by('id').values_list('status_code', flat=True)), [500, 200])

    def test_si_falla_el_registro_la_llamada_no_se_rompe(self):
        with patch('auditoria.openai_cliente._guardar', side_effect=RuntimeError('base caída')):
            respuesta = _chat(cliente_openai('prueba', api_key='k', transporte_base=_transporte()))
        self.assertEqual(respuesta.choices[0].message.content, '{"ok": true}')
        self.assertFalse(LlamadaOpenAI.objects.exists())

    def test_multipart_de_imagenes_guarda_el_cuerpo_crudo_y_el_modelo(self):
        cliente = cliente_openai('infografia', api_key='k', transporte_base=_transporte(
            cuerpo={'created': 1, 'data': [{'b64_json': 'AAAA'}], 'usage': {'input_tokens': 7, 'output_tokens': 9}},
        ))
        cliente.images.edit(model='gpt-image-prueba', prompt='lámina', image=('a.png', b'\x89PNGdatos', 'image/png'))
        llamada = LlamadaOpenAI.objects.get()
        self.assertIsNone(llamada.peticion)
        self.assertIn(b'\x89PNGdatos', bytes(llamada.peticion_cruda))
        self.assertEqual(llamada.modelo, 'gpt-image-prueba')
        self.assertEqual(llamada.respuesta['data'][0]['b64_json'], 'AAAA')
        self.assertEqual((llamada.tokens_entrada, llamada.tokens_salida), (7, 9))


class RelacionesTests(TestCase):
    def setUp(self):
        self.jornada, self.momento = _jornada()
        self.admin = get_user_model().objects.create_user('aud', password='x', is_staff=True)
        self.extraccion = ExtraccionMomento.objects.create(
            momento=self.momento, archivo=SimpleUploadedFile('d.docx', b'x'), solicitado_por=self.admin,
        )

    def test_el_contexto_asocia_jornada_momento_origen_y_usuario(self):
        with contexto_llamada(origen=self.extraccion):
            _chat(cliente_openai('extraccion_momento', api_key='k', transporte_base=_transporte()))
        llamada = LlamadaOpenAI.objects.get()
        self.assertEqual(llamada.origen, self.extraccion)
        self.assertEqual(llamada.momento, self.momento)
        self.assertEqual(llamada.jornada, self.jornada)
        self.assertEqual(llamada.usuario, self.admin)

    def test_el_decorador_carga_el_registro_por_id(self):
        @auditar_llamadas('participantes.ExtraccionMomento')
        def procesar(extraccion_id):
            _chat(cliente_openai('extraccion_momento', api_key='k', transporte_base=_transporte()))

        procesar(self.extraccion.id)
        self.assertEqual(LlamadaOpenAI.objects.get().origen, self.extraccion)

    def test_fuera_de_contexto_se_registra_igual_sin_relaciones(self):
        _chat(cliente_openai('suelta', api_key='k', transporte_base=_transporte()))
        llamada = LlamadaOpenAI.objects.get()
        self.assertIsNone(llamada.jornada)
        self.assertIsNone(llamada.origen)


class HilosTests(TransactionTestCase):
    """Las llamadas reales salen desde hilos internos (`_run`): el contexto tiene que llegar."""

    def test_el_contexto_llega_al_hilo_interno(self):
        jornada, momento = _jornada()

        def _run():
            _chat(cliente_openai('analisis_v2', api_key='k', transporte_base=_transporte()))

        with contexto_llamada(jornada=jornada, momento=momento):
            hilo = hilo_con_contexto(_run)
        hilo.start()
        hilo.join()
        llamada = LlamadaOpenAI.objects.get()
        self.assertEqual((llamada.jornada_id, llamada.momento_id), (jornada.id, momento.id))

    def test_un_hilo_comun_no_hereda_el_contexto(self):
        """Por qué existe `hilo_con_contexto`."""
        jornada, _ = _jornada()

        def _run():
            _chat(cliente_openai('analisis_v2', api_key='k', transporte_base=_transporte()))

        with contexto_llamada(jornada=jornada):
            hilo = threading.Thread(target=_run)
            hilo.start()
            hilo.join()
        self.assertIsNone(LlamadaOpenAI.objects.get().jornada_id)


class FlujoRealTests(TransactionTestCase):
    """De punta a punta por el código de producción: `procesar_analisis_v2` → su hilo interno →
    `llamar_openai_estructurado` → la API (simulada en la capa HTTP)."""

    def test_un_analisis_v2_deja_sus_llamadas_asociadas(self):
        from analitica.models import AnalisisV2, SystemPrompt
        from analitica.tests_v2 import crear_jornada_completa
        from analitica.v2.procesar import procesar_analisis_v2

        d = crear_jornada_completa()
        analisis = AnalisisV2.objects.create(jornada=d['jornada'], modo='integral', pipeline='llm')
        # Una respuesta que no pasa la validación: fuerza también el reintento de reparación.
        respuesta = {**RESPUESTA_CHAT, 'choices': [{'index': 0, 'finish_reason': 'stop',
                                                    'message': {'role': 'assistant', 'content': '{}'}}]}
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'sk-test'}), \
                patch('auditoria.openai_cliente.httpx.HTTPTransport', return_value=_transporte(cuerpo=respuesta)):
            procesar_analisis_v2(analisis.id)

        llamadas = list(LlamadaOpenAI.objects.order_by('id'))
        self.assertEqual(len(llamadas), 2)  # el intento y la reparación
        for llamada in llamadas:
            self.assertEqual(llamada.flujo, 'analisis_v2')
            self.assertEqual(llamada.origen, analisis)
            self.assertEqual(llamada.jornada_id, d['jornada'].id)
        self.assertEqual(llamadas[0].peticion['messages'][0]['content'],
                         SystemPrompt.activo_de('analisis_llm').contenido)
        # La reparación manda la conversación completa: system, user, assistant y los errores.
        self.assertEqual([m['role'] for m in llamadas[1].peticion['messages']],
                         ['system', 'user', 'assistant', 'user'])


class CaracterNuloTests(TestCase):
    def test_un_nulo_en_el_texto_no_impide_registrar(self):
        """PostgreSQL rechaza \\u0000 en jsonb; viene a veces en texto extraído de un PDF."""
        cliente = cliente_openai('prueba', api_key='k', transporte_base=_transporte())
        cliente.chat.completions.create(model='m', messages=[{'role': 'user', 'content': 'a\x00b'}])
        self.assertEqual(LlamadaOpenAI.objects.get().peticion['messages'][0]['content'], 'ab')
