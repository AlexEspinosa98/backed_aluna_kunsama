"""Precarga el instrumento "Leer, escribir y pensar en tiempos de inteligencia artificial" a
partir del documento institucional Reflexion_Lectura_Escritura_IA_UNIMAGDALENA.docx (Universidad
del Magdalena, 2026): una reflexión pedagógica sobre alfabetización funcional y escritura en la
era de la IA generativa, con una matriz comparativa de 8 aspectos × 3 columnas y 6 preguntas
abiertas de discusión docente.

Idempotente: usa update_or_create por slug/orden, así que correrlo de nuevo actualiza el
contenido en vez de duplicarlo. El instrumento queda sin ningún encargado asignado (solo visible
para administradores completos) hasta que se le asigne uno vía /api/admin/instrumentos/.

Uso:
    python manage.py cargar_instrumento_reflexion
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from instrumentos.models import (
    ColumnaMatrizInstrumento, FilaMatrizInstrumento, Instrumento, PreguntaInstrumento,
    SeccionInstrumento,
)

INSTRUMENTO = {
    'slug': 'reflexion-lectura-escritura-ia',
    'nombre': 'Leer, escribir y pensar en tiempos de inteligencia artificial',
    'descripcion': (
        'Documento de trabajo para docentes de competencias comunicativas — una reflexión a '
        'partir de un correo cotidiano. Universidad del Magdalena, 2026.'
    ),
}

SECCIONES_CONTENIDO = [
    (
        1, 'Nota ética',
        'El caso ha sido completamente anonimizado. No interesa identificar, juzgar ni '
        'ridiculizar a quien escribió el mensaje. Se utiliza exclusivamente como detonante '
        'pedagógico para pensar las brechas de alfabetización, el derecho a una educación de '
        'calidad y los desafíos de la inteligencia artificial generativa.'
    ),
    (
        2, '1. El correo que me hizo detenerme',
        'Entre los muchos correos que recibo diariamente como Rector, recientemente encontré uno '
        'que me hizo detenerme. No fue por la solicitud en sí misma —que relataba una situación '
        'humana que merecía atención—, sino por la enorme dificultad para comprender con '
        'precisión qué había sucedido. El mensaje acumulaba hechos, emociones, actores y momentos '
        'en extensas secuencias casi sin puntuación; cambiaba de sujeto sin advertencia; mezclaba '
        'lo que la persona sabía con lo que suponía; y hacía difícil reconstruir una cronología '
        'básica.\n'
        'Mi primera reacción no debe ser la burla ni el juicio. Una persona puede haber crecido '
        'en condiciones de desigualdad, haber tenido acceso precario a la educación o haber '
        'atravesado una trayectoria escolar que no logró garantizarle aprendizajes fundamentales. '
        'En ese caso, el problema no es solamente individual: nos interpela como sociedad y como '
        'sistema educativo. Pero la inquietud se vuelve todavía mayor cuando mensajes con '
        'dificultades semejantes llegan también de estudiantes universitarios e incluso de '
        'graduados.'
    ),
    (
        3, '2. Un fragmento anonimizado',
        'El siguiente fragmento conserva deliberadamente sus problemas de redacción para efectos '
        'del ejercicio:\n'
        '"...el estudiante me hace una cita a la cual yo asisto llegando a la universidad me dan '
        'un ticket que dice cirugía la verdad yo pensé que sólo era una valoración porque el '
        'estudiante nunca me dejó claro que ese día me iban a realizar unas extracciones..."'
    ),
    (
        4, '3. El nuevo analfabetismo: una provocación, no una etiqueta',
        'Durante mucho tiempo asociamos el analfabetismo con no poder leer ni escribir. Hoy esa '
        'definición elemental resulta insuficiente para comprender el problema. Una persona puede '
        'tener un teléfono inteligente, abrir una cuenta de correo, escribir mensajes, navegar '
        'por redes sociales e incluso producir textos con inteligencia artificial y, sin embargo, '
        'tener enormes dificultades para comprender un texto complejo, organizar una idea, '
        'distinguir evidencia de opinión, interpretar información cuantitativa o formular un '
        'argumento.\n'
        'Por eso prefiero hablar aquí de una provocación pedagógica y no de una nueva categoría '
        'para etiquetar personas. El desafío contemporáneo es la alfabetización funcional, '
        'crítica, numérica y digital: poder usar la lectura, la escritura y el razonamiento para '
        'participar de manera autónoma en la vida social, académica, laboral y democrática.\n'
        'El problema es paradójico. Nunca habíamos tenido tantas herramientas para producir '
        'palabras y contenidos, pero producir texto no equivale a comprender; tener acceso a '
        'información no equivale a saber evaluarla; y conseguir que una máquina redacte un '
        'párrafo impecable no equivale a saber pensar.'
    ),
    (
        5, '4. La IA no elimina la necesidad de saber escribir',
        'La inteligencia artificial generativa puede corregir ortografía, reorganizar párrafos, '
        'mejorar el tono, resumir y proponer estructuras. Es una herramienta extraordinaria. Pero '
        'su utilidad depende de la capacidad de la persona para reconocer el problema, formular '
        'una instrucción pertinente, verificar el resultado y asumir responsabilidad por lo que '
        'finalmente comunica.\n'
        'La IA puede mejorar la expresión de una idea; no garantiza la calidad, la verdad ni la '
        'claridad de la idea.\n'
        'En un caso como el analizado, una IA podría convertir una narración confusa en una '
        'comunicación elegante, pero también podría introducir relaciones causales que la persona '
        'nunca estableció, convertir una percepción en una afirmación de hecho o dar fuerza '
        'jurídica a algo que el relato original no permite concluir. Un texto más fluido puede '
        'ser, paradójicamente, más peligroso si quien lo firma no posee las competencias para '
        'revisarlo críticamente.\n'
        'Por ello, cuanto mejores sean las máquinas escribiendo, más importante será que los '
        'seres humanos sepan leer, escribir, argumentar, preguntar, contrastar y revisar. La '
        'alfabetización en inteligencia artificial no reemplaza la alfabetización tradicional: se '
        'construye sobre ella.'
    ),
    (
        6, '5. Educación digna: el verdadero asunto',
        'Esta reflexión no debería conducirnos a responsabilizar únicamente a quien escribe mal. '
        'Debería conducirnos a preguntarnos qué significa garantizar el derecho a una educación '
        'digna. No basta con matricular, promover, graduar o entregar un diploma. Una educación '
        'digna debe ampliar de manera efectiva la capacidad de una persona para comprender el '
        'mundo, expresar su pensamiento, razonar con cantidades, dialogar con otras perspectivas '
        'y tomar decisiones informadas.\n'
        'Si un estudiante atraviesa años de escolaridad y llega a la universidad sin poder '
        'construir un relato comprensible, interpretar críticamente un documento o organizar un '
        'argumento, tenemos que preguntarnos no solamente qué le faltó al estudiante, sino qué no '
        'logró garantizar el sistema educativo.\n'
        'Y si alguien obtiene un título universitario conservando esas brechas, la pregunta es '
        'todavía más exigente para nosotros. La inclusión no puede significar reducir la '
        'expectativa académica. Precisamente porque creemos en la inclusión, debemos garantizar '
        'oportunidades reales para desarrollar las capacidades que permiten ejercer plenamente la '
        'ciudadanía y una profesión.'
    ),
    (
        7, '6. Volver a lo fundamental',
        'En medio de la fascinación por la inteligencia artificial, la automatización y las '
        'nuevas tecnologías, corremos el riesgo de considerar obsoletos algunos aprendizajes '
        'fundamentales. Creo que ocurre exactamente lo contrario. Lectura, escritura, matemáticas, '
        'humanidades, pensamiento científico, historia, filosofía y artes son hoy más necesarias '
        'porque proporcionan estructuras desde las cuales podemos juzgar aquello que producen las '
        'máquinas.\n'
        'Las redes digitales permiten que cualquier persona produzca y distribuya contenido, y '
        'eso amplía posibilidades democráticas y creativas. Pero la abundancia de contenidos no '
        'garantiza su valor. En un entorno saturado de información, la educación debe ayudarnos a '
        'distinguir lo relevante de lo trivial, la evidencia de la opinión, el argumento de la '
        'manipulación y el conocimiento de la mera popularidad.'
    ),
    (
        8, '7. Radiografía comunicativa del fragmento',
        'Dimensión → Dificultad observable\n'
        'Puntuación y segmentación → Acumula varias acciones y momentos sin delimitar unidades de '
        'sentido.\n'
        'Sintaxis y concordancia → Dificulta reconocer con rapidez sujeto, acción, objeto y '
        'circunstancia.\n'
        'Referentes → "Él", "el estudiante" o "el doctor" pueden dejar incierto quién hizo qué.\n'
        'Cronología → No permite reconstruir fácilmente el orden de los acontecimientos.\n'
        'Hechos e interpretaciones → Mezcla síntomas, recuerdos, inferencias y valoraciones '
        'emocionales.\n'
        'Registro y precisión → Algunas expresiones comunican angustia, pero reducen precisión '
        'institucional.\n'
        'Propósito → La solicitud queda parcialmente oculta por la desorganización del relato.'
    ),
    (
        9, '8. Ejercicio para un claustro o taller docente',
        'Propósito: discutir qué significa enseñar competencias comunicativas en la era de la '
        'IA. Duración sugerida: 60–75 minutos.\n'
        '1. Leer sin IA (10 min): identificar problemas de puntuación, sintaxis, coherencia, '
        'referentes, cronología, registro, precisión y propósito.\n'
        '2. Reconstruir el significado (15 min): separar en tres grupos — hechos que el texto '
        'afirma; percepciones o emociones; información que no puede determinarse con certeza.\n'
        '3. Reescribir humanamente (15 min): producir una versión clara y breve sin IA y sin '
        'agregar hechos.\n'
        '4. Trabajar con IA (15 min): pedir a una IA que mejore el mensaje. Marcar lo que añadió, '
        'eliminó, suavizó, intensificó o interpretó.\n'
        '5. Comparar y discutir (15–20 min): preguntar qué conocimientos fueron necesarios para '
        'evaluar la salida de la IA y qué riesgo existiría si el autor aceptara automáticamente '
        'la primera versión.'
    ),
    (
        12, '11. Tesis para la discusión',
        'El reto educativo de la inteligencia artificial no es conseguir que todos puedan generar '
        'textos. Es lograr que todos puedan comprenderlos, juzgarlos, cuestionarlos y hacerse '
        'responsables de ellos.\n'
        'Una universidad comprometida con la inclusión no puede conformarse con facilitar acceso '
        'a herramientas. Debe formar las capacidades humanas que permiten utilizarlas con '
        'autonomía. El verdadero riesgo de una sociedad rodeada de inteligencia artificial no es '
        'solamente que las máquinas escriban por nosotros; es que dejemos de desarrollar las '
        'capacidades necesarias para saber cuándo aquello que escriben tiene sentido.'
    ),
    (
        13, '12. Referentes para ampliar la discusión',
        'UNESCO distingue la alfabetización básica de la alfabetización funcional, entendida como '
        'la capacidad de utilizar lectura, escritura y cálculo para desenvolverse eficazmente en '
        'la comunidad y contribuir al desarrollo propio y colectivo. La Encuesta de Competencias '
        'de Adultos 2023 de la OCDE aborda alfabetización, numeracia y resolución adaptativa de '
        'problemas como capacidades fundacionales para desenvolverse en la vida cotidiana, el '
        'trabajo y la ciudadanía. Estos referentes ayudan a evitar una visión reducida de la '
        'alfabetización como simple capacidad mecánica de decodificar o producir palabras.\n'
        'Documento de reflexión y trabajo pedagógico · Universidad del Magdalena · 2026'
    ),
]

MATRIZ_FILAS = [
    'Claridad del propósito',
    'Cronología',
    'Identificación de actores',
    'Hechos vs. interpretaciones',
    'Precisión léxica',
    'Coherencia',
    'Información añadida/no sustentada',
    'Riesgos de interpretación',
]

MATRIZ_COLUMNAS = ['Texto original', 'Reescritura humana', 'Versión con IA']

PREGUNTAS_DISCUSION = [
    '¿Estamos enseñando a escribir para aprobar una asignatura o para participar competentemente '
    'en la vida?',
    '¿Cómo detectar y atender brechas de lectura y escritura sin estigmatizar?',
    '¿Qué competencias comunicativas mínimas deberían demostrar todos nuestros graduados?',
    '¿Qué cambia en la enseñanza de la escritura cuando una máquina puede producir textos '
    'formalmente excelentes?',
    '¿Qué debe saber una persona para detectar que una respuesta de IA es elegante pero '
    'incorrecta?',
    '¿Cómo articulamos lectura, escritura, matemáticas, humanidades y alfabetización en IA como '
    'capacidades transversales?',
]


class Command(BaseCommand):
    help = 'Precarga el instrumento de reflexión Lectura/Escritura/IA (UNIMAGDALENA) con su matriz y preguntas.'

    @transaction.atomic
    def handle(self, *args, **options):
        instrumento, _ = Instrumento.objects.update_or_create(
            slug=INSTRUMENTO['slug'],
            defaults={'nombre': INSTRUMENTO['nombre'], 'descripcion': INSTRUMENTO['descripcion']},
        )

        for orden, titulo, contenido in SECCIONES_CONTENIDO:
            SeccionInstrumento.objects.update_or_create(
                instrumento=instrumento, orden=orden,
                defaults={
                    'titulo': titulo, 'tipo': SeccionInstrumento.TIPO_CONTENIDO,
                    'contenido': contenido, 'activa': True,
                },
            )

        seccion_matriz, _ = SeccionInstrumento.objects.update_or_create(
            instrumento=instrumento, orden=10,
            defaults={
                'titulo': '9. Matriz de comparación', 'tipo': SeccionInstrumento.TIPO_PREGUNTAS,
                'contenido': '', 'activa': True,
            },
        )
        pregunta_matriz, _ = PreguntaInstrumento.objects.update_or_create(
            seccion=seccion_matriz, orden=1,
            defaults={
                'tipo': PreguntaInstrumento.TIPO_MATRIZ,
                'texto': 'Compare el texto original, su reescritura humana y la versión con IA en cada aspecto.',
                'obligatoria': True, 'activa': True,
            },
        )
        for orden, texto in enumerate(MATRIZ_FILAS, start=1):
            FilaMatrizInstrumento.objects.update_or_create(
                pregunta=pregunta_matriz, orden=orden, defaults={'texto': texto}
            )
        for orden, texto in enumerate(MATRIZ_COLUMNAS, start=1):
            ColumnaMatrizInstrumento.objects.update_or_create(
                pregunta=pregunta_matriz, orden=orden, defaults={'texto': texto}
            )

        seccion_preguntas, _ = SeccionInstrumento.objects.update_or_create(
            instrumento=instrumento, orden=11,
            defaults={
                'titulo': '10. Preguntas para la conversación docente',
                'tipo': SeccionInstrumento.TIPO_PREGUNTAS, 'contenido': '', 'activa': True,
            },
        )
        for orden, texto in enumerate(PREGUNTAS_DISCUSION, start=1):
            PreguntaInstrumento.objects.update_or_create(
                seccion=seccion_preguntas, orden=orden,
                defaults={
                    'tipo': PreguntaInstrumento.TIPO_ABIERTA, 'texto': texto,
                    'obligatoria': True, 'activa': True,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f'Instrumento "{instrumento.nombre}" ({instrumento.slug}) cargado/actualizado.'
        ))
