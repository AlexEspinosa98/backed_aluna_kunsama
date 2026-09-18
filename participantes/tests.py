import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from jornadas.models import ColumnaMatrizPregunta, FilaMatrizPregunta, Jornada, Momento, OpcionPregunta, Pregunta

from jornadas import emparejamiento

from .extraccion_momento_ia_openai import (
    _construir_payload_esquema, _limpiar_y_validar, aprobar_extraccion_momento,
    emparejar_responsable_momento,
)
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
            'fila_id': None, 'fila_temporal': None, 'columna_id': None,
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
            'fila_id': None, 'fila_temporal': None, 'columna_id': None,
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


class FilasAdicionalesAdminTests(APITestCase):
    """El campo `filas_adicionales` (HU-53) no puede tener un único default de modelo porque el
    suyo depende del tipo: apagado en matriz, encendido en lista. Estas pruebas fijan esa
    resolución y las dos combinaciones que no tienen sentido y se rechazan."""
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username='admin_filas', password='pass12345', is_staff=True,
        )
        self.jornada = Jornada.objects.create(
            slug='jornada-filas', nombre='Jornada filas',
            fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 2),
        )
        self.momento = Momento.objects.create(
            jornada=self.jornada, orden=1, titulo='Tablas', tipo=Momento.TIPO_INDIVIDUAL,
        )
        self.client.force_authenticate(user=self.admin)

    def _crear(self, tipo, orden, **extra):
        return self.client.post('/api/admin/preguntas/', {
            'momento': self.momento.id, 'tipo': tipo, 'texto': f'Pregunta {tipo}',
            'orden': orden, 'obligatoria': False, **extra,
        }, format='json')

    def test_matriz_nace_con_filas_adicionales_apagado(self):
        resp = self._crear('matriz', 1)
        self.assertEqual(resp.status_code, 201)
        self.assertFalse(resp.data['filas_adicionales'])

    def test_lista_nace_con_filas_adicionales_encendido(self):
        resp = self._crear('lista', 2)
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data['filas_adicionales'])

    def test_matriz_puede_nacer_con_filas_adicionales_encendido(self):
        resp = self._crear('matriz', 3, filas_adicionales=True)
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Pregunta.objects.get(id=resp.data['id']).filas_adicionales)

    def test_lista_no_puede_apagar_filas_adicionales(self):
        resp = self._crear('lista', 4, filas_adicionales=False)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('filas_adicionales', resp.data)

    def test_tipo_sin_filas_no_puede_encender_filas_adicionales(self):
        for tipo in ('abierta', 'unica', 'multiple', 'audio'):
            with self.subTest(tipo=tipo):
                resp = self._crear(tipo, 10, filas_adicionales=True)
                self.assertEqual(resp.status_code, 400)
                self.assertIn('filas_adicionales', resp.data)

    def test_patch_enciende_filas_adicionales_en_matriz_existente(self):
        pregunta_id = self._crear('matriz', 5).data['id']
        resp = self.client.patch(
            f'/api/admin/preguntas/{pregunta_id}/', {'filas_adicionales': True}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Pregunta.objects.get(id=pregunta_id).filas_adicionales)

    def test_patch_a_lista_fuerza_filas_adicionales(self):
        # Cambiar el tipo sin mandar el campo no puede dejar la fila en una combinación inválida.
        pregunta_id = self._crear('matriz', 6).data['id']
        resp = self.client.patch(
            f'/api/admin/preguntas/{pregunta_id}/', {'tipo': 'lista'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Pregunta.objects.get(id=pregunta_id).filas_adicionales)

    def test_patch_de_matriz_con_flag_a_tipo_abierta_apaga_el_flag(self):
        pregunta_id = self._crear('matriz', 7, filas_adicionales=True).data['id']
        resp = self.client.patch(
            f'/api/admin/preguntas/{pregunta_id}/', {'tipo': 'abierta'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Pregunta.objects.get(id=pregunta_id).filas_adicionales)


class MatrizConFilasAdicionalesTests(BaseJornadaTestCase):
    """Matriz con `filas_adicionales` encendido (HU-53): conviven las filas FIJAS del admin
    (`fila_id` → Respuesta.fila) con las filas EXTRA que agrega quien responde (`fila_temporal`
    → Respuesta.fila_lista), en la misma pregunta y en el mismo envío."""
    def setUp(self):
        super().setUp()
        self.matriz = Pregunta.objects.create(
            momento=self.momento_individual, tipo=Pregunta.TIPO_MATRIZ,
            texto='Capacidades por área', orden=6, obligatoria=True, filas_adicionales=True,
        )
        self.fila_fija = FilaMatrizPregunta.objects.create(pregunta=self.matriz, texto='Área A', orden=1)
        self.col_1 = ColumnaMatrizPregunta.objects.create(pregunta=self.matriz, texto='Responsable', orden=1)
        self.col_2 = ColumnaMatrizPregunta.objects.create(pregunta=self.matriz, texto='Meta', orden=2)
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

    def _celdas_fijas(self):
        return [
            {'pregunta_id': self.matriz.id, 'fila_id': self.fila_fija.id, 'columna_id': self.col_1.id, 'texto_libre': 'Ana'},
            {'pregunta_id': self.matriz.id, 'fila_id': self.fila_fija.id, 'columna_id': self.col_2.id, 'texto_libre': 'Meta A'},
        ]

    def _celdas_extra(self):
        return [
            {'pregunta_id': self.matriz.id, 'fila_temporal': 1, 'columna_id': self.col_1.id, 'texto_libre': 'Juan'},
            {'pregunta_id': self.matriz.id, 'fila_temporal': 1, 'columna_id': self.col_2.id, 'texto_libre': 'Meta extra'},
        ]

    def test_envio_mixto_guarda_filas_fijas_y_agregadas(self):
        resp = self.client.post(
            self.url, self._respuestas_base(self._celdas_fijas() + self._celdas_extra()),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Respuesta.objects.filter(pregunta=self.matriz, fila__isnull=False).count(), 2)
        self.assertEqual(Respuesta.objects.filter(pregunta=self.matriz, fila_lista__isnull=False).count(), 2)
        self.assertEqual(FilaListaRespuesta.objects.filter(pregunta=self.matriz).count(), 1)
        extra = Respuesta.objects.get(pregunta=self.matriz, fila_lista__isnull=False, columna=self.col_1)
        self.assertEqual(extra.texto_libre, 'Juan')
        self.assertIsNone(extra.fila)

    def test_reenviar_sin_filas_extra_las_borra_y_conserva_las_fijas(self):
        self.client.post(
            self.url, self._respuestas_base(self._celdas_fijas() + self._celdas_extra()),
            format='json', **self.auth_header(self.token),
        )
        resp = self.client.post(
            self.url, self._respuestas_base(self._celdas_fijas()),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(FilaListaRespuesta.objects.filter(pregunta=self.matriz).count(), 0)
        self.assertEqual(Respuesta.objects.filter(pregunta=self.matriz, fila_lista__isnull=False).count(), 0)
        self.assertEqual(Respuesta.objects.filter(pregunta=self.matriz, fila__isnull=False).count(), 2)

    def test_las_filas_extra_no_cuentan_para_la_obligatoriedad(self):
        # Obligatoria en una matriz sigue siendo "todas las celdas fijas": mandar filas extra no
        # puede sustituir una celda fija que falta.
        resp = self.client.post(
            self.url, self._respuestas_base(self._celdas_extra()),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('faltantes', resp.data)

    def test_rechaza_celda_con_fila_id_y_fila_temporal_a_la_vez(self):
        entradas = self._celdas_fijas() + [
            {'pregunta_id': self.matriz.id, 'fila_id': self.fila_fija.id, 'fila_temporal': 1,
             'columna_id': self.col_1.id, 'texto_libre': 'x'},
        ]
        resp = self.client.post(
            self.url, self._respuestas_base(entradas), format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 400)

    def test_matriz_sin_el_flag_sigue_rechazando_fila_temporal(self):
        self.matriz.filas_adicionales = False
        self.matriz.save(update_fields=['filas_adicionales'])
        resp = self.client.post(
            self.url, self._respuestas_base(self._celdas_fijas() + self._celdas_extra()),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(FilaListaRespuesta.objects.filter(pregunta=self.matriz).count(), 0)

    def test_un_envio_invalido_no_deja_las_filas_extra_a_medias(self):
        """El guardado es atómico: las filas dinámicas se borran y se recrean, así que si una
        celda posterior no valida, lo ya escrito tiene que revertirse entero."""
        self.client.post(
            self.url, self._respuestas_base(self._celdas_fijas() + self._celdas_extra()),
            format='json', **self.auth_header(self.token),
        )
        self.assertEqual(FilaListaRespuesta.objects.filter(pregunta=self.matriz).count(), 1)

        entradas = self._celdas_fijas() + [
            {'pregunta_id': self.matriz.id, 'fila_temporal': 9, 'columna_id': self.col_1.id, 'texto_libre': 'Nuevo'},
            # Celda inválida: una matriz no acepta opciones.
            {'pregunta_id': self.matriz.id, 'fila_id': self.fila_fija.id, 'columna_id': self.col_1.id,
             'texto_libre': 'x', 'opcion_ids': [self.opcion_a.id]},
        ]
        resp = self.client.post(
            self.url, self._respuestas_base(entradas), format='json', **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(FilaListaRespuesta.objects.filter(pregunta=self.matriz).count(), 1)

    def test_el_momento_expone_filas_adicionales(self):
        resp = self.client.get(
            f'/api/jornadas/{self.jornada.slug}/momentos/{self.momento_individual.id}/',
            **self.auth_header(self.token),
        )
        self.assertEqual(resp.status_code, 200)
        preguntas = {p['id']: p for p in resp.data['preguntas']}
        self.assertTrue(preguntas[self.matriz.id]['filas_adicionales'])
        self.assertFalse(preguntas[self.pregunta_abierta.id]['filas_adicionales'])


class ExtraccionFilasAgregadasTests(BaseJornadaTestCase):
    """El extractor por IA transcribiendo FILAS AGREGADAS (HU-53): filas que estaban en el
    documento pero no en el esquema de la pregunta. Nada de esto llama a OpenAI — se prueban
    `_construir_payload_esquema` (lo que la IA ve), `_limpiar_y_validar` (el filtro de lo que la
    IA respondió) y `aprobar_extraccion_momento` (la escritura real)."""
    def setUp(self):
        super().setUp()
        self.matriz = Pregunta.objects.create(
            momento=self.momento_individual, tipo=Pregunta.TIPO_MATRIZ,
            texto='Capacidades por área', orden=7, obligatoria=False, filas_adicionales=True,
        )
        self.fila_fija = FilaMatrizPregunta.objects.create(pregunta=self.matriz, texto='Área A', orden=1)
        self.col_1 = ColumnaMatrizPregunta.objects.create(pregunta=self.matriz, texto='Responsable', orden=1)
        self.col_2 = ColumnaMatrizPregunta.objects.create(pregunta=self.matriz, texto='Meta', orden=2)

        self.matriz_fija = Pregunta.objects.create(
            momento=self.momento_individual, tipo=Pregunta.TIPO_MATRIZ,
            texto='Solo filas fijas', orden=8, obligatoria=False,
        )
        self.fija_fila = FilaMatrizPregunta.objects.create(pregunta=self.matriz_fija, texto='F1', orden=1)
        self.fija_col = ColumnaMatrizPregunta.objects.create(pregunta=self.matriz_fija, texto='C1', orden=1)

        self.participante = Participante.objects.create(
            jornada=self.jornada, correo_institucional='extra@uni.edu.co',
            nombre='Depto', apellido='Extra', rol='jefe',
        )
        self.admin = get_user_model().objects.create_user(
            username='admin_extra', password='pass12345', is_staff=True,
        )

    # --- lo que la IA ve -------------------------------------------------------------------
    def test_el_esquema_le_dice_a_la_ia_si_puede_agregar_filas(self):
        esquema = _construir_payload_esquema(self.momento_individual)
        por_id = {p['id']: p for p in esquema['preguntas']}
        self.assertTrue(por_id[self.matriz.id]['filas_adicionales'])
        self.assertFalse(por_id[self.matriz_fija.id]['filas_adicionales'])
        self.assertFalse(por_id[self.pregunta_abierta.id]['filas_adicionales'])

    def test_el_esquema_manda_las_columnas_de_una_lista(self):
        # Antes solo se mandaban las de matriz, así que la IA no tenía a qué columna apuntar en
        # una lista y toda la pregunta terminaba omitida.
        lista = Pregunta.objects.create(
            momento=self.momento_individual, tipo=Pregunta.TIPO_LISTA,
            texto='Profesores', orden=9, obligatoria=False, filas_adicionales=True,
        )
        columna = ColumnaMatrizPregunta.objects.create(pregunta=lista, texto='Nombre', orden=1)
        esquema = _construir_payload_esquema(self.momento_individual)
        por_id = {p['id']: p for p in esquema['preguntas']}
        self.assertEqual([c['id'] for c in por_id[lista.id]['columnas']], [columna.id])
        self.assertEqual(por_id[lista.id]['filas'], [])
        self.assertTrue(por_id[lista.id]['filas_adicionales'])

    # --- filtro de lo que la IA respondió --------------------------------------------------
    def test_conserva_celdas_de_fila_agregada(self):
        crudo = {'respuestas': [
            {'pregunta': self.matriz.id, 'fila_temporal': 1, 'columna_id': self.col_1.id, 'texto_libre': 'Juan'},
            {'pregunta': self.matriz.id, 'fila_temporal': 1, 'columna_id': self.col_2.id, 'texto_libre': 'Meta X'},
        ]}
        limpio, omitidas = _limpiar_y_validar(crudo, self.momento_individual)
        self.assertEqual(omitidas, [])
        self.assertEqual(len(limpio['respuestas']), 2)
        self.assertEqual(limpio['respuestas'][0]['fila_temporal'], 1)
        self.assertIsNone(limpio['respuestas'][0]['fila_id'])

    def test_conserva_celdas_fijas_y_agregadas_en_la_misma_pregunta(self):
        crudo = {'respuestas': [
            {'pregunta': self.matriz.id, 'fila_id': self.fila_fija.id, 'columna_id': self.col_1.id, 'texto_libre': 'Ana'},
            {'pregunta': self.matriz.id, 'fila_temporal': 1, 'columna_id': self.col_1.id, 'texto_libre': 'Juan'},
        ]}
        limpio, omitidas = _limpiar_y_validar(crudo, self.momento_individual)
        self.assertEqual(omitidas, [])
        self.assertEqual(
            [(r['fila_id'], r['fila_temporal']) for r in limpio['respuestas']],
            [(self.fila_fija.id, None), (None, 1)],
        )

    def test_omite_fila_agregada_si_la_pregunta_no_la_permite(self):
        crudo = {'respuestas': [
            {'pregunta': self.matriz_fija.id, 'fila_temporal': 1, 'columna_id': self.fija_col.id, 'texto_libre': 'x'},
        ]}
        limpio, omitidas = _limpiar_y_validar(crudo, self.momento_individual)
        self.assertEqual(omitidas, [self.matriz_fija.id])
        self.assertEqual(limpio['respuestas'], [])

    def test_omite_celda_con_fila_id_y_fila_temporal_a_la_vez(self):
        crudo = {'respuestas': [
            {'pregunta': self.matriz.id, 'fila_id': self.fila_fija.id, 'fila_temporal': 1,
             'columna_id': self.col_1.id, 'texto_libre': 'x'},
        ]}
        limpio, omitidas = _limpiar_y_validar(crudo, self.momento_individual)
        self.assertEqual(omitidas, [self.matriz.id])
        self.assertEqual(limpio['respuestas'], [])

    def test_omite_fila_temporal_que_no_es_un_numero(self):
        crudo = {'respuestas': [
            {'pregunta': self.matriz.id, 'fila_temporal': 'fila nueva', 'columna_id': self.col_1.id,
             'texto_libre': 'x'},
        ]}
        limpio, omitidas = _limpiar_y_validar(crudo, self.momento_individual)
        self.assertEqual(omitidas, [self.matriz.id])
        self.assertEqual(limpio['respuestas'], [])

    def test_omite_columna_que_no_es_de_la_pregunta(self):
        crudo = {'respuestas': [
            {'pregunta': self.matriz.id, 'fila_temporal': 1, 'columna_id': self.fija_col.id, 'texto_libre': 'x'},
        ]}
        _limpio, omitidas = _limpiar_y_validar(crudo, self.momento_individual)
        self.assertEqual(omitidas, [self.matriz.id])

    # --- escritura real --------------------------------------------------------------------
    def _extraccion(self, respuestas):
        return ExtraccionMomento.objects.create(
            momento=self.momento_individual, participante=self.participante,
            archivo=SimpleUploadedFile('b.pdf', b'contenido', content_type='application/pdf'),
            estado=ExtraccionMomento.ESTADO_COMPLETO,
            resultado={'respuestas': respuestas},
        )

    def test_aprobar_escribe_las_filas_agregadas(self):
        extraccion = self._extraccion([
            {'pregunta': self.matriz.id, 'fila_id': self.fila_fija.id, 'fila_temporal': None,
             'columna_id': self.col_1.id, 'texto_libre': 'Ana', 'opcion_ids': []},
            {'pregunta': self.matriz.id, 'fila_id': None, 'fila_temporal': 1,
             'columna_id': self.col_1.id, 'texto_libre': 'Juan', 'opcion_ids': []},
            {'pregunta': self.matriz.id, 'fila_id': None, 'fila_temporal': 1,
             'columna_id': self.col_2.id, 'texto_libre': 'Meta X', 'opcion_ids': []},
            {'pregunta': self.matriz.id, 'fila_id': None, 'fila_temporal': 2,
             'columna_id': self.col_1.id, 'texto_libre': 'Sofía', 'opcion_ids': []},
        ])
        guardadas = aprobar_extraccion_momento(extraccion, self.admin)
        self.assertEqual(len(guardadas), 4)
        self.assertEqual(FilaListaRespuesta.objects.filter(pregunta=self.matriz).count(), 2)
        self.assertEqual(
            Respuesta.objects.filter(pregunta=self.matriz, fila__isnull=False).count(), 1,
        )
        self.assertEqual(
            Respuesta.objects.filter(pregunta=self.matriz, fila_lista__isnull=False).count(), 3,
        )
        # Las celdas de un mismo fila_temporal comparten fila, y dos distintos no.
        fila_1 = set(
            Respuesta.objects.filter(pregunta=self.matriz, texto_libre__in=['Juan', 'Meta X'])
            .values_list('fila_lista_id', flat=True)
        )
        self.assertEqual(len(fila_1), 1)
        fila_2 = Respuesta.objects.get(pregunta=self.matriz, texto_libre='Sofía').fila_lista_id
        self.assertNotIn(fila_2, fila_1)

    def test_aprobar_reemplaza_las_filas_agregadas_previas_de_esa_pregunta(self):
        aprobar_extraccion_momento(self._extraccion([
            {'pregunta': self.matriz.id, 'fila_id': None, 'fila_temporal': 1,
             'columna_id': self.col_1.id, 'texto_libre': 'Viejo', 'opcion_ids': []},
            {'pregunta': self.matriz.id, 'fila_id': None, 'fila_temporal': 2,
             'columna_id': self.col_1.id, 'texto_libre': 'Viejo 2', 'opcion_ids': []},
        ]), self.admin)
        self.assertEqual(FilaListaRespuesta.objects.filter(pregunta=self.matriz).count(), 2)

        aprobar_extraccion_momento(self._extraccion([
            {'pregunta': self.matriz.id, 'fila_id': None, 'fila_temporal': 1,
             'columna_id': self.col_1.id, 'texto_libre': 'Nuevo', 'opcion_ids': []},
        ]), self.admin)
        self.assertEqual(FilaListaRespuesta.objects.filter(pregunta=self.matriz).count(), 1)
        self.assertEqual(
            list(Respuesta.objects.filter(
                pregunta=self.matriz, fila_lista__isnull=False,
            ).values_list('texto_libre', flat=True)),
            ['Nuevo'],
        )

    def test_aprobar_no_borra_filas_de_una_pregunta_que_el_documento_no_menciona(self):
        """Aprobar escribe lo que el documento traía. Un documento que no habla de una pregunta
        no es una instrucción de borrar lo que esa pregunta ya tenía."""
        aprobar_extraccion_momento(self._extraccion([
            {'pregunta': self.matriz.id, 'fila_id': None, 'fila_temporal': 1,
             'columna_id': self.col_1.id, 'texto_libre': 'Se queda', 'opcion_ids': []},
        ]), self.admin)

        aprobar_extraccion_momento(self._extraccion([
            {'pregunta': self.pregunta_abierta.id, 'texto_libre': 'Otra cosa', 'opcion_ids': []},
        ]), self.admin)
        self.assertEqual(FilaListaRespuesta.objects.filter(pregunta=self.matriz).count(), 1)
        self.assertEqual(
            Respuesta.objects.get(pregunta=self.matriz, fila_lista__isnull=False).texto_libre, 'Se queda',
        )


class ResponsableDetectadoMomentoTests(BaseJornadaTestCase):
    """HU-55 del lado de momentos: subir un documento sin decir de quién es y dejar que la IA
    detecte al responsable. Acá no hace falta un estado nuevo como en instrumentos — este modelo
    ya difiere la escritura hasta `aprobar`, así que sin responsable simplemente no se aprueba."""
    def setUp(self):
        super().setUp()
        self.ana = Participante.objects.create(
            jornada=self.jornada, correo_institucional='ana@uni.edu.co',
            nombre='Ana María', apellido='Gómez', rol='docente',
        )
        self.juan = Participante.objects.create(
            jornada=self.jornada, correo_institucional='juan@uni.edu.co',
            nombre='Juan', apellido='Pérez', rol='docente',
        )
        self.admin = get_user_model().objects.create_user(
            username='admin_resp', password='pass12345', is_staff=True,
        )

    def test_empareja_por_nombre_parcial(self):
        participante, estado = emparejar_responsable_momento(
            self.momento_individual, {'nombre': 'Ana Gómez'},
        )
        self.assertEqual(participante, self.ana)
        self.assertEqual(estado, emparejamiento.ESTADO_EMPAREJADO)

    def test_empareja_por_correo_institucional(self):
        participante, estado = emparejar_responsable_momento(
            self.momento_individual, {'nombre': 'No coincide', 'correo': 'JUAN@UNI.EDU.CO'},
        )
        self.assertEqual(participante, self.juan)
        self.assertEqual(estado, emparejamiento.ESTADO_EMPAREJADO)

    def test_no_empareja_contra_otra_jornada(self):
        otra = Jornada.objects.create(
            slug='otra-jornada', nombre='Otra', fecha_inicio=datetime.date(2026, 9, 1),
            fecha_fin=datetime.date(2026, 9, 2),
        )
        Participante.objects.create(
            jornada=otra, correo_institucional='externo@uni.edu.co',
            nombre='Carlos', apellido='Restrepo', rol='docente',
        )
        participante, estado = emparejar_responsable_momento(
            self.momento_individual, {'nombre': 'Carlos Restrepo'},
        )
        self.assertIsNone(participante)
        self.assertEqual(estado, emparejamiento.ESTADO_SIN_COINCIDENCIA)

    def test_sin_coincidencia_no_crea_participante(self):
        antes = Participante.objects.count()
        participante, estado = emparejar_responsable_momento(
            self.momento_individual, {'nombre': 'Nadie Conocido'},
        )
        self.assertIsNone(participante)
        self.assertEqual(estado, emparejamiento.ESTADO_SIN_COINCIDENCIA)
        self.assertEqual(Participante.objects.count(), antes)

    def test_subir_sin_participante_ya_no_es_error_de_validacion(self):
        self.client.force_authenticate(user=self.admin)
        with patch('participantes.admin_views.threading.Thread'):
            resp = self.client.post('/api/admin/momento-extracciones/', {
                'momento': self.momento_individual.id,
                'archivo': SimpleUploadedFile('d.pdf', b'x', content_type='application/pdf'),
            }, format='multipart')
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(ExtraccionMomento.objects.get(id=resp.data['id']).participante)

    def test_ficha_de_alta_incompleta_sigue_siendo_error(self):
        """Omitir todo es delegarle la detección a la IA; mandar media ficha es un bug del
        cliente y tiene que seguir fallando."""
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post('/api/admin/momento-extracciones/', {
            'momento': self.momento_individual.id,
            'archivo': SimpleUploadedFile('d.pdf', b'x', content_type='application/pdf'),
            'nombre': 'Solo el nombre',
        }, format='multipart')
        self.assertEqual(resp.status_code, 400)

    def _extraccion_sin_responsable(self):
        return ExtraccionMomento.objects.create(
            momento=self.momento_individual, participante=None,
            archivo=SimpleUploadedFile('e.pdf', b'x', content_type='application/pdf'),
            estado=ExtraccionMomento.ESTADO_COMPLETO,
            responsable_detectado={'nombre': 'Alguien Sin Registro'},
            responsable_estado=emparejamiento.ESTADO_SIN_COINCIDENCIA,
            resultado={'respuestas': [
                {'pregunta': self.pregunta_abierta.id, 'texto_libre': 'Del papel', 'opcion_ids': []},
            ]},
        )

    def test_no_se_puede_aprobar_sin_responsable(self):
        extraccion = self._extraccion_sin_responsable()
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(f'/api/admin/momento-extracciones/{extraccion.id}/aprobar/')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Respuesta.objects.filter(pregunta=self.pregunta_abierta).count(), 0)

    def test_asignar_responsable_y_luego_aprobar(self):
        extraccion = self._extraccion_sin_responsable()
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f'/api/admin/momento-extracciones/{extraccion.id}/asignar-responsable/',
            {'participante_id': self.ana.id}, format='json',
        )
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post(f'/api/admin/momento-extracciones/{extraccion.id}/aprobar/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Respuesta.objects.get(pregunta=self.pregunta_abierta, participante=self.ana).texto_libre,
            'Del papel',
        )

    def test_asignar_rechaza_participante_de_otra_jornada(self):
        extraccion = self._extraccion_sin_responsable()
        otra = Jornada.objects.create(
            slug='jornada-ajena', nombre='Ajena', fecha_inicio=datetime.date(2026, 9, 1),
            fecha_fin=datetime.date(2026, 9, 2),
        )
        ajeno = Participante.objects.create(
            jornada=otra, correo_institucional='x@uni.edu.co', nombre='X', apellido='Y', rol='z',
        )
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f'/api/admin/momento-extracciones/{extraccion.id}/asignar-responsable/',
            {'participante_id': ajeno.id}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_el_listado_no_revienta_con_una_extraccion_sin_responsable(self):
        self._extraccion_sin_responsable()
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/admin/momento-extracciones/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data[0]['participante_nombre'])
