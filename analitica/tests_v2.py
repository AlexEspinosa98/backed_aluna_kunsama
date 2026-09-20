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
