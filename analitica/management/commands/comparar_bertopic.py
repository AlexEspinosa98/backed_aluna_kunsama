"""Herramienta EXPERIMENTAL de comparación (ver analitica/topicos_experimental.py). No es un
endpoint de la API — se corre a mano, no aparece en Swagger ni en docs/USER_STORIES.md. Genera dos
PDF (flujo actual de producción vs. flujo mejorado) para evaluar antes de decidir si se adopta.

Uso:
    python manage.py comparar_bertopic --jornada jornada-agil-2
    python manage.py comparar_bertopic --jornada jornada-agil-2 --min-respuestas 8 --salida /tmp
"""
from django.core.management.base import BaseCommand, CommandError

from analitica.analysis import MIN_RESPUESTAS_TOPICOS
from analitica.pdf_comparacion import generar_pdf_actual, generar_pdf_mejorado
from analitica.topicos_experimental import comparar_pregunta
from jornadas.models import Jornada, Pregunta
from participantes.models import Respuesta


class Command(BaseCommand):
    help = (
        'Compara el flujo de tópicos ACTUAL (producción) vs. uno MEJORADO (experimental: '
        'stopwords ampliadas, tri-términos, etiquetas por LLM, relación entre temas) sobre las '
        'preguntas abiertas de una jornada, y genera dos PDF para evaluar. No toca producción.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--jornada', default='jornada-agil-2', help='Slug de la jornada.')
        parser.add_argument(
            '--min-respuestas', type=int, default=MIN_RESPUESTAS_TOPICOS,
            help=f'Mínimo de respuestas no vacías para incluir una pregunta (default {MIN_RESPUESTAS_TOPICOS}).',
        )
        parser.add_argument('--salida', default='.', help='Carpeta donde escribir los PDF.')

    def handle(self, *args, **options):
        try:
            jornada = Jornada.objects.get(slug=options['jornada'])
        except Jornada.DoesNotExist as exc:
            raise CommandError(f"No existe una jornada con slug '{options['jornada']}'.") from exc

        preguntas = (
            Pregunta.objects.filter(momento__jornada=jornada, tipo='abierta')
            .select_related('momento')
            .order_by('momento__orden', 'orden')
        )

        resultados = []
        for pregunta in preguntas:
            n = Respuesta.objects.filter(pregunta=pregunta).exclude(texto_libre='').count()
            if n < options['min_respuestas']:
                self.stdout.write(f'  [omitida] pregunta {pregunta.id}: solo {n} respuestas')
                continue
            self.stdout.write(f'  comparando pregunta {pregunta.id} ({n} respuestas)...')
            resultados.append(comparar_pregunta(pregunta))

        if not resultados:
            raise CommandError(
                'Ninguna pregunta abierta alcanzó el mínimo de respuestas — no hay nada que comparar.'
            )

        salida_actual = f"{options['salida']}/bertopic_actual.pdf"
        salida_mejorado = f"{options['salida']}/bertopic_mejorado.pdf"
        generar_pdf_actual(resultados, salida_actual, jornada.nombre)
        generar_pdf_mejorado(resultados, salida_mejorado, jornada.nombre)

        self.stdout.write(self.style.SUCCESS(
            f'Listo: {len(resultados)} preguntas comparadas.\n  {salida_actual}\n  {salida_mejorado}'
        ))
