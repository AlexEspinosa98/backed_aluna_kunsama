from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Jornada(models.Model):
    slug = models.SlugField(unique=True)
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    activa = models.BooleanField(default=True)
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='jornadas_creadas',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha_inicio']

    def __str__(self):
        return self.nombre


class Momento(models.Model):
    TIPO_INDIVIDUAL = 'individual'
    TIPO_MESA = 'mesa'
    TIPO_CHOICES = [
        (TIPO_INDIVIDUAL, 'Respuesta individual'),
        (TIPO_MESA, 'Respuesta por mesa'),
    ]

    jornada = models.ForeignKey(Jornada, on_delete=models.CASCADE, related_name='momentos')
    orden = models.PositiveIntegerField()
    titulo = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, blank=True)
    contexto = models.TextField(blank=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_INDIVIDUAL)
    categorias_semilla = models.JSONField(default=list, blank=True, help_text=(
        'Lista opcional de categorías temáticas predefinidas para este momento (ej. '
        '["principios", "riesgos y dilemas", ...]). Si está vacía, los temas se descubren '
        'automáticamente con BERTopic, igual que hoy.'
    ))
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['orden']
        unique_together = [('jornada', 'orden'), ('jornada', 'slug')]

    def __str__(self):
        return f'{self.jornada.slug} · {self.orden} · {self.titulo}'

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.titulo)[:250] or 'momento'
            slug = base_slug
            contador = 1
            while Momento.objects.filter(jornada=self.jornada, slug=slug).exclude(pk=self.pk).exists():
                contador += 1
                slug = f'{base_slug}-{contador}'
            self.slug = slug
        super().save(*args, **kwargs)


class Pregunta(models.Model):
    TIPO_ABIERTA = 'abierta'
    TIPO_UNICA = 'unica'
    TIPO_MULTIPLE = 'multiple'
    TIPO_CHOICES = [
        (TIPO_ABIERTA, 'Abierta'),
        (TIPO_UNICA, 'Selección única'),
        (TIPO_MULTIPLE, 'Selección múltiple'),
    ]

    momento = models.ForeignKey(Momento, on_delete=models.CASCADE, related_name='preguntas')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    texto = models.CharField(max_length=500)
    orden = models.PositiveIntegerField()
    obligatoria = models.BooleanField(default=True)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ['orden']
        unique_together = [('momento', 'orden')]

    def __str__(self):
        return self.texto


class OpcionPregunta(models.Model):
    pregunta = models.ForeignKey(Pregunta, on_delete=models.CASCADE, related_name='opciones')
    texto = models.CharField(max_length=255)
    orden = models.PositiveIntegerField()

    class Meta:
        ordering = ['orden']
        unique_together = [('pregunta', 'orden')]

    def __str__(self):
        return self.texto
