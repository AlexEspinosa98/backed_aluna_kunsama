from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Instrumento(models.Model):
    slug = models.SlugField(unique=True, blank=True)
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    # Igual que Jornada.propietarios: varios encargados pueden compartir un mismo instrumento.
    # Vacío = visible solo para administradores completos (ver instrumentos.scoping).
    encargados = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='instrumentos_a_cargo',
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='instrumentos_creados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.nombre)[:250] or 'instrumento'
            slug = base_slug
            contador = 1
            while Instrumento.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                contador += 1
                slug = f'{base_slug}-{contador}'
            self.slug = slug
        super().save(*args, **kwargs)


class SeccionInstrumento(models.Model):
    TIPO_CONTENIDO = 'contenido'
    TIPO_PREGUNTAS = 'preguntas'
    TIPO_CHOICES = [
        (TIPO_CONTENIDO, 'Contenido (solo lectura)'),
        (TIPO_PREGUNTAS, 'Preguntas (a diligenciar)'),
    ]

    instrumento = models.ForeignKey(Instrumento, on_delete=models.CASCADE, related_name='secciones')
    orden = models.PositiveIntegerField()
    titulo = models.CharField(max_length=255)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_CONTENIDO)
    # Solo se usa cuando tipo=contenido: texto narrativo libre (markdown/texto plano) que se
    # muestra tal cual, incluidas tablas puramente informativas (ej. "Radiografía comunicativa" del
    # documento origen) — no son preguntas, no generan RespuestaInstrumento.
    contenido = models.TextField(blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ['orden']
        unique_together = [('instrumento', 'orden')]

    def __str__(self):
        return f'{self.instrumento.slug} · {self.orden} · {self.titulo}'


class PreguntaInstrumento(models.Model):
    TIPO_ABIERTA = 'abierta'
    TIPO_UNICA = 'unica'
    TIPO_MULTIPLE = 'multiple'
    TIPO_MATRIZ = 'matriz'
    TIPO_CHOICES = [
        (TIPO_ABIERTA, 'Abierta'),
        (TIPO_UNICA, 'Selección única'),
        (TIPO_MULTIPLE, 'Selección múltiple'),
        (TIPO_MATRIZ, 'Matriz comparativa (filas × columnas)'),
    ]

    seccion = models.ForeignKey(SeccionInstrumento, on_delete=models.CASCADE, related_name='preguntas')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    texto = models.CharField(max_length=500)
    orden = models.PositiveIntegerField()
    obligatoria = models.BooleanField(default=True)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ['orden']
        unique_together = [('seccion', 'orden')]

    def __str__(self):
        return self.texto


class OpcionPreguntaInstrumento(models.Model):
    pregunta = models.ForeignKey(PreguntaInstrumento, on_delete=models.CASCADE, related_name='opciones')
    texto = models.CharField(max_length=255)
    orden = models.PositiveIntegerField()

    class Meta:
        ordering = ['orden']
        unique_together = [('pregunta', 'orden')]

    def __str__(self):
        return self.texto


class FilaMatrizInstrumento(models.Model):
    pregunta = models.ForeignKey(PreguntaInstrumento, on_delete=models.CASCADE, related_name='filas')
    texto = models.CharField(max_length=255)
    orden = models.PositiveIntegerField()

    class Meta:
        ordering = ['orden']
        unique_together = [('pregunta', 'orden')]

    def __str__(self):
        return self.texto


class ColumnaMatrizInstrumento(models.Model):
    pregunta = models.ForeignKey(PreguntaInstrumento, on_delete=models.CASCADE, related_name='columnas')
    texto = models.CharField(max_length=255)
    orden = models.PositiveIntegerField()

    class Meta:
        ordering = ['orden']
        unique_together = [('pregunta', 'orden')]

    def __str__(self):
        return self.texto


class PreregistroInstrumento(models.Model):
    """Autorización explícita para responder un instrumento — a diferencia de Participante
    (autorregistro libre en una jornada), acá el encargado da de alta a cada usuario uno por uno.
    El usuario es un User Django normal (is_staff=False) que autentica con el mismo
    obtain_auth_token que ya usa /api/admin/login/ — IsAdminUser ya lo bloquea de /api/admin/**
    por no ser staff, sin necesidad de lógica adicional."""
    instrumento = models.ForeignKey(Instrumento, on_delete=models.CASCADE, related_name='preregistrados')
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='instrumentos_asignados',
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='preregistros_creados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('instrumento', 'usuario')]

    def __str__(self):
        return f'{self.usuario} · {self.instrumento.slug}'


class AplicacionInstrumento(models.Model):
    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_ACEPTADO = 'aceptado'
    ESTADO_RECHAZADO = 'rechazado'
    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, 'Pendiente de revisión'),
        (ESTADO_ACEPTADO, 'Aceptado'),
        (ESTADO_RECHAZADO, 'Rechazado'),
    ]

    preregistro = models.OneToOneField(
        PreregistroInstrumento, on_delete=models.CASCADE, related_name='aplicacion'
    )
    # enviado_en=None significa que el preregistrado todavía no ha enviado nada — no es uno de los
    # 3 estados oficiales (pendiente/aceptado/rechazado) sino la ausencia de ellos; estado solo es
    # significativo cuando enviado_en no es nulo (ver AplicacionInstrumento.estado_visible).
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    enviado_en = models.DateTimeField(null=True, blank=True)
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='aplicaciones_revisadas',
    )
    revisado_en = models.DateTimeField(null=True, blank=True)
    comentario_revision = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    @property
    def estado_visible(self):
        return self.estado if self.enviado_en else 'sin_enviar'

    def __str__(self):
        return f'{self.preregistro} · {self.estado_visible}'


class RespuestaInstrumento(models.Model):
    aplicacion = models.ForeignKey(AplicacionInstrumento, on_delete=models.CASCADE, related_name='respuestas')
    pregunta = models.ForeignKey(PreguntaInstrumento, on_delete=models.CASCADE, related_name='respuestas')
    # fila/columna solo se usan cuando pregunta.tipo == matriz: una RespuestaInstrumento por celda.
    fila = models.ForeignKey(FilaMatrizInstrumento, on_delete=models.CASCADE, null=True, blank=True)
    columna = models.ForeignKey(ColumnaMatrizInstrumento, on_delete=models.CASCADE, null=True, blank=True)
    texto_libre = models.TextField(blank=True)
    opciones = models.ManyToManyField(OpcionPreguntaInstrumento, blank=True, related_name='respuestas')
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('aplicacion', 'pregunta', 'fila', 'columna')]

    def __str__(self):
        return f'{self.pregunta_id} · aplicacion:{self.aplicacion_id}'
