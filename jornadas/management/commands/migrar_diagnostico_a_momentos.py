"""Reconstruye el "Instrumento de Diagnóstico para la Articulación Académica" como UN SOLO
Momento/varias Preguntas de la jornada clásica (`jornadas.Momento`/`jornadas.Pregunta`), en vez
del módulo separado `instrumentos` — el frontend de administración de jornadas (pestaña
"Instrumento" = momentos/preguntas) no tiene ninguna vista para `instrumentos.Instrumento`, así
que ese contenido nunca aparecía ahí por más que estuviera bien vinculado en la base de datos.
Un solo momento (no uno por sección) para que la sesión se sienta como un único recorrido
fluido, no una serie de pasos separados.

Lee el contenido YA CARGADO en `instrumentos.Instrumento` (slug
'diagnostico-articulacion-academica', ver `cargar_instrumento_diagnostico_articulacion`) y lo
copia 1:1 — no retipea ningún texto. Desde que `jornadas.Pregunta` tiene tipo `matriz` (con
`FilaMatrizPregunta`/`ColumnaMatrizPregunta`, mismo diseño que ya existía en `instrumentos`), cada
pregunta tipo matriz del instrumento se copia como UNA pregunta matriz con sus filas y columnas
reales — ya NO se aplana en una pregunta por celda (esa era la versión anterior de este comando,
necesaria mientras `Pregunta` solo tenía abierta/única/múltiple).

Idempotente: borra y recrea el Momento de la jornada indicada en cada corrida.

Uso:
    python manage.py migrar_diagnostico_a_momentos
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from instrumentos.models import Instrumento, PreguntaInstrumento, SeccionInstrumento
from jornadas.models import ColumnaMatrizPregunta, FilaMatrizPregunta, Momento, OpcionPregunta, Pregunta

SLUG_INSTRUMENTO = 'diagnostico-articulacion-academica'


class Command(BaseCommand):
    help = 'Reconstruye el diagnóstico de articulación académica como un único Momento/Preguntas de su jornada.'

    def handle(self, *args, **options):
        try:
            instrumento = Instrumento.objects.get(slug=SLUG_INSTRUMENTO)
        except Instrumento.DoesNotExist:
            raise CommandError(
                f'No existe el Instrumento "{SLUG_INSTRUMENTO}" — corre primero '
                'cargar_instrumento_diagnostico_articulacion.'
            )
        if instrumento.jornada_id is None:
            raise CommandError('El instrumento no está vinculado a ninguna Jornada (instrumento.jornada).')

        jornada = instrumento.jornada

        with transaction.atomic():
            Momento.objects.filter(jornada=jornada).delete()

            secciones_contenido = list(
                instrumento.secciones.filter(tipo=SeccionInstrumento.TIPO_CONTENIDO).order_by('orden')
            )
            contexto = '\n\n'.join(s.contenido for s in secciones_contenido if s.contenido).strip()

            momento = Momento.objects.create(
                jornada=jornada, orden=1, titulo=instrumento.nombre,
                contexto=contexto, tipo=Momento.TIPO_INDIVIDUAL,
            )

            orden_pregunta = 1
            for seccion in instrumento.secciones.filter(
                tipo=SeccionInstrumento.TIPO_PREGUNTAS
            ).order_by('orden'):
                for pregunta in seccion.preguntas.all().order_by('orden'):
                    if pregunta.tipo == PreguntaInstrumento.TIPO_MATRIZ:
                        nueva = Pregunta.objects.create(
                            momento=momento, tipo=Pregunta.TIPO_MATRIZ, texto=pregunta.texto,
                            orden=orden_pregunta, obligatoria=pregunta.obligatoria,
                        )
                        orden_pregunta += 1
                        for fila in pregunta.filas.all().order_by('orden'):
                            FilaMatrizPregunta.objects.create(pregunta=nueva, texto=fila.texto, orden=fila.orden)
                        for columna in pregunta.columnas.all().order_by('orden'):
                            ColumnaMatrizPregunta.objects.create(
                                pregunta=nueva, texto=columna.texto, orden=columna.orden
                            )
                        continue

                    tipo = (
                        Pregunta.TIPO_MULTIPLE if pregunta.tipo == PreguntaInstrumento.TIPO_MULTIPLE
                        else Pregunta.TIPO_UNICA if pregunta.tipo == PreguntaInstrumento.TIPO_UNICA
                        else Pregunta.TIPO_ABIERTA
                    )
                    nueva = Pregunta.objects.create(
                        momento=momento, tipo=tipo, texto=pregunta.texto,
                        orden=orden_pregunta, obligatoria=pregunta.obligatoria,
                    )
                    orden_pregunta += 1
                    for opcion in pregunta.opciones.all().order_by('orden'):
                        OpcionPregunta.objects.create(pregunta=nueva, texto=opcion.texto, orden=opcion.orden)

        total_preguntas = Pregunta.objects.filter(momento__jornada=jornada).count()
        total_matriz = Pregunta.objects.filter(momento__jornada=jornada, tipo=Pregunta.TIPO_MATRIZ).count()
        self.stdout.write(self.style.SUCCESS(
            f'Jornada "{jornada.nombre}" ({jornada.slug}): 1 momento, {total_preguntas} preguntas '
            f'({total_matriz} de tipo matriz).'
        ))
