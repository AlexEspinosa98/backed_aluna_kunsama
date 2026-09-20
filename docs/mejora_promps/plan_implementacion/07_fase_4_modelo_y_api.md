# 07 — Fase 4: modelo `AnalisisV2`, migración, API, lista unificada y tests

**Objetivo**: encender el flujo de punta a punta. Al terminar, `POST /api/admin/analisis-v2/`
crea el registro, lanza `procesar_analisis_v2` en background y el resultado v2 queda disponible
en `GET /api/admin/analisis-v2/{id}/` y en la lista unificada `GET /api/admin/analisis/`.

**Prerrequisitos**: fases 0–3.

**Archivos**: `analitica/models.py` (agregar modelo), `analitica/migrations/0017_analisis_v2.py`
(generada), `analitica/serializers.py` (agregar 4 serializers), `analitica/admin_views.py`
(agregar viewset + item en la lista unificada), `analitica/urls.py`, `analitica/admin.py`,
`analitica/tests_v2.py`.

## Paso 4.1 — Modelo (`analitica/models.py`)

Agregar el import al inicio del archivo (junto al de `prompt_comun`; `contrato.py` no importa
Django, así que no hay ciclo):

```python
from .v2.contrato import (
    MODO_CHOICES, MODO_INTEGRAL, MODO_POR_MOMENTO, PIPELINE_BERTOPIC_LLM, PIPELINE_CHOICES,
    PIPELINE_LLM,
)
```

Agregar la clase **al final del archivo** (después de `InfografiaImagen`):

```python
class AnalisisV2(models.Model):
    """Análisis con IA bajo el contrato `kunsamu.analisis/v2` (docs/mejora_promps/, plan en
    docs/mejora_promps/plan_implementacion/). Un modelo aparte de `Reporte`/`AnalisisMomentoIA`/
    `AnalisisJornadaIA` a propósito (D1 del plan): el frontend elige renderer por la `version` del
    resultado y conserva los visores históricos, y el contrato rompe la partición por alcance de
    los tres modelos legacy (un `por_momento` con varios momentos produce varios informes en UNA
    solicitud). Sin `enfoque`: el contrato lo elimina — el modelo decide el método por pregunta y
    lo declara en `naturaleza`/`metodos` de cada hallazgo.

    `entrada` es el sobre normalizado EXACTO que se le mandó al modelo, guardado antes de llamar y
    nunca recalculado: los JSON Pointers de citas y documentos BERTopic de `resultado` apuntan a
    índices de sus arrays. `resultado` solo se llena con una salida que pasó las dos capas de
    validación; lo descartado (salidas inválidas, errores, metadatos de las llamadas, notas del
    adaptador BERTopic) queda en `diagnostico` para auditoría."""
    MODO_INTEGRAL = MODO_INTEGRAL
    MODO_POR_MOMENTO = MODO_POR_MOMENTO
    PIPELINE_LLM = PIPELINE_LLM
    PIPELINE_BERTOPIC_LLM = PIPELINE_BERTOPIC_LLM

    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_PROCESANDO = 'procesando'
    ESTADO_COMPLETO = 'completo'
    ESTADO_ERROR = 'error'
    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, 'Pendiente'),
        (ESTADO_PROCESANDO, 'Procesando'),
        (ESTADO_COMPLETO, 'Completo'),
        (ESTADO_ERROR, 'Error'),
    ]

    jornada = models.ForeignKey(Jornada, on_delete=models.CASCADE, related_name='analisis_v2')
    momentos = models.ManyToManyField(Momento, blank=True, related_name='analisis_v2', help_text=(
        'Vacío en modo integral (el alcance es toda la jornada). En por_momento, los momentos '
        'elegidos — el orden efectivo es por Momento.orden.'
    ))
    modo = models.CharField(max_length=12, choices=MODO_CHOICES)
    pipeline = models.CharField(max_length=15, choices=PIPELINE_CHOICES, default=PIPELINE_LLM)
    contexto = models.TextField(blank=True, max_length=MAX_LARGO_TEXTO_LIBRE, help_text=(
        'Contexto general escrito por quien pide el análisis. Viaja como dato en '
        '`personalizacion.contexto_usuario`, nunca dentro del system prompt.'
    ))
    instrucciones = models.TextField(blank=True, max_length=MAX_LARGO_TEXTO_LIBRE, help_text=(
        'Instrucciones de quien pide el análisis (`personalizacion.instrucciones_usuario`). '
        'Ajustan énfasis y tono; el formato del informe es fijo por contrato.'
    ))
    personalizacion_momentos = models.JSONField(default=list, blank=True, help_text=(
        'Lista de {"momento": <id>, "contexto": "…", "instrucciones": "…"} — como máximo una '
        'entrada por momento del alcance.'
    ))
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    error_mensaje = models.TextField(blank=True)
    entrada = models.JSONField(default=dict, blank=True)
    resultado = models.JSONField(default=dict, blank=True, help_text='Salida kunsamu.analisis/v2 validada.')
    diagnostico = models.JSONField(default=dict, blank=True)
    version_prompt = models.CharField(max_length=40, blank=True)
    version_esquema = models.CharField(max_length=40, blank=True)
    prompt_usado = models.TextField(blank=True)
    modelo_usado = models.CharField(max_length=60, blank=True)
    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='analisis_v2_solicitados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    completado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Análisis v2 (contrato kunsamu.analisis/v2)'
        verbose_name_plural = 'Análisis v2 (contrato kunsamu.analisis/v2)'

    def __str__(self):
        return f'Análisis v2 {self.id} · {self.jornada} · {self.modo} · {self.pipeline} · {self.estado}'
```

## Paso 4.2 — Migración

```bash
source .venv/bin/activate
python manage.py makemigrations analitica -n analisis_v2
```

Debe crear `analitica/migrations/0017_analisis_v2.py` con `CreateModel('AnalisisV2', …)` y las
dos relaciones. Abrirla y confirmar que `dependencies` apunta a
`('analitica', '0016_infografia_fija_analisis_exacto')`. Luego
`python manage.py makemigrations analitica --check --dry-run` → `No changes detected`.

## Paso 4.3 — Serializers (`analitica/serializers.py`)

Agregar a los imports: `AnalisisV2` en la lista de `.models`, y
`from .v2.contrato import VERSION`. Agregar al final del archivo:

```python
class PersonalizacionMomentoSerializer(serializers.Serializer):
    momento = serializers.PrimaryKeyRelatedField(queryset=Momento.objects.all())
    contexto = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=MAX_LARGO_TEXTO_LIBRE, trim_whitespace=False,
    )
    instrucciones = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=MAX_LARGO_TEXTO_LIBRE, trim_whitespace=False,
    )


class _AnalisisV2CamposDerivados(serializers.ModelSerializer):
    """Campos derivados comunes a la lectura de lista y de detalle."""
    jornada = serializers.SlugRelatedField(slug_field='slug', read_only=True)
    jornada_id = serializers.IntegerField(read_only=True)
    momentos = MomentoResumenSerializer(many=True, read_only=True)
    version = serializers.SerializerMethodField()
    metodo = serializers.SerializerMethodField()
    estado_analitico = serializers.SerializerMethodField()

    def get_version(self, obj):
        return VERSION

    def get_metodo(self, obj):
        # Para que la agrupación actual del panel (bertopic / openai) siga funcionando sin cambios.
        return 'bertopic' if obj.pipeline == AnalisisV2.PIPELINE_BERTOPIC_LLM else 'openai'

    def get_estado_analitico(self, obj):
        return (obj.resultado or {}).get('estado')


class AnalisisV2ListaSerializer(_AnalisisV2CamposDerivados):
    """Sin `entrada`, `resultado`, `diagnostico` ni `prompt_usado`: la entrada contiene el corpus
    completo y el resultado puede pesar cientos de KB — en un listado que el panel consulta cada
    pocos segundos sería un desperdicio. El detalle (`retrieve`) sí trae todo."""
    class Meta:
        model = AnalisisV2
        fields = [
            'id', 'version', 'jornada', 'jornada_id', 'momentos', 'modo', 'pipeline', 'metodo',
            'contexto', 'instrucciones', 'personalizacion_momentos', 'estado', 'estado_analitico',
            'error_mensaje', 'version_prompt', 'version_esquema', 'modelo_usado', 'solicitado_por',
            'creado_en', 'actualizado_en', 'completado_en',
        ]
        read_only_fields = fields


class AnalisisV2Serializer(_AnalisisV2CamposDerivados):
    class Meta:
        model = AnalisisV2
        fields = AnalisisV2ListaSerializer.Meta.fields + ['resultado', 'entrada', 'diagnostico', 'prompt_usado']
        read_only_fields = fields


class AnalisisV2CrearSerializer(serializers.ModelSerializer):
    momentos = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Momento.objects.all(), required=False,
        help_text='Obligatorio y no vacío en por_momento; no se acepta en integral.',
    )
    personalizacion_momentos = PersonalizacionMomentoSerializer(many=True, required=False)

    class Meta:
        model = AnalisisV2
        fields = [
            'id', 'jornada', 'modo', 'pipeline', 'momentos', 'contexto', 'instrucciones',
            'personalizacion_momentos', 'estado', 'creado_en',
        ]
        read_only_fields = ['id', 'estado', 'creado_en']

    def validate(self, attrs):
        jornada = attrs['jornada']
        modo = attrs['modo']
        momentos = attrs.get('momentos') or []
        for momento in momentos:
            if momento.jornada_id != jornada.id:
                raise serializers.ValidationError(
                    {'momentos': f'El momento "{momento.titulo}" no pertenece a la jornada seleccionada.'}
                )
        if modo == AnalisisV2.MODO_INTEGRAL and momentos:
            raise serializers.ValidationError(
                {'momentos': 'En modo integral no se mandan momentos: el alcance es toda la jornada.'}
            )
        if modo == AnalisisV2.MODO_POR_MOMENTO:
            if not momentos:
                raise serializers.ValidationError({'momentos': 'En modo por_momento hay que indicar al menos un momento.'})
            if len({m.id for m in momentos}) != len(momentos):
                raise serializers.ValidationError({'momentos': 'Hay momentos repetidos.'})

        if modo == AnalisisV2.MODO_POR_MOMENTO:
            alcance_ids = {m.id for m in momentos}
        else:
            alcance_ids = set(jornada.momentos.values_list('id', flat=True))
        vistos = set()
        for item in attrs.get('personalizacion_momentos') or []:
            momento = item['momento']
            if momento.id not in alcance_ids:
                raise serializers.ValidationError(
                    {'personalizacion_momentos': f'El momento "{momento.titulo}" no está en el alcance del análisis.'}
                )
            if momento.id in vistos:
                raise serializers.ValidationError({'personalizacion_momentos': 'Un momento aparece más de una vez.'})
            vistos.add(momento.id)
        return attrs

    def create(self, validated_data):
        momentos = validated_data.pop('momentos', [])
        personalizacion = validated_data.pop('personalizacion_momentos', [])
        validated_data['personalizacion_momentos'] = [
            {
                'momento': item['momento'].id,
                'contexto': item.get('contexto') or '',
                'instrucciones': item.get('instrucciones') or '',
            }
            for item in personalizacion
        ]
        analisis = AnalisisV2.objects.create(**validated_data)
        if momentos:
            analisis.momentos.set(momentos)
        return analisis
```

## Paso 4.4 — ViewSet y lista unificada (`analitica/admin_views.py`)

Imports a agregar: `AnalisisV2` en la lista de `.models`; los tres serializers nuevos en la de
`.serializers` (`AnalisisV2CrearSerializer, AnalisisV2ListaSerializer, AnalisisV2Serializer`);
`from .v2.contrato import VERSION as VERSION_V2`; `from .v2.procesar import procesar_analisis_v2`.

Constante, junto a los otros umbrales:

```python
# La llamada v2 es una sola pero grande (salida de hasta ~24k tokens con un modelo de razonamiento)
# y en bertopic_llm va precedida de embeddings + clustering por pregunta — más margen que las vías
# legacy antes de dar por muerto al worker.
UMBRAL_HUERFANO_ANALISIS_V2 = timedelta(minutes=45)
```

ViewSet — colocarlo después de `AnalisisJornadaIAViewSet`:

```python
class AnalisisV2ViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Análisis bajo el contrato kunsamu.analisis/v2 (ver `AnalisisV2` en models.py y el plan en
    docs/mejora_promps/plan_implementacion/). Orden de guards en `create` (D4 del plan): 400 de
    forma → 403 de jornada ajena → sanar huérfanos → 409 si hay otro en curso con el MISMO alcance
    (jornada + modo + conjunto de momentos) → 400 si la jornada no tiene momentos. Sin guard de
    "sin respuestas": `sin_datos` es un estado analítico válido del contrato y lo produce el
    backend sin gastar una llamada (D11)."""
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = AnalisisV2.objects.select_related('jornada').prefetch_related('momentos')
        queryset = filtrar_por_propietario(queryset, self.request.user, 'jornada__propietarios')
        jornada_id = self.request.query_params.get('jornada')
        if jornada_id:
            queryset = queryset.filter(jornada_id=jornada_id)
        momento_id = self.request.query_params.get('momento')
        if momento_id:
            queryset = queryset.filter(momentos__id=momento_id).distinct()
        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return AnalisisV2CrearSerializer
        if self.action == 'list':
            return AnalisisV2ListaSerializer
        return AnalisisV2Serializer

    def create(self, request, *args, **kwargs):
        entrada = AnalisisV2CrearSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        jornada = entrada.validated_data['jornada']
        verificar_acceso_jornada(request.user, jornada)
        modo = entrada.validated_data['modo']
        momentos = entrada.validated_data.get('momentos') or []

        AnalisisV2.objects.filter(
            jornada=jornada,
            estado__in=[AnalisisV2.ESTADO_PENDIENTE, AnalisisV2.ESTADO_PROCESANDO],
            actualizado_en__lt=timezone.now() - UMBRAL_HUERFANO_ANALISIS_V2,
        ).update(
            estado=AnalisisV2.ESTADO_ERROR,
            error_mensaje='El análisis quedó procesando más de 45 minutos sin completarse '
                          '(probablemente el worker se reinició o falló) y se marcó como error '
                          'automáticamente.',
        )

        ids_alcance = {m.id for m in momentos}
        en_curso = AnalisisV2.objects.filter(
            jornada=jornada, modo=modo,
            estado__in=[AnalisisV2.ESTADO_PENDIENTE, AnalisisV2.ESTADO_PROCESANDO],
        ).prefetch_related('momentos')
        for otro in en_curso:
            if {m.id for m in otro.momentos.all()} == ids_alcance:
                return Response(
                    {'detail': 'Ya hay un análisis v2 en proceso para este mismo alcance — espera a '
                               'que termine (o falle) antes de pedir otro.'},
                    status=status.HTTP_409_CONFLICT,
                )

        if modo == AnalisisV2.MODO_INTEGRAL and not jornada.momentos.exists():
            return Response(
                {'jornada': ['La jornada no tiene momentos: no hay nada que analizar.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        analisis = entrada.save(solicitado_por=request.user)
        threading.Thread(target=procesar_analisis_v2, args=(analisis.id,), daemon=True).start()

        salida = AnalisisV2Serializer(analisis)
        headers = self.get_success_headers(salida.data)
        return Response(salida.data, status=status.HTTP_201_CREATED, headers=headers)
```

Lista unificada — agregar la función junto a `_item_analisis_jornada`:

```python
def _item_analisis_v2(analisis):
    momentos = list(analisis.momentos.all())
    momento = momentos[0] if len(momentos) == 1 else None
    if analisis.modo == AnalisisV2.MODO_INTEGRAL:
        alcance = 'jornada'
    else:
        alcance = 'momento' if len(momentos) == 1 else 'momentos'
    return {
        'tipo': 'analisis_v2',
        'id': analisis.id,
        'jornada': analisis.jornada_id,
        'momento': momento.id if momento else None,
        'momento_titulo': momento.titulo if momento else None,
        'momento_orden': momento.orden if momento else None,
        # Derivado del pipeline para que la agrupación actual del panel siga funcionando.
        'metodo': 'bertopic' if analisis.pipeline == AnalisisV2.PIPELINE_BERTOPIC_LLM else 'openai',
        'enfoque': None,
        'alcance': alcance,
        'estado': analisis.estado,
        'error_mensaje': analisis.error_mensaje,
        'creado_en': analisis.creado_en,
        'completado_en': analisis.completado_en,
        # Solo los items v2 traen estas cuatro claves: es lo que le dice al frontend qué renderer usar.
        'version': VERSION_V2,
        'modo': analisis.modo,
        'pipeline': analisis.pipeline,
        'estado_analitico': (analisis.resultado or {}).get('estado'),
    }
```

En `AnalisisUnificadoView.get`, **antes** de `items.sort(...)`, agregar:

```python
        analisis_v2 = filtrar_por_propietario(
            AnalisisV2.objects.select_related('jornada').prefetch_related('momentos'),
            request.user, 'jornada__propietarios',
        )
        if jornada_id:
            analisis_v2 = analisis_v2.filter(jornada_id=jornada_id)
        if momento_id:
            # Un v2 integral abarca todos los momentos pero no es "de" uno puntual — mismo criterio
            # que analisis_jornada: con ?momento= solo entran los por_momento que lo incluyen.
            analisis_v2 = analisis_v2.filter(momentos__id=momento_id).distinct()
        items.extend(_item_analisis_v2(a) for a in analisis_v2)
```

Actualizar el docstring de `AnalisisUnificadoView` para mencionar que también une `AnalisisV2`.

## Paso 4.5 — Rutas y admin

`analitica/urls.py`: agregar `AnalisisV2ViewSet` al import y
`router.register('analisis-v2', AnalisisV2ViewSet, basename='admin-analisis-v2')` después del
registro de `analisis-jornada-ia`.

`analitica/admin.py`: agregar `AnalisisV2` al import y:

```python
@admin.register(AnalisisV2)
class AnalisisV2Admin(admin.ModelAdmin):
    list_display = ['id', 'jornada', 'modo', 'pipeline', 'estado', 'creado_en', 'completado_en']
    list_filter = ['modo', 'pipeline', 'estado']
    readonly_fields = [
        'entrada', 'resultado', 'diagnostico', 'prompt_usado', 'modelo_usado', 'error_mensaje',
        'version_prompt', 'version_esquema', 'completado_en',
    ]
```

## Paso 4.6 — Verificación

```bash
source .venv/bin/activate
python -m py_compile analitica/models.py analitica/serializers.py analitica/admin_views.py analitica/urls.py analitica/admin.py analitica/migrations/0017_analisis_v2.py
python manage.py makemigrations analitica --check --dry-run     # "No changes detected"
python manage.py check                                          # "System check identified no issues"
```

Si hay Postgres local accesible (`.env`), además: `python manage.py migrate analitica` y un
`python manage.py shell -c "from analitica.models import AnalisisV2; print(AnalisisV2.objects.count())"`.

## Paso 4.7 — Tests (escribir, no correr) — agregar a `analitica/tests_v2.py`

```python
from rest_framework.test import APITestCase

from .models import AnalisisV2
from .tests import crear_admin_completo, crear_dependencia, crear_jornada
from .v2.procesar import procesar_analisis_v2


class AnalisisV2ApiTests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.dependencia = crear_dependencia('dependencia')
        self.d = crear_jornada_completa()
        self.jornada = self.d['jornada']
        self.jornada.propietarios.set([self.dependencia])
        self.jornada_ajena = crear_jornada('ajena')
        self.momento_ajeno = Momento.objects.create(jornada=self.jornada_ajena, orden=1, titulo='Ajeno')
        self.client.force_authenticate(user=self.admin)

    def _post(self, cuerpo):
        with patch('analitica.admin_views.threading.Thread') as hilo:
            resp = self.client.post('/api/admin/analisis-v2/', cuerpo, format='json')
        return resp, hilo

    def test_integral_crea_pendiente_y_lanza_hilo(self):
        resp, hilo = self._post({'jornada': self.jornada.id, 'modo': 'integral', 'pipeline': 'llm', 'contexto': 'C'})
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['estado'], 'pendiente')
        self.assertEqual(resp.data['version'], 'kunsamu.analisis/v2')
        self.assertEqual(resp.data['metodo'], 'openai')
        self.assertEqual(resp.data['momentos'], [])
        self.assertEqual(resp.data['contexto'], 'C')
        hilo.return_value.start.assert_called_once()
        self.assertEqual(AnalisisV2.objects.get(pk=resp.data['id']).solicitado_por, self.admin)

    def test_por_momento_con_personalizacion(self):
        m1 = self.d['m1']
        resp, _ = self._post({
            'jornada': self.jornada.id, 'modo': 'por_momento', 'pipeline': 'bertopic_llm', 'momentos': [m1.id],
            'personalizacion_momentos': [{'momento': m1.id, 'contexto': 'ctx', 'instrucciones': 'ins'}],
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['metodo'], 'bertopic')
        self.assertEqual([m['id'] for m in resp.data['momentos']], [m1.id])
        self.assertEqual(resp.data['personalizacion_momentos'], [{'momento': m1.id, 'contexto': 'ctx', 'instrucciones': 'ins'}])

    def test_integral_con_momentos_da_400(self):
        resp, _ = self._post({'jornada': self.jornada.id, 'modo': 'integral', 'pipeline': 'llm', 'momentos': [self.d['m1'].id]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('momentos', resp.data)

    def test_por_momento_sin_momentos_da_400(self):
        resp, _ = self._post({'jornada': self.jornada.id, 'modo': 'por_momento', 'pipeline': 'llm'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('momentos', resp.data)

    def test_momento_de_otra_jornada_da_400(self):
        resp, _ = self._post({'jornada': self.jornada.id, 'modo': 'por_momento', 'pipeline': 'llm', 'momentos': [self.momento_ajeno.id]})
        self.assertEqual(resp.status_code, 400)

    def test_personalizacion_fuera_del_alcance_da_400(self):
        resp, _ = self._post({
            'jornada': self.jornada.id, 'modo': 'por_momento', 'pipeline': 'llm', 'momentos': [self.d['m1'].id],
            'personalizacion_momentos': [{'momento': self.d['m2'].id, 'contexto': 'x'}],
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('personalizacion_momentos', resp.data)

    def test_pipeline_invalido_da_400(self):
        resp, _ = self._post({'jornada': self.jornada.id, 'modo': 'integral', 'pipeline': 'otro'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('pipeline', resp.data)

    def test_dependencia_no_puede_pedir_de_jornada_ajena(self):
        self.client.force_authenticate(user=self.dependencia)
        resp, _ = self._post({'jornada': self.jornada_ajena.id, 'modo': 'integral', 'pipeline': 'llm'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(AnalisisV2.objects.filter(jornada=self.jornada_ajena).exists())

    def test_409_solo_para_el_mismo_alcance(self):
        AnalisisV2.objects.create(jornada=self.jornada, modo='integral', estado=AnalisisV2.ESTADO_PROCESANDO)
        resp, _ = self._post({'jornada': self.jornada.id, 'modo': 'integral', 'pipeline': 'llm'})
        self.assertEqual(resp.status_code, 409)
        resp, _ = self._post({'jornada': self.jornada.id, 'modo': 'por_momento', 'pipeline': 'llm', 'momentos': [self.d['m1'].id]})
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_jornada_sin_momentos_da_400_en_integral(self):
        vacia = crear_jornada('vacia', propietario=self.admin)
        resp, _ = self._post({'jornada': vacia.id, 'modo': 'integral', 'pipeline': 'llm'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('jornada', resp.data)

    def test_lista_detalle_y_scoping(self):
        a = AnalisisV2.objects.create(jornada=self.jornada, modo='integral', estado=AnalisisV2.ESTADO_COMPLETO,
                                      resultado={'estado': 'parcial'}, entrada={'x': 1})
        AnalisisV2.objects.create(jornada=self.jornada_ajena, modo='integral')
        resp = self.client.get(f'/api/admin/analisis-v2/?jornada={self.jornada.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([i['id'] for i in resp.data], [a.id])
        self.assertNotIn('entrada', resp.data[0])
        self.assertEqual(resp.data[0]['estado_analitico'], 'parcial')
        resp = self.client.get(f'/api/admin/analisis-v2/{a.id}/')
        self.assertEqual(resp.data['entrada'], {'x': 1})
        self.client.force_authenticate(user=self.dependencia)
        resp = self.client.get('/api/admin/analisis-v2/')
        self.assertEqual([i['id'] for i in resp.data], [a.id])

    def test_lista_unificada_incluye_v2(self):
        a = AnalisisV2.objects.create(jornada=self.jornada, modo='por_momento', pipeline='bertopic_llm')
        a.momentos.set([self.d['m1']])
        resp = self.client.get(f'/api/admin/analisis/?jornada={self.jornada.id}')
        item = next(i for i in resp.data if i['tipo'] == 'analisis_v2')
        self.assertEqual(item['id'], a.id)
        self.assertEqual(item['version'], 'kunsamu.analisis/v2')
        self.assertEqual(item['metodo'], 'bertopic')
        self.assertEqual(item['alcance'], 'momento')
        self.assertEqual(item['momento_titulo'], self.d['m1'].titulo)
        self.assertIsNone(item['enfoque'])
        resp = self.client.get(f"/api/admin/analisis/?momento={self.d['m1'].id}")
        self.assertIn(a.id, [i['id'] for i in resp.data if i['tipo'] == 'analisis_v2'])
        resp = self.client.get(f"/api/admin/analisis/?momento={self.d['m2'].id}")
        self.assertNotIn(a.id, [i['id'] for i in resp.data if i['tipo'] == 'analisis_v2'])


class ProcesarAnalisisV2Tests(TestCase):
    """El orquestador con la llamada a OpenAI mockeada: lo que se guarda, en qué estado y qué
    queda en diagnostico."""

    def setUp(self):
        self.d = crear_jornada_completa()

    def _salida_valida(self, system, user, modelo=None, reparacion=None):
        # Una salida que SIEMPRE valida contra la entrada: la forma sin_datos construida a partir
        # del propio `user` (no importa que la entrada sí tenga respuestas — eso no lo comprueba
        # el validador de negocio).
        entrada = json.loads(user)
        return construir_salida_sin_datos(entrada, 'llm'), None, {'finish_reason': 'stop', 'modo_salida': 'json_schema'}

    def test_completo_con_salida_valida(self):
        a = AnalisisV2.objects.create(jornada=self.d['jornada'], modo='integral', pipeline='llm')
        with patch('analitica.v2.procesar.llamar_openai_estructurado', side_effect=self._salida_valida) as llamada:
            procesar_analisis_v2(a.id)
        a.refresh_from_db()
        self.assertEqual(a.estado, AnalisisV2.ESTADO_COMPLETO, a.error_mensaje)
        self.assertEqual(a.resultado['version'], 'kunsamu.analisis/v2')
        self.assertEqual(a.modelo_usado, 'Generado con IA')
        self.assertEqual(a.version_esquema, 'v2.0')
        self.assertTrue(a.prompt_usado.startswith('# System prompt Kunsamu — LLM'))
        self.assertEqual(a.entrada['solicitud']['modo'], 'integral')
        self.assertEqual(len(a.diagnostico['intentos']), 1)
        self.assertEqual(llamada.call_count, 1)

    def test_sin_datos_no_llama_a_openai(self):
        vacia = Jornada.objects.create(slug='v', nombre='V', fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 1))
        m = Momento.objects.create(jornada=vacia, orden=1, titulo='M')
        Pregunta.objects.create(momento=m, tipo='abierta', texto='¿?', orden=1)
        a = AnalisisV2.objects.create(jornada=vacia, modo='integral', pipeline='bertopic_llm')
        with patch('analitica.v2.procesar.llamar_openai_estructurado') as llamada:
            procesar_analisis_v2(a.id)
        a.refresh_from_db()
        llamada.assert_not_called()
        self.assertEqual(a.estado, AnalisisV2.ESTADO_COMPLETO, a.error_mensaje)
        self.assertEqual(a.resultado['estado'], 'sin_datos')
        self.assertEqual(a.resultado['pipeline'], 'bertopic_llm')
        self.assertEqual(a.prompt_usado, '')
        self.assertEqual(a.entrada['bertopic'], {'version_adaptador': '1.0', 'ejecuciones': []})

    def test_invalida_dos_veces_termina_en_error_con_diagnostico(self):
        a = AnalisisV2.objects.create(jornada=self.d['jornada'], modo='integral', pipeline='llm')
        invalida = ({'version': 'kunsamu.analisis/v2'}, None, {'finish_reason': 'stop'})
        with patch('analitica.v2.procesar.llamar_openai_estructurado', return_value=invalida) as llamada:
            procesar_analisis_v2(a.id)
        a.refresh_from_db()
        self.assertEqual(llamada.call_count, 2)
        self.assertIsNotNone(llamada.call_args_list[1].kwargs.get('reparacion'))
        self.assertEqual(a.estado, AnalisisV2.ESTADO_ERROR)
        self.assertIn('no pasó la validación', a.error_mensaje)
        self.assertEqual(a.resultado, {})
        self.assertEqual(len(a.diagnostico['intentos']), 2)
        self.assertTrue(a.diagnostico['intentos'][0]['errores_validacion'])

    def test_error_del_proveedor_termina_en_error(self):
        a = AnalisisV2.objects.create(jornada=self.d['jornada'], modo='integral', pipeline='llm')
        with patch('analitica.v2.procesar.llamar_openai_estructurado', return_value=(None, 'boom', {})):
            procesar_analisis_v2(a.id)
        a.refresh_from_db()
        self.assertEqual(a.estado, AnalisisV2.ESTADO_ERROR)
        self.assertEqual(a.error_mensaje, 'boom')
```

`python -m py_compile analitica/tests_v2.py` debe pasar.

## Paso 4.8 — Commit

```bash
git status --short
git add analitica/models.py analitica/migrations/0017_analisis_v2.py analitica/serializers.py \
        analitica/admin_views.py analitica/urls.py analitica/admin.py analitica/tests_v2.py
git commit -m "feat(v2): modelo AnalisisV2 y endpoint /api/admin/analisis-v2/ (contrato kunsamu.analisis/v2)

Modelo nuevo en vez de tocar Reporte/AnalisisMomentoIA/AnalisisJornadaIA: el frontend elige
renderer por la version del resultado y conserva los visores históricos, y el contrato rompe la
partición por alcance de los tres legacy. POST con modo integral|por_momento, pipeline
llm|bertopic_llm, contexto/instrucciones y personalización por momento; guards 403 → 409 (mismo
alcance) → 400; sin guard de "sin respuestas" porque sin_datos es un estado válido que el
backend produce sin IA. Entra a la lista unificada como tipo analisis_v2 con version/modo/
pipeline/estado_analitico. Este push despliega en el servidor de develop y aplica la migración
0017 al reiniciar el contenedor."
```

**Aviso al pushear**: es la primera fase con migración. El contenedor `app` la aplica al arrancar
(`docker/entrypoint.sh`). Confirmar en el servidor de pruebas con `docker compose logs app | grep
-i "applying analitica.0017"` (ver `11_verificacion_y_smoke.md`).

## Criterios de "hecho"

- [ ] `makemigrations --check` sin cambios; `manage.py check` limpio; todo compila.
- [ ] `GET /api/admin/analisis-v2/` responde `200 []` en el servidor de pruebas tras el deploy.
- [ ] Tests escritos (no corridos). Commit sin `Dockerfile`/`docker-compose.yml`.
