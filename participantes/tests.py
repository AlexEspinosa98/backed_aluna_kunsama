import datetime

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from jornadas.models import Jornada, Momento, OpcionPregunta, Pregunta

from .models import Participante, Respuesta


class BaseJornadaTestCase(APITestCase):
    def setUp(self):
        self.jornada = Jornada.objects.create(
            slug='jornada-2026',
            nombre='Jornada 2026',
            descripcion='Descripción',
            fecha_inicio=datetime.date(2026, 9, 1),
            fecha_fin=datetime.date(2026, 9, 2),
        )
        self.momento_individual = Momento.objects.create(
            jornada=self.jornada, orden=1, titulo='Bienvenida', contexto='Contexto',
            tipo=Momento.TIPO_INDIVIDUAL,
        )
        self.pregunta_abierta = Pregunta.objects.create(
            momento=self.momento_individual, tipo=Pregunta.TIPO_ABIERTA,
            texto='¿Cómo te sientes?', orden=1, obligatoria=True,
        )
        self.pregunta_unica = Pregunta.objects.create(
            momento=self.momento_individual, tipo=Pregunta.TIPO_UNICA,
            texto='¿Color favorito?', orden=2, obligatoria=True,
        )
        self.opcion_a = OpcionPregunta.objects.create(pregunta=self.pregunta_unica, texto='Rojo', orden=1)
        self.opcion_b = OpcionPregunta.objects.create(pregunta=self.pregunta_unica, texto='Azul', orden=2)

        self.momento_mesa = Momento.objects.create(
            jornada=self.jornada, orden=2, titulo='Discusión grupal', contexto='Contexto mesa',
            tipo=Momento.TIPO_MESA,
        )
        self.pregunta_mesa = Pregunta.objects.create(
            momento=self.momento_mesa, tipo=Pregunta.TIPO_MULTIPLE,
            texto='¿Qué temas discutieron?', orden=1, obligatoria=True,
        )
        self.opcion_mesa_a = OpcionPregunta.objects.create(pregunta=self.pregunta_mesa, texto='Tema A', orden=1)
        self.opcion_mesa_b = OpcionPregunta.objects.create(pregunta=self.pregunta_mesa, texto='Tema B', orden=2)

    def registrar_participante(self, correo='persona@uni.edu.co', **extra):
        datos = {
            'correo_institucional': correo, 'nombre': 'Ana', 'apellido': 'Pérez',
            'telefono': '3000000000', 'rol': 'estudiante',
        }
        datos.update(extra)
        resp = self.client.post(
            f'/api/jornadas/{self.jornada.slug}/registro/', datos, format='json',
        )
        return resp

    def auth_header(self, token):
        return {'HTTP_AUTHORIZATION': f'Participant {token}'}


class RegistroTests(BaseJornadaTestCase):
    def test_registro_crea_participante_y_token(self):
        resp = self.registrar_participante()
        self.assertEqual(resp.status_code, 201)
        self.assertIn('token', resp.data)
        self.assertEqual(Participante.objects.count(), 1)
        self.assertEqual(Participante.objects.first().slug, 'ana-perez')

    def test_registro_duplicado_mismo_correo_falla(self):
        self.registrar_participante()
        resp = self.registrar_participante()
        self.assertEqual(resp.status_code, 400)


class MomentosTests(BaseJornadaTestCase):
    def setUp(self):
        super().setUp()
        self.token = self.registrar_participante().data['token']

    def test_listar_momentos_requiere_token(self):
        resp = self.client.get(f'/api/jornadas/{self.jornada.slug}/momentos/')
        self.assertEqual(resp.status_code, 401)

    def test_listar_momentos_con_token(self):
        resp = self.client.get(
            f'/api/jornadas/{self.jornada.slug}/momentos/', **self.auth_header(self.token)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 2)

    def test_token_de_otra_jornada_es_rechazado(self):
        otra_jornada = Jornada.objects.create(
            slug='otra-jornada', nombre='Otra', fecha_inicio=datetime.date(2026, 1, 1),
            fecha_fin=datetime.date(2026, 1, 2),
        )
        resp = self.client.get(
            f'/api/jornadas/{otra_jornada.slug}/momentos/', **self.auth_header(self.token)
        )
        self.assertEqual(resp.status_code, 403)

    def test_detalle_momento_incluye_preguntas_y_opciones(self):
        resp = self.client.get(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_individual.id}/',
            **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['preguntas']), 2)


class RespuestasIndividualesTests(BaseJornadaTestCase):
    def setUp(self):
        super().setUp()
        self.token = self.registrar_participante().data['token']

    def _payload(self, texto='Muy bien', opcion_id=None):
        return {
            'respuestas': [
                {'pregunta_id': self.pregunta_abierta.id, 'texto_libre': texto},
                {'pregunta_id': self.pregunta_unica.id, 'opcion_ids': [opcion_id or self.opcion_a.id]},
            ]
        }

    def test_enviar_respuestas_individuales(self):
        resp = self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_individual.id}/respuestas/',
            self._payload(),
            format='json',
            **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Respuesta.objects.count(), 2)
        respuesta_unica = Respuesta.objects.get(pregunta=self.pregunta_unica)
        self.assertEqual(list(respuesta_unica.opciones.all()), [self.opcion_a])

    def test_reenviar_respuesta_actualiza_no_duplica(self):
        self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_individual.id}/respuestas/',
            self._payload(texto='Primero'),
            format='json',
            **self.auth_header(self.token),
        )
        self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_individual.id}/respuestas/',
            self._payload(texto='Segundo', opcion_id=self.opcion_b.id),
            format='json',
            **self.auth_header(self.token),
        )
        self.assertEqual(Respuesta.objects.count(), 2)
        respuesta_abierta = Respuesta.objects.get(pregunta=self.pregunta_abierta)
        self.assertEqual(respuesta_abierta.texto_libre, 'Segundo')

    def test_pregunta_obligatoria_faltante_falla(self):
        resp = self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_individual.id}/respuestas/',
            {'respuestas': [{'pregunta_id': self.pregunta_abierta.id, 'texto_libre': 'Bien'}]},
            format='json',
            **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 400)


class RespuestasPorMesaTests(BaseJornadaTestCase):
    def setUp(self):
        super().setUp()
        self.token_1 = self.registrar_participante('uno@uni.edu.co').data['token']
        self.token_2 = self.registrar_participante('dos@uni.edu.co').data['token']

    def _payload(self, mesa='Mesa 1', opciones=None):
        return {
            'mesa': mesa,
            'respuestas': [
                {'pregunta_id': self.pregunta_mesa.id, 'opcion_ids': opciones or [self.opcion_mesa_a.id]},
            ],
        }

    def test_respuesta_por_mesa_requiere_mesa(self):
        resp = self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_mesa.id}/respuestas/',
            {'respuestas': [{'pregunta_id': self.pregunta_mesa.id, 'opcion_ids': [self.opcion_mesa_a.id]}]},
            format='json',
            **self.auth_header(self.token_1),
        )
        self.assertEqual(resp.status_code, 400)

    def test_dos_participantes_misma_mesa_comparten_respuesta(self):
        self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_mesa.id}/respuestas/',
            self._payload(opciones=[self.opcion_mesa_a.id]),
            format='json',
            **self.auth_header(self.token_1),
        )
        self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_mesa.id}/respuestas/',
            self._payload(opciones=[self.opcion_mesa_a.id, self.opcion_mesa_b.id]),
            format='json',
            **self.auth_header(self.token_2),
        )
        self.assertEqual(Respuesta.objects.filter(pregunta=self.pregunta_mesa).count(), 1)
        respuesta = Respuesta.objects.get(pregunta=self.pregunta_mesa)
        self.assertEqual(respuesta.opciones.count(), 2)
        self.assertEqual(respuesta.registrado_por.token.hex, self.token_2.replace('-', ''))


class PreguntaRestringidaPorMesaTests(BaseJornadaTestCase):
    def setUp(self):
        super().setUp()
        self.pregunta_mesa.mesas_permitidas = [1]
        self.pregunta_mesa.save(update_fields=['mesas_permitidas'])
        self.token_mesa_1 = self.registrar_participante('vocero1@uni.edu.co', mesa=1, es_vocero=True).data['token']
        self.token_mesa_2 = self.registrar_participante('vocero2@uni.edu.co', mesa=2, es_vocero=True).data['token']

    def test_pregunta_no_aparece_para_mesa_no_permitida(self):
        resp = self.client.get(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_mesa.id}/',
            **self.auth_header(self.token_mesa_2),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['preguntas'], [])

    def test_pregunta_si_aparece_para_mesa_permitida(self):
        resp = self.client.get(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_mesa.id}/',
            **self.auth_header(self.token_mesa_1),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([p['id'] for p in resp.data['preguntas']], [self.pregunta_mesa.id])

    def test_mesa_no_permitida_no_puede_responder(self):
        resp = self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_mesa.id}/respuestas/',
            {'respuestas': [{'pregunta_id': self.pregunta_mesa.id, 'opcion_ids': [self.opcion_mesa_a.id]}]},
            format='json',
            **self.auth_header(self.token_mesa_2),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Respuesta.objects.count(), 0)

    def test_mesa_permitida_si_puede_responder(self):
        resp = self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_mesa.id}/respuestas/',
            {'respuestas': [{'pregunta_id': self.pregunta_mesa.id, 'opcion_ids': [self.opcion_mesa_a.id]}]},
            format='json',
            **self.auth_header(self.token_mesa_1),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Respuesta.objects.count(), 1)


class AdminApiTests(BaseJornadaTestCase):
    def test_crud_jornada_requiere_staff(self):
        resp = self.client.post('/api/admin/jornadas/', {
            'slug': 'nueva', 'nombre': 'Nueva', 'fecha_inicio': '2026-10-01', 'fecha_fin': '2026-10-02',
        }, format='json')
        self.assertEqual(resp.status_code, 401)

        User = get_user_model()
        staff = User.objects.create_user(username='admin', password='pass12345', is_staff=True)
        self.client.force_authenticate(user=staff)
        resp = self.client.post('/api/admin/jornadas/', {
            'slug': 'nueva', 'nombre': 'Nueva', 'fecha_inicio': '2026-10-01', 'fecha_fin': '2026-10-02',
        }, format='json')
        self.assertEqual(resp.status_code, 201)


class ParticipantesAdminScopingTests(BaseJornadaTestCase):
    """La jornada de BaseJornadaTestCase no tiene propietario — para probar el scoping por
    dependencia hace falta una segunda jornada que sí tenga uno."""
    def setUp(self):
        super().setUp()
        User = get_user_model()
        from jornadas.models import PerfilUsuario
        self.dependencia = User.objects.create_user(username='dep', password='pass12345', is_staff=True)
        PerfilUsuario.objects.create(user=self.dependencia, rol=PerfilUsuario.ROL_DEPENDENCIA)
        self.jornada.propietario = self.dependencia
        self.jornada.save(update_fields=['propietario'])

        self.otra_jornada = Jornada.objects.create(
            slug='otra-jornada-admin', nombre='Otra', fecha_inicio=datetime.date(2026, 1, 1),
            fecha_fin=datetime.date(2026, 1, 2),
        )
        Participante.objects.create(
            jornada=self.otra_jornada, correo_institucional='ajeno@uni.edu.co',
            nombre='Otro', apellido='Participante', rol='estudiante',
        )
        self.token = self.registrar_participante().data['token']

    def test_dependencia_solo_ve_participantes_de_su_jornada(self):
        self.client.force_authenticate(user=self.dependencia)
        resp = self.client.get('/api/admin/participantes/')
        self.assertEqual(resp.status_code, 200)
        jornadas_devueltas = {p['jornada'] for p in resp.data}
        self.assertEqual(jornadas_devueltas, {self.jornada.slug})
