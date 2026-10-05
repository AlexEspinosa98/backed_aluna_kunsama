"""Crea las versiones de los system prompts para el contrato `kunsamu.analisis/v2.1` (HU-100).

Los prompts viven en la tabla `SystemPrompt` y la versión activa de cada tipo puede haberla escrito
alguien desde el admin (no está en el repo). Por eso este comando no trae textos completos: parte
de la versión ACTIVA de cada tipo, le aplica solo los cambios de v2.1 (recursos/
CONTRATO_ANALISIS_V2_1.md) y crea la versión siguiente — inmutable una vez activada, como todas.

- `analisis_llm` y `analisis_bertopic`: versión del contrato, párrafo de colores y de grafos y
  flujos, catálogo de 20 tipos y la extensión sugerida del informe (cifras en vez de adjetivos).
- `resumen_presentacion`: versión del contrato y regla de colores.

Si una frase que el cambio necesita reemplazar no está en la versión activa (alguien la reescribió),
NO crea esa versión: lo informa, para que el cambio se haga a mano y nada quede contradictorio.

    python manage.py actualizar_prompts_v2_1              # crea borradores
    python manage.py actualizar_prompts_v2_1 --activar    # crea y activa
"""
import re

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analitica.models import SystemPrompt

MARCA = 'contrato v2.1'

BLOQUE_COLORES_ANALISIS = """### Colores, grafos y flujos (contrato v2.1)

- **Colores.** Declara colores (`#rrggbb`) sólo cuando el color tiene significado: semáforos, Sí/No, escalas ordenadas, grupos de actores o temas. Usa el mismo color para el mismo concepto en todo el informe (Sí siempre del mismo verde, el mismo actor siempre del mismo color). Si el color no significa nada, deja `[]` o `null`: el visor aplica su paleta. Cada tipo tiene su campo: `colores_series` (varias series, radar, líneas), `colores_categorias` (barras simples y dona), `escala` (mapa de calor; con `color_medio` es divergente), `colores_terminos` (nube), `color` en histograma y en grupos de caja, y `grupos[].color` / `nodos[].color` / `flujos[].color` en redes, grafos, sankey y treemap.
- **Grafos y flujos.** Para actores, entidades o procesos y sus relaciones usa `grafo`, con `grupos` (sector, tipo de actor) y `etiqueta` en cada arista («financia», «depende de»), y `tipo_relacion` `flujo`, `jerarquia`, `influencia` o `pertenencia`; reserva `red_semantica` para términos del texto, con `coocurrencia`, `similitud` o `interpretativa`. Para «cuánto va de A a B» usa `sankey`: ids de nodo únicos, flujos entre nodos existentes, `valor ≥ 0`, sin flujos de un nodo a sí mismo y **sin ciclos**. Para «de qué se compone y con qué peso» usa `treemap`: al menos una raíz (`padre: null`), sin ciclos, hojas con `valor ≥ 0` y nodos con hijos con `valor: null` (el visor suma).
- El catálogo tiene **20** variantes: las anteriores más `grafo`, `sankey` y `treemap`.

"""

# (frase de la versión activa, reemplazo) — extensión del informe sugerida por el contrato v2.1.
EXTENSION = [
    (
        'Cada `afirmacion`: 1 o 2 frases, hasta 65 palabras, ancladas a evidencia. `implicacion`: hasta 35 palabras o `null`.',
        'Cada `afirmacion`: de 3 a 5 oraciones, ancladas a evidencia: qué se observó, en qué medida, por qué y con qué matices. `implicacion`: siempre, en una o dos frases; `null` sólo si la evidencia no permite ninguna consecuencia para decidir.',
    ),
    (
        'No impongas una cantidad mínima de hallazgos. Prioriza y combina duplicados sin borrar diferencias sustantivas. Habitualmente bastan de 3 a 6 por informe; si el corpus exige más para no omitir una decisión relevante, amplía el número y conserva la brevedad de cada uno. No rellenes listas.',
        'Entre 5 y 8 hallazgos por informe cuando la evidencia lo sostiene; menos si el material no da para más, nunca rellenando. Prioriza y combina duplicados sin borrar diferencias sustantivas. En cada hallazgo cualitativo incluye al menos dos citas literales cuando existan; en cada cuantitativo, una o dos métricas; y una visualización por cada hallazgo cuantitativo.',
    ),
    (
        'No fuerces recomendaciones si la evidencia no permite ninguna; usa `[]`.',
        'Apunta a entre 3 y 6 recomendaciones por informe cuando la evidencia las sostiene. No fuerces recomendaciones si la evidencia no permite ninguna; usa `[]`.',
    ),
]

BLOQUE_COLORES_RESUMEN = """- **Colores (contrato v2.1).** Copia los colores que traiga cada visualización. Si una visualización organiza los resultados en niveles o estados (un semáforo, Sí/No, una escala ordenada) y no trae colores, decláralos (`#rrggbb`) en `colores_categorias` (una serie) o `colores_series` (varias): por ejemplo verde, amarillo y rojo para un semáforo. Usa el mismo color para el mismo concepto en todo el resumen. Fuera de esos casos deja `[]` o `null`: el visor aplica su paleta. Los colores no son datos: declararlos no rompe la regla de «nada nuevo», siempre que los datos de la visualización queden idénticos.
"""


def _con_version_nueva(texto):
    return re.sub(r'kunsamu\.analisis/v2(?![.\d])', 'kunsamu.analisis/v2.1', texto)


def _parche_analisis(texto):
    texto = _con_version_nueva(texto)
    ancla = '## Redacción y decisiones'
    if ancla not in texto:
        raise ValueError(f'no encuentra la sección «{ancla}»')
    texto = texto.replace(ancla, BLOQUE_COLORES_ANALISIS + ancla, 1)
    for actual, nuevo in EXTENSION:
        if actual not in texto:
            raise ValueError(f'no encuentra la frase a reemplazar: «{actual[:70]}…»')
        texto = texto.replace(actual, nuevo, 1)
    return texto


def _parche_resumen(texto):
    texto = _con_version_nueva(texto)
    actual = '- **No modifiques los datos de una visualización.** Una visualización se copia completa con su `id`, `tipo`, `datos`, `metodo`, `unidad_analisis`, `base` y `fuente_ids`. Puedes acortar su `titulo` y su `nota`; nada más.'
    if actual not in texto:
        raise ValueError('no encuentra la regla «No modifiques los datos de una visualización»')
    texto = texto.replace(actual, actual.replace('; nada más.', ', y declarar colores según la regla de colores (ver «Visualizaciones»); nada más.'), 1)
    ancla = '## Limitaciones'
    if ancla not in texto:
        raise ValueError(f'no encuentra la sección «{ancla}»')
    return texto.replace(ancla, BLOQUE_COLORES_RESUMEN + '\n' + ancla, 1)


CAMBIOS = {
    'analisis_llm': (_parche_analisis, 'Contrato v2.1: colores, grafos/sankey/treemap y extensión del informe'),
    'analisis_bertopic': (_parche_analisis, 'Contrato v2.1: colores, grafos/sankey/treemap y extensión del informe'),
    'resumen_presentacion': (_parche_resumen, 'Contrato v2.1: colores con significado'),
}


class Command(BaseCommand):
    help = 'Crea (y opcionalmente activa) las versiones de los prompts para el contrato v2.1.'

    def add_arguments(self, parser):
        parser.add_argument('--activar', action='store_true')
        parser.add_argument('--usuario', default=None, help='username que queda como autor/activador')

    def handle(self, *args, **opciones):
        usuario = None
        if opciones['usuario']:
            usuario = get_user_model().objects.filter(username=opciones['usuario']).first()
            if usuario is None:
                raise CommandError(f"No existe el usuario {opciones['usuario']!r}")
        for tipo, (parche, etiqueta) in CAMBIOS.items():
            activo = SystemPrompt.activo_de(tipo)
            if MARCA in activo.contenido:
                self.stdout.write(f'{tipo}: {activo.referencia} ya está en v2.1, no se crea nada.')
                continue
            try:
                contenido = parche(activo.contenido)
            except ValueError as exc:
                self.stdout.write(self.style.ERROR(f'{tipo}: NO se creó — {exc}. Hay que hacerlo a mano.'))
                continue
            with transaction.atomic():
                nuevo = SystemPrompt.objects.create(
                    tipo=tipo, contenido=contenido, etiqueta=etiqueta[:60], creado_por=usuario,
                    notas=f'Creada desde {activo.referencia} por `actualizar_prompts_v2_1` (HU-100): {etiqueta}.',
                )
                if opciones['activar']:
                    nuevo.activar(usuario)
            estado = 'activa' if opciones['activar'] else 'borrador'
            self.stdout.write(self.style.SUCCESS(
                f'{tipo}: {activo.referencia} → {nuevo.referencia} ({estado}, {len(contenido)} caracteres)'
            ))
