"""Constantes y recursos congelados del contrato `kunsamu.analisis/v2`.

El esquema de `recursos/` es copia de la entrega `docs/mejora_promps/` (20-sep-2026); se carga
desde acá y no desde `docs/` para que un reordenamiento de la documentación nunca cambie lo que
corre en producción. Quien lo modifique debe subir a mano `VERSION_ESQUEMA`.

Los system prompts ya NO viven acá: desde HU-92 están en la tabla `analitica.SystemPrompt`, uno
activo por tipo (`TIPO_PROMPT_POR_PIPELINE`), y cada corrida guarda en `version_prompt` la
referencia de la versión que usó.
"""
import json
from functools import lru_cache
from pathlib import Path

# HU-100: v2.1 agrega colores con significado y los tipos grafo, sankey y treemap
# (recursos/CONTRATO_ANALISIS_V2_1.md). Lo que se GENERA es siempre v2.1; lo que se LEE acepta
# también v2, porque los análisis guardados antes no se reescriben y el frontend lee las dos.
# El esquema v2.0 queda archivado en recursos/analisis.schema.v2_0.json.
VERSION = 'kunsamu.analisis/v2.1'
VERSION_ESQUEMA = 'v2.1'
VERSIONES_LEGIBLES = ('kunsamu.analisis/v2', 'kunsamu.analisis/v2.1')


def es_contrato_v2(resultado):
    """True si `resultado` es una salida del contrato v2 en cualquiera de sus versiones."""
    return isinstance(resultado, dict) and resultado.get('version') in VERSIONES_LEGIBLES

MODO_INTEGRAL = 'integral'
MODO_POR_MOMENTO = 'por_momento'
MODO_CHOICES = [
    (MODO_INTEGRAL, 'Integral — un informe de toda la jornada'),
    (MODO_POR_MOMENTO, 'Por momento — un informe independiente por cada momento elegido'),
]

PIPELINE_LLM = 'llm'
PIPELINE_BERTOPIC_LLM = 'bertopic_llm'
PIPELINE_CHOICES = [
    (PIPELINE_LLM, 'LLM directo (sin BERTopic)'),
    (PIPELINE_BERTOPIC_LLM, 'BERTopic + LLM'),
]

# Estado ANALÍTICO (dentro de `resultado.estado`), distinto del estado del trabajo (`AnalisisV2.estado`).
ESTADOS_ANALITICOS = ('completo', 'parcial', 'sin_datos', 'datos_insuficientes')

RECURSOS = Path(__file__).resolve().parent / 'recursos'
# Qué tipo de `SystemPrompt` usa cada pipeline (los valores son `SystemPrompt.TIPO_*`; van como
# texto porque models.py importa este módulo y no al revés).
TIPO_PROMPT_POR_PIPELINE = {
    PIPELINE_LLM: 'analisis_llm',
    PIPELINE_BERTOPIC_LLM: 'analisis_bertopic',
}


@lru_cache(maxsize=None)
def cargar_esquema():
    """El JSON Schema (Draft 2020-12) de la salida. Es un dict compartido: no mutarlo — quien
    necesite una variante (ver `llm.esquema_para_openai`) hace su propia copia."""
    with open(RECURSOS / 'analisis.schema.json', encoding='utf-8') as archivo:
        return json.load(archivo)
