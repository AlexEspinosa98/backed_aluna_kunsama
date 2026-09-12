import datetime

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from jornadas.models import Jornada
from participantes.models import Participante

from .models import (
    AplicacionInstrumento, ColumnaMatrizInstrumento, FilaMatrizInstrumento, Instrumento,
    PreguntaInstrumento, PreregistroInstrumento, SeccionInstrumento,
)

Usuario = get_user_model()


def crear_admin(username='admin'):
    return Usuario.objects.create_user(username=username, password='pass12345', is_staff=True)


def crear_preregistrado(username='docente', password='clave12345'):
    return Usuario.objects.create_user(username=username, password=password, is_staff=False)


class BaseInstrumentoTestCase(APITestCase):
    def setUp(self):
        self.admin = crear_admin()
        self.instrumento = Instrumento.objects.create(nombre='Reflexión lectura y escritura')
        self.instrumento.encargados.add(self.admin)

        self.seccion_contenido = SeccionInstrumento.objects.create(
            instrumento=self.instrumento, orden=1, titulo='Intro',
            tipo=SeccionInstrumento.TIPO_CONTENIDO, contenido='Texto narrativo.',
        )
        self.seccion_preguntas = SeccionInstrumento.objects.create(
            instrumento=self.instrumento, orden=2, titulo='Preguntas',
            tipo=SeccionInstrumento.TIPO_PREGUNTAS,
        )
        self.pregunta_abierta = PreguntaInstrumento.objects.create(
            seccion=self.seccion_preguntas, tipo=PreguntaInstrumento.TIPO_ABIERTA,
            texto='¿Qué opinas?', orden=1, obligatoria=True,
        )
        self.pregunta_matriz = PreguntaInstrumento.objects.create(
            seccion=self.seccion_preguntas, tipo=PreguntaInstrumento.TIPO_MATRIZ,
            texto='Compare', orden=2, obligatoria=True,
        )
        self.fila = FilaMatrizInstrumento.objects.create(pregunta=self.pregunta_matriz, texto='Claridad', orden=1)
        self.columna = ColumnaMatrizInstrumento.objects.create(
            pregunta=self.pregunta_matriz, texto='Original', orden=1
        )

        self.preregistrado = crear_preregistrado()
        self.preregistro = PreregistroInstrumento.objects.create(
            instrumento=self.instrumento, usuario=self.preregistrado, creado_por=self.admin,
        )

    def respuestas_validas(self):
        return {
            'respuestas': [
                {'pregunta': self.pregunta_abierta.id, 'texto_libre': 'Mi reflexión.'},
                {
                    'pregunta': self.pregunta_matriz.id, 'fila': self.fila.id,
                    'columna': self.columna.id, 'texto_libre': 'Celda diligenciada.',
                },
            ]
        }


class LoginPreregistradoTests(BaseInstrumentoTestCase):
    def test_login_usa_el_mismo_obtain_auth_token_que_admin(self):
        resp = self.client.post(
            '/api/instrumentos/login/', {'username': 'docente', 'password': 'clave12345'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('token', resp.data)
        self.assertEqual(Token.objects.get(user=self.preregistrado).key, resp.data['token'])

    def test_preregistrado_no_es_staff_y_no_puede_entrar_a_admin(self):
        token = Token.objects.create(user=self.preregistrado)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        resp = self.client.get('/api/admin/instrumentos/')
        self.assertEqual(resp.status_code, 403)


class ParticipanteNoRevientaContraInstrumentosTests(BaseInstrumentoTestCase):
    """Mismo cuidado que ya existe para Participante contra /api/admin/**: un token de Participante
    no debe causar un 500 al pegarle a los endpoints de instrumentos."""

    def test_token_de_participante_no_revienta_el_listado(self):
        jornada = Jornada.objects.create(
            slug='jornada-x', nombre='Jornada X',
            fecha_inicio=datetime.date(2026, 1, 1), fecha_fin=datetime.date(2026, 1, 2),
        )
        participante = Participante.objects.create(
            jornada=jornada, correo_institucional='p@uni.edu.co', nombre='Ana', apellido='Ruiz', rol='estudiante',
        )
        resp = self.client.get(
            '/api/instrumentos/', HTTP_AUTHORIZATION=f'Participant {participante.token}',
        )
        self.assertEqual(resp.status_code, 403)


class InstrumentoAdminScopingTests(BaseInstrumentoTestCase):
    def test_admin_puede_crear_seccion(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            '/api/admin/instrumento-secciones/',
            {'instrumento': self.instrumento.id, 'orden': 3, 'titulo': 'Nueva', 'tipo': 'contenido'},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)

    def test_no_admin_no_puede_listar_instrumentos(self):
        self.client.force_authenticate(user=self.preregistrado)
        resp = self.client.get('/api/admin/instrumentos/')
        self.assertEqual(resp.status_code, 403)


class PreregistroInstrumentoEndpointTests(BaseInstrumentoTestCase):
    """Cubre el endpoint POST /api/admin/instrumento-preregistrados/ end-to-end (no solo el ORM
    directo que usa BaseInstrumentoTestCase.setUp) — un usuario_id opcional junto a un
    unique_together (instrumento, usuario) hace que DRF exija 'usuario_id' como requerido salvo
    que se desactiven los validadores automáticos (ver get_unique_together_validators en
    PreregistroInstrumentoAdminSerializer)."""

    def test_crear_preregistro_con_usuario_nuevo(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            '/api/admin/instrumento-preregistrados/',
            {
                'instrumento': self.instrumento.id, 'username': 'nuevo_docente',
                'password': 'ClaveSegura123', 'email': 'nuevo@uni.edu',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(Usuario.objects.filter(username='nuevo_docente', is_staff=False).exists())

    def test_crear_preregistro_con_usuario_existente(self):
        otro = crear_preregistrado(username='ya_existe')
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            '/api/admin/instrumento-preregistrados/',
            {'instrumento': self.instrumento.id, 'usuario_id': otro.id},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_no_permite_preregistrar_dos_veces_al_mismo_usuario(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            '/api/admin/instrumento-preregistrados/',
            {'instrumento': self.instrumento.id, 'usuario_id': self.preregistrado.id},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)


class InstrumentoDetalleYRespuestasTests(BaseInstrumentoTestCase):
    def test_no_preregistrado_no_puede_ver_el_instrumento(self):
        otro = crear_preregistrado(username='otro')
        self.client.force_authenticate(user=otro)
        resp = self.client.get(f'/api/instrumentos/{self.instrumento.slug}/')
        self.assertEqual(resp.status_code, 403)

    def test_preregistrado_ve_el_instrumento_con_mi_aplicacion_nula(self):
        self.client.force_authenticate(user=self.preregistrado)
        resp = self.client.get(f'/api/instrumentos/{self.instrumento.slug}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data['mi_aplicacion'])
        self.assertEqual(len(resp.data['secciones']), 2)

    def test_enviar_respuestas_incompletas_falla(self):
        self.client.force_authenticate(user=self.preregistrado)
        resp = self.client.post(
            f'/api/instrumentos/{self.instrumento.slug}/respuestas/',
            {'respuestas': [{'pregunta': self.pregunta_abierta.id, 'texto_libre': 'Solo esta.'}]},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_flujo_completo_envio_revision_reenvio(self):
        self.client.force_authenticate(user=self.preregistrado)
        resp = self.client.post(
            f'/api/instrumentos/{self.instrumento.slug}/respuestas/', self.respuestas_validas(), format='json',
        )
        self.assertEqual(resp.status_code, 200)
        aplicacion = AplicacionInstrumento.objects.get(preregistro=self.preregistro)
        self.assertEqual(aplicacion.estado_visible, 'pendiente')
        self.assertIsNotNone(aplicacion.enviado_en)

        # El encargado rechaza.
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f'/api/admin/instrumento-aplicaciones/{aplicacion.id}/revisar/',
            {'estado': 'rechazado', 'comentario_revision': 'Falta profundidad.'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        aplicacion.refresh_from_db()
        self.assertEqual(aplicacion.estado, 'rechazado')

        # El preregistrado puede reenviar tras el rechazo, y vuelve a pendiente.
        self.client.force_authenticate(user=self.preregistrado)
        resp = self.client.post(
            f'/api/instrumentos/{self.instrumento.slug}/respuestas/', self.respuestas_validas(), format='json',
        )
        self.assertEqual(resp.status_code, 200)
        aplicacion.refresh_from_db()
        self.assertEqual(aplicacion.estado, 'pendiente')
        self.assertIsNone(aplicacion.revisado_en)

        # El encargado acepta.
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f'/api/admin/instrumento-aplicaciones/{aplicacion.id}/revisar/',
            {'estado': 'aceptado'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)

        # Ya no se puede reenviar una aplicación aceptada.
        self.client.force_authenticate(user=self.preregistrado)
        resp = self.client.post(
            f'/api/instrumentos/{self.instrumento.slug}/respuestas/', self.respuestas_validas(), format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_dashboard_cuenta_estados(self):
        self.client.force_authenticate(user=self.preregistrado)
        self.client.post(
            f'/api/instrumentos/{self.instrumento.slug}/respuestas/', self.respuestas_validas(), format='json',
        )
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(f'/api/admin/instrumentos/{self.instrumento.slug}/dashboard/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['total_preregistrados'], 1)
        self.assertEqual(resp.data['conteos']['pendiente'], 1)

    def test_descarga_docx_solo_tras_enviar(self):
        self.client.force_authenticate(user=self.preregistrado)
        resp = self.client.get(f'/api/instrumentos/{self.instrumento.slug}/descargar/')
        self.assertEqual(resp.status_code, 404)

        self.client.post(
            f'/api/instrumentos/{self.instrumento.slug}/respuestas/', self.respuestas_validas(), format='json',
        )
        resp = self.client.get(f'/api/instrumentos/{self.instrumento.slug}/descargar/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp['Content-Type'],
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
