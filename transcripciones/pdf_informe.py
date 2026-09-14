"""PDF de un InformeTranscripcion — capa de presentación 100% determinística con reportlab,
directamente desde `informe.resultado` y la transcripción ya guardada, sin ninguna llamada
externa. Mismo espíritu que analitica/pdf_presentacion.py (la alternativa confiable, sin depender
de que un LLM arme bien un documento), pero mucho más simple: acá no hay gráficos que dibujar,
solo prosa, citas y el anexo de la transcripción completa."""
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
)

INSTITUCIONAL = colors.HexColor('#0f3d3e')
ACENTO = colors.HexColor('#1c7c73')
TINTA = colors.HexColor('#1a1a1a')
TINTA_SEC = colors.HexColor('#5c5c5c')


def _estilos():
    base = getSampleStyleSheet()
    return {
        'portada_titulo': ParagraphStyle(
            'portada_titulo', parent=base['Title'], fontName='Helvetica-Bold', fontSize=26,
            textColor=colors.white, leading=32, alignment=TA_CENTER,
        ),
        'portada_lede': ParagraphStyle(
            'portada_lede', fontName='Helvetica', fontSize=11, textColor=colors.HexColor('#cfe8e5'),
            leading=16, alignment=TA_CENTER, spaceBefore=14,
        ),
        'h1': ParagraphStyle('h1', fontName='Helvetica-Bold', fontSize=16, textColor=INSTITUCIONAL,
                              spaceBefore=6, spaceAfter=8),
        'h2': ParagraphStyle('h2', fontName='Helvetica-Bold', fontSize=12, textColor=TINTA,
                              leading=15, spaceAfter=5),
        'body': ParagraphStyle('body', fontName='Helvetica', fontSize=9.5, textColor=TINTA,
                                leading=13.5, spaceAfter=8),
        'cita': ParagraphStyle('cita', fontName='Helvetica-Oblique', fontSize=9, textColor=TINTA_SEC,
                                leading=13, leftIndent=14, spaceAfter=5),
        'meta': ParagraphStyle('meta', fontName='Helvetica-Oblique', fontSize=8, textColor=TINTA_SEC),
        'transcripcion': ParagraphStyle('transcripcion', fontName='Helvetica', fontSize=8.5,
                                         textColor=TINTA, leading=12, spaceAfter=4),
        'vacio': ParagraphStyle('vacio', fontName='Helvetica-Oblique', fontSize=9, textColor=TINTA_SEC),
    }


def _escapar(texto):
    return (texto or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _portada(informe, estilos):
    def _fondo(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(INSTITUCIONAL)
        canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], fill=1, stroke=0)
        canvas.restoreState()

    contenido = [
        Spacer(1, 8 * cm),
        Paragraph(_escapar(informe.sesion.nombre), estilos['portada_titulo']),
        Paragraph('Informe de sesión transcrita', estilos['portada_lede']),
    ]
    if informe.completado_en:
        fecha = timezone.localtime(informe.completado_en).strftime('%d de %B de %Y, %H:%M')
        contenido.append(Paragraph(fecha, estilos['portada_lede']))
    return contenido, _fondo


def _fondo_normal(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor('#f4f7f6'))
    canvas.rect(0, 0, doc.pagesize[0], 1.4 * cm, fill=1, stroke=0)
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(TINTA_SEC)
    canvas.drawString(2 * cm, 0.6 * cm, 'Informe generado con IA a partir de la transcripción registrada.')
    canvas.drawRightString(doc.pagesize[0] - 2 * cm, 0.6 * cm, f'Página {canvas.getPageNumber()}')
    canvas.restoreState()


def construir_pdf(informe):
    estilos = _estilos()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.6 * cm, bottomMargin=2 * cm,
    )

    story, fondo_portada = _portada(informe, estilos)
    story.append(PageBreak())

    resultado = informe.resultado or {}

    story.append(Paragraph('Resumen ejecutivo', estilos['h1']))
    resumen = resultado.get('resumen_ejecutivo')
    story.append(Paragraph(_escapar(resumen) or '(sin resumen)', estilos['body']))
    story.append(Spacer(1, 6))

    temas = resultado.get('temas_discutidos') or []
    if temas:
        story.append(Paragraph('Temas discutidos', estilos['h2']))
        story.append(Paragraph(_escapar(' · '.join(temas)), estilos['body']))
        story.append(Spacer(1, 6))

    story.append(HRFlowable(width='100%', color=colors.HexColor('#dcdcdc'), thickness=0.6))
    story.append(Spacer(1, 10))

    hallazgos = resultado.get('hallazgos') or []
    if hallazgos:
        story.append(Paragraph('Hallazgos', estilos['h1']))
        for hallazgo in hallazgos:
            story.append(Paragraph(_escapar(hallazgo.get('titulo')), estilos['h2']))
            story.append(Paragraph(_escapar(hallazgo.get('descripcion')), estilos['body']))
            for cita in hallazgo.get('citas') or []:
                story.append(Paragraph(f'“{_escapar(cita)}”', estilos['cita']))
            story.append(Spacer(1, 6))
    else:
        story.append(Paragraph('Este informe todavía no tiene hallazgos.', estilos['vacio']))

    story.append(PageBreak())
    story.append(Paragraph('Anexo — transcripción completa', estilos['h1']))
    fragmentos = list(informe.sesion.fragmentos.order_by('secuencia'))
    if fragmentos:
        for fragmento in fragmentos:
            prefijo = f'<b>{_escapar(fragmento.hablante)}:</b> ' if fragmento.hablante else ''
            story.append(Paragraph(prefijo + _escapar(fragmento.texto), estilos['transcripcion']))
    else:
        story.append(Paragraph('(sin fragmentos registrados)', estilos['vacio']))

    def _on_page(canvas, doc_):
        if doc_.page == 1:
            fondo_portada(canvas, doc_)
        else:
            _fondo_normal(canvas, doc_)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buffer.getvalue()


def construir_pdf_response(informe):
    pdf_bytes = construir_pdf(informe)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{informe.sesion.slug}-informe-{informe.id}.pdf"'
    return response
