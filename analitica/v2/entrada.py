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
