"""Servicio de copia profunda para el banco de instrumentos (plantillas de `Momento`).

Bajo D1-A (docs/banco_instrumentos/02_decisiones.md) el momento ES la plantilla: no hay modelo
de "plantilla" aparte, `copiar_momento` simplemente clona un `Momento` (con todo su árbol de
preguntas/opciones/filas/columnas) dentro de otra jornada — o de la misma, para duplicar. Ver
docs/banco_instrumentos/03_modelo_de_datos.md §4 para el algoritmo detallado que esto implementa,
incluida la corrección D11-B (se copian TODAS las preguntas, activas o no, conservando `activa`).
"""
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import ColumnaMatrizPregunta, FilaMatrizPregunta, Jornada, Momento, OpcionPregunta, Pregunta, RolJornada


def _bloquear_jornada(jornada):
    """select_for_update sobre la fila de la jornada destino — sirve tanto para calcular
    `orden = max(orden)+1` sin carrera (U22) como para que la validación de `orden` explícito ya
    ocupado no quede expuesta a la misma carrera (dos POST con el mismo `orden` a la vez)."""
    return Jornada.objects.select_for_update().get(pk=jornada.pk)


def _resolver_orden(jornada_destino, orden):
    _bloquear_jornada(jornada_destino)
    if orden is None:
        ultimo = Momento.objects.filter(jornada=jornada_destino).aggregate(Max('orden'))['orden__max']
        return (ultimo or 0) + 1
    if Momento.objects.filter(jornada=jornada_destino, orden=orden).exists():
        raise ValidationError({'orden': ['Ya existe un momento con ese orden en la jornada.']})
    return orden


def _origen_info(origen, usuario):
    """Snapshot documental (D14): sobrevive al borrado del original porque no depende de la FK
    `momento_origen` (SET_NULL) para reconstruirse."""
    return {
        'momento_id': origen.id,
        'titulo': origen.titulo,
        'jornada_id': origen.jornada_id,
        'jornada_slug': origen.jornada.slug,
        'jornada_nombre': origen.jornada.nombre,
        'creado_por': origen.creado_por.username if origen.creado_por_id else None,
        'copiado_en': timezone.now().isoformat(),
        'copiado_por': usuario.username if usuario is not None else None,
    }


def _advertencias_roles(momento_copia, preguntas_copiadas, jornada_destino):
    """D10-A: `roles_permitidos` se copia tal cual (es contenido, no un catálogo obligatorio) —
    esto solo agrega una advertencia informativa si algún rol usado no existe como
    `RolJornada.nombre` en la jornada destino. Nada se rompe: en tiempo de ejecución
    `roles_permitidos` se compara contra `Participante.rol` como texto libre."""
    roles_destino = set(RolJornada.objects.filter(jornada=jornada_destino).values_list('nombre', flat=True))
    roles_usados = set(momento_copia.roles_permitidos or [])
    for pregunta in preguntas_copiadas:
        roles_usados.update(pregunta.roles_permitidos or [])
    faltantes = sorted(roles_usados - roles_destino)
    if not faltantes:
        return []
    lista = ', '.join(f'«{rol}»' for rol in faltantes)
    plural = 'es' if len(faltantes) > 1 else ''
    return [
        f'Los rol{plural} {lista} no existen en la jornada destino; se conservaron en '
        f'roles_permitidos igual.'
    ]


@transaction.atomic
def copiar_momento(origen, jornada_destino, usuario, *, orden=None, titulo=None,
                    visibilidad=Momento.VISIBILIDAD_PRIVADO):
    """Copia profunda de `origen` (preguntas, opciones, filas y columnas incluidas) dentro de
    `jornada_destino`. Devuelve `(copia, advertencias)`.

    Copiar dentro de la misma jornada (duplicar) es el mismo código: alcanza con que
    `jornada_destino == origen.jornada`.

    Garantías: el original solo se lee, nunca se modifica; la copia no comparte ninguna fila con
    el original (ni preguntas, ni opciones); si algo falla a mitad de camino, `transaction.atomic`
    revierte todo (U23) — nunca queda un momento a medias.
    """
    advertencias = []
    orden = _resolver_orden(jornada_destino, orden)

    copia = Momento.objects.create(
        jornada=jornada_destino,
        orden=orden,
        titulo=titulo or origen.titulo,
        slug='',  # save() lo regenera en la jornada destino (unique_together jornada+slug)
        contexto=origen.contexto,
        tipo=origen.tipo,
        categorias_semilla=origen.categorias_semilla,
        mesas_permitidas=origen.mesas_permitidas,
        roles_permitidos=origen.roles_permitidos,
        permite_carga_archivo=origen.permite_carga_archivo,
        activo=True,  # la copia es un momento nuevo en la jornada destino: el usuario decide su estado ahí
        visibilidad=visibilidad,
        creado_por=usuario,
        momento_origen=origen,
        origen_info=_origen_info(origen, usuario),
    )

    # D11-B: se copian TODAS las preguntas del origen (activas o no) conservando `activa` tal
    # cual — antes solo se copiaban las activas, pero el equipo decidió que una plantilla debe
    # traer su árbol completo (el destino decide después si las reactiva).
    preguntas_origen = list(
        Pregunta.objects.filter(momento=origen).order_by('orden')
    )
    preguntas_nuevas = [
        Pregunta(
            momento=copia,
            tipo=p.tipo,
            texto=p.texto,
            orden=p.orden,
            obligatoria=p.obligatoria,
            activa=p.activa,
            filas_adicionales=p.filas_adicionales,
            mesas_permitidas=p.mesas_permitidas,
            roles_permitidos=p.roles_permitidos,
            depende_de_opcion=None,  # se remapea en la segunda pasada, una vez existan las opciones copiadas
        )
        for p in preguntas_origen
    ]
    # bulk_create en Postgres (nuestro backend) devuelve los objetos CON pk asignado, así que
    # `preguntas_creadas` ya sirve para construir el mapa de ids origen -> copia.
    preguntas_creadas = Pregunta.objects.bulk_create(preguntas_nuevas)
    mapa_preguntas = {
        p_origen.id: p_nueva for p_origen, p_nueva in zip(preguntas_origen, preguntas_creadas)
    }

    opciones_por_pregunta_origen = {}
    opciones_nuevas = []
    filas_nuevas = []
    columnas_nuevas = []
    for p_origen in preguntas_origen:
        p_nueva = mapa_preguntas[p_origen.id]
        opciones_origen = list(OpcionPregunta.objects.filter(pregunta=p_origen).order_by('orden'))
        opciones_por_pregunta_origen[p_origen.id] = opciones_origen
        opciones_nuevas.extend(
            OpcionPregunta(pregunta=p_nueva, texto=o.texto, orden=o.orden) for o in opciones_origen
        )
        filas_nuevas.extend(
            FilaMatrizPregunta(pregunta=p_nueva, texto=f.texto, orden=f.orden)
            for f in FilaMatrizPregunta.objects.filter(pregunta=p_origen).order_by('orden')
        )
        columnas_nuevas.extend(
            ColumnaMatrizPregunta(pregunta=p_nueva, texto=c.texto, orden=c.orden)
            for c in ColumnaMatrizPregunta.objects.filter(pregunta=p_origen).order_by('orden')
        )

    opciones_creadas = OpcionPregunta.objects.bulk_create(opciones_nuevas) if opciones_nuevas else []
    if filas_nuevas:
        FilaMatrizPregunta.objects.bulk_create(filas_nuevas)
    if columnas_nuevas:
        ColumnaMatrizPregunta.objects.bulk_create(columnas_nuevas)

    # Reconstruye mapa_opciones[id_origen] = copia recorriendo en el mismo orden en que se
    # insertaron: bulk_create conserva el orden de la lista que se le pasó.
    mapa_opciones = {}
    cursor = 0
    for p_origen in preguntas_origen:
        for o_origen in opciones_por_pregunta_origen[p_origen.id]:
            mapa_opciones[o_origen.id] = opciones_creadas[cursor]
            cursor += 1

    # Segunda pasada: depende_de_opcion (D9-A). Si la opción origen está DENTRO del árbol que se
    # acaba de copiar (mapa_opciones) se remapea a la copia; si apunta a una opción de OTRO
    # momento (fuera de este árbol) se deja NULL y se avisa — la copia queda válida igual.
    por_actualizar = []
    for p_origen in preguntas_origen:
        if p_origen.depende_de_opcion_id is None:
            continue
        opcion_nueva = mapa_opciones.get(p_origen.depende_de_opcion_id)
        p_nueva = mapa_preguntas[p_origen.id]
        if opcion_nueva is not None:
            p_nueva.depende_de_opcion = opcion_nueva
            por_actualizar.append(p_nueva)
        else:
            advertencias.append(
                f'La pregunta «{p_origen.texto}» dependía de una opción de otro momento; la '
                f'dependencia se quitó.'
            )
    if por_actualizar:
        Pregunta.objects.bulk_update(por_actualizar, ['depende_de_opcion'])

    advertencias.extend(_advertencias_roles(copia, preguntas_creadas, jornada_destino))

    return copia, advertencias
