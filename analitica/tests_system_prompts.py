"""HU-92: los system prompts de la analítica viven en la tabla `SystemPrompt`, versionados,
inmutables desde que se activan, uno activo por tipo, y cada flujo usa el activo de su tipo."""
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APITestCase

from .models import AnalisisV2, SystemPrompt, SystemPromptInmutable
from .tests import crear_admin_completo, crear_dependencia
from .tests_v2 import crear_jornada_completa
from .v2.procesar import procesar_analisis_v2

URL = '/api/admin/system-prompts/'
SEMILLA = Path(__file__).resolve().parent / 'system_prompts_semilla'


class SiembraTests(TestCase):
    def test_cada_tipo_arranca_con_su_version_1_activa(self):
        activos = {p.tipo: p for p in SystemPrompt.objects.filter(activo=True)}
        self.assertEqual(set(activos), {tipo for tipo, _ in SystemPrompt.TIPO_CHOICES})
        for tipo, prompt in activos.items():
            self.assertEqual(prompt.version, 1)
            self.assertTrue(prompt.inmutable)
            self.assertEqual(prompt.contenido, (SEMILLA / f'{tipo}.md').read_text(encoding='utf-8'))


class ModeloTests(TestCase):
    def setUp(self):
        self.v1 = SystemPrompt.activo_de(SystemPrompt.TIPO_ANALISIS_LLM)

    def test_la_version_se_numera_sola_por_tipo(self):
        nueva = SystemPrompt.objects.create(tipo=SystemPrompt.TIPO_ANALISIS_LLM, contenido='x')
        otra_tipo = SystemPrompt.objects.create(tipo=SystemPrompt.TIPO_INFOGRAFIA, contenido='y')
        self.assertEqual(nueva.version, 2)
        self.assertEqual(otra_tipo.version, 2)
        self.assertFalse(nueva.activo)

    def test_una_version_activada_no_se_puede_modificar_ni_borrar(self):
        self.v1.contenido = 'cambiado'
        with self.assertRaises(SystemPromptInmutable):
            self.v1.save()
        with self.assertRaises(SystemPromptInmutable):
            SystemPrompt.objects.get(pk=self.v1.pk).delete()

    def test_activar_deja_una_sola_activa_y_la_anterior_sigue_inmutable(self):
        nueva = SystemPrompt.objects.create(tipo=SystemPrompt.TIPO_ANALISIS_LLM, contenido='nuevo')
        nueva.activar()
        self.v1.refresh_from_db()
        self.assertTrue(nueva.activo)
        self.assertFalse(self.v1.activo)
        self.assertTrue(self.v1.inmutable)
        self.assertEqual(SystemPrompt.activo_de(SystemPrompt.TIPO_ANALISIS_LLM), nueva)
        # Los otros tipos no se tocan.
        self.assertTrue(SystemPrompt.objects.filter(tipo=SystemPrompt.TIPO_INFOGRAFIA, activo=True).exists())

    def test_volver_a_una_anterior_no_cambia_su_fecha_de_activacion(self):
        primera_activacion = self.v1.activado_en
        SystemPrompt.objects.create(tipo=SystemPrompt.TIPO_ANALISIS_LLM, contenido='nuevo').activar()
        self.v1.activar()
        self.assertTrue(self.v1.activo)
        self.assertEqual(self.v1.activado_en, primera_activacion)

    def test_sin_activo_el_error_dice_que_hacer(self):
        SystemPrompt.objects.filter(tipo=SystemPrompt.TIPO_SUGERENCIAS).update(activo=False)
        with self.assertRaisesMessage(SystemPrompt.DoesNotExist, 'system-prompts'):
            SystemPrompt.activo_de(SystemPrompt.TIPO_SUGERENCIAS)


class ApiTests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin_prompts')
        self.client.force_authenticate(user=self.admin)

    def _crear(self, **extra):
        cuerpo = {'tipo': 'analisis_bertopic', 'contenido': 'Prompt nuevo', 'etiqueta': 'prueba', **extra}
        return self.client.post(URL, cuerpo, format='json')

    def test_listar_por_tipo_sin_contenido(self):
        resp = self.client.get(URL, {'tipo': 'infografia'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertNotIn('contenido', resp.data[0])
        self.assertEqual(resp.data[0]['referencia'], 'infografia#1')

    def test_activos_trae_uno_por_tipo_con_contenido(self):
        resp = self.client.get(f'{URL}activos/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), len(SystemPrompt.TIPO_CHOICES))
        self.assertTrue(all(p['contenido'] for p in resp.data))

    def test_borrador_se_edita_y_se_borra(self):
        creado = self._crear().data
        self.assertEqual(creado['version'], 2)
        self.assertFalse(creado['activo'])

        resp = self.client.patch(f'{URL}{creado["id"]}/', {'contenido': 'Corregido'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['contenido'], 'Corregido')
        self.assertEqual(self.client.delete(f'{URL}{creado["id"]}/').status_code, 204)

    def test_activada_es_inmutable_por_la_api(self):
        creado = self._crear().data
        self.assertEqual(self.client.post(f'{URL}{creado["id"]}/activar/').status_code, 200)

        resp = self.client.patch(f'{URL}{creado["id"]}/', {'contenido': 'Otro'}, format='json')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.client.delete(f'{URL}{creado["id"]}/').status_code, 409)
        self.assertEqual(SystemPrompt.objects.get(pk=creado['id']).contenido, 'Prompt nuevo')

    def test_crear_y_activar_en_un_paso(self):
        creado = self._crear(activar=True).data
        self.assertTrue(creado['activo'])
        self.assertEqual(SystemPrompt.activo_de('analisis_bertopic').id, creado['id'])

    def test_contenido_vacio_es_400(self):
        self.assertEqual(self._crear(contenido='   ').status_code, 400)

    def test_dependencia_lee_pero_no_crea_ni_activa(self):
        self.client.force_authenticate(user=crear_dependencia('dep_prompts'))
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.assertEqual(self._crear().status_code, 403)
        v1 = SystemPrompt.activo_de('analisis_llm')
        self.assertEqual(self.client.post(f'{URL}{v1.id}/activar/').status_code, 403)


class LosFlujosUsanElActivoTests(TestCase):
    def test_el_analisis_v2_usa_y_registra_la_version_activa(self):
        nueva = SystemPrompt.objects.create(tipo='analisis_llm', contenido='SYSTEM DE PRUEBA v2')
        nueva.activar()
        d = crear_jornada_completa()
        analisis = AnalisisV2.objects.create(jornada=d['jornada'], modo='integral', pipeline='llm')

        with patch('analitica.v2.procesar.llamar_openai_estructurado',
                   return_value=(None, 'corte de prueba', {})) as llamada:
            procesar_analisis_v2(analisis.id)

        self.assertEqual(llamada.call_args.args[0], 'SYSTEM DE PRUEBA v2')
        analisis.refresh_from_db()
        self.assertEqual(analisis.version_prompt, 'analisis_llm#2')

    def test_el_pipeline_bertopic_usa_su_propio_tipo(self):
        SystemPrompt.objects.create(tipo='analisis_bertopic', contenido='SYSTEM BERTOPIC').activar()
        d = crear_jornada_completa()
        analisis = AnalisisV2.objects.create(jornada=d['jornada'], modo='integral', pipeline='bertopic_llm')

        with patch('analitica.v2.procesar.llamar_openai_estructurado',
                   return_value=(None, 'corte de prueba', {})) as llamada, \
                patch('analitica.v2.bertopic_adaptador.anexar_bertopic', side_effect=lambda e, **k: (e, [])):
            procesar_analisis_v2(analisis.id)

        self.assertEqual(llamada.call_args.args[0], 'SYSTEM BERTOPIC')

    def test_la_infografia_usa_el_activo(self):
        from .infografia_ia_openai import SLIDES, _construir_prompt

        SystemPrompt.objects.create(tipo='infografia', contenido='PREFIJO NUEVO').activar()
        prompt = _construir_prompt({'jornada': 'J'}, slide=SLIDES[0])
        self.assertTrue(prompt.startswith('PREFIJO NUEVO'))
        # La regla de datos sigue al final, fuera del alcance de cualquier versión.
        self.assertIn('REGLA INNEGOCIABLE', prompt)


class DjangoAdminTests(TestCase):
    """Lo mismo desde /admin/: activar y partir de una versión son acciones de la lista."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        self.su = get_user_model().objects.create_superuser('su_prompts', 'su@x.co', 'pass12345')
        self.client.force_login(self.su)
        self.v1 = SystemPrompt.activo_de('sugerencias')
        self.lista = '/admin/analitica/systemprompt/'

    def _accion(self, accion, *ids):
        return self.client.post(self.lista, {'action': accion, '_selected_action': [str(i) for i in ids]})

    def test_lista_y_detalle_cargan(self):
        self.assertEqual(self.client.get(self.lista).status_code, 200)
        self.assertEqual(self.client.get(f'{self.lista}{self.v1.pk}/change/').status_code, 200)
        self.assertEqual(self.client.get(f'{self.lista}add/').status_code, 200)

    def test_una_activada_no_se_edita_desde_el_formulario(self):
        self.client.post(f'{self.lista}{self.v1.pk}/change/', {'contenido': 'pisado', 'etiqueta': 'x', 'notas': ''})
        self.v1.refresh_from_db()
        self.assertNotEqual(self.v1.contenido, 'pisado')

    def test_crear_borrador_y_activarlo(self):
        resp = self.client.post(f'{self.lista}add/', {
            'tipo': 'sugerencias', 'contenido': 'Nuevo desde admin', 'etiqueta': 'admin', 'notas': '',
        })
        self.assertEqual(resp.status_code, 302)
        nueva = SystemPrompt.objects.get(tipo='sugerencias', version=2)
        self.assertEqual(nueva.creado_por, self.su)

        self._accion('activar_version', nueva.pk)
        self.assertEqual(SystemPrompt.activo_de('sugerencias'), nueva)

    def test_nueva_version_desde_una_existente(self):
        resp = self._accion('nueva_version_desde_esta', self.v1.pk)
        nueva = SystemPrompt.objects.get(tipo='sugerencias', version=2)
        self.assertRedirects(resp, f'{self.lista}{nueva.pk}/change/')
        self.assertEqual(nueva.contenido, self.v1.contenido)
        self.assertFalse(nueva.activo)

    def test_una_activada_no_se_borra(self):
        self.assertEqual(self.client.get(f'{self.lista}{self.v1.pk}/delete/').status_code, 403)
        self.assertTrue(SystemPrompt.objects.filter(pk=self.v1.pk).exists())
