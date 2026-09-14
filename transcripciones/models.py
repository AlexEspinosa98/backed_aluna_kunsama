from django.conf import settings
from django.db import models
from django.utils.text import slugify


class SesionTranscripcion(models.Model):
    """Una sesión grabada (reunión, entrevista, taller) transcrita por el front vía gpt-transcribe
    — el backend nunca toca audio ni websockets, solo recibe el texto ya transcrito en fragmentos
    y lo almacena. Recurso independiente de Jornada/Momento/Participante: no es una encuesta con
    preguntas y respuestas por persona, es UNA conversación continua."""
    EN_CURSO = 'en_curso'
    CERRADA = 'cerrada'
    ESTADO_CHOICES = [
        (EN_CURSO, 'En curso'),
        (CERRADA, 'Cerrada'),
    ]

    slug = models.SlugField(unique=True, blank=True)
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=EN_CURSO)
    # Mismo patrón que Instrumento.encargados/Jornada.propietarios: varios encargados pueden
    # compartir una sesión; vacía = visible solo para administradores completos.
    encargados = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='transcripciones_a_cargo',
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transcripciones_creadas',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    cerrada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado_en']

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.nombre)[:250] or 'sesion'
            slug = base_slug
            contador = 1
            while SesionTranscripcion.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                contador += 1
                slug = f'{base_slug}-{contador}'
            self.slug = slug
        super().save(*args, **kwargs)


class FragmentoTranscripcion(models.Model):
    """Un pedazo de texto transcrito, mandado por el front en tiempo real mientras la sesión está
    en curso. `secuencia` la asigna el front (0, 1, 2, ...), no el servidor — así la ingesta es
    update_or_create por (sesion, secuencia): si un POST se reintenta por una caída de red, no se
    duplica, y el orden final no depende de en qué orden llegaron los paquetes por la red."""
    sesion = models.ForeignKey(SesionTranscripcion, on_delete=models.CASCADE, related_name='fragmentos')
    secuencia = models.PositiveIntegerField()
    texto = models.TextField()
    # Opcional: solo si el front hace diarización (identifica quién habla). Vacío = no se sabe.
    hablante = models.CharField(max_length=150, blank=True)
    # Opcional: offset en milisegundos dentro de la grabación, si el front lo tiene disponible.
    inicio_ms = models.PositiveIntegerField(null=True, blank=True)
    fin_ms = models.PositiveIntegerField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['secuencia']
        unique_together = [('sesion', 'secuencia')]

    def __str__(self):
        return f'{self.sesion_id} · #{self.secuencia}'


class InformeTranscripcion(models.Model):
    """Mismo mecanismo que Reporte/AnalisisJornadaIA (analitica): una llamada a OpenAI que lee la
    transcripción completa y redacta un informe — con la diferencia de que acá no hay preguntas ni
    conteos reales que proteger (no es una encuesta), así que no tiene sentido forzar
    `tipo_grafica`/`datos` como en analitica: el resultado son hallazgos en prosa con citas
    textuales, no cifras. Sesiones largas (hasta 4h) se resumen por mapa-reducción (ver
    transcripciones/informe_ia.py) en vez de una sola llamada gigante — cada InformeTranscripcion
    es el resultado final ya sintetizado, con su propio historial por sesión (igual que Reporte)."""
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

    sesion = models.ForeignKey(SesionTranscripcion, on_delete=models.CASCADE, related_name='informes')
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    resultado = models.JSONField(
        default=dict, blank=True,
        help_text='resumen_ejecutivo, hallazgos[] (titulo, descripcion, citas[]), '
        'temas_discutidos[], tramos_analizados — ver transcripciones/informe_ia.py.',
    )
    error_mensaje = models.TextField(blank=True)
    modelo_usado = models.CharField(max_length=60, blank=True)

    # Presentación HTML generada por OpenAI a partir de `resultado` — misma capa aparte que
    # Reporte.presentacion_html: se puede pedir, fallar o regenerar sin volver a analizar.
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
        related_name='informes_transcripcion_solicitados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    completado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado_en']

    def __str__(self):
        return f'Informe {self.id} · {self.sesion} · {self.estado}'
