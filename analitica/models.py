from django.conf import settings
from django.db import models

from jornadas.models import Jornada, Momento


class PlantillaAnalisis(models.Model):
    nombre = models.CharField(max_length=150, unique=True)
    prompt_sistema = models.TextField(
        help_text='Instrucciones de tono, foco y longitud para el LLM. Los datos '
        '(estadísticas y tópicos) se le entregan aparte, ya calculados.'
    )
    predeterminada = models.BooleanField(default=False)
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='plantillas_analisis_creadas',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.predeterminada:
            PlantillaAnalisis.objects.exclude(pk=self.pk).update(predeterminada=False)


class Reporte(models.Model):
    ALCANCE_JORNADA = 'jornada'
    ALCANCE_MOMENTO = 'momento'
    ALCANCE_MOMENTOS = 'momentos'
    ALCANCE_CHOICES = [
        (ALCANCE_JORNADA, 'Jornada completa'),
        (ALCANCE_MOMENTO, 'Momento individual'),
        (ALCANCE_MOMENTOS, 'Momentos combinados'),
    ]

    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_PROCESANDO = 'procesando'
    ESTADO_COMPLETO = 'completo'
    ESTADO_ERROR = 'error'
    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, 'Pendiente'),
        (ESTADO_PROCESANDO, 'Procesando'),
        (ESTADO_COMPLETO, 'Completo'),
        (ESTADO_ERROR, 'Error'),
    ]

    jornada = models.ForeignKey(Jornada, on_delete=models.CASCADE, related_name='reportes')
    momentos = models.ManyToManyField(Momento, blank=True, related_name='reportes')
    alcance = models.CharField(max_length=10, choices=ALCANCE_CHOICES)
    plantilla = models.ForeignKey(
        PlantillaAnalisis, on_delete=models.SET_NULL, null=True, blank=True, related_name='reportes'
    )
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    error_mensaje = models.TextField(blank=True)

    analisis = models.JSONField(
        default=dict, blank=True,
        help_text='Estructura jerárquica: participación + análisis por momento y por pregunta '
        '(descripción, tipo de gráfica, valores característicos). Ver analitica/analysis.py.',
    )
    texto_reporte = models.TextField(blank=True)
    modelo_usado = models.CharField(max_length=150, blank=True)

    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reportes_solicitados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    completado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado_en']

    def __str__(self):
        return f'Reporte {self.id} · {self.jornada.slug} · {self.alcance} · {self.estado}'
