"""Retoma los análisis integrales (HU-98) y los resúmenes para presentación (HU-99) que esperan a
OpenAI en segundo plano.

Cada análisis lo sigue su propio hilo, que consulta cada 30 s. Pero un reinicio del servidor
mata ese hilo, y entonces nadie recogería la respuesta que OpenAI igual termina. Este comando,
corrido por cron cada 5 minutos, consulta una vez cada análisis en curso que nadie haya consultado
en el último minuto y lo avanza (publica, lanza la reparación o marca error) — el mismo paso que
da el hilo, con la fila bloqueada para que nunca lo procesen los dos a la vez.

    */5 * * * * cd <app> && venv/bin/python manage.py consultar_analisis_background

Sin `store` en OpenAI la respuesta terminada dura ~10 minutos: cada 5 alcanza.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from analitica.models import AnalisisJornadaIA, ResumenPresentacion
from analitica.v2.background import avanzar_en_segundo_plano
from auditoria.openai_cliente import contexto_llamada


class Command(BaseCommand):
    help = 'Consulta y avanza lo que espera a OpenAI en segundo plano (análisis integrales y resúmenes).'

    def handle(self, *args, **opciones):
        hace_un_minuto = timezone.now() - timedelta(minutes=1)
        for Modelo in (AnalisisJornadaIA, ResumenPresentacion):
            pendientes = (
                Modelo.objects.filter(estado=Modelo.ESTADO_PROCESANDO)
                .exclude(respuesta_openai_id='')
                .exclude(consultado_en__gt=hace_un_minuto)
            )
            for registro in pendientes:
                with contexto_llamada(origen=registro):
                    terminado = avanzar_en_segundo_plano(Modelo, registro.id)
                registro.refresh_from_db(fields=['estado', 'fase_openai'])
                self.stdout.write(
                    f'{timezone.now():%Y-%m-%d %H:%M:%S} {Modelo.__name__} {registro.id}: '
                    f'{registro.estado} ({registro.fase_openai}){" — terminó" if terminado else ""}'
                )
