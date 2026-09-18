import datetime

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from jornadas.models import ColumnaMatrizPregunta, FilaMatrizPregunta, Jornada, Momento, OpcionPregunta, Pregunta

from .extraccion_momento_ia_openai import _limpiar_y_validar, aprobar_extraccion_momento
from .models import ExtraccionMomento, FilaListaRespuesta, Participante, Respuesta


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
    """Lo que se prueba acá es que en un momento tipo mesa la respuesta es de LA MESA, no de la
    persona: quien la manda queda en `registrado_por`, pero la fila es una sola por mesa.

    Esta clase quedó desactualizada cuando mesa/vocero pasaron a fijarse en el registro (ver
    ff4d47a): la mesa ya no viaja en el body del POST — se lee de `Participante.mesa` para que
    nadie pueda responder a nombre de otra mesa — y solo el vocero puede enviar. Los dos
    participantes de antes no eran voceros, así que recibían 403 y no se guardaba nada.
    """
    def setUp(self):
        super().setUp()
        # Los dos son de la MESA 1; solo uno puede ser vocero a la vez (_validar_vocero_unico).
        self.token_1 = self.registrar_participante(
            'uno@uni.edu.co', mesa=1, es_vocero=True,
        ).data['token']
        self.token_2 = self.registrar_participante(
            'dos@uni.edu.co', mesa=1, es_vocero=False,
        ).data['token']
        self.participante_1 = Participante.objects.get(correo_institucional='uno@uni.edu.co')
        self.participante_2 = Participante.objects.get(correo_institucional='dos@uni.edu.co')
        self.url = f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_mesa.id}/respuestas/'

    def _payload(self, opciones=None):
        # Sin clave `mesa`: el body ya no la acepta, sale de Participante.mesa (ver
        # RespuestaEnvioSerializer).
        return {
            'respuestas': [
                {'pregunta_id': self.pregunta_mesa.id, 'opcion_ids': opciones or [self.opcion_mesa_a.id]},
            ],
        }

    def _cambiar_voceria(self, nuevo_vocero):
        """Mueve la vocería de la mesa 1 de un participante al otro, como lo haría un admin con
        PATCH /api/admin/participantes/{id}/ — en dos pasos porque no puede haber dos voceros de
        la misma mesa al tiempo."""
        for participante in (self.participante_1, self.participante_2):
            if participante.es_vocero and participante != nuevo_vocero:
                participante.es_vocero = False
                participante.save(update_fields=['es_vocero'])
        nuevo_vocero.es_vocero = True
        nuevo_vocero.save(update_fields=['es_vocero'])

    def test_respuesta_por_mesa_requiere_mesa(self):
        # Vocero SIN mesa asignada: pasa el filtro de vocería y cae justo en la validación de
        # mesa, que es lo que este test quiere fijar (un 403 por no ser vocero lo dejaría pasar
        # sin probar nada de esto).
        token = self.registrar_participante(
            'sinmesa@uni.edu.co', es_vocero=True,
        ).data['token']
        resp = self.client.post(
            self.url, self._payload(), format='json', **self.auth_header(token),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('mesa', resp.data)

    def test_no_vocero_no_puede_responder_momento_de_mesa(self):
        resp = self.client.post(
            self.url, self._payload(), format='json', **self.auth_header(self.token_2),
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Respuesta.objects.filter(pregunta=self.pregunta_mesa).count(), 0)

    def test_dos_participantes_misma_mesa_comparten_respuesta(self):
        resp_1 = self.client.post(
            self.url, self._payload(opciones=[self.opcion_mesa_a.id]),
            format='json', **self.auth_header(self.token_1),
        )
        self.assertEqual(resp_1.status_code, 200)

        # La vocería cambia de persona, pero la mesa sigue siendo la 1: el segundo envío tiene
        # que ACTUALIZAR la fila de la mesa, no crear una segunda.
        self._cambiar_voceria(self.participante_2)
        resp_2 = self.client.post(
            self.url, self._payload(opciones=[self.opcion_mesa_a.id, self.opcion_mesa_b.id]),
            format='json', **self.auth_header(self.token_2),
        )
        self.assertEqual(resp_2.status_code, 200)

        self.assertEqual(Respuesta.objects.filter(pregunta=self.pregunta_mesa).count(), 1)
        respuesta = Respuesta.objects.get(pregunta=self.pregunta_mesa)
        self.assertEqual(respuesta.mesa, 1)
        self.assertIsNone(respuesta.participante)
        self.assertEqual(respuesta.opciones.count(), 2)
        self.assertEqual(respuesta.registrado_por.token.hex, self.token_2.replace('-', ''))

    def test_cualquiera_de_la_mesa_lee_lo_que_respondio_el_vocero(self):
        self.client.post(
            self.url, self._payload(opciones=[self.opcion_mesa_a.id]),
            format='json', **self.auth_header(self.token_1),
        )
        # El no vocero no puede escribir, pero sí ver lo que su mesa ya respondió.
        resp = self.client.get(self.url, **self.auth_header(self.token_2))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]['pregunta'], self.pregunta_mesa.id)


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


class MomentoRestringidoPorMesaTests(BaseJornadaTestCase):
    """Café del Mundo: cada momento tipo mesa puede restringirse a ciertas mesas completas (no
    solo preguntas sueltas dentro de un momento compartido)."""
    def setUp(self):
        super().setUp()
        self.momento_mesa.mesas_permitidas = [1]
        self.momento_mesa.save(update_fields=['mesas_permitidas'])
        self.token_mesa_1 = self.registrar_participante('vocero1b@uni.edu.co', mesa=1, es_vocero=True).data['token']
        self.token_mesa_2 = self.registrar_participante('vocero2b@uni.edu.co', mesa=2, es_vocero=True).data['token']

    def test_momento_no_aparece_en_indice_para_mesa_no_permitida(self):
        resp = self.client.get(
            f'/api/jornadas/{self.jornada.slug}/momentos/', **self.auth_header(self.token_mesa_2)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.momento_mesa.id, [m['id'] for m in resp.data])

    def test_momento_si_aparece_en_indice_para_mesa_permitida(self):
        resp = self.client.get(
            f'/api/jornadas/{self.jornada.slug}/momentos/', **self.auth_header(self.token_mesa_1)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.momento_mesa.id, [m['id'] for m in resp.data])

    def test_detalle_de_momento_da_404_para_mesa_no_permitida(self):
        resp = self.client.get(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_mesa.id}/',
            **self.auth_header(self.token_mesa_2),
        )
        self.assertEqual(resp.status_code, 404)

    def test_detalle_de_momento_si_funciona_para_mesa_permitida(self):
        resp = self.client.get(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_mesa.id}/',
            **self.auth_header(self.token_mesa_1),
        )
        self.assertEqual(resp.status_code, 200)

    def test_mesa_no_permitida_no_puede_responder_el_momento(self):
        resp = self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_mesa.id}/respuestas/',
            {'respuestas': [{'pregunta_id': self.pregunta_mesa.id, 'opcion_ids': [self.opcion_mesa_a.id]}]},
            format='json',
            **self.auth_header(self.token_mesa_2),
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Respuesta.objects.count(), 0)

    def test_mesa_permitida_si_puede_responder_el_momento(self):
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
        self.jornada.propietarios.set([self.dependencia])

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


class LimpiarYValidarExtraccionTests(BaseJornadaTestCase):
    """_limpiar_y_validar es lo que la IA usa para filtrar su transcripción antes de dejarla en
    ExtraccionMomento.resultado — no depende de OpenAI, se prueba directo con datos "crudos"."""
    def test_conserva_respuesta_abierta_valida(self):
        crudo = {'respuestas': [{'pregunta': self.pregunta_abierta.id, 'texto_libre': 'Bien.', 'opcion_ids': []}]}
        limpio, omitidas = _limpiar_y_validar(crudo, self.momento_individual)
        self.assertEqual(limpio['respuestas'], [{
            'pregunta': self.pregunta_abierta.id, 'texto_libre': 'Bien.', 'opcion_ids': [],
            'fila_id': None, 'columna_id': None,
        }])
        self.assertEqual(omitidas, [])

    def test_conserva_opcion_valida_y_descarta_opcion_ajena(self):
        otra_pregunta = Pregunta.objects.create(
            momento=self.momento_individual, tipo=Pregunta.TIPO_ABIERTA, texto='Otra', orden=3,
        )
        opcion_ajena = OpcionPregunta.objects.create(pregunta=otra_pregunta, texto='No es de esta pregunta', orden=1)
        crudo = {'respuestas': [{
            'pregunta': self.pregunta_unica.id, 'texto_libre': '',
            'opcion_ids': [self.opcion_a.id, opcion_ajena.id],
        }]}
        limpio, omitidas = _limpiar_y_validar(crudo, self.momento_individual)
        self.assertEqual(limpio['respuestas'], [{
            'pregunta': self.pregunta_unica.id, 'texto_libre': '', 'opcion_ids': [self.opcion_a.id],
            'fila_id': None, 'columna_id': None,
        }])
        self.assertEqual(omitidas, [])

    def test_omite_pregunta_unica_con_mas_de_una_opcion(self):
        crudo = {'respuestas': [{
            'pregunta': self.pregunta_unica.id, 'texto_libre': '',
            'opcion_ids': [self.opcion_a.id, self.opcion_b.id],
        }]}
        _limpio, omitidas = _limpiar_y_validar(crudo, self.momento_individual)
        self.assertEqual(omitidas, [self.pregunta_unica.id])

    def test_omite_pregunta_que_no_pertenece_al_momento(self):
        crudo = {'respuestas': [{'pregunta': 999999, 'texto_libre': 'x', 'opcion_ids': []}]}
        _limpio, omitidas = _limpiar_y_validar(crudo, self.momento_individual)
        self.assertEqual(omitidas, [999999])


class AprobarExtraccionMomentoTests(BaseJornadaTestCase):
    def setUp(self):
        super().setUp()
        self.participante = Participante.objects.create(
            jornada=self.jornada, correo_institucional='depto@uni.edu.co',
            nombre='Depto', apellido='Sistemas', rol='jefe',
        )
        self.admin = get_user_model().objects.create_user(username='admin_test', password='pass12345', is_staff=True)
        self.extraccion = ExtraccionMomento.objects.create(
            momento=self.momento_individual, participante=self.participante,
            archivo=SimpleUploadedFile('a.pdf', b'contenido', content_type='application/pdf'),
            estado=ExtraccionMomento.ESTADO_COMPLETO,
            resultado={'respuestas': [
                {'pregunta': self.pregunta_abierta.id, 'texto_libre': 'Todo bien.', 'opcion_ids': []},
                {'pregunta': self.pregunta_unica.id, 'texto_libre': '', 'opcion_ids': [self.opcion_a.id]},
            ]},
        )

    def test_aprobar_escribe_respuestas_reales_del_participante(self):
        guardadas = aprobar_extraccion_momento(self.extraccion, self.admin)
        self.assertEqual(len(guardadas), 2)
        self.assertEqual(
            Respuesta.objects.get(pregunta=self.pregunta_abierta, participante=self.participante).texto_libre,
            'Todo bien.',
        )
        opciones = list(
            Respuesta.objects.get(pregunta=self.pregunta_unica, participante=self.participante).opciones.all()
        )
        self.assertEqual(opciones, [self.opcion_a])
        self.extraccion.refresh_from_db()
        self.assertIsNotNone(self.extraccion.aprobado_en)
        self.assertEqual(self.extraccion.aprobado_por, self.admin)

    def test_endpoint_no_deja_aprobar_dos_veces(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(f'/api/admin/momento-extracciones/{self.extraccion.id}/aprobar/')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(f'/api/admin/momento-extracciones/{self.extraccion.id}/aprobar/')
        self.assertEqual(resp.status_code, 403)

    def test_endpoint_no_deja_aprobar_extraccion_sin_completar(self):
        self.extraccion.estado = ExtraccionMomento.ESTADO_PROCESANDO
        self.extraccion.save(update_fields=['estado'])
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(f'/api/admin/momento-extracciones/{self.extraccion.id}/aprobar/')
        self.assertEqual(resp.status_code, 400)


class ExtraccionMomentoScopingTests(BaseJornadaTestCase):
    def setUp(self):
        super().setUp()
        from jornadas.models import PerfilUsuario
        User = get_user_model()

        self.admin = User.objects.create_user(username='admin_scope', password='pass12345', is_staff=True)
        self.dependencia = User.objects.create_user(username='dep_scope', password='pass12345', is_staff=True)
        PerfilUsuario.objects.create(user=self.dependencia, rol=PerfilUsuario.ROL_DEPENDENCIA)
        self.jornada.propietarios.set([self.dependencia])

        self.otra_jornada = Jornada.objects.create(
            slug='otra-jornada-extraccion', nombre='Otra', fecha_inicio=datetime.date(2026, 1, 1),
            fecha_fin=datetime.date(2026, 1, 2),
        )
        self.otro_momento = Momento.objects.create(
            jornada=self.otra_jornada, orden=1, titulo='Otro momento', tipo=Momento.TIPO_INDIVIDUAL,
        )
        self.otro_participante = Participante.objects.create(
            jornada=self.otra_jornada, correo_institucional='otro@uni.edu.co',
            nombre='Otro', apellido='Depto', rol='jefe',
        )

        self.participante = Participante.objects.create(
            jornada=self.jornada, correo_institucional='propio@uni.edu.co',
            nombre='Propio', apellido='Depto', rol='jefe',
        )
        self.extraccion_propia = ExtraccionMomento.objects.create(
            momento=self.momento_individual, participante=self.participante,
            archivo=SimpleUploadedFile('a.pdf', b'x', content_type='application/pdf'),
        )
        self.extraccion_ajena = ExtraccionMomento.objects.create(
            momento=self.otro_momento, participante=self.otro_participante,
            archivo=SimpleUploadedFile('b.pdf', b'x', content_type='application/pdf'),
        )

    def test_dependencia_solo_ve_extracciones_de_su_jornada(self):
        self.client.force_authenticate(user=self.dependencia)
        resp = self.client.get('/api/admin/momento-extracciones/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([e['id'] for e in resp.data], [self.extraccion_propia.id])

    def test_admin_completo_ve_todas_las_extracciones(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/admin/momento-extracciones/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            {e['id'] for e in resp.data}, {self.extraccion_propia.id, self.extraccion_ajena.id}
        )

    def test_dependencia_no_puede_subir_documento_para_momento_ajeno(self):
        self.client.force_authenticate(user=self.dependencia)
        archivo = SimpleUploadedFile('c.pdf', b'x', content_type='application/pdf')
        resp = self.client.post('/api/admin/momento-extracciones/', {
            'momento': self.otro_momento.id, 'participante_id': self.otro_participante.id, 'archivo': archivo,
        }, format='multipart')
        self.assertEqual(resp.status_code, 403)

    def test_rechaza_formato_no_soportado(self):
        self.client.force_authenticate(user=self.admin)
        archivo = SimpleUploadedFile('c.txt', b'x', content_type='text/plain')
        resp = self.client.post('/api/admin/momento-extracciones/', {
            'momento': self.momento_individual.id, 'participante_id': self.participante.id, 'archivo': archivo,
        }, format='multipart')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('archivo', resp.data)


class RespuestaMatrizTests(BaseJornadaTestCase):
    """Pregunta.tipo == matriz sobre el momento individual — una celda (fila×columna) por
    entrada, todas con el mismo pregunta_id. Mismo endpoint que las demás respuestas
    (RespuestasMomentoView), sin nada nuevo del lado del cliente salvo fila_id/columna_id."""
    def setUp(self):
        super().setUp()
        self.pregunta_matriz_2 = Pregunta.objects.create(
            momento=self.momento_individual, tipo=Pregunta.TIPO_MATRIZ,
            texto='Responsabilidades', orden=3, obligatoria=True,
        )
        self.fila_1 = FilaMatrizPregunta.objects.create(pregunta=self.pregunta_matriz_2, texto='Proceso A', orden=1)
        self.fila_2 = FilaMatrizPregunta.objects.create(pregunta=self.pregunta_matriz_2, texto='Proceso B', orden=2)
        self.col_1 = ColumnaMatrizPregunta.objects.create(pregunta=self.pregunta_matriz_2, texto='Quién', orden=1)
        self.col_2 = ColumnaMatrizPregunta.objects.create(pregunta=self.pregunta_matriz_2, texto='Cuándo', orden=2)

        self.token = self.registrar_participante().data['token']

    def _respuestas_base(self, extra=None):
        base = [
            {'pregunta_id': self.pregunta_abierta.id, 'texto_libre': 'Mi reflexión.'},
            {'pregunta_id': self.pregunta_unica.id, 'opcion_ids': [self.opcion_a.id]},
        ]
        return {'respuestas': base + (extra or [])}

    def test_guarda_una_respuesta_por_celda(self):
        resp = self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_individual.id}/respuestas/',
            self._respuestas_base([
                {'pregunta_id': self.pregunta_matriz_2.id, 'fila_id': self.fila_1.id, 'columna_id': self.col_1.id, 'texto_libre': 'Juan'},
                {'pregunta_id': self.pregunta_matriz_2.id, 'fila_id': self.fila_1.id, 'columna_id': self.col_2.id, 'texto_libre': 'Hoy'},
                {'pregunta_id': self.pregunta_matriz_2.id, 'fila_id': self.fila_2.id, 'columna_id': self.col_1.id, 'texto_libre': 'Ana'},
                {'pregunta_id': self.pregunta_matriz_2.id, 'fila_id': self.fila_2.id, 'columna_id': self.col_2.id, 'texto_libre': 'Mañana'},
            ]),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Respuesta.objects.filter(pregunta=self.pregunta_matriz_2).count(), 4)
        celda = Respuesta.objects.get(pregunta=self.pregunta_matriz_2, fila=self.fila_1, columna=self.col_1)
        self.assertEqual(celda.texto_libre, 'Juan')

    def test_matriz_obligatoria_exige_todas_las_celdas(self):
        resp = self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_individual.id}/respuestas/',
            self._respuestas_base([
                {'pregunta_id': self.pregunta_matriz_2.id, 'fila_id': self.fila_1.id, 'columna_id': self.col_1.id, 'texto_libre': 'Juan'},
            ]),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('faltantes', resp.data)

    def test_rechaza_celda_sin_fila_o_columna(self):
        resp = self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_individual.id}/respuestas/',
            self._respuestas_base([
                {'pregunta_id': self.pregunta_matriz_2.id, 'fila_id': self.fila_1.id, 'texto_libre': 'Juan'},
                {'pregunta_id': self.pregunta_matriz_2.id, 'fila_id': self.fila_1.id, 'columna_id': self.col_2.id, 'texto_libre': 'x'},
                {'pregunta_id': self.pregunta_matriz_2.id, 'fila_id': self.fila_2.id, 'columna_id': self.col_1.id, 'texto_libre': 'x'},
                {'pregunta_id': self.pregunta_matriz_2.id, 'fila_id': self.fila_2.id, 'columna_id': self.col_2.id, 'texto_libre': 'x'},
            ]),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 400)

    def test_rechaza_fila_columna_en_pregunta_no_matriz(self):
        resp = self.client.post(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_individual.id}/respuestas/',
            self._respuestas_base([
                {'pregunta_id': self.pregunta_matriz_2.id, 'fila_id': self.fila_1.id, 'columna_id': self.col_1.id, 'texto_libre': 'Juan'},
                {'pregunta_id': self.pregunta_matriz_2.id, 'fila_id': self.fila_1.id, 'columna_id': self.col_2.id, 'texto_libre': 'x'},
                {'pregunta_id': self.pregunta_matriz_2.id, 'fila_id': self.fila_2.id, 'columna_id': self.col_1.id, 'texto_libre': 'x'},
                {'pregunta_id': self.pregunta_matriz_2.id, 'fila_id': self.fila_2.id, 'columna_id': self.col_2.id, 'texto_libre': 'x'},
                {'pregunta_id': self.pregunta_abierta.id, 'texto_libre': 'x', 'fila_id': self.fila_1.id},
            ]),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 400)


class RespuestaAudioTests(BaseJornadaTestCase):
    """Pregunta.tipo == audio (HU-52). El front graba, transcribe de su lado y nos manda SOLO el
    texto — para el backend es idéntica a una `abierta` (se guarda en Respuesta.texto_libre, no
    entra ni se guarda ningún archivo), y lo que estos tests fijan es justamente eso: que el tipo
    nuevo no abra una puerta distinta (nada de opciones ni de celdas) y que no se quede fuera de
    la validación de obligatoriedad."""
    def setUp(self):
        super().setUp()
        self.pregunta_audio = Pregunta.objects.create(
            momento=self.momento_individual, tipo=Pregunta.TIPO_AUDIO,
            texto='Cuéntanos en voz alta tu experiencia', orden=4, obligatoria=True,
        )
        self.token = self.registrar_participante().data['token']
        self.url = (
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_individual.id}/respuestas/'
        )

    def _respuestas_base(self, extra=None):
        base = [
            {'pregunta_id': self.pregunta_abierta.id, 'texto_libre': 'Mi reflexión.'},
            {'pregunta_id': self.pregunta_unica.id, 'opcion_ids': [self.opcion_a.id]},
        ]
        return {'respuestas': base + (extra or [])}

    def test_guarda_la_transcripcion_como_texto_libre(self):
        resp = self.client.post(
            self.url,
            self._respuestas_base([
                {'pregunta_id': self.pregunta_audio.id, 'texto_libre': 'Me pareció muy enriquecedor el taller.'},
            ]),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 200)
        guardada = Respuesta.objects.get(pregunta=self.pregunta_audio)
        self.assertEqual(guardada.texto_libre, 'Me pareció muy enriquecedor el taller.')
        self.assertEqual(guardada.opciones.count(), 0)
        self.assertIsNone(guardada.fila)
        self.assertIsNone(guardada.fila_lista)
        self.assertIsNone(guardada.columna)

    def test_la_transcripcion_se_lee_de_vuelta(self):
        self.client.post(
            self.url,
            self._respuestas_base([
                {'pregunta_id': self.pregunta_audio.id, 'texto_libre': 'Transcripción de prueba.'},
            ]),
            format='json', **self.auth_header(self.token),
        )
        resp = self.client.get(self.url, **self.auth_header(self.token))
        self.assertEqual(resp.status_code, 200)
        fila = next(r for r in resp.data if r['pregunta'] == self.pregunta_audio.id)
        self.assertEqual(fila['texto_libre'], 'Transcripción de prueba.')
        self.assertEqual(fila['opciones'], [])

    def test_reenviar_actualiza_la_misma_respuesta(self):
        for texto in ('Primera versión.', 'Segunda versión corregida.'):
            resp = self.client.post(
                self.url,
                self._respuestas_base([{'pregunta_id': self.pregunta_audio.id, 'texto_libre': texto}]),
                format='json', **self.auth_header(self.token),
            )
            self.assertEqual(resp.status_code, 200)
        self.assertEqual(Respuesta.objects.filter(pregunta=self.pregunta_audio).count(), 1)
        self.assertEqual(
            Respuesta.objects.get(pregunta=self.pregunta_audio).texto_libre, 'Segunda versión corregida.',
        )

    def test_rechaza_opciones_en_pregunta_audio(self):
        # La opción se crea colgada de la PROPIA pregunta audio a propósito: si se usara una de
        # otra pregunta, el 400 vendría del chequeo genérico de "esa opción no es de esta
        # pregunta" y este test pasaría sin probar nada del tipo nuevo.
        opcion_colada = OpcionPregunta.objects.create(pregunta=self.pregunta_audio, texto='No debería', orden=1)
        resp = self.client.post(
            self.url,
            self._respuestas_base([
                {'pregunta_id': self.pregunta_audio.id, 'texto_libre': 'x', 'opcion_ids': [opcion_colada.id]},
            ]),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 400)

    def test_rechaza_fila_columna_o_fila_temporal_en_pregunta_audio(self):
        fila = FilaMatrizPregunta.objects.create(pregunta=self.pregunta_abierta, texto='f', orden=1)
        columna = ColumnaMatrizPregunta.objects.create(pregunta=self.pregunta_abierta, texto='c', orden=1)
        for extra in (
            {'fila_id': fila.id},
            {'columna_id': columna.id},
            {'fila_temporal': 1},
        ):
            with self.subTest(extra=extra):
                entrada = {'pregunta_id': self.pregunta_audio.id, 'texto_libre': 'x', **extra}
                resp = self.client.post(
                    self.url, self._respuestas_base([entrada]),
                    format='json', **self.auth_header(self.token),
                )
                self.assertEqual(resp.status_code, 400)

    def test_audio_obligatoria_sin_entrada_es_faltante(self):
        resp = self.client.post(
            self.url, self._respuestas_base(), format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('faltantes', resp.data)

    def test_audio_obligatoria_con_texto_en_blanco_se_rechaza(self):
        resp = self.client.post(
            self.url,
            self._respuestas_base([{'pregunta_id': self.pregunta_audio.id, 'texto_libre': '   '}]),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 400)

    def test_audio_no_obligatoria_acepta_no_venir(self):
        self.pregunta_audio.obligatoria = False
        self.pregunta_audio.save()
        resp = self.client.post(
            self.url, self._respuestas_base(), format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Respuesta.objects.filter(pregunta=self.pregunta_audio).count(), 0)

    def test_el_momento_expone_la_pregunta_audio_sin_opciones_ni_celdas(self):
        resp = self.client.get(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_individual.id}/',
            **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 200)
        pregunta = next(p for p in resp.data['preguntas'] if p['id'] == self.pregunta_audio.id)
        self.assertEqual(pregunta['tipo'], 'audio')
        self.assertEqual(pregunta['opciones'], [])
        self.assertEqual(pregunta['filas'], [])
        self.assertEqual(pregunta['columnas'], [])

    def test_estadisticas_tratan_audio_como_texto_libre(self):
        """Sin esto una pregunta audio caería en la rama de opción cerrada y el Excel/el informe
        IA reportarían 0 respuestas aunque las transcripciones estén guardadas."""
        from analitica.analysis import _estadisticas_pregunta

        self.client.post(
            self.url,
            self._respuestas_base([{'pregunta_id': self.pregunta_audio.id, 'texto_libre': 'Algo dicho.'}]),
            format='json', **self.auth_header(self.token),
        )
        estad = _estadisticas_pregunta(self.pregunta_audio)
        self.assertEqual(estad['total_respuestas'], 1)
        self.assertEqual(estad['respuestas_no_vacias'], 1)
        self.assertNotIn('conteo_opciones', estad)


class PreguntaAudioAdminTests(APITestCase):
    """El tipo nuevo tiene que poder crearse desde el panel de administración como cualquier
    otro — si `audio` no está en Pregunta.TIPO_CHOICES, DRF lo rechaza con 400 en el ChoiceField
    que arma el ModelSerializer."""
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username='admin_audio', password='pass12345', is_staff=True,
        )
        self.jornada = Jornada.objects.create(
            slug='jornada-audio', nombre='Jornada audio',
            fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 2),
        )
        self.momento = Momento.objects.create(
            jornada=self.jornada, orden=1, titulo='Voces', tipo=Momento.TIPO_INDIVIDUAL,
        )
        self.client.force_authenticate(user=self.admin)

    def test_crea_pregunta_tipo_audio(self):
        resp = self.client.post('/api/admin/preguntas/', {
            'momento': self.momento.id, 'tipo': 'audio', 'texto': '¿Qué te llevas de hoy?',
            'orden': 1, 'obligatoria': True,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['tipo'], 'audio')
        self.assertEqual(Pregunta.objects.get(id=resp.data['id']).tipo, Pregunta.TIPO_AUDIO)

    def test_rechaza_un_tipo_inexistente(self):
        resp = self.client.post('/api/admin/preguntas/', {
            'momento': self.momento.id, 'tipo': 'audio_archivo', 'texto': 'x',
            'orden': 2, 'obligatoria': False,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('tipo', resp.data)


class RespuestaListaRegresionTests(BaseJornadaTestCase):
    """Red de seguridad mínima para el tipo `lista` (HU-51), que se agregó sin tests: el tipo
    `audio` tocó la validación compartida (`_validar_entrada`, que ahora sí recibe
    `fila_temporal` en el camino normal de guardado), así que acá se fija que una lista siga
    guardándose por filas dinámicas y siga rechazando `fila_id`."""
    def setUp(self):
        super().setUp()
        self.pregunta_lista = Pregunta.objects.create(
            momento=self.momento_individual, tipo=Pregunta.TIPO_LISTA,
            texto='Mapa de capacidades', orden=5, obligatoria=True,
        )
        self.col_nombre = ColumnaMatrizPregunta.objects.create(
            pregunta=self.pregunta_lista, texto='Profesor(a)', orden=1,
        )
        self.col_formacion = ColumnaMatrizPregunta.objects.create(
            pregunta=self.pregunta_lista, texto='Formación', orden=2,
        )
        self.token = self.registrar_participante().data['token']
        self.url = (
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_individual.id}/respuestas/'
        )

    def _respuestas_base(self, extra=None):
        base = [
            {'pregunta_id': self.pregunta_abierta.id, 'texto_libre': 'Mi reflexión.'},
            {'pregunta_id': self.pregunta_unica.id, 'opcion_ids': [self.opcion_a.id]},
        ]
        return {'respuestas': base + (extra or [])}

    def _dos_filas(self):
        return [
            {'pregunta_id': self.pregunta_lista.id, 'fila_temporal': 1, 'columna_id': self.col_nombre.id, 'texto_libre': 'Juan Pérez'},
            {'pregunta_id': self.pregunta_lista.id, 'fila_temporal': 1, 'columna_id': self.col_formacion.id, 'texto_libre': 'Magíster'},
            {'pregunta_id': self.pregunta_lista.id, 'fila_temporal': 2, 'columna_id': self.col_nombre.id, 'texto_libre': 'Ana Gómez'},
            {'pregunta_id': self.pregunta_lista.id, 'fila_temporal': 2, 'columna_id': self.col_formacion.id, 'texto_libre': 'Doctora'},
        ]

    def test_guarda_una_fila_por_fila_temporal(self):
        resp = self.client.post(
            self.url, self._respuestas_base(self._dos_filas()),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(FilaListaRespuesta.objects.filter(pregunta=self.pregunta_lista).count(), 2)
        self.assertEqual(Respuesta.objects.filter(pregunta=self.pregunta_lista).count(), 4)

    def test_reenviar_reemplaza_las_filas_anteriores(self):
        self.client.post(
            self.url, self._respuestas_base(self._dos_filas()),
            format='json', **self.auth_header(self.token),
        )
        resp = self.client.post(
            self.url, self._respuestas_base(self._dos_filas()[:2]),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(FilaListaRespuesta.objects.filter(pregunta=self.pregunta_lista).count(), 1)
        self.assertEqual(Respuesta.objects.filter(pregunta=self.pregunta_lista).count(), 2)

    def test_rechaza_fila_id_en_pregunta_lista(self):
        fila_ajena = FilaMatrizPregunta.objects.create(pregunta=self.pregunta_lista, texto='f', orden=1)
        entradas = self._dos_filas()
        entradas[0] = {**entradas[0], 'fila_id': fila_ajena.id}
        resp = self.client.post(
            self.url, self._respuestas_base(entradas),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 400)

    def test_lista_obligatoria_exige_al_menos_una_fila_completa(self):
        resp = self.client.post(
            self.url,
            self._respuestas_base([
                {'pregunta_id': self.pregunta_lista.id, 'fila_temporal': 1, 'columna_id': self.col_nombre.id, 'texto_libre': 'Juan Pérez'},
            ]),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('faltantes', resp.data)
