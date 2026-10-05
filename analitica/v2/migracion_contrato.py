"""Lleva una salida `kunsamu.analisis/v2` a `v2.1` (HU-100) sin cambiar su contenido.

v2.1 agrega campos obligatorios (colores, grupos y rótulos de red) que en v2 no existían. Esta
función los agrega con su valor "vacío" — `[]` o `null`, que en v2.1 significa "sin color propio:
paleta del visor" — y sube la versión. No inventa colores ni toca datos.

La usan:
- el resumen para presentación (HU-99), para mandarle al modelo las visualizaciones de un
  análisis v2 ya en la forma v2.1 que tiene que devolver (y así poder copiarlas idénticas);
- la conversión de los ejemplos congelados de la entrega a v2.1.

Los análisis v2 GUARDADOS no se migran: el frontend lee las dos versiones.
"""
import copy

from .contrato import VERSION

_CATEGORICOS = ('barras', 'barras_agrupadas', 'barras_apiladas', 'barras_100', 'dona', 'radar')
_COORDENADAS = ('lineas', 'areas', 'dispersion', 'pendientes')


def _visual_a_v2_1(visual):
    tipo, datos = visual['tipo'], visual['datos']
    if tipo in _CATEGORICOS:
        datos.setdefault('colores_series', [])
        datos.setdefault('colores_categorias', [])
    elif tipo in _COORDENADAS:
        datos.setdefault('colores_series', [])
    elif tipo == 'histograma':
        datos.setdefault('color', None)
    elif tipo == 'caja_bigotes':
        for grupo in datos.get('grupos', []):
            grupo.setdefault('color', None)
    elif tipo == 'mapa_calor':
        datos.setdefault('escala', None)
    elif tipo == 'nube_palabras':
        datos.setdefault('colores_terminos', [])
    elif tipo in ('red_semantica', 'grafo'):
        datos.setdefault('grupos', [])
        for nodo in datos.get('nodos', []):
            nodo.setdefault('grupo', None)
            nodo.setdefault('color', None)
        for arista in datos.get('aristas', []):
            arista.setdefault('etiqueta', None)
    return visual


def visualizaciones_a_v2_1(visualizaciones):
    """Copia de la lista de visualizaciones con los campos de v2.1 completos."""
    return [_visual_a_v2_1(v) for v in copy.deepcopy(visualizaciones or [])]


def salida_a_v2_1(salida):
    """Copia de una salida v2 (o v2.1) en la forma v2.1."""
    nueva = copy.deepcopy(salida)
    nueva['version'] = VERSION
    nueva['visualizaciones'] = visualizaciones_a_v2_1(nueva.get('visualizaciones'))
    return nueva
