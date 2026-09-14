"""Precarga el "Instrumento de Diagnóstico para la Articulación Académica" (Universidad del
Magdalena) a partir de Formato_Diagnostico_Articulacion_Academica_UNIMAGDALENA.docx: una sesión de
trabajo de ~90 minutos (jefe de departamento + docentes + decano/delegado + directores de
programa) para identificar capacidades, brechas, duplicidades y puntos de articulación académica.

Es un instrumento distinto e independiente del de reflexión
(`cargar_instrumento_reflexion`) — mismo módulo `instrumentos`, mismo flujo completo (preregistro,
revisión, dashboard, descarga en Word), pero es un segundo `Instrumento` aparte con su propio
árbol de secciones/preguntas.

Tres de sus tablas (mapa de capacidades profesorales, asuntos para decisión institucional,
compromisos inmediatos) no tienen filas fijas en el documento original — el grupo agrega tantas
como necesite en la sesión. En vez de un tipo de pregunta nuevo, se modelan con el tipo `matriz`
ya existente, precargado con un número generoso de filas en blanco (más que las que trae el propio
Word) — el admin puede agregar más desde `/api/admin/instrumento-filas-matriz/` en cualquier
momento si una sesión concreta las necesita.

Idempotente: usa `update_or_create` por slug/orden, así que correrlo de nuevo actualiza el
contenido en vez de duplicarlo.

Uso:
    python manage.py cargar_instrumento_diagnostico_articulacion
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from instrumentos.models import (
    ColumnaMatrizInstrumento, FilaMatrizInstrumento, Instrumento, OpcionPreguntaInstrumento,
    PreguntaInstrumento, SeccionInstrumento,
)

INSTRUMENTO = {
    'slug': 'diagnostico-articulacion-academica',
    'nombre': 'Instrumento de Diagnóstico para la Articulación Académica',
    'descripcion': (
        'Departamentos · Facultades · Programas · Estudios Generales · CREO · Posgrados. Sesión '
        'de trabajo de aproximadamente 90 minutos liderada por el jefe de departamento, con '
        'participación de sus docentes, el decano o su delegado y los directores de programas '
        'relacionados — Universidad del Magdalena.'
    ),
}

DATOS_GENERALES = [
    'Unidad/Departamento',
    'Facultad/Unidad asociada',
    'Responsable',
    'Fecha de sesión',
    'Programas participantes',
    'N.º participantes',
]

PROPOSITO_METODOLOGIA = (
    'Este instrumento permite identificar capacidades, brechas, duplicidades, vacíos y puntos de '
    'articulación académica. Debe diligenciarse en una sesión de trabajo de aproximadamente 90 '
    'minutos, liderada por el jefe de departamento, con participación de sus docentes, el decano '
    'o su delegado y los directores de programas relacionados. Cuando corresponda, se recomienda '
    'vincular a CREO, Estudios Generales y Posgrados. El propósito no es resolver en esta sesión '
    'los conflictos de competencia, sino identificarlos y formular alternativas para la reunión '
    'institucional de articulación.\n'
    'Semáforo: 🟢 articulación consolidada · 🟡 articulación parcial/informal · 🔴 ausencia, '
    'duplicidad, vacío o conflicto.'
)

MAPA_OFERTA_ASPECTOS = [
    'Programas y modalidades en los que participa la unidad',
    'Asignaturas/componentes disciplinares que atiende',
    'Número y tipo de profesores (planta, ocasionales, cátedra)',
    'Perfiles de formación y principales áreas de experticia',
    'Asignaturas/componentes equivalentes en distintos programas o modalidades',
    'Asignaturas del área atendidas por profesores externos al departamento',
    'Principales brechas de capacidad profesoral identificadas',
]

SEMAFORO_DIMENSIONES = [
    'Diseño y revisión de microdiseños',
    'Contenidos mínimos disciplinares',
    'Resultados de aprendizaje',
    'Evaluaciones comunes / comparables',
    'Perfil requerido del profesor',
    'Selección y asignación docente',
    'Formación y actualización docente',
    'Nivelación académica',
    'Seguimiento del desempeño estudiantil',
    'Saber Pro',
    'Innovación pedagógica e inteligencia artificial',
    'Articulación con educación media',
    'Articulación pregrado-posgrado',
    'Articulación presencial-CREO / modalidades',
]
SEMAFORO_OPCIONES = [
    '🟢 Articulación consolidada',
    '🟡 Articulación parcial o informal',
    '🔴 Ausencia, duplicidad, vacío o conflicto',
]
SEMAFORO_SUBPREGUNTAS_ABIERTAS = ['¿Cómo funciona hoy?', 'Problema / brecha', 'Propuesta inicial']

RESPONSABILIDADES_PROCESOS = [
    'Microdiseños',
    'Estándares disciplinares',
    'Resultados de aprendizaje',
    'Evaluación',
    'Perfil profesoral',
    'Asignación docente',
    'Formación profesoral',
    'Nivelación',
    'Saber Pro',
    'Innovación pedagógica e IA',
    'Oferta abierta, a distancia, virtual e híbrida',
    'Posgrados',
]
RESPONSABILIDADES_COLUMNAS = [
    '¿Quién lo hace hoy?', '¿Quién debería liderar?', '¿Quién debe participar?', '¿Quién debería validar?',
]

COHERENCIA_VARIABLES = [
    'Nombre', 'Créditos', 'Resultados de aprendizaje', 'Contenidos esenciales',
    'Perfil del profesor', 'Estrategia de evaluación', 'Recursos/bibliografía',
]
COHERENCIA_COLUMNAS = [
    'Programa/modalidad A', 'Programa/modalidad B', 'Programa/modalidad C', 'CREO / otra modalidad',
]
COHERENCIA_PREGUNTAS_ABIERTAS = [
    '¿Qué debería ser común?', '¿Qué puede ser diferente y por qué?',
    '¿Qué diferencias actuales no tienen justificación académica?',
]

# Filas de sobra (más que las del Word) para las 3 tablas de "cuantas filas hagan falta" — el
# admin puede agregar más desde /api/admin/instrumento-filas-matriz/ si una sesión concreta
# necesita todavía más.
CAPACIDADES_FILAS = [f'Profesor(a) {i}' for i in range(1, 13)]
CAPACIDADES_COLUMNAS = [
    'Nombre', 'Formación', 'Área de experticia', 'Asignaturas', 'Programas/modalidades',
    'Necesidades de actualización',
]

SINTESIS_EJECUTIVA = [
    'Tres fortalezas que debemos preservar (máximo 3 prioridades)',
    'Tres problemas de articulación que debemos resolver (máximo 3 prioridades)',
    'Tres procesos que deberían estandarizarse institucionalmente (máximo 3 prioridades)',
    'Tres decisiones que requieren acuerdo entre unidades (máximo 3 prioridades)',
    'Tres acciones que la unidad puede iniciar inmediatamente (máximo 3 prioridades)',
]

ASUNTOS_FILAS = [f'Ítem {i}' for i in range(1, 9)]
ASUNTOS_COLUMNAS = ['Asunto', 'Unidades involucradas', 'Alternativas identificadas', 'Decisión requerida']

COMPROMISOS_FILAS = [f'Ítem {i}' for i in range(1, 9)]
COMPROMISOS_COLUMNAS = ['Acción', 'Responsable', 'Apoyos requeridos', 'Plazo propuesto']

PRINCIPIO_ORIENTADOR = (
    'Principio orientador: articular capacidades para fortalecer la calidad académica, evitando '
    'duplicidades, vacíos y conflictos de competencia.'
)


def _seccion(instrumento, orden, titulo, tipo=SeccionInstrumento.TIPO_PREGUNTAS, contenido=''):
    seccion, _ = SeccionInstrumento.objects.update_or_create(
        instrumento=instrumento, orden=orden,
        defaults={'titulo': titulo, 'tipo': tipo, 'contenido': contenido, 'activa': True},
    )
    return seccion


def _pregunta_abierta(seccion, orden, texto, obligatoria=True):
    pregunta, _ = PreguntaInstrumento.objects.update_or_create(
        seccion=seccion, orden=orden,
        defaults={
            'tipo': PreguntaInstrumento.TIPO_ABIERTA, 'texto': texto,
            'obligatoria': obligatoria, 'activa': True,
        },
    )
    return pregunta


def _pregunta_unica(seccion, orden, texto, opciones, obligatoria=True):
    pregunta, _ = PreguntaInstrumento.objects.update_or_create(
        seccion=seccion, orden=orden,
        defaults={
            'tipo': PreguntaInstrumento.TIPO_UNICA, 'texto': texto,
            'obligatoria': obligatoria, 'activa': True,
        },
    )
    for orden_opcion, texto_opcion in enumerate(opciones, start=1):
        OpcionPreguntaInstrumento.objects.update_or_create(
            pregunta=pregunta, orden=orden_opcion, defaults={'texto': texto_opcion}
        )
    return pregunta


def _pregunta_matriz(seccion, orden, texto, filas, columnas, obligatoria=True):
    pregunta, _ = PreguntaInstrumento.objects.update_or_create(
        seccion=seccion, orden=orden,
        defaults={
            'tipo': PreguntaInstrumento.TIPO_MATRIZ, 'texto': texto,
            'obligatoria': obligatoria, 'activa': True,
        },
    )
    for orden_fila, texto_fila in enumerate(filas, start=1):
        FilaMatrizInstrumento.objects.update_or_create(
            pregunta=pregunta, orden=orden_fila, defaults={'texto': texto_fila}
        )
    for orden_columna, texto_columna in enumerate(columnas, start=1):
        ColumnaMatrizInstrumento.objects.update_or_create(
            pregunta=pregunta, orden=orden_columna, defaults={'texto': texto_columna}
        )
    return pregunta


class Command(BaseCommand):
    help = 'Precarga el instrumento de Diagnóstico de Articulación Académica (UNIMAGDALENA).'

    @transaction.atomic
    def handle(self, *args, **options):
        instrumento, _ = Instrumento.objects.update_or_create(
            slug=INSTRUMENTO['slug'],
            defaults={'nombre': INSTRUMENTO['nombre'], 'descripcion': INSTRUMENTO['descripcion']},
        )

        # 1 — Datos generales de la sesión
        seccion = _seccion(instrumento, 1, 'Datos generales de la sesión')
        for i, texto in enumerate(DATOS_GENERALES, start=1):
            _pregunta_abierta(seccion, i, texto)

        # 2 — Propósito y metodología
        _seccion(
            instrumento, 2, '1. Propósito y metodología',
            tipo=SeccionInstrumento.TIPO_CONTENIDO, contenido=PROPOSITO_METODOLOGIA,
        )

        # 3 — Mapa de oferta y capacidades (no obligatoria: no todas las unidades tienen algo que
        # reportar en cada aspecto).
        seccion = _seccion(instrumento, 3, '2. Mapa de oferta y capacidades')
        for i, texto in enumerate(MAPA_OFERTA_ASPECTOS, start=1):
            _pregunta_abierta(seccion, i, texto, obligatoria=False)

        # 4 — Semáforo de articulación académica: 14 dimensiones × (1 semáforo + 3 abiertas). No
        # obligatoria: exigir las 56 en una sesión de 90 minutos no es realista.
        seccion = _seccion(instrumento, 4, '3. Semáforo de articulación académica')
        orden = 1
        for dimension in SEMAFORO_DIMENSIONES:
            _pregunta_unica(seccion, orden, f'{dimension} — Semáforo', SEMAFORO_OPCIONES, obligatoria=False)
            orden += 1
            for subpregunta in SEMAFORO_SUBPREGUNTAS_ABIERTAS:
                _pregunta_abierta(seccion, orden, f'{dimension} — {subpregunta}', obligatoria=False)
                orden += 1

        # 5 — Matriz de responsabilidades. No obligatoria: exigir las 48 celdas (12 procesos × 4
        # columnas) bloquearía el envío si algún proceso queda sin discutir en la sesión.
        seccion = _seccion(instrumento, 5, '4. Matriz de responsabilidades: situación actual y propuesta')
        _pregunta_matriz(
            seccion, 1,
            'Para cada proceso, indique quién lo hace hoy, quién debería liderarlo, quién debe '
            'participar y quién debería validarlo. Los desacuerdos sobre liderazgo o validación '
            'deben registrarse como asuntos para decisión institucional, no forzarse a consenso.',
            RESPONSABILIDADES_PROCESOS, RESPONSABILIDADES_COLUMNAS, obligatoria=False,
        )

        # 6 — Análisis de coherencia académica: 3 componentes, cada uno con matriz + 3 abiertas.
        # No obligatoria por el mismo motivo que la sección 5 — un departamento puede no tener los
        # tres componentes listos para comparar.
        seccion = _seccion(
            instrumento, 6, '5. Análisis de coherencia académica: tres componentes representativos',
        )
        orden = 1
        for numero_componente in (1, 2, 3):
            _pregunta_matriz(
                seccion, orden,
                f'Componente {numero_componente} — seleccione una asignatura o componente '
                'disciplinar relevante y compárelo entre programas/modalidades.',
                COHERENCIA_VARIABLES, COHERENCIA_COLUMNAS, obligatoria=False,
            )
            orden += 1
            for subpregunta in COHERENCIA_PREGUNTAS_ABIERTAS:
                _pregunta_abierta(
                    seccion, orden, f'Componente {numero_componente} — {subpregunta}', obligatoria=False,
                )
                orden += 1

        # 7 — Mapa de capacidades profesorales (filas libres, prellenadas generosamente)
        seccion = _seccion(instrumento, 7, '6. Mapa de capacidades profesorales')
        _pregunta_matriz(
            seccion, 1,
            'Registre cada profesor(a) del departamento. Pregunta orientadora: ¿tenemos los '
            'perfiles y capacidades que necesitamos para enseñar lo que nuestros currículos '
            'declaran que deben aprender los estudiantes?',
            CAPACIDADES_FILAS, CAPACIDADES_COLUMNAS, obligatoria=False,
        )

        # 8 — Síntesis ejecutiva para la reunión institucional
        seccion = _seccion(instrumento, 8, '7. Síntesis ejecutiva para la reunión institucional')
        for i, texto in enumerate(SINTESIS_EJECUTIVA, start=1):
            _pregunta_abierta(seccion, i, texto)

        # 9 — Asuntos para decisión institucional (filas libres)
        seccion = _seccion(instrumento, 9, '8. Asuntos para decisión institucional')
        _pregunta_matriz(
            seccion, 1, 'Registre cada asunto que requiera decisión institucional.',
            ASUNTOS_FILAS, ASUNTOS_COLUMNAS, obligatoria=False,
        )

        # 10 — Compromisos inmediatos (filas libres)
        seccion = _seccion(instrumento, 10, '9. Compromisos inmediatos')
        _pregunta_matriz(
            seccion, 1, 'Registre cada compromiso inmediato acordado en la sesión.',
            COMPROMISOS_FILAS, COMPROMISOS_COLUMNAS, obligatoria=False,
        )

        # 11 — Cierre
        _seccion(
            instrumento, 11, 'Principio orientador',
            tipo=SeccionInstrumento.TIPO_CONTENIDO, contenido=PRINCIPIO_ORIENTADOR,
        )

        self.stdout.write(self.style.SUCCESS(
            f'Instrumento "{instrumento.nombre}" ({instrumento.slug}) cargado/actualizado.'
        ))
