import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from jornadas.models import Jornada, Momento, PerfilUsuario, Pregunta

from .models import AnalisisJornadaIA, AnalisisMomentoIA, InfografiaJornada, PlantillaAnalisis, Reporte

Usuario = get_user_model()


def crear_jornada(slug, propietario=None):
    jornada = Jornada.objects.create(
        slug=slug, nombre=slug, fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 2),
    )
    if propietario:
        jornada.propietarios.set([propietario])
    return jornada


def crear_momento_con_respuesta(jornada, orden=1, titulo='Momento con datos'):
    """Un momento con una pregunta abierta y UNA respuesta real — lo mínimo para pasar el guard
    de "sin respuestas en el alcance" (HU-57 §5, ver `_sin_respuestas` en admin_views.py) sin
    tener que montar un instrumento completo en cada test."""
    from participantes.models import Respuesta

    momento = Momento.objects.create(jornada=jornada, orden=orden, titulo=titulo)
    pregunta = Pregunta.objects.create(momento=momento, tipo=Pregunta.TIPO_ABIERTA, texto='¿Qué opinas?', orden=1)
    Respuesta.objects.create(pregunta=pregunta, texto_libre='Una respuesta real de prueba.')
    return momento


def crear_dependencia(username):
    usuario = Usuario.objects.create_user(username=username, password='pass12345', is_staff=True)
    PerfilUsuario.objects.create(user=usuario, rol=PerfilUsuario.ROL_DEPENDENCIA)
    return usuario


def crear_admin_completo(username):
    return Usuario.objects.create_user(username=username, password='pass12345', is_staff=True)


class ReporteScopingTests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dependencia_a = crear_dependencia('dependencia_a')
        self.jornada_a = crear_jornada('jornada-a', propietario=self.dependencia_a)
        self.jornada_b = crear_jornada('jornada-b')
        # estado=COMPLETO a propósito: ReporteViewSet.create() bloquea con 409 si hay OTRO
        # reporte pendiente/procesando (un solo análisis a la vez, ver el guard en
        # admin_views.py) — dejarlos en pendiente haría que ese guard se dispare antes de
        # llegar a la validación de ownership que estos tests quieren probar.
        self.reporte_a = Reporte.objects.create(
            jornada=self.jornada_a, alcance=Reporte.ALCANCE_JORNADA, estado=Reporte.ESTADO_COMPLETO,
        )
        self.reporte_b = Reporte.objects.create(
            jornada=self.jornada_b, alcance=Reporte.ALCANCE_JORNADA, estado=Reporte.ESTADO_COMPLETO,
        )

    def test_dependencia_solo_ve_reportes_de_su_jornada(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.get('/api/admin/reportes/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r['id'] for r in resp.data], [self.reporte_a.id])

    def test_admin_completo_ve_todos_los_reportes(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/admin/reportes/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({r['id'] for r in resp.data}, {self.reporte_a.id, self.reporte_b.id})

    def test_dependencia_no_puede_pedir_reporte_de_jornada_ajena(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post('/api/admin/reportes/', {'jornada': self.jornada_b.id}, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Reporte.objects.filter(jornada=self.jornada_b).exclude(id=self.reporte_b.id).exists())

    def test_dependencia_no_puede_ver_reporte_de_jornada_ajena(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.get(f'/api/admin/reportes/{self.reporte_b.id}/')
        self.assertEqual(resp.status_code, 404)


class AnalisisJornadaIAScopingTests(APITestCase):
    """Análisis de jornada completa vía GPT (AnalisisJornadaIA) — mismo scoping por dependencia
    que ya prueba ReporteScopingTests para Reporte, aplicado a este endpoint independiente."""
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dependencia_a = crear_dependencia('dependencia_a')
        self.jornada_a = crear_jornada('jornada-a', propietario=self.dependencia_a)
        self.jornada_b = crear_jornada('jornada-b')
        # estado=COMPLETO a propósito, mismo motivo que en ReporteScopingTests: dejarlos en
        # pendiente/procesando dispararía el guard de "ya hay un análisis en curso" (409) antes
        # de llegar a la validación de ownership que estos tests quieren probar.
        self.analisis_a = AnalisisJornadaIA.objects.create(
            jornada=self.jornada_a, estado=AnalisisJornadaIA.ESTADO_COMPLETO,
        )
        self.analisis_b = AnalisisJornadaIA.objects.create(
            jornada=self.jornada_b, estado=AnalisisJornadaIA.ESTADO_COMPLETO,
        )

    def test_dependencia_solo_ve_analisis_de_su_jornada(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.get('/api/admin/analisis-jornada-ia/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([a['id'] for a in resp.data], [self.analisis_a.id])

    def test_admin_completo_ve_todos_los_analisis(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/admin/analisis-jornada-ia/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({a['id'] for a in resp.data}, {self.analisis_a.id, self.analisis_b.id})

    def test_dependencia_no_puede_pedir_analisis_de_jornada_ajena(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post('/api/admin/analisis-jornada-ia/', {'jornada': self.jornada_b.id}, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(
            AnalisisJornadaIA.objects.filter(jornada=self.jornada_b).exclude(id=self.analisis_b.id).exists()
        )

    def test_dependencia_no_puede_ver_analisis_de_jornada_ajena(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.get(f'/api/admin/analisis-jornada-ia/{self.analisis_b.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_no_deja_pedir_dos_analisis_a_la_vez_para_la_misma_jornada(self):
        self.analisis_a.estado = AnalisisJornadaIA.ESTADO_PROCESANDO
        self.analisis_a.save(update_fields=['estado'])
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post('/api/admin/analisis-jornada-ia/', {'jornada': self.jornada_a.id}, format='json')
        self.assertEqual(resp.status_code, 409)


class InfografiaSinReporteTests(APITestCase):
    """La infografía se pide a nivel de JORNADA. Exigir un `Reporte` dejaba sin salida al panel,
    que usa el reporte integral (AnalisisJornadaIA) y no el pipeline local."""

    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dependencia = crear_dependencia('dependencia_a')
        self.jornada = crear_jornada('jornada-a', propietario=self.dependencia)
        self.ajena = crear_jornada('jornada-b')

    def _analisis_integral_completo(self, jornada):
        return AnalisisJornadaIA.objects.create(
            jornada=jornada, estado=AnalisisJornadaIA.ESTADO_COMPLETO,
            resultado={'resumen_ejecutivo': 'Hubo consenso.', 'hallazgos': [{'titulo': 'Tema'}]},
        )

    def test_genera_desde_el_reporte_integral_sin_reporte_local(self):
        self._analisis_integral_completo(self.jornada)
        self.client.force_authenticate(user=self.admin)
        with patch('analitica.admin_views.threading.Thread'):
            resp = self.client.post(
                '/api/admin/infografias/', {'jornada': self.jornada.id}, format='json',
            )
        self.assertEqual(resp.status_code, 201)
        infografia = InfografiaJornada.objects.get(id=resp.data['id'])
        self.assertEqual(infografia.jornada, self.jornada)
        self.assertIsNone(infografia.reporte)
        self.assertEqual(Reporte.objects.count(), 0)

    def test_400_si_la_jornada_no_tiene_analitica(self):
        """Se avisa de una vez, en vez de crear un registro que va a fallar en background."""
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            '/api/admin/infografias/', {'jornada': self.jornada.id}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(InfografiaJornada.objects.count(), 0)

    def test_409_si_ya_hay_una_en_curso(self):
        self._analisis_integral_completo(self.jornada)
        InfografiaJornada.objects.create(
            jornada=self.jornada, estado=InfografiaJornada.ESTADO_PROCESANDO,
        )
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            '/api/admin/infografias/', {'jornada': self.jornada.id}, format='json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_dependencia_no_puede_pedirla_para_jornada_ajena(self):
        self._analisis_integral_completo(self.ajena)
        self.client.force_authenticate(user=self.dependencia)
        resp = self.client.post(
            '/api/admin/infografias/', {'jornada': self.ajena.id}, format='json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(InfografiaJornada.objects.count(), 0)

    def test_dependencia_solo_ve_las_de_su_jornada(self):
        InfografiaJornada.objects.create(jornada=self.jornada)
        InfografiaJornada.objects.create(jornada=self.ajena)
        self.client.force_authenticate(user=self.dependencia)
        resp = self.client.get('/api/admin/infografias/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([i['jornada'] for i in resp.data], [self.jornada.id])

    def test_rechaza_un_reporte_de_otra_jornada(self):
        reporte_ajeno = Reporte.objects.create(
            jornada=self.ajena, alcance=Reporte.ALCANCE_JORNADA, estado=Reporte.ESTADO_COMPLETO,
        )
        self._analisis_integral_completo(self.jornada)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post('/api/admin/infografias/', {
            'jornada': self.jornada.id, 'reporte': reporte_ajeno.id,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_el_atajo_desde_un_reporte_sigue_funcionando(self):
        reporte = Reporte.objects.create(
            jornada=self.jornada, alcance=Reporte.ALCANCE_JORNADA,
            estado=Reporte.ESTADO_COMPLETO, analisis={'participacion': {'total': 3}},
        )
        self.client.force_authenticate(user=self.admin)
        with patch('analitica.admin_views.threading.Thread'):
            resp = self.client.post(f'/api/admin/reportes/{reporte.id}/generar-infografia/')
        self.assertEqual(resp.status_code, 202)
        infografia = InfografiaJornada.objects.get()
        self.assertEqual(infografia.jornada, self.jornada)
        self.assertEqual(infografia.reporte, reporte)


class PlantillaAnalisisPermisosTests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dependencia = crear_dependencia('dependencia_a')
        self.plantilla = PlantillaAnalisis.objects.create(
            nombre='Plantilla base', tipo=PlantillaAnalisis.TIPO_LOCAL, prompt_sistema='Instrucciones',
        )

    def test_dependencia_puede_leer_plantillas(self):
        self.client.force_authenticate(user=self.dependencia)
        resp = self.client.get('/api/admin/plantillas-analisis/')
        self.assertEqual(resp.status_code, 200)

    def test_dependencia_no_puede_crear_plantillas(self):
        self.client.force_authenticate(user=self.dependencia)
        resp = self.client.post('/api/admin/plantillas-analisis/', {
            'nombre': 'Otra', 'tipo': PlantillaAnalisis.TIPO_LOCAL, 'prompt_sistema': 'Texto',
        }, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_admin_completo_puede_crear_plantillas(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post('/api/admin/plantillas-analisis/', {
            'nombre': 'Otra', 'tipo': PlantillaAnalisis.TIPO_LOCAL, 'prompt_sistema': 'Texto',
        }, format='json')
        self.assertEqual(resp.status_code, 201)


class PayloadJornadaConTranscripcionesTests(APITestCase):
    """El análisis de jornada (AnalisisJornadaIA) reutiliza el informe YA CALCULADO de cualquier
    grabación vinculada y marcada para incluirse — nunca vuelve a leer la transcripción cruda.
    Ver analitica/analisis_ia_openai.py::_construir_payload_jornada/_transcripciones_payload."""

    def setUp(self):
        self.jornada = crear_jornada('jornada-con-grabacion')

    def _payload(self):
        from .analisis_ia_openai import _construir_payload_jornada
        return _construir_payload_jornada(self.jornada)

    def test_jornada_sin_transcripciones_da_lista_vacia(self):
        self.assertEqual(self._payload()['transcripciones'], [])

    def test_incluye_informe_completo_de_sesion_vinculada_e_incluida(self):
        from transcripciones.models import InformeTranscripcion, SesionTranscripcion

        sesion = SesionTranscripcion.objects.create(
            nombre='Reunión de comité', jornada=self.jornada, incluir_en_analisis_jornada=True,
        )
        InformeTranscripcion.objects.create(
            sesion=sesion, estado=InformeTranscripcion.ESTADO_COMPLETO,
            resultado={
                'resumen_ejecutivo': 'Se acordó revisar el presupuesto.',
                'temas_discutidos': ['presupuesto'],
                'hallazgos': [{'titulo': 'Acuerdo presupuestal', 'descripcion': '...', 'citas': []}],
            },
        )

        transcripciones = self._payload()['transcripciones']
        self.assertEqual(len(transcripciones), 1)
        self.assertEqual(transcripciones[0]['sesion_id'], sesion.id)
        self.assertEqual(transcripciones[0]['resumen_ejecutivo'], 'Se acordó revisar el presupuesto.')

    def test_excluye_sesion_marcada_para_no_incluirse(self):
        from transcripciones.models import InformeTranscripcion, SesionTranscripcion

        sesion = SesionTranscripcion.objects.create(
            nombre='Reunión aparte', jornada=self.jornada, incluir_en_analisis_jornada=False,
        )
        InformeTranscripcion.objects.create(sesion=sesion, estado=InformeTranscripcion.ESTADO_COMPLETO)

        self.assertEqual(self._payload()['transcripciones'], [])

    def test_excluye_sesion_sin_informe_completo(self):
        from transcripciones.models import InformeTranscripcion, SesionTranscripcion

        sesion = SesionTranscripcion.objects.create(nombre='Sin informe listo', jornada=self.jornada)
        InformeTranscripcion.objects.create(sesion=sesion, estado=InformeTranscripcion.ESTADO_PROCESANDO)

        self.assertEqual(self._payload()['transcripciones'], [])

    def test_toma_el_informe_completo_mas_reciente(self):
        from django.utils import timezone

        from transcripciones.models import InformeTranscripcion, SesionTranscripcion

        sesion = SesionTranscripcion.objects.create(nombre='Con reintento', jornada=self.jornada)
        InformeTranscripcion.objects.create(
            sesion=sesion, estado=InformeTranscripcion.ESTADO_COMPLETO,
            resultado={'resumen_ejecutivo': 'Versión vieja'},
            completado_en=timezone.now() - datetime.timedelta(days=1),
        )
        InformeTranscripcion.objects.create(
            sesion=sesion, estado=InformeTranscripcion.ESTADO_COMPLETO,
            resultado={'resumen_ejecutivo': 'Versión nueva'},
            completado_en=timezone.now(),
        )

        transcripciones = self._payload()['transcripciones']
        self.assertEqual(len(transcripciones), 1)
        self.assertEqual(transcripciones[0]['resumen_ejecutivo'], 'Versión nueva')


class AnalisisGuiadoCamposTests(APITestCase):
    """HU-57 (docs/HU_BACKEND_ANALISIS_GUIADO.md) §1: enfoque/contexto/instrucciones en las tres
    solicitudes de análisis, persistidos y devueltos tal cual. No espera a que el hilo en
    background termine (no hay OPENAI_API_KEY en el entorno de test): solo verifica la respuesta
    síncrona del `create()`, que es donde vive el contrato que describe la HU."""
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.jornada = crear_jornada('jornada-guiada', propietario=self.admin)
        self.momento = crear_momento_con_respuesta(self.jornada)
        self.client.force_authenticate(user=self.admin)

    def test_reporte_persiste_y_devuelve_los_campos_guiados(self):
        resp = self.client.post('/api/admin/reportes/', {
            'jornada': self.jornada.id,
            'momentos': [self.momento.id],
            'enfoque': 'cualitativo',
            'contexto': 'Jornada de percepción sobre bienestar.',
            'instrucciones': 'Tono cercano.',
            'contexto_momento': 'Este momento se trabajó en mesas.',
            'instrucciones_momento': 'Destaca tensiones.',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['metodo'], 'bertopic')
        self.assertEqual(resp.data['enfoque'], 'cualitativo')
        self.assertEqual(resp.data['contexto'], 'Jornada de percepción sobre bienestar.')
        self.assertEqual(resp.data['instrucciones'], 'Tono cercano.')
        self.assertEqual(resp.data['contexto_momento'], 'Este momento se trabajó en mesas.')
        self.assertEqual(resp.data['instrucciones_momento'], 'Destaca tensiones.')

    def test_reporte_enfoque_por_defecto_es_mixto(self):
        resp = self.client.post(
            '/api/admin/reportes/', {'jornada': self.jornada.id, 'momentos': [self.momento.id]}, format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['enfoque'], 'mixto')

    def test_reporte_enfoque_invalido_da_400(self):
        resp = self.client.post('/api/admin/reportes/', {
            'jornada': self.jornada.id, 'momentos': [self.momento.id], 'enfoque': 'no-existe',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('enfoque', resp.data)

    def test_reporte_sin_respuestas_en_el_alcance_da_400_explicito(self):
        momento_vacio = Momento.objects.create(jornada=self.jornada, orden=99, titulo='Vacío')
        resp = self.client.post(
            '/api/admin/reportes/', {'jornada': self.jornada.id, 'momentos': [momento_vacio.id]}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('no tiene respuestas', str(resp.data))
        self.assertFalse(Reporte.objects.filter(jornada=self.jornada, momentos=momento_vacio).exists())

    def test_analisis_momento_persiste_campos_guiados_y_metodo(self):
        resp = self.client.post('/api/admin/analisis-momento-ia/', {
            'momento': self.momento.id, 'enfoque': 'cuantitativo', 'contexto': 'Ctx',
            'instrucciones': 'Instr', 'contexto_momento': 'CtxM', 'instrucciones_momento': 'InstrM',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['metodo'], 'openai')
        self.assertEqual(resp.data['enfoque'], 'cuantitativo')
        self.assertEqual(resp.data['momento_orden'], self.momento.orden)
        self.assertEqual(resp.data['contexto_momento'], 'CtxM')

    def test_analisis_momento_sin_respuestas_da_400(self):
        momento_vacio = Momento.objects.create(jornada=self.jornada, orden=99, titulo='Vacío')
        resp = self.client.post('/api/admin/analisis-momento-ia/', {'momento': momento_vacio.id}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(AnalisisMomentoIA.objects.filter(momento=momento_vacio).exists())

    def test_analisis_jornada_persiste_campos_guiados_y_metodo(self):
        resp = self.client.post('/api/admin/analisis-jornada-ia/', {
            'jornada': self.jornada.id, 'enfoque': 'mixto', 'contexto': 'Ctx', 'instrucciones': 'Instr',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['metodo'], 'openai')
        self.assertEqual(resp.data['contexto'], 'Ctx')

    def test_analisis_jornada_sin_momentos_activos_con_respuestas_da_400(self):
        jornada_vacia = crear_jornada('jornada-sin-datos', propietario=self.admin)
        Momento.objects.create(jornada=jornada_vacia, orden=1, titulo='Sin respuestas')
        resp = self.client.post('/api/admin/analisis-jornada-ia/', {'jornada': jornada_vacia.id}, format='json')
        self.assertEqual(resp.status_code, 400)


class AnalisisSugerenciasViewTests(APITestCase):
    """HU-57 §3. Sin OPENAI_API_KEY en el entorno de test, `generar_sugerencias` devuelve `[]`
    determinísticamente (ver sugerencias_ia_openai.py) — alcanza para probar el contrato HTTP
    (200 con la forma esperada, 400 de validación, 403 de scoping) sin mockear la llamada."""
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dependencia = crear_dependencia('dependencia')
        self.jornada = crear_jornada('jornada-sug', propietario=self.dependencia)
        self.jornada_ajena = crear_jornada('jornada-sug-ajena')
        self.momento = crear_momento_con_respuesta(self.jornada)

    def test_responde_200_con_lista_de_sugerencias(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post('/api/admin/analisis-sugerencias/', {
            'jornada': self.jornada.id, 'momentos': [], 'metodo': 'openai', 'enfoque': 'mixto',
            'contexto': '', 'instrucciones': '',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data, {'sugerencias': []})

    def test_metodo_invalido_da_400(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post('/api/admin/analisis-sugerencias/', {
            'jornada': self.jornada.id, 'metodo': 'no-existe',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_dependencia_no_puede_pedir_sugerencias_de_jornada_ajena(self):
        self.client.force_authenticate(user=self.dependencia)
        resp = self.client.post('/api/admin/analisis-sugerencias/', {
            'jornada': self.jornada_ajena.id, 'metodo': 'bertopic',
        }, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_momento_de_otra_jornada_da_400(self):
        self.client.force_authenticate(user=self.admin)
        momento_ajeno = crear_momento_con_respuesta(self.jornada_ajena)
        resp = self.client.post('/api/admin/analisis-sugerencias/', {
            'jornada': self.jornada.id, 'momentos': [momento_ajeno.id], 'metodo': 'bertopic',
        }, format='json')
        self.assertEqual(resp.status_code, 400)


class AnalisisUnificadoViewTests(APITestCase):
    """HU-57 §4: `GET /api/admin/analisis/` une Reporte + AnalisisMomentoIA + AnalisisJornadaIA de
    una jornada en una sola lista."""
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dependencia = crear_dependencia('dependencia')
        self.jornada = crear_jornada('jornada-unif', propietario=self.dependencia)
        self.jornada_ajena = crear_jornada('jornada-unif-ajena')
        self.momento = crear_momento_con_respuesta(self.jornada)

        self.reporte = Reporte.objects.create(
            jornada=self.jornada, alcance=Reporte.ALCANCE_JORNADA, estado=Reporte.ESTADO_COMPLETO,
        )
        self.analisis_momento = AnalisisMomentoIA.objects.create(
            momento=self.momento, estado=AnalisisMomentoIA.ESTADO_PROCESANDO,
        )
        self.analisis_jornada = AnalisisJornadaIA.objects.create(
            jornada=self.jornada, estado=AnalisisJornadaIA.ESTADO_COMPLETO,
        )
        # De otra jornada — no debe aparecer al filtrar por `self.jornada`.
        Reporte.objects.create(jornada=self.jornada_ajena, alcance=Reporte.ALCANCE_JORNADA)

    def test_sin_filtro_da_400(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/admin/analisis/')
        self.assertEqual(resp.status_code, 400)

    def test_lista_los_tres_tipos_de_la_jornada(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(f'/api/admin/analisis/?jornada={self.jornada.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 3)
        tipos = {item['tipo'] for item in resp.data}
        self.assertEqual(tipos, {'reporte', 'analisis_momento', 'analisis_jornada'})
        por_tipo = {item['tipo']: item for item in resp.data}
        self.assertEqual(por_tipo['reporte']['metodo'], 'bertopic')
        self.assertEqual(por_tipo['analisis_momento']['metodo'], 'openai')
        self.assertEqual(por_tipo['analisis_momento']['momento_titulo'], self.momento.titulo)
        self.assertEqual(por_tipo['analisis_momento']['alcance'], 'momento')
        self.assertIsNone(por_tipo['analisis_jornada']['momento'])

    def test_filtro_por_momento_excluye_reporte_y_analisis_de_jornada_no_ligados_a_el(self):
        # `self.reporte` es de alcance JORNADA (sin momentos en su M2M) — filtrar por momento no
        # debe traerlo, solo lo que de verdad está ligado a ESE momento.
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(f'/api/admin/analisis/?momento={self.momento.id}')
        self.assertEqual(resp.status_code, 200)
        tipos = {item['tipo'] for item in resp.data}
        self.assertEqual(tipos, {'analisis_momento'})

    def test_filtro_por_momento_incluye_reporte_ligado_a_ese_momento(self):
        self.client.force_authenticate(user=self.admin)
        reporte_momento = Reporte.objects.create(jornada=self.jornada, alcance=Reporte.ALCANCE_MOMENTO)
        reporte_momento.momentos.set([self.momento])
        resp = self.client.get(f'/api/admin/analisis/?momento={self.momento.id}')
        self.assertEqual(resp.status_code, 200)
        tipos = {item['tipo'] for item in resp.data}
        self.assertEqual(tipos, {'reporte', 'analisis_momento'})

    def test_dependencia_solo_ve_su_jornada(self):
        self.client.force_authenticate(user=self.dependencia)
        resp = self.client.get(f'/api/admin/analisis/?jornada={self.jornada_ajena.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, [])
