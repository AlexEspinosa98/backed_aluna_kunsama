"""Modo segundo plano de OpenAI para el análisis integral de la jornada (HU-98) y para el resumen
de un análisis para presentación (HU-99). El ciclo (lanzar → consultar → validar → reparar →
publicar) es común; lo propio de cada uno vive en un adaptador (`ADAPTADORES`): qué esquema de
salida se pide y cómo se valida lo que vuelve.

En el modo de siempre (`procesar.ejecutar_analisis_v2`) el servidor abre una conexión y espera la
respuesta; si pasan `KUNSAMU_V2_TIMEOUT_SECONDS`, corta y el trabajo — pagado — se pierde. Acá se
le pide a OpenAI la respuesta con `background: true` (Responses API): OpenAI la procesa por su
cuenta y devuelve un id al instante; el análisis guarda ese id y se consulta hasta que termina.

    iniciar_analisis_background(analisis)   prepara la entrada (misma que el modo de siempre) y
                                            lanza el intento; o resuelve sin IA si no hay datos
    avanzar_analisis_background(id)         consulta una vez y avanza: sigue esperando, valida y
                                            publica, lanza la reparación, o marca error
    seguir_hasta_terminar(id)               el hilo del análisis consulta cada 30 s
    (comando consultar_analisis_background) el cron retoma lo que un reinicio dejó a medias

Lo que NO cambia respecto del modo de siempre: la entrada, el system prompt activo, el esquema
estricto de salida, la validación y la reparación (`preparar_entrada_v2`/`evaluar_salida_v2`).

**Sin `store`** (decisión de producto, `KUNSAMU_V2_BACKGROUND_STORE=0`): OpenAI no guarda la
respuesta más allá de ~10 minutos. El hilo consulta cada 30 s y el cron cada 5 min, así que se
recoge a tiempo; si se perdiera (servidor caído justo esa ventana), el análisis termina en error
explicándolo, nunca queda colgado.
"""
import json
import logging
import os
import time
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .contrato import MODO_INTEGRAL, PIPELINE_LLM, cargar_esquema
from .llm import (
    DEFAULT_MODEL, MAX_OUTPUT_TOKENS, MODELO_USADO_LABEL, NOMBRE_ESQUEMA, REASONING_EFFORT,
    cargar_json_estricto, esquema_para_openai, turnos_de_reparacion,
)
from .procesar import (
    MODELO_USADO_SIN_DATOS, aplicar_resultado, evaluar_salida_v2, guardador_de_entrada,
    preparar_entrada_v2,
)

logger = logging.getLogger(__name__)

ACTIVO = os.environ.get('KUNSAMU_V2_BACKGROUND_JORNADA', '1') == '1'
GUARDAR_EN_OPENAI = os.environ.get('KUNSAMU_V2_BACKGROUND_STORE', '0') == '1'
INTERVALO_CONSULTA_SEGUNDOS = int(os.environ.get('KUNSAMU_V2_BACKGROUND_INTERVALO', '30'))
# Tope de seguridad: pasado este tiempo se cancela en OpenAI (para no pagar algo que nadie va a
# recoger) y el análisis termina en error.
DURACION_MAXIMA = timedelta(minutes=int(os.environ.get('KUNSAMU_V2_BACKGROUND_MAX_MINUTOS', '120')))
ESTADOS_EN_CURSO = ('queued', 'in_progress')


# --- llamadas a OpenAI ----------------------------------------------------------------------------
def _cliente():
    from auditoria.openai_cliente import cliente_openai

    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY no está configurada en el entorno del servidor (.env).')
    return cliente_openai('analisis_v2_background', api_key=api_key)


def crear_respuesta(system, user, modelo, esfuerzo, flex, reparacion=None, esquema=None):
    """Lanza la respuesta en segundo plano y devuelve `(response, notas)`. Sin reintentos
    automáticos al crear: un reintento por un corte de red podría dejar DOS análisis corriendo
    (y cobrándose) en OpenAI. Si Flex no tiene capacidad (429, que OpenAI no cobra), se lanza en
    el tier normal y queda anotado."""
    import openai

    entrada = [{'role': 'user', 'content': user}]
    if reparacion:
        entrada.extend(turnos_de_reparacion(reparacion))
    kwargs = dict(
        model=modelo, instructions=system, input=entrada, background=True,
        store=GUARDAR_EN_OPENAI, max_output_tokens=MAX_OUTPUT_TOKENS,
        text={'format': {
            'type': 'json_schema', 'name': NOMBRE_ESQUEMA, 'strict': True,
            'schema': esquema or esquema_para_openai(cargar_esquema()),
        }},
    )
    if esfuerzo:
        kwargs['reasoning'] = {'effort': esfuerzo}
    cliente = _cliente().with_options(max_retries=0)
    notas = {}
    if flex:
        try:
            return cliente.responses.create(service_tier='flex', **kwargs), notas
        except openai.RateLimitError as exc:
            notas['flex_no_disponible'] = str(exc)[:300]
    return cliente.responses.create(**kwargs), notas


def consultar_respuesta(response_id):
    return _cliente().responses.retrieve(response_id)


def cancelar_respuesta(response_id):
    """Best-effort: si no se puede cancelar, solo se registra."""
    try:
        _cliente().responses.cancel(response_id)
    except Exception:  # noqa: BLE001
        logger.warning('No se pudo cancelar la respuesta %s en OpenAI', response_id, exc_info=True)


# --- orquestación ---------------------------------------------------------------------------------
def _opciones(analisis):
    return {
        'modelo': analisis.modelo_solicitado or DEFAULT_MODEL,
        'esfuerzo': analisis.esfuerzo_solicitado or REASONING_EFFORT,
        'flex': analisis.flex,
    }


def _system_y_user(analisis):
    """El system prompt de la versión con que se preparó la corrida (inmutable, HU-92) y el user
    serializado DESDE LA ENTRADA GUARDADA. Se arma igual en el intento y en la reparación: jsonb
    reordena las claves al guardar, y si el intento usara la entrada en memoria el texto cambiaría
    entre llamadas y la reparación perdería la caché de OpenAI (entrada ~20 veces más barata).

    `version_prompt` puede componer varias versiones con `+` (un ajuste, HU-102:
    `analisis_llm#5+ajuste_analisis#1`): el system es su contenido en ese orden."""
    from analitica.models import SystemPrompt

    partes = []
    for referencia in analisis.version_prompt.split('+'):
        tipo, version = referencia.split('#')
        partes.append(SystemPrompt.objects.get(tipo=tipo, version=int(version)).contenido.rstrip())
    system = '\n\n'.join(partes)
    user = json.dumps(analisis.entrada, ensure_ascii=False, separators=(',', ':'))
    return system, user


def _lanzar(analisis, fase, reparacion=None):
    system, user = _system_y_user(analisis)
    opciones = _opciones(analisis)
    adaptador = adaptador_de(type(analisis))
    respuesta, notas = crear_respuesta(
        system, user, reparacion=reparacion, esquema=adaptador.esquema(), **opciones,
    )
    intentos = analisis.diagnostico.setdefault('intentos', [])
    intentos.append({
        'n': len(intentos) + 1, 'fase': fase, 'response_id': respuesta.id,
        'lanzado_en': timezone.now().isoformat(), 'tier': getattr(respuesta, 'service_tier', None),
        **opciones, **notas,
    })
    analisis.respuesta_openai_id = respuesta.id
    analisis.fase_openai = fase
    analisis.consultado_en = timezone.now()
    analisis.save(update_fields=[
        'respuesta_openai_id', 'fase_openai', 'consultado_en', 'diagnostico', 'actualizado_en',
    ])


def _terminar_con_error(analisis, mensaje):
    analisis.estado = analisis.ESTADO_ERROR
    analisis.error_mensaje = mensaje[:4000]
    analisis.save(update_fields=['estado', 'error_mensaje', 'diagnostico', 'actualizado_en'])


def iniciar_analisis_background(analisis):
    """Prepara la entrada y lanza el primer intento. Nunca lanza: cualquier falla deja el análisis
    en error con el motivo."""
    analisis.diagnostico = {'bertopic': [], 'intentos': [], 'modo': 'background', 'store': GUARDAR_EN_OPENAI}
    try:
        preparado = preparar_entrada_v2(
            analisis.jornada, MODO_INTEGRAL, [], PIPELINE_LLM,
            contexto=analisis.contexto, instrucciones=analisis.instrucciones,
            referencia=f'analisis-jornada-{analisis.id}',
            al_guardar_entrada=guardador_de_entrada(analisis), diagnostico=analisis.diagnostico,
            adjuntos=analisis.adjuntos,
        )
        if preparado['user'] is None:
            aplicar_resultado(analisis, {
                'ok': True, 'salida': preparado['salida_sin_datos'], 'error': None,
                'modelo_usado': MODELO_USADO_SIN_DATOS, 'prompt_usado': '',
                'diagnostico': analisis.diagnostico,
            })
            return
        analisis.refresh_from_db(fields=['entrada', 'version_prompt', 'version_esquema'])
        _lanzar(analisis, analisis.FASE_INTENTO)
    except Exception as exc:  # noqa: BLE001
        _terminar_con_error(analisis, str(exc))


def _texto_de(respuesta):
    """El JSON de salida, o un error legible si el modelo se negó."""
    for item in getattr(respuesta, 'output', None) or []:
        for contenido in getattr(item, 'content', None) or []:
            if getattr(contenido, 'type', '') == 'refusal':
                raise RuntimeError(f'El proveedor rechazó la solicitud: {contenido.refusal}')
    texto = (respuesta.output_text or '').strip()
    if not texto:
        raise RuntimeError('OpenAI no devolvió contenido.')
    return texto


def _uso(respuesta):
    uso = getattr(respuesta, 'usage', None)
    if uso is None:
        return None
    detalle = getattr(uso, 'input_tokens_details', None)
    return {
        'input_tokens': uso.input_tokens, 'output_tokens': uso.output_tokens,
        'cached_tokens': getattr(detalle, 'cached_tokens', None),
        'reasoning_tokens': getattr(getattr(uso, 'output_tokens_details', None), 'reasoning_tokens', None),
    }


def avanzar_analisis_background(analisis_id):
    """El paso de `avanzar_en_segundo_plano` para un análisis integral de la jornada."""
    from analitica.models import AnalisisJornadaIA

    return avanzar_en_segundo_plano(AnalisisJornadaIA, analisis_id)


def avanzar_en_segundo_plano(Modelo, registro_id):
    """Consulta UNA vez la respuesta en curso del registro y lo avanza. Devuelve True si ya no está
    esperando a OpenAI. Seguro de llamar desde el hilo y desde el cron a la vez: la fila se
    bloquea y el que llega segundo no hace nada."""
    import openai

    adaptador = adaptador_de(Modelo)
    with transaction.atomic():
        analisis = (
            Modelo.objects.select_for_update(skip_locked=True)
            .filter(pk=registro_id, estado=Modelo.ESTADO_PROCESANDO)
            .exclude(respuesta_openai_id='').first()
        )
        if analisis is None:
            return not Modelo.objects.filter(pk=registro_id, estado=Modelo.ESTADO_PROCESANDO).exists()

        intento = analisis.diagnostico['intentos'][-1]
        try:
            respuesta = consultar_respuesta(analisis.respuesta_openai_id)
        except openai.NotFoundError:
            _terminar_con_error(analisis, (
                'OpenAI ya no tiene la respuesta de este análisis: sin `store`, la borra unos 10 '
                'minutos después de terminar y no se alcanzó a recoger (¿el servidor estuvo caído?). '
                'Vuelve a lanzar el análisis.'
            ))
            return True
        except Exception as exc:  # noqa: BLE001 — falla transitoria: se reintenta en la próxima consulta
            intento['ultimo_error_consulta'] = str(exc)[:300]
            analisis.consultado_en = timezone.now()
            analisis.save(update_fields=['consultado_en', 'diagnostico', 'actualizado_en'])
            return False

        if respuesta.status in ESTADOS_EN_CURSO:
            if timezone.now() - analisis.creado_en > DURACION_MAXIMA:
                cancelar_respuesta(analisis.respuesta_openai_id)
                _terminar_con_error(analisis, (
                    f'El análisis superó el máximo de {int(DURACION_MAXIMA.total_seconds() // 60)} '
                    'minutos esperando a OpenAI y se canceló.'
                ))
                return True
            analisis.consultado_en = timezone.now()
            analisis.save(update_fields=['consultado_en', 'actualizado_en'])
            return False

        intento.update({
            'estado_openai': respuesta.status, 'terminado_en': timezone.now().isoformat(),
            'usage': _uso(respuesta), 'tier': getattr(respuesta, 'service_tier', intento.get('tier')),
        })
        if respuesta.status != 'completed':
            detalle = getattr(respuesta, 'error', None) or getattr(respuesta, 'incomplete_details', None)
            _terminar_con_error(analisis, (
                f'OpenAI terminó la respuesta en estado "{respuesta.status}": {detalle}. Si es por '
                '`max_output_tokens`, la salida no cupo en KUNSAMU_V2_MAX_OUTPUT_TOKENS.'
            ))
            return True

        try:
            salida = cargar_json_estricto(_texto_de(respuesta))
        except Exception as exc:  # noqa: BLE001
            _terminar_con_error(analisis, f'La respuesta de OpenAI no es un JSON válido: {exc}')
            return True

        ultimo = analisis.fase_openai == Modelo.FASE_REPARACION
        publicable, errores = adaptador.evaluar(analisis, salida, intento, ultimo)
        if not errores:
            system, _ = _system_y_user(analisis)
            aplicar_resultado(analisis, {
                'ok': True, 'salida': publicable, 'error': None, 'modelo_usado': MODELO_USADO_LABEL,
                'prompt_usado': system, 'diagnostico': analisis.diagnostico,
            })
            return True
        if ultimo:
            _terminar_con_error(analisis, (
                'La respuesta de la IA no pasó la validación tras un reintento de reparación: '
                + ' | '.join(errores[:8])
            ))
            return True
        try:
            _lanzar(analisis, Modelo.FASE_REPARACION,
                    reparacion={'salida_previa': salida, 'errores': errores})
        except Exception as exc:  # noqa: BLE001
            _terminar_con_error(analisis, f'No se pudo lanzar la reparación en OpenAI: {exc}')
            return True
        return False


def seguir_hasta_terminar(analisis_id, Modelo=None):
    """Lo que hace el hilo del análisis después de lanzarlo: consultar cada
    `INTERVALO_CONSULTA_SEGUNDOS` hasta que termine. Si el hilo muere (reinicio del servidor), el
    cron `consultar_analisis_background` sigue desde donde quedó."""
    from django.db import close_old_connections

    limite = time.monotonic() + DURACION_MAXIMA.total_seconds() + 600
    while time.monotonic() < limite:
        time.sleep(INTERVALO_CONSULTA_SEGUNDOS)
        close_old_connections()
        if Modelo is None:
            from analitica.models import AnalisisJornadaIA as Modelo
        if avanzar_en_segundo_plano(Modelo, analisis_id):
            return


# --- adaptadores ----------------------------------------------------------------------------------
class _AdaptadorAnalisisJornada:
    """Análisis integral: el modelo devuelve el contrato completo y se valida contra su entrada."""

    def esquema(self):
        return None  # el contrato completo, el de siempre

    def evaluar(self, analisis, salida, intento, ultimo):
        errores = evaluar_salida_v2(salida, analisis.entrada, PIPELINE_LLM, intento, analisis.diagnostico, ultimo=ultimo)
        return salida, errores


# Lo que copia el backend del análisis original en un resumen para presentación: el modelo no lo
# escribe (no puede alterarlo ni gasta tokens copiándolo).
# `version` no se copia: el resumen sale siempre en la versión vigente del contrato (HU-100), aunque el
# análisis de origen sea v2 — sus visualizaciones las completa el modelo con los campos de color.
CLAVES_COPIADAS_DEL_ORIGINAL = ('pipeline', 'estado', 'alcance', 'fuentes', 'cobertura')
CLAVES_DEL_RESUMEN = ('informes', 'visualizaciones', 'limitaciones')


def esquema_del_resumen():
    """El esquema del contrato v2 restringido a lo que escribe el modelo en un resumen: mismas
    definiciones (`$defs`), solo `informes`, `visualizaciones` y `limitaciones` en la raíz."""
    import copy

    esquema = copy.deepcopy(esquema_para_openai(cargar_esquema()))
    esquema['properties'] = {k: esquema['properties'][k] for k in CLAVES_DEL_RESUMEN}
    esquema['required'] = list(CLAVES_DEL_RESUMEN)
    return esquema


class _AdaptadorResumenPresentacion:
    """Resumen para presentación (HU-99): el modelo escribe solo la parte editorial; el backend
    completa el contrato con lo del original y valida TODO contra la entrada original del análisis
    — así una cita o una métrica del resumen apunta a los mismos datos que en el análisis."""

    def esquema(self):
        return esquema_del_resumen()

    def evaluar(self, resumen, salida, intento, ultimo):
        from analitica.models import resultado_v2_de

        fuente = resumen.fuente
        original = resultado_v2_de(fuente)
        from .contrato import VERSION

        completa = {'version': VERSION, **{k: original[k] for k in CLAVES_COPIADAS_DEL_ORIGINAL}, **salida}
        errores = evaluar_salida_v2(
            completa, fuente.entrada, original['pipeline'], intento, resumen.diagnostico, ultimo=ultimo,
        )
        return completa, errores


class _AdaptadorAjusteAnalisis:
    """Ajuste de un análisis (HU-102, un `AnalisisV2` con `es_ajuste`): el modelo devuelve el
    contrato completo y se valida contra la entrada del ajuste — la del análisis original más el
    bloque `ajuste`, con las mismas fuentes —, con el pipeline del original."""

    def esquema(self):
        return None

    def evaluar(self, analisis, salida, intento, ultimo):
        errores = evaluar_salida_v2(salida, analisis.entrada, analisis.pipeline, intento, analisis.diagnostico, ultimo=ultimo)
        return salida, errores


def adaptador_de(Modelo):
    return {
        'AnalisisJornadaIA': _AdaptadorAnalisisJornada(),
        'ResumenPresentacion': _AdaptadorResumenPresentacion(),
        'AnalisisV2': _AdaptadorAjusteAnalisis(),
    }[Modelo.__name__]

