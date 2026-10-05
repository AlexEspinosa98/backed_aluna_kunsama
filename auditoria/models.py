from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class LlamadaOpenAI(models.Model):
    """Una petición HTTP a la API de OpenAI, completa, tal como salió y tal como volvió (HU-95).

    La escribe `auditoria.openai_cliente` desde la capa de transporte del cliente HTTP, así que
    registra lo que de verdad viajó: el cuerpo exacto (todos los mensajes y prompts, las imágenes
    en base64, los parámetros), la respuesta exacta, el estado HTTP y cuánto tardó. Un reintento
    automático del SDK es otra fila; una petición que falla también queda, con su error.

    Las relaciones (`jornada`, `momento`, `origen`, `usuario`) las aporta el flujo que dispara la
    llamada (`contexto_llamada`); `flujo` siempre está.

    Lo único que NO se guarda es la API key: el encabezado `Authorization` se elimina antes."""
    ESTADO_OK = 'ok'
    ESTADO_ERROR_HTTP = 'error_http'
    ESTADO_ERROR_RED = 'error_red'
    ESTADO_CHOICES = [
        (ESTADO_OK, 'OK (2xx)'),
        (ESTADO_ERROR_HTTP, 'Error HTTP (OpenAI respondió con error)'),
        (ESTADO_ERROR_RED, 'Error de red / sin respuesta'),
    ]

    flujo = models.CharField(max_length=60, db_index=True, help_text='Qué parte del sistema hizo la llamada.')
    jornada = models.ForeignKey(
        'jornadas.Jornada', on_delete=models.SET_NULL, null=True, blank=True, related_name='llamadas_openai',
    )
    momento = models.ForeignKey(
        'jornadas.Momento', on_delete=models.SET_NULL, null=True, blank=True, related_name='llamadas_openai',
    )
    # El registro que originó la llamada (un AnalisisJornadaIA, una ExtraccionMomento, una
    # InfografiaJornada…). Genérico porque son de muchos modelos y apps distintas.
    origen_tipo = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    origen_id = models.CharField(max_length=40, blank=True)
    origen = GenericForeignKey('origen_tipo', 'origen_id')
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='llamadas_openai',
    )

    metodo = models.CharField(max_length=10)
    url = models.CharField(max_length=500)
    endpoint = models.CharField(max_length=120, db_index=True, help_text='Ruta de la API, ej. /v1/chat/completions.')
    modelo = models.CharField(max_length=80, blank=True, db_index=True)
    # Cuerpo de la petición: JSON parseado si es JSON (chat, imágenes generadas); si no (multipart
    # de images.edit), el cuerpo crudo en `peticion_cruda`.
    peticion = models.JSONField(null=True, blank=True)
    peticion_cruda = models.BinaryField(null=True, blank=True)
    peticion_content_type = models.CharField(max_length=200, blank=True)
    peticion_headers = models.JSONField(default=dict, blank=True)
    peticion_bytes = models.PositiveBigIntegerField(default=0)

    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, db_index=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    respuesta = models.JSONField(null=True, blank=True)
    respuesta_cruda = models.TextField(blank=True, help_text='Cuerpo de la respuesta cuando no es JSON.')
    respuesta_headers = models.JSONField(default=dict, blank=True)
    respuesta_bytes = models.PositiveBigIntegerField(default=0)
    error = models.TextField(blank=True)

    request_id = models.CharField(max_length=120, blank=True, help_text='x-request-id de OpenAI, para soporte.')
    tokens_entrada = models.PositiveIntegerField(null=True, blank=True)
    tokens_salida = models.PositiveIntegerField(null=True, blank=True)
    tokens_total = models.PositiveIntegerField(null=True, blank=True)

    iniciado_en = models.DateTimeField(db_index=True)
    finalizado_en = models.DateTimeField()
    duracion_ms = models.PositiveIntegerField(help_text='Desde que sale la petición hasta que llega la respuesta completa.')

    class Meta:
        ordering = ['-iniciado_en']
        verbose_name = 'Llamada a OpenAI'
        verbose_name_plural = 'Llamadas a OpenAI'
        indexes = [models.Index(fields=['origen_tipo', 'origen_id'])]

    def __str__(self):
        return f'{self.flujo} · {self.endpoint} · {self.status_code or self.estado} · {self.duracion_ms} ms'
