from django.conf import settings
from django.db import models
from django.utils.text import slugify

from jornadas import emparejamiento


class Instrumento(models.Model):
    slug = models.SlugField(unique=True, blank=True)
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    # Opcional: vincula este instrumento a una jornada (ej. el diagnóstico de un departamento se
    # aplica como parte de una jornada concreta, junto a sus momentos). Cuando está vinculado,
    # `encargados` deja de usarse para scoping — pasa a ser Jornada.propietarios, un solo lugar
    # para gestionar quién administra todo el paquete (ver propietarios_efectivos() más abajo e
    # instrumentos/scoping.py). null=True/SET_NULL: un instrumento puede seguir existiendo suelto
    # (sin jornada), como los que ya había antes de este campo.
    jornada = models.ForeignKey(
        'jornadas.Jornada',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='instrumentos',
    )
    # Igual que Jornada.propietarios: varios encargados pueden compartir un mismo instrumento.
    # Vacío = visible solo para administradores completos (ver instrumentos.scoping). Sin efecto
    # si `jornada` está definida — ver propietarios_efectivos().
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

    def propietarios_efectivos(self):
        """Quién administra este instrumento: Jornada.propietarios si está vinculado a una, si
        no sus propios `encargados`. Devuelve un manager M2M (mismo tipo en ambos casos), así que
        el llamador puede encadenar `.filter(...)`/`.all()` sin distinguir el caso."""
        return self.jornada.propietarios if self.jornada_id else self.encargados

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
    # True cuando estas respuestas vinieron de ExtraccionInstrumento (IA leyendo un PDF/Word ya
    # diligenciado) en vez de que la persona las haya tecleado en la web — el frontend lo usa para
    # avisar "esto lo llenó la IA, revisa antes de aceptar". No cambia el flujo de revisión: sigue
    # siendo pendiente/aceptado/rechazado igual que cualquier otra aplicación.
    generado_por_ia = models.BooleanField(default=False)
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


class ExtraccionInstrumento(models.Model):
    """Carga un instrumento ya diligenciado en papel/PDF/Word: una sola llamada a OpenAI lee el
    documento (texto si es seleccionable —.docx o PDF con texto—, o las páginas como imagen si es
    un PDF escaneado/a mano) y transcribe las respuestas al MISMO formato que ya usa el envío
    normal (RespuestaInstrumentoEnvioSerializer, ver instrumentos/extraccion_ia_openai.py) — no
    inventa una estructura nueva, solo llena "el mismo formulario" que llenaría la persona en la
    web. El resultado SIEMPRE cae en revisión humana (AplicacionInstrumento.estado='pendiente',
    generado_por_ia=True): la extracción puede equivocarse (letra ilegible, celda ambigua), así
    que nunca se acepta sola."""
    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_PROCESANDO = 'procesando'
    ESTADO_COMPLETO = 'completo'
    ESTADO_SIN_RESPONSABLE = 'sin_responsable'
    ESTADO_ERROR = 'error'
    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, 'Pendiente'),
        (ESTADO_PROCESANDO, 'Procesando'),
        (ESTADO_COMPLETO, 'Completo'),
        (ESTADO_SIN_RESPONSABLE, 'Transcrito — falta asignar responsable'),
        (ESTADO_ERROR, 'Error'),
    ]

    instrumento = models.ForeignKey(Instrumento, on_delete=models.CASCADE, related_name='extracciones')
    # A quién (persona/departamento) pertenece el documento ya diligenciado. Si todavía no tiene
    # PreregistroInstrumento para este instrumento, se le crea uno al procesar — mismo espíritu
    # que un preregistro manual, solo que disparado por esta carga en vez de un alta explícita.
    # Opcional desde HU-55: si no se indica al subir, la IA lee el responsable del propio documento
    # y se intenta emparejar (ver responsable_estado). Si no se logra, la extracción queda en
    # ESTADO_SIN_RESPONSABLE con la transcripción ya guardada en `resultado_crudo`, a la espera de
    # que un admin asigne a la persona — nunca se crea una cuenta a partir de un nombre leído.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
        related_name='extracciones_instrumento',
    )
    # Lo que la IA LEYÓ como responsable en el documento: {"nombre", "correo", "cargo",
    # "dependencia"}, todo opcional. Se guarda aunque el emparejamiento falle — es lo que le
    # permite a un admin entender por qué no se emparejó y a quién debería asignarlo.
    responsable_detectado = models.JSONField(default=dict, blank=True)
    responsable_estado = models.CharField(
        max_length=20, choices=emparejamiento.ESTADO_CHOICES,
        default=emparejamiento.ESTADO_NO_BUSCADO,
    )
    # La transcripción cruda de la IA, tal como volvió. Existe para que el trabajo no se pierda
    # cuando no hay responsable al que atribuirle la AplicacionInstrumento: se guarda acá y se
    # escribe después, cuando un admin asigne a la persona (ver asignar_responsable_instrumento).
    resultado_crudo = models.JSONField(default=dict, blank=True)
    archivo = models.FileField(upload_to='instrumentos/extracciones/%Y/%m/')
    nombre_archivo_original = models.CharField(max_length=255, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    aplicacion = models.ForeignKey(
        AplicacionInstrumento, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='extraccion_origen',
    )
    # ids de PreguntaInstrumento que la IA intentó llenar pero no pasaron validación (celda mal
    # formada, opción que no pertenece a la pregunta, etc.) — quedan sin respuesta, a completar a
    # mano en la revisión. No es lo mismo que "obligatoria sin responder": esto es "se intentó y
    # falló", ver `_omitir_error` en extraccion_ia_openai.py.
    preguntas_omitidas = models.JSONField(default=list, blank=True)
    error_mensaje = models.TextField(blank=True)
    modelo_usado = models.CharField(max_length=60, blank=True)
    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='extracciones_solicitadas',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    completado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Extracción de instrumento con IA (documento diligenciado)'
        verbose_name_plural = 'Extracciones de instrumento con IA (documentos diligenciados)'

    def __str__(self):
        return f'Extracción {self.id} · {self.instrumento.slug} · {self.estado}'
