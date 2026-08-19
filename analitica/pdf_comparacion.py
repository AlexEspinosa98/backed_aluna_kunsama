"""Genera los dos PDF de comparación (flujo actual vs. mejorado) a partir de los resultados de
`analitica.topicos_experimental.comparar_pregunta`. Herramienta experimental, ver ese módulo."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

RELACION_LABELS = {
    'consenso_fuerte': 'Consenso fuerte — los temas dicen básicamente lo mismo',
    'consenso_moderado': 'Consenso moderado — coinciden en general, con matices',
    'tension': 'Tensión — los temas se contradicen o proponen cosas opuestas',
    'dispersos': 'Dispersos — los temas hablan de cosas distintas, sin relación clara',
}


def _estilos():
    base = getSampleStyleSheet()
    return {
        'titulo': ParagraphStyle('titulo', parent=base['Title'], spaceAfter=6),
        'subtitulo': ParagraphStyle('subtitulo', parent=base['Normal'], fontSize=10,
                                     textColor='#555555', spaceAfter=18),
        'pregunta': ParagraphStyle('pregunta', parent=base['Heading2'], spaceBefore=14,
                                    spaceAfter=2),
        'meta': ParagraphStyle('meta', parent=base['Normal'], fontSize=9,
                                textColor='#666666', spaceAfter=8),
        'tema': ParagraphStyle('tema', parent=base['Normal'], fontSize=10.5,
                                leftIndent=12, spaceAfter=4),
        'relacion': ParagraphStyle('relacion', parent=base['Normal'], fontSize=10,
                                    leftIndent=12, spaceBefore=4, spaceAfter=10,
                                    textColor='#1c5f9c'),
        'vacio': ParagraphStyle('vacio', parent=base['Normal'], leftIndent=12,
                                 textColor='#999999', spaceAfter=8),
    }


def generar_pdf_actual(resultados, ruta, jornada_nombre):
    est = _estilos()
    doc = SimpleDocTemplate(ruta, pagesize=letter, topMargin=2 * cm, bottomMargin=2 * cm)
    story = [
        Paragraph('Tópicos — flujo ACTUAL (producción)', est['titulo']),
        Paragraph(
            f'{jornada_nombre} · BERTopic con palabras clave crudas (c-TF-IDF), sin cambios · '
            f'{len(resultados)} preguntas',
            est['subtitulo'],
        ),
    ]
    for r in resultados:
        story.append(Paragraph(f"[{r['momento_titulo']}] {r['texto']}", est['pregunta']))
        story.append(Paragraph(f"{r['total_respuestas']} respuestas analizadas", est['meta']))
        if not r['temas_actual']:
            story.append(Paragraph('No se identificaron temas separables.', est['vacio']))
        for i, t in enumerate(r['temas_actual'], start=1):
            palabras = ', '.join(t['palabras_clave'])
            story.append(Paragraph(f"Tema {i} ({t['tamano']} respuestas): {palabras}", est['tema']))
    doc.build(story)


def generar_pdf_mejorado(resultados, ruta, jornada_nombre):
    est = _estilos()
    doc = SimpleDocTemplate(ruta, pagesize=letter, topMargin=2 * cm, bottomMargin=2 * cm)
    story = [
        Paragraph('Tópicos — flujo MEJORADO (experimental)', est['titulo']),
        Paragraph(
            f'{jornada_nombre} · Stopwords ampliadas + tri-términos + etiquetas redactadas por '
            f'LLM sobre respuestas reales + relación entre temas · {len(resultados)} preguntas',
            est['subtitulo'],
        ),
    ]
    for r in resultados:
        story.append(Paragraph(f"[{r['momento_titulo']}] {r['texto']}", est['pregunta']))
        story.append(Paragraph(f"{r['total_respuestas']} respuestas analizadas", est['meta']))
        if not r['temas_mejorado']:
            story.append(Paragraph('No se identificaron temas separables.', est['vacio']))
        for i, t in enumerate(r['temas_mejorado'], start=1):
            story.append(Paragraph(
                f"Tema {i} ({t['tamano']} respuestas, {t['porcentaje']}%): {t['etiqueta']}",
                est['tema'],
            ))
        if r['relacion_mejorado']:
            etiqueta = RELACION_LABELS.get(r['relacion_mejorado'], r['relacion_mejorado'])
            story.append(Paragraph(f"Relación entre los temas: {etiqueta}", est['relacion']))
    doc.build(story)
