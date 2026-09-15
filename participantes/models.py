import uuid

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from jornadas.models import Jornada, Momento, OpcionPregunta, Pregunta


class Participante(models.Model):
    # DRF permission classes (IsAdminUser, IsAuthenticated, etc.) leen estos
    # atributos asumiendo un modelo tipo User. Sin ellos, si un token de
    # participante llega a un endpoint de admin, la autenticación igual
    # sucede y la verificación de permiso revienta con AttributeError (500)
    # en vez de negar el acceso limpiamente (403).
    is_staff = False
    is_active = True
    is_authenticated = True

    jornada = models.ForeignKey(Jornada, on_delete=models.CASCADE, related_name='participantes')
    correo_institucional = models.EmailField()
    nombre = models.CharField(max_length=150)
    apellido = models.CharField(max_length=150)
    telefono = models.CharField(max_length=30, blank=True)
    # Rol institucional del participante (ej. "estudiante", "directivo") — texto libre, sin lista
    # fija de valores. Es un dato del participante en sí, distinto de mesa/es_vocero (que son
    # sobre su lugar dentro de la dinámica grupal, no sobre quién es institucionalmente).
    rol = models.CharField(max_length=100)
    # Mesa y vocero se fijan una vez para toda la jornada (no por momento) — se capturan en el
    # registro, pero un admin puede corregirlos después vía PATCH /api/admin/participantes/{id}/
    # (ver ParticipanteAdminViewSet) si una mesa se reorganiza o cambia quién es el vocero. Mesa es
    # numérica (el número de la mesa física, ej. 3) — no texto libre, para que comparar/asignar
    # mesas sea exacto y no dependa de cómo alguien escribió "Mesa 3" / "mesa 3" / "MESA 3".
    mesa = models.PositiveIntegerField(null=True, blank=True)
    es_vocero = models.BooleanField(
        default=False,
        help_text='Solo el vocero de una mesa puede enviar respuestas en momentos tipo mesa.',
    )
    slug = models.SlugField(max_length=200)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [
            ('jornada', 'correo_institucional'),
            ('jornada', 'slug'),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(f'{self.nombre} {self.apellido}')
            slug = base_slug
            contador = 1
            while Participante.objects.filter(jornada=self.jornada, slug=slug).exclude(pk=self.pk).exists():
                contador += 1
                slug = f'{base_slug}-{contador}'
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.nombre} {self.apellido} ({self.jornada.slug})'


class Respuesta(models.Model):
    pregunta = models.ForeignKey(Pregunta, on_delete=models.CASCADE, related_name='respuestas')
    participante = models.ForeignKey(
        Participante,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='respuestas',
    )
    mesa = models.PositiveIntegerField(null=True, blank=True)
    registrado_por = models.ForeignKey(
        Participante,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='respuestas_registradas',
    )
    texto_libre = models.TextField(blank=True)
    opciones = models.ManyToManyField(OpcionPregunta, blank=True, related_name='respuestas')
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [
            ('pregunta', 'participante'),
            ('pregunta', 'mesa'),
        ]

    def __str__(self):
        dueno = self.participante_id and f'participante:{self.participante_id}' or f'mesa:{self.mesa}'
        return f'{self.pregunta_id} · {dueno}'


class ExtraccionMomento(models.Model):
    """Carga un momento ya diligenciado en papel/PDF/Word — mismo mecanismo que
    instrumentos.ExtraccionInstrumento (ver ese modelo), portado acá porque este momento en
    particular vive en el modelo clásico Momento/Pregunta, no en el módulo `instrumentos`. Una
    sola llamada a OpenAI lee el documento y transcribe las respuestas, pero A DIFERENCIA de
    RespuestasMomentoView (que guarda de inmediato), el resultado queda en `resultado` (JSON) SIN
    tocar Respuesta hasta que un admin lo aprueba explícitamente vía el action `aprobar` — acá no
    existe forma de editar una Respuesta ya guardada (RespuestaAdminViewSet es de solo lectura),
    así que la única ventana de revisión real es ANTES de escribirla."""
    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_PROCESANDO = 'procesando'
    ESTADO_COMPLETO = 'completo'
    ESTADO_ERROR = 'error'
    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, 'Pendiente'),
        (ESTADO_PROCESANDO, 'Procesando'),
        (ESTADO_COMPLETO, 'Completo — a la espera de revisión'),
        (ESTADO_ERROR, 'Error'),
    ]

    momento = models.ForeignKey(Momento, on_delete=models.CASCADE, related_name='extracciones')
    # A quién (persona/departamento) pertenece el documento ya diligenciado. Se crea/reutiliza al
    # subir el archivo (no al aprobar) — mismo espíritu que un registro manual de participante.
    participante = models.ForeignKey(Participante, on_delete=models.CASCADE, related_name='extracciones')
    archivo = models.FileField(upload_to='participantes/extracciones/%Y/%m/')
    nombre_archivo_original = models.CharField(max_length=255, blank=True)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    # {"respuestas": [{"pregunta": id, "texto_libre": str, "opcion_ids": [ids]}, ...]} — mismo
    # formato que RespuestaEnvioSerializer, sin escribir todavía en Respuesta (ver aprobar()).
    resultado = models.JSONField(default=dict, blank=True)
    preguntas_omitidas = models.JSONField(default=list, blank=True)
    error_mensaje = models.TextField(blank=True)
    modelo_usado = models.CharField(max_length=60, blank=True)
    aprobado_en = models.DateTimeField(null=True, blank=True)
    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='extracciones_momento_aprobadas',
    )
    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='extracciones_momento_solicitadas',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    completado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Extracción de momento con IA (documento diligenciado)'
        verbose_name_plural = 'Extracciones de momento con IA (documentos diligenciados)'

    def __str__(self):
        return f'Extracción {self.id} · {self.momento_id} · {self.estado}'
