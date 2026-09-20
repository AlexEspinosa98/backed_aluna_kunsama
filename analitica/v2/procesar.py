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
