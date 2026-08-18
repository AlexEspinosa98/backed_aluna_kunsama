from django.conf import settings
from django.db import models


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
    contexto = models.TextField(blank=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_INDIVIDUAL)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['orden']
        unique_together = [('jornada', 'orden')]

    def __str__(self):
        return f'{self.jornada.slug} · {self.orden} · {self.titulo}'


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
