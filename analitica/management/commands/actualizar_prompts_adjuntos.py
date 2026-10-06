"""Crea las versiones de los system prompts que explican los adjuntos de un análisis (HU-101).

Mismo criterio que `actualizar_prompts_v2_1`: parte de la versión ACTIVA de cada tipo (puede haberla
escrito alguien desde el admin) y crea la siguiente, sumándole una sección al final. No reemplaza
frases, así que no depende de cómo esté redactada la versión activa.

- `analisis_llm` y `analisis_bertopic`: las fuentes `f-adj…` (documento o imagen adjunta como
  evidencia secundaria) y `entrada.referencias` (material de contexto, nunca evidencia).
- `resumen_presentacion`: `entrada.referencias` como contexto del resumen.

La regla también viaja dentro de la entrada (`referencias.nota`, `fuentes[].datos.metodo_resumen`),
así que un análisis con adjuntos funciona aunque este comando no se haya corrido; con él, el
modelo la tiene además en el system prompt, que es donde pesa más.

    python manage.py actualizar_prompts_adjuntos              # crea borradores
    python manage.py actualizar_prompts_adjuntos --activar    # crea y activa
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analitica.models import SystemPrompt

MARCA = 'Adjuntos del análisis (HU-101)'

BLOQUE_ANALISIS = f"""## {MARCA}

- **Fuentes adjuntas.** Una fuente de tipo `resumen_secundario` cuyo id empieza por `f-adj` es un documento o una imagen que adjuntó el equipo organizador. Su contenido completo está en `datos.texto`; `datos.metodo_resumen` dice qué es y cómo se leyó (texto extraído del archivo, o lectura con un modelo de visión, que puede traer errores de lectura). Es evidencia **secundaria**: puede sostener, contrastar o matizar un hallazgo, va en `fuente_ids` y se cita con su `fuente_id` y el localizador `/texto`, con un fragmento contiguo y literal de ese texto.
- **Nunca la mezcles con los participantes.** Los conteos, porcentajes, bases y métricas salen sólo de las fuentes `respuestas` y `agregado` (y `bertopic` si existe). No atribuyas a los participantes lo que dice un adjunto ni lo cuentes como una respuesta más; cuando un hallazgo se apoye en un adjunto, dilo en la redacción («el informe de autoevaluación adjunto señala…»). Un hallazgo que sólo se sostiene en adjuntos, sin respuestas de los participantes, debe decirlo explícitamente.
- **Referencias de contexto.** `entrada.referencias`, si existe, es material de CONTEXTO (normativa, antecedentes, objetivos institucionales, resultados previos). Úsalo para entender el marco, interpretar y contrastar lo que dicen las fuentes y alinear las recomendaciones. **No es evidencia:** no tiene id de fuente, así que no puede ir en `fuente_ids`, ni en citas, métricas o visualizaciones, y nada se cuenta a partir de él. Si lo usas para enmarcar un hallazgo o una recomendación, nómbralo en el texto.
"""

BLOQUE_RESUMEN = f"""## {MARCA}

- `entrada.referencias`, si existe, es material de CONTEXTO que adjuntó quien pide el resumen (el público, la normativa, los antecedentes, los objetivos de la presentación). Úsalo para decidir el énfasis, el orden y el lenguaje del resumen. No agrega hallazgos, cifras, citas ni visualizaciones: todo lo que aparezca en el resumen sigue saliendo del análisis original.
"""

CAMBIOS = {
    'analisis_llm': (BLOQUE_ANALISIS, 'Adjuntos: fuentes secundarias y contexto'),
    'analisis_bertopic': (BLOQUE_ANALISIS, 'Adjuntos: fuentes secundarias y contexto'),
    'resumen_presentacion': (BLOQUE_RESUMEN, 'Adjuntos: contexto del resumen'),
}


class Command(BaseCommand):
    help = 'Crea (y opcionalmente activa) las versiones de los prompts que explican los adjuntos (HU-101).'

    def add_arguments(self, parser):
        parser.add_argument('--activar', action='store_true')
        parser.add_argument('--usuario', default=None, help='username que queda como autor/activador')

    def handle(self, *args, **opciones):
        usuario = None
        if opciones['usuario']:
            usuario = get_user_model().objects.filter(username=opciones['usuario']).first()
            if usuario is None:
                raise CommandError(f"No existe el usuario {opciones['usuario']!r}")
        for tipo, (bloque, etiqueta) in CAMBIOS.items():
            try:
                activo = SystemPrompt.activo_de(tipo)
            except SystemPrompt.DoesNotExist as exc:
                self.stdout.write(self.style.ERROR(f'{tipo}: NO se creó — {exc}'))
                continue
            if MARCA in activo.contenido:
                self.stdout.write(f'{tipo}: {activo.referencia} ya explica los adjuntos, no se crea nada.')
                continue
            contenido = activo.contenido.rstrip() + '\n\n' + bloque
            with transaction.atomic():
                nuevo = SystemPrompt.objects.create(
                    tipo=tipo, contenido=contenido, etiqueta=etiqueta[:60], creado_por=usuario,
                    notas=f'Creada desde {activo.referencia} por `actualizar_prompts_adjuntos` (HU-101): {etiqueta}.',
                )
                if opciones['activar']:
                    nuevo.activar(usuario)
            estado = 'activa' if opciones['activar'] else 'borrador'
            self.stdout.write(self.style.SUCCESS(
                f'{tipo}: {activo.referencia} → {nuevo.referencia} ({estado}, {len(contenido)} caracteres)'
            ))
