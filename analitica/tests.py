import datetime

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from jornadas.models import Jornada, PerfilUsuario

from .models import AnalisisJornadaIA, PlantillaAnalisis, Reporte

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
