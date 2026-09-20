"""Una llamada a OpenAI con salida estructurada para el contrato v2 (D6 del plan).

Mismo esqueleto que `_llamar_openai_json` en analisis_ia_openai.py (hilo + join con timeout,
`reasoning_effort` en vez de `temperature` cuando aplica, nunca lanza) con tres diferencias:
1. `response_format` = json_schema ESTRICTO con el esquema congelado; si el proveedor lo rechaza,
   se reintenta con json_object y el esquema anexado al system (README de la entrega, §Integración
   backend). En ambos casos la respuesta se valida igual después (validacion.py).
2. Se comprueba `refusal` y `finish_reason == 'stop'` ANTES de parsear: un JSON truncado por
   límite de tokens nunca se acepta.
3. `json.loads` rechaza NaN/Infinity (json.loads los acepta por defecto y el esquema no).

Devuelve (salida_dict | None, error | None, meta). `meta` NUNCA incluye el nombre del modelo:
se guarda en `AnalisisV2.diagnostico`, que la API expone, y el módulo nunca revela el proveedor.
"""
import copy
import json
import os
import threading

from .contrato import cargar_esquema

DEFAULT_MODEL = os.environ.get('OPENAI_MODEL_V2') or os.environ.get('OPENAI_MODEL', 'gpt-4o')
REASONING_EFFORT = os.environ.get('OPENAI_REASONING_EFFORT', 'medium')
# La salida v2 es grande (informes + cobertura + visualizaciones tipadas): mucho más margen que
# los 6000/8000 tokens de las vías legacy.
MAX_OUTPUT_TOKENS = int(os.environ.get('KUNSAMU_V2_MAX_OUTPUT_TOKENS', '24000'))
TIMEOUT_SECONDS = int(os.environ.get('KUNSAMU_V2_TIMEOUT_SECONDS', '540'))
NOMBRE_ESQUEMA = 'kunsamu_analisis_v2'
MODELO_USADO_LABEL = 'Generado con IA'


def _rechazar_constante(nombre):
    raise ValueError(f'valor no permitido en JSON: {nombre}')


def cargar_json_estricto(texto):
    """`json.loads` que rechaza NaN/Infinity/-Infinity (el esquema exige números finitos)."""
    return json.loads(texto, parse_constant=_rechazar_constante)


def esquema_para_openai(esquema):
    """Copia del esquema sin las claves informativas de la raíz (`$schema`, `title`,
    `description`), que el modo estricto de OpenAI no necesita y algunos modelos rechazan."""
    copia = copy.deepcopy(esquema)
    for clave in ('$schema', 'title', 'description'):
        copia.pop(clave, None)
    return copia


def _mensaje_reparacion(errores):
    lista = '\n'.join(f'- {e}' for e in errores[:40])
    return (
        'Tu respuesta anterior NO pasó la validación del backend. Errores concretos:\n' + lista +
        '\n\nDevuelve de nuevo el objeto JSON COMPLETO y corregido, conforme al mismo esquema y a '
        'las mismas reglas del system prompt. Corrige solo lo necesario. No inventes datos para '
        '"cuadrar" una cifra ni una cita: si algo no puede sustentarse con la entrada, elimínalo y '
        'registra la limitación.'
    )


def llamar_openai_estructurado(system, user, modelo=None, reparacion=None):
    """`reparacion`: `{'salida_previa': dict, 'errores': [str]}` para el único reintento que hace
    procesar.py — se manda la conversación completa (system, user, assistant=JSON previo,
    user=errores) para que el modelo corrija sobre lo que ya produjo."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None, 'OPENAI_API_KEY no está configurada en el entorno del servidor (.env).', {}

    esquema = esquema_para_openai(cargar_esquema())
    modelo = modelo or DEFAULT_MODEL
    mensajes = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    if reparacion:
        mensajes.append({'role': 'assistant', 'content': json.dumps(reparacion['salida_previa'], ensure_ascii=False)})
        mensajes.append({'role': 'user', 'content': _mensaje_reparacion(reparacion['errores'])})
    resultado = {}

    def _crear(client, response_format, system_extra=''):
        msgs = mensajes
        if system_extra:
            msgs = [{'role': 'system', 'content': system + system_extra}] + mensajes[1:]
        kwargs = dict(
            model=modelo, messages=msgs, max_completion_tokens=MAX_OUTPUT_TOKENS,
            response_format=response_format,
        )
        if REASONING_EFFORT:
            # Los modelos de razonamiento no aceptan `temperature` — nunca ambos a la vez.
            kwargs['reasoning_effort'] = REASONING_EFFORT
        else:
            kwargs['temperature'] = 0.2
        return client.chat.completions.create(**kwargs)

    def _run():
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            formato_estricto = {
                'type': 'json_schema',
                'json_schema': {'name': NOMBRE_ESQUEMA, 'strict': True, 'schema': esquema},
            }
            try:
                respuesta = _crear(client, formato_estricto)
                resultado['modo_salida'] = 'json_schema'
            except Exception as exc:  # noqa: BLE001 — solo el rechazo del formato cae al respaldo
                texto_exc = str(exc).lower()
                if 'schema' not in texto_exc and 'response_format' not in texto_exc:
                    raise
                extra = (
                    '\n\nESQUEMA JSON OBLIGATORIO DE LA SALIDA (JSON Schema; cúmplelo al pie de la '
                    'letra, sin claves adicionales):\n' + json.dumps(esquema, ensure_ascii=False)
                )
                respuesta = _crear(client, {'type': 'json_object'}, system_extra=extra)
                resultado['modo_salida'] = 'json_object'
            opcion = respuesta.choices[0]
            resultado['finish_reason'] = opcion.finish_reason
            resultado['refusal'] = getattr(opcion.message, 'refusal', None)
            resultado['texto'] = (opcion.message.content or '').strip()
            uso = getattr(respuesta, 'usage', None)
            if uso is not None:
                resultado['usage'] = {
                    'prompt_tokens': getattr(uso, 'prompt_tokens', None),
                    'completion_tokens': getattr(uso, 'completion_tokens', None),
                }
        except Exception as exc:  # noqa: BLE001 — cualquier falla de la API cae a error legible
            resultado['error'] = str(exc)

    hilo = threading.Thread(target=_run, daemon=True)
    hilo.start()
    hilo.join(timeout=TIMEOUT_SECONDS)

    meta = {k: resultado.get(k) for k in ('modo_salida', 'finish_reason', 'usage')}
    if hilo.is_alive():
        return None, f'Tiempo de espera agotado ({TIMEOUT_SECONDS}s) esperando a OpenAI.', meta
    if resultado.get('error'):
        return None, resultado['error'], meta
    if resultado.get('refusal'):
        return None, f'El proveedor rechazó la solicitud: {resultado["refusal"]}', meta
    if resultado.get('finish_reason') not in (None, 'stop'):
        return None, (
            f'La respuesta no terminó completa (finish_reason={resultado.get("finish_reason")}) — '
            'probablemente truncada por el límite de tokens de salida; no se acepta un JSON incompleto.'
        ), meta
    texto = resultado.get('texto')
    if not texto:
        return None, 'OpenAI no devolvió contenido.', meta
    try:
        return cargar_json_estricto(texto), None, meta
    except ValueError as exc:  # json.JSONDecodeError es subclase de ValueError
        return None, f'OpenAI devolvió JSON inválido: {exc}', meta
