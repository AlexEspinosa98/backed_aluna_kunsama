import datetime
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from jornadas.models import Jornada, PerfilUsuario
from participantes.models import Participante

from jornadas import emparejamiento

from .extraccion_ia_openai import (
    _guardar_respuestas, _limpiar_responsable, asignar_responsable_instrumento,
    emparejar_responsable_instrumento,
)
from .models import (
    AplicacionInstrumento, ColumnaMatrizInstrumento, ExtraccionInstrumento, FilaMatrizInstrumento,
    Instrumento, OpcionPreguntaInstrumento, PreguntaInstrumento, PreregistroInstrumento,
    RespuestaInstrumento, SeccionInstrumento,
)

Usuario = get_user_model()


def crear_admin(username='admin'):
    return Usuario.objects.create_user(username=username, password='pass12345', is_staff=True)


def crear_dependencia(username='dependencia'):
    usuario = Usuario.objects.create_user(username=username, password='pass12345', is_staff=True)
    PerfilUsuario.objects.create(user=usuario, rol=PerfilUsuario.ROL_DEPENDENCIA)
    return usuario


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

    def test_login_no_distingue_mayusculas_en_username(self):
        resp = self.client.post(
            '/api/instrumentos/login/', {'username': 'Docente', 'password': 'clave12345'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('token', resp.data)


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


class InstrumentoVinculadoAJornadaTests(APITestCase):
    """Un instrumento puede vincularse a una Jornada — en ese caso `encargados` deja de usarse
    para scoping, la propiedad pasa a ser Jornada.propietarios (ver
    Instrumento.propietarios_efectivos())."""

    def setUp(self):
        self.admin = crear_admin('admin2')
        self.dependencia_a = crear_dependencia('dependencia_a')
        self.dependencia_b = crear_dependencia('dependencia_b')
        self.jornada_a = Jornada.objects.create(
            slug='jornada-a', nombre='Jornada A',
            fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 2),
        )
        self.jornada_a.propietarios.add(self.dependencia_a)

    def test_instrumento_vinculado_hereda_propietarios_de_la_jornada(self):
        instrumento = Instrumento.objects.create(nombre='Diagnóstico', jornada=self.jornada_a)

        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.get(f'/api/admin/instrumentos/{instrumento.slug}/')
        self.assertEqual(resp.status_code, 200)

        self.client.force_authenticate(user=self.dependencia_b)
        resp = self.client.get(f'/api/admin/instrumentos/{instrumento.slug}/')
        self.assertEqual(resp.status_code, 404)

    def test_dependencia_no_puede_vincular_a_jornada_ajena(self):
        jornada_ajena = Jornada.objects.create(
            slug='jornada-ajena', nombre='Ajena',
            fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 2),
        )
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post(
            '/api/admin/instrumentos/', {'nombre': 'Intento', 'jornada': jornada_ajena.id}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_dependencia_puede_crear_vinculado_a_su_jornada_sin_forzar_encargados(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post(
            '/api/admin/instrumentos/', {'nombre': 'Vinculado', 'jornada': self.jornada_a.id}, format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        instrumento = Instrumento.objects.get(slug=resp.data['slug'])
        self.assertEqual(instrumento.jornada_id, self.jornada_a.id)
        self.assertEqual(list(instrumento.encargados.all()), [])

    def test_desvincular_de_jornada_deja_al_usuario_como_encargado(self):
        instrumento = Instrumento.objects.create(nombre='Para desvincular', jornada=self.jornada_a)
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.patch(f'/api/admin/instrumentos/{instrumento.slug}/', {'jornada': None}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        instrumento.refresh_from_db()
        self.assertIsNone(instrumento.jornada_id)
        self.assertEqual(list(instrumento.encargados.all()), [self.dependencia_a])

    def test_seccion_bajo_instrumento_vinculado_usa_scoping_de_jornada(self):
        instrumento = Instrumento.objects.create(nombre='Con secciones', jornada=self.jornada_a)

        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post(
            '/api/admin/instrumento-secciones/',
            {'instrumento': instrumento.id, 'orden': 1, 'titulo': 'Intro', 'tipo': 'contenido'},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)

        self.client.force_authenticate(user=self.dependencia_b)
        resp = self.client.post(
            '/api/admin/instrumento-secciones/',
            {'instrumento': instrumento.id, 'orden': 2, 'titulo': 'Ajena', 'tipo': 'contenido'},
            format='json',
        )
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

    def test_no_permite_crear_usuario_nuevo_con_username_duplicado_por_mayusculas(self):
        # self.preregistrado ya existe con username='docente' (ver setUp) — el login ya no
        # distingue mayúsculas, así que tampoco se debe poder crear 'Docente' como cuenta aparte.
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            '/api/admin/instrumento-preregistrados/',
            {
                'instrumento': self.instrumento.id, 'username': 'Docente',
                'password': 'OtraClave123',
            },
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


class GuardarRespuestasExtraccionTests(BaseInstrumentoTestCase):
    """_guardar_respuestas es lo que la IA usa para volcar su transcripción a
    RespuestaInstrumento — no depende de OpenAI, así que se prueba directo con datos "crudos"
    como los que devolvería el modelo."""
    def setUp(self):
        super().setUp()
        self.aplicacion = AplicacionInstrumento.objects.create(preregistro=self.preregistro)
        self.preguntas_validas = {self.pregunta_abierta.id: self.pregunta_abierta, self.pregunta_matriz.id: self.pregunta_matriz}

    def test_guarda_pregunta_abierta_aunque_la_ia_mande_fila_columna_null_explicitos(self):
        # Regresión: el prompt le pide a la IA mandar siempre fila/columna (null si no aplica),
        # pero PrimaryKeyRelatedField(required=False) sin allow_null=True rechaza un null
        # explícito — sin el filtrado en _guardar_respuestas, esto se omitía siempre.
        crudo = [{
            'pregunta': self.pregunta_abierta.id, 'texto_libre': 'Respuesta de la IA.',
            'opciones': [], 'fila': None, 'columna': None,
        }]
        guardadas, omitidas = _guardar_respuestas(self.aplicacion, crudo, self.preguntas_validas)
        self.assertEqual(guardadas, 1)
        self.assertEqual(omitidas, [])
        respuesta = RespuestaInstrumento.objects.get(aplicacion=self.aplicacion, pregunta=self.pregunta_abierta)
        self.assertEqual(respuesta.texto_libre, 'Respuesta de la IA.')

    def test_guarda_celda_de_matriz_con_fila_y_columna_reales(self):
        crudo = [{
            'pregunta': self.pregunta_matriz.id, 'texto_libre': 'Celda IA.',
            'opciones': [], 'fila': self.fila.id, 'columna': self.columna.id,
        }]
        guardadas, omitidas = _guardar_respuestas(self.aplicacion, crudo, self.preguntas_validas)
        self.assertEqual(guardadas, 1)
        self.assertEqual(omitidas, [])
        respuesta = RespuestaInstrumento.objects.get(aplicacion=self.aplicacion, pregunta=self.pregunta_matriz)
        self.assertEqual(respuesta.fila_id, self.fila.id)
        self.assertEqual(respuesta.columna_id, self.columna.id)

    def test_omite_pregunta_matriz_sin_fila_ni_columna(self):
        crudo = [{
            'pregunta': self.pregunta_matriz.id, 'texto_libre': 'Sin ubicar.',
            'opciones': [], 'fila': None, 'columna': None,
        }]
        guardadas, omitidas = _guardar_respuestas(self.aplicacion, crudo, self.preguntas_validas)
        self.assertEqual(guardadas, 0)
        self.assertEqual(omitidas, [self.pregunta_matriz.id])

    def test_omite_pregunta_que_no_pertenece_al_instrumento(self):
        crudo = [{'pregunta': 999999, 'texto_libre': 'Inventada.', 'opciones': [], 'fila': None, 'columna': None}]
        guardadas, omitidas = _guardar_respuestas(self.aplicacion, crudo, self.preguntas_validas)
        self.assertEqual(guardadas, 0)
        self.assertEqual(omitidas, [999999])


class ExtraccionInstrumentoScopingTests(BaseInstrumentoTestCase):
    """Scoping por dependencia sobre ExtraccionInstrumento — mismo patrón que
    AnalisisJornadaIAScopingTests en analitica/tests.py, aplicado a esta subida de PDF/Word."""
    def setUp(self):
        super().setUp()
        self.dependencia = crear_dependencia()
        self.instrumento.encargados.add(self.dependencia)

        self.otro_instrumento = Instrumento.objects.create(nombre='Otro instrumento')
        self.otro_instrumento.encargados.add(self.admin)

        self.extraccion_propia = ExtraccionInstrumento.objects.create(
            instrumento=self.instrumento, usuario=self.preregistrado,
            archivo=SimpleUploadedFile('a.pdf', b'contenido', content_type='application/pdf'),
        )
        self.extraccion_ajena = ExtraccionInstrumento.objects.create(
            instrumento=self.otro_instrumento, usuario=self.preregistrado,
            archivo=SimpleUploadedFile('b.pdf', b'contenido', content_type='application/pdf'),
        )

    def test_dependencia_solo_ve_extracciones_de_su_instrumento(self):
        self.client.force_authenticate(user=self.dependencia)
        resp = self.client.get('/api/admin/instrumento-extracciones/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([e['id'] for e in resp.data], [self.extraccion_propia.id])

    def test_admin_completo_ve_todas_las_extracciones(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/admin/instrumento-extracciones/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            {e['id'] for e in resp.data}, {self.extraccion_propia.id, self.extraccion_ajena.id}
        )

    def test_dependencia_no_puede_subir_documento_para_instrumento_ajeno(self):
        self.client.force_authenticate(user=self.dependencia)
        archivo = SimpleUploadedFile('c.pdf', b'contenido', content_type='application/pdf')
        resp = self.client.post('/api/admin/instrumento-extracciones/', {
            'instrumento': self.otro_instrumento.id, 'usuario_id': self.preregistrado.id, 'archivo': archivo,
        }, format='multipart')
        self.assertEqual(resp.status_code, 403)

    def test_rechaza_formato_no_soportado(self):
        self.client.force_authenticate(user=self.admin)
        archivo = SimpleUploadedFile('c.txt', b'contenido', content_type='text/plain')
        resp = self.client.post('/api/admin/instrumento-extracciones/', {
            'instrumento': self.instrumento.id, 'usuario_id': self.preregistrado.id, 'archivo': archivo,
        }, format='multipart')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('archivo', resp.data)


class EmparejarResponsableInstrumentoTests(BaseInstrumentoTestCase):
    """Emparejamiento del responsable que la IA leyó en el documento (HU-55). Nada de esto llama
    a OpenAI: se prueba la resolución contra la base, que es la parte que decide a nombre de
    quién va a quedar una respuesta."""
    def setUp(self):
        super().setUp()
        self.preregistrado = Usuario.objects.create_user(
            username='jperez', password='clave12345', is_staff=False,
            first_name='Juan', last_name='Pérez', email='juan@uni.edu.co',
        )
        PreregistroInstrumento.objects.create(
            instrumento=self.instrumento, usuario=self.preregistrado, creado_por=self.admin,
        )

    def test_empareja_por_nombre_del_preregistrado(self):
        usuario, estado = emparejar_responsable_instrumento(self.instrumento, {'nombre': 'juan perez'})
        self.assertEqual(usuario, self.preregistrado)
        self.assertEqual(estado, emparejamiento.ESTADO_EMPAREJADO)

    def test_empareja_por_correo(self):
        usuario, estado = emparejar_responsable_instrumento(
            self.instrumento, {'nombre': 'Otro Nombre', 'correo': 'JUAN@UNI.EDU.CO'},
        )
        self.assertEqual(usuario, self.preregistrado)
        self.assertEqual(estado, emparejamiento.ESTADO_EMPAREJADO)

    def test_prefiere_al_preregistrado_sobre_un_homonimo_ajeno(self):
        """Un homónimo que no tiene nada que ver con el instrumento no debería competir con
        alguien a quien sí se le asignó — si compitiera, cualquier nombre común sería ambiguo."""
        Usuario.objects.create_user(
            username='jperez2', password='clave12345', is_staff=False,
            first_name='Juan', last_name='Pérez',
        )
        usuario, estado = emparejar_responsable_instrumento(self.instrumento, {'nombre': 'Juan Pérez'})
        self.assertEqual(usuario, self.preregistrado)
        self.assertEqual(estado, emparejamiento.ESTADO_EMPAREJADO)

    def test_cae_a_usuarios_no_preregistrados_si_no_hay_nada_en_el_instrumento(self):
        externo = Usuario.objects.create_user(
            username='ext', password='clave12345', is_staff=False,
            first_name='Ana', last_name='Gómez',
        )
        usuario, estado = emparejar_responsable_instrumento(self.instrumento, {'nombre': 'Ana Gómez'})
        self.assertEqual(usuario, externo)
        self.assertEqual(estado, emparejamiento.ESTADO_EMPAREJADO)

    def test_sin_coincidencia_no_inventa_usuario(self):
        antes = Usuario.objects.count()
        usuario, estado = emparejar_responsable_instrumento(
            self.instrumento, {'nombre': 'Persona Que No Existe'},
        )
        self.assertIsNone(usuario)
        self.assertEqual(estado, emparejamiento.ESTADO_SIN_COINCIDENCIA)
        self.assertEqual(Usuario.objects.count(), antes)

    def test_documento_sin_responsable(self):
        usuario, estado = emparejar_responsable_instrumento(self.instrumento, {})
        self.assertIsNone(usuario)
        self.assertEqual(estado, emparejamiento.ESTADO_SIN_DATO)

    def test_limpiar_responsable_tolera_basura_de_la_ia(self):
        self.assertEqual(_limpiar_responsable(None), {})
        self.assertEqual(_limpiar_responsable('Juan'), {})
        self.assertEqual(
            _limpiar_responsable({'nombre': '  Juan  ', 'correo': None, 'cargo': 12, 'dependencia': ''}),
            {'nombre': 'Juan'},
        )


class AsignarResponsableInstrumentoTests(BaseInstrumentoTestCase):
    """Una extracción que quedó en `sin_responsable` (la IA transcribió pero nadie coincidió) se
    termina asignando la persona a mano, SIN volver a llamar a OpenAI — la transcripción ya está
    guardada en `resultado_crudo`."""
    def setUp(self):
        super().setUp()
        self.usuario = crear_preregistrado('depto')
        self.extraccion = ExtraccionInstrumento.objects.create(
            instrumento=self.instrumento, usuario=None,
            archivo=SimpleUploadedFile('doc.pdf', b'x', content_type='application/pdf'),
            estado=ExtraccionInstrumento.ESTADO_SIN_RESPONSABLE,
            responsable_detectado={'nombre': 'Alguien Sin Cuenta'},
            responsable_estado=emparejamiento.ESTADO_SIN_COINCIDENCIA,
            resultado_crudo={'respuestas': [
                {'pregunta': self.pregunta_abierta.id, 'texto_libre': 'Respuesta del papel', 'opciones': []},
            ]},
        )

    def test_la_transcripcion_no_se_pierde_mientras_no_hay_responsable(self):
        self.assertEqual(len(self.extraccion.resultado_crudo['respuestas']), 1)
        self.assertIsNone(self.extraccion.aplicacion)

    def test_asignar_escribe_la_aplicacion_con_lo_ya_transcrito(self):
        asignar_responsable_instrumento(self.extraccion, self.usuario)
        self.extraccion.refresh_from_db()
        self.assertEqual(self.extraccion.usuario, self.usuario)
        self.assertEqual(self.extraccion.estado, ExtraccionInstrumento.ESTADO_COMPLETO)
        self.assertIsNotNone(self.extraccion.aplicacion)
        self.assertTrue(self.extraccion.aplicacion.generado_por_ia)
        self.assertEqual(
            self.extraccion.aplicacion.estado, AplicacionInstrumento.ESTADO_PENDIENTE,
        )
        self.assertEqual(
            RespuestaInstrumento.objects.get(
                aplicacion=self.extraccion.aplicacion, pregunta=self.pregunta_abierta,
            ).texto_libre,
            'Respuesta del papel',
        )

    def test_asignar_crea_el_preregistro_si_no_existia(self):
        self.assertFalse(
            PreregistroInstrumento.objects.filter(
                instrumento=self.instrumento, usuario=self.usuario,
            ).exists()
        )
        asignar_responsable_instrumento(self.extraccion, self.usuario)
        self.assertTrue(
            PreregistroInstrumento.objects.filter(
                instrumento=self.instrumento, usuario=self.usuario,
            ).exists()
        )

    def test_asignar_conserva_por_que_hubo_que_asignar_a_mano(self):
        asignar_responsable_instrumento(self.extraccion, self.usuario)
        self.extraccion.refresh_from_db()
        self.assertEqual(self.extraccion.responsable_estado, emparejamiento.ESTADO_SIN_COINCIDENCIA)
        self.assertEqual(self.extraccion.responsable_detectado, {'nombre': 'Alguien Sin Cuenta'})

    def test_endpoint_asignar_responsable(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f'/api/admin/instrumento-extracciones/{self.extraccion.id}/asignar-responsable/',
            {'usuario_id': self.usuario.id}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['estado'], ExtraccionInstrumento.ESTADO_COMPLETO)

    def test_endpoint_rechaza_asignar_sobre_una_extraccion_ya_completa(self):
        self.extraccion.estado = ExtraccionInstrumento.ESTADO_COMPLETO
        self.extraccion.save(update_fields=['estado'])
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f'/api/admin/instrumento-extracciones/{self.extraccion.id}/asignar-responsable/',
            {'usuario_id': self.usuario.id}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_subir_sin_usuario_ya_no_es_error_de_validacion(self):
        """Antes era obligatorio decir de quién era el documento. Desde HU-55 se puede omitir y
        dejar que la IA lo detecte."""
        self.client.force_authenticate(user=self.admin)
        with patch('instrumentos.views.threading.Thread'):
            resp = self.client.post('/api/admin/instrumento-extracciones/', {
                'instrumento': self.instrumento.id,
                'archivo': SimpleUploadedFile('x.pdf', b'x', content_type='application/pdf'),
            }, format='multipart')
        self.assertEqual(resp.status_code, 201)
        self.assertIsNone(ExtraccionInstrumento.objects.get(id=resp.data['id']).usuario)
