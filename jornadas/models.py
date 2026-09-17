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


class RolJornada(models.Model):
    """Catálogo de roles institucionales válidos para una jornada (ej. "estudiante",
    "directivo") — igual que la mesa (un entero simple, sin modelo propio) no le da a esto un
    catálogo obligatorio: Participante.rol sigue siendo texto libre (ver ese modelo), esto es
    solo la lista que un admin puede definir para (a) restringir momentos/preguntas por rol
    (Momento.roles_permitidos/Pregunta.roles_permitidos, mismo patrón que mesas_permitidas) y
    (b) que el front tenga qué mostrar en un dropdown al registrar un participante — una jornada
    sin roles definidos aquí no se ve afectada en nada, sigue aceptando cualquier texto libre."""
    jornada = models.ForeignKey(Jornada, on_delete=models.CASCADE, related_name='roles_definidos')
    nombre = models.CharField(max_length=100)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']
        unique_together = [('jornada', 'nombre')]

    def __str__(self):
        return f'{self.nombre} ({self.jornada.slug})'


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
    # Mismo patrón que Pregunta.mesas_permitidas, pero a nivel de momento completo — para
    # dinámicas tipo "Café del Mundo" donde cada mesa física trabaja un momento/tema distinto
    # (no las mismas preguntas repartidas por mesa dentro de un único momento compartido). Solo
    # aplica cuando tipo=mesa. Vacía = visible para todas las mesas, igual que siempre. Una mesa
    # puede aparecer en más de un momento si un mismo tema se reparte entre varias mesas físicas.
    mesas_permitidas = models.JSONField(default=list, blank=True, help_text=(
        'Lista opcional de números de mesa que pueden ver/participar en este momento completo '
        '(solo aplica en momentos tipo mesa). Vacía = visible para todas las mesas.'
    ))
    # Mismo patrón que mesas_permitidas, pero por rol institucional (RolJornada.nombre — o
    # cualquier texto, ya que Participante.rol es libre) en vez de por mesa física. Se combina
    # con mesas_permitidas por AND: si un momento restringe ambos, hay que cumplir los dos. No
    # depende de que la jornada tenga RolJornada definidos — compara directo contra
    # Participante.rol como texto.
    roles_permitidos = models.JSONField(default=list, blank=True, help_text=(
        'Lista opcional de nombres de rol que pueden ver/participar en este momento. Vacía = '
        'visible para todos los roles.'
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
    TIPO_MATRIZ = 'matriz'
    TIPO_CHOICES = [
        (TIPO_ABIERTA, 'Abierta'),
        (TIPO_UNICA, 'Selección única'),
        (TIPO_MULTIPLE, 'Selección múltiple'),
        (TIPO_MATRIZ, 'Matriz comparativa (filas × columnas)'),
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
    roles_permitidos = models.JSONField(default=list, blank=True, help_text=(
        'Lista opcional de nombres de rol que pueden ver/responder esta pregunta. Vacía = '
        'visible para todos los roles, igual que hoy.'
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


class FilaMatrizPregunta(models.Model):
    """Solo se usa cuando Pregunta.tipo == matriz — mismo diseño que
    instrumentos.FilaMatrizInstrumento, portado acá para que una jornada también pueda tener
    preguntas tipo matriz (fila × columna) en vez de aplanar cada celda en una pregunta suelta."""
    pregunta = models.ForeignKey(Pregunta, on_delete=models.CASCADE, related_name='filas')
    texto = models.CharField(max_length=255)
    orden = models.PositiveIntegerField()

    class Meta:
        ordering = ['orden']
        unique_together = [('pregunta', 'orden')]

    def __str__(self):
        return self.texto


class ColumnaMatrizPregunta(models.Model):
    pregunta = models.ForeignKey(Pregunta, on_delete=models.CASCADE, related_name='columnas')
    texto = models.CharField(max_length=255)
    orden = models.PositiveIntegerField()

    class Meta:
        ordering = ['orden']
        unique_together = [('pregunta', 'orden')]

    def __str__(self):
        return self.texto
