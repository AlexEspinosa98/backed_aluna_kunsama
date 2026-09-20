# 09 — Fase 6 (recomendada, diferible): infografía a partir de un `AnalisisV2`

**Objetivo**: que `POST /api/admin/infografias/` acepte `{"analisis_v2": <id>}` como cuarta forma
de fijar el análisis del que salen las láminas (D12), sin cambiar el prompt de imagen ni el resto
del flujo. Es la única pieza legacy que se toca en todo el plan.

**Prerrequisitos**: fase 4. Independiente de la fase 5.

**Archivos**: `analitica/models.py` (FK nuevo), migración `0018`, `analitica/serializers.py`
(dos serializers de infografía), `analitica/admin_views.py` (helpers + `create` del viewset),
`analitica/infografia_ia_openai.py` (`_obtener_datos_analitica` + `generar_infografias`),
`analitica/tests_v2.py`.

Antes de tocar `infografia_ia_openai.py`, leerlo entero (461 líneas): `_obtener_datos_analitica`
(líneas ~191–265) es la función que decide de dónde salen los datos; `generar_infografias`
(más abajo) es el hilo de background que la llama con los FK de la `InfografiaJornada`.

## Paso 6.1 — Modelo

En `InfografiaJornada` (models.py), después de `analisis_jornada`:

```python
    analisis_v2 = models.ForeignKey(
        'AnalisisV2', on_delete=models.SET_NULL, null=True, blank=True, related_name='infografias',
        help_text='Fija el AnalisisV2 (contrato kunsamu.analisis/v2) exacto del que salen los datos.',
    )
```

Migración: `python manage.py makemigrations analitica -n infografia_analisis_v2` →
`0018_infografia_analisis_v2.py`. Confirmar dependencia `0017_analisis_v2`.

## Paso 6.2 — Serializers

`InfografiaJornadaSerializer.Meta.fields`: agregar `'analisis_v2'` después de `'analisis_jornada'`.

`InfografiaJornadaCrearSerializer`: agregar `'analisis_v2'` a `fields` (después de
`'analisis_jornada'`) y reescribir `validate` así:

```python
    def validate(self, attrs):
        reporte = attrs.get('reporte')
        analisis_momento = attrs.get('analisis_momento')
        analisis_jornada = attrs.get('analisis_jornada')
        analisis_v2 = attrs.get('analisis_v2')

        elegidos = [v for v in (reporte, analisis_momento, analisis_jornada, analisis_v2) if v is not None]
        if len(elegidos) != 1:
            raise serializers.ValidationError(
                'Manda EXACTAMENTE uno de "reporte", "analisis_momento", "analisis_jornada" o '
                '"analisis_v2" — la infografía queda atada a esa versión exacta del análisis, nunca '
                'a "la jornada" o "el momento" en general (ver HU-73).'
            )

        if analisis_v2 is not None:
            momentos = list(analisis_v2.momentos.all())
            # Un por_momento de UN momento es "de" ese momento (título de portada, filtros); un
            # integral o un por_momento de varios es de la jornada.
            attrs['momento'] = momentos[0] if (
                analisis_v2.modo == analisis_v2.MODO_POR_MOMENTO and len(momentos) == 1
            ) else None
            attrs['jornada'] = analisis_v2.jornada
        elif analisis_momento is not None:
            attrs['momento'] = analisis_momento.momento
            attrs['jornada'] = analisis_momento.momento.jornada
        elif analisis_jornada is not None:
            attrs['momento'] = None
            attrs['jornada'] = analisis_jornada.jornada
        else:
            attrs['momento'] = None
            attrs['jornada'] = reporte.jornada
        return attrs
```

Actualizar el docstring del serializer para nombrar el cuarto campo.

## Paso 6.3 — `admin_views.py`

- `_filtro_fuente_infografia(reporte=None, analisis_momento=None, analisis_jornada=None, analisis_v2=None)`:
  agregar al inicio `if analisis_v2 is not None: return {'analisis_v2': analisis_v2}`.
- `_infografias_en_curso`, `sanar_infografias_huerfanas`, `hay_infografia_en_curso`: agregar el
  parámetro `analisis_v2=None` al final de la firma y pasarlo a `_filtro_fuente_infografia(...,
  analisis_v2=analisis_v2)`. Las llamadas existentes con tres posicionales siguen válidas.
- `InfografiaJornadaViewSet.get_queryset`: agregar `'analisis_v2'` al `select_related` y el filtro
  `?analisis_v2=<id>` (mismo patrón que `analisis_jornada`).
- `InfografiaJornadaViewSet.create`: leer `analisis_v2 = entrada.validated_data.get('analisis_v2')`
  y pasarlo como kwarg a `sanar_infografias_huerfanas(...)`, `hay_infografia_en_curso(...)` y
  `_obtener_datos_analitica(jornada, reporte, momento, analisis_momento, analisis_jornada,
  analisis_v2=analisis_v2)`.
- Actualizar el docstring de `InfografiaJornadaViewSet` (cuatro formas de fijar).

## Paso 6.4 — `infografia_ia_openai.py`

1. Firma: `def _obtener_datos_analitica(jornada, reporte=None, momento=None, analisis_momento=None, analisis_jornada=None, analisis_v2=None):` y, **como primera línea del cuerpo** (antes del `if momento is not None:` — esa rama busca un `AnalisisMomentoIA` y no debe alcanzarse para un v2):

```python
    if analisis_v2 is not None:
        return _datos_desde_analisis_v2(jornada, analisis_v2)
```

2. Función nueva, encima de `_obtener_datos_analitica`:

```python
def _datos_desde_analisis_v2(jornada, analisis_v2):
    """Traduce un resultado kunsamu.analisis/v2 al MISMO diccionario que las láminas ya consumen
    para los análisis IA legacy (`resumen_ejecutivo` + `hallazgos[{titulo, descripcion,
    tipo_grafica, datos[{etiqueta, valor, unidad}]}]`) — el prompt de imagen no cambia. La
    descripción es `afirmacion` (+ `implicacion`); los datos salen de `metricas` y, si el
    hallazgo no trae métricas pero sí una visualización categórica, de sus filas."""
    from .models import AnalisisV2

    if analisis_v2.estado != AnalisisV2.ESTADO_COMPLETO or not analisis_v2.resultado:
        return None, (
            f'El análisis v2 #{analisis_v2.id} no está completo o no tiene resultado. Espera a que '
            'termine y vuelve a pedir la infografía.'
        )
    resultado = analisis_v2.resultado
    if resultado.get('estado') == 'sin_datos':
        return None, 'El análisis v2 no tiene datos (estado sin_datos): no hay nada que ilustrar.'

    categoricas = ('barras', 'barras_agrupadas', 'barras_apiladas', 'barras_100', 'dona', 'radar')
    visuales = {v['id']: v for v in resultado.get('visualizaciones', [])}
    hallazgos = []
    for informe in resultado.get('informes', []):
        for h in informe.get('hallazgos', []):
            datos = [
                {'etiqueta': m['etiqueta'], 'valor': m['valor'], 'unidad': m['unidad']}
                for m in h.get('metricas', [])
            ]
            tipo_grafica = None
            for vid in h.get('visualizacion_ids', []):
                visual = visuales.get(vid)
                if visual and visual['tipo'] in categoricas:
                    tipo_grafica = {'dona': 'pastel', 'radar': 'radar'}.get(visual['tipo'], 'barras')
                    if not datos:
                        datos = [
                            {'etiqueta': f['categoria'], 'valor': f['valor'], 'unidad': visual['datos']['unidad']}
                            for f in visual['datos']['filas'] if f['valor'] is not None
                        ]
                    break
            descripcion = h['afirmacion'] + (f" {h['implicacion']}" if h.get('implicacion') else '')
            hallazgos.append({'titulo': h['titulo'], 'descripcion': descripcion, 'tipo_grafica': tipo_grafica, 'datos': datos})

    momentos = list(analisis_v2.momentos.all())
    momento = momentos[0] if analisis_v2.modo == AnalisisV2.MODO_POR_MOMENTO and len(momentos) == 1 else None
    return {
        'fuente': 'analisis_v2',
        'jornada': jornada.nombre,
        'momento': momento.titulo if momento else None,
        'tipo_momento': momento.tipo if momento else None,
        'resumen_ejecutivo': ' '.join(i['resumen'] for i in resultado.get('informes', [])),
        'hallazgos': hallazgos,
    }, None
```

`_titulo_lamina` ya hace `datos.get('momento') or datos.get('jornada')`, así que la portada sale
bien sin tocarla.

3. En `generar_infografias(infografia_id)`: localizar la llamada a `_obtener_datos_analitica(...)`
   y agregarle `analisis_v2=infografia.analisis_v2`. Si el `select_related` de esa función
   enumera los FK, agregar `'analisis_v2'`.

## Paso 6.5 — Verificación

```bash
source .venv/bin/activate
python -m py_compile analitica/models.py analitica/serializers.py analitica/admin_views.py analitica/infografia_ia_openai.py analitica/migrations/0018_infografia_analisis_v2.py
python manage.py makemigrations analitica --check --dry-run
python manage.py check
```

## Paso 6.6 — Tests (escribir, no correr) — agregar a `analitica/tests_v2.py`

```python
from .infografia_ia_openai import _obtener_datos_analitica
from .models import InfografiaJornada


class InfografiaDesdeAnalisisV2Tests(APITestCase):
    def setUp(self):
        self.admin = crear_admin_completo('admin')
        self.d = crear_jornada_completa()
        self.jornada = self.d['jornada']
        self.resultado = _ejemplo('llm_por_momento.salida.json')
        self.analisis = AnalisisV2.objects.create(
            jornada=self.jornada, modo='por_momento', pipeline='llm', estado=AnalisisV2.ESTADO_COMPLETO,
            resultado=self.resultado,
        )
        self.analisis.momentos.set([self.d['m1']])
        self.client.force_authenticate(user=self.admin)

    def test_traduce_resultado_v2_al_formato_de_las_laminas(self):
        datos, error = _obtener_datos_analitica(self.jornada, analisis_v2=self.analisis)
        self.assertIsNone(error)
        self.assertEqual(datos['fuente'], 'analisis_v2')
        self.assertEqual(datos['momento'], self.d['m1'].titulo)
        self.assertEqual(len(datos['hallazgos']), 2)
        primero = datos['hallazgos'][0]
        self.assertEqual(primero['tipo_grafica'], 'barras')
        self.assertEqual(primero['datos'][0]['etiqueta'], 'El horario no sirve')
        self.assertIn('Conviene contrastar', primero['descripcion'])
        self.assertIsNone(datos['hallazgos'][1]['tipo_grafica'])

    def test_no_completo_o_sin_datos_da_error(self):
        self.analisis.estado = AnalisisV2.ESTADO_PROCESANDO
        self.analisis.save()
        _, error = _obtener_datos_analitica(self.jornada, analisis_v2=self.analisis)
        self.assertIn('no está completo', error)
        self.analisis.estado = AnalisisV2.ESTADO_COMPLETO
        self.analisis.resultado = _ejemplo('sin_datos.salida.json')
        self.analisis.save()
        _, error = _obtener_datos_analitica(self.jornada, analisis_v2=self.analisis)
        self.assertIn('sin_datos', error)

    def test_api_fija_analisis_v2_y_deriva_momento(self):
        with patch('analitica.admin_views.threading.Thread'):
            resp = self.client.post('/api/admin/infografias/', {'analisis_v2': self.analisis.id}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        infografia = InfografiaJornada.objects.get(pk=resp.data['id'])
        self.assertEqual(infografia.analisis_v2, self.analisis)
        self.assertEqual(infografia.momento, self.d['m1'])
        self.assertEqual(infografia.jornada, self.jornada)
        resp = self.client.get(f'/api/admin/infografias/?analisis_v2={self.analisis.id}')
        self.assertEqual([i['id'] for i in resp.data], [infografia.id])

    def test_dos_pines_a_la_vez_da_400(self):
        reporte = Reporte.objects.create(jornada=self.jornada, alcance=Reporte.ALCANCE_JORNADA, estado=Reporte.ESTADO_COMPLETO)
        resp = self.client.post('/api/admin/infografias/', {'analisis_v2': self.analisis.id, 'reporte': reporte.id}, format='json')
        self.assertEqual(resp.status_code, 400)
```

(Agregar `Reporte` al import de `.models` en `tests_v2.py`.)

## Paso 6.7 — Commit

```bash
git status --short
git add analitica/models.py analitica/migrations/0018_infografia_analisis_v2.py analitica/serializers.py \
        analitica/admin_views.py analitica/infografia_ia_openai.py analitica/tests_v2.py
git commit -m "feat(v2): la infografía puede fijarse a un AnalisisV2

Cuarto FK mutuamente excluyente en InfografiaJornada. El resultado v2 se traduce al mismo
diccionario que ya consumen las láminas (afirmacion+implicacion como descripción, metricas o la
visualización categórica del hallazgo como datos), así que el prompt de imagen no cambia. Un
por_momento de un solo momento es 'de' ese momento para la portada y los filtros."
```

## Criterios de "hecho"

- [ ] `makemigrations --check` limpio; `manage.py check` limpio.
- [ ] `POST /api/admin/infografias/ {"analisis_v2": id}` en el servidor de pruebas → 201 y
      láminas generadas (o el 400 explicativo si el análisis no está completo).
- [ ] Commit sin `Dockerfile`/`docker-compose.yml`.
