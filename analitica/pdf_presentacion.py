"""PDF de un Reporte de analítica — capa de presentación 100% determinística: reportlab arma el
documento (portada, resumen ejecutivo, secciones por momento, gráficos reales) directamente desde
`reporte.analisis`, sin ninguna llamada externa ni SVG "a mano" de un LLM. Mismo enfoque de
gráficos ya validado contra datos reales esta sesión (`analitica/presentacion.py` usa OpenAI para
una versión alternativa en HTML; este módulo es la alternativa confiable cuando se necesita un
documento listo para imprimir/entregar sin depender de que un modelo dibuje bien un SVG)."""
import re
from io import BytesIO

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.platypus import (
    HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

PALETA = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#7a5ec9']
TINTA = colors.HexColor('#1a1f24')
TINTA_SEC = colors.HexColor('#5b6670')
INSTITUCIONAL = colors.HexColor('#14384a')
ACENTO = colors.HexColor('#c08a28')
LINEA = colors.HexColor('#d8dbe0')
FONDO_TAG = colors.HexColor('#eef1f3')
FONDO_PAGINA = colors.HexColor('#f4f6f5')

NIVEL_ACUERDO_COLOR = {
    'consenso_fuerte': colors.HexColor('#1baf7a'),
    'consenso_moderado': colors.HexColor('#2a78d6'),
    'tension_estrategica': colors.HexColor('#eb6834'),
    'tema_emergente': colors.HexColor('#7a5ec9'),
    'asunto_pendiente': colors.HexColor('#8c97a3'),
}
NIVEL_ACUERDO_LABEL = {
    'consenso_fuerte': 'Consenso fuerte',
    'consenso_moderado': 'Consenso moderado',
    'tension_estrategica': 'Tensión estratégica',
    'tema_emergente': 'Tema emergente',
    'asunto_pendiente': 'Asunto pendiente',
}
TIPO_MOMENTO_LABEL = {'individual': 'Reflexión individual', 'mesa': 'Consenso de mesa'}

MD_BOLD_RE = re.compile(r'\*\*(.+?)\*\*')


def _md(texto):
    return MD_BOLD_RE.sub(r'<b>\1</b>', texto or '')


def _recortar(texto, n):
    return (texto[:n] + '…') if len(texto) > n else texto


def _estilos():
    base = getSampleStyleSheet()
    return {
        'portada_titulo': ParagraphStyle(
            'portada_titulo', parent=base['Title'], fontName='Helvetica-Bold', fontSize=28,
            textColor=colors.white, leading=34, alignment=TA_CENTER,
        ),
        'portada_lede': ParagraphStyle(
            'portada_lede', parent=base['Normal'], fontName='Helvetica', fontSize=11.5,
            textColor=colors.HexColor('#cfd8dc'), leading=16, alignment=TA_CENTER, spaceBefore=14,
        ),
        'portada_stat_valor': ParagraphStyle(
            'portada_stat_valor', fontName='Helvetica-Bold', fontSize=20, textColor=colors.white,
            alignment=TA_CENTER,
        ),
        'portada_stat_label': ParagraphStyle(
            'portada_stat_label', fontName='Helvetica', fontSize=8.5,
            textColor=colors.HexColor('#a9c2cd'), alignment=TA_CENTER,
        ),
        'eyebrow': ParagraphStyle('eyebrow', fontName='Helvetica-Bold', fontSize=8.5,
                                   textColor=ACENTO, spaceAfter=6),
        'h1': ParagraphStyle('h1', fontName='Helvetica-Bold', fontSize=17, textColor=INSTITUCIONAL,
                              spaceBefore=6, spaceAfter=8),
        'h2': ParagraphStyle('h2', fontName='Helvetica-Bold', fontSize=12, textColor=TINTA,
                              leading=15, spaceAfter=5),
        'kicker': ParagraphStyle('kicker', fontName='Helvetica-Bold', fontSize=8,
                                  textColor=ACENTO, spaceAfter=6),
        'body': ParagraphStyle('body', fontName='Helvetica', fontSize=9.5, textColor=TINTA,
                                leading=13.5, spaceAfter=8),
        'callout': ParagraphStyle('callout', fontName='Helvetica', fontSize=10.5, textColor=TINTA,
                                   leading=15, spaceAfter=9),
        'meta': ParagraphStyle('meta', fontName='Helvetica-Oblique', fontSize=8,
                                textColor=TINTA_SEC),
        'tag': ParagraphStyle('tag', fontName='Helvetica-Bold', fontSize=7.5, textColor=TINTA_SEC),
        'chip': ParagraphStyle('chip', fontName='Helvetica', fontSize=8.5, textColor=TINTA,
                                leading=12),
        'vacio': ParagraphStyle('vacio', fontName='Helvetica-Oblique', fontSize=9,
                                 textColor=TINTA_SEC),
    }


def _pill(texto, estilos, fondo=FONDO_TAG, color_texto=None):
    style = estilos['tag']
    if color_texto:
        style = ParagraphStyle('tag_c', parent=style, textColor=color_texto)
    t = Table([[Paragraph(texto.upper(), style)]])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), fondo),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    return t


def _grafico_barras(items, ancho=440, alto=None):
    alto = alto or max(60, 26 * len(items))
    d = Drawing(ancho, alto)
    bc = HorizontalBarChart()
    bc.x, bc.y = 170, 10
    bc.height, bc.width = alto - 20, ancho - 200
    bc.data = [[it['tamano'] for it in items]]
    bc.categoryAxis.categoryNames = [
        _recortar(it['tema'], 38) + f" — {it['porcentaje']}%" for it in items
    ]
    bc.categoryAxis.labels.fontName = 'Helvetica'
    bc.categoryAxis.labels.fontSize = 7.5
    bc.valueAxis.visible = False
    bc.valueAxis.valueMin = 0
    bc.bars.strokeWidth = 0
    for i in range(len(items)):
        bc.bars[(0, i)].fillColor = colors.HexColor(PALETA[i % len(PALETA)])
    bc.barLabels.fontName = 'Helvetica-Bold'
    bc.barLabels.fontSize = 7.5
    bc.barLabelFormat = '%d'
    bc.barLabels.nudge = 8
    d.add(bc)
    return d


def _grafico_pastel(items, diametro=110):
    d = Drawing(diametro + 220, diametro + 10)
    pie = Pie()
    pie.x, pie.y = 5, 5
    pie.width = pie.height = diametro
    pie.data = [it['tamano'] for it in items]
    pie.labels = None
    pie.sideLabels = False
    for i in range(len(items)):
        pie.slices[i].fillColor = colors.HexColor(PALETA[i % len(PALETA)])
        pie.slices[i].strokeColor = colors.white
        pie.slices[i].strokeWidth = 1.5
    d.add(pie)
    leyenda_x = diametro + 20
    for i, it in enumerate(items):
        y = diametro - 12 - i * 16
        d.add(Rect(leyenda_x, y, 9, 9, fillColor=colors.HexColor(PALETA[i % len(PALETA)]), strokeColor=None))
        etiqueta = _recortar(it['tema'], 48)
        d.add(String(leyenda_x + 14, y + 1, f"{etiqueta} — {it['tamano']} ({it['porcentaje']}%)",
                      fontName='Helvetica', fontSize=7.5, fillColor=TINTA))
    return d


def _bloque_valores(pregunta, estilos):
    metodo = pregunta.get('metodo_valores')
    valores = pregunta.get('valores_caracteristicos') or []
    tipo_g = pregunta.get('tipo_grafica')
    total = pregunta.get('total_respuestas') or 0

    if metodo == 'conteo' and valores:
        items = [
            {'tema': v.get('texto') or '', 'tamano': v.get('conteo', 0),
             'porcentaje': round(v.get('conteo', 0) / total * 100, 1) if total else 0.0}
            for v in valores
        ]
        if any(it['tamano'] for it in items):
            return _grafico_pastel(items) if (tipo_g == 'pastel' and len(items) <= 5) else _grafico_barras(items)
        return Paragraph('Sin datos suficientes para graficar.', estilos['vacio'])

    if metodo == 'bertopic_llm' and valores and all(v.get('tamano') is not None for v in valores):
        items = [{'tema': v.get('tema'), 'tamano': v['tamano'], 'porcentaje': v['porcentaje']} for v in valores]
        return _grafico_pastel(items) if (tipo_g == 'pastel' and len(items) <= 5) else _grafico_barras(items)

    if valores and metodo in ('llm', 'bertopic_sin_clasificar'):
        frases = ' · '.join(
            (v.get('tema') or v.get('texto') or '') for v in valores if (v.get('tema') or v.get('texto'))
        )
        return Paragraph(frases, estilos['chip'])

    return Paragraph('Sin datos suficientes para graficar.', estilos['vacio'])


def _portada(reporte, participacion, estilos):
    stats = [
        (participacion.get('total_participantes'), 'Inscritos'),
        (participacion.get('participantes_que_respondieron'), 'Respondieron'),
        (f"{participacion.get('tasa_participacion', '—')}%", 'Participación'),
        (len((reporte.analisis or {}).get('momentos') or []), 'Momentos'),
    ]
    tabla = Table(
        [[Paragraph(str(v), estilos['portada_stat_valor']) for v, _ in stats],
         [Paragraph(k, estilos['portada_stat_label']) for _, k in stats]],
        colWidths=[110] * 4,
    )
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1c4a61')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#2c6178')),
        ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    return [
        Spacer(1, 6 * cm),
        Paragraph(reporte.jornada.nombre, estilos['portada_titulo']),
        Paragraph('Informe de resultados', estilos['portada_lede']),
        Spacer(1, 1.2 * cm),
        tabla,
        PageBreak(),
    ]


def _fondo_portada(canvas, doc):
    # SimpleDocTemplate no pinta el lienzo completo por sí solo — un Paragraph con texto blanco
    # sin esto queda blanco sobre blanco, invisible. Se pinta la página ANTES de que Platypus
    # dibuje los flowables encima, así que el rectángulo cubre toda la hoja, no solo el área con
    # margen. onFirstPage solo aplica a la portada; el resto del documento queda en blanco normal.
    canvas.saveState()
    canvas.setFillColor(INSTITUCIONAL)
    ancho, alto = doc.pagesize
    canvas.rect(0, 0, ancho, alto, fill=1, stroke=0)
    canvas.restoreState()


def _fondo_normal(canvas, doc):
    pass


def construir_pdf(reporte):
    """Devuelve los bytes del PDF de este `Reporte` — ya `completo`, se arma directo desde
    `reporte.analisis` sin recalcular ni llamar a ningún servicio externo."""
    estilos = _estilos()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
        title=f'{reporte.jornada.nombre} — Informe de resultados',
    )
    flow = []
    analisis = reporte.analisis or {}
    participacion = analisis.get('participacion') or {}

    flow += _portada(reporte, participacion, estilos)

    texto_reporte = reporte.texto_reporte or ''
    if texto_reporte:
        flow.append(Paragraph('SÍNTESIS PARA LA RECTORÍA', estilos['kicker']))
        for parr in [p for p in texto_reporte.split('\n') if p.strip()]:
            flow.append(Paragraph(_md(parr), estilos['callout']))
        flow.append(Spacer(1, 6))
        flow.append(Paragraph(
            f"Reporte {reporte.slug} · modelo {reporte.modelo_usado or '—'}", estilos['meta']))
        flow.append(PageBreak())

    momentos = analisis.get('momentos') or []
    for mi, m in enumerate(momentos, start=1):
        tipo_momento = TIPO_MOMENTO_LABEL.get(m.get('tipo'), m.get('tipo') or '')
        flow.append(HRFlowable(width='100%', thickness=0.5, color=LINEA, spaceBefore=4, spaceAfter=10))
        flow.append(Paragraph(f'MOMENTO {mi} DE {len(momentos)} · {tipo_momento.upper()}', estilos['kicker']))
        flow.append(Paragraph(f'Momento {mi}', estilos['h1']))
        flow.append(Paragraph(_md(m.get('descripcion_general') or ''), estilos['body']))
        flow.append(Spacer(1, 4))

        for p in m.get('preguntas') or []:
            metodo_tag = {
                'bertopic_llm': 'Análisis temático',
                'llm': 'Temas recurrentes',
                'conteo': 'Resultados',
                'bertopic_sin_clasificar': 'Temas identificados',
                'insuficiente': 'Muestra insuficiente',
                'sin_datos': 'Sin respuestas',
            }.get(p.get('metodo_valores'), p.get('metodo_valores') or '')

            pills = [_pill(metodo_tag, estilos)]
            nivel = p.get('nivel_acuerdo')
            if nivel:
                color_nivel = NIVEL_ACUERDO_COLOR.get(nivel, TINTA_SEC)
                pills.append(_pill(NIVEL_ACUERDO_LABEL.get(nivel, nivel), estilos,
                                    fondo=colors.Color(color_nivel.red, color_nivel.green, color_nivel.blue, 0.15),
                                    color_texto=color_nivel))

            bloque = [
                Paragraph(p.get('texto') or f"Pregunta {p.get('pregunta_id', '')}", estilos['h2']),
                Table([pills], style=TableStyle([
                    ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (0, 0), 6),
                ])),
                Spacer(1, 6),
                _bloque_valores(p, estilos),
                Spacer(1, 4),
                Paragraph(
                    _md(p.get('descripcion') or '') +
                    f" <font color='#8c97a3' size=8>({p.get('total_respuestas', 0)} respuestas)</font>",
                    estilos['body']),
                Spacer(1, 12),
            ]
            flow.append(KeepTogether(bloque))

    doc.build(flow, onFirstPage=_fondo_portada, onLaterPages=_fondo_normal)
    return buffer.getvalue()


def construir_pdf_response(reporte):
    pdf_bytes = construir_pdf(reporte)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{reporte.slug}.pdf"'
    return response
