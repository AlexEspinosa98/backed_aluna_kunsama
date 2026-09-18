import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from jornadas.models import Jornada, PerfilUsuario

from .models import AnalisisJornadaIA, InfografiaJornada, PlantillaAnalisis, Reporte

Usuario = get_user_model()


def crear_jornada(slug, propietario=None):
    jornada = Jornada.objects.create(
        slug=slug, nombre=slug, fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 2),
    )
    if propietario:
        jornada.propietarios.set([propietario])
    return jornada


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
