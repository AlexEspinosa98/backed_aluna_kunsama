"""Ajuste de un análisis ya terminado (HU-102).

Toma un análisis con salida `kunsamu.analisis/v2` (cualquiera de los cuatro: `Reporte`,
`AnalisisMomentoIA`, `AnalisisJornadaIA`, `AnalisisV2` — incluido otro ajuste) y se lo vuelve a
pasar a OpenAI con instrucciones y contexto nuevos, para obtener una versión mejorada. El resultado
es un `AnalisisV2` nuevo (`es_ajuste=True`): el original no se toca, y el ajuste hereda todo lo que
ya funciona con un `AnalisisV2` (visor, lista unificada, infografía, resumen para presentación, y
volver a ajustarlo).

Qué recibe el modelo:
- **La entrada original EXACTA** del análisis de origen (`origen.entrada`), sin recalcular: los
  JSON Pointers de las citas y métricas del análisis previo siguen resolviendo contra las mismas
  fuentes, y la salida ajustada se valida contra esa misma entrada con las reglas de siempre. Si las
  respuestas cambiaron desde entonces, el ajuste NO las ve — para eso se pide un análisis nuevo.
- **`entrada.ajuste`**: el análisis previo, las instrucciones y el contexto del ajuste.
- Adjuntos nuevos opcionales (HU-101), que se suman como fuente o como contexto.

System prompt: el activo del análisis para su pipeline MÁS el activo de tipo `ajuste_analisis`, que
explica el bloque `ajuste`. `version_prompt` guarda las dos referencias unidas por `+`
(`analisis_llm#5+ajuste_analisis#1`), y el intento y la reparación usan exactamente esas.

Corre siempre en el modo segundo plano de OpenAI (`v2.background`): la entrada de una jornada
grande ya ronda el millón de caracteres y el análisis previo se suma encima.
"""
import copy
import json

from django.db import close_old_connections

from auditoria.openai_cliente import auditar_llamadas

from .v2 import background
from .v2.adjuntos import bloque_referencias, resolver_adjuntos
from .v2.contrato import TIPO_PROMPT_POR_PIPELINE, VERSION, VERSION_ESQUEMA
from .v2.migracion_contrato import visualizaciones_a_v2_1
from .v2.procesar import MAX_CARACTERES_ENTRADA

# Viaja dentro de `entrada.ajuste` para que la regla esté junto al material (metadato del backend).
NOTA_AJUSTE = (
    'Ajuste de un análisis ya entregado. `analisis_previo` es la salida entregada para esta misma '
    'entrada; devuelve el análisis COMPLETO ajustado según `instrucciones_ajuste`, con el mismo '
    'contrato. El análisis previo no es evidencia: la evidencia sigue siendo `fuentes`.'
)


def analisis_previo(origen):
    """La salida del origen, lista para que el modelo la reescriba en la versión vigente del
    contrato (v2.1): las visualizaciones de un análisis v2 se llevan a la forma v2.1."""
    from .models import resultado_v2_de

    previo = copy.deepcopy(resultado_v2_de(origen))
    previo['version'] = VERSION
    previo['visualizaciones'] = visualizaciones_a_v2_1(previo.get('visualizaciones') or [])
    return previo


def entrada_del_ajuste(origen, jornada, instrucciones, contexto='', adjuntos=None, diagnostico=None):
    """La entrada del origen, intacta, más el bloque `ajuste` y los adjuntos nuevos. Lanza
    `ValueError` si algo no se puede armar (adjunto ilegible, tamaño)."""
    entrada = copy.deepcopy(origen.entrada)

    fuentes, referencias, notas = resolver_adjuntos(jornada, adjuntos or [])
    ids_fuentes = {f['id'] for f in entrada['fuentes']}
    # Un adjunto que el análisis de origen ya tenía como fuente no se duplica (mismo id, mismo texto
    # salvo que se haya corregido; se conserva el de la entrada original para no mover sus citas).
    entrada['fuentes'].extend(f for f in fuentes if f['id'] not in ids_fuentes)
    if referencias:
        previas = (entrada.get('referencias') or {}).get('documentos') or []
        ids_previas = {r['id'] for r in previas}
        entrada['referencias'] = bloque_referencias(previas + [r for r in referencias if r['id'] not in ids_previas])
    if diagnostico is not None and notas:
        diagnostico['adjuntos'] = notas

    entrada['ajuste'] = {
        'nota': NOTA_AJUSTE,
        'instrucciones_ajuste': instrucciones,
        'contexto_ajuste': contexto or '',
        'analisis_previo': analisis_previo(origen),
    }
    largo = len(json.dumps(entrada, ensure_ascii=False, separators=(',', ':')))
    if largo > MAX_CARACTERES_ENTRADA:
        raise ValueError(
            f'La entrada del ajuste es demasiado grande para una sola llamada ({largo} caracteres, '
            f'máximo {MAX_CARACTERES_ENTRADA}): el análisis original más el análisis previo no caben. '
            'Ajusta un análisis por momento en vez del integral.'
        )
    return entrada


def referencia_de_prompts(pipeline):
    from .models import SystemPrompt

    base = SystemPrompt.activo_de(TIPO_PROMPT_POR_PIPELINE[pipeline])
    ajuste = SystemPrompt.activo_de(SystemPrompt.TIPO_AJUSTE_ANALISIS)
    return f'{base.referencia}+{ajuste.referencia}'


def iniciar_ajuste(analisis):
    """Arma y guarda la entrada, fija las versiones de prompt y lanza el primer intento. Nunca
    lanza: cualquier falla deja el ajuste en error con el motivo."""
    analisis.diagnostico = {'intentos': [], 'modo': 'background', 'store': background.GUARDAR_EN_OPENAI}
    try:
        origen = analisis.origen_ajuste
        if origen is None:
            raise ValueError('El análisis de origen ya no existe.')
        analisis.entrada = entrada_del_ajuste(
            origen, analisis.jornada, analisis.instrucciones, analisis.contexto, analisis.adjuntos,
            diagnostico=analisis.diagnostico,
        )
        analisis.version_prompt = referencia_de_prompts(analisis.pipeline)
        analisis.version_esquema = VERSION_ESQUEMA
        analisis.save(update_fields=['entrada', 'version_prompt', 'version_esquema', 'diagnostico', 'actualizado_en'])
        # Desde lo guardado, igual que el análisis integral: intento y reparación mandan el mismo texto.
        analisis.refresh_from_db(fields=['entrada'])
        background._lanzar(analisis, analisis.FASE_INTENTO)
    except Exception as exc:  # noqa: BLE001
        background._terminar_con_error(analisis, str(exc))


@auditar_llamadas('analitica.AnalisisV2')
def procesar_ajuste(analisis_id):
    """Corre en un hilo: lanza y consulta hasta que termina. Si el hilo muere (reinicio), el cron
    `consultar_analisis_background` sigue desde donde quedó."""
    close_old_connections()
    from .models import AnalisisV2

    analisis = None
    try:
        analisis = AnalisisV2.objects.select_related('jornada').get(pk=analisis_id)
        analisis.estado = AnalisisV2.ESTADO_PROCESANDO
        analisis.save(update_fields=['estado', 'actualizado_en'])
        iniciar_ajuste(analisis)
        analisis.refresh_from_db(fields=['estado'])
        if analisis.estado == AnalisisV2.ESTADO_PROCESANDO:
            background.seguir_hasta_terminar(analisis.id, AnalisisV2)
    except Exception as exc:  # noqa: BLE001 — nunca debe dejar el hilo morir en silencio
        if analisis is not None:
            background._terminar_con_error(analisis, str(exc))
    finally:
        close_old_connections()
