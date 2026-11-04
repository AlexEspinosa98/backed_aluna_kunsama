"""Precarga la jornada "Revisión de los Objetivos Educativos (PEO) del Programa de Ingeniería
Electrónica" (Universidad del Magdalena): 4 mesas abiertas, 4 roles constituyentes (Estudiante,
Docente, Egresado, Empleador) y un instrumento individual de ~8 minutos.

- Los roles se crean como `RolJornada` (el front los muestra en el dropdown de registro). Por eso
  la pregunta "¿con qué grupo constituyente participa?" del formulario en papel NO es una
  pregunta: el rol ya queda en `Participante.rol` al registrarse.
- El contexto (PEO vigentes + criterios de revisión: pertinencia, claridad, proyección) va en el
  `contexto` del momento, que es lo que el participante lee antes de responder.
- 4 mesas (números 1 a 4, se asignan al registrar al participante; el modelo no guarda un tope
  de mesas). Un solo momento.
- Sin restricciones por mesa ni por rol: todos responden las mismas preguntas (jornada abierta).

Idempotente (update_or_create): correrlo de nuevo actualiza en vez de duplicar.

Uso:
    python manage.py seed_abet_electronica
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from jornadas.models import Jornada, Momento, OpcionPregunta, Pregunta, RolJornada

JORNADA = {
    'slug': 'abet_electronica',
    'nombre': 'Revisión de los Objetivos Educativos del Programa de Ingeniería Electrónica',
    'descripcion': (
        'Cuatro mesas de trabajo (mesas 1 a 4) con estudiantes, docentes, egresados y empleadores para revisar los '
        'Objetivos Educativos del Programa (PEO): lo que se espera que los graduados alcancen '
        'entre tres y cinco años después de terminar su carrera.'
    ),
    # Fecha de hoy (jornada de un solo día).
    'fecha_inicio': date(2026, 11, 3),
    'fecha_fin': date(2026, 11, 3),
    'activa': True,
}

RESPONSABLE_EMAIL = 'alexanderespinosaev@unimagdalena.edu.co'

ROLES = ['Estudiante', 'Docente', 'Egresado', 'Empleador']

CONTEXTO = (
    'Revisión de los Objetivos Educativos del Programa de Ingeniería Electrónica. '
    'Este formulario recoge su percepción sobre los logros que deberían caracterizar a los '
    'graduados de Ingeniería Electrónica entre tres y cinco años después de su graduación. '
    'Responda individualmente antes de iniciar la conversación de la mesa. No existen '
    'respuestas correctas o incorrectas. Tiempo estimado: 8 minutos.\n\n'
    'Un Objetivo Educativo del Programa describe lo que se espera que los graduados alcancen '
    'algunos años después de terminar su carrera.\n\n'
    'Objetivos Educativos vigentes (punto de partida):\n'
    'PEO 1. Desempeñar la profesión en las áreas de la Ingeniería Electrónica con '
    'responsabilidad ética, fundamento científico y tecnológico, espíritu innovador y '
    'competitividad.\n'
    'PEO 2. Generar ambientes de aprendizaje autónomo y continuo para el desarrollo de la '
    'disciplina y la vida.\n'
    '(Fuente: Proyecto Educativo del Programa de Ingeniería Electrónica 2025-1)\n\n'
    'Qué vamos a revisar:\n'
    '1. Pertinencia: ¿los PEO responden a las necesidades actuales y futuras de nuestros '
    'constituyentes?\n'
    '2. Claridad: ¿expresan logros profesionales comprensibles para estudiantes, docentes, '
    'egresados y empleadores?\n'
    '3. Proyección: ¿representan lo que debería caracterizar al egresado de Ingeniería '
    'Electrónica?\n'
    '(Fuente conceptual: ABET Criteria for Accrediting Engineering Programs 2026–2027, '
    'Criterion 2)'
)

MOMENTOS = [
    {
        'orden': 1,
        'titulo': 'Revisión individual de los Objetivos Educativos',
        'tipo': Momento.TIPO_INDIVIDUAL,
        'contexto': CONTEXTO,
        'preguntas': [
            {
                'texto': 'De los siguientes elementos asociados con el primer Objetivo '
                         'Educativo, seleccione los cuatro que considera indispensables para '
                         'caracterizar la trayectoria del egresado de Ingeniería Electrónica.',
                'tipo': Pregunta.TIPO_MULTIPLE,
                'opciones': [
                    'Ejercicio profesional en áreas de la Ingeniería Electrónica',
                    'Responsabilidad ética',
                    'Fundamento científico',
                    'Fundamento tecnológico',
                    'Innovación',
                    'Competitividad profesional',
                ],
            },
            {
                'texto': '¿Cuáles de los siguientes aspectos deberían tener mayor presencia en '
                         'los Objetivos Educativos del Programa? Seleccione máximo tres.',
                'tipo': Pregunta.TIPO_MULTIPLE,
                'opciones': [
                    'Contribución a las necesidades tecnológicas de la región y del país',
                    'Liderazgo y trabajo interdisciplinario',
                    'Responsabilidad social, ambiental y sostenibilidad',
                    'Adaptación a tecnologías emergentes',
                    'Gestión y liderazgo de proyectos de ingeniería',
                    'Emprendimiento de base tecnológica',
                    'Investigación o formación avanzada',
                    'Proyección internacional y competitividad global',
                    'Otro',
                ],
            },
            {
                'texto': 'El segundo Objetivo Educativo propone el aprendizaje autónomo y '
                         'continuo. ¿Cómo debería reflejarse este propósito en la trayectoria '
                         'profesional y personal del egresado de Ingeniería Electrónica?',
            },
            {
                'texto': 'Después de revisar los dos Objetivos Educativos, ¿qué logro '
                         'importante debería alcanzar un egresado de Ingeniería Electrónica '
                         'entre tres y cinco años después de graduarse que todavía no esté '
                         'suficientemente representado?',
            },
            {
                'texto': 'Comentario adicional dictado: grabe con su voz cualquier idea, '
                         'preocupación o propuesta sobre los Objetivos Educativos que no '
                         'haya quedado recogida en las respuestas anteriores.',
                'tipo': Pregunta.TIPO_AUDIO,
                'obligatoria': False,
            },
        ],
    },
]


class Command(BaseCommand):
    help = 'Precarga la jornada de revisión de los PEO de Ingeniería Electrónica.'

    @transaction.atomic
    def handle(self, *args, **options):
        jornada, creada = Jornada.objects.update_or_create(
            slug=JORNADA['slug'], defaults={k: v for k, v in JORNADA.items() if k != 'slug'}
        )
        self.stdout.write(('Creada' if creada else 'Actualizada') + f' jornada "{jornada.nombre}"')

        # Responsable (dueño) de la jornada: debe existir ya como usuario del panel admin
        # (el seed no crea cuentas ni contraseñas). Se busca por email o por username.
        Usuario = get_user_model()
        responsable = (
            Usuario.objects.filter(email__iexact=RESPONSABLE_EMAIL).first()
            or Usuario.objects.filter(username__iexact=RESPONSABLE_EMAIL).first()
        )
        if responsable:
            jornada.propietarios.add(responsable)
            self.stdout.write(f'  Responsable: {responsable.username} ({RESPONSABLE_EMAIL})')
        else:
            self.stdout.write(self.style.WARNING(
                f'  No existe usuario con email/username {RESPONSABLE_EMAIL}: créalo en '
                '/api/admin/usuarios/ (rol dependencia) y vuelve a correr el seed para asignarlo.'
            ))

        for nombre in ROLES:
            RolJornada.objects.get_or_create(jornada=jornada, nombre=nombre)
        self.stdout.write(f'  Roles: {", ".join(ROLES)}')

        for momento_data in MOMENTOS:
            momento, m_creado = Momento.objects.update_or_create(
                jornada=jornada, orden=momento_data['orden'],
                defaults={
                    'titulo': momento_data['titulo'],
                    'contexto': momento_data['contexto'],
                    'tipo': momento_data['tipo'],
                    'activo': True,
                },
            )
            self.stdout.write(
                f'  {"Creado" if m_creado else "Actualizado"} momento {momento.orden}: {momento.titulo}'
            )

            for i, pregunta_data in enumerate(momento_data['preguntas'], start=1):
                pregunta, _ = Pregunta.objects.update_or_create(
                    momento=momento, orden=i,
                    defaults={
                        'texto': pregunta_data['texto'],
                        'tipo': pregunta_data.get('tipo', Pregunta.TIPO_ABIERTA),
                        'obligatoria': pregunta_data.get('obligatoria', True),
                        'activa': True,
                    },
                )
                for j, opcion_texto in enumerate(pregunta_data.get('opciones', []), start=1):
                    OpcionPregunta.objects.update_or_create(
                        pregunta=pregunta, orden=j, defaults={'texto': opcion_texto},
                    )

        self.stdout.write(self.style.SUCCESS(
            f'Listo: {len(MOMENTOS)} momento(s), '
            f'{sum(len(m["preguntas"]) for m in MOMENTOS)} preguntas.'
        ))
