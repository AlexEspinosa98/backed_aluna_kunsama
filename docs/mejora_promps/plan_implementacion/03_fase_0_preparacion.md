# 03 — Fase 0: preparación, recursos congelados y `contrato.py`

**Objetivo**: dejar en el repo, versionado y listo para importar, todo lo que las fases siguientes
necesitan: la dependencia `jsonschema` declarada, el paquete `analitica/v2/` con el esquema, los
dos prompts y los ejemplos congelados, y el módulo `contrato.py` que los carga.

**Prerrequisitos**: ninguno. Rama `develop` limpia salvo los cambios retenidos de `Dockerfile` /
`docker-compose.yml` (no tocarlos) y las carpetas sin versionar `docs/mejora_promps/` y
`docs/SYSTEM_PROMPTS.md` (esta fase las commitea).

## Paso 0.1 — Declarar `jsonschema`

Editar `requirements.txt`: agregar una línea `jsonschema` inmediatamente después de
`drf-spectacular` (que es quien hoy lo trae de forma transitiva). Sin pin, como el resto del
archivo.

## Paso 0.2 — Crear el paquete `analitica/v2/` y copiar los recursos

```bash
cd /Users/jfcc/backed_aluna_kunsama
mkdir -p analitica/v2/recursos/ejemplos
touch analitica/v2/__init__.py
cp docs/mejora_promps/analisis.schema.json      analitica/v2/recursos/analisis.schema.json
cp docs/mejora_promps/SYSTEM_PROMPT_LLM.md      analitica/v2/recursos/SYSTEM_PROMPT_LLM.md
cp docs/mejora_promps/SYSTEM_PROMPT_BERTOPIC.md analitica/v2/recursos/SYSTEM_PROMPT_BERTOPIC.md
cp docs/mejora_promps/ejemplos/*.json           analitica/v2/recursos/ejemplos/
```

Verificar que quedaron 9 archivos en `ejemplos/` (`bertopic_integral.entrada/salida`,
`llm_integral.entrada/salida`, `llm_por_momento.entrada/salida`, `sin_datos.entrada/salida`,
`catalogo_visual.salida`). No copiar `.DS_Store` (está ignorado por git de todas formas).

`analitica/v2/__init__.py` lleva solo un docstring:

```python
"""Análisis con IA bajo el contrato `kunsamu.analisis/v2` (docs/mejora_promps/). Paquete aparte
de los pipelines legacy (analysis.py, analisis_ia_openai.py), que siguen intactos para los
resultados históricos — el frontend elige renderer por la `version` del resultado. Plan completo
en docs/mejora_promps/plan_implementacion/."""
```

## Paso 0.3 — `analitica/v2/contrato.py`

Crear con este contenido exacto:

```python
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
VERSION_PROMPT = 'v2.0'

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
```

## Paso 0.4 — Verificación

```bash
source .venv/bin/activate
python -m py_compile analitica/v2/__init__.py analitica/v2/contrato.py
python - <<'EOF'
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
from analitica.v2 import contrato
e = contrato.cargar_esquema()
assert e['properties']['version']['enum'] == ['kunsamu.analisis/v2'], e['properties']['version']
assert len(e['$defs']) == 38, len(e['$defs'])
assert set(e['required']) == {'version', 'pipeline', 'estado', 'alcance', 'fuentes', 'cobertura',
                              'limitaciones', 'informes', 'visualizaciones'}
for p in ('llm', 'bertopic_llm'):
    t = contrato.cargar_prompt(p)
    assert 'kunsamu.analisis/v2' in t and len(t) > 10000, (p, len(t))
print('OK recursos')
EOF
```

(El `import django` sin `setup()` basta: `contrato.py` no usa el ORM.)

## Paso 0.5 — Commit

```bash
git status --short          # Dockerfile y docker-compose.yml deben seguir como " M" y NO entrar
git add requirements.txt analitica/v2/__init__.py analitica/v2/contrato.py analitica/v2/recursos \
        docs/mejora_promps docs/SYSTEM_PROMPTS.md
git commit -m "feat(v2): recursos congelados del contrato kunsamu.analisis/v2 y documentación de la entrega

Primer paso del plan docs/mejora_promps/plan_implementacion/: el esquema, los dos system prompts
y los ejemplos de la entrega del frontend quedan copiados en analitica/v2/recursos/ (lo que
corre en producción no debe depender de dónde viva la documentación) y jsonschema pasa a ser una
dependencia declarada, no transitiva. También entra la entrega misma (docs/mejora_promps/) y
docs/SYSTEM_PROMPTS.md, que estaban sin versionar."
```

## Criterios de "hecho"

- [ ] `requirements.txt` incluye `jsonschema`.
- [ ] `analitica/v2/recursos/` tiene `analisis.schema.json`, los dos `.md` y 9 ejemplos.
- [ ] `contrato.py` compila y el script de verificación imprime `OK recursos`.
- [ ] Commit hecho sin `Dockerfile`/`docker-compose.yml`.
