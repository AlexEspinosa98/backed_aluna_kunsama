import datetime

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import Jornada, Momento, PerfilUsuario, Pregunta

Usuario = get_user_model()


def crear_jornada(slug, propietario=None):
    return Jornada.objects.create(
        slug=slug, nombre=slug, fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 2),
        propietario=propietario,
    )


def crear_dependencia(username):
    usuario = Usuario.objects.create_user(username=username, password='pass12345', is_staff=True)
    PerfilUsuario.objects.create(user=usuario, rol=PerfilUsuario.ROL_DEPENDENCIA)
    return usuario


def crear_admin_completo(username):
    # Sin fila en PerfilUsuario == admin completo, ver jornadas/scoping.py.
    return Usuario.objects.create_user(username=username, password='pass12345', is_staff=True)


class ScopingPorDependenciaTests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dependencia_a = crear_dependencia('dependencia_a')
        self.dependencia_b = crear_dependencia('dependencia_b')
        self.jornada_a = crear_jornada('jornada-a', propietario=self.dependencia_a)
        self.jornada_b = crear_jornada('jornada-b', propietario=self.dependencia_b)
        self.jornada_sin_dueno = crear_jornada('jornada-sin-dueno')

    def test_admin_completo_ve_todas_las_jornadas(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/admin/jornadas/')
        self.assertEqual(resp.status_code, 200)
        slugs = {j['slug'] for j in resp.data}
        self.assertEqual(slugs, {'jornada-a', 'jornada-b', 'jornada-sin-dueno'})

    def test_dependencia_solo_ve_sus_jornadas(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.get('/api/admin/jornadas/')
        self.assertEqual(resp.status_code, 200)
        slugs = {j['slug'] for j in resp.data}
        self.assertEqual(slugs, {'jornada-a'})

    def test_dependencia_no_puede_ver_detalle_de_jornada_ajena(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.get(f'/api/admin/jornadas/{self.jornada_b.slug}/')
        self.assertEqual(resp.status_code, 404)

    def test_dependencia_crea_jornada_y_queda_como_propietaria(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post('/api/admin/jornadas/', {
            'slug': 'jornada-nueva', 'nombre': 'Nueva',
            'fecha_inicio': '2026-10-01', 'fecha_fin': '2026-10-02',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        jornada = Jornada.objects.get(slug='jornada-nueva')
        self.assertEqual(jornada.propietario_id, self.dependencia_a.id)

    def test_dependencia_no_puede_asignarse_jornada_de_otro_al_crear(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post('/api/admin/jornadas/', {
            'slug': 'jornada-truco', 'nombre': 'Truco',
            'fecha_inicio': '2026-10-01', 'fecha_fin': '2026-10-02',
            'propietario': self.dependencia_b.id,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        jornada = Jornada.objects.get(slug='jornada-truco')
        self.assertEqual(jornada.propietario_id, self.dependencia_a.id)

    def test_dependencia_no_puede_reasignar_propietario_al_editar(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.patch(f'/api/admin/jornadas/{self.jornada_a.slug}/', {
            'propietario': self.dependencia_b.id,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.jornada_a.refresh_from_db()
        self.assertEqual(self.jornada_a.propietario_id, self.dependencia_a.id)

    def test_admin_completo_reasigna_propietario(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(f'/api/admin/jornadas/{self.jornada_a.slug}/', {
            'propietario': self.dependencia_b.id,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.jornada_a.refresh_from_db()
        self.assertEqual(self.jornada_a.propietario_id, self.dependencia_b.id)

    def test_dependencia_no_puede_crear_momento_bajo_jornada_ajena(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post('/api/admin/momentos/', {
            'jornada': self.jornada_b.id, 'orden': 1, 'titulo': 'Intento', 'tipo': Momento.TIPO_INDIVIDUAL,
        }, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_dependencia_crea_momento_en_su_propia_jornada(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post('/api/admin/momentos/', {
            'jornada': self.jornada_a.id, 'orden': 1, 'titulo': 'Bienvenida', 'tipo': Momento.TIPO_INDIVIDUAL,
        }, format='json')
        self.assertEqual(resp.status_code, 201)

    def test_dependencia_no_ve_momentos_de_jornada_ajena(self):
        momento = Momento.objects.create(
            jornada=self.jornada_b, orden=1, titulo='Bienvenida', tipo=Momento.TIPO_INDIVIDUAL,
        )
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.get('/api/admin/momentos/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(momento.id, [m['id'] for m in resp.data])

    def test_dependencia_no_puede_crear_pregunta_bajo_momento_ajeno(self):
        momento_ajeno = Momento.objects.create(
            jornada=self.jornada_b, orden=1, titulo='Bienvenida', tipo=Momento.TIPO_INDIVIDUAL,
        )
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post('/api/admin/preguntas/', {
            'momento': momento_ajeno.id, 'tipo': Pregunta.TIPO_ABIERTA, 'texto': '¿Intento?', 'orden': 1,
        }, format='json')
        self.assertEqual(resp.status_code, 403)


class UsuarioAdminViewSetTests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dependencia = crear_dependencia('dependencia_a')

    def test_admin_completo_crea_usuario_dependencia(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post('/api/admin/usuarios/', {
            'username': 'nueva_dependencia', 'password': 'Contrasena-123', 'rol': PerfilUsuario.ROL_DEPENDENCIA,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        usuario = Usuario.objects.get(username='nueva_dependencia')
        self.assertTrue(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)
        self.assertEqual(usuario.perfil.rol, PerfilUsuario.ROL_DEPENDENCIA)

    def test_admin_completo_ve_jornadas_propias_de_cada_usuario(self):
        crear_jornada('jornada-x', propietario=self.dependencia)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(f'/api/admin/usuarios/{self.dependencia.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([j['slug'] for j in resp.data['jornadas_propias']], ['jornada-x'])

    def test_dependencia_no_puede_gestionar_usuarios(self):
        self.client.force_authenticate(user=self.dependencia)
        resp = self.client.get('/api/admin/usuarios/')
        self.assertEqual(resp.status_code, 403)
