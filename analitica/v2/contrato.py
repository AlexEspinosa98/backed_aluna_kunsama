"""Constantes y recursos congelados del contrato `kunsamu.analisis/v2`.

Los archivos de `recursos/` son copias de la entrega `docs/mejora_promps/` (20-sep-2026). Se
cargan desde acá y no desde `docs/` para que un reordenamiento de la documentación nunca cambie
lo que corre en producción. Quien modifique un recurso debe subir a mano la constante de versión
correspondiente: cada `AnalisisV2` guarda con qué versión de prompt y de esquema se generó.
"""
import json
from functools import lru_cache
from pathlib import Path

VERSION = 'kunsamu.analisis/v2'
VERSION_ESQUEMA = 'v2.0'
# v2.1 (2026-09-20): SYSTEM_PROMPT_LLM.md reemplazado por la versión "analista principal" que
# mandó el frontend (rol experto, cálculos que la evidencia permita, títulos como conclusión).
VERSION_PROMPT = 'v2.1'

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
_ARCHIVO_PROMPT = {
    PIPELINE_LLM: 'SYSTEM_PROMPT_LLM.md',
    PIPELINE_BERTOPIC_LLM: 'SYSTEM_PROMPT_BERTOPIC.md',
}


@lru_cache(maxsize=None)
def cargar_esquema():
    """El JSON Schema (Draft 2020-12) de la salida. Es un dict compartido: no mutarlo — quien
    necesite una variante (ver `llm.esquema_para_openai`) hace su propia copia."""
    with open(RECURSOS / 'analisis.schema.json', encoding='utf-8') as archivo:
        return json.load(archivo)


@lru_cache(maxsize=None)
def cargar_prompt(pipeline):
    """El system prompt completo del pipeline, tal cual está en el archivo — sin anexos."""
    return (RECURSOS / _ARCHIVO_PROMPT[pipeline]).read_text(encoding='utf-8')
