from django.conf import settings
from django.db import models
from django.utils import timezone

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
    slug = models.SlugField(max_length=250, blank=True, unique=True, help_text=(
        'Autogenerado: jornada + alcance + fecha/hora local de Colombia — para poder '
        'distinguir reportes a simple vista, no solo por id.'
    ))
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

    # Presentación HTML generada por OpenAI a partir de `analisis` (ver analitica/presentacion.py)
    # — capa de presentación aparte del análisis en sí: se puede pedir, fallar o regenerar sin
    # tocar ni volver a correr el pipeline local (BERTopic + LLM local) que ya calculó los números.
    PRESENTACION_ESTADO_PENDIENTE = 'pendiente'
    PRESENTACION_ESTADO_PROCESANDO = 'procesando'
    PRESENTACION_ESTADO_COMPLETO = 'completo'
    PRESENTACION_ESTADO_ERROR = 'error'
    PRESENTACION_ESTADO_CHOICES = [
        (PRESENTACION_ESTADO_PENDIENTE, 'Pendiente'),
        (PRESENTACION_ESTADO_PROCESANDO, 'Procesando'),
        (PRESENTACION_ESTADO_COMPLETO, 'Completo'),
        (PRESENTACION_ESTADO_ERROR, 'Error'),
    ]
    presentacion_html = models.TextField(blank=True)
    presentacion_estado = models.CharField(
        max_length=12, choices=PRESENTACION_ESTADO_CHOICES, default=PRESENTACION_ESTADO_PENDIENTE,
    )
    presentacion_error = models.TextField(blank=True)
    presentacion_modelo = models.CharField(max_length=60, blank=True)
    presentacion_generada_en = models.DateTimeField(null=True, blank=True)

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
        return self.slug or f'Reporte {self.id} · {self.jornada.slug} · {self.alcance} · {self.estado}'

    def save(self, *args, **kwargs):
        if not self.slug:
            # settings.TIME_ZONE = 'America/Bogota', así que timezone.localtime() ya da la hora
            # de Colombia aunque el timestamp se guarde en UTC internamente.
            ahora_bogota = timezone.localtime(timezone.now())
            base_slug = f'{self.jornada.slug}-{self.alcance}-{ahora_bogota:%Y%m%d-%H%M}'
            slug = base_slug
            contador = 1
            while Reporte.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                contador += 1
                slug = f'{base_slug}-{contador}'
            self.slug = slug
        super().save(*args, **kwargs)


class AnalisisMomentoIA(models.Model):
    """Vía de análisis alternativa a `Reporte`: en vez del pipeline local multiagente (una llamada
    de LLM local por pregunta, BERTopic para descubrir temas), UNA sola llamada a OpenAI analiza
    TODO el momento de una vez — se le da el enunciado y las respuestas crudas de cada pregunta
    (conteos reales para unica/multiple, todas las respuestas de texto para abierta) y el propio
    GPT identifica temas, clasifica y redacta, devolviendo el mismo formato de JSON que ya produce
    el pipeline local (`MomentoAnalisis` — ver `docs/REPORTE_ANALITICA_SCHEMA.html`) para que el
    frontend pueda renderizar cualquiera de los dos con el mismo componente. No depende de un
    `Reporte` — se dispara directo desde un `Momento`, con su propio historial."""
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

    momento = models.ForeignKey(Momento, on_delete=models.CASCADE, related_name='analisis_ia')
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    resultado = models.JSONField(
        default=dict, blank=True,
        help_text='Mismo formato que un item de analisis.momentos[] en Reporte: momento_id, tipo, '
        'descripcion_general, preguntas[] (con valores_caracteristicos y metodo_valores).',
    )
    error_mensaje = models.TextField(blank=True)
    modelo_usado = models.CharField(max_length=60, blank=True)
    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='analisis_momento_ia_solicitados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    completado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Análisis de momento con IA (OpenAI)'
        verbose_name_plural = 'Análisis de momento con IA (OpenAI)'

    def __str__(self):
        return f'Análisis IA {self.id} · {self.momento} · {self.estado}'
