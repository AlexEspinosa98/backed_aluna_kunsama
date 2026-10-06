"""Adjuntos de un análisis (HU-101): documentos e imágenes de la jornada que entran a la analítica
como fuente o como contexto, y a la presentación. Sin llamadas reales a OpenAI: la lectura con
visión y la llamada del análisis se mockean."""
import io
import json
import shutil
import tempfile
from io import StringIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from jornadas.contenido_assets import ErrorLecturaAsset, asegurar_contenido
from jornadas.models import JornadaAsset

from .models import AnalisisJornadaIA, AnalisisV2, ResumenPresentacion, SystemPrompt
from .presentacion_diseno_ia import _reunir_assets
from .resumen_presentacion import entrada_del_resumen
from .tests import crear_admin_completo, crear_jornada
from .tests_v2 import crear_jornada_completa
from .v2.adjuntos import NOTA_REFERENCIAS
from .v2.contrato import MODO_INTEGRAL, PIPELINE_LLM, RECURSOS
from .v2.entrada import construir_entrada
from .v2.procesar import preparar_entrada_v2, procesar_analisis_v2
from .v2.sin_datos import construir_salida_sin_datos
from .v2.validacion import normalizar_salida, validar_negocio

MEDIA_TEMPORAL = tempfile.mkdtemp(prefix='kunsamu-tests-adjuntos-')
TEXTO_DOCUMENTO = 'Acuerdo 012 de 2025: la universidad ofrecerá una franja al final de la tarde.'


def _png():
    from PIL import Image

    salida = io.BytesIO()
    Image.new('RGB', (40, 30), (20, 60, 90)).save(salida, format='PNG')
    return salida.getvalue()


def _docx(parrafos):
    import docx

    documento = docx.Document()
    for parrafo in parrafos:
        documento.add_paragraph(parrafo)
    salida = io.BytesIO()
    documento.save(salida)
    return salida.getvalue()


def _asset(jornada, nombre, contenido, tipo=JornadaAsset.TIPO_DOCUMENTO, **extra):
    return JornadaAsset.objects.create(
        jornada=jornada, tipo=tipo, archivo=SimpleUploadedFile(nombre, contenido),
        nombre_archivo_original=nombre, **extra,
    )


@override_settings(MEDIA_ROOT=MEDIA_TEMPORAL)
class BaseAdjuntos(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TEMPORAL, ignore_errors=True)

    def setUp(self):
        self.d = crear_jornada_completa()
        self.jornada = self.d['jornada']
        self.doc = _asset(self.jornada, 'acuerdo.txt', TEXTO_DOCUMENTO.encode('utf-8'), titulo='Acuerdo 012')
        self.foto = _asset(self.jornada, 'papelografo.png', _png(), tipo=JornadaAsset.TIPO_ASSET,
                           descripcion='Papelógrafo de la mesa 3')


class LecturaDeContenidoTests(BaseAdjuntos):
    def test_txt_se_lee_tal_cual(self):
        self.assertEqual(asegurar_contenido(self.doc), TEXTO_DOCUMENTO)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.contenido_estado, JornadaAsset.CONTENIDO_LISTO)
        self.assertEqual(self.doc.contenido_metodo, JornadaAsset.METODO_TEXTO)

    def test_docx_se_lee_con_el_lector_de_las_extracciones(self):
        asset = _asset(self.jornada, 'informe.docx', _docx(['Primer párrafo', 'Segundo párrafo']))
        texto = asegurar_contenido(asset)
        self.assertIn('Primer párrafo', texto)
        self.assertIn('Segundo párrafo', texto)

    def test_imagen_se_lee_con_vision_una_sola_vez(self):
        with patch('jornadas.contenido_assets._leer_con_vision', return_value='FRANJA TARDE\nDescripción: notas') as vision:
            self.assertEqual(asegurar_contenido(self.foto), 'FRANJA TARDE\nDescripción: notas')
            asegurar_contenido(self.foto)
        vision.assert_called_once()
        url = vision.call_args.args[1][0]
        self.assertTrue(url.startswith('data:image/jpeg;base64,'))
        self.foto.refresh_from_db()
        self.assertEqual(self.foto.contenido_metodo, JornadaAsset.METODO_VISION)

    def test_sin_clave_de_openai_la_imagen_queda_en_error_con_motivo(self):
        with self.assertRaises(ErrorLecturaAsset):
            asegurar_contenido(self.foto)
        self.foto.refresh_from_db()
        self.assertEqual(self.foto.contenido_estado, JornadaAsset.CONTENIDO_ERROR)
        self.assertIn('OPENAI_API_KEY', self.foto.contenido_error)

    def test_guia_de_marca_escrita_no_necesita_lectura(self):
        guia = JornadaAsset.objects.create(jornada=self.jornada, tipo=JornadaAsset.TIPO_SYSTEM_DESIGN, texto='Azul #14384A')
        self.assertEqual(asegurar_contenido(guia), 'Azul #14384A')


class EntradaConAdjuntosTests(BaseAdjuntos):
    def _preparar(self, adjuntos):
        diagnostico = {'bertopic': [], 'intentos': []}
        with patch('jornadas.contenido_assets._leer_con_vision', return_value='Lo que dice la foto'):
            preparado = preparar_entrada_v2(
                self.jornada, MODO_INTEGRAL, [], PIPELINE_LLM, adjuntos=adjuntos, diagnostico=diagnostico,
            )
        return preparado['entrada'], diagnostico

    def test_sin_adjuntos_la_entrada_no_cambia(self):
        entrada, _ = self._preparar([])
        self.assertEqual(entrada, construir_entrada(self.jornada, MODO_INTEGRAL, []))
        self.assertNotIn('referencias', entrada)

    def test_fuente_entra_como_resumen_secundario_y_contexto_como_referencia(self):
        entrada, diagnostico = self._preparar([
            {'asset': self.doc.id, 'uso': 'fuente'}, {'asset': self.foto.id, 'uso': 'contexto'},
        ])
        fuente = next(f for f in entrada['fuentes'] if f['id'] == f'f-adj{self.doc.id}')
        self.assertEqual(fuente['tipo'], 'resumen_secundario')
        self.assertEqual(fuente['etiqueta'], 'Documento adjunto — Acuerdo 012')
        self.assertEqual(fuente['datos']['texto'], TEXTO_DOCUMENTO)
        self.assertEqual((fuente['momento_ids'], fuente['pregunta_ids']), ([], []))
        self.assertEqual(entrada['referencias']['nota'], NOTA_REFERENCIAS)
        [ref] = entrada['referencias']['documentos']
        self.assertEqual(ref['id'], f'ref-adj{self.foto.id}')
        self.assertEqual(ref['tipo'], 'imagen')
        self.assertEqual(ref['texto'], 'Lo que dice la foto')
        self.assertEqual(ref['descripcion'], 'Papelógrafo de la mesa 3')
        self.assertNotIn(f'ref-adj{self.foto.id}', [f['id'] for f in entrada['fuentes']])
        self.assertEqual([n['uso'] for n in diagnostico['adjuntos']], ['fuente', 'contexto'])

    def test_los_agregados_no_cuentan_los_adjuntos(self):
        sin, _ = self._preparar([])
        con, _ = self._preparar([{'asset': self.doc.id, 'uso': 'fuente'}])
        agregados = lambda e: [f for f in e['fuentes'] if f['tipo'] == 'agregado']  # noqa: E731
        self.assertTrue(agregados(sin))
        for a, b in zip(agregados(sin), agregados(con)):
            self.assertEqual(a['datos']['bases'], b['datos']['bases'])
            self.assertEqual(a['datos']['distribuciones'], b['datos']['distribuciones'])

    def test_adjunto_ilegible_falla_antes_de_llamar_a_la_ia(self):
        with self.assertRaisesRegex(ValueError, 'No se pudo leer el adjunto "papelografo.png"'):
            preparar_entrada_v2(self.jornada, MODO_INTEGRAL, [], PIPELINE_LLM,
                                adjuntos=[{'asset': self.foto.id, 'uso': 'fuente'}])

    def test_adjunto_de_otra_jornada_falla(self):
        ajeno = _asset(crear_jornada('otra'), 'x.txt', b'x')
        with self.assertRaisesRegex(ValueError, 'no pertenece a esta jornada'):
            preparar_entrada_v2(self.jornada, MODO_INTEGRAL, [], PIPELINE_LLM,
                                adjuntos=[{'asset': ajeno.id, 'uso': 'contexto'}])


class ValidacionConAdjuntosTests(TestCase):
    """Sobre el par de ejemplo de la entrega: un adjunto como fuente es citable y verificable; uno
    de contexto no puede aparecer como fuente de nada."""

    def setUp(self):
        leer = lambda n: json.loads((RECURSOS / 'ejemplos' / n).read_text(encoding='utf-8'))  # noqa: E731
        self.entrada, self.salida = leer('llm_integral.entrada.json'), leer('llm_integral.salida.json')
        self.fuente = {
            'id': 'f-adj7', 'tipo': 'resumen_secundario', 'etiqueta': 'Documento adjunto — Acuerdo',
            'momento_ids': [], 'pregunta_ids': [], 'cobertura': 'desconocida',
            'datos': {'texto': TEXTO_DOCUMENTO, 'fuentes_originales_ids': [], 'metodo_resumen': 'x',
                      'cobertura_original': 'desconocida'},
        }
        self.entrada['fuentes'].append(self.fuente)
        self.entrada['referencias'] = {'nota': NOTA_REFERENCIAS, 'documentos': [{'id': 'ref-adj8', 'texto': 'ctx'}]}
        self.salida['fuentes'].append({k: v for k, v in self.fuente.items() if k != 'datos'})
        self.hallazgo = self.salida['informes'][0]['hallazgos'][0]
        self.hallazgo['fuente_ids'].append('f-adj7')

    def test_cita_literal_del_adjunto_valida(self):
        self.hallazgo['citas'].append({'fuente_id': 'f-adj7', 'texto': 'una franja al final de la tarde', 'localizador': '/texto'})
        self.assertEqual(validar_negocio(self.salida, self.entrada), [])

    def test_cita_inventada_del_adjunto_no_valida(self):
        self.hallazgo['citas'].append({'fuente_id': 'f-adj7', 'texto': 'cerrará la sede', 'localizador': '/texto'})
        self.assertTrue(any('subcadena literal' in e for e in validar_negocio(self.salida, self.entrada)))

    def test_cita_con_localizador_equivocado_se_relocaliza_al_texto(self):
        self.hallazgo['citas'].append({'fuente_id': 'f-adj7', 'texto': 'una franja al final de la tarde', 'localizador': '/respuestas/0/valor'})
        normalizar_salida(self.salida, self.entrada)
        self.assertEqual(self.hallazgo['citas'][-1]['localizador'], '/texto')
        self.assertEqual(validar_negocio(self.salida, self.entrada), [])

    def test_una_referencia_de_contexto_no_puede_ser_fuente(self):
        self.hallazgo['fuente_ids'].append('ref-adj8')
        self.assertTrue(any('no declaradas' in e for e in validar_negocio(self.salida, self.entrada)))


class ProcesarConAdjuntosTests(BaseAdjuntos):
    def _salida_valida(self, system, user, **_):
        return construir_salida_sin_datos(json.loads(user), 'llm'), None, {'finish_reason': 'stop'}

    def test_la_entrada_guardada_lleva_los_adjuntos(self):
        a = AnalisisV2.objects.create(jornada=self.jornada, modo='integral', pipeline='llm',
                                      adjuntos=[{'asset': self.doc.id, 'uso': 'fuente'}])
        with patch('analitica.v2.procesar.llamar_openai_estructurado', side_effect=self._salida_valida) as llamada:
            procesar_analisis_v2(a.id)
        a.refresh_from_db()
        self.assertEqual(a.estado, AnalisisV2.ESTADO_COMPLETO, a.error_mensaje)
        self.assertIn(f'f-adj{self.doc.id}', [f['id'] for f in a.entrada['fuentes']])
        self.assertIn(TEXTO_DOCUMENTO, llamada.call_args.args[1])

    def test_adjunto_ilegible_deja_el_analisis_en_error_sin_llamar(self):
        a = AnalisisV2.objects.create(jornada=self.jornada, modo='integral', pipeline='llm',
                                      adjuntos=[{'asset': self.foto.id, 'uso': 'contexto'}])
        with patch('analitica.v2.procesar.llamar_openai_estructurado') as llamada:
            procesar_analisis_v2(a.id)
        a.refresh_from_db()
        llamada.assert_not_called()
        self.assertEqual(a.estado, AnalisisV2.ESTADO_ERROR)
        self.assertIn('No se pudo leer el adjunto', a.error_mensaje)


@override_settings(MEDIA_ROOT=MEDIA_TEMPORAL)
class ApiAdjuntosTests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.client.force_authenticate(user=self.admin)
        self.d = crear_jornada_completa()
        self.jornada = self.d['jornada']
        self.doc = _asset(self.jornada, 'acuerdo.txt', TEXTO_DOCUMENTO.encode('utf-8'))
        self.ajeno = _asset(crear_jornada('otra'), 'x.txt', b'x')

    def _post(self, url, cuerpo):
        with patch('analitica.admin_views.threading.Thread'):
            return self.client.post(url, cuerpo, format='json')

    def test_analisis_v2_guarda_los_adjuntos_normalizados(self):
        resp = self._post('/api/admin/analisis-v2/', {
            'jornada': self.jornada.id, 'modo': 'integral', 'pipeline': 'llm',
            'adjuntos': [{'asset': self.doc.id, 'uso': 'fuente'}],
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['adjuntos'], [{'asset': self.doc.id, 'uso': 'fuente'}])

    def test_un_id_suelto_es_contexto(self):
        resp = self._post('/api/admin/analisis-jornada-ia/', {'jornada': self.jornada.id, 'adjuntos': [self.doc.id]})
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(AnalisisJornadaIA.objects.get(pk=resp.data['id']).adjuntos,
                         [{'asset': self.doc.id, 'uso': 'contexto'}])

    def test_rechaza_asset_de_otra_jornada_repetido_o_uso_desconocido(self):
        base = {'jornada': self.jornada.id, 'modo': 'integral', 'pipeline': 'llm'}
        for adjuntos in ([self.ajeno.id], [self.doc.id, self.doc.id], [{'asset': self.doc.id, 'uso': 'evidencia'}]):
            resp = self._post('/api/admin/analisis-v2/', {**base, 'adjuntos': adjuntos})
            self.assertEqual(resp.status_code, 400, adjuntos)
            self.assertIn('adjuntos', resp.data)

    def test_resumen_solo_admite_contexto(self):
        entrada = construir_entrada(self.jornada, MODO_INTEGRAL, [])
        analisis = AnalisisJornadaIA.objects.create(
            jornada=self.jornada, estado=AnalisisJornadaIA.ESTADO_COMPLETO, entrada=entrada,
            resultado=construir_salida_sin_datos(entrada, 'llm'),
        )
        url = '/api/admin/resumenes-presentacion/'
        resp = self._post(url, {'analisis_jornada': analisis.id, 'adjuntos': [{'asset': self.doc.id, 'uso': 'fuente'}]})
        self.assertEqual(resp.status_code, 400, resp.data)
        resp = self._post(url, {'analisis_jornada': analisis.id, 'adjuntos': [self.doc.id]})
        self.assertEqual(resp.status_code, 201, resp.data)
        resumen = ResumenPresentacion.objects.get(pk=resp.data['id'])
        self.assertEqual(resumen.adjuntos, [self.doc.id])
        self.assertEqual(entrada_del_resumen(resumen)['referencias']['documentos'][0]['texto'], TEXTO_DOCUMENTO)

    def test_subir_documento_lo_lee_en_segundo_plano(self):
        archivo = SimpleUploadedFile('marco.md', b'# Marco\nTexto')
        with patch('jornadas.views.threading.Thread') as hilo:
            resp = self.client.post('/api/admin/jornada-assets/', {
                'jornada': self.jornada.id, 'tipo': 'documento', 'archivos': [archivo],
                'titulo': 'Marco institucional', 'descripcion': 'Plan de desarrollo',
            }, format='multipart')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data[0]['nombre'], 'Marco institucional')
        self.assertEqual(resp.data[0]['contenido_estado'], 'sin_leer')
        hilo.return_value.start.assert_called_once()

    def test_documento_rechaza_formato_de_imagen(self):
        resp = self.client.post('/api/admin/jornada-assets/', {
            'jornada': self.jornada.id, 'tipo': 'documento', 'archivos': [SimpleUploadedFile('a.png', _png())],
        }, format='multipart')
        self.assertEqual(resp.status_code, 400)

    def test_patch_corrige_el_contenido_y_lo_marca_como_escrito(self):
        resp = self.client.patch(f'/api/admin/jornada-assets/{self.doc.id}/', {
            'contenido_texto': 'Texto corregido', 'usar_en_presentacion': False,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.contenido_texto, 'Texto corregido')
        self.assertEqual(self.doc.contenido_estado, JornadaAsset.CONTENIDO_LISTO)
        self.assertEqual(self.doc.contenido_metodo, JornadaAsset.METODO_TEXTO_ESCRITO)
        self.assertFalse(self.doc.usar_en_presentacion)


class PresentacionConAdjuntosTests(BaseAdjuntos):
    def test_diseno_no_recibe_documentos_ni_imagenes_excluidas(self):
        oculta = _asset(self.jornada, 'solo-analisis.png', _png(), tipo=JornadaAsset.TIPO_ASSET, usar_en_presentacion=False)
        resumen, imagenes = _reunir_assets(self.jornada)
        ids = [a['id'] for a in resumen]
        self.assertIn(str(self.foto.id), ids)
        self.assertNotIn(str(self.doc.id), ids)
        self.assertNotIn(str(oculta.id), ids)
        self.assertEqual([i[0] for i in imagenes], [str(self.foto.id)])
        self.assertEqual(next(a for a in resumen if a['id'] == str(self.foto.id))['descripcion'], 'Papelógrafo de la mesa 3')


class ComandoPromptsAdjuntosTests(TestCase):
    def test_crea_y_activa_una_version_por_tipo_y_es_idempotente(self):
        antes = {t: SystemPrompt.activo_de(t).version for t in ('analisis_llm', 'analisis_bertopic', 'resumen_presentacion')}
        call_command('actualizar_prompts_adjuntos', '--activar', stdout=StringIO())
        for tipo, version in antes.items():
            activo = SystemPrompt.activo_de(tipo)
            self.assertEqual(activo.version, version + 1)
            self.assertIn('Adjuntos del análisis (HU-101)', activo.contenido)
        call_command('actualizar_prompts_adjuntos', '--activar', stdout=StringIO())
        self.assertEqual(SystemPrompt.activo_de('analisis_llm').version, antes['analisis_llm'] + 1)
