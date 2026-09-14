from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from jornadas.models import PerfilUsuario

from .informe_ia import PALABRAS_POR_TRAMO, _limpiar_texto, _particionar_en_tramos
from .models import FragmentoTranscripcion, InformeTranscripcion, SesionTranscripcion

Usuario = get_user_model()


def crear_admin_completo(username):
    return Usuario.objects.create_user(username=username, password='pass12345', is_staff=True)


def crear_dependencia(username):
    usuario = Usuario.objects.create_user(username=username, password='pass12345', is_staff=True)
    PerfilUsuario.objects.create(user=usuario, rol=PerfilUsuario.ROL_DEPENDENCIA)
    return usuario


def crear_sesion(nombre, encargado=None, estado=SesionTranscripcion.EN_CURSO):
    sesion = SesionTranscripcion.objects.create(nombre=nombre, estado=estado)
    if encargado:
        sesion.encargados.add(encargado)
    return sesion


class SesionTranscripcionScopingTests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dependencia_a = crear_dependencia('dependencia_a')
        self.sesion_a = crear_sesion('Sesion A', encargado=self.dependencia_a)
        self.sesion_b = crear_sesion('Sesion B')

    def test_dependencia_solo_ve_sus_sesiones(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.get('/api/admin/transcripciones/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([s['slug'] for s in resp.data], [self.sesion_a.slug])

    def test_admin_completo_ve_todas(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/admin/transcripciones/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({s['slug'] for s in resp.data}, {self.sesion_a.slug, self.sesion_b.slug})

    def test_dependencia_queda_como_unico_encargado_al_crear(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post('/api/admin/transcripciones/', {'nombre': 'Nueva sesión'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        sesion = SesionTranscripcion.objects.get(slug=resp.data['slug'])
        self.assertEqual(list(sesion.encargados.all()), [self.dependencia_a])

    def test_dependencia_no_ve_sesion_ajena(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.get(f'/api/admin/transcripciones/{self.sesion_b.slug}/')
        self.assertEqual(resp.status_code, 404)


class SesionVinculadaAJornadaTests(APITestCase):
    """Una sesión puede vincularse a una Jornada — en ese caso `encargados` deja de usarse para
    scoping, la propiedad pasa a ser Jornada.propietarios (mismo mecanismo que Instrumento)."""

    def setUp(self):
        from jornadas.models import Jornada

        self.admin = crear_admin_completo('admin')
        self.dependencia_a = crear_dependencia('dependencia_a')
        self.dependencia_b = crear_dependencia('dependencia_b')
        self.jornada_a = Jornada.objects.create(
            slug='jornada-a', nombre='Jornada A',
            fecha_inicio='2026-09-01', fecha_fin='2026-09-02',
        )
        self.jornada_a.propietarios.add(self.dependencia_a)

    def test_sesion_vinculada_hereda_propietarios_de_la_jornada(self):
        sesion = SesionTranscripcion.objects.create(nombre='Grabación jornada A', jornada=self.jornada_a)

        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.get(f'/api/admin/transcripciones/{sesion.slug}/')
        self.assertEqual(resp.status_code, 200)

        self.client.force_authenticate(user=self.dependencia_b)
        resp = self.client.get(f'/api/admin/transcripciones/{sesion.slug}/')
        self.assertEqual(resp.status_code, 404)

    def test_dependencia_no_puede_vincular_a_jornada_ajena(self):
        from jornadas.models import Jornada

        jornada_ajena = Jornada.objects.create(
            slug='jornada-ajena', nombre='Ajena', fecha_inicio='2026-09-01', fecha_fin='2026-09-02',
        )
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post(
            '/api/admin/transcripciones/', {'nombre': 'Intento', 'jornada': jornada_ajena.id}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_dependencia_puede_crear_vinculada_a_su_jornada_sin_forzar_encargados(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post(
            '/api/admin/transcripciones/', {'nombre': 'Vinculada', 'jornada': self.jornada_a.id}, format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        sesion = SesionTranscripcion.objects.get(slug=resp.data['slug'])
        self.assertEqual(sesion.jornada_id, self.jornada_a.id)
        self.assertEqual(list(sesion.encargados.all()), [])

    def test_desvincular_de_jornada_deja_al_usuario_como_encargado(self):
        sesion = SesionTranscripcion.objects.create(nombre='Para desvincular', jornada=self.jornada_a)
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.patch(f'/api/admin/transcripciones/{sesion.slug}/', {'jornada': None}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        sesion.refresh_from_db()
        self.assertIsNone(sesion.jornada_id)
        self.assertEqual(list(sesion.encargados.all()), [self.dependencia_a])


class IngestaFragmentosTests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.sesion = crear_sesion('Sesion en curso')
        self.client.force_authenticate(user=self.admin)

    def _ingestar(self, fragmentos):
        return self.client.post(
            f'/api/admin/transcripciones/{self.sesion.slug}/fragmentos/',
            {'fragmentos': fragmentos}, format='json',
        )

    def test_ingesta_crea_fragmentos_en_orden(self):
        resp = self._ingestar([
            {'secuencia': 0, 'texto': 'Hola a todos.'},
            {'secuencia': 1, 'texto': 'Empecemos la reunión.', 'hablante': 'Ana'},
        ])
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(FragmentoTranscripcion.objects.filter(sesion=self.sesion).count(), 2)

    def test_reenviar_misma_secuencia_no_duplica_y_actualiza_texto(self):
        self._ingestar([{'secuencia': 0, 'texto': 'texto con error de transcripción'}])
        resp = self._ingestar([{'secuencia': 0, 'texto': 'texto correcto'}])
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(FragmentoTranscripcion.objects.filter(sesion=self.sesion).count(), 1)
        fragmento = FragmentoTranscripcion.objects.get(sesion=self.sesion, secuencia=0)
        self.assertEqual(fragmento.texto, 'texto correcto')

    def test_no_acepta_fragmentos_de_sesion_cerrada(self):
        self.sesion.estado = SesionTranscripcion.CERRADA
        self.sesion.save(update_fields=['estado'])
        resp = self._ingestar([{'secuencia': 0, 'texto': 'demasiado tarde'}])
        self.assertEqual(resp.status_code, 400)


class CerrarYRevisionTests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.sesion = crear_sesion('Sesion a cerrar')
        FragmentoTranscripcion.objects.create(sesion=self.sesion, secuencia=0, texto='Primero.')
        FragmentoTranscripcion.objects.create(sesion=self.sesion, secuencia=1, texto='Segundo.', hablante='Ana')
        self.client.force_authenticate(user=self.admin)

    def test_cerrar_marca_estado_y_fecha(self):
        resp = self.client.post(f'/api/admin/transcripciones/{self.sesion.slug}/cerrar/')
        self.assertEqual(resp.status_code, 200)
        self.sesion.refresh_from_db()
        self.assertEqual(self.sesion.estado, SesionTranscripcion.CERRADA)
        self.assertIsNotNone(self.sesion.cerrada_en)

    def test_no_se_puede_cerrar_dos_veces(self):
        self.client.post(f'/api/admin/transcripciones/{self.sesion.slug}/cerrar/')
        resp = self.client.post(f'/api/admin/transcripciones/{self.sesion.slug}/cerrar/')
        self.assertEqual(resp.status_code, 400)

    def test_transcripcion_reconstruida_respeta_el_orden(self):
        resp = self.client.get(f'/api/admin/transcripciones/{self.sesion.slug}/transcripcion/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['texto_completo'], 'Primero.\n[Ana] Segundo.')

    def test_no_se_puede_editar_fragmento_mientras_esta_en_curso(self):
        fragmento = self.sesion.fragmentos.get(secuencia=0)
        resp = self.client.patch(
            f'/api/admin/transcripcion-fragmentos/{fragmento.id}/', {'texto': 'corregido'}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_editar_y_borrar_fragmento_una_vez_cerrada(self):
        self.client.post(f'/api/admin/transcripciones/{self.sesion.slug}/cerrar/')
        fragmento = self.sesion.fragmentos.get(secuencia=0)

        resp = self.client.patch(
            f'/api/admin/transcripcion-fragmentos/{fragmento.id}/', {'texto': 'corregido'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        fragmento.refresh_from_db()
        self.assertEqual(fragmento.texto, 'corregido')

        otro = self.sesion.fragmentos.get(secuencia=1)
        resp = self.client.delete(f'/api/admin/transcripcion-fragmentos/{otro.id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(FragmentoTranscripcion.objects.filter(id=otro.id).exists())


class InformeTranscripcionScopingTests(APITestCase):
    """Mismo patrón que AnalisisJornadaIAScopingTests en analitica/tests.py: los informes se
    crean directo por ORM en estado ya resuelto para no disparar el hilo de fondo real (que
    llamaría a OpenAI) — acá solo se prueban los guards de la vista."""

    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dependencia_a = crear_dependencia('dependencia_a')
        self.sesion_a = crear_sesion(
            'Sesion A', encargado=self.dependencia_a, estado=SesionTranscripcion.CERRADA,
        )
        self.sesion_b = crear_sesion('Sesion B', estado=SesionTranscripcion.CERRADA)
        self.sesion_en_curso = crear_sesion(
            'Sesion en curso', encargado=self.dependencia_a, estado=SesionTranscripcion.EN_CURSO,
        )

    def test_no_se_puede_pedir_informe_de_sesion_en_curso(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post(
            '/api/admin/transcripcion-informes/', {'sesion': self.sesion_en_curso.id}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_dependencia_no_puede_pedir_informe_de_sesion_ajena(self):
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post(
            '/api/admin/transcripcion-informes/', {'sesion': self.sesion_b.id}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_no_deja_pedir_dos_informes_a_la_vez_para_la_misma_sesion(self):
        InformeTranscripcion.objects.create(sesion=self.sesion_a, estado=InformeTranscripcion.ESTADO_PROCESANDO)
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.post(
            '/api/admin/transcripcion-informes/', {'sesion': self.sesion_a.id}, format='json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_dependencia_solo_ve_informes_de_su_sesion(self):
        informe_a = InformeTranscripcion.objects.create(
            sesion=self.sesion_a, estado=InformeTranscripcion.ESTADO_COMPLETO,
        )
        InformeTranscripcion.objects.create(sesion=self.sesion_b, estado=InformeTranscripcion.ESTADO_COMPLETO)
        self.client.force_authenticate(user=self.dependencia_a)
        resp = self.client.get('/api/admin/transcripcion-informes/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([i['id'] for i in resp.data], [informe_a.id])


class PdfInformeTests(APITestCase):
    """El PDF se arma 100% en el servidor con reportlab, sin llamar a OpenAI — se puede probar
    completo sin mocks, igual que el resto del pipeline determinístico del proyecto."""

    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.sesion = crear_sesion('Sesion con informe', estado=SesionTranscripcion.CERRADA)
        FragmentoTranscripcion.objects.create(sesion=self.sesion, secuencia=0, texto='Hola.', hablante='Ana')
        self.informe = InformeTranscripcion.objects.create(
            sesion=self.sesion,
            estado=InformeTranscripcion.ESTADO_COMPLETO,
            resultado={
                'resumen_ejecutivo': 'Resumen de prueba.',
                'temas_discutidos': ['presupuesto', 'cronograma'],
                'hallazgos': [
                    {'titulo': 'Hallazgo 1', 'descripcion': 'Descripción del hallazgo.', 'citas': ['una cita real']},
                ],
            },
        )
        self.client.force_authenticate(user=self.admin)

    def test_pdf_de_informe_completo_responde_pdf_valido(self):
        resp = self.client.get(f'/api/admin/transcripcion-informes/{self.informe.id}/pdf/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_pdf_de_informe_no_completo_falla(self):
        self.informe.estado = InformeTranscripcion.ESTADO_PENDIENTE
        self.informe.save(update_fields=['estado'])
        resp = self.client.get(f'/api/admin/transcripcion-informes/{self.informe.id}/pdf/')
        self.assertEqual(resp.status_code, 400)


class InformeIAHelpersTests(APITestCase):
    """Funciones puras de transcripciones/informe_ia.py — sin red, deterministas."""

    def test_particionar_respeta_presupuesto_de_palabras(self):
        class FragmentoFalso:
            def __init__(self, texto):
                self.texto = texto

        fragmentos = [FragmentoFalso('palabra ' * 100) for _ in range(int(PALABRAS_POR_TRAMO / 100) + 5)]
        tramos = _particionar_en_tramos(fragmentos)
        self.assertGreater(len(tramos), 1)
        for tramo in tramos:
            total_palabras = sum(len(f.texto.split()) for f in tramo)
            self.assertLessEqual(total_palabras, PALABRAS_POR_TRAMO + 100)

    def test_particionar_no_parte_un_fragmento_a_la_mitad(self):
        class FragmentoFalso:
            def __init__(self, texto):
                self.texto = texto

        fragmentos = [FragmentoFalso('una sola línea larga ' * 50)]
        tramos = _particionar_en_tramos(fragmentos)
        self.assertEqual(len(tramos), 1)
        self.assertEqual(tramos[0], fragmentos)

    def test_limpiar_texto_quita_etiquetas_de_estructura(self):
        self.assertEqual(_limpiar_texto('Hallazgo: el equipo llegó a un acuerdo.'), 'el equipo llegó a un acuerdo.')
        self.assertEqual(_limpiar_texto('(1) Se discutió el presupuesto.'), 'Se discutió el presupuesto.')
        self.assertEqual(_limpiar_texto(''), '')
