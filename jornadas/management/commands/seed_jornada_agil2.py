"""Precarga la 'Jornada Ágil 2' (Universidad del Magdalena, 20 de agosto de 2026) a partir de los
documentos institucionales de convocatoria y de dinámicas participativas.

Mapea la secuencia real del día (reflexión individual → consenso de mesa → dinámica participativa,
repetida para los dos temas de la jornada: EIBIC y la Política de Innovación y Emprendimiento) a
seis Momentos, cada uno con sus preguntas. Las preguntas de opción única de las dinámicas
(elección de hilo de color, elección de rumbo) quedan modeladas como preguntas `unica` con sus
opciones.

Idempotente: usa `update_or_create` por slug/orden, así que correrlo de nuevo actualiza el
contenido en vez de duplicarlo.

Uso:
    python manage.py seed_jornada_agil2
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from jornadas.models import Jornada, Momento, OpcionPregunta, Pregunta

JORNADA = {
    'slug': 'jornada-agil-2',
    'nombre': 'Jornada Ágil 2 — Actualización del Sistema de Investigación, Ciencia, '
              'Tecnología, Innovación y Creación',
    'descripcion': (
        'Ética, innovación y emprendimiento para transformar desde el conocimiento. '
        'Hotel Irotama, Santa Marta. Segunda Jornada Ágil para la actualización del Sistema de '
        'Investigación, Ciencia, Tecnología, Innovación y Creación de la Universidad del '
        'Magdalena: consolidación de los lineamientos institucionales en Ética de la '
        'Investigación, Bioética e Integridad Científica (EIBIC) y orientación de la nueva '
        'Política Institucional de Innovación y Emprendimiento.'
    ),
    'fecha_inicio': date(2026, 8, 20),
    'fecha_fin': date(2026, 8, 20),
    'activa': True,
}

HILO_EIBIC_OPCIONES = [
    'Verde — capacidad o fortaleza que debe consolidarse',
    'Rojo — riesgo, dilema, conflicto o barrera que debe resolverse',
    'Amarillo — oportunidad, solución o nueva práctica que debería desarrollarse',
    'Azul — necesidad de articulación, gobernanza, participación o trabajo conjunto',
]

HILO_BRUJULA_OPCIONES = [
    'Verde — fortalecer una capacidad existente o construir una nueva capacidad',
    'Rojo — resolver una barrera o nudo estructural',
    'Amarillo — desarrollar una nueva oportunidad, apuesta o futuro posible',
    'Azul — crear una conexión, alianza o nueva forma de articulación',
]

RUMBO_OPCIONES = [
    'Rumbo 1 — Personas y Cultura',
    'Rumbo 2 — Conocimiento que se transforma',
    'Rumbo 3 — Ecosistema y Conexiones',
    'Rumbo 4 — Impacto y Territorio',
]

MOMENTOS = [
    {
        'orden': 1,
        'titulo': 'Momento 1 — EIBIC: reflexión individual',
        'tipo': Momento.TIPO_INDIVIDUAL,
        'contexto': (
            'Construir colectivamente los lineamientos estratégicos que deben orientar la Ética '
            'de la Investigación, Bioética e Integridad Científica (EIBIC) en UNIMAGDALENA. '
            'Responde individualmente antes de la deliberación en mesa.'
        ),
        'preguntas': [
            {'texto': '¿Qué principio ético debería ser irrenunciable en toda actividad de '
                       'investigación, innovación, creación y transferencia que se desarrolle en '
                       'UNIMAGDALENA?'},
            {'texto': '¿En qué momentos del ciclo de una investigación —formulación, evaluación, '
                       'ejecución, manejo de datos, publicación, transferencia o apropiación— '
                       'considera que existen hoy los mayores riesgos éticos o de integridad '
                       'científica?'},
            {'texto': '¿Qué dilema o conflicto ético considera más urgente prevenir o gestionar '
                       'en la Universidad: conflictos de interés, autoría, propiedad intelectual, '
                       'manejo de datos, consentimiento informado, relación con comunidades, uso '
                       'de inteligencia artificial, evaluación, publicación u otro?'},
            {'texto': '¿Qué debería cambiar en el Comité de Ética en Investigación y sus '
                       'subcomités para responder de manera oportuna, especializada y '
                       'proporcional a la diversidad de investigaciones, disciplinas y niveles de '
                       'riesgo de la Universidad?'},
            {'texto': '¿Cuáles conocimientos y capacidades mínimas en ética de la investigación, '
                       'bioética e integridad científica deberían desarrollar toda persona que '
                       'participe en actividades de investigación y creación en UNIMAGDALENA?'},
            {'texto': '¿Cuáles responsabilidades tienen los investigadores en una investigación '
                       'que involucre personas, comunidades, pueblos y saberes tradicionales, '
                       'animales, biodiversidad, datos sensibles o tecnologías emergentes, para '
                       'asegurar respeto, participación, reconocimiento, beneficios y protección '
                       'frente a posibles daños?'},
            {'texto': '¿Cuál es el principio ético fundamental que debe orientar toda actividad '
                       'de investigación, innovación, creación y transferencia en Unimagdalena, y '
                       'cuáles deberían ser los tres compromisos irrenunciables de investigadores '
                       'y de la Universidad cuando se transita de investigación académica a '
                       'innovación, empresa, emprendimiento o spin-off?'},
        ],
    },
    {
        'orden': 2,
        'titulo': 'Momento 1 — EIBIC: consenso de mesa',
        'tipo': Momento.TIPO_MESA,
        'contexto': (
            'Con base en la reflexión individual, la mesa delibera y construye consensos sobre '
            'los lineamientos EIBIC.'
        ),
        'preguntas': [
            {'texto': '¿Cuáles deben ser los cinco principios irrenunciables que orienten la '
                       'ética de la investigación, la bioética y la integridad científica en '
                       'UNIMAGDALENA?'},
            {'texto': '¿Cuáles son los cinco riesgos, dilemas o conflictos en EIBIC prioritarios '
                       'que el sistema institucional de EIBIC debe prevenir, detectar o '
                       'gestionar?'},
            {'texto': '¿Qué arquitectura mínima de gobernanza ética necesita la Universidad para '
                       'articular el Comité de Ética en Investigación, los subcomités, las '
                       'facultades, los programas, los investigadores y las demás instancias '
                       'responsables?'},
            {'texto': '¿Cuáles son las tres capacidades institucionales prioritarias que deben '
                       'fortalecerse para consolidar una cultura EIBIC en toda la Universidad?'},
            {'texto': '¿Cómo debería incorporarse la formación en EIBIC en pregrado, posgrado y '
                       'formación de investigadores, considerando las diferencias entre '
                       'disciplinas y tipos de investigación?'},
            {'texto': '¿Cómo transversalizar los lineamientos en EIBIC en los diferentes '
                       'escenarios misionales de docencia, investigación y extensión en la '
                       'Universidad?'},
        ],
    },
    {
        'orden': 3,
        'titulo': 'Dinámica 1 — El nudo que cuida',
        'tipo': Momento.TIPO_MESA,
        'contexto': (
            'Al finalizar el Momento 1, cada mesa construye un "nudo de cuidado": relaciona una '
            'conclusión central de su conversación con una salvaguarda o compromiso concreto, y '
            'elige un hilo de color según la naturaleza de esa conclusión.'
        ),
        'preguntas': [
            {'texto': '¿Qué debemos cuidar? Identifiquen aquello que consideran fundamental '
                       'proteger desde la EIBIC (personas, comunidades, saberes, derechos, datos, '
                       'biodiversidad, autoría, confianza, calidad científica, independencia, '
                       'transparencia, u otro).'},
            {'texto': '¿Qué conclusión de nuestra mesa resulta más importante para lograrlo?'},
            {'texto': '¿Qué compromiso o salvaguarda permitiría protegerlo?'},
            {'texto': '¿Qué hilo de color representa mejor la naturaleza de la conclusión '
                       'principal de la mesa?', 'tipo': Pregunta.TIPO_UNICA,
             'opciones': HILO_EIBIC_OPCIONES},
        ],
    },
    {
        'orden': 4,
        'titulo': 'Momento 2 — La brújula: reflexión individual',
        'tipo': Momento.TIPO_INDIVIDUAL,
        'contexto': (
            'Definir colectivamente los elementos estratégicos que deben orientar la Política '
            'Institucional de Innovación y Emprendimiento de UNIMAGDALENA. Responde '
            'individualmente antes de la deliberación en mesa.'
        ),
        'preguntas': [
            {'texto': '¿Qué debe significar innovar y emprender al estilo UNIMAGDALENA y qué '
                       'debería diferenciarnos como universidad pública, caribeña, incluyente, '
                       'intercultural y comprometida con el territorio?'},
            {'texto': '¿Qué propósitos y principios deben orientar la innovación y el '
                       'emprendimiento para que generen valor público y compartido, bienestar, '
                       'sostenibilidad e impactos verificables, y no se reduzcan únicamente a la '
                       'creación de empresas o a resultados económicos?'},
            {'texto': '¿Qué competencias y experiencias deberían desarrollar estudiantes, '
                       'profesores, graduados y servidores para que la innovación, la creatividad '
                       'y el emprendimiento sean capacidades transversales de la comunidad '
                       'universitaria?'},
            {'texto': '¿Cómo debemos conectar la investigación, la creación y los saberes '
                       'científicos, ancestrales, comunitarios y territoriales con la innovación, '
                       'el emprendimiento, la transferencia y la apropiación social del '
                       'conocimiento, evitando prácticas extractivas y fortaleciendo la justicia '
                       'epistémica y la soberanía del conocimiento?'},
            {'texto': '¿Qué rutas, apoyos y capacidades institucionales deberían acompañar una '
                       'iniciativa desde la identificación de un problema u oportunidad hasta su '
                       'validación, adopción, transferencia, creación de emprendimientos o '
                       'spin-off y escalamiento?'},
            {'texto': '¿Cómo deberían integrarse la inteligencia artificial, los datos y las '
                       'tecnologías emergentes a la innovación y el emprendimiento para ampliar '
                       'capacidades humanas y territoriales, generar nuevas soluciones y reducir '
                       'brechas, manteniendo la centralidad del ser humano, la ética, la '
                       'inclusión y la sostenibilidad?'},
            {'texto': '¿Qué relaciones deberíamos fortalecer con empresas, Estado, comunidades, '
                       'organizaciones sociales, pueblos indígenas, graduados, inversionistas, '
                       'universidades y aliados nacionales e internacionales para convertir a '
                       'UNIMAGDALENA en un ecosistema abierto de innovación y emprendimiento '
                       'conectado con los desafíos del Caribe?'},
            {'texto': '¿Qué resultados e impactos deberíamos poder demostrar en 2036 para '
                       'afirmar que la innovación y el emprendimiento están transformando '
                       'efectivamente la Universidad, las personas, las organizaciones y el '
                       'territorio?'},
        ],
    },
    {
        'orden': 5,
        'titulo': 'Momento 2 — La brújula: consenso de mesa',
        'tipo': Momento.TIPO_MESA,
        'contexto': (
            'Con base en la reflexión individual, la mesa delibera y construye consensos sobre '
            'la orientación de la Política de Innovación y Emprendimiento.'
        ),
        'preguntas': [
            {'texto': '¿Cuál debe ser la promesa diferencial de UNIMAGDALENA como universidad '
                       'innovadora y emprendedora del Caribe y qué propósito superior debe '
                       'orientar su Política de Innovación y Emprendimiento?'},
            {'texto': '¿Cuáles deben ser los cinco principios irrenunciables que orienten las '
                       'decisiones institucionales sobre innovación, emprendimiento, '
                       'transferencia, spin-off y relación con el entorno?'},
            {'texto': '¿Cuáles son las cinco capacidades institucionales prioritarias que '
                       'debemos consolidar o desarrollar para hacer posible ese modelo de '
                       'universidad innovadora y emprendedora?'},
            {'texto': '¿Cuáles deben ser las tres transformaciones estructurales prioritarias '
                       'que la nueva política debe producir en la cultura, la formación, la '
                       'investigación y creación, la transferencia, el emprendimiento o la '
                       'relación de UNIMAGDALENA con su ecosistema?'},
            {'texto': '¿Cuáles son los cinco resultados o impactos verificables que deberían '
                       'evidenciar en 2036 que la Política de Innovación y Emprendimiento está '
                       'generando valor público, valor compartido y transformación territorial?'},
        ],
    },
    {
        'orden': 6,
        'titulo': 'Dinámica 2 — La brújula tejida',
        'tipo': Momento.TIPO_MESA,
        'contexto': (
            'Cada mesa define hacia cuál de los cuatro rumbos (Personas y Cultura, Conocimiento '
            'que se transforma, Ecosistema y Conexiones, Impacto y Territorio) apunta su '
            'propuesta, qué transformación concreta impulsa y qué impacto espera producir.'
        ),
        'preguntas': [
            {'texto': '¿Hacia cuál de los cuatro rumbos apunta principalmente la propuesta de la '
                       'mesa?', 'tipo': Pregunta.TIPO_UNICA, 'opciones': RUMBO_OPCIONES},
            {'texto': '¿Qué transformación concreta necesitamos impulsar? (la respuesta debe '
                       'comenzar con un verbo: Crear, Transformar, Conectar, Fortalecer, '
                       'Simplificar, Formar, Financiar, Reconocer, Incentivar, Transferir, '
                       'Escalar...)'},
            {'texto': '¿Qué impacto esperamos producir? Completen: "Sabremos que avanzamos '
                       'cuando..."'},
            {'texto': '¿Qué hilo de color representa mejor la naturaleza de la transformación '
                       'propuesta?', 'tipo': Pregunta.TIPO_UNICA, 'opciones': HILO_BRUJULA_OPCIONES},
        ],
    },
]


class Command(BaseCommand):
    help = 'Precarga la Jornada Ágil 2 (EIBIC + Política de Innovación y Emprendimiento).'

    @transaction.atomic
    def handle(self, *args, **options):
        jornada, creada = Jornada.objects.update_or_create(
            slug=JORNADA['slug'], defaults={k: v for k, v in JORNADA.items() if k != 'slug'}
        )
        self.stdout.write(('Creada' if creada else 'Actualizada') + f' jornada "{jornada.nombre}"')

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
                pregunta, p_creada = Pregunta.objects.update_or_create(
                    momento=momento, orden=i,
                    defaults={
                        'texto': pregunta_data['texto'],
                        'tipo': pregunta_data.get('tipo', Pregunta.TIPO_ABIERTA),
                        'obligatoria': True,
                        'activa': True,
                    },
                )
                for j, opcion_texto in enumerate(pregunta_data.get('opciones', []), start=1):
                    OpcionPregunta.objects.update_or_create(
                        pregunta=pregunta, orden=j, defaults={'texto': opcion_texto},
                    )

        self.stdout.write(self.style.SUCCESS(
            f'Listo: {len(MOMENTOS)} momentos, '
            f'{sum(len(m["preguntas"]) for m in MOMENTOS)} preguntas.'
        ))
