"""Banco de instrumentos (plantillas de Momento) — ver docs/banco_instrumentos/*.md.

Dos clases: `CopiarMomentoTests` prueba `jornadas.banco.copiar_momento` directo, sin pasar por la
API (Fase 2). `BancoMomentoAPITests` prueba los endpoints `/api/admin/banco-momentos/**` y, de
paso, los campos nuevos en `/api/admin/momentos/` (Fase 1/3). Los nombres de los tests llevan el
id del caso de docs/banco_instrumentos/04_flujos_y_casos.md §4 donde aplica.
"""
from rest_framework.test import APITestCase

from .banco import copiar_momento
from .models import Momento, OpcionPregunta, Pregunta, RolJornada
from .tests import crear_admin_completo, crear_dependencia, crear_jornada


def _crear_momento(jornada, **kwargs):
    kwargs.setdefault('orden', 1)
    kwargs.setdefault('titulo', 'Momento')
    kwargs.setdefault('tipo', Momento.TIPO_INDIVIDUAL)
    return Momento.objects.create(jornada=jornada, **kwargs)


class CopiarMomentoTests(APITestCase):
    """jornadas.banco.copiar_momento — sin pasar por la API. Ver
    docs/banco_instrumentos/03_modelo_de_datos.md §4 para el algoritmo que se está probando."""

    def setUp(self):
        self.dep_a = crear_dependencia('dep_a')
        self.dep_b = crear_dependencia('dep_b')
        self.jornada_a = crear_jornada('jornada-a', propietario=self.dep_a)
        self.jornada_b = crear_jornada('jornada-b', propietario=self.dep_b)

    def test_u02_usar_el_mismo_publico_dos_veces_en_la_misma_jornada(self):
        origen = _crear_momento(
            self.jornada_a, titulo='Diagnóstico', visibilidad=Momento.VISIBILIDAD_PUBLICO,
        )
        copia1, advertencias1 = copiar_momento(origen, self.jornada_b, self.dep_b)
        copia2, advertencias2 = copiar_momento(origen, self.jornada_b, self.dep_b)
        self.assertEqual(advertencias1, [])
        self.assertEqual(advertencias2, [])
        self.assertEqual(copia2.orden, copia1.orden + 1)
        self.assertEqual(copia1.slug, 'diagnostico')
        self.assertEqual(copia2.slug, 'diagnostico-2')

    def test_u04_usar_mi_propio_momento_en_la_misma_jornada_duplicar(self):
        origen = _crear_momento(self.jornada_a, titulo='Bienvenida')
        copia, advertencias = copiar_momento(origen, self.jornada_a, self.dep_a)
        self.assertEqual(advertencias, [])
        self.assertEqual(copia.orden, 2)
        self.assertEqual(copia.slug, 'bienvenida-2')
        self.assertNotEqual(copia.id, origen.id)

    def test_u13_preguntas_inactivas_se_copian_conservando_activa_false(self):
        origen = _crear_momento(self.jornada_a)
        Pregunta.objects.create(momento=origen, tipo=Pregunta.TIPO_ABIERTA, texto='Activa', orden=1, activa=True)
        Pregunta.objects.create(momento=origen, tipo=Pregunta.TIPO_ABIERTA, texto='Inactiva', orden=2, activa=False)
        copia, _ = copiar_momento(origen, self.jornada_b, self.dep_b)
        preguntas = list(copia.preguntas.order_by('orden'))
        self.assertEqual(len(preguntas), 2)
        self.assertTrue(preguntas[0].activa)
        self.assertFalse(preguntas[1].activa)

    def test_u14_depende_de_opcion_interna_se_remapea_incluida_pregunta_inactiva(self):
        origen = _crear_momento(self.jornada_a)
        p1 = Pregunta.objects.create(momento=origen, tipo=Pregunta.TIPO_UNICA, texto='P1', orden=1, activa=False)
        o1 = OpcionPregunta.objects.create(pregunta=p1, texto='Sí', orden=1)
        Pregunta.objects.create(
            momento=origen, tipo=Pregunta.TIPO_ABIERTA, texto='P2', orden=2, depende_de_opcion=o1,
        )
        copia, advertencias = copiar_momento(origen, self.jornada_b, self.dep_b)
        self.assertEqual(advertencias, [])
        p1_copia = copia.preguntas.get(texto='P1')
        p2_copia = copia.preguntas.get(texto='P2')
        self.assertIsNotNone(p2_copia.depende_de_opcion_id)
        self.assertNotEqual(p2_copia.depende_de_opcion_id, o1.id)
        self.assertEqual(p2_copia.depende_de_opcion.pregunta_id, p1_copia.id)
        self.assertFalse(p1_copia.activa)

    def test_u15_dependencia_a_opcion_de_otro_momento_se_anula_con_advertencia(self):
        momento_a = _crear_momento(self.jornada_a, titulo='A', orden=1)
        momento_b = _crear_momento(self.jornada_a, titulo='B', orden=2)
        pa = Pregunta.objects.create(momento=momento_a, tipo=Pregunta.TIPO_UNICA, texto='PA', orden=1)
        oa = OpcionPregunta.objects.create(pregunta=pa, texto='Sí', orden=1)
        Pregunta.objects.create(
            momento=momento_b, tipo=Pregunta.TIPO_ABIERTA, texto='PB', orden=1, depende_de_opcion=oa,
        )
        copia, advertencias = copiar_momento(momento_b, self.jornada_b, self.dep_b)
        pb_copia = copia.preguntas.get(texto='PB')
        self.assertIsNone(pb_copia.depende_de_opcion_id)
        self.assertEqual(len(advertencias), 1)
        self.assertIn('PB', advertencias[0])

    def test_u17_roles_permitidos_inexistentes_en_destino_generan_advertencia(self):
        origen = _crear_momento(self.jornada_a, roles_permitidos=['Decano'])
        Pregunta.objects.create(
            momento=origen, tipo=Pregunta.TIPO_ABIERTA, texto='P', orden=1,
            roles_permitidos=['Jefe de programa'],
        )
        copia, advertencias = copiar_momento(origen, self.jornada_b, self.dep_b)
        self.assertEqual(copia.roles_permitidos, ['Decano'])
        self.assertEqual(len(advertencias), 1)
        self.assertIn('Decano', advertencias[0])
        self.assertIn('Jefe de programa', advertencias[0])

    def test_u17b_roles_permitidos_que_existen_en_destino_no_generan_advertencia(self):
        RolJornada.objects.create(jornada=self.jornada_b, nombre='Docente')
        origen = _crear_momento(self.jornada_a, roles_permitidos=['Docente'])
        _, advertencias = copiar_momento(origen, self.jornada_b, self.dep_b)
        self.assertEqual(advertencias, [])

    def test_u18_mesas_permitidas_se_copian_tal_cual_sin_advertencia(self):
        origen = _crear_momento(self.jornada_a, tipo=Momento.TIPO_MESA, mesas_permitidas=[1, 2, 3])
        copia, advertencias = copiar_momento(origen, self.jornada_b, self.dep_b)
        self.assertEqual(copia.mesas_permitidas, [1, 2, 3])
        self.assertEqual(advertencias, [])

    def test_u20_permite_carga_archivo_se_copia(self):
        origen = _crear_momento(self.jornada_a, permite_carga_archivo=True)
        copia, _ = copiar_momento(origen, self.jornada_b, self.dep_b)
        self.assertTrue(copia.permite_carga_archivo)

    def test_u21_datos_de_ejecucion_no_se_copian(self):
        from participantes.models import Respuesta

        origen = _crear_momento(self.jornada_a)
        pregunta = Pregunta.objects.create(momento=origen, tipo=Pregunta.TIPO_ABIERTA, texto='P', orden=1)
        Respuesta.objects.create(pregunta=pregunta, texto_libre='algo')
        copia, _ = copiar_momento(origen, self.jornada_b, self.dep_b)
        pregunta_copia = copia.preguntas.get(texto='P')
        self.assertEqual(Respuesta.objects.filter(pregunta=pregunta_copia).count(), 0)
        self.assertEqual(Respuesta.objects.filter(pregunta=pregunta).count(), 1)

    def test_u24_origen_con_cero_preguntas(self):
        origen = _crear_momento(self.jornada_a, titulo='Vacío')
        copia, advertencias = copiar_momento(origen, self.jornada_b, self.dep_b)
        self.assertEqual(advertencias, [])
        self.assertEqual(copia.preguntas.count(), 0)

    def test_u25_copiar_una_copia_apunta_al_intermedio_no_al_abuelo(self):
        abuelo = _crear_momento(self.jornada_a, titulo='Abuelo')
        intermedio, _ = copiar_momento(abuelo, self.jornada_b, self.dep_b)
        nieto, _ = copiar_momento(intermedio, self.jornada_b, self.dep_b)
        self.assertEqual(nieto.momento_origen_id, intermedio.id)
        self.assertNotEqual(nieto.momento_origen_id, abuelo.id)
        self.assertEqual(nieto.origen_info['momento_id'], intermedio.id)

    def test_u27_editar_la_copia_no_afecta_al_original(self):
        origen = _crear_momento(self.jornada_a)
        copia, _ = copiar_momento(origen, self.jornada_b, self.dep_b)
        copia.titulo = 'Adaptado'
        copia.save(update_fields=['titulo'])
        origen.refresh_from_db()
        self.assertEqual(origen.titulo, 'Momento')

    def test_u28_editar_el_original_no_afecta_a_la_copia(self):
        origen = _crear_momento(self.jornada_a)
        copia, _ = copiar_momento(origen, self.jornada_b, self.dep_b)
        origen.titulo = 'Editado'
        origen.save(update_fields=['titulo'])
        copia.refresh_from_db()
        self.assertEqual(copia.titulo, 'Momento')

    def test_u29_borrar_el_original_deja_momento_origen_null_y_conserva_origen_info(self):
        origen = _crear_momento(self.jornada_a)
        copia, _ = copiar_momento(origen, self.jornada_b, self.dep_b)
        origen_info_antes = dict(copia.origen_info)
        origen.delete()
        copia.refresh_from_db()
        self.assertIsNone(copia.momento_origen_id)
        self.assertEqual(copia.origen_info, origen_info_antes)

    def test_u31_borrar_la_copia_no_afecta_al_original_y_baja_veces_usado(self):
        origen = _crear_momento(self.jornada_a)
        copia, _ = copiar_momento(origen, self.jornada_b, self.dep_b)
        self.assertEqual(origen.momentos_derivados.count(), 1)
        copia.delete()
        self.assertTrue(Momento.objects.filter(pk=origen.pk).exists())
        self.assertEqual(origen.momentos_derivados.count(), 0)


class BancoMomentoAPITests(APITestCase):
    """`/api/admin/banco-momentos/**` y los campos nuevos de `/api/admin/momentos/`. Incluye la
    matriz de permisos de docs/banco_instrumentos/04_flujos_y_casos.md §3 (un test por celda
    relevante, con nombres `test_matriz_*`)."""

    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dep_a = crear_dependencia('dep_a')
        self.dep_b = crear_dependencia('dep_b')
        self.jornada_a = crear_jornada('jornada-a', propietario=self.dep_a)
        self.jornada_b = crear_jornada('jornada-b', propietario=self.dep_b)

        self.momento_a_privado = _crear_momento(self.jornada_a, titulo='Mío privado', orden=1)
        self.momento_a_publico = _crear_momento(
            self.jornada_a, titulo='Mío público', orden=2, visibilidad=Momento.VISIBILIDAD_PUBLICO,
        )
        self.momento_b_privado = _crear_momento(self.jornada_b, titulo='Ajeno privado', orden=1)
        self.momento_b_publico = _crear_momento(
            self.jornada_b, titulo='Ajeno público', orden=2, visibilidad=Momento.VISIBILIDAD_PUBLICO,
        )

    # -- Exploración del banco (B0x) -----------------------------------------------------------

    def test_b01_dependencia_lista_publicos_de_cualquiera_union_jornadas_propias(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.get('/api/admin/banco-momentos/')
        self.assertEqual(resp.status_code, 200)
        ids = {item['id'] for item in resp.data}
        self.assertEqual(ids, {
            self.momento_a_privado.id, self.momento_a_publico.id, self.momento_b_publico.id,
        })
        self.assertNotIn(self.momento_b_privado.id, ids)

    def test_b01b_sin_duplicados_cuando_la_jornada_tiene_varios_propietarios(self):
        compartida = crear_jornada('jornada-compartida', propietarios=[self.dep_a, self.dep_b])
        momento = _crear_momento(compartida, titulo='Compartido')
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.get('/api/admin/banco-momentos/')
        ids = [item['id'] for item in resp.data]
        self.assertEqual(ids.count(momento.id), 1)

    def test_b02_admin_lista_todos_incluidos_privados_ajenos(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get('/api/admin/banco-momentos/')
        self.assertEqual(resp.status_code, 200)
        ids = {item['id'] for item in resp.data}
        self.assertEqual(ids, {
            self.momento_a_privado.id, self.momento_a_publico.id,
            self.momento_b_privado.id, self.momento_b_publico.id,
        })

    def test_b02b_incluir_inactivos_quita_el_filtro_de_activo_para_cualquiera(self):
        self.momento_a_privado.activo = False
        self.momento_a_privado.save(update_fields=['activo'])
        self.client.force_authenticate(user=self.admin)
        resp_sin_flag = self.client.get('/api/admin/banco-momentos/')
        resp_con_flag = self.client.get('/api/admin/banco-momentos/?incluir_inactivos=1')
        ids_sin_flag = {item['id'] for item in resp_sin_flag.data}
        ids_con_flag = {item['id'] for item in resp_con_flag.data}
        self.assertNotIn(self.momento_a_privado.id, ids_sin_flag)
        self.assertIn(self.momento_a_privado.id, ids_con_flag)

    def test_b03_alcance_mios_solo_jornadas_propias_cualquier_visibilidad(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.get('/api/admin/banco-momentos/?alcance=mios')
        ids = {item['id'] for item in resp.data}
        self.assertEqual(ids, {self.momento_a_privado.id, self.momento_a_publico.id})

    def test_b04_alcance_publicos_solo_visibilidad_publico(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.get('/api/admin/banco-momentos/?alcance=publicos')
        ids = {item['id'] for item in resp.data}
        self.assertEqual(ids, {self.momento_a_publico.id, self.momento_b_publico.id})

    def test_b05_busqueda_por_texto_icontains_en_titulo_y_contexto(self):
        _crear_momento(self.jornada_a, titulo='Diagnóstico institucional', orden=3)
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.get('/api/admin/banco-momentos/?q=diagn')
        titulos = {item['titulo'] for item in resp.data}
        self.assertEqual(titulos, {'Diagnóstico institucional'})

    def test_b06_filtro_por_tipo_exacto(self):
        _crear_momento(self.jornada_a, titulo='De mesa', orden=3, tipo=Momento.TIPO_MESA)
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.get('/api/admin/banco-momentos/?tipo=mesa')
        titulos = {item['titulo'] for item in resp.data}
        self.assertEqual(titulos, {'De mesa'})

    def test_b08_solo_originales_excluye_copias(self):
        copia, _ = copiar_momento(self.momento_a_publico, self.jornada_a, self.dep_a)
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.get('/api/admin/banco-momentos/?solo_originales=1')
        ids = {item['id'] for item in resp.data}
        self.assertNotIn(copia.id, ids)
        self.assertIn(self.momento_a_publico.id, ids)

    def test_b09_detalle_de_privado_ajeno_da_404(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.get(f'/api/admin/banco-momentos/{self.momento_b_privado.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_b10_detalle_de_momento_inactivo_visible_da_200(self):
        self.momento_a_publico.activo = False
        self.momento_a_publico.save(update_fields=['activo'])
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.get(f'/api/admin/banco-momentos/{self.momento_a_publico.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['activo'])

    def test_b10b_incluir_inactivos_en_el_listado(self):
        self.momento_a_publico.activo = False
        self.momento_a_publico.save(update_fields=['activo'])
        self.client.force_authenticate(user=self.dep_a)
        sin_flag = self.client.get('/api/admin/banco-momentos/')
        con_flag = self.client.get('/api/admin/banco-momentos/?incluir_inactivos=1')
        self.assertNotIn(self.momento_a_publico.id, {i['id'] for i in sin_flag.data})
        self.assertIn(self.momento_a_publico.id, {i['id'] for i in con_flag.data})

    def test_b15_participante_recibe_403_limpio(self):
        from participantes.models import Participante

        participante = Participante.objects.create(
            jornada=self.jornada_a, correo_institucional='p@x.com', nombre='P', apellido='X', rol='estudiante',
        )
        self.client.force_authenticate(user=participante)
        resp = self.client.get('/api/admin/banco-momentos/')
        self.assertEqual(resp.status_code, 403)

    # -- Uso como plantilla (U0x) ---------------------------------------------------------------

    def test_u01_usar_publico_ajeno_en_jornada_mia(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.post(
            f'/api/admin/banco-momentos/{self.momento_b_publico.id}/usar/', {'jornada': self.jornada_a.id},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        momento = resp.data['momento']
        self.assertEqual(momento['momento_origen'], self.momento_b_publico.id)
        self.assertEqual(momento['creado_por']['id'], self.dep_a.id)
        self.assertEqual(momento['visibilidad'], Momento.VISIBILIDAD_PRIVADO)
        self.assertEqual(resp.data['advertencias'], [])

    def test_u03_usar_mi_propio_momento_en_otra_jornada_mia(self):
        otra_jornada_a = crear_jornada('jornada-a2', propietario=self.dep_a)
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.post(
            f'/api/admin/banco-momentos/{self.momento_a_privado.id}/usar/', {'jornada': otra_jornada_a.id},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_u05_jornada_ajena_en_el_body_da_403(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.post(
            f'/api/admin/banco-momentos/{self.momento_a_publico.id}/usar/', {'jornada': self.jornada_b.id},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data['detail'], 'Esta jornada no te pertenece.')

    def test_u06_jornada_inexistente_en_el_body_da_400(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.post(
            f'/api/admin/banco-momentos/{self.momento_a_publico.id}/usar/', {'jornada': 999999},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('jornada', resp.data)

    def test_u07_origen_privado_ajeno_da_404(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.post(
            f'/api/admin/banco-momentos/{self.momento_b_privado.id}/usar/', {'jornada': self.jornada_a.id},
            format='json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_u08_origen_inactivo_visible_se_puede_usar_y_la_copia_nace_activa(self):
        self.momento_a_publico.activo = False
        self.momento_a_publico.save(update_fields=['activo'])
        self.client.force_authenticate(user=self.dep_b)
        resp = self.client.post(
            f'/api/admin/banco-momentos/{self.momento_a_publico.id}/usar/', {'jornada': self.jornada_b.id},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.data['momento']['activo'])

    def test_u09_orden_explicito_ocupado_da_400(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.post(
            f'/api/admin/banco-momentos/{self.momento_b_publico.id}/usar/',
            {'jornada': self.jornada_a.id, 'orden': self.momento_a_privado.orden},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('orden', resp.data)

    def test_u11_titulo_override_genera_slug_a_partir_de_el(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.post(
            f'/api/admin/banco-momentos/{self.momento_b_publico.id}/usar/',
            {'jornada': self.jornada_a.id, 'titulo': 'Diagnóstico — sede norte'},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['momento']['titulo'], 'Diagnóstico — sede norte')
        self.assertEqual(resp.data['momento']['slug'], 'diagnostico-sede-norte')

    def test_u12_visibilidad_publico_en_el_body_nace_publica(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.post(
            f'/api/admin/banco-momentos/{self.momento_b_publico.id}/usar/',
            {'jornada': self.jornada_a.id, 'visibilidad': Momento.VISIBILIDAD_PUBLICO},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['momento']['visibilidad'], Momento.VISIBILIDAD_PUBLICO)

    def test_u26_admin_usa_privado_ajeno_en_jornada_de_un_tercero(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f'/api/admin/banco-momentos/{self.momento_b_privado.id}/usar/', {'jornada': self.jornada_a.id},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['momento']['creado_por']['id'], self.admin.id)

    # -- Trazabilidad (T0x) -----------------------------------------------------------------

    def test_t01_momento_de_una_copia_incluye_momento_origen_y_origen_info(self):
        copia, _ = copiar_momento(self.momento_a_publico, self.jornada_b, self.dep_b)
        self.client.force_authenticate(user=self.dep_b)
        resp = self.client.get(f'/api/admin/momentos/{copia.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['momento_origen'], self.momento_a_publico.id)
        self.assertEqual(resp.data['origen_info']['momento_id'], self.momento_a_publico.id)

    def test_t02_momento_desde_cero_no_tiene_origen(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.get(f'/api/admin/momentos/{self.momento_a_privado.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data['momento_origen'])
        self.assertEqual(resp.data['origen_info'], {})

    def test_t03_derivados_como_dependencia_solo_los_de_mis_jornadas(self):
        copia_mia, _ = copiar_momento(self.momento_a_publico, self.jornada_a, self.dep_a)
        copia_ajena, _ = copiar_momento(self.momento_a_publico, self.jornada_b, self.dep_b)
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.get(f'/api/admin/banco-momentos/{self.momento_a_publico.id}/derivados/')
        self.assertEqual(resp.status_code, 200)
        ids = {item['id'] for item in resp.data}
        self.assertEqual(ids, {copia_mia.id})
        self.assertNotIn(copia_ajena.id, ids)

    def test_t04_derivados_como_admin_todos(self):
        copia_a, _ = copiar_momento(self.momento_a_publico, self.jornada_a, self.dep_a)
        copia_b, _ = copiar_momento(self.momento_a_publico, self.jornada_b, self.dep_b)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(f'/api/admin/banco-momentos/{self.momento_a_publico.id}/derivados/')
        ids = {item['id'] for item in resp.data}
        self.assertEqual(ids, {copia_a.id, copia_b.id})

    def test_t05_veces_usado_cuenta_todas_las_copias_sin_filtrar_por_visibilidad(self):
        copiar_momento(self.momento_a_publico, self.jornada_a, self.dep_a)
        copiar_momento(
            self.momento_a_publico, self.jornada_b, self.dep_b,
            visibilidad=Momento.VISIBILIDAD_PUBLICO,
        )
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.get('/api/admin/banco-momentos/')
        item = next(i for i in resp.data if i['id'] == self.momento_a_publico.id)
        self.assertEqual(item['veces_usado'], 2)

    # -- Creación y visibilidad (C0x) --------------------------------------------------------

    def test_c01_crear_momento_sin_visibilidad_nace_privado(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.post('/api/admin/momentos/', {
            'jornada': self.jornada_a.id, 'orden': 10, 'titulo': 'Nuevo', 'tipo': Momento.TIPO_INDIVIDUAL,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['visibilidad'], Momento.VISIBILIDAD_PRIVADO)

    def test_c03_crear_momento_con_visibilidad_invalida_da_400(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.post('/api/admin/momentos/', {
            'jornada': self.jornada_a.id, 'orden': 10, 'titulo': 'Nuevo', 'tipo': Momento.TIPO_INDIVIDUAL,
            'visibilidad': 'todos',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('visibilidad', resp.data)

    def test_c04_creado_por_y_momento_origen_en_el_body_se_ignoran(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.post('/api/admin/momentos/', {
            'jornada': self.jornada_a.id, 'orden': 10, 'titulo': 'Nuevo', 'tipo': Momento.TIPO_INDIVIDUAL,
            'creado_por': self.dep_b.id, 'momento_origen': self.momento_b_publico.id,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['creado_por']['id'], self.dep_a.id)
        self.assertIsNone(resp.data['momento_origen'])

    # -- Matriz de permisos (04_flujos_y_casos.md §3) ----------------------------------------

    def test_matriz_dependencia_edita_borra_y_republica_su_propio_momento(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.patch(
            f'/api/admin/momentos/{self.momento_a_privado.id}/', {'titulo': 'Editado'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        resp = self.client.patch(
            f'/api/admin/momentos/{self.momento_a_privado.id}/',
            {'visibilidad': Momento.VISIBILIDAD_PUBLICO}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete(f'/api/admin/momentos/{self.momento_a_privado.id}/')
        self.assertEqual(resp.status_code, 204)

    def test_matriz_dependencia_no_edita_ni_borra_momento_publico_ajeno(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.patch(
            f'/api/admin/momentos/{self.momento_b_publico.id}/', {'titulo': 'Intento'}, format='json',
        )
        self.assertEqual(resp.status_code, 404)
        resp = self.client.patch(
            f'/api/admin/momentos/{self.momento_b_publico.id}/',
            {'visibilidad': Momento.VISIBILIDAD_PRIVADO}, format='json',
        )
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete(f'/api/admin/momentos/{self.momento_b_publico.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_matriz_dependencia_no_edita_ni_borra_momento_privado_ajeno(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.patch(
            f'/api/admin/momentos/{self.momento_b_privado.id}/', {'titulo': 'Intento'}, format='json',
        )
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete(f'/api/admin/momentos/{self.momento_b_privado.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_matriz_dependencia_no_usa_momento_propio_ni_publico_ajeno_en_jornada_ajena(self):
        self.client.force_authenticate(user=self.dep_a)
        for origen_id in (self.momento_a_privado.id, self.momento_b_publico.id):
            resp = self.client.post(
                f'/api/admin/banco-momentos/{origen_id}/usar/', {'jornada': self.jornada_b.id}, format='json',
            )
            self.assertEqual(resp.status_code, 403)

    def test_matriz_dependencia_no_ve_derivados_de_un_privado_ajeno(self):
        self.client.force_authenticate(user=self.dep_a)
        resp = self.client.get(f'/api/admin/banco-momentos/{self.momento_b_privado.id}/derivados/')
        self.assertEqual(resp.status_code, 404)

    def test_matriz_admin_edita_cambia_visibilidad_y_borra_cualquier_momento(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.patch(
            f'/api/admin/momentos/{self.momento_b_privado.id}/', {'titulo': 'Editado por admin'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        resp = self.client.patch(
            f'/api/admin/momentos/{self.momento_b_privado.id}/',
            {'visibilidad': Momento.VISIBILIDAD_PUBLICO}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete(f'/api/admin/momentos/{self.momento_b_privado.id}/')
        self.assertEqual(resp.status_code, 204)

    def test_matriz_admin_usa_cualquier_momento_en_cualquier_jornada(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.post(
            f'/api/admin/banco-momentos/{self.momento_a_privado.id}/usar/', {'jornada': self.jornada_b.id},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_matriz_admin_ve_detalle_de_cualquier_privado(self):
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(f'/api/admin/banco-momentos/{self.momento_a_privado.id}/')
        self.assertEqual(resp.status_code, 200)
