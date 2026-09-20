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


import datetime

from django.test import TestCase

from jornadas.models import ColumnaMatrizPregunta, FilaMatrizPregunta, Jornada, Momento, OpcionPregunta, Pregunta
from participantes.models import FilaListaRespuesta, Participante, Respuesta

from .v2.entrada import construir_entrada, hay_respuestas
from .v2.sin_datos import construir_salida_sin_datos


def crear_jornada_completa():
    """Una jornada con los seis tipos de pregunta y respuestas de ambos tipos de momento. Devuelve
    un dict con todo lo creado para que los tests afirmen sobre ids concretos."""
    jornada = Jornada.objects.create(
        slug='j-v2', nombre='Jornada v2', descripcion='Objetivo de prueba',
        fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 2),
    )
    p1 = Participante.objects.create(jornada=jornada, correo_institucional='a@x.co', nombre='A', apellido='A', rol='docente')
    p2 = Participante.objects.create(jornada=jornada, correo_institucional='b@x.co', nombre='B', apellido='B', rol='docente', mesa=3, es_vocero=True)

    m1 = Momento.objects.create(jornada=jornada, orden=2, titulo='Encuesta', contexto='Ctx m1', categorias_semilla=['acceso', 'claridad'])
    q_unica = Pregunta.objects.create(momento=m1, tipo='unica', texto='¿Le sirve?', orden=1)
    o_si = OpcionPregunta.objects.create(pregunta=q_unica, texto='Sí', orden=1)
    o_no = OpcionPregunta.objects.create(pregunta=q_unica, texto='No', orden=2)
    q_multi = Pregunta.objects.create(momento=m1, tipo='multiple', texto='¿Cuáles?', orden=2, obligatoria=False)
    o_a = OpcionPregunta.objects.create(pregunta=q_multi, texto='A', orden=1)
    o_b = OpcionPregunta.objects.create(pregunta=q_multi, texto='B', orden=2)
    q_abierta = Pregunta.objects.create(momento=m1, tipo='abierta', texto='¿Por qué?', orden=3)
    q_inactiva_con_datos = Pregunta.objects.create(momento=m1, tipo='abierta', texto='Vieja', orden=4, activa=False)
    Pregunta.objects.create(momento=m1, tipo='abierta', texto='Vieja sin datos', orden=5, activa=False)

    r = Respuesta.objects.create(pregunta=q_unica, participante=p1); r.opciones.set([o_si])
    r = Respuesta.objects.create(pregunta=q_unica, participante=p2); r.opciones.set([o_no])
    r = Respuesta.objects.create(pregunta=q_multi, participante=p1); r.opciones.set([o_a, o_b])
    Respuesta.objects.create(pregunta=q_abierta, participante=p1, texto_libre='Necesito una opción al final de la tarde.')
    Respuesta.objects.create(pregunta=q_abierta, participante=p2, texto_libre='   ')
    Respuesta.objects.create(pregunta=q_inactiva_con_datos, participante=p1, texto_libre='dato viejo')

    m2 = Momento.objects.create(jornada=jornada, orden=1, titulo='Mesa', tipo='mesa')
    q_matriz = Pregunta.objects.create(momento=m2, tipo='matriz', texto='Mapa', orden=1)
    f1 = FilaMatrizPregunta.objects.create(pregunta=q_matriz, texto='Fila 1', orden=1)
    c1 = ColumnaMatrizPregunta.objects.create(pregunta=q_matriz, texto='Col 1', orden=1)
    c2 = ColumnaMatrizPregunta.objects.create(pregunta=q_matriz, texto='Col 2', orden=2)
    Respuesta.objects.create(pregunta=q_matriz, mesa=3, fila=f1, columna=c1, texto_libre='x')
    Respuesta.objects.create(pregunta=q_matriz, mesa=3, fila=f1, columna=c2, texto_libre='y')
    q_lista = Pregunta.objects.create(momento=m2, tipo='lista', texto='Registros', orden=2, filas_adicionales=True)
    cl = ColumnaMatrizPregunta.objects.create(pregunta=q_lista, texto='Nombre', orden=1)
    fl = FilaListaRespuesta.objects.create(pregunta=q_lista, mesa=3, orden=1)
    Respuesta.objects.create(pregunta=q_lista, mesa=3, fila_lista=fl, columna=cl, texto_libre='Juan')
    q_audio = Pregunta.objects.create(momento=m2, tipo='audio', texto='Cuéntanos', orden=3)
    Respuesta.objects.create(pregunta=q_audio, mesa=3, texto_libre='transcripción')

    return {
        'jornada': jornada, 'm1': m1, 'm2': m2, 'q_unica': q_unica, 'q_multi': q_multi, 'q_abierta': q_abierta,
        'q_inactiva_con_datos': q_inactiva_con_datos, 'q_matriz': q_matriz, 'q_lista': q_lista, 'q_audio': q_audio,
        'o_si': o_si, 'o_no': o_no, 'o_a': o_a, 'o_b': o_b, 'f1': f1, 'c1': c1, 'c2': c2, 'fl': fl, 'p1': p1, 'p2': p2,
    }


class EntradaNormalizadaTests(TestCase):
    def setUp(self):
        self.d = crear_jornada_completa()

    def _fuente(self, entrada, fid):
        return next(f for f in entrada['fuentes'] if f['id'] == fid)

    def test_integral_incluye_todos_los_momentos_por_orden(self):
        entrada = construir_entrada(self.d['jornada'], 'integral', [], contexto='C', instrucciones='I')
        self.assertEqual(entrada['solicitud'], {'modo': 'integral', 'jornada_id': str(self.d['jornada'].id),
                                                'momento_ids': [str(self.d['m2'].id), str(self.d['m1'].id)]})
        self.assertEqual(entrada['personalizacion']['contexto_usuario'], 'C')
        self.assertIsNone(entrada['bertopic'])
        self.assertTrue(hay_respuestas(entrada))

    def test_por_momento_respeta_orden_y_personalizacion(self):
        m1, m2 = self.d['m1'], self.d['m2']
        entrada = construir_entrada(self.d['jornada'], 'por_momento', [m1, m2], personalizacion_momentos=[
            {'momento': m1.id, 'contexto': 'ctx1', 'instrucciones': 'ins1'},
        ])
        self.assertEqual(entrada['solicitud']['momento_ids'], [str(m2.id), str(m1.id)])
        self.assertEqual(entrada['personalizacion']['instrucciones_por_momento'],
                         [{'momento_id': str(m1.id), 'instrucciones': 'ins1', 'contexto': 'ctx1'}])

    def test_inventario_y_contexto_del_momento(self):
        entrada = construir_entrada(self.d['jornada'], 'por_momento', [self.d['m1']])
        momento = entrada['momentos'][0]
        ids = [p['id'] for p in momento['preguntas']]
        self.assertIn(str(self.d['q_inactiva_con_datos'].id), ids)
        self.assertEqual(len(ids), 4)  # unica, multiple, abierta, inactiva con datos
        self.assertIn('Categorías temáticas de referencia', momento['contexto'])
        self.assertTrue(momento['contexto'].startswith('Ctx m1'))
        unica = momento['preguntas'][0]
        self.assertEqual(unica['tipo'], 'unica')
        self.assertEqual([o['etiqueta'] for o in unica['opciones']], ['Sí', 'No'])
        self.assertEqual(unica['reglas_elegibilidad']['unidad_esperada'], 'persona')
        self.assertIsNone(unica['reglas_elegibilidad']['estructura'])

    def test_respuestas_escalares(self):
        entrada = construir_entrada(self.d['jornada'], 'por_momento', [self.d['m1']])
        fuente = self._fuente(entrada, f"f-m{self.d['m1'].id}")
        self.assertEqual(fuente['datos']['unidad_analisis'], 'respuesta_individual')
        por_pregunta = {}
        for r in fuente['datos']['respuestas']:
            por_pregunta.setdefault(r['pregunta_id'], []).append(r)
        unicas = por_pregunta[str(self.d['q_unica'].id)]
        self.assertEqual([r['valor'] for r in unicas], [str(self.d['o_si'].id), str(self.d['o_no'].id)])
        self.assertEqual(unicas[0]['sujeto_id'], f"p{self.d['p1'].id}")
        multi = por_pregunta[str(self.d['q_multi'].id)][0]
        self.assertEqual(multi['valor'], [str(self.d['o_a'].id), str(self.d['o_b'].id)])
        abiertas = por_pregunta[str(self.d['q_abierta'].id)]
        self.assertEqual(abiertas[0]['valor'], 'Necesito una opción al final de la tarde.')
        self.assertIsNone(abiertas[1]['valor'])

    def test_agregado_con_conteos_y_porcentajes(self):
        entrada = construir_entrada(self.d['jornada'], 'por_momento', [self.d['m1']])
        agg = self._fuente(entrada, f"f-agg-m{self.d['m1'].id}")
        self.assertEqual(agg['pregunta_ids'], [str(self.d['q_unica'].id), str(self.d['q_multi'].id)])
        dist = {d['pregunta_id']: d for d in agg['datos']['distribuciones']}
        unica = dist[str(self.d['q_unica'].id)]
        self.assertEqual(unica['tipo'], 'respuesta_unica')
        self.assertEqual([(c['n'], c['porcentaje']) for c in unica['categorias']], [(1, 50.0), (1, 50.0)])
        multi = dist[str(self.d['q_multi'].id)]
        self.assertEqual([c['n'] for c in multi['categorias']], [1, 1])
        base = next(b for b in agg['datos']['bases'] if b['pregunta_id'] == str(self.d['q_unica'].id))
        self.assertEqual((base['recibidas_n'], base['validas_n'], base['ausentes_n']), (2, 2, 0))

    def test_matriz_lista_y_audio_de_mesa(self):
        entrada = construir_entrada(self.d['jornada'], 'por_momento', [self.d['m2']])
        momento = entrada['momentos'][0]
        matriz = momento['preguntas'][0]
        self.assertEqual(matriz['reglas_elegibilidad']['unidad_esperada'], 'mesa')
        self.assertEqual(matriz['reglas_elegibilidad']['estructura']['filas'], [{'id': str(self.d['f1'].id), 'etiqueta': 'Fila 1'}])
        self.assertFalse(matriz['reglas_elegibilidad']['estructura']['permite_repetir_filas'])
        lista = momento['preguntas'][1]
        self.assertEqual(lista['reglas_elegibilidad']['estructura']['filas'], [])
        self.assertTrue(lista['reglas_elegibilidad']['estructura']['permite_repetir_filas'])
        fuente = self._fuente(entrada, f"f-m{self.d['m2'].id}")
        self.assertEqual(fuente['datos']['unidad_analisis'], 'respuesta_de_mesa')
        self.assertNotIn(f"f-agg-m{self.d['m2'].id}", [f['id'] for f in entrada['fuentes']])
        respuestas = fuente['datos']['respuestas']
        self.assertEqual(respuestas[0]['id'], f"r-q{self.d['q_matriz'].id}-mesa-3")
        self.assertEqual(respuestas[0]['sujeto_id'], 'mesa-3')
        celdas = respuestas[0]['valor']['celdas']
        self.assertEqual([c['valor'] for c in celdas], ['x', 'y'])
        self.assertEqual(celdas[0]['fila_id'], str(self.d['f1'].id))
        self.assertIsNone(celdas[0]['fila_lista_id'])
        self.assertEqual(respuestas[1]['valor']['celdas'][0]['fila_lista_id'], str(self.d['fl'].id))
        self.assertIsNone(respuestas[1]['valor']['celdas'][0]['fila_id'])
        self.assertEqual(respuestas[2]['valor'], 'transcripción')


class SalidaSinDatosTests(TestCase):
    def test_jornada_vacia_produce_salida_valida_en_ambos_modos(self):
        jornada = Jornada.objects.create(slug='j-vacia', nombre='Vacía', fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 1))
        m = Momento.objects.create(jornada=jornada, orden=1, titulo='M')
        Pregunta.objects.create(momento=m, tipo='abierta', texto='¿?', orden=1)
        for modo in ('integral', 'por_momento'):
            entrada = construir_entrada(jornada, modo, [m])
            self.assertFalse(hay_respuestas(entrada))
            salida = construir_salida_sin_datos(entrada, 'llm')
            self.assertEqual(validar_salida(salida, entrada, 'llm'), [], modo)
            self.assertEqual(salida['estado'], 'sin_datos')
            self.assertEqual(salida['cobertura'][0]['estado'], 'sin_datos')


from unittest.mock import patch

from .v2.contrato import cargar_esquema
from .v2.llm import cargar_json_estricto, esquema_para_openai, llamar_openai_estructurado


class LlmEstructuradoTests(SimpleTestCase):
    def test_esquema_para_openai_quita_claves_informativas_sin_mutar_el_original(self):
        e = esquema_para_openai(cargar_esquema())
        self.assertNotIn('$schema', e)
        self.assertIn('$defs', e)
        self.assertIn('$schema', cargar_esquema())

    def test_json_estricto_rechaza_nan(self):
        with self.assertRaises(ValueError):
            cargar_json_estricto('{"a": NaN}')

    @patch.dict('os.environ', {'OPENAI_API_KEY': ''})
    def test_sin_api_key_devuelve_error_sin_lanzar(self):
        salida, error, meta = llamar_openai_estructurado('s', 'u')
        self.assertIsNone(salida)
        self.assertIn('OPENAI_API_KEY', error)


from rest_framework.test import APITestCase

from .models import AnalisisV2, Reporte
from .tests import crear_admin_completo, crear_dependencia, crear_jornada
from .v2.procesar import procesar_analisis_v2


class AnalisisV2ApiTests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dependencia = crear_dependencia('dependencia')
        self.d = crear_jornada_completa()
        self.jornada = self.d['jornada']
        self.jornada.propietarios.set([self.dependencia])
        self.jornada_ajena = crear_jornada('ajena')
        self.momento_ajeno = Momento.objects.create(jornada=self.jornada_ajena, orden=1, titulo='Ajeno')
        self.client.force_authenticate(user=self.admin)

    def _post(self, cuerpo):
        with patch('analitica.admin_views.threading.Thread') as hilo:
            resp = self.client.post('/api/admin/analisis-v2/', cuerpo, format='json')
        return resp, hilo

    def test_integral_crea_pendiente_y_lanza_hilo(self):
        resp, hilo = self._post({'jornada': self.jornada.id, 'modo': 'integral', 'pipeline': 'llm', 'contexto': 'C'})
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['estado'], 'pendiente')
        self.assertEqual(resp.data['version'], 'kunsamu.analisis/v2')
        self.assertEqual(resp.data['metodo'], 'openai')
        self.assertEqual(resp.data['momentos'], [])
        self.assertEqual(resp.data['contexto'], 'C')
        hilo.return_value.start.assert_called_once()
        self.assertEqual(AnalisisV2.objects.get(pk=resp.data['id']).solicitado_por, self.admin)

    def test_por_momento_con_personalizacion(self):
        m1 = self.d['m1']
        resp, _ = self._post({
            'jornada': self.jornada.id, 'modo': 'por_momento', 'pipeline': 'bertopic_llm', 'momentos': [m1.id],
            'personalizacion_momentos': [{'momento': m1.id, 'contexto': 'ctx', 'instrucciones': 'ins'}],
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['metodo'], 'bertopic')
        self.assertEqual([m['id'] for m in resp.data['momentos']], [m1.id])
        self.assertEqual(resp.data['personalizacion_momentos'], [{'momento': m1.id, 'contexto': 'ctx', 'instrucciones': 'ins'}])

    def test_integral_con_momentos_da_400(self):
        resp, _ = self._post({'jornada': self.jornada.id, 'modo': 'integral', 'pipeline': 'llm', 'momentos': [self.d['m1'].id]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('momentos', resp.data)

    def test_por_momento_sin_momentos_da_400(self):
        resp, _ = self._post({'jornada': self.jornada.id, 'modo': 'por_momento', 'pipeline': 'llm'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('momentos', resp.data)

    def test_momento_de_otra_jornada_da_400(self):
        resp, _ = self._post({'jornada': self.jornada.id, 'modo': 'por_momento', 'pipeline': 'llm', 'momentos': [self.momento_ajeno.id]})
        self.assertEqual(resp.status_code, 400)

    def test_personalizacion_fuera_del_alcance_da_400(self):
        resp, _ = self._post({
            'jornada': self.jornada.id, 'modo': 'por_momento', 'pipeline': 'llm', 'momentos': [self.d['m1'].id],
            'personalizacion_momentos': [{'momento': self.d['m2'].id, 'contexto': 'x'}],
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('personalizacion_momentos', resp.data)

    def test_pipeline_invalido_da_400(self):
        resp, _ = self._post({'jornada': self.jornada.id, 'modo': 'integral', 'pipeline': 'otro'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('pipeline', resp.data)

    def test_dependencia_no_puede_pedir_de_jornada_ajena(self):
        self.client.force_authenticate(user=self.dependencia)
        resp, _ = self._post({'jornada': self.jornada_ajena.id, 'modo': 'integral', 'pipeline': 'llm'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(AnalisisV2.objects.filter(jornada=self.jornada_ajena).exists())

    def test_409_solo_para_el_mismo_alcance(self):
        AnalisisV2.objects.create(jornada=self.jornada, modo='integral', estado=AnalisisV2.ESTADO_PROCESANDO)
        resp, _ = self._post({'jornada': self.jornada.id, 'modo': 'integral', 'pipeline': 'llm'})
        self.assertEqual(resp.status_code, 409)
        resp, _ = self._post({'jornada': self.jornada.id, 'modo': 'por_momento', 'pipeline': 'llm', 'momentos': [self.d['m1'].id]})
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_jornada_sin_momentos_da_400_en_integral(self):
        vacia = crear_jornada('vacia', propietario=self.admin)
        resp, _ = self._post({'jornada': vacia.id, 'modo': 'integral', 'pipeline': 'llm'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('jornada', resp.data)

    def test_lista_detalle_y_scoping(self):
        a = AnalisisV2.objects.create(jornada=self.jornada, modo='integral', estado=AnalisisV2.ESTADO_COMPLETO,
                                      resultado={'estado': 'parcial'}, entrada={'x': 1})
        AnalisisV2.objects.create(jornada=self.jornada_ajena, modo='integral')
        resp = self.client.get(f'/api/admin/analisis-v2/?jornada={self.jornada.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([i['id'] for i in resp.data], [a.id])
        self.assertNotIn('entrada', resp.data[0])
        self.assertEqual(resp.data[0]['estado_analitico'], 'parcial')
        resp = self.client.get(f'/api/admin/analisis-v2/{a.id}/')
        self.assertEqual(resp.data['entrada'], {'x': 1})
        self.client.force_authenticate(user=self.dependencia)
        resp = self.client.get('/api/admin/analisis-v2/')
        self.assertEqual([i['id'] for i in resp.data], [a.id])

    def test_lista_unificada_incluye_v2(self):
        a = AnalisisV2.objects.create(jornada=self.jornada, modo='por_momento', pipeline='bertopic_llm')
        a.momentos.set([self.d['m1']])
        resp = self.client.get(f'/api/admin/analisis/?jornada={self.jornada.id}')
        item = next(i for i in resp.data if i['tipo'] == 'analisis_v2')
        self.assertEqual(item['id'], a.id)
        self.assertEqual(item['version'], 'kunsamu.analisis/v2')
        self.assertEqual(item['metodo'], 'bertopic')
        self.assertEqual(item['alcance'], 'momento')
        self.assertEqual(item['momento_titulo'], self.d['m1'].titulo)
        self.assertIsNone(item['enfoque'])
        resp = self.client.get(f"/api/admin/analisis/?momento={self.d['m1'].id}")
        self.assertIn(a.id, [i['id'] for i in resp.data if i['tipo'] == 'analisis_v2'])
        resp = self.client.get(f"/api/admin/analisis/?momento={self.d['m2'].id}")
        self.assertNotIn(a.id, [i['id'] for i in resp.data if i['tipo'] == 'analisis_v2'])


class ProcesarAnalisisV2Tests(TestCase):
    """El orquestador con la llamada a OpenAI mockeada: lo que se guarda, en qué estado y qué
    queda en diagnostico."""

    def setUp(self):
        self.d = crear_jornada_completa()

    def _salida_valida(self, system, user, modelo=None, reparacion=None):
        # Una salida que SIEMPRE valida contra la entrada: la forma sin_datos construida a partir
        # del propio `user` (no importa que la entrada sí tenga respuestas — eso no lo comprueba
        # el validador de negocio).
        entrada = json.loads(user)
        return construir_salida_sin_datos(entrada, 'llm'), None, {'finish_reason': 'stop', 'modo_salida': 'json_schema'}

    def test_completo_con_salida_valida(self):
        a = AnalisisV2.objects.create(jornada=self.d['jornada'], modo='integral', pipeline='llm')
        with patch('analitica.v2.procesar.llamar_openai_estructurado', side_effect=self._salida_valida) as llamada:
            procesar_analisis_v2(a.id)
        a.refresh_from_db()
        self.assertEqual(a.estado, AnalisisV2.ESTADO_COMPLETO, a.error_mensaje)
        self.assertEqual(a.resultado['version'], 'kunsamu.analisis/v2')
        self.assertEqual(a.modelo_usado, 'Generado con IA')
        self.assertEqual(a.version_esquema, 'v2.0')
        self.assertTrue(a.prompt_usado.startswith('# System prompt Kunsamu — LLM'))
        self.assertEqual(a.entrada['solicitud']['modo'], 'integral')
        self.assertEqual(len(a.diagnostico['intentos']), 1)
        self.assertEqual(llamada.call_count, 1)

    def test_sin_datos_no_llama_a_openai(self):
        vacia = Jornada.objects.create(slug='v', nombre='V', fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 1))
        m = Momento.objects.create(jornada=vacia, orden=1, titulo='M')
        Pregunta.objects.create(momento=m, tipo='abierta', texto='¿?', orden=1)
        a = AnalisisV2.objects.create(jornada=vacia, modo='integral', pipeline='bertopic_llm')
        with patch('analitica.v2.procesar.llamar_openai_estructurado') as llamada:
            procesar_analisis_v2(a.id)
        a.refresh_from_db()
        llamada.assert_not_called()
        self.assertEqual(a.estado, AnalisisV2.ESTADO_COMPLETO, a.error_mensaje)
        self.assertEqual(a.resultado['estado'], 'sin_datos')
        self.assertEqual(a.resultado['pipeline'], 'bertopic_llm')
        self.assertEqual(a.prompt_usado, '')
        self.assertEqual(a.entrada['bertopic'], {'version_adaptador': '1.0', 'ejecuciones': []})

    def test_invalida_dos_veces_termina_en_error_con_diagnostico(self):
        a = AnalisisV2.objects.create(jornada=self.d['jornada'], modo='integral', pipeline='llm')
        invalida = ({'version': 'kunsamu.analisis/v2'}, None, {'finish_reason': 'stop'})
        with patch('analitica.v2.procesar.llamar_openai_estructurado', return_value=invalida) as llamada:
            procesar_analisis_v2(a.id)
        a.refresh_from_db()
        self.assertEqual(llamada.call_count, 2)
        self.assertIsNotNone(llamada.call_args_list[1].kwargs.get('reparacion'))
        self.assertEqual(a.estado, AnalisisV2.ESTADO_ERROR)
        self.assertIn('no pasó la validación', a.error_mensaje)
        self.assertEqual(a.resultado, {})
        self.assertEqual(len(a.diagnostico['intentos']), 2)
        self.assertTrue(a.diagnostico['intentos'][0]['errores_validacion'])

    def test_error_del_proveedor_termina_en_error(self):
        a = AnalisisV2.objects.create(jornada=self.d['jornada'], modo='integral', pipeline='llm')
        with patch('analitica.v2.procesar.llamar_openai_estructurado', return_value=(None, 'boom', {})):
            procesar_analisis_v2(a.id)
        a.refresh_from_db()
        self.assertEqual(a.estado, AnalisisV2.ESTADO_ERROR)
        self.assertEqual(a.error_mensaje, 'boom')

    def test_bertopic_llm_guarda_ejecuciones_en_la_entrada(self):
        q = self.d['q_abierta']
        for i in range(10):
            Respuesta.objects.create(pregunta=q, texto_libre=f'Texto de prueba número {i}')
        a = AnalisisV2.objects.create(jornada=self.d['jornada'], modo='por_momento', pipeline='bertopic_llm')
        a.momentos.set([self.d['m1']])

        class Doble:
            topics_ = [0] * 6 + [-1] * 5
            def get_topic_info(self):
                import pandas as pd
                return pd.DataFrame({'Topic': [-1, 0], 'Count': [5, 6], 'Name': ['-1_x', '0_prueba']})
            def get_topic(self, t):
                return [('prueba', 0.4)]
            def get_representative_docs(self, t):
                return []

        def salida(system, user, modelo=None, reparacion=None):
            entrada = json.loads(user)
            return construir_salida_sin_datos(entrada, 'bertopic_llm'), None, {}

        with patch('analitica.v2.bertopic_adaptador._ajustar_modelo', return_value=Doble()), \
             patch('analitica.v2.procesar.llamar_openai_estructurado', side_effect=salida):
            procesar_analisis_v2(a.id)
        a.refresh_from_db()
        self.assertEqual(a.estado, AnalisisV2.ESTADO_COMPLETO, a.error_mensaje)
        self.assertEqual(len(a.entrada['bertopic']['ejecuciones']), 1)
        self.assertEqual(a.entrada['bertopic']['ejecuciones'][0]['ejecucion_id'], f'run-p{q.id}')
        self.assertIn(f'fbt-p{q.id}', [f['id'] for f in a.entrada['fuentes']])
        self.assertEqual(a.diagnostico['bertopic'][0]['motivo'], 'ok')
        self.assertTrue(a.prompt_usado.startswith('# System prompt Kunsamu — BERTopic + LLM'))


from .v2.bertopic_adaptador import anexar_bertopic, exportar_ejecucion, id_topico


class BertopicAdaptadorTests(SimpleTestCase):
    """El adaptador con un doble de BERTopic (sin descargar el modelo de embeddings): mapeo de
    tópicos/documentos/agregados y el filtro de preguntas con corpus insuficiente."""

    class Doble:
        topics_ = [0, 0, 0, 1, 1, 1, -1, -1]

        def get_topic_info(self):
            import pandas as pd
            return pd.DataFrame({'Topic': [-1, 0, 1], 'Count': [2, 3, 3], 'Name': ['-1_x', '0_horario', '1_turno']})

        def get_topic(self, t):
            return [('horario', 0.5), ('turno', 0.2)]

        def get_representative_docs(self, t):
            return ['t0'] if t == 0 else ['t3']

    def test_exportar_ejecucion_mapea_topicos_documentos_y_agregados(self):
        docs = [(i + 10, {'id': f'r{i}', 'pregunta_id': 'q2', 'sujeto_id': None, 'valor': f't{i}'}) for i in range(8)]
        fuente, ejecucion = exportar_ejecucion(
            self.Doble(), docs, 'run-pq2', 'f-m1', 'm1', 'q2', '¿Por qué?', 'analisis-1',
        )
        self.assertEqual(fuente['id'], 'fbt-pq2')
        self.assertEqual(fuente['datos']['documentos'][0]['localizador'], '/respuestas/10/valor')
        self.assertEqual(fuente['datos']['documentos'][6]['topico_final_id'], id_topico('run-pq2', -1))
        self.assertEqual(id_topico('run-pq2', -1), 'run-pq2::-1')
        self.assertTrue(fuente['datos']['documentos'][0]['es_representativo'])
        self.assertFalse(fuente['datos']['documentos'][1]['es_representativo'])
        self.assertEqual([t['conteo_documentos'] for t in fuente['datos']['topicos']], [2, 3, 3])
        self.assertEqual(
            fuente['datos']['agregados'][0]['conteos'],
            [{'topico_id': 'run-pq2::-1', 'n': 2}, {'topico_id': 'run-pq2::0', 'n': 3}, {'topico_id': 'run-pq2::1', 'n': 3}],
        )
        self.assertEqual(ejecucion['corpus']['outliers_finales_n'], 2)
        self.assertEqual(ejecucion['fuente_resultados_id'], 'fbt-pq2')

    def test_anexar_bertopic_omite_preguntas_insuficientes(self):
        docs = [(i + 10, {'id': f'r{i}', 'pregunta_id': 'q2', 'sujeto_id': None, 'valor': f't{i}'}) for i in range(8)]
        entrada = {
            'momentos': [{'id': 'm1', 'preguntas': [
                {'id': 'q2', 'tipo': 'abierta', 'texto': '¿?'}, {'id': 'q1', 'tipo': 'unica', 'texto': 'x'},
            ]}],
            'fuentes': [{'id': 'f-m1', 'tipo': 'respuestas', 'momento_ids': ['m1'], 'datos': {'respuestas': [d for _, d in docs]}}],
        }
        with patch('analitica.v2.bertopic_adaptador._ajustar_modelo', return_value=self.Doble()):
            entrada, notas = anexar_bertopic(entrada, analisis_id=1)
        self.assertEqual(len(entrada['bertopic']['ejecuciones']), 1)
        self.assertEqual(notas[0]['motivo'], 'ok', notas)

        entrada['fuentes'][0]['datos']['respuestas'] = entrada['fuentes'][0]['datos']['respuestas'][:3]
        del entrada['fuentes'][1]
        _, notas = anexar_bertopic(entrada)
        self.assertEqual(notas[0]['motivo'], 'insuficiente', notas)


from .infografia_ia_openai import _obtener_datos_analitica
from .models import InfografiaJornada


class InfografiaDesdeAnalisisV2Tests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.d = crear_jornada_completa()
        self.jornada = self.d['jornada']
        self.resultado = _ejemplo('llm_por_momento.salida.json')
        self.analisis = AnalisisV2.objects.create(
            jornada=self.jornada, modo='por_momento', pipeline='llm', estado=AnalisisV2.ESTADO_COMPLETO,
            resultado=self.resultado,
        )
        self.analisis.momentos.set([self.d['m1']])
        self.client.force_authenticate(user=self.admin)

    def test_traduce_resultado_v2_al_formato_de_las_laminas(self):
        datos, error = _obtener_datos_analitica(self.jornada, analisis_v2=self.analisis)
        self.assertIsNone(error)
        self.assertEqual(datos['fuente'], 'analisis_v2')
        self.assertEqual(datos['momento'], self.d['m1'].titulo)
        self.assertEqual(len(datos['hallazgos']), 2)
        primero = datos['hallazgos'][0]
        self.assertEqual(primero['tipo_grafica'], 'barras')
        self.assertEqual(primero['datos'][0]['etiqueta'], 'El horario no sirve')
        self.assertIn('Conviene contrastar', primero['descripcion'])
        self.assertIsNone(datos['hallazgos'][1]['tipo_grafica'])

    def test_no_completo_o_sin_datos_da_error(self):
        self.analisis.estado = AnalisisV2.ESTADO_PROCESANDO
        self.analisis.save()
        _, error = _obtener_datos_analitica(self.jornada, analisis_v2=self.analisis)
        self.assertIn('no está completo', error)
        self.analisis.estado = AnalisisV2.ESTADO_COMPLETO
        self.analisis.resultado = _ejemplo('sin_datos.salida.json')
        self.analisis.save()
        _, error = _obtener_datos_analitica(self.jornada, analisis_v2=self.analisis)
        self.assertIn('sin_datos', error)

    def test_api_fija_analisis_v2_y_deriva_momento(self):
        with patch('analitica.admin_views.threading.Thread'):
            resp = self.client.post('/api/admin/infografias/', {'analisis_v2': self.analisis.id}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        infografia = InfografiaJornada.objects.get(pk=resp.data['id'])
        self.assertEqual(infografia.analisis_v2, self.analisis)
        self.assertEqual(infografia.momento, self.d['m1'])
        self.assertEqual(infografia.jornada, self.jornada)
        resp = self.client.get(f'/api/admin/infografias/?analisis_v2={self.analisis.id}')
        self.assertEqual([i['id'] for i in resp.data], [infografia.id])

    def test_dos_pines_a_la_vez_da_400(self):
        reporte = Reporte.objects.create(jornada=self.jornada, alcance=Reporte.ALCANCE_JORNADA, estado=Reporte.ESTADO_COMPLETO)
        resp = self.client.post('/api/admin/infografias/', {'analisis_v2': self.analisis.id, 'reporte': reporte.id}, format='json')
        self.assertEqual(resp.status_code, 400)


from .analisis_ia_openai import analizar_jornada_ia, analizar_momento_ia
from .analysis import procesar_reporte
from .models import AnalisisJornadaIA, AnalisisMomentoIA


class EndpointsExistentesProducenV2Tests(TestCase):
    """Rediseño: los tres puntos de entrada existentes (AnalisisJornadaIA, AnalisisMomentoIA,
    Reporte) corren el pipeline v2 y guardan el contrato kunsamu.analisis/v2 en su campo de
    siempre. La llamada a OpenAI se mockea con una salida que siempre valida (ver
    ProcesarAnalisisV2Tests._salida_valida)."""

    def setUp(self):
        self.d = crear_jornada_completa()

    @staticmethod
    def _salida(pipeline):
        def _fake(system, user, modelo=None, reparacion=None):
            return construir_salida_sin_datos(json.loads(user), pipeline), None, {'finish_reason': 'stop'}
        return _fake

    def test_analisis_jornada_ia_usa_prompt_llm_integral(self):
        a = AnalisisJornadaIA.objects.create(jornada=self.d['jornada'], enfoque='cualitativo', contexto='C')
        with patch('analitica.v2.procesar.llamar_openai_estructurado', side_effect=self._salida('llm')) as llamada:
            analizar_jornada_ia(a.id)
        a.refresh_from_db()
        self.assertEqual(a.estado, AnalisisJornadaIA.ESTADO_COMPLETO, a.error_mensaje)
        self.assertEqual(a.resultado['version'], 'kunsamu.analisis/v2')
        self.assertEqual(a.resultado['alcance']['modo'], 'integral')
        self.assertEqual(a.entrada['personalizacion']['contexto_usuario'], 'C')
        self.assertEqual(a.version_esquema, 'v2.0')
        self.assertTrue(a.prompt_usado.startswith('# System prompt Kunsamu — LLM'))
        self.assertEqual(llamada.call_args.args[0], a.prompt_usado)  # system = archivo íntegro, sin anexos
        self.assertNotIn('ENFOQUE', a.prompt_usado)

    def test_analisis_momento_ia_usa_por_momento_con_personalizacion(self):
        m = self.d['m1']
        a = AnalisisMomentoIA.objects.create(momento=m, contexto_momento='CtxM', instrucciones_momento='InsM')
        with patch('analitica.v2.procesar.llamar_openai_estructurado', side_effect=self._salida('llm')):
            analizar_momento_ia(a.id)
        a.refresh_from_db()
        self.assertEqual(a.estado, AnalisisMomentoIA.ESTADO_COMPLETO, a.error_mensaje)
        self.assertEqual(a.resultado['alcance'], {'modo': 'por_momento', 'jornada_id': str(self.d['jornada'].id), 'momento_ids': [str(m.id)]})
        self.assertEqual(a.entrada['personalizacion']['instrucciones_por_momento'],
                         [{'momento_id': str(m.id), 'instrucciones': 'InsM', 'contexto': 'CtxM'}])

    def test_reporte_usa_bertopic_llm_y_llena_texto_reporte(self):
        reporte = Reporte.objects.create(jornada=self.d['jornada'], alcance=Reporte.ALCANCE_JORNADA)
        with patch('analitica.v2.procesar.llamar_openai_estructurado', side_effect=self._salida('bertopic_llm')):
            procesar_reporte(reporte.id)
        reporte.refresh_from_db()
        self.assertEqual(reporte.estado, Reporte.ESTADO_COMPLETO, reporte.error_mensaje)
        self.assertEqual(reporte.analisis['version'], 'kunsamu.analisis/v2')
        self.assertEqual(reporte.analisis['pipeline'], 'bertopic_llm')
        self.assertTrue(reporte.prompt_usado.startswith('# System prompt Kunsamu — BERTopic + LLM'))
        self.assertEqual(reporte.entrada['bertopic']['version_adaptador'], '1.0')
        self.assertTrue(reporte.texto_reporte)
        self.assertEqual(reporte.texto_reporte, reporte.analisis['informes'][0]['resumen'])

    def test_reporte_por_momento_con_varios_momentos(self):
        reporte = Reporte.objects.create(jornada=self.d['jornada'], alcance=Reporte.ALCANCE_MOMENTOS)
        reporte.momentos.set([self.d['m1'], self.d['m2']])
        with patch('analitica.v2.procesar.llamar_openai_estructurado', side_effect=self._salida('bertopic_llm')):
            procesar_reporte(reporte.id)
        reporte.refresh_from_db()
        self.assertEqual(reporte.estado, Reporte.ESTADO_COMPLETO, reporte.error_mensaje)
        self.assertEqual(reporte.analisis['alcance']['modo'], 'por_momento')
        self.assertEqual(len(reporte.analisis['informes']), 2)

    def test_error_del_proveedor_deja_registro_en_error_con_diagnostico(self):
        a = AnalisisJornadaIA.objects.create(jornada=self.d['jornada'])
        with patch('analitica.v2.procesar.llamar_openai_estructurado', return_value=(None, 'boom', {})):
            analizar_jornada_ia(a.id)
        a.refresh_from_db()
        self.assertEqual(a.estado, AnalisisJornadaIA.ESTADO_ERROR)
        self.assertEqual(a.error_mensaje, 'boom')
        self.assertEqual(a.resultado, {})
        self.assertEqual(len(a.diagnostico['intentos']), 1)


class ListaUnificadaYPresentacionV2Tests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.d = crear_jornada_completa()
        self.client.force_authenticate(user=self.admin)

    def test_items_legacy_traen_version_y_estado_analitico(self):
        viejo = AnalisisJornadaIA.objects.create(jornada=self.d['jornada'], estado='completo', resultado={'resumen_ejecutivo': 'x', 'hallazgos': []})
        nuevo = AnalisisJornadaIA.objects.create(jornada=self.d['jornada'], estado='completo', resultado={'version': 'kunsamu.analisis/v2', 'estado': 'parcial'})
        resp = self.client.get(f"/api/admin/analisis/?jornada={self.d['jornada'].id}")
        por_id = {i['id']: i for i in resp.data if i['tipo'] == 'analisis_jornada'}
        self.assertIsNone(por_id[viejo.id]['version'])
        self.assertEqual(por_id[nuevo.id]['version'], 'kunsamu.analisis/v2')
        self.assertEqual(por_id[nuevo.id]['estado_analitico'], 'parcial')

    def test_presentacion_y_pdf_dan_400_para_reporte_v2(self):
        reporte = Reporte.objects.create(
            jornada=self.d['jornada'], alcance=Reporte.ALCANCE_JORNADA, estado=Reporte.ESTADO_COMPLETO,
            analisis={'version': 'kunsamu.analisis/v2', 'estado': 'completo', 'informes': []},
        )
        resp = self.client.post(f'/api/admin/reportes/{reporte.id}/generar-presentacion/')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('v2', resp.data['detail'])
        resp = self.client.get(f'/api/admin/reportes/{reporte.id}/pdf/')
        self.assertEqual(resp.status_code, 400)

    def test_detalle_legacy_expone_versiones_y_diagnostico(self):
        a = AnalisisJornadaIA.objects.create(jornada=self.d['jornada'], version_prompt='v2.0', diagnostico={'intentos': []})
        resp = self.client.get(f'/api/admin/analisis-jornada-ia/{a.id}/')
        self.assertEqual(resp.data['version_prompt'], 'v2.0')
        self.assertEqual(resp.data['diagnostico'], {'intentos': []})


from .v2.validacion import normalizar_salida


class NormalizacionSalidaTests(SimpleTestCase):
    """Correcciones de representación observadas en una respuesta real (AnalisisJornadaIA #11):
    citas con el id de la respuesta como localizador y `orden_categorias` con las series."""

    def test_localizador_por_id_se_resuelve_a_puntero(self):
        salida, entrada = _ejemplo('llm_integral.salida.json'), _ejemplo('llm_integral.entrada.json')
        cita = salida['informes'][0]['hallazgos'][0]['citas'][0]
        fuente = next(f for f in entrada['fuentes'] if f['id'] == cita['fuente_id'])
        idx = int(cita['localizador'].split('/')[2])
        cita['localizador'] = fuente['datos']['respuestas'][idx]['id']
        notas = normalizar_salida(salida, entrada)
        self.assertEqual(len(notas), 1)
        self.assertEqual(cita['localizador'], f'/respuestas/{idx}/valor')
        self.assertEqual(validar_negocio(salida, entrada), [])

    def test_orden_categorias_con_series_se_reconstruye(self):
        salida, entrada = _ejemplo('llm_integral.salida.json'), _ejemplo('llm_integral.entrada.json')
        v = next(v for v in salida['visualizaciones'] if v['tipo'] in ('barras', 'barras_100', 'dona'))
        series = sorted({f['serie'] for f in v['datos']['filas']})
        v['datos']['orden_categorias'] = series
        self.assertTrue(any('orden_categorias' in e for e in validar_negocio(salida, entrada)))
        notas = normalizar_salida(salida, entrada)
        self.assertEqual(len(notas), 1)
        self.assertEqual(v['datos']['orden_categorias'], list(dict.fromkeys(f['categoria'] for f in v['datos']['filas'])))
        self.assertEqual(validar_negocio(salida, entrada), [])

    def test_no_toca_una_salida_correcta(self):
        salida, entrada = _ejemplo('bertopic_integral.salida.json'), _ejemplo('bertopic_integral.entrada.json')
        self.assertEqual(normalizar_salida(salida, entrada), [])
