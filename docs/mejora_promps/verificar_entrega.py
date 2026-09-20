"""Verifica esta entrega; no es un validador completo de negocio de producción."""
import copy
import json
from pathlib import Path
from jsonschema import Draft202012Validator

BASE = Path(__file__).resolve().parent
SCHEMA = json.loads((BASE / 'analisis.schema.json').read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def exigir(condition, message):
    if not condition:
        raise ValueError(message)


def pointer(value, path):
    exigir(path == '' or path.startswith('/'), 'JSON Pointer inválido')
    if path:
        for key in path[1:].split('/'):
            key = key.replace('~1', '/').replace('~0', '~')
            value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def semantic_checks(out, inp):
    exigir(out['alcance'] == inp['solicitud'], 'Alcance alterado')
    ids = [v['id'] for v in out['visualizaciones']]
    ids += [i['id'] for i in out['informes']]
    ids += [x['id'] for i in out['informes'] for k in ('hallazgos', 'recomendaciones') for x in i[k]]
    exigir(len(ids) == len(set(ids)), 'IDs locales duplicados')
    sources = {f['id']: f for f in inp['fuentes']}
    declared = {f['id']: f for f in out['fuentes']}
    exigir(len(declared) == len(out['fuentes']), 'Fuentes duplicadas')
    for sid, f in declared.items():
        exigir(sid in sources, 'Fuente inexistente')
        exigir(f == {k: v for k, v in sources[sid].items() if k != 'datos'}, 'Metadata de fuente alterada')
    expected = {(m['id'], p['id']) for m in inp['momentos'] for p in m['preguntas']}
    got = [(c['momento_id'], c['pregunta_id']) for c in out['cobertura']]
    exigir(set(got) == expected and len(got) == len(expected), 'Cobertura incompleta o duplicada')
    if out['alcance']['modo'] == 'integral':
        exigir(len(out['informes']) == 1, 'Integral requiere un informe')
        exigir(out['informes'][0]['momento_ids'] == inp['solicitud']['momento_ids'], 'Integral incompleto')
    else:
        exigir([i['momento_ids'] for i in out['informes']] == [[m] for m in inp['solicitud']['momento_ids']], 'Informes por momento incorrectos')
    visuals = {v['id']: v for v in out['visualizaciones']}
    used = set()
    for report in out['informes']:
        hids = {h['id'] for h in report['hallazgos']}
        for rec in report['recomendaciones']:
            exigir(set(rec['hallazgo_ids']) <= hids and bool(rec['hallazgo_ids']), 'Acción sin hallazgo válido')
        for h in report['hallazgos']:
            exigir(set(h['fuente_ids']) <= set(declared), 'Hallazgo con fuente inexistente')
            if out['alcance']['modo'] == 'por_momento':
                for sid in h['fuente_ids']:
                    exigir(set(declared[sid]['momento_ids']) <= set(report['momento_ids']), 'Cruce no permitido entre momentos')
            for vid in h['visualizacion_ids']:
                exigir(vid in visuals, 'Visualización inexistente')
                used.add(vid)
            for q in h['citas']:
                exigir(q['fuente_id'] in h['fuente_ids'], 'Cita sin fuente declarada')
                original = pointer(sources[q['fuente_id']]['datos'], q['localizador'])
                exigir(isinstance(original, str) and q['texto'] in original and bool(q['texto']), 'Cita no literal')
            for m in h['metricas']:
                for r in m['referencias']:
                    exigir(r['fuente_id'] in h['fuente_ids'], 'Métrica sin fuente declarada')
                    pointer(sources[r['fuente_id']]['datos'], r['ruta'])
                if m['unidad'] == 'porcentaje':
                    check_percent(m['valor'], m['numerador'], m['denominador'])
    exigir(used == set(visuals), 'Visualizaciones huérfanas')
    for v in out['visualizaciones']:
        exigir(set(v['fuente_ids']) <= set(declared), 'Visualización sin fuente válida')
        d = v['datos']
        if d.get('unidad') == 'porcentaje':
            for row in d.get('filas', []):
                check_percent(row['valor'], row['numerador'], row['denominador'])
        if v['tipo'] == 'red_semantica':
            nodes = {n['id'] for n in d['nodos']}
            exigir(len(nodes) == len(d['nodos']), 'Nodos duplicados')
            for edge in d['aristas']:
                exigir(edge['origen'] in nodes and edge['destino'] in nodes, 'Arista inválida')
                if d['tipo_relacion'] == 'interpretativa':
                    exigir(edge['peso'] is None, 'Peso interpretativo inventado')
        if v['tipo'] in ('tabla', 'matriz_cualitativa'):
            exigir(all(len(r['celdas']) == len(d['columnas']) for r in d['filas']), 'Tabla desalineada')


def check_percent(value, numerator, denominator):
    exigir(numerator is not None and denominator is not None and denominator > 0, 'Base porcentual ausente')
    exigir(0 <= numerator <= denominator, 'Numerador porcentual inválido')
    exigir(value is not None and abs(value - 100 * numerator / denominator) <= 0.011, 'Porcentaje incorrecto')


def main():
    Draft202012Validator.check_schema(SCHEMA)
    files = sorted((BASE / 'ejemplos').glob('*.salida.json'))
    paired = 0
    for path in files:
        out = json.loads(path.read_text())
        VALIDATOR.validate(out)
        input_path = path.with_name(path.name.replace('.salida.', '.entrada.'))
        if input_path.exists():
            semantic_checks(out, json.loads(input_path.read_text()))
            paired += 1
        print(f'OK {path.name}')
    original = json.loads((BASE / 'ejemplos/llm_integral.salida.json').read_text())
    inp = json.loads((BASE / 'ejemplos/llm_integral.entrada.json').read_text())
    mutants = []
    bad = copy.deepcopy(original); bad['html'] = '<p>No permitido</p>'; mutants.append(bad)
    bad = copy.deepcopy(original); bad['informes'][0]['hallazgos'][0]['metricas'][0]['valor'] = 90; mutants.append(bad)
    bad = copy.deepcopy(original); bad['informes'][0]['hallazgos'][0]['citas'][0]['texto'] = 'Cita inventada'; mutants.append(bad)
    bad = copy.deepcopy(original); bad['informes'][0]['hallazgos'][0]['visualizacion_ids'] = ['no-existe']; mutants.append(bad)
    for n, bad in enumerate(mutants, 1):
        rejected = False
        try:
            VALIDATOR.validate(bad)
            semantic_checks(bad, inp)
        except (ValueError, KeyError, IndexError, TypeError, __import__('jsonschema').ValidationError):
            rejected = True
        exigir(rejected, f'Mutación inválida {n} aceptada')
    print(f'Esquema válido; {len(files)} salidas; {paired} pares comprobados; {len(mutants)} mutaciones rechazadas.')
    print('No se evaluó un LLM real ni la calidad interpretativa de sus respuestas.')


if __name__ == '__main__':
    main()
