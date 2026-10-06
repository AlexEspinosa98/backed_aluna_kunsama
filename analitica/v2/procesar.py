"""Orquestador del análisis v2. `ejecutar_analisis_v2` es el núcleo, independiente de qué modelo
lo persista: lo usan `procesar_analisis_v2` (AnalisisV2) y, desde el rediseño, los tres puntos de
entrada existentes — `analisis_ia_openai.analizar_jornada_ia`, `analisis_ia_openai.analizar_momento_ia`
y `analysis.procesar_reporte` — que ahora producen el mismo contrato `kunsamu.analisis/v2` en sus
campos de siempre (`resultado` / `analisis`).

Secuencia:
  entrada normalizada → [BERTopic si el pipeline lo pide] → GUARDAR la entrada (inmutable, vía
  `al_guardar_entrada`) → si no hay respuestas: salida sin_datos del backend; si hay: system =
  el `SystemPrompt` activo del pipeline (HU-92), user = JSON de la entrada → OpenAI estructurado → validar (esquema +
  negocio) → si falla, UN reintento de reparación → validar → resultado publicado, o error con
  todo lo descartado en `diagnostico` para auditoría.
"""
import json
import os

from django.db import close_old_connections
from django.utils import timezone

from auditoria.openai_cliente import auditar_llamadas

from .adjuntos import anexar_adjuntos
from .contrato import PIPELINE_BERTOPIC_LLM, TIPO_PROMPT_POR_PIPELINE, VERSION_ESQUEMA
from .entrada import construir_entrada, hay_respuestas
from .llm import MODELO_USADO_LABEL, llamar_openai_estructurado
from .sin_datos import construir_salida_sin_datos
from .validacion import normalizar_salida, recortar_citas_no_verificables, validar_salida

# ≈300k tokens. Un corpus mayor necesitaría codificación por lotes + agregación (fuera de alcance,
# D10): mejor fallar con un mensaje claro que mandar una llamada que el modelo va a truncar.
MAX_CARACTERES_ENTRADA = int(os.environ.get('KUNSAMU_V2_MAX_CARACTERES_ENTRADA', '1200000'))
MODELO_USADO_SIN_DATOS = 'Sin datos — generado por el backend sin IA'


def preparar_entrada_v2(jornada, modo, momentos, pipeline, contexto='', instrucciones='',
                        personalizacion_momentos=None, referencia='', al_guardar_entrada=None,
                        diagnostico=None, adjuntos=None):
    """Todo lo que va ANTES de llamar a la IA, compartido por el modo de siempre
    (`ejecutar_analisis_v2`) y el de segundo plano (`v2.background`, HU-98). Lanza ante cualquier
    error. Devuelve `{'prompt': SystemPrompt, 'entrada': dict, 'user': str|None,
    'salida_sin_datos': dict|None}` — con `user` en None cuando no hay respuestas, porque entonces
    la salida la arma el backend sin IA (`salida_sin_datos`). `adjuntos`: los documentos/imágenes
    de la jornada que entran como fuente o como contexto (HU-101, ver `adjuntos.py`)."""
    from analitica.models import SystemPrompt

    diagnostico = diagnostico if diagnostico is not None else {'bertopic': [], 'intentos': []}
    prompt = SystemPrompt.activo_de(TIPO_PROMPT_POR_PIPELINE[pipeline])
    entrada = construir_entrada(
        jornada, modo, list(momentos or []), contexto=contexto, instrucciones=instrucciones,
        personalizacion_momentos=personalizacion_momentos,
    )
    if adjuntos:
        anexar_adjuntos(entrada, jornada, adjuntos, diagnostico=diagnostico)
    if pipeline == PIPELINE_BERTOPIC_LLM:
        from .bertopic_adaptador import anexar_bertopic
        entrada, notas = anexar_bertopic(entrada, analisis_id=referencia)
        diagnostico['bertopic'] = notas
    if al_guardar_entrada is not None:
        al_guardar_entrada(entrada, prompt.referencia)

    if not hay_respuestas(entrada):
        salida = construir_salida_sin_datos(entrada, pipeline)
        errores = validar_salida(salida, entrada, pipeline_esperado=pipeline)
        if errores:
            raise RuntimeError(
                'La salida sin_datos generada por el backend no pasó la validación (bug): '
                + '; '.join(errores[:5])
            )
        return {'prompt': prompt, 'entrada': entrada, 'user': None, 'salida_sin_datos': salida}

    # Compacto (sin espacios tras `,` y `:`): misma información, ~4 % menos de entrada (HU-94).
    user = json.dumps(entrada, ensure_ascii=False, separators=(',', ':'))
    if len(user) > MAX_CARACTERES_ENTRADA:
        raise ValueError(
            f'El alcance es demasiado grande para una sola llamada ({len(user)} caracteres, '
            f'máximo {MAX_CARACTERES_ENTRADA}). Pide el análisis por momento con menos momentos.'
        )
    return {'prompt': prompt, 'entrada': entrada, 'user': user, 'salida_sin_datos': None}


def evaluar_salida_v2(salida, entrada, pipeline, intento, diagnostico, ultimo):
    """Normaliza y valida una salida de la IA, y deja constancia en `intento` (el dict de ese
    intento dentro de `diagnostico['intentos']`). En el ÚLTIMO intento, si lo único que falla son
    citas que no existen en ninguna fuente, las retira y publica el resto. Devuelve la lista de
    errores que quedan (vacía = válida)."""
    intento['normalizaciones'] = normalizar_salida(salida, entrada)
    errores = validar_salida(salida, entrada, pipeline_esperado=pipeline)
    if errores and ultimo and all('citas[' in e for e in errores):
        # Solo quedan citas que no existen en ninguna fuente (paráfrasis): se retiran esas
        # citas y se publica el resto, en vez de perder un análisis entero por ellas.
        intento['errores_antes_del_recorte'] = errores
        diagnostico['citas_descartadas'] = recortar_citas_no_verificables(salida, entrada)
        errores = validar_salida(salida, entrada, pipeline_esperado=pipeline)
    if errores:
        intento.update({'errores_validacion': errores, 'salida_descartada': salida})
    return errores


def ejecutar_analisis_v2(jornada, modo, momentos, pipeline, contexto='', instrucciones='',
                         personalizacion_momentos=None, referencia='', al_guardar_entrada=None,
                         modelo=None, esfuerzo=None, flex=False, adjuntos=None):
    """Corre el análisis completo y devuelve un dict — NUNCA lanza:
      {'ok': bool, 'entrada': dict, 'salida': dict|None, 'error': str|None,
       'prompt_usado': str, 'modelo_usado': str, 'diagnostico': dict,
       'version_esquema': str, 'version_prompt': str}
    `al_guardar_entrada(entrada, version_prompt)` se invoca en cuanto la entrada está armada y
    ANTES de llamar a la IA, para que quien persiste la guarde inmutable: los JSON Pointers de la
    salida se validan contra esa versión exacta. `version_prompt` es la referencia del
    `SystemPrompt` activo (HU-92), que se fija al empezar para que toda la corrida —incluido el
    reintento de reparación— use la misma versión aunque alguien active otra a mitad de camino.
    `referencia` identifica la corrida en el bloque BERTopic. `modelo`/`esfuerzo`/`flex`: los que
    pidió quien lanzó el análisis (HU-98); None = los de la configuración."""
    diagnostico = {'bertopic': [], 'intentos': []}
    resultado = {
        'ok': False, 'entrada': {}, 'salida': None, 'error': None, 'prompt_usado': '',
        'modelo_usado': '', 'diagnostico': diagnostico,
        'version_esquema': VERSION_ESQUEMA, 'version_prompt': '',
    }
    try:
        preparado = preparar_entrada_v2(
            jornada, modo, momentos, pipeline, contexto=contexto, instrucciones=instrucciones,
            personalizacion_momentos=personalizacion_momentos, referencia=referencia,
            al_guardar_entrada=al_guardar_entrada, diagnostico=diagnostico, adjuntos=adjuntos,
        )
        entrada, prompt, user = preparado['entrada'], preparado['prompt'], preparado['user']
        resultado.update({'entrada': entrada, 'version_prompt': prompt.referencia})
        if user is None:
            resultado.update({
                'ok': True, 'salida': preparado['salida_sin_datos'], 'modelo_usado': MODELO_USADO_SIN_DATOS,
            })
            return resultado

        system = prompt.contenido
        resultado['prompt_usado'] = system
        opciones = {'modelo': modelo, 'esfuerzo': esfuerzo, 'flex': flex}

        salida, error, meta = llamar_openai_estructurado(system, user, **opciones)
        diagnostico['intentos'].append({'n': 1, 'error': error, 'meta': meta})
        if salida is None:
            raise RuntimeError(error)
        errores = evaluar_salida_v2(salida, entrada, pipeline, diagnostico['intentos'][-1], diagnostico, ultimo=False)
        if errores:
            salida, error, meta = llamar_openai_estructurado(
                system, user, reparacion={'salida_previa': salida, 'errores': errores}, **opciones,
            )
            diagnostico['intentos'].append({'n': 2, 'error': error, 'meta': meta})
            if salida is None:
                raise RuntimeError(error)
            errores = evaluar_salida_v2(salida, entrada, pipeline, diagnostico['intentos'][-1], diagnostico, ultimo=True)
            if errores:
                raise RuntimeError(
                    'La respuesta de la IA no pasó la validación tras un reintento de reparación: '
                    + ' | '.join(errores[:8])
                )
        resultado.update({'ok': True, 'salida': salida, 'modelo_usado': MODELO_USADO_LABEL})
        return resultado
    except Exception as exc:  # noqa: BLE001 — el error se devuelve, nunca se propaga
        resultado['error'] = str(exc)[:4000]
        return resultado


def resumen_de_salida(salida):
    """Texto plano representativo de una salida v2 (los resúmenes de sus informes) — para los
    campos narrativos que ya existían, como `Reporte.texto_reporte`."""
    return '\n\n'.join(i.get('resumen', '') for i in (salida or {}).get('informes', []) if i.get('resumen'))


def guardador_de_entrada(registro):
    """Callback `al_guardar_entrada` para cualquier registro con `ResultadoV2Mixin` (o
    `AnalisisV2`): persiste la entrada y las versiones ANTES de la llamada a la IA."""
    def _guardar(entrada, version_prompt):
        registro.entrada = entrada
        registro.version_esquema = VERSION_ESQUEMA
        registro.version_prompt = version_prompt
        registro.save(update_fields=['entrada', 'version_esquema', 'version_prompt'])
    return _guardar


def aplicar_resultado(registro, r, campo_resultado='resultado', extra=None):
    """Vuelca el dict de `ejecutar_analisis_v2` en un registro (estado completo o error). `extra`:
    campos adicionales a fijar solo en éxito (ej. `texto_reporte` de un Reporte)."""
    registro.diagnostico = r['diagnostico']
    if not r['ok']:
        registro.estado = registro.ESTADO_ERROR
        registro.error_mensaje = r['error'] or 'Error desconocido generando el análisis.'
        registro.save(update_fields=['estado', 'error_mensaje', 'diagnostico'])
        return
    setattr(registro, campo_resultado, r['salida'])
    registro.estado = registro.ESTADO_COMPLETO
    registro.error_mensaje = ''
    registro.modelo_usado = r['modelo_usado']
    registro.prompt_usado = r['prompt_usado']
    registro.completado_en = timezone.now()
    campos = [campo_resultado, 'estado', 'error_mensaje', 'modelo_usado', 'prompt_usado', 'diagnostico', 'completado_en']
    for clave, valor in (extra or {}).items():
        setattr(registro, clave, valor)
        campos.append(clave)
    registro.save(update_fields=campos)


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


@auditar_llamadas('analitica.AnalisisV2')
def procesar_analisis_v2(analisis_id):
    close_old_connections()
    from analitica.models import AnalisisV2

    analisis = None
    r = None
    try:
        analisis = AnalisisV2.objects.select_related('jornada').get(pk=analisis_id)
        analisis.estado = AnalisisV2.ESTADO_PROCESANDO
        analisis.save(update_fields=['estado'])

        def _guardar_entrada(entrada, version_prompt):
            analisis.entrada = entrada
            analisis.version_esquema = VERSION_ESQUEMA
            analisis.version_prompt = version_prompt
            analisis.save(update_fields=['entrada', 'version_esquema', 'version_prompt'])

        r = ejecutar_analisis_v2(
            analisis.jornada, analisis.modo, list(analisis.momentos.all()), analisis.pipeline,
            contexto=analisis.contexto, instrucciones=analisis.instrucciones,
            personalizacion_momentos=analisis.personalizacion_momentos,
            referencia=f'analisis-v2-{analisis.id}', al_guardar_entrada=_guardar_entrada,
            adjuntos=analisis.adjuntos,
        )
        if not r['ok']:
            raise RuntimeError(r['error'])
        _completar(analisis, r['salida'], r['modelo_usado'], r['prompt_usado'], r['diagnostico'])
    except Exception as exc:  # noqa: BLE001 — nunca debe dejar el hilo morir en silencio
        if analisis is not None:
            analisis.estado = analisis.ESTADO_ERROR
            analisis.error_mensaje = str(exc)[:4000]
            analisis.diagnostico = r['diagnostico'] if r else {}
            analisis.save(update_fields=['estado', 'error_mensaje', 'diagnostico'])
    finally:
        close_old_connections()
