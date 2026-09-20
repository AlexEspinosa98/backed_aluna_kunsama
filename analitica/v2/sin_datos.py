"""Salida v2 para un alcance sin ninguna respuesta, construida por el backend sin llamar a la IA
(D11 del plan). `sin_datos` es un estado ANALÍTICO válido del contrato (el frontend lo renderiza
como estado vacío); gastar una llamada cara para que un modelo produzca "no hay datos" es más
lento y menos fiable que producirlo acá. Pasa por las mismas dos capas de validación que una
respuesta del modelo (procesar.py): si no pasara, es un bug."""
from .contrato import MODO_INTEGRAL, VERSION

RESUMEN_INTEGRAL = (
    'No se registraron respuestas en ningún momento del alcance. No hay evidencia para formular '
    'hallazgos ni recomendaciones.'
)
RESUMEN_MOMENTO = (
    'No se registraron respuestas en este momento. No hay evidencia para formular hallazgos ni '
    'recomendaciones.'
)
NOTA_COBERTURA = 'No se registró ninguna respuesta para esta pregunta.'


def construir_salida_sin_datos(entrada, pipeline):
    solicitud = entrada['solicitud']
    fuentes = [
        {k: f[k] for k in ('id', 'tipo', 'etiqueta', 'momento_ids', 'pregunta_ids', 'cobertura')}
        for f in entrada['fuentes']
    ]
    cobertura = [
        {'momento_id': m['id'], 'pregunta_id': p['id'], 'estado': 'sin_datos', 'metodos': [], 'nota': NOTA_COBERTURA}
        for m in entrada['momentos'] for p in m['preguntas']
    ]
    if solicitud['modo'] == MODO_INTEGRAL:
        informes = [{
            'id': 'i1', 'momento_ids': list(solicitud['momento_ids']),
            'titulo': entrada['jornada']['nombre'], 'resumen': RESUMEN_INTEGRAL,
            'hallazgos': [], 'recomendaciones': [],
        }]
    else:
        nombres = {m['id']: m['nombre'] for m in entrada['momentos']}
        informes = [
            {
                'id': f'i{n}', 'momento_ids': [momento_id], 'titulo': nombres.get(momento_id, momento_id),
                'resumen': RESUMEN_MOMENTO, 'hallazgos': [], 'recomendaciones': [],
            }
            for n, momento_id in enumerate(solicitud['momento_ids'], start=1)
        ]
    return {
        'version': VERSION,
        'pipeline': pipeline,
        'estado': 'sin_datos',
        'alcance': {'modo': solicitud['modo'], 'jornada_id': solicitud['jornada_id'], 'momento_ids': list(solicitud['momento_ids'])},
        'fuentes': fuentes,
        'cobertura': cobertura,
        'limitaciones': [],
        'informes': informes,
        'visualizaciones': [],
    }
