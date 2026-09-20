# 06 — Fase 3: llamada estructurada a OpenAI y orquestador

**Objetivo**: `analitica/v2/llm.py` (una llamada a Chat Completions con `response_format`
`json_schema` estricto y respaldo `json_object`, que nunca lanza) y `analitica/v2/procesar.py` (el
trabajo de background: entrada → [bertopic] → guardar entrada → sin_datos o LLM → validar →
reparar una vez → guardar). También el **stub** `bertopic_adaptador.py` que la fase 5 reemplaza.

**Prerrequisitos**: fases 0, 1 y 2. `procesar.py` importa `analitica.models.AnalisisV2`, que
recién existe en la fase 4 — el import es perezoso (dentro de la función) para que este módulo
compile desde ya; el flujo completo se ejercita en la fase 4.

## Paso 3.1 — `analitica/v2/llm.py`

```python
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
```

## Paso 3.2 — Stub `analitica/v2/bertopic_adaptador.py` (la fase 5 lo reemplaza completo)

```python
"""Adaptador BERTopic → contrato v2. STUB hasta la fase 5 del plan: declara cero ejecuciones, que
es una entrada válida ("una lista de ejecuciones vacía indica ausencia de resultados y debe
declararse como tal", ENTRADA_Y_BERTOPIC.md §6). Así `pipeline=bertopic_llm` funciona desde la
fase 4 sin inventar resultados."""


def anexar_bertopic(entrada, analisis_id=None):
    """(entrada_con_bertopic, notas_para_diagnostico). No lanza."""
    entrada['bertopic'] = {'version_adaptador': '1.0', 'ejecuciones': []}
    return entrada, [{'motivo': 'adaptador_no_implementado'}]
```

## Paso 3.3 — `analitica/v2/procesar.py`

```python
"""Orquestador del análisis v2 — corre en un hilo de background lanzado desde la vista, con el
mismo patrón que `analizar_jornada_ia` (close_old_connections al entrar y al salir, try/except que
marca error, nunca deja morir el hilo en silencio).

Secuencia (D9/D11 del plan):
  entrada normalizada → [BERTopic si el pipeline lo pide] → GUARDAR la entrada (inmutable)
  → si no hay respuestas: salida sin_datos del backend
    si hay: system = archivo del prompt, user = JSON de la entrada → OpenAI estructurado
  → validar (esquema + negocio) → si falla, UN reintento de reparación → validar
  → completo (resultado publicado) o error (resultado vacío; todo lo descartado queda en
    `diagnostico` para auditoría).
"""
import json
import os

from django.db import close_old_connections
from django.utils import timezone

from .contrato import PIPELINE_BERTOPIC_LLM, VERSION_ESQUEMA, VERSION_PROMPT, cargar_prompt
from .entrada import construir_entrada, hay_respuestas
from .llm import MODELO_USADO_LABEL, llamar_openai_estructurado
from .sin_datos import construir_salida_sin_datos
from .validacion import validar_salida

# ≈300k tokens. Un corpus mayor necesitaría codificación por lotes + agregación (fuera de alcance,
# D10): mejor fallar con un mensaje claro que mandar una llamada que el modelo va a truncar.
MAX_CARACTERES_ENTRADA = int(os.environ.get('KUNSAMU_V2_MAX_CARACTERES_ENTRADA', '1200000'))
MODELO_USADO_SIN_DATOS = 'Sin datos — generado por el backend sin IA'


def _completar(analisis, salida, modelo_usado, prompt_usado, diagnostico):
    analisis.resultado = salida
    analisis.estado = analisis.ESTADO_COMPLETO
    analisis.error_mensaje = ''
    analisis.modelo_usado = modelo_usado
    analisis.prompt_usado = prompt_usado
    analisis.diagnostico = diagnostico
    analisis.completado_en = timezone.now()
    analisis.save(update_fields=[
        'resultado', 'estado', 'error_mensaje', 'modelo_usado', 'prompt_usado', 'diagnostico',
        'completado_en',
    ])


def procesar_analisis_v2(analisis_id):
    close_old_connections()
    from analitica.models import AnalisisV2

    analisis = None
    diagnostico = {'bertopic': [], 'intentos': []}
    try:
        analisis = AnalisisV2.objects.select_related('jornada').get(pk=analisis_id)
        analisis.estado = AnalisisV2.ESTADO_PROCESANDO
        analisis.save(update_fields=['estado'])

        entrada = construir_entrada(
            analisis.jornada, analisis.modo, list(analisis.momentos.all()),
            contexto=analisis.contexto, instrucciones=analisis.instrucciones,
            personalizacion_momentos=analisis.personalizacion_momentos,
        )
        if analisis.pipeline == PIPELINE_BERTOPIC_LLM:
            from .bertopic_adaptador import anexar_bertopic
            entrada, notas = anexar_bertopic(entrada, analisis_id=analisis.id)
            diagnostico['bertopic'] = notas

        # Inmutable desde acá: los índices de los JSON Pointers de la salida se validan contra
        # ESTA versión, nunca contra una reconstrucción posterior.
        analisis.entrada = entrada
        analisis.version_esquema = VERSION_ESQUEMA
        analisis.version_prompt = VERSION_PROMPT
        analisis.save(update_fields=['entrada', 'version_esquema', 'version_prompt'])

        if not hay_respuestas(entrada):
            salida = construir_salida_sin_datos(entrada, analisis.pipeline)
            errores = validar_salida(salida, entrada, pipeline_esperado=analisis.pipeline)
            if errores:
                raise RuntimeError(
                    'La salida sin_datos generada por el backend no pasó la validación (bug): '
                    + '; '.join(errores[:5])
                )
            _completar(analisis, salida, MODELO_USADO_SIN_DATOS, prompt_usado='', diagnostico=diagnostico)
            return

        user = json.dumps(entrada, ensure_ascii=False)
        if len(user) > MAX_CARACTERES_ENTRADA:
            raise ValueError(
                f'El alcance es demasiado grande para una sola llamada ({len(user)} caracteres, '
                f'máximo {MAX_CARACTERES_ENTRADA}). Pide el análisis por momento con menos momentos.'
            )
        system = cargar_prompt(analisis.pipeline)
        analisis.prompt_usado = system
        analisis.save(update_fields=['prompt_usado'])

        salida, error, meta = llamar_openai_estructurado(system, user)
        diagnostico['intentos'].append({'n': 1, 'error': error, 'meta': meta})
        if salida is None:
            raise RuntimeError(error)
        errores = validar_salida(salida, entrada, pipeline_esperado=analisis.pipeline)
        if errores:
            diagnostico['intentos'][-1].update({'errores_validacion': errores, 'salida_descartada': salida})
            salida, error, meta = llamar_openai_estructurado(
                system, user, reparacion={'salida_previa': salida, 'errores': errores},
            )
            diagnostico['intentos'].append({'n': 2, 'error': error, 'meta': meta})
            if salida is None:
                raise RuntimeError(error)
            errores = validar_salida(salida, entrada, pipeline_esperado=analisis.pipeline)
            if errores:
                diagnostico['intentos'][-1].update({'errores_validacion': errores, 'salida_descartada': salida})
                raise RuntimeError(
                    'La respuesta de la IA no pasó la validación tras un reintento de reparación: '
                    + ' | '.join(errores[:8])
                )
        _completar(analisis, salida, MODELO_USADO_LABEL, prompt_usado=system, diagnostico=diagnostico)
    except Exception as exc:  # noqa: BLE001 — nunca debe dejar el hilo morir en silencio
        if analisis is not None:
            analisis.estado = analisis.ESTADO_ERROR
            analisis.error_mensaje = str(exc)[:4000]
            analisis.diagnostico = diagnostico
            analisis.save(update_fields=['estado', 'error_mensaje', 'diagnostico'])
    finally:
        close_old_connections()
```

## Paso 3.4 — Verificación

```bash
source .venv/bin/activate
python -m py_compile analitica/v2/llm.py analitica/v2/bertopic_adaptador.py analitica/v2/procesar.py
python - <<'EOF'
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ.pop('OPENAI_API_KEY', None)
import django; django.setup()
from analitica.v2.llm import cargar_json_estricto, esquema_para_openai, llamar_openai_estructurado
from analitica.v2.contrato import cargar_esquema
e = esquema_para_openai(cargar_esquema())
assert '$schema' not in e and 'title' not in e and '$defs' in e and 'required' in e
assert '$schema' in cargar_esquema()   # el original no se mutó
try:
    cargar_json_estricto('{"a": NaN}'); raise SystemExit('NaN aceptado')
except ValueError:
    pass
salida, error, meta = llamar_openai_estructurado('s', 'u')
assert salida is None and 'OPENAI_API_KEY' in error and meta == {}, (salida, error, meta)
print('OK llm')
EOF
```

> Ojo: `django.setup()` lee `.env` con `environ.Env.read_env`, que **no sobreescribe** variables ya
> presentes en `os.environ` — por eso el script quita `OPENAI_API_KEY` antes. Si aun así el último
> assert falla porque `.env` la define, es esperable: quita ese assert y da por buena la
> verificación de los otros tres puntos.

## Paso 3.5 — Tests (escribir, no correr) — agregar a `analitica/tests_v2.py`

```python
from unittest.mock import patch

from .v2.contrato import cargar_esquema
from .v2.llm import cargar_json_estricto, esquema_para_openai, llamar_openai_estructurado


class LlmEstructuradoTests(SimpleTestCase):
    def test_esquema_para_openai_quita_claves_informativas_sin_mutar_el_original(self):
        e = esquema_para_openai(cargar_esquema())
        self.assertNotIn('$schema', e)
        self.assertIn('$defs', e)
        self.assertIn('$schema', cargar_esquema())

    def test_json_estricto_rechaza_nan(self):
        with self.assertRaises(ValueError):
            cargar_json_estricto('{"a": NaN}')

    @patch.dict('os.environ', {'OPENAI_API_KEY': ''})
    def test_sin_api_key_devuelve_error_sin_lanzar(self):
        salida, error, meta = llamar_openai_estructurado('s', 'u')
        self.assertIsNone(salida)
        self.assertIn('OPENAI_API_KEY', error)
```

Los tests del orquestador van en la fase 4 (necesitan el modelo).

## Paso 3.6 — Commit

```bash
git status --short
git add analitica/v2/llm.py analitica/v2/bertopic_adaptador.py analitica/v2/procesar.py analitica/tests_v2.py
git commit -m "feat(v2): llamada estructurada a OpenAI (json_schema estricto) y orquestador con reparación

llm.py: response_format json_schema strict con el esquema congelado, respaldo json_object si el
proveedor lo rechaza, y nunca se parsea una respuesta truncada o rechazada. procesar.py: guarda la
entrada inmutable antes de llamar, produce sin_datos sin IA cuando el alcance está vacío, valida en
dos capas y reintenta UNA vez con los errores concretos; lo descartado queda en diagnostico. El
adaptador BERTopic es un stub (cero ejecuciones, válido) hasta la fase 5."
```

## Criterios de "hecho"

- [ ] Los tres módulos compilan; el script imprime `OK llm`.
- [ ] Commit sin `Dockerfile`/`docker-compose.yml`.
