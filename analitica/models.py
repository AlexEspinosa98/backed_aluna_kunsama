from django.conf import settings
from django.db import models
from django.utils import timezone

from jornadas.models import Jornada, Momento

from .prompt_comun import ENFOQUE_CHOICES, ENFOQUE_DEFAULT
from .v2.contrato import (
    MODO_CHOICES, MODO_INTEGRAL, MODO_POR_MOMENTO, PIPELINE_BERTOPIC_LLM, PIPELINE_CHOICES,
    PIPELINE_LLM,
)


# Campos del análisis guiado (HU-57 del frontend, ver docs/HU_BACKEND_ANALISIS_GUIADO.md) —
# compartidos por `Reporte`, `AnalisisMomentoIA` y `AnalisisJornadaIA` porque el asistente del
# panel es uno solo para los tres métodos y le pide lo mismo a cualquiera que elija: con qué
# enfoque leer los datos, y contexto/instrucciones libres. Dos mixins abstractos (no una función
# que devuelva campos — Django no permite `**dict` de `Field` en el cuerpo de una clase) para que
# los tres modelos no se desalineen entre sí (help_text, choices, max_length) a medida que el
# asistente evolucione.
class AnalisisGuiadoMixin(models.Model):
    enfoque = models.CharField(
        max_length=15, choices=ENFOQUE_CHOICES, default=ENFOQUE_DEFAULT, help_text=(
            'Con qué enfoque leer los datos: cualitativo (voces y matices), cuantitativo '
            '(cifras y comparaciones) o mixto (ambos por igual, default).'
        ),
    )
    contexto = models.TextField(
        blank=True, help_text=(
            'Contexto general que escribió quien pidió el análisis — puede coincidir con '
            'Jornada.descripcion o no. Se guarda tal cual, sin normalizar.'
        ),
    )
    instrucciones = models.TextField(
        blank=True, help_text=(
            'Instrucciones adicionales de quien pidió el análisis (tono, público, cantidad de '
            'gráficos, idioma…) — mandan sobre el estilo y la estructura por defecto.'
        ),
    )
    adjuntos = models.JSONField(default=list, blank=True, help_text=(
        'Documentos/imágenes de la jornada (JornadaAsset) sumados al análisis (HU-101): lista de '
        '{"asset": <id>, "uso": "fuente"|"contexto"}. Ver analitica/v2/adjuntos.py.'
    ))

    class Meta:
        abstract = True


class AnalisisGuiadoPorMomentoMixin(models.Model):
    """Solo tiene sentido cuando el alcance es UN momento — un `Reporte` de la jornada completa
    o de varios momentos combinados los deja vacíos (nada que lo impida a nivel de modelo; es el
    serializer quien decide cuándo pedirlos, ver `ReporteCrearSerializer`)."""
    contexto_momento = models.TextField(
        blank=True, help_text=(
            'Contexto propio de ESTE momento, además del contexto general de la jornada. Solo '
            'aplica cuando el alcance es un único momento.'
        ),
    )
    instrucciones_momento = models.TextField(
        blank=True, help_text=(
            'Instrucciones propias de ESTE momento, además de las generales. Solo aplica '
            'cuando el alcance es un único momento.'
        ),
    )

    class Meta:
        abstract = True


class ResultadoV2Mixin(models.Model):
    """Auditoría del contrato `kunsamu.analisis/v2` (docs/mejora_promps/) en los tres análisis
    existentes, que desde el rediseño producen ese contrato en `resultado`/`analisis` (ver
    `analitica/v2/procesar.py::ejecutar_analisis_v2`). `entrada` es el sobre normalizado EXACTO
    que se le mandó al modelo, guardado antes de llamar y nunca recalculado: los JSON Pointers de
    citas y documentos BERTopic del resultado apuntan a índices de sus arrays. `diagnostico`
    conserva lo descartado (salidas inválidas, errores, metadatos de las llamadas, notas del
    adaptador BERTopic). Un registro anterior al rediseño tiene los cuatro campos vacíos."""
    entrada = models.JSONField(default=dict, blank=True)
    diagnostico = models.JSONField(default=dict, blank=True)
    version_prompt = models.CharField(max_length=40, blank=True)
    version_esquema = models.CharField(max_length=40, blank=True)

    class Meta:
        abstract = True


class SystemPromptInmutable(Exception):
    """Se intentó modificar o borrar una versión de system prompt que ya estuvo activa."""


class SystemPrompt(models.Model):
    """Los system prompts de los flujos de IA de la analítica, versionados (HU-92).

    Antes vivían en el código (dos `.md` del contrato v2 y constantes en cada módulo), así que
    cambiar uno era un despliegue y no quedaba rastro de con cuál se generó cada análisis. Ahora
    cada flujo pide `SystemPrompt.activo(tipo)` y usa el contenido de la versión activa de su tipo.

    Reglas:
    - **Una versión activa por tipo** (constraint parcial en la base). Activar una desactiva la
      anterior del mismo tipo, nunca las de otro.
    - **Inmutable desde que se activa por primera vez** (`activado_en`): ni su contenido ni sus
      datos se pueden cambiar, ni se puede borrar — un análisis viejo dice "lo generó la versión 3"
      y eso tiene que seguir significando lo mismo. Para cambiar un prompt se crea una versión
      nueva. Un borrador que nunca se activó sí se puede editar y borrar.
    - Desactivar no existe como acción: se activa otra versión (incluida una anterior, para volver
      atrás). Un tipo nunca se queda sin prompt.

    `referencia` (ej. `analisis_llm#3`) es lo que se guarda en `version_prompt` de cada corrida."""
    TIPO_ANALISIS_LLM = 'analisis_llm'
    TIPO_ANALISIS_BERTOPIC = 'analisis_bertopic'
    TIPO_INFOGRAFIA = 'infografia'
    TIPO_PRESENTACION = 'presentacion'
    TIPO_PRESENTACION_DISENO = 'presentacion_diseno'
    TIPO_SUGERENCIAS = 'sugerencias'
    TIPO_RESUMEN_PRESENTACION = 'resumen_presentacion'
    TIPO_AJUSTE_ANALISIS = 'ajuste_analisis'
    TIPO_CHOICES = [
        (TIPO_ANALISIS_LLM, 'Análisis — pipeline LLM'),
        (TIPO_ANALISIS_BERTOPIC, 'Análisis — pipeline BERTopic + LLM'),
        (TIPO_INFOGRAFIA, 'Infografía (prompt base de las láminas)'),
        (TIPO_PRESENTACION, 'Presentación HTML de un reporte'),
        (TIPO_PRESENTACION_DISENO, 'Diseño de presentación (diagramación)'),
        (TIPO_SUGERENCIAS, 'Sugerencias para el análisis guiado'),
        (TIPO_RESUMEN_PRESENTACION, 'Resumen de un análisis para presentar en diapositivas'),
        (TIPO_AJUSTE_ANALISIS, 'Ajuste de un análisis ya entregado (se suma al prompt del análisis)'),
    ]

    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    # Consecutiva por tipo, la asigna el backend al crear (1, 2, 3…).
    version = models.PositiveIntegerField(editable=False)
    etiqueta = models.CharField(
        max_length=60, blank=True,
        help_text='Nombre corto opcional para reconocerla (ej. "v2.2 analista principal").',
    )
    notas = models.TextField(blank=True, help_text='Qué cambia respecto de la anterior y por qué.')
    contenido = models.TextField()
    activo = models.BooleanField(default=False, editable=False)
    activado_en = models.DateTimeField(null=True, blank=True, editable=False)
    activado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='system_prompts_activados', editable=False,
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='system_prompts_creados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tipo', '-version']
        constraints = [
            models.UniqueConstraint(fields=['tipo', 'version'], name='system_prompt_version_unica'),
            models.UniqueConstraint(
                fields=['tipo'], condition=models.Q(activo=True), name='system_prompt_un_activo_por_tipo',
            ),
        ]

    def __str__(self):
        return f'{self.referencia}{" (activo)" if self.activo else ""}'

    @property
    def referencia(self):
        return f'{self.tipo}#{self.version}'

    @property
    def inmutable(self):
        return self.activado_en is not None

    @classmethod
    def activo_de(cls, tipo):
        """La versión activa de `tipo`. Lanza `SystemPrompt.DoesNotExist` con un mensaje claro si
        no hay ninguna — no se cae a un texto del código: si la tabla no tiene el prompt, el flujo
        tiene que fallar a la vista, no generar con algo que nadie eligió."""
        try:
            return cls.objects.get(tipo=tipo, activo=True)
        except cls.DoesNotExist:
            raise cls.DoesNotExist(
                f'No hay un system prompt activo de tipo "{tipo}". Activa una versión en '
                '/api/admin/system-prompts/.'
            )

    def save(self, *args, **kwargs):
        if self.pk is None:
            if self.version is None:
                ultima = SystemPrompt.objects.filter(tipo=self.tipo).aggregate(
                    m=models.Max('version'),
                )['m']
                self.version = (ultima or 0) + 1
        else:
            anterior = SystemPrompt.objects.filter(pk=self.pk).values(
                'tipo', 'contenido', 'etiqueta', 'notas', 'activado_en',
            ).first()
            if anterior and anterior['activado_en'] is not None and any(
                anterior[campo] != getattr(self, campo) for campo in ('tipo', 'contenido', 'etiqueta', 'notas')
            ):
                raise SystemPromptInmutable(
                    f'{self.referencia} ya estuvo activa y no se puede modificar: crea una versión nueva.'
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.inmutable:
            raise SystemPromptInmutable(
                f'{self.referencia} ya estuvo activa y no se puede borrar: puede haber análisis '
                'generados con ella.'
            )
        return super().delete(*args, **kwargs)

    def activar(self, usuario=None):
        """La deja como la activa de su tipo (y a la anterior, no). Atómico y con bloqueo de las
        filas del tipo, para que dos activaciones simultáneas no dejen dos activas ni ninguna."""
        from django.db import transaction

        with transaction.atomic():
            list(SystemPrompt.objects.select_for_update().filter(tipo=self.tipo))
            SystemPrompt.objects.filter(tipo=self.tipo, activo=True).exclude(pk=self.pk).update(activo=False)
            campos = {'activo': True}
            if self.activado_en is None:
                campos.update(activado_en=timezone.now(), activado_por=usuario)
            SystemPrompt.objects.filter(pk=self.pk).update(**campos)
        self.refresh_from_db()
        return self


class PlantillaAnalisis(models.Model):
    # 'local': instrucciones adicionales para el pipeline multiagente local (analysis.py) —
    # aplican a cada pregunta, momento y jornada, ver _instrucciones_plantilla.
    # 'gpt_momento': instrucciones adicionales para el análisis de un momento completo vía OpenAI
    # (analisis_ia_openai.py, AnalisisMomentoIA) — un tipo de plantilla independiente porque son
    # prompts de propósito distinto (uno redacta muchas descripciones cortas, el otro un reporte
    # con hallazgos cruzados); cada tipo tiene su propia plantilla "predeterminada".
    # 'gpt_jornada': mismo mecanismo que 'gpt_momento' pero para analizar TODOS los momentos de
    # una jornada de una sola vez (AnalisisJornadaIA) — prompt propio porque cruza momentos
    # completos entre sí, no solo preguntas dentro de un mismo momento.
    TIPO_LOCAL = 'local'
    TIPO_GPT_MOMENTO = 'gpt_momento'
    TIPO_GPT_JORNADA = 'gpt_jornada'
    TIPO_CHOICES = [
        (TIPO_LOCAL, 'Pipeline local (por pregunta/momento/jornada)'),
        (TIPO_GPT_MOMENTO, 'Análisis de momento completo vía OpenAI'),
        (TIPO_GPT_JORNADA, 'Análisis de jornada completa vía OpenAI'),
    ]

    nombre = models.CharField(max_length=150, unique=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_LOCAL)
    prompt_sistema = models.TextField(
        help_text='Instrucciones de tono, foco y longitud para el LLM. Los datos '
        '(estadísticas y tópicos) se le entregan aparte, ya calculados.'
    )
    predeterminada = models.BooleanField(
        default=False,
        help_text='Solo una plantilla puede ser predeterminada POR TIPO — marcar una nueva '
        'desmarca automáticamente la anterior del mismo tipo, nunca las del otro tipo.',
    )
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
            PlantillaAnalisis.objects.exclude(pk=self.pk).filter(tipo=self.tipo).update(
                predeterminada=False
            )


class Reporte(AnalisisGuiadoMixin, AnalisisGuiadoPorMomentoMixin, ResultadoV2Mixin, models.Model):
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
    # Auditoría del análisis guiado (HU-57): el prompt de sistema con el que se generó la síntesis
    # de jornada (`analysis.py::analizar_jornada`), ya con enfoque/contexto/instrucciones
    # compuestos — mismo campo que ya tienen InfografiaJornada y, desde este mismo cambio, los dos
    # `Analisis*IA`. No es "el" prompt del reporte completo (hay uno por pregunta y por momento,
    # ver analysis.py) sino el representativo de más alto nivel, para mostrar en el detalle "con
    # qué se generó" sin tener que guardar decenas de prompts por reporte.
    prompt_usado = models.TextField(blank=True)

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
    # La versión de system prompt con la que se generó la presentación (HU-92). Aparte de
    # `version_prompt`, que es la del análisis.
    presentacion_version_prompt = models.CharField(max_length=40, blank=True)
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


class AnalisisMomentoIA(AnalisisGuiadoMixin, AnalisisGuiadoPorMomentoMixin, ResultadoV2Mixin, models.Model):
    """Vía de análisis alternativa a `Reporte`: en vez del pipeline multiagente de `analysis.py`
    (una llamada a OpenAI por pregunta, BERTopic para descubrir temas), UNA sola llamada a OpenAI
    lee el instrumento completo del momento (contexto + todas sus preguntas y respuestas reales) y
    redacta un reporte general — hallazgos que pueden cruzar varias preguntas a la vez, no un
    bloque aislado por pregunta como hace el pipeline de `analysis.py`. Ver
    `analitica/analisis_ia_openai.py` para el formato exacto de `resultado`. No depende de un
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
        help_text='momento_id, tipo, resumen_ejecutivo, hallazgos[] (cada uno con titulo, '
        'descripcion, preguntas_relacionadas, tipo_grafica y datos) — ver analisis_ia_openai.py.',
    )
    error_mensaje = models.TextField(blank=True)
    modelo_usado = models.CharField(max_length=60, blank=True)
    # Auditoría del análisis guiado (HU-57) — el system prompt compuesto (plantilla + enfoque +
    # contexto + instrucciones + regla de datos, ver analitica/prompt_comun.py) con el que se
    # generó ESTE análisis.
    prompt_usado = models.TextField(blank=True)
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


class AnalisisJornadaIA(AnalisisGuiadoMixin, ResultadoV2Mixin, models.Model):
    """Mismo mecanismo que `AnalisisMomentoIA` (una sola llamada a OpenAI, sin pasar por
    `Reporte`), pero a escala de jornada completa: lee TODOS los momentos activos de la jornada
    (cada uno con su contexto, preguntas y respuestas reales) en una sola llamada, para encontrar
    hallazgos que cruzan momentos distintos — no solo preguntas dentro de un mismo momento, como
    hace `AnalisisMomentoIA`. Pensado para jornadas tipo "Café del Mundo" con varios momentos
    cortos (uno por mesa/tema) donde el valor real está en ver el panorama completo de una vez,
    no mesa por mesa. Ver `analitica/analisis_ia_openai.py` (`analizar_jornada_ia`,
    `SYSTEM_PROMPT_JORNADA`) para el detalle exacto de payload y formato de `resultado`. Sin
    `AnalisisGuiadoPorMomentoMixin`: el alcance es siempre la jornada entera, nunca un momento."""
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

    jornada = models.ForeignKey(Jornada, on_delete=models.CASCADE, related_name='analisis_ia')
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)

    # Lo que pidió quien lanzó el análisis (HU-98). Vacío = lo de la configuración
    # (OPENAI_MODEL_V2 / OPENAI_REASONING_EFFORT_V2); `flex` = tier Flex de OpenAI, mitad de precio
    # a cambio de más demora, que en segundo plano no importa.
    modelo_solicitado = models.CharField(max_length=80, blank=True)
    esfuerzo_solicitado = models.CharField(max_length=10, blank=True)
    flex = models.BooleanField(default=False)
    # Modo segundo plano de OpenAI (HU-98): la respuesta en curso y en qué fase va. Mientras
    # `respuesta_openai_id` tenga valor, el análisis está esperando a OpenAI, no a un hilo nuestro.
    FASE_INTENTO = 'intento'
    FASE_REPARACION = 'reparacion'
    respuesta_openai_id = models.CharField(max_length=120, blank=True, db_index=True)
    fase_openai = models.CharField(max_length=12, blank=True)
    consultado_en = models.DateTimeField(null=True, blank=True)
    resultado = models.JSONField(
        default=dict, blank=True,
        help_text='jornada_id, resumen_ejecutivo, hallazgos[] (cada uno con titulo, descripcion, '
        'momentos_relacionados, preguntas_relacionadas, transcripciones_relacionadas, '
        'tipo_grafica y datos) — ver '
        'analisis_ia_openai.py.',
    )
    error_mensaje = models.TextField(blank=True)
    modelo_usado = models.CharField(max_length=60, blank=True)
    # Auditoría del análisis guiado (HU-57) — ver el comentario equivalente en AnalisisMomentoIA.
    prompt_usado = models.TextField(blank=True)
    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='analisis_jornada_ia_solicitados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    completado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Análisis de jornada con IA (OpenAI)'
        verbose_name_plural = 'Análisis de jornada con IA (OpenAI)'

    def __str__(self):
        return f'Análisis IA {self.id} · {self.jornada} · {self.estado}'


class InfografiaJornada(models.Model):
    """Una corrida de generación de infografía (3 imágenes) para una `Jornada`, vía el modelo de
    imágenes de OpenAI (ver analitica/infografia_ia_openai.py). Usa como referencia visual directa
    los `JornadaAsset` de la jornada (fotos/logos + el system design más reciente) y como contenido
    la analítica ya calculada.

    Cuelga de la JORNADA, no de un `Reporte`. La analítica puede venir de cualquiera de las vías
    del módulo —el pipeline local (`Reporte`), el reporte integral de jornada (`AnalisisJornadaIA`)
    o el de un momento (`AnalisisMomentoIA`)— y exigir un `Reporte` dejaba sin salida a quien usara
    las otras: tenía que crear y esperar un reporte que no necesitaba solo para desbloquear el
    botón. `reporte`, `analisis_momento` y `analisis_jornada` son NULLABLE a nivel de columna (solo
    uno aplica según el alcance) pero `InfografiaJornadaCrearSerializer` exige EXACTAMENTE uno de
    los tres al crear (HU-73) — nunca "la jornada"/"el momento" solos. Antes de HU-73 los tres eran
    opcionales y, sin ninguno, `_obtener_datos_analitica` caía al análisis MÁS RECIENTE completo de
    ese alcance; desde que una jornada/momento puede acumular varias VERSIONES de análisis a la vez
    (HU-71, distintos métodos y enfoques), esa caída silenciosa significaba que dos versiones
    podían terminar compartiendo la misma infografía, o que una generada mirando la versión A
    mostrara datos de la versión B que se volvió "la más reciente" mientras tanto — exactamente lo
    que una infografía aislada por versión no puede permitir.

    `jornada` sigue siendo obligatoria incluso cuando la infografía es de un momento (se deriva de
    `momento.jornada`): es lo que sostiene el scoping por propietario sin duplicar reglas, y evita
    que consultar "las infografías de esta jornada" tenga que mirar dos campos."""
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

    jornada = models.ForeignKey(Jornada, on_delete=models.CASCADE, related_name='infografias')
    momento = models.ForeignKey(
        Momento, on_delete=models.CASCADE, null=True, blank=True, related_name='infografias',
        help_text='Solo si la infografía es de UN momento. Null = es de la jornada completa.',
    )
    reporte = models.ForeignKey(
        Reporte, on_delete=models.SET_NULL, null=True, blank=True, related_name='infografias',
        help_text='Fija el Reporte (pipeline local) exacto del que salen los datos. Solo aplica '
        'con alcance de jornada (sin `momento`). Sin esto, se usa el más reciente completo.',
    )
    analisis_momento = models.ForeignKey(
        'AnalisisMomentoIA', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='infografias',
        help_text='Fija el AnalisisMomentoIA exacto del que salen los datos. Solo aplica con '
        '`momento`. Sin esto, se usa el más reciente completo de ese momento.',
    )
    analisis_jornada = models.ForeignKey(
        'AnalisisJornadaIA', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='infografias',
        help_text='Fija el AnalisisJornadaIA exacto del que salen los datos. Solo aplica con '
        'alcance de jornada (sin `momento`). Sin esto, se usa el más reciente completo.',
    )
    analisis_v2 = models.ForeignKey(
        'AnalisisV2', on_delete=models.SET_NULL, null=True, blank=True, related_name='infografias',
        help_text='Fija el AnalisisV2 (contrato kunsamu.analisis/v2) exacto del que salen los datos.',
    )
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    instrucciones = models.TextField(blank=True, help_text=(
        'Instrucciones libres que se integran al prompt de esta corrida, con precedencia sobre el '
        'estilo y la estructura por defecto. Sirven para cambiar el tono, la composición o qué '
        'información aparece en las láminas, sin tocar código. Por corrida y no por jornada a '
        'propósito: se prueban distintas y se compara el resultado contra `prompt_usado`.'
    ))
    prompt_usado = models.TextField(blank=True)
    # La versión de system prompt con la que se generó (`SystemPrompt.referencia`, HU-92).
    version_prompt = models.CharField(max_length=40, blank=True)
    error_mensaje = models.TextField(blank=True)
    modelo_usado = models.CharField(max_length=60, blank=True)
    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='infografias_solicitadas',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    completado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Infografía de jornada (IA)'
        verbose_name_plural = 'Infografías de jornada (IA)'

    def __str__(self):
        alcance = self.momento or self.jornada
        return f'Infografía {self.id} · {alcance} · {self.estado}'


class InfografiaImagen(models.Model):
    """Cada una de las 3 imágenes que produce una `InfografiaJornada` completa."""
    infografia = models.ForeignKey(InfografiaJornada, on_delete=models.CASCADE, related_name='imagenes')
    archivo = models.ImageField(upload_to='analitica/infografias/%Y/%m/')
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['orden']

    def __str__(self):
        return f'Imagen {self.orden} · infografía {self.infografia_id}'


class AnalisisV2(models.Model):
    """Análisis con IA bajo el contrato `kunsamu.analisis/v2` (docs/mejora_promps/, plan en
    docs/mejora_promps/plan_implementacion/). Un modelo aparte de `Reporte`/`AnalisisMomentoIA`/
    `AnalisisJornadaIA` a propósito (D1 del plan): el frontend elige renderer por la `version` del
    resultado y conserva los visores históricos, y el contrato rompe la partición por alcance de
    los tres modelos legacy (un `por_momento` con varios momentos produce varios informes en UNA
    solicitud). Sin `enfoque`: el contrato lo elimina — el modelo decide el método por pregunta y
    lo declara en `naturaleza`/`metodos` de cada hallazgo.

    `entrada` es el sobre normalizado EXACTO que se le mandó al modelo, guardado antes de llamar y
    nunca recalculado: los JSON Pointers de citas y documentos BERTopic de `resultado` apuntan a
    índices de sus arrays. `resultado` solo se llena con una salida que pasó las dos capas de
    validación; lo descartado (salidas inválidas, errores, metadatos de las llamadas, notas del
    adaptador BERTopic) queda en `diagnostico` para auditoría.

    **Ajustes (HU-102).** Un análisis con `es_ajuste=True` es la versión corregida de otro ya
    terminado (`ajuste_de_*`, uno solo): se le vuelve a pasar a OpenAI el análisis previo junto con
    su entrada original EXACTA y las instrucciones de ajuste (ver `analitica/ajuste_analisis.py`).
    Corre siempre en el modo segundo plano de OpenAI (`respuesta_openai_id`, `fase_openai`…) porque
    la entrada más el análisis previo pueden pasar del millón de caracteres. `instrucciones` y
    `contexto` son las del ajuste."""
    FASE_INTENTO = 'intento'
    FASE_REPARACION = 'reparacion'
    CAMPOS_AJUSTE = ('ajuste_de_reporte', 'ajuste_de_analisis_momento', 'ajuste_de_analisis_jornada', 'ajuste_de_analisis_v2')
    MODO_INTEGRAL = MODO_INTEGRAL
    MODO_POR_MOMENTO = MODO_POR_MOMENTO
    PIPELINE_LLM = PIPELINE_LLM
    PIPELINE_BERTOPIC_LLM = PIPELINE_BERTOPIC_LLM

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

    jornada = models.ForeignKey(Jornada, on_delete=models.CASCADE, related_name='analisis_v2')
    momentos = models.ManyToManyField(Momento, blank=True, related_name='analisis_v2', help_text=(
        'Vacío en modo integral (el alcance es toda la jornada). En por_momento, los momentos '
        'elegidos — el orden efectivo es por Momento.orden.'
    ))
    modo = models.CharField(max_length=12, choices=MODO_CHOICES)
    pipeline = models.CharField(max_length=15, choices=PIPELINE_CHOICES, default=PIPELINE_LLM)
    contexto = models.TextField(blank=True, help_text=(
        'Contexto general escrito por quien pide el análisis. Viaja como dato en '
        '`personalizacion.contexto_usuario`, nunca dentro del system prompt.'
    ))
    instrucciones = models.TextField(blank=True, help_text=(
        'Instrucciones de quien pide el análisis (`personalizacion.instrucciones_usuario`). '
        'Ajustan énfasis y tono; el formato del informe es fijo por contrato.'
    ))
    personalizacion_momentos = models.JSONField(default=list, blank=True, help_text=(
        'Lista de {"momento": <id>, "contexto": "…", "instrucciones": "…"} — como máximo una '
        'entrada por momento del alcance.'
    ))
    adjuntos = models.JSONField(default=list, blank=True, help_text=(
        'Documentos/imágenes de la jornada (JornadaAsset) sumados al análisis (HU-101): lista de '
        '{"asset": <id>, "uso": "fuente"|"contexto"}. Ver analitica/v2/adjuntos.py.'
    ))
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    error_mensaje = models.TextField(blank=True)
    entrada = models.JSONField(default=dict, blank=True)
    resultado = models.JSONField(default=dict, blank=True, help_text='Salida kunsamu.analisis/v2 validada.')
    diagnostico = models.JSONField(default=dict, blank=True)
    version_prompt = models.CharField(max_length=40, blank=True)
    version_esquema = models.CharField(max_length=40, blank=True)
    prompt_usado = models.TextField(blank=True)
    modelo_usado = models.CharField(max_length=60, blank=True)
    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='analisis_v2_solicitados',
    )
    # HU-102: ajuste de un análisis ya terminado. `es_ajuste` sobrevive aunque se borre el origen
    # (las FK quedan en NULL): el ajuste no depende de él, lleva su propia copia de la entrada.
    es_ajuste = models.BooleanField(default=False)
    ajuste_de_reporte = models.ForeignKey('Reporte', null=True, blank=True, on_delete=models.SET_NULL, related_name='ajustes')
    ajuste_de_analisis_momento = models.ForeignKey('AnalisisMomentoIA', null=True, blank=True, on_delete=models.SET_NULL, related_name='ajustes')
    ajuste_de_analisis_jornada = models.ForeignKey('AnalisisJornadaIA', null=True, blank=True, on_delete=models.SET_NULL, related_name='ajustes')
    ajuste_de_analisis_v2 = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='ajustes')
    # Modo segundo plano de OpenAI (mismo motor que AnalisisJornadaIA, HU-98) — solo los ajustes.
    modelo_solicitado = models.CharField(max_length=80, blank=True)
    esfuerzo_solicitado = models.CharField(max_length=10, blank=True)
    flex = models.BooleanField(default=False)
    respuesta_openai_id = models.CharField(max_length=120, blank=True, db_index=True)
    fase_openai = models.CharField(max_length=12, blank=True)
    consultado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    completado_en = models.DateTimeField(null=True, blank=True)

    @property
    def campo_ajuste(self):
        return next((c for c in self.CAMPOS_AJUSTE if getattr(self, f'{c}_id')), None)

    @property
    def origen_ajuste(self):
        campo = self.campo_ajuste
        return getattr(self, campo) if campo else None

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Análisis v2'
        verbose_name_plural = 'Análisis v2'

    def __str__(self):
        return f'Análisis v2 {self.id} · {self.jornada} · {self.modo} · {self.pipeline} · {self.estado}'


class PresentacionDiseno(models.Model):
    """Diagramación de una presentación (colores, tipografía, papel de cada asset, plantilla de
    cada diapositiva) decidida por un modelo de OpenAI con visión sobre los assets de la jornada
    (docs/HU_BACKEND_DISENO_PRESENTACION.md). Opcional y bajo demanda: nunca se genera sola —
    sólo cuando el usuario pulsa «Diagramar con IA» en el frontend — y el resultado se guarda
    para no volver a gastar tokens cada vez que se abre la presentación.

    Un diseño pertenece a UN análisis concreto, mismo patrón que `InfografiaJornada` (HU-73):
    exactamente uno de `reporte`/`analisis_momento`/`analisis_jornada` no nulo. La regla de
    integridad se valida en la vista antes de crear/actualizar (mismo criterio que
    `InfografiaJornadaCrearSerializer.validate`), no acá — ver `analitica/admin_views.py`.

    Es `OneToOneField` y no `ForeignKey` a propósito: un análisis tiene A LO SUMO un diseño
    guardado a la vez — un `POST` repetido sobre el mismo análisis ACTUALIZA esa fila (el
    «Rediseñar» del usuario), nunca crea una segunda."""
    reporte = models.OneToOneField(
        'Reporte', null=True, blank=True, on_delete=models.CASCADE,
        related_name='presentacion_diseno',
    )
    analisis_momento = models.OneToOneField(
        'AnalisisMomentoIA', null=True, blank=True, on_delete=models.CASCADE,
        related_name='presentacion_diseno',
    )
    analisis_jornada = models.OneToOneField(
        'AnalisisJornadaIA', null=True, blank=True, on_delete=models.CASCADE,
        related_name='presentacion_diseno',
    )
    version = models.CharField(max_length=40, default='kunsamu.presentacion/v1')
    # La versión de system prompt con la que se diseñó (`SystemPrompt.referencia`, HU-92).
    version_prompt = models.CharField(max_length=40, blank=True)
    # Único campo del proyecto que SÍ guarda el nombre real del modelo de OpenAI que respondió
    # (la HU lo pide explícitamente en §2.2) — el resto del código lo trata como secreto de
    # proveedor y nunca lo expone en un campo genérico.
    modelo = models.CharField(max_length=60)
    diapositivas = models.JSONField(
        help_text='La secuencia recibida en el POST, tal cual — el backend nunca la reconstruye '
        'ni la altera, sólo la guarda y se la pasa al modelo.',
    )
    diseno = models.JSONField(
        help_text='Contrato kunsamu.presentacion/v1 ya saneado (ver presentacion_diseno_ia.py).',
    )
    correcciones = models.JSONField(default=list, blank=True)
    assets = models.JSONField(
        default=list, blank=True, help_text='Ids de JornadaAsset enviados al modelo.',
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Diseño de presentación (IA)'
        verbose_name_plural = 'Diseños de presentación (IA)'

    def __str__(self):
        fuente = self.reporte or self.analisis_momento or self.analisis_jornada
        return f'Diseño de presentación {self.id} · {fuente}'


class ResumenPresentacion(models.Model):
    """Un análisis ya terminado, resumido para presentarlo en diapositivas (HU-99).

    Parte de la salida estructurada de un análisis (`kunsamu.analisis/v2`) y produce OTRA salida
    con el mismo contrato, más corta: pocos hallazgos por informe, cada uno pensado como una
    diapositiva. El modelo solo escribe `informes`, `visualizaciones` y `limitaciones`; lo demás
    (`version`, `pipeline`, `estado`, `alcance`, `fuentes`, `cobertura`) se copia del original, y
    el resultado se valida con las mismas reglas que el análisis, contra su entrada original —
    así cada cifra, cita y visualización sigue siendo rastreable a los datos.

    Corre en el modo segundo plano de OpenAI (mismo motor que el análisis integral, HU-98) con el
    `SystemPrompt` activo de tipo `resumen_presentacion`. Se puede pedir varias veces sobre el
    mismo análisis (con distintas instrucciones); cada pedido es una fila."""
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
    FASE_INTENTO = 'intento'
    FASE_REPARACION = 'reparacion'

    # El análisis de origen: exactamente uno de los cuatro.
    reporte = models.ForeignKey('Reporte', null=True, blank=True, on_delete=models.CASCADE, related_name='resumenes_presentacion')
    analisis_momento = models.ForeignKey('AnalisisMomentoIA', null=True, blank=True, on_delete=models.CASCADE, related_name='resumenes_presentacion')
    analisis_jornada = models.ForeignKey('AnalisisJornadaIA', null=True, blank=True, on_delete=models.CASCADE, related_name='resumenes_presentacion')
    analisis_v2 = models.ForeignKey('AnalisisV2', null=True, blank=True, on_delete=models.CASCADE, related_name='resumenes_presentacion')
    jornada = models.ForeignKey(Jornada, on_delete=models.CASCADE, related_name='resumenes_presentacion')

    instrucciones = models.TextField(
        blank=True, help_text='Público, duración, cantidad de diapositivas, énfasis… Sin tope de largo.',
    )
    adjuntos = models.JSONField(default=list, blank=True, help_text=(
        'Ids de JornadaAsset que entran como contexto del resumen (HU-101). Solo contexto: un '
        'resumen no puede sumar fuentes que el análisis original no tenía.'
    ))
    modelo_solicitado = models.CharField(max_length=80, blank=True)
    esfuerzo_solicitado = models.CharField(max_length=10, blank=True)
    flex = models.BooleanField(default=False)

    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    resultado = models.JSONField(default=dict, blank=True, help_text='Salida `kunsamu.analisis/v2` validada.')
    # Lo que se le mandó al modelo (el análisis original más jornada e instrucciones), guardado
    # antes de llamar: el intento y la reparación se arman desde aquí con el mismo texto exacto.
    entrada = models.JSONField(default=dict, blank=True)
    diagnostico = models.JSONField(default=dict, blank=True)
    prompt_usado = models.TextField(blank=True)
    version_prompt = models.CharField(max_length=40, blank=True)
    version_esquema = models.CharField(max_length=40, blank=True)
    modelo_usado = models.CharField(max_length=60, blank=True)
    error_mensaje = models.TextField(blank=True)

    respuesta_openai_id = models.CharField(max_length=120, blank=True, db_index=True)
    fase_openai = models.CharField(max_length=12, blank=True)
    consultado_en = models.DateTimeField(null=True, blank=True)

    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='resumenes_presentacion_solicitados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    completado_en = models.DateTimeField(null=True, blank=True)

    CAMPOS_FUENTE = ('reporte', 'analisis_momento', 'analisis_jornada', 'analisis_v2')

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Resumen para presentación'
        verbose_name_plural = 'Resúmenes para presentación'

    def __str__(self):
        return f'Resumen para presentación {self.id} · {self.campo_fuente} · {self.estado}'

    @property
    def campo_fuente(self):
        return next((c for c in self.CAMPOS_FUENTE if getattr(self, f'{c}_id')), None)

    @property
    def fuente(self):
        campo = self.campo_fuente
        return getattr(self, campo) if campo else None


def resultado_v2_de(analisis):
    """La salida `kunsamu.analisis/v2` de cualquiera de los cuatro análisis (el reporte la guarda en
    `analisis`, los demás en `resultado`)."""
    return analisis.analisis if isinstance(analisis, Reporte) else analisis.resultado

