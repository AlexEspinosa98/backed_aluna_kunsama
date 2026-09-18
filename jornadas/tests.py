import datetime

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from .models import Jornada, JornadaAsset, Momento, PerfilUsuario, Pregunta

Usuario = get_user_model()


def crear_jornada(slug, propietario=None, propietarios=None):
    jornada = Jornada.objects.create(
        slug=slug, nombre=slug, fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 2),
    )
    duenos = propietarios if propietarios is not None else ([propietario] if propietario else [])
    if duenos:
        jornada.propietarios.set(duenos)
    return jornada


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

    def test_dos_dependencias_comparten_la_misma_jornada(self):
        jornada_compartida = crear_jornada('jornada-compartida', propietarios=[self.dependencia_a, self.dependencia_b])
        for usuario in (self.dependencia_a, self.dependencia_b):
            self.client.force_authenticate(user=usuario)
            resp = self.client.get('/api/admin/jornadas/')
            self.assertEqual(resp.status_code, 200)
            self.assertIn('jornada-compartida', {j['slug'] for j in resp.data})
            resp_detalle = self.client.get(f'/api/admin/jornadas/{jornada_compartida.slug}/')
            self.assertEqual(resp_detalle.status_code, 200)

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
        self.assertEqual(list(jornada.propietarios.all()), [self.dependencia_a])

    def test_dependencia_no_puede_asignarse_jornada_de_otro_al_crear(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post('/api/admin/jornadas/', {
            'slug': 'jornada-truco', 'nombre': 'Truco',
            'fecha_inicio': '2026-10-01', 'fecha_fin': '2026-10-02',
            'propietarios': [self.dependencia_b.id],
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        jornada = Jornada.objects.get(slug='jornada-truco')
        self.assertEqual(list(jornada.propietarios.all()), [self.dependencia_a])

    def test_dependencia_no_puede_reasignar_propietario_al_editar(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.patch(f'/api/admin/jornadas/{self.jornada_a.slug}/', {
            'propietarios': [self.dependencia_b.id],
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.jornada_a.refresh_from_db()
        self.assertEqual(list(self.jornada_a.propietarios.all()), [self.dependencia_a])

    def test_admin_completo_reasigna_propietario(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(f'/api/admin/jornadas/{self.jornada_a.slug}/', {
            'propietarios': [self.dependencia_b.id],
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.jornada_a.refresh_from_db()
        self.assertEqual(list(self.jornada_a.propietarios.all()), [self.dependencia_b])

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

    def test_admin_completo_ve_jornadas_e_instrumentos_del_mismo_usuario(self):
        # Un usuario de dependencia puede estar a cargo de varias jornadas, varios instrumentos Y
        # varias sesiones de transcripción a la vez — /api/admin/usuarios/ es la vista "universal"
        # de los tres módulos.
        from instrumentos.models import Instrumento
        from transcripciones.models import SesionTranscripcion

        crear_jornada('jornada-x', propietario=self.dependencia)
        crear_jornada('jornada-y', propietario=self.dependencia)
        instrumento_a = Instrumento.objects.create(nombre='Instrumento A')
        instrumento_a.encargados.add(self.dependencia)
        instrumento_b = Instrumento.objects.create(nombre='Instrumento B')
        instrumento_b.encargados.add(self.dependencia)
        sesion_a = SesionTranscripcion.objects.create(nombre='Sesion A')
        sesion_a.encargados.add(self.dependencia)

        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(f'/api/admin/usuarios/{self.dependencia.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            sorted(j['slug'] for j in resp.data['jornadas_propias']), ['jornada-x', 'jornada-y']
        )
        self.assertEqual(
            sorted(i['slug'] for i in resp.data['instrumentos_a_cargo']),
            ['instrumento-a', 'instrumento-b'],
        )
        self.assertEqual(
            [s['slug'] for s in resp.data['transcripciones_a_cargo']], ['sesion-a'],
        )

    def test_dependencia_no_puede_gestionar_usuarios(self):
        self.client.force_authenticate(user=self.dependencia)
        resp = self.client.get('/api/admin/usuarios/')
        self.assertEqual(resp.status_code, 403)

    def test_no_permite_crear_username_duplicado_por_mayusculas(self):
        Usuario.objects.create_user(username='john', password='pass12345', is_staff=True)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post('/api/admin/usuarios/', {
            'username': 'John', 'password': 'Contrasena-123',
        }, format='json')
        self.assertEqual(resp.status_code, 400)


class LoginCaseInsensitiveTests(APITestCase):
    """Reporte real: un docente con username 'john' no podía entrar escribiendo 'John' (o
    viceversa) — Postgres compara texto exacto por defecto. Cubre tanto /api/admin/login/ como
    /api/instrumentos/login/, porque ambos pasan por el mismo AUTHENTICATION_BACKENDS de Django
    (ver config/auth_backends.py)."""

    def setUp(self):
        self.usuario = Usuario.objects.create_user(username='john', password='ClaveSegura123', is_staff=True)

    def test_login_admin_no_distingue_mayusculas_en_username(self):
        resp = self.client.post('/api/admin/login/', {'username': 'John', 'password': 'ClaveSegura123'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('token', resp.data)

    def test_login_admin_si_distingue_mayusculas_en_password(self):
        resp = self.client.post('/api/admin/login/', {'username': 'john', 'password': 'clavesegura123'})
        self.assertEqual(resp.status_code, 400)


class JornadaAssetTests(APITestCase):
    """Assets (imágenes) y system design de una jornada, usados como referencia visual al generar
    infografías (ver analitica/infografia_ia_openai.py)."""
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dependencia_a = crear_dependencia('dependencia_a')
        self.dependencia_b = crear_dependencia('dependencia_b')
        self.jornada_a = crear_jornada('jornada-a', propietario=self.dependencia_a)
        self.jornada_b = crear_jornada('jornada-b', propietario=self.dependencia_b)

    def _imagen(self, nombre='logo.png'):
        return SimpleUploadedFile(nombre, b'contenido-imagen', content_type='image/png')

    def _pdf(self, nombre='marca.pdf'):
        return SimpleUploadedFile(nombre, b'contenido-pdf', content_type='application/pdf')

    def test_admin_sube_asset_imagen(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post('/api/admin/jornada-assets/', {
            'jornada': self.jornada_a.id, 'tipo': JornadaAsset.TIPO_ASSET, 'archivo': self._imagen(),
        }, format='multipart')
        self.assertEqual(resp.status_code, 201)
        asset = JornadaAsset.objects.get(id=resp.data['id'])
        self.assertEqual(asset.jornada, self.jornada_a)
        self.assertEqual(asset.nombre_archivo_original, 'logo.png')
        self.assertEqual(asset.subido_por, self.admin)

    def test_admin_sube_system_design_como_pdf(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post('/api/admin/jornada-assets/', {
            'jornada': self.jornada_a.id, 'tipo': JornadaAsset.TIPO_SYSTEM_DESIGN, 'archivo': self._pdf(),
        }, format='multipart')
        self.assertEqual(resp.status_code, 201)

    def test_rechaza_pdf_para_tipo_asset(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post('/api/admin/jornada-assets/', {
            'jornada': self.jornada_a.id, 'tipo': JornadaAsset.TIPO_ASSET, 'archivo': self._pdf(),
        }, format='multipart')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('archivo', resp.data)

    def test_rechaza_docx_para_system_design(self):
        self.client.force_authenticate(user=self.admin)
        archivo = SimpleUploadedFile(
            'marca.docx', b'contenido',
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        resp = self.client.post('/api/admin/jornada-assets/', {
            'jornada': self.jornada_a.id, 'tipo': JornadaAsset.TIPO_SYSTEM_DESIGN, 'archivo': archivo,
        }, format='multipart')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('archivo', resp.data)

    def test_dependencia_no_puede_subir_asset_a_jornada_ajena(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post('/api/admin/jornada-assets/', {
            'jornada': self.jornada_b.id, 'tipo': JornadaAsset.TIPO_ASSET, 'archivo': self._imagen(),
        }, format='multipart')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(JornadaAsset.objects.count(), 0)

    def test_dependencia_solo_ve_assets_de_su_jornada(self):
        JornadaAsset.objects.create(jornada=self.jornada_a, archivo=self._imagen('a.png'))
        JornadaAsset.objects.create(jornada=self.jornada_b, archivo=self._imagen('b.png'))
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.get('/api/admin/jornada-assets/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]['jornada'], self.jornada_a.id)

    def test_admin_borra_asset(self):
        asset = JornadaAsset.objects.create(jornada=self.jornada_a, archivo=self._imagen())
        self.client.force_authenticate(user=self.admin)
        resp = self.client.delete(f'/api/admin/jornada-assets/{asset.id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(JornadaAsset.objects.count(), 0)
