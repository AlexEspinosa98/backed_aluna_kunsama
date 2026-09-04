from django.conf import settings
from django.db import models
from django.utils.text import slugify


class PerfilUsuario(models.Model):
    """Rol de un usuario admin/staff dentro de la app — no confundir con is_staff/is_superuser
    de Django, que solo controlan si puede autenticarse contra /api/admin/**. Un usuario SIN fila
    aquí (todo lo que existe hoy: superusers creados con createsuperuser) se trata como admin
    completo — así el rollout de roles no requiere migrar datos ni puede dejar a nadie bloqueado
    por accidente (ver jornadas.scoping.es_dependencia)."""
    ROL_ADMIN = 'admin'
    ROL_DEPENDENCIA = 'dependencia'
    ROL_CHOICES = [
        (ROL_ADMIN, 'Administrador'),
        (ROL_DEPENDENCIA, 'Dependencia'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil')
    rol = models.CharField(max_length=20, choices=ROL_CHOICES, default=ROL_DEPENDENCIA)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user} · {self.get_rol_display()}'


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
    # Dueños de la jornada para el rol "dependencia" (ver PerfilUsuario) — distinto de creada_por,
    # que es solo auditoría de quién la creó. Vacío = visible solo para administradores completos
    # (una jornada sin dependencia asignada). Varios usuarios "dependencia" pueden compartir una
    # misma jornada (ej. dos personas de la misma área viendo/editando la misma jornada). Un admin
    # completo puede reasignar esta lista en cualquier momento; un usuario de dependencia nunca
    # puede tocarla (se fuerza a sí mismo al crear, ver jornadas.views.JornadaAdminViewSet).
    propietarios = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='jornadas_propias',
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
    mesas_permitidas = models.JSONField(default=list, blank=True, help_text=(
        'Lista opcional de números de mesa que pueden ver/responder esta pregunta (solo aplica '
        'en momentos tipo mesa). Vacía = visible para todas las mesas, igual que hoy.'
    ))

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
