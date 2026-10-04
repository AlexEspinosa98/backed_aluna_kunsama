"""Separa lo que una carga de documento le pisó a alguien que ya había respondido (HU-91).

Antes de HU-91, escribir una extracción hacía `update_or_create` celda por celda sobre las
respuestas del participante: si esa persona ya había respondido por la web, las celdas que el
documento traía reemplazaban las suyas y las demás quedaban como estaban. El resultado es una
mezcla que no es ni lo que respondió ni lo que decía el documento.

Lo que había respondido no está en ningún lado de la base actual, pero sí en un respaldo previo a
la carga. Este comando, por cada extracción indicada:

1. lee del RESPALDO las respuestas que la persona tenía en ese momento (con sus opciones y filas
   agregadas);
2. borra la mezcla actual y las vuelve a escribir como **versión 1**, con sus fechas originales;
3. escribe la transcripción del documento (`ExtraccionMomento.resultado`, intacta) como
   **versión 2**.

El respaldo tiene que estar restaurado en una base aparte del mismo servidor de PostgreSQL (mismas
credenciales que `default`), por ejemplo:

    docker exec aluna_kunsama_db createdb -U aluna_kunsamu aluna_respaldo_20260920
    docker exec -i aluna_kunsama_db pg_restore -U aluna_kunsamu -d aluna_respaldo_20260920 \\
        --no-owner --no-acl < ~/backups/aluna_kunsama/20260920_032349/db/aluna_kunsamu.dump

Se lee con SQL directo y no con el ORM porque el esquema del respaldo es el de su fecha (no tiene
`version`, por ejemplo).

Por defecto NO escribe nada: corre todo dentro de una transacción, informa y la revierte. Con
`--aplicar` la confirma — una transacción por extracción, así que una que falle no deja a las
demás a medias.

Uso:
    python manage.py restaurar_respuestas_extraccion 7 11 15 19 21 --respaldo-db aluna_respaldo_20260920
    python manage.py restaurar_respuestas_extraccion 7 11 15 19 21 --respaldo-db aluna_respaldo_20260920 --aplicar
"""
import psycopg2
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from jornadas.models import ColumnaMatrizPregunta, FilaMatrizPregunta, OpcionPregunta, Pregunta
from participantes.extraccion_momento_ia_openai import MODO_NUEVA_VERSION, escribir_extraccion_momento
from participantes.models import ExtraccionMomento, FilaListaRespuesta, Participante, Respuesta


class _Simulacion(Exception):
    """Se lanza al final de una corrida sin `--aplicar` para revertir la transacción."""


class Command(BaseCommand):
    help = (
        'Restaura como versión 1 las respuestas que una carga de documento pisó (leyéndolas de un '
        'respaldo) y deja el documento como versión 2.'
    )

    def add_arguments(self, parser):
        parser.add_argument('extracciones', nargs='+', type=int, help='IDs de ExtraccionMomento.')
        parser.add_argument(
            '--respaldo-db', required=True,
            help='Nombre de la base donde está restaurado el respaldo (mismo servidor y credenciales).',
        )
        parser.add_argument('--aplicar', action='store_true', help='Confirma los cambios.')
        parser.add_argument(
            '--forzar', action='store_true',
            help='Sigue aunque haya ediciones web posteriores al respaldo (se perderían).',
        )

    def handle(self, *args, **opciones):
        respaldo = self._conectar(opciones['respaldo_db'])
        try:
            corte = self._fecha_del_respaldo(respaldo)
            self.stdout.write(f'Respaldo {opciones["respaldo_db"]}: última respuesta guardada {corte}.')
            if not opciones['aplicar']:
                self.stdout.write(self.style.WARNING('SIMULACIÓN — no se escribe nada (usa --aplicar).'))
            for extraccion_id in opciones['extracciones']:
                self.stdout.write('')
                try:
                    with transaction.atomic():
                        self._restaurar(extraccion_id, respaldo, corte, opciones['forzar'])
                        if not opciones['aplicar']:
                            raise _Simulacion
                    self.stdout.write(self.style.SUCCESS(f'  Extracción {extraccion_id}: restaurada.'))
                except _Simulacion:
                    self.stdout.write(f'  Extracción {extraccion_id}: simulada, revertida.')
                except CommandError as exc:
                    self.stdout.write(self.style.ERROR(f'  Extracción {extraccion_id}: omitida — {exc}'))
        finally:
            respaldo.close()

    # --- respaldo ------------------------------------------------------------------------------
    def _conectar(self, nombre):
        db = settings.DATABASES['default']
        try:
            return psycopg2.connect(
                dbname=nombre, user=db.get('USER'), password=db.get('PASSWORD'),
                host=db.get('HOST') or 'localhost', port=db.get('PORT') or 5432,
            )
        except psycopg2.Error as exc:
            raise CommandError(f'No se pudo conectar a la base del respaldo "{nombre}": {exc}')

    def _fecha_del_respaldo(self, respaldo):
        with respaldo.cursor() as cur:
            cur.execute('SELECT max(actualizado_en) FROM participantes_respuesta')
            return cur.fetchone()[0]

    def _leer_respaldo(self, respaldo, participante_id, momento_id):
        with respaldo.cursor() as cur:
            cur.execute(
                """
                SELECT r.id, r.pregunta_id, r.fila_id, r.columna_id, r.fila_lista_id,
                       r.texto_libre, r.registrado_por_id, r.creado_en, r.actualizado_en
                FROM participantes_respuesta r
                JOIN jornadas_pregunta p ON p.id = r.pregunta_id
                WHERE r.participante_id = %s AND p.momento_id = %s
                ORDER BY r.id
                """,
                [participante_id, momento_id],
            )
            columnas = [c[0] for c in cur.description]
            filas = [dict(zip(columnas, fila)) for fila in cur.fetchall()]
            if not filas:
                return [], {}, {}

            cur.execute(
                'SELECT respuesta_id, opcionpregunta_id FROM participantes_respuesta_opciones '
                'WHERE respuesta_id = ANY(%s)',
                [[f['id'] for f in filas]],
            )
            opciones = {}
            for respuesta_id, opcion_id in cur.fetchall():
                opciones.setdefault(respuesta_id, []).append(opcion_id)

            ids_fila_lista = sorted({f['fila_lista_id'] for f in filas if f['fila_lista_id']})
            filas_lista = {}
            if ids_fila_lista:
                cur.execute(
                    'SELECT id, pregunta_id, orden, creado_en FROM participantes_filalistarespuesta '
                    'WHERE id = ANY(%s)',
                    [ids_fila_lista],
                )
                filas_lista = {f[0]: {'pregunta_id': f[1], 'orden': f[2], 'creado_en': f[3]}
                               for f in cur.fetchall()}
        return filas, opciones, filas_lista

    # --- restauración --------------------------------------------------------------------------
    def _restaurar(self, extraccion_id, respaldo, corte, forzar):
        try:
            extraccion = ExtraccionMomento.objects.select_related(
                'participante', 'momento', 'aprobado_por',
            ).get(pk=extraccion_id)
        except ExtraccionMomento.DoesNotExist:
            raise CommandError('no existe.')
        persona, momento = extraccion.participante, extraccion.momento
        if persona is None or extraccion.aprobado_en is None:
            raise CommandError('no está escrita a nombre de nadie: no pisó nada.')
        self.stdout.write(
            f'Extracción {extraccion.id} «{extraccion.nombre_archivo_original}» → '
            f'{persona.nombre} {persona.apellido} (participante {persona.id}), momento {momento.id}'
        )

        actuales = Respuesta.objects.filter(participante=persona, pregunta__momento=momento)
        if actuales.exclude(version=Respuesta.VERSION_ORIGINAL).exists():
            raise CommandError('la persona ya tiene más de una versión en el momento — ¿ya se restauró?')

        filas, opciones, filas_lista = self._leer_respaldo(respaldo, persona.id, momento.id)
        if not filas:
            raise CommandError(
                'el respaldo no tiene respuestas suyas en este momento: no había nada que pisar.'
            )

        # Lo editado por la web DESPUÉS del respaldo y ANTES de la carga no está en el respaldo:
        # restaurar lo borraría. Lo escrito por la carga misma (o después) sí se reemplaza.
        perdidas = actuales.filter(actualizado_en__gt=corte, actualizado_en__lt=extraccion.creado_en).count()
        if perdidas and not forzar:
            raise CommandError(
                f'{perdidas} celdas se editaron después del respaldo y antes de la carga; se '
                'perderían. Usa --forzar si igual quieres restaurar.'
            )

        celdas_documento = len((extraccion.resultado or {}).get('respuestas') or [])
        self.stdout.write(
            f'  hoy: {actuales.count()} celdas (mezcla) · respaldo: {len(filas)} celdas web '
            f'→ versión 1 · documento: {celdas_documento} celdas → versión 2'
        )

        # Lo que el respaldo referencia tiene que seguir existiendo; si no, esa celda no se puede
        # volver a escribir y se informa en vez de inventar a dónde va.
        preguntas = set(Pregunta.objects.filter(momento=momento).values_list('id', flat=True))
        filas_fijas = set(FilaMatrizPregunta.objects.filter(pregunta__momento=momento).values_list('id', flat=True))
        columnas = set(ColumnaMatrizPregunta.objects.filter(pregunta__momento=momento).values_list('id', flat=True))
        opciones_validas = set(OpcionPregunta.objects.filter(pregunta__momento=momento).values_list('id', flat=True))
        participantes = set(Participante.objects.filter(jornada=momento.jornada).values_list('id', flat=True))

        actuales.delete()
        FilaListaRespuesta.objects.filter(participante=persona, pregunta__momento=momento).delete()

        nuevas_filas_lista = {}
        for viejo_id, datos in filas_lista.items():
            fila = FilaListaRespuesta.objects.create(
                pregunta_id=datos['pregunta_id'], participante=persona,
                version=Respuesta.VERSION_ORIGINAL, orden=datos['orden'],
            )
            FilaListaRespuesta.objects.filter(pk=fila.pk).update(creado_en=datos['creado_en'])
            nuevas_filas_lista[viejo_id] = fila.id

        escritas, descartadas = 0, 0
        for fila in filas:
            if (
                fila['pregunta_id'] not in preguntas
                or (fila['fila_id'] and fila['fila_id'] not in filas_fijas)
                or (fila['columna_id'] and fila['columna_id'] not in columnas)
            ):
                descartadas += 1
                continue
            respuesta = Respuesta.objects.create(
                pregunta_id=fila['pregunta_id'], participante=persona,
                version=Respuesta.VERSION_ORIGINAL,
                fila_id=fila['fila_id'], columna_id=fila['columna_id'],
                fila_lista_id=nuevas_filas_lista.get(fila['fila_lista_id']),
                texto_libre=fila['texto_libre'],
                registrado_por_id=fila['registrado_por_id'] if fila['registrado_por_id'] in participantes else None,
            )
            respuesta.opciones.set([o for o in opciones.get(fila['id'], []) if o in opciones_validas])
            # `auto_now`/`auto_now_add` las pisan al crear: se devuelven las originales después.
            Respuesta.objects.filter(pk=respuesta.pk).update(
                creado_en=fila['creado_en'], actualizado_en=fila['actualizado_en'],
            )
            escritas += 1
        if descartadas:
            self.stdout.write(self.style.WARNING(
                f'  {descartadas} celdas del respaldo apuntan a preguntas/filas/columnas que ya no '
                'existen y no se restauraron.'
            ))

        # El documento, como versión 2. Se conservan la fecha y el autor de la escritura original:
        # esto corrige DÓNDE quedó, no es una carga nueva.
        aprobado_en, aprobado_por = extraccion.aprobado_en, extraccion.aprobado_por
        documento = escribir_extraccion_momento(extraccion, aprobado_por, modo=MODO_NUEVA_VERSION)
        extraccion.aprobado_en = aprobado_en
        extraccion.save(update_fields=['aprobado_en'])

        self.stdout.write(
            f'  escritas: {escritas} celdas web en versión 1 · {len(documento)} celdas del '
            f'documento en versión {extraccion.version_escrita}'
        )
