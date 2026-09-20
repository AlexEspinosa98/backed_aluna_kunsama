# 05 — Fase 2: entrada normalizada desde la base de datos y salida `sin_datos`

**Objetivo**: `analitica/v2/entrada.py` (construye el sobre de `ENTRADA_Y_BERTOPIC.md` §1–§2 a
partir de `Jornada`/`Momento`/`Pregunta`/`Respuesta`) y `analitica/v2/sin_datos.py` (construye
una salida v2 válida cuando el alcance no tiene respuestas, sin llamar a la IA — D11).

**Prerrequisitos**: fases 0 y 1.

Ambas son funciones puras sobre el ORM: reciben objetos y valores, no el modelo `AnalisisV2` (que
aún no existe). Así se prueban con fixtures sin API y se pueden llamar desde el orquestador con
cualquier fuente de parámetros.

## Paso 2.1 — Mapeo exacto (léelo antes del código)

### Sobre

| Clave | Valor |
|---|---|
| `solicitud` | `{"modo": modo, "jornada_id": str(jornada.id), "momento_ids": [str(m.id) …]}`. `integral` → todos los momentos de la jornada ordenados por `orden` (sin filtrar `activo`). `por_momento` → los momentos recibidos, ordenados por `orden`. |
| `jornada` | `{"id": str, "nombre": jornada.nombre, "objetivo": jornada.descripcion or "", "contexto": "Jornada realizada entre YYYY-MM-DD y YYYY-MM-DD."}` |
| `momentos[]` | `{"id": str, "nombre": momento.titulo, "tipo": momento.tipo, "contexto": <contexto + frase de categorías semilla>, "preguntas": [...]}` |
| `personalizacion` | `{"instrucciones_usuario": instrucciones, "contexto_usuario": contexto, "instrucciones_por_momento": [{"momento_id": str, "instrucciones": "…", "contexto": "…"} …]}` — solo los momentos que estén en el alcance; orden = el del alcance. |
| `fuentes[]` | Por cada momento del alcance, en orden: una fuente `respuestas` (siempre) y, si el momento tiene preguntas `unica`/`multiple` en el inventario, una fuente `agregado`. |
| `bertopic` | `None` (la fase 5 lo llena en el pipeline `bertopic_llm`). |

### Inventario de preguntas de un momento

`momento.preguntas.filter(Q(activa=True) | Q(respuestas__isnull=False)).distinct().order_by('orden')`.

### Pregunta

```
{
  "id": str(p.id), "texto": p.texto, "tipo": p.tipo,          # abierta|unica|multiple|matriz|lista|audio (nombres canónicos)
  "opciones": [{"id": str(o.id), "etiqueta": o.texto} …],      # [] si no aplica
  "reglas_elegibilidad": {
    "descripcion": <frase>, "filtro": <str|null>, "unidad_esperada": "persona"|"mesa",
    "escala": null,
    "estructura": null | {"filas": [{"id","etiqueta"}], "columnas": [{"id","etiqueta","tipo":"abierta","opciones":[]}], "permite_repetir_filas": bool}
  }
}
```

`descripcion`: base `"Participantes de la jornada"` (momento individual) o `"Mesas de la
jornada"` (mesa); si `roles_permitidos`: `" con rol {a, b}"`; si es mesa y `mesas_permitidas`:
`" de las mesas {1, 3}"`; si `depende_de_opcion`: `' que marcaron la opción "{opcion.texto}" en la
pregunta "{opcion.pregunta.texto}"'`; termina con `". Pregunta obligatoria."` o
`". Pregunta opcional."`. `filtro`: partes `roles:a,b` / `mesas:1,3` / `depende_de_opcion:<id>`
unidas con ` & `, o `null` si no hay ninguna. `estructura.filas` = filas fijas (solo `matriz`;
`[]` en `lista`); `permite_repetir_filas` = `p.acepta_filas_dinamicas`.

### Fuente `respuestas` de un momento

```
{"id": "f-m{momento.id}", "tipo": "respuestas", "etiqueta": "Respuestas registradas — {titulo}",
 "momento_ids": [str(momento.id)], "pregunta_ids": [ids del inventario], "cobertura": "completa",
 "datos": {"unidad_analisis": "respuesta_individual"|"respuesta_de_mesa", "respuestas": [...]}}
```

`respuestas` en orden: preguntas del inventario por `orden`; dentro de cada pregunta,
`Respuesta` por `id` ascendente. Por tipo:

| tipo | filas `Respuesta` | elemento generado |
|---|---|---|
| `unica` | una por sujeto | `{"id": "r{r.id}", "pregunta_id", "sujeto_id", "valor": str(opcion.id) o null}` |
| `multiple` | una por sujeto | `valor: [str(o.id) …]` (lista, puede ser `[]`) |
| `abierta`, `audio` | una por sujeto | `valor: texto_libre` si no está en blanco, si no `null` (el texto se conserva **sin strip**: las citas deben ser subcadenas del original) |
| `matriz`, `lista` | **una por celda** | se agrupan por sujeto → `{"id": "r-q{p.id}-{sujeto}", "pregunta_id", "sujeto_id", "valor": {"celdas": [{"fila_id": str|null, "columna_id": str|null, "fila_lista_id": str|null, "valor": texto|null} …]}}`; orden de los grupos = primer `Respuesta.id` de cada sujeto; celdas por `Respuesta.id` |

`sujeto_id`: `"p{participante_id}"` si hay participante; si no, `"mesa-{mesa}"` si hay mesa; si
no, `null` (solo en datos de prueba). Para la clave de agrupación de matriz/lista se usa el
`sujeto_id` o `"anon"`.

### Fuente `agregado` de un momento (solo si hay preguntas `unica`/`multiple`)

```
{"id": "f-agg-m{momento.id}", "tipo": "agregado", "etiqueta": "Conteos por opción calculados por el backend — {titulo}",
 "momento_ids": [...], "pregunta_ids": [solo las cerradas], "cobertura": "completa",
 "datos": {"unidad_analisis": <mismo que respuestas>,
           "bases": [{"id": "b-q{p.id}", "pregunta_id", "elegibles_n": null, "recibidas_n": <Respuesta.count()>, "validas_n": <con ≥1 opción>, "ausentes_n": recibidas−validas, "no_aplica_n": null, "rechazadas_n": null}],
           "distribuciones": [{"pregunta_id", "base_id": "b-q{p.id}", "tipo": "respuesta_unica"|"respuesta_multiple", "categorias": [{"id": str(o.id), "etiqueta": o.texto, "n": <conteo>, "porcentaje": round(100*n/validas_n, 2) o null si validas_n == 0}]}],
           "estadisticas": [],
           "procedimiento": {"origen": "backend", "calculado_por": "analitica.v2.entrada._fuente_agregado", "datos_version": <ISO now>, "notas": "…"}}}
```

## Paso 2.2 — `analitica/v2/entrada.py`

Crear con este contenido exacto:

```python
"""Sobre de entrada normalizado del contrato v2 (docs/mejora_promps/ENTRADA_Y_BERTOPIC.md §1–§5),
construido desde los modelos reales de jornadas/participantes. Mapeo detallado en
docs/mejora_promps/plan_implementacion/05_fase_2_entrada_y_sin_datos.md.

Tres decisiones fijas (D7 del plan):
- Todos los IDs son strings y el orden de cada array es determinista (preguntas por `orden`,
  respuestas por `id`): los JSON Pointers de las citas (`/respuestas/10/valor`) y de los documentos
  BERTopic apuntan a índices de estos arrays, y el orquestador guarda este sobre ANTES de llamar
  a la IA para que nunca se recalcule con otro orden.
- Siempre hay una fuente `respuestas` por momento del alcance, aunque esté vacía: una fuente
  completa vacía es lo que permite declarar `sin_datos` en vez de `no_recibida`.
- Las preguntas cerradas llevan además una fuente `agregado` con conteos calculados acá — los
  números nunca dependen del LLM (misma filosofía que analysis.py); el modelo los cita con
  `origen: reportado` y una ruta verificable.
"""
from django.db.models import Q
from django.utils import timezone

from .contrato import MODO_INTEGRAL

TIPOS_TEXTO = ('abierta', 'audio')
TIPOS_CERRADOS = ('unica', 'multiple')
TIPOS_CELDAS = ('matriz', 'lista')


def _texto_o_null(texto):
    # Sin strip: el original se conserva tal cual para que una cita literal sea subcadena exacta.
    return texto if isinstance(texto, str) and texto.strip() else None


def _sujeto_id(respuesta):
    if respuesta.participante_id:
        return f'p{respuesta.participante_id}'
    if respuesta.mesa is not None:
        return f'mesa-{respuesta.mesa}'
    return None


def preguntas_inventario(momento):
    """Activas, o inactivas con al menos una respuesta real: una pregunta desactivada con datos
    no desaparece del inventario en silencio (mismo criterio que `Momento.activo` para los
    análisis de jornada completa)."""
    return list(
        momento.preguntas.filter(Q(activa=True) | Q(respuestas__isnull=False))
        .distinct().order_by('orden')
        .prefetch_related('opciones', 'filas', 'columnas')
        .select_related('depende_de_opcion', 'depende_de_opcion__pregunta')
    )


def _reglas_elegibilidad(pregunta, momento):
    es_mesa = momento.tipo == 'mesa'
    descripcion = 'Mesas de la jornada' if es_mesa else 'Participantes de la jornada'
    filtros = []
    if pregunta.roles_permitidos:
        roles = ', '.join(str(r) for r in pregunta.roles_permitidos)
        descripcion += f' con rol {roles}'
        filtros.append('roles:' + ','.join(str(r) for r in pregunta.roles_permitidos))
    if es_mesa and pregunta.mesas_permitidas:
        mesas = ', '.join(str(m) for m in pregunta.mesas_permitidas)
        descripcion += f' de las mesas {mesas}'
        filtros.append('mesas:' + ','.join(str(m) for m in pregunta.mesas_permitidas))
    if pregunta.depende_de_opcion_id:
        opcion = pregunta.depende_de_opcion
        descripcion += (
            f' que marcaron la opción "{opcion.texto}" en la pregunta "{opcion.pregunta.texto}"'
        )
        filtros.append(f'depende_de_opcion:{opcion.id}')
    descripcion += '. Pregunta obligatoria.' if pregunta.obligatoria else '. Pregunta opcional.'

    estructura = None
    if pregunta.tipo in TIPOS_CELDAS:
        estructura = {
            'filas': (
                [{'id': str(f.id), 'etiqueta': f.texto} for f in pregunta.filas.all()]
                if pregunta.tipo == 'matriz' else []
            ),
            'columnas': [
                {'id': str(c.id), 'etiqueta': c.texto, 'tipo': 'abierta', 'opciones': []}
                for c in pregunta.columnas.all()
            ],
            'permite_repetir_filas': pregunta.acepta_filas_dinamicas,
        }
    return {
        'descripcion': descripcion,
        'filtro': ' & '.join(filtros) if filtros else None,
        'unidad_esperada': 'mesa' if es_mesa else 'persona',
        'escala': None,
        'estructura': estructura,
    }


def _pregunta_payload(pregunta, momento):
    return {
        'id': str(pregunta.id),
        'texto': pregunta.texto,
        'tipo': pregunta.tipo,
        'opciones': [{'id': str(o.id), 'etiqueta': o.texto} for o in pregunta.opciones.all()],
        'reglas_elegibilidad': _reglas_elegibilidad(pregunta, momento),
    }


def _momento_payload(momento, preguntas):
    contexto = momento.contexto or ''
    if momento.categorias_semilla:
        # El contrato no tiene campo para categorías semilla: van como contexto descriptivo (no
        # como orden de formato), que es lo único que la entrada admite en `momentos[].contexto`.
        frase = (
            'Categorías temáticas de referencia definidas por el equipo organizador: '
            + ', '.join(str(c) for c in momento.categorias_semilla) + '.'
        )
        contexto = f'{contexto}\n{frase}' if contexto else frase
    return {
        'id': str(momento.id),
        'nombre': momento.titulo,
        'tipo': momento.tipo,
        'contexto': contexto,
        'preguntas': [_pregunta_payload(p, momento) for p in preguntas],
    }


def _respuestas_de_pregunta(pregunta):
    from participantes.models import Respuesta

    filas = (
        Respuesta.objects.filter(pregunta=pregunta)
        .select_related('fila', 'columna', 'fila_lista')
        .prefetch_related('opciones')
        .order_by('id')
    )
    pregunta_id = str(pregunta.id)
    if pregunta.tipo in TIPOS_CELDAS:
        grupos = {}
        for respuesta in filas:
            sujeto = _sujeto_id(respuesta)
            grupos.setdefault(sujeto or 'anon', (sujeto, []))[1].append(respuesta)
        return [
            {
                'id': f'r-q{pregunta.id}-{clave}',
                'pregunta_id': pregunta_id,
                'sujeto_id': sujeto,
                'valor': {'celdas': [
                    {
                        'fila_id': str(r.fila_id) if r.fila_id else None,
                        'columna_id': str(r.columna_id) if r.columna_id else None,
                        'fila_lista_id': str(r.fila_lista_id) if r.fila_lista_id else None,
                        'valor': _texto_o_null(r.texto_libre),
                    }
                    for r in celdas
                ]},
            }
            for clave, (sujeto, celdas) in grupos.items()
        ]

    resultado = []
    for respuesta in filas:
        if pregunta.tipo == 'unica':
            opciones = list(respuesta.opciones.all())
            valor = str(opciones[0].id) if opciones else None
        elif pregunta.tipo == 'multiple':
            valor = [str(o.id) for o in respuesta.opciones.all()]
        else:
            valor = _texto_o_null(respuesta.texto_libre)
        resultado.append({
            'id': f'r{respuesta.id}',
            'pregunta_id': pregunta_id,
            'sujeto_id': _sujeto_id(respuesta),
            'valor': valor,
        })
    return resultado


def _unidad_analisis(momento):
    return 'respuesta_de_mesa' if momento.tipo == 'mesa' else 'respuesta_individual'


def _fuente_respuestas(momento, preguntas):
    respuestas = []
    for pregunta in preguntas:
        respuestas.extend(_respuestas_de_pregunta(pregunta))
    return {
        'id': f'f-m{momento.id}',
        'tipo': 'respuestas',
        'etiqueta': f'Respuestas registradas — {momento.titulo}',
        'momento_ids': [str(momento.id)],
        'pregunta_ids': [str(p.id) for p in preguntas],
        'cobertura': 'completa',
        'datos': {'unidad_analisis': _unidad_analisis(momento), 'respuestas': respuestas},
    }


def _fuente_agregado(momento, preguntas):
    """Conteos por opción de las preguntas cerradas, calculados acá y no por el LLM. `None` si el
    momento no tiene preguntas cerradas en el inventario."""
    from participantes.models import Respuesta

    cerradas = [p for p in preguntas if p.tipo in TIPOS_CERRADOS]
    if not cerradas:
        return None
    bases, distribuciones = [], []
    for pregunta in cerradas:
        filas = Respuesta.objects.filter(pregunta=pregunta)
        recibidas = filas.count()
        validas = filas.filter(opciones__isnull=False).distinct().count()
        base_id = f'b-q{pregunta.id}'
        bases.append({
            'id': base_id, 'pregunta_id': str(pregunta.id), 'elegibles_n': None,
            'recibidas_n': recibidas, 'validas_n': validas, 'ausentes_n': recibidas - validas,
            'no_aplica_n': None, 'rechazadas_n': None,
        })
        categorias = []
        for opcion in pregunta.opciones.all():
            n = filas.filter(opciones=opcion).count()
            categorias.append({
                'id': str(opcion.id), 'etiqueta': opcion.texto, 'n': n,
                'porcentaje': round(100 * n / validas, 2) if validas else None,
            })
        distribuciones.append({
            'pregunta_id': str(pregunta.id), 'base_id': base_id,
            'tipo': 'respuesta_unica' if pregunta.tipo == 'unica' else 'respuesta_multiple',
            'categorias': categorias,
        })
    return {
        'id': f'f-agg-m{momento.id}',
        'tipo': 'agregado',
        'etiqueta': f'Conteos por opción calculados por el backend — {momento.titulo}',
        'momento_ids': [str(momento.id)],
        'pregunta_ids': [str(p.id) for p in cerradas],
        'cobertura': 'completa',
        'datos': {
            'unidad_analisis': _unidad_analisis(momento),
            'bases': bases,
            'distribuciones': distribuciones,
            'estadisticas': [],
            'procedimiento': {
                'origen': 'backend',
                'calculado_por': 'analitica.v2.entrada._fuente_agregado',
                'datos_version': timezone.now().isoformat(),
                'notas': (
                    'Conteos exactos sobre la tabla de respuestas; porcentaje = 100 × n / validas_n '
                    'de la misma pregunta (validas_n = respuestas con al menos una opción marcada). '
                    'En selección múltiple una respuesta cuenta en cada opción que marcó, así que '
                    'los porcentajes pueden sumar más de 100.'
                ),
            },
        },
    }


def momentos_del_alcance(jornada, modo, momentos):
    """`integral` → todos los momentos de la jornada (activos o no). `por_momento` → los dados.
    Siempre ordenados por `orden`: ese es "el orden recibido" que el contrato pide respetar en
    `informes`, y es determinista."""
    if modo == MODO_INTEGRAL:
        return list(jornada.momentos.all().order_by('orden'))
    return sorted(momentos, key=lambda m: m.orden)


def construir_entrada(jornada, modo, momentos, contexto='', instrucciones='', personalizacion_momentos=None):
    """El sobre completo, con `bertopic: None` (la fase 5 lo llena en el pipeline bertopic_llm).
    `momentos`: lista de `Momento` (ignorada en modo integral). `personalizacion_momentos`: lista
    de dicts `{'momento': <id int>, 'contexto': str, 'instrucciones': str}`."""
    alcance = momentos_del_alcance(jornada, modo, momentos or [])
    ids_alcance = [str(m.id) for m in alcance]
    por_momento = {int(item['momento']): item for item in (personalizacion_momentos or [])}

    momentos_payload, fuentes = [], []
    for momento in alcance:
        preguntas = preguntas_inventario(momento)
        momentos_payload.append(_momento_payload(momento, preguntas))
        fuentes.append(_fuente_respuestas(momento, preguntas))
        agregado = _fuente_agregado(momento, preguntas)
        if agregado:
            fuentes.append(agregado)

    return {
        'solicitud': {'modo': modo, 'jornada_id': str(jornada.id), 'momento_ids': ids_alcance},
        'jornada': {
            'id': str(jornada.id),
            'nombre': jornada.nombre,
            'objetivo': jornada.descripcion or '',
            'contexto': f'Jornada realizada entre {jornada.fecha_inicio:%Y-%m-%d} y {jornada.fecha_fin:%Y-%m-%d}.',
        },
        'momentos': momentos_payload,
        'personalizacion': {
            'instrucciones_usuario': instrucciones or '',
            'contexto_usuario': contexto or '',
            'instrucciones_por_momento': [
                {
                    'momento_id': str(m.id),
                    'instrucciones': por_momento[m.id].get('instrucciones') or '',
                    'contexto': por_momento[m.id].get('contexto') or '',
                }
                for m in alcance if m.id in por_momento
            ],
        },
        'fuentes': fuentes,
        'bertopic': None,
    }


def hay_respuestas(entrada):
    return any(f['tipo'] == 'respuestas' and f['datos']['respuestas'] for f in entrada['fuentes'])
```

## Paso 2.3 — `analitica/v2/sin_datos.py`

```python
"""Salida v2 para un alcance sin ninguna respuesta, construida por el backend sin llamar a la IA
(D11 del plan). `sin_datos` es un estado ANALÍTICO válido del contrato (el frontend lo renderiza
como estado vacío); gastar una llamada cara para que un modelo produzca "no hay datos" es más
lento y menos fiable que producirlo acá. Pasa por las mismas dos capas de validación que una
respuesta del modelo (procesar.py): si no pasara, es un bug."""
from .contrato import MODO_INTEGRAL, VERSION

RESUMEN_INTEGRAL = (
    'No se registraron respuestas en ningún momento del alcance. No hay evidencia para formular '
    'hallazgos ni recomendaciones.'
)
RESUMEN_MOMENTO = (
    'No se registraron respuestas en este momento. No hay evidencia para formular hallazgos ni '
    'recomendaciones.'
)
NOTA_COBERTURA = 'No se registró ninguna respuesta para esta pregunta.'


def construir_salida_sin_datos(entrada, pipeline):
    solicitud = entrada['solicitud']
    fuentes = [
        {k: f[k] for k in ('id', 'tipo', 'etiqueta', 'momento_ids', 'pregunta_ids', 'cobertura')}
        for f in entrada['fuentes']
    ]
    cobertura = [
        {'momento_id': m['id'], 'pregunta_id': p['id'], 'estado': 'sin_datos', 'metodos': [], 'nota': NOTA_COBERTURA}
        for m in entrada['momentos'] for p in m['preguntas']
    ]
    if solicitud['modo'] == MODO_INTEGRAL:
        informes = [{
            'id': 'i1', 'momento_ids': list(solicitud['momento_ids']),
            'titulo': entrada['jornada']['nombre'], 'resumen': RESUMEN_INTEGRAL,
            'hallazgos': [], 'recomendaciones': [],
        }]
    else:
        nombres = {m['id']: m['nombre'] for m in entrada['momentos']}
        informes = [
            {
                'id': f'i{n}', 'momento_ids': [momento_id], 'titulo': nombres.get(momento_id, momento_id),
                'resumen': RESUMEN_MOMENTO, 'hallazgos': [], 'recomendaciones': [],
            }
            for n, momento_id in enumerate(solicitud['momento_ids'], start=1)
        ]
    return {
        'version': VERSION,
        'pipeline': pipeline,
        'estado': 'sin_datos',
        'alcance': {'modo': solicitud['modo'], 'jornada_id': solicitud['jornada_id'], 'momento_ids': list(solicitud['momento_ids'])},
        'fuentes': fuentes,
        'cobertura': cobertura,
        'limitaciones': [],
        'informes': informes,
        'visualizaciones': [],
    }
```

## Paso 2.4 — Verificación

```bash
source .venv/bin/activate
python -m py_compile analitica/v2/entrada.py analitica/v2/sin_datos.py
```

Comprobación semántica sin base de datos (usa el ejemplo `sin_datos` de la entrega como entrada):

```bash
python - <<'EOF'
import json, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django; django.setup()
from analitica.v2.contrato import RECURSOS
from analitica.v2.sin_datos import construir_salida_sin_datos
from analitica.v2.validacion import validar_salida
entrada = json.loads((RECURSOS / 'ejemplos/sin_datos.entrada.json').read_text())
salida = construir_salida_sin_datos(entrada, 'llm')
assert validar_salida(salida, entrada, 'llm') == [], validar_salida(salida, entrada, 'llm')
entrada['solicitud']['modo'] = 'por_momento'
salida = construir_salida_sin_datos(entrada, 'bertopic_llm')
assert validar_salida(salida, entrada, 'bertopic_llm') == [], validar_salida(salida, entrada, 'bertopic_llm')
assert len(salida['informes']) == 2
print('OK sin_datos')
EOF
```

(`django.setup()` necesita `.env`; no toca la base.)

## Paso 2.5 — Tests (escribir, no correr) — agregar a `analitica/tests_v2.py`

```python
import datetime

from django.test import TestCase

from jornadas.models import ColumnaMatrizPregunta, FilaMatrizPregunta, Jornada, Momento, OpcionPregunta, Pregunta
from participantes.models import FilaListaRespuesta, Participante, Respuesta

from .v2.entrada import construir_entrada, hay_respuestas
from .v2.sin_datos import construir_salida_sin_datos


def crear_jornada_completa():
    """Una jornada con los seis tipos de pregunta y respuestas de ambos tipos de momento. Devuelve
    un dict con todo lo creado para que los tests afirmen sobre ids concretos."""
    jornada = Jornada.objects.create(
        slug='j-v2', nombre='Jornada v2', descripcion='Objetivo de prueba',
        fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 2),
    )
    p1 = Participante.objects.create(jornada=jornada, correo_institucional='a@x.co', nombre='A', apellido='A', rol='docente')
    p2 = Participante.objects.create(jornada=jornada, correo_institucional='b@x.co', nombre='B', apellido='B', rol='docente', mesa=3, es_vocero=True)

    m1 = Momento.objects.create(jornada=jornada, orden=2, titulo='Encuesta', contexto='Ctx m1', categorias_semilla=['acceso', 'claridad'])
    q_unica = Pregunta.objects.create(momento=m1, tipo='unica', texto='¿Le sirve?', orden=1)
    o_si = OpcionPregunta.objects.create(pregunta=q_unica, texto='Sí', orden=1)
    o_no = OpcionPregunta.objects.create(pregunta=q_unica, texto='No', orden=2)
    q_multi = Pregunta.objects.create(momento=m1, tipo='multiple', texto='¿Cuáles?', orden=2, obligatoria=False)
    o_a = OpcionPregunta.objects.create(pregunta=q_multi, texto='A', orden=1)
    o_b = OpcionPregunta.objects.create(pregunta=q_multi, texto='B', orden=2)
    q_abierta = Pregunta.objects.create(momento=m1, tipo='abierta', texto='¿Por qué?', orden=3)
    q_inactiva_con_datos = Pregunta.objects.create(momento=m1, tipo='abierta', texto='Vieja', orden=4, activa=False)
    Pregunta.objects.create(momento=m1, tipo='abierta', texto='Vieja sin datos', orden=5, activa=False)

    r = Respuesta.objects.create(pregunta=q_unica, participante=p1); r.opciones.set([o_si])
    r = Respuesta.objects.create(pregunta=q_unica, participante=p2); r.opciones.set([o_no])
    r = Respuesta.objects.create(pregunta=q_multi, participante=p1); r.opciones.set([o_a, o_b])
    Respuesta.objects.create(pregunta=q_abierta, participante=p1, texto_libre='Necesito una opción al final de la tarde.')
    Respuesta.objects.create(pregunta=q_abierta, participante=p2, texto_libre='   ')
    Respuesta.objects.create(pregunta=q_inactiva_con_datos, participante=p1, texto_libre='dato viejo')

    m2 = Momento.objects.create(jornada=jornada, orden=1, titulo='Mesa', tipo='mesa')
    q_matriz = Pregunta.objects.create(momento=m2, tipo='matriz', texto='Mapa', orden=1)
    f1 = FilaMatrizPregunta.objects.create(pregunta=q_matriz, texto='Fila 1', orden=1)
    c1 = ColumnaMatrizPregunta.objects.create(pregunta=q_matriz, texto='Col 1', orden=1)
    c2 = ColumnaMatrizPregunta.objects.create(pregunta=q_matriz, texto='Col 2', orden=2)
    Respuesta.objects.create(pregunta=q_matriz, mesa=3, fila=f1, columna=c1, texto_libre='x')
    Respuesta.objects.create(pregunta=q_matriz, mesa=3, fila=f1, columna=c2, texto_libre='y')
    q_lista = Pregunta.objects.create(momento=m2, tipo='lista', texto='Registros', orden=2, filas_adicionales=True)
    cl = ColumnaMatrizPregunta.objects.create(pregunta=q_lista, texto='Nombre', orden=1)
    fl = FilaListaRespuesta.objects.create(pregunta=q_lista, mesa=3, orden=1)
    Respuesta.objects.create(pregunta=q_lista, mesa=3, fila_lista=fl, columna=cl, texto_libre='Juan')
    q_audio = Pregunta.objects.create(momento=m2, tipo='audio', texto='Cuéntanos', orden=3)
    Respuesta.objects.create(pregunta=q_audio, mesa=3, texto_libre='transcripción')

    return {
        'jornada': jornada, 'm1': m1, 'm2': m2, 'q_unica': q_unica, 'q_multi': q_multi, 'q_abierta': q_abierta,
        'q_inactiva_con_datos': q_inactiva_con_datos, 'q_matriz': q_matriz, 'q_lista': q_lista, 'q_audio': q_audio,
        'o_si': o_si, 'o_no': o_no, 'o_a': o_a, 'o_b': o_b, 'f1': f1, 'c1': c1, 'c2': c2, 'fl': fl, 'p1': p1, 'p2': p2,
    }


class EntradaNormalizadaTests(TestCase):
    def setUp(self):
        self.d = crear_jornada_completa()

    def _fuente(self, entrada, fid):
        return next(f for f in entrada['fuentes'] if f['id'] == fid)

    def test_integral_incluye_todos_los_momentos_por_orden(self):
        entrada = construir_entrada(self.d['jornada'], 'integral', [], contexto='C', instrucciones='I')
        self.assertEqual(entrada['solicitud'], {'modo': 'integral', 'jornada_id': str(self.d['jornada'].id),
                                                'momento_ids': [str(self.d['m2'].id), str(self.d['m1'].id)]})
        self.assertEqual(entrada['personalizacion']['contexto_usuario'], 'C')
        self.assertIsNone(entrada['bertopic'])
        self.assertTrue(hay_respuestas(entrada))

    def test_por_momento_respeta_orden_y_personalizacion(self):
        m1, m2 = self.d['m1'], self.d['m2']
        entrada = construir_entrada(self.d['jornada'], 'por_momento', [m1, m2], personalizacion_momentos=[
            {'momento': m1.id, 'contexto': 'ctx1', 'instrucciones': 'ins1'},
        ])
        self.assertEqual(entrada['solicitud']['momento_ids'], [str(m2.id), str(m1.id)])
        self.assertEqual(entrada['personalizacion']['instrucciones_por_momento'],
                         [{'momento_id': str(m1.id), 'instrucciones': 'ins1', 'contexto': 'ctx1'}])

    def test_inventario_y_contexto_del_momento(self):
        entrada = construir_entrada(self.d['jornada'], 'por_momento', [self.d['m1']])
        momento = entrada['momentos'][0]
        ids = [p['id'] for p in momento['preguntas']]
        self.assertIn(str(self.d['q_inactiva_con_datos'].id), ids)
        self.assertEqual(len(ids), 4)  # unica, multiple, abierta, inactiva con datos
        self.assertIn('Categorías temáticas de referencia', momento['contexto'])
        self.assertTrue(momento['contexto'].startswith('Ctx m1'))
        unica = momento['preguntas'][0]
        self.assertEqual(unica['tipo'], 'unica')
        self.assertEqual([o['etiqueta'] for o in unica['opciones']], ['Sí', 'No'])
        self.assertEqual(unica['reglas_elegibilidad']['unidad_esperada'], 'persona')
        self.assertIsNone(unica['reglas_elegibilidad']['estructura'])

    def test_respuestas_escalares(self):
        entrada = construir_entrada(self.d['jornada'], 'por_momento', [self.d['m1']])
        fuente = self._fuente(entrada, f"f-m{self.d['m1'].id}")
        self.assertEqual(fuente['datos']['unidad_analisis'], 'respuesta_individual')
        por_pregunta = {}
        for r in fuente['datos']['respuestas']:
            por_pregunta.setdefault(r['pregunta_id'], []).append(r)
        unicas = por_pregunta[str(self.d['q_unica'].id)]
        self.assertEqual([r['valor'] for r in unicas], [str(self.d['o_si'].id), str(self.d['o_no'].id)])
        self.assertEqual(unicas[0]['sujeto_id'], f"p{self.d['p1'].id}")
        multi = por_pregunta[str(self.d['q_multi'].id)][0]
        self.assertEqual(multi['valor'], [str(self.d['o_a'].id), str(self.d['o_b'].id)])
        abiertas = por_pregunta[str(self.d['q_abierta'].id)]
        self.assertEqual(abiertas[0]['valor'], 'Necesito una opción al final de la tarde.')
        self.assertIsNone(abiertas[1]['valor'])

    def test_agregado_con_conteos_y_porcentajes(self):
        entrada = construir_entrada(self.d['jornada'], 'por_momento', [self.d['m1']])
        agg = self._fuente(entrada, f"f-agg-m{self.d['m1'].id}")
        self.assertEqual(agg['pregunta_ids'], [str(self.d['q_unica'].id), str(self.d['q_multi'].id)])
        dist = {d['pregunta_id']: d for d in agg['datos']['distribuciones']}
        unica = dist[str(self.d['q_unica'].id)]
        self.assertEqual(unica['tipo'], 'respuesta_unica')
        self.assertEqual([(c['n'], c['porcentaje']) for c in unica['categorias']], [(1, 50.0), (1, 50.0)])
        multi = dist[str(self.d['q_multi'].id)]
        self.assertEqual([c['n'] for c in multi['categorias']], [1, 1])
        base = next(b for b in agg['datos']['bases'] if b['pregunta_id'] == str(self.d['q_unica'].id))
        self.assertEqual((base['recibidas_n'], base['validas_n'], base['ausentes_n']), (2, 2, 0))

    def test_matriz_lista_y_audio_de_mesa(self):
        entrada = construir_entrada(self.d['jornada'], 'por_momento', [self.d['m2']])
        momento = entrada['momentos'][0]
        matriz = momento['preguntas'][0]
        self.assertEqual(matriz['reglas_elegibilidad']['unidad_esperada'], 'mesa')
        self.assertEqual(matriz['reglas_elegibilidad']['estructura']['filas'], [{'id': str(self.d['f1'].id), 'etiqueta': 'Fila 1'}])
        self.assertFalse(matriz['reglas_elegibilidad']['estructura']['permite_repetir_filas'])
        lista = momento['preguntas'][1]
        self.assertEqual(lista['reglas_elegibilidad']['estructura']['filas'], [])
        self.assertTrue(lista['reglas_elegibilidad']['estructura']['permite_repetir_filas'])
        fuente = self._fuente(entrada, f"f-m{self.d['m2'].id}")
        self.assertEqual(fuente['datos']['unidad_analisis'], 'respuesta_de_mesa')
        self.assertNotIn(f"f-agg-m{self.d['m2'].id}", [f['id'] for f in entrada['fuentes']])
        respuestas = fuente['datos']['respuestas']
        self.assertEqual(respuestas[0]['id'], f"r-q{self.d['q_matriz'].id}-mesa-3")
        self.assertEqual(respuestas[0]['sujeto_id'], 'mesa-3')
        celdas = respuestas[0]['valor']['celdas']
        self.assertEqual([c['valor'] for c in celdas], ['x', 'y'])
        self.assertEqual(celdas[0]['fila_id'], str(self.d['f1'].id))
        self.assertIsNone(celdas[0]['fila_lista_id'])
        self.assertEqual(respuestas[1]['valor']['celdas'][0]['fila_lista_id'], str(self.d['fl'].id))
        self.assertIsNone(respuestas[1]['valor']['celdas'][0]['fila_id'])
        self.assertEqual(respuestas[2]['valor'], 'transcripción')


class SalidaSinDatosTests(TestCase):
    def test_jornada_vacia_produce_salida_valida_en_ambos_modos(self):
        jornada = Jornada.objects.create(slug='j-vacia', nombre='Vacía', fecha_inicio=datetime.date(2026, 9, 1), fecha_fin=datetime.date(2026, 9, 1))
        m = Momento.objects.create(jornada=jornada, orden=1, titulo='M')
        Pregunta.objects.create(momento=m, tipo='abierta', texto='¿?', orden=1)
        for modo in ('integral', 'por_momento'):
            entrada = construir_entrada(jornada, modo, [m])
            self.assertFalse(hay_respuestas(entrada))
            salida = construir_salida_sin_datos(entrada, 'llm')
            self.assertEqual(validar_salida(salida, entrada, 'llm'), [], modo)
            self.assertEqual(salida['estado'], 'sin_datos')
            self.assertEqual(salida['cobertura'][0]['estado'], 'sin_datos')
```

`python -m py_compile analitica/tests_v2.py` debe pasar.

## Paso 2.6 — Commit

```bash
git status --short
git add analitica/v2/entrada.py analitica/v2/sin_datos.py analitica/tests_v2.py
git commit -m "feat(v2): entrada normalizada desde la base de datos y salida sin_datos sin IA

construir_entrada arma el sobre del contrato (solicitud, jornada, momentos con inventario
completo, personalización, fuentes respuestas+agregado) con IDs string y orden determinista,
porque los JSON Pointers de citas y documentos dependen de ese orden. Los conteos de preguntas
cerradas los calcula el backend (fuente agregado): los números nunca dependen del LLM. Un alcance
sin respuestas produce su salida sin_datos acá mismo, validada, sin gastar una llamada."
```

## Criterios de "hecho"

- [ ] `entrada.py` y `sin_datos.py` compilan; el script de verificación imprime `OK sin_datos`.
- [ ] Tests agregados y compilando (no corridos).
- [ ] Commit sin `Dockerfile`/`docker-compose.yml`.
