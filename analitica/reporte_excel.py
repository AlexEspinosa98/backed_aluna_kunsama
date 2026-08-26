"""Exporta el resultado completo de una jornada a un .xlsx — mismo formato validado a mano
contra datos reales: Resumen, Índice, Participantes, Mesas, y una hoja por MOMENTO (no por
pregunta) con todas sus preguntas apiladas, cada una con su caracterización (conteos/porcentajes
vía fórmulas, no cifras pegadas) y el detalle completo de cada respuesta. 100% determinístico,
sin IA — reusa `_estadisticas_pregunta` (analysis.py), la misma fuente de verdad que ya usan el
pipeline local, el análisis vía OpenAI y `estadisticas-preguntas`, así que las cifras nunca
pueden desalinearse de las que se ven ahí. Deliberadamente NO filtra por `momento.activo`: una
jornada cerrada, con todos sus momentos desactivados, es justo cuando más se necesita este
reporte."""
import re
from datetime import datetime
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

from .analysis import _estadisticas_pregunta

FONT_NAME = 'Arial'
F_TITLE = Font(name=FONT_NAME, size=16, bold=True, color='FFFFFF')
F_SUBTITLE = Font(name=FONT_NAME, size=11, italic=True, color='5B6B72')
F_SECTION = Font(name=FONT_NAME, size=12, bold=True, color='FFFFFF')
F_HEADER = Font(name=FONT_NAME, size=10, bold=True, color='FFFFFF')
F_LABEL = Font(name=FONT_NAME, size=10, bold=True, color='17242A')
F_BODY = Font(name=FONT_NAME, size=10, color='17242A')
F_MUTED = Font(name=FONT_NAME, size=9, italic=True, color='5B6B72')
F_LINK = Font(name=FONT_NAME, size=10, color='1F6F5C', underline='single')

FILL_TITLE = PatternFill('solid', fgColor='1F6F5C')
FILL_SECTION = PatternFill('solid', fgColor='2F6F62')
FILL_HEADER = PatternFill('solid', fgColor='17242A')
FILL_ALT = PatternFill('solid', fgColor='F2F5F4')
FILL_WARN = PatternFill('solid', fgColor='FBEBDA')
FILL_MISSING = PatternFill('solid', fgColor='FDECEC')

THIN = Side(style='thin', color='DCE3E4')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

ALIGN_WRAP = Alignment(wrap_text=True, vertical='top')
ALIGN_CENTER = Alignment(horizontal='center', vertical='center')
ALIGN_LEFT = Alignment(horizontal='left', vertical='center')

TIPO_MOMENTO_LABEL = {'individual': 'Individual', 'mesa': 'Consenso de mesa'}


def _style_title_row(ws: Worksheet, row, text, span):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    c = ws.cell(row=row, column=1, value=text)
    c.font = F_TITLE
    c.fill = FILL_TITLE
    c.alignment = ALIGN_LEFT
    ws.row_dimensions[row].height = 26


def _style_section_row(ws: Worksheet, row, text, span):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    c = ws.cell(row=row, column=1, value=text)
    c.font = F_SECTION
    c.fill = FILL_SECTION
    c.alignment = ALIGN_LEFT
    ws.row_dimensions[row].height = 20


def _style_header_cells(ws: Worksheet, row, col_start, col_end):
    for col in range(col_start, col_end + 1):
        c = ws.cell(row=row, column=col)
        c.font = F_HEADER
        c.fill = FILL_HEADER
        c.alignment = ALIGN_CENTER
        c.border = BORDER


def _safe_sheet_name(base, used):
    base = re.sub(r'[\[\]:*?/\\]', '', base).strip()
    name = base[:31]
    i = 2
    while name in used:
        suffix = f' ({i})'
        name = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(name)
    return name


def generar_excel_jornada(jornada):
    from participantes.models import Participante, Respuesta
    from participantes.utils import agrupar_por_mesa

    momentos = list(jornada.momentos.order_by('orden').prefetch_related('preguntas__opciones'))
    participantes = list(
        Participante.objects.filter(jornada=jornada).order_by('nombre', 'apellido')
    )
    total_participantes = len(participantes)
    mesas_dict, sin_mesa = agrupar_por_mesa(participantes)
    mesas_ordenadas = []
    for numero in sorted(mesas_dict.keys()):
        integrantes = mesas_dict[numero]
        vocero = next((p for p in integrantes if p.es_vocero), None)
        mesas_ordenadas.append({'mesa': numero, 'total_participantes': len(integrantes), 'vocero': vocero})
    total_mesas = len(mesas_ordenadas)

    respuestas_por_momento = {
        m.id: list(
            Respuesta.objects.filter(pregunta__momento=m)
            .select_related('participante')
            .prefetch_related('opciones')
        )
        for m in momentos
    }

    preguntas_flat = []
    for m in momentos:
        for p in sorted(m.preguntas.all(), key=lambda x: x.orden):
            if p.activa:
                preguntas_flat.append({'momento': m, 'pregunta': p})

    wb = Workbook()
    wb.remove(wb.active)
    used_names = set()

    # ---------------- Participantes ----------------
    ws_p = wb.create_sheet(_safe_sheet_name('Participantes', used_names))
    ws_p.sheet_view.showGridLines = False
    ws_p.freeze_panes = 'A3'
    headers_p = ['ID', 'Nombre', 'Apellido', 'Correo institucional', 'Rol', 'Mesa', 'Es vocero', 'Registrado']
    for i, w in enumerate([7, 20, 22, 32, 16, 8, 10, 20], start=1):
        ws_p.column_dimensions[chr(64 + i)].width = w
    _style_title_row(ws_p, 1, 'Participantes registrados', len(headers_p))
    for i, h in enumerate(headers_p, start=1):
        ws_p.cell(row=2, column=i, value=h)
    _style_header_cells(ws_p, 2, 1, len(headers_p))
    row = 3
    part_first_row = row
    for p in participantes:
        vals = [p.id, p.nombre, p.apellido, p.correo_institucional, p.rol.capitalize(),
                p.mesa if p.mesa is not None else '—', 'Sí' if p.es_vocero else 'No',
                timezone.localtime(p.creado_en).strftime('%Y-%m-%d')]
        for i, v in enumerate(vals, start=1):
            c = ws_p.cell(row=row, column=i, value=v)
            c.font = F_BODY
            c.border = BORDER
            if i in (1, 6, 7, 8):
                c.alignment = ALIGN_CENTER
            if (row - part_first_row) % 2 == 1:
                c.fill = FILL_ALT
        row += 1
    part_last_row = max(row - 1, part_first_row)
    COL_ROL_P = 'E'

    # ---------------- Mesas ----------------
    ws_m = wb.create_sheet(_safe_sheet_name('Mesas', used_names))
    ws_m.sheet_view.showGridLines = False
    ws_m.freeze_panes = 'A3'
    headers_m = ['Mesa', 'Total participantes', 'Vocero', 'Correo del vocero']
    for i, w in enumerate([8, 18, 24, 32], start=1):
        ws_m.column_dimensions[chr(64 + i)].width = w
    _style_title_row(ws_m, 1, 'Mesas formadas', len(headers_m))
    for i, h in enumerate(headers_m, start=1):
        ws_m.cell(row=2, column=i, value=h)
    _style_header_cells(ws_m, 2, 1, len(headers_m))
    row = 3
    mesa_first_row = row
    for m in mesas_ordenadas:
        voc = m['vocero']
        vals = [m['mesa'], m['total_participantes'],
                f'{voc.nombre} {voc.apellido}' if voc else 'Sin vocero',
                voc.correo_institucional if voc else '—']
        for i, v in enumerate(vals, start=1):
            c = ws_m.cell(row=row, column=i, value=v)
            c.font = F_BODY
            c.border = BORDER
            if i in (1, 2):
                c.alignment = ALIGN_CENTER
            if not voc:
                c.fill = FILL_WARN
            elif (row - mesa_first_row) % 2 == 1:
                c.fill = FILL_ALT
        row += 1
    mesa_last_row = max(row - 1, mesa_first_row)
    if sin_mesa:
        row += 1
        ws_m.cell(row=row, column=1, value='Sin mesa asignada:').font = F_LABEL
        row += 1
        for p in sin_mesa:
            ws_m.cell(row=row, column=1, value=f'{p.nombre} {p.apellido} ({p.correo_institucional})').font = F_BODY
            row += 1

    # ---------------- Resumen ----------------
    ws = wb.create_sheet(_safe_sheet_name('Resumen', used_names))
    ws.sheet_view.showGridLines = False
    for col, width in zip('ABCDEF', [40, 16, 16, 16, 16, 50]):
        ws.column_dimensions[col].width = width

    _style_title_row(ws, 1, f'Reporte de resultados — {jornada.nombre}', 6)
    ws.merge_cells('A2:F2')
    ws['A2'] = jornada.descripcion
    ws['A2'].font = F_SUBTITLE
    ws['A2'].alignment = ALIGN_WRAP
    ws.row_dimensions[2].height = 45
    ws['A3'] = (
        f'Fecha del evento: {jornada.fecha_inicio}  ·  Reporte generado: '
        f'{timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")}  ·  Datos en vivo de la '
        f'base de datos — sin IA, cifras 100% determinísticas.'
    )
    ws['A3'].font = F_MUTED

    row = 5
    _style_section_row(ws, row, 'Totales generales', 6)
    row += 1
    ws.cell(row=row, column=1, value='Participantes registrados').font = F_LABEL
    ws.cell(row=row, column=2, value=f"=COUNTA(Participantes!A{part_first_row}:A{part_last_row})").font = F_BODY
    total_part_cell = f'$B${row}'
    ws.cell(row=row, column=2).alignment = ALIGN_CENTER
    row += 1
    ws.cell(row=row, column=1, value='Mesas formadas').font = F_LABEL
    ws.cell(row=row, column=2, value=f"=COUNTA(Mesas!A{mesa_first_row}:A{mesa_last_row})").font = F_BODY
    ws.cell(row=row, column=2).alignment = ALIGN_CENTER
    row += 1
    ws.cell(row=row, column=1, value='Sin mesa asignada').font = F_LABEL
    ws.cell(row=row, column=2, value=len(sin_mesa)).font = F_BODY
    ws.cell(row=row, column=2).alignment = ALIGN_CENTER
    row += 1
    ws.cell(row=row, column=1, value='Momentos en la jornada').font = F_LABEL
    ws.cell(row=row, column=2, value=len(momentos)).font = F_BODY
    ws.cell(row=row, column=2).alignment = ALIGN_CENTER
    row += 1
    ws.cell(row=row, column=1, value='Preguntas totales (activas)').font = F_LABEL
    ws.cell(row=row, column=2, value=len(preguntas_flat)).font = F_BODY
    ws.cell(row=row, column=2).alignment = ALIGN_CENTER
    row += 2

    _style_section_row(ws, row, 'Caracterización de participantes por rol', 6)
    row += 1
    for i, h in enumerate(['Rol', 'Cantidad', '% del total'], start=1):
        ws.cell(row=row, column=i, value=h)
    _style_header_cells(ws, row, 1, 3)
    row += 1
    roles_count = {}
    for p in participantes:
        roles_count[p.rol.capitalize()] = roles_count.get(p.rol.capitalize(), 0) + 1
    role_first_row = row
    for rol, _n in sorted(roles_count.items(), key=lambda x: -x[1]):
        ws.cell(row=row, column=1, value=rol).font = F_BODY
        cnt = ws.cell(
            row=row, column=2,
            value=f"=COUNTIF(Participantes!${COL_ROL_P}${part_first_row}:${COL_ROL_P}${part_last_row},A{row})",
        )
        cnt.font = F_BODY
        cnt.alignment = ALIGN_CENTER
        pct = ws.cell(row=row, column=3, value=f'=IF({total_part_cell}=0,0,B{row}/{total_part_cell})')
        pct.number_format = '0.0%'
        pct.font = F_BODY
        pct.alignment = ALIGN_CENTER
        if (row - role_first_row) % 2 == 1:
            for c in range(1, 4):
                ws.cell(row=row, column=c).fill = FILL_ALT
        row += 1
    row += 1

    _style_section_row(ws, row, 'Momentos de la jornada', 6)
    row += 1
    for i, h in enumerate(['Orden', 'Momento', 'Tipo', 'Preguntas', 'Obligatorias'], start=1):
        ws.cell(row=row, column=i, value=h)
    _style_header_cells(ws, row, 1, 5)
    row += 1
    momento_start = row
    for m in momentos:
        preguntas_m = [p for p in m.preguntas.all() if p.activa]
        n_obl = sum(1 for p in preguntas_m if p.obligatoria)
        ws.cell(row=row, column=1, value=m.orden).alignment = ALIGN_CENTER
        ws.cell(row=row, column=2, value=m.titulo).font = F_BODY
        ws.cell(row=row, column=3, value=TIPO_MOMENTO_LABEL.get(m.tipo, m.tipo)).alignment = ALIGN_CENTER
        ws.cell(row=row, column=4, value=len(preguntas_m)).alignment = ALIGN_CENTER
        ws.cell(row=row, column=5, value=n_obl).alignment = ALIGN_CENTER
        for col in range(1, 6):
            ws.cell(row=row, column=col).border = BORDER
            if (row - momento_start) % 2 == 1:
                ws.cell(row=row, column=col).fill = FILL_ALT
        row += 1
    row += 1
    ws.cell(row=row, column=1, value="Ver hoja 'Índice' para saltar directo a cada pregunta.").font = F_MUTED

    # ---------------- Índice ----------------
    ws_idx = wb.create_sheet(_safe_sheet_name('Índice', used_names))
    ws_idx.sheet_view.showGridLines = False
    ws_idx.freeze_panes = 'A3'
    headers_idx = ['#', 'Momento', 'Tipo momento', 'Pregunta', 'Tipo pregunta', 'Obligatoria', 'Respuestas', 'Ir a la pregunta']
    for col, w in zip('ABCDEFGH', [5, 26, 14, 55, 12, 12, 12, 16]):
        ws_idx.column_dimensions[col].width = w
    _style_title_row(ws_idx, 1, f'Índice de preguntas ({len(preguntas_flat)})', len(headers_idx))
    for i, h in enumerate(headers_idx, start=1):
        ws_idx.cell(row=2, column=i, value=h)
    _style_header_cells(ws_idx, 2, 1, len(headers_idx))
    idx_row = 3

    # ---------------- una hoja por momento, con todas sus preguntas apiladas ----------------
    n = 0
    for m in momentos:
        preguntas_m = sorted([p for p in m.preguntas.all() if p.activa], key=lambda x: x.orden)
        if not preguntas_m:
            continue
        is_mesa = m.tipo == 'mesa'
        universo = total_mesas if is_mesa else total_participantes

        titulo_limpio = re.sub(r'\s+', ' ', m.titulo).strip()
        sheet_title = _safe_sheet_name(f'M{m.orden} {titulo_limpio}', used_names)
        wsp = wb.create_sheet(sheet_title)
        wsp.sheet_view.showGridLines = False
        ncols = 6
        for col, w in zip('ABCDEF', [24, 30, 14, 12, 30, 20]):
            wsp.column_dimensions[col].width = w

        _style_title_row(wsp, 1, m.titulo, ncols)
        row = 2
        meta_momento = (
            f"Tipo: {TIPO_MOMENTO_LABEL.get(m.tipo, m.tipo)}  ·  {len(preguntas_m)} preguntas  ·  "
            f"Universo: {universo} ({'mesas' if is_mesa else 'participantes'})"
        )
        wsp.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
        wsp.cell(row=row, column=1, value=meta_momento).font = F_MUTED
        row += 1
        back_top = wsp.cell(row=row, column=1, value='← Volver al índice')
        back_top.hyperlink = f"#'{ws_idx.title}'!A1"
        back_top.font = F_LINK
        row += 2

        for p in preguntas_m:
            n += 1
            block_start_row = row
            stats = _estadisticas_pregunta(p)
            total_resp = stats.get('total_respuestas', 0)
            opciones = list(p.opciones.all()) if p.tipo in ('unica', 'multiple') else []

            wsp.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
            qc = wsp.cell(row=row, column=1, value=f'Pregunta {p.orden} — {p.texto}')
            qc.font = Font(name=FONT_NAME, size=12, bold=True, color='17242A')
            qc.alignment = ALIGN_WRAP
            wsp.row_dimensions[row].height = 30
            row += 1

            meta = f"Tipo: {p.tipo}  ·  Obligatoria: {'Sí' if p.obligatoria else 'No'}"
            wsp.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
            wsp.cell(row=row, column=1, value=meta).font = F_MUTED
            row += 1

            _style_section_row(wsp, row, 'Caracterización', ncols)
            row += 1

            if opciones:
                for i, h in enumerate(['Opción', 'Conteo', '% sobre respuestas'], start=1):
                    wsp.cell(row=row, column=i, value=h)
                _style_header_cells(wsp, row, 1, 3)
                row += 1
                first_opt_row = row
                for op in sorted(opciones, key=lambda o: o.orden):
                    wsp.cell(row=row, column=1, value=op.texto).font = F_BODY
                    wsp.cell(row=row, column=1).border = BORDER
                    row += 1
                last_opt_row = row - 1
                row_total_stats = row
                wsp.cell(row=row, column=1, value='Total de respuestas').font = F_LABEL
                row += 1
                wsp.cell(row=row, column=1, value='Cobertura sobre el universo').font = F_LABEL
                row_coverage = row
                row += 1
                row_novacia = None
            else:
                first_opt_row = last_opt_row = None
                row_total_stats = row
                wsp.cell(row=row, column=1, value='Total de respuestas').font = F_LABEL
                row += 1
                wsp.cell(row=row, column=1, value='Respuestas no vacías').font = F_LABEL
                row_novacia = row
                row += 1
                wsp.cell(row=row, column=1, value='Cobertura sobre el universo').font = F_LABEL
                row_coverage = row
                row += 1

            wsp.cell(row=row, column=1, value='Universo (participantes/mesas esperadas)').font = F_LABEL
            wsp.cell(row=row, column=2, value=universo).font = F_BODY
            wsp.cell(row=row, column=2).alignment = ALIGN_CENTER
            row += 2

            _style_section_row(wsp, row, 'Respuestas registradas', ncols)
            row += 1

            respuestas_de_pregunta = [r for r in respuestas_por_momento[m.id] if r.pregunta_id == p.id]

            if is_mesa:
                resp_por_mesa = {r.mesa: r for r in respuestas_de_pregunta if r.mesa is not None}
                headers_resp = ['Mesa', 'Vocero', 'Respuesta', 'Última actualización']
                for i, h in enumerate(headers_resp, start=1):
                    wsp.cell(row=row, column=i, value=h)
                _style_header_cells(wsp, row, 1, len(headers_resp))
                row += 1
                first_resp_row = row
                for mm in mesas_ordenadas:
                    r = resp_por_mesa.get(mm['mesa'])
                    voc = mm['vocero']
                    voc_name = f'{voc.nombre} {voc.apellido}' if voc else 'Sin vocero'
                    if r:
                        valor = r.texto_libre if p.tipo == 'abierta' else ('; '.join(o.texto for o in r.opciones.all()) or '—')
                        fecha = timezone.localtime(r.actualizado_en).strftime('%Y-%m-%d %H:%M')
                    else:
                        valor, fecha = '', ''
                    wsp.cell(row=row, column=1, value=mm['mesa']).alignment = ALIGN_CENTER
                    wsp.cell(row=row, column=2, value=voc_name).font = F_BODY
                    vc = wsp.cell(row=row, column=3, value=valor)
                    vc.font = F_BODY
                    vc.alignment = ALIGN_WRAP
                    wsp.cell(row=row, column=4, value=fecha).font = F_MUTED
                    for col in range(1, 5):
                        wsp.cell(row=row, column=col).border = BORDER
                        if not r:
                            wsp.cell(row=row, column=col).fill = FILL_MISSING
                        elif (row - first_resp_row) % 2 == 1:
                            wsp.cell(row=row, column=col).fill = FILL_ALT
                    row += 1
                last_resp_row = max(row - 1, first_resp_row)
                resp_col_letter = 'C'
            else:
                resp_por_participante = {r.participante_id: r for r in respuestas_de_pregunta if r.participante_id is not None}
                headers_resp = ['Participante', 'Correo', 'Rol', 'Mesa', 'Respuesta', 'Última actualización']
                for i, h in enumerate(headers_resp, start=1):
                    wsp.cell(row=row, column=i, value=h)
                wsp.column_dimensions['E'].width = 34
                wsp.column_dimensions['F'].width = 20
                _style_header_cells(wsp, row, 1, len(headers_resp))
                row += 1
                first_resp_row = row
                for part in participantes:
                    r = resp_por_participante.get(part.id)
                    if r:
                        valor = r.texto_libre if p.tipo == 'abierta' else ('; '.join(o.texto for o in r.opciones.all()) or '—')
                        fecha = timezone.localtime(r.actualizado_en).strftime('%Y-%m-%d %H:%M')
                    else:
                        valor, fecha = '', ''
                    wsp.cell(row=row, column=1, value=f'{part.nombre} {part.apellido}').font = F_BODY
                    wsp.cell(row=row, column=2, value=part.correo_institucional).font = F_BODY
                    wsp.cell(row=row, column=3, value=part.rol.capitalize()).alignment = ALIGN_CENTER
                    wsp.cell(row=row, column=4, value=part.mesa if part.mesa is not None else '—').alignment = ALIGN_CENTER
                    vc = wsp.cell(row=row, column=5, value=valor)
                    vc.font = F_BODY
                    vc.alignment = ALIGN_WRAP
                    wsp.cell(row=row, column=6, value=fecha).font = F_MUTED
                    for col in range(1, 7):
                        wsp.cell(row=row, column=col).border = BORDER
                        if not r:
                            wsp.cell(row=row, column=col).fill = FILL_MISSING
                        elif (row - first_resp_row) % 2 == 1:
                            wsp.cell(row=row, column=col).fill = FILL_ALT
                    row += 1
                last_resp_row = max(row - 1, first_resp_row)
                resp_col_letter = 'E'

            resp_range = f'${resp_col_letter}${first_resp_row}:${resp_col_letter}${last_resp_row}'
            if first_opt_row:
                for i, r_ in enumerate(range(first_opt_row, last_opt_row + 1)):
                    cnt = wsp.cell(row=r_, column=2, value=f'=COUNTIF({resp_range},$A${r_})')
                    cnt.font = F_BODY
                    cnt.alignment = ALIGN_CENTER
                    cnt.border = BORDER
                    wsp.cell(row=r_, column=1).border = BORDER
                    pct = wsp.cell(row=r_, column=3, value=f'=IF($B${row_total_stats}=0,0,B{r_}/$B${row_total_stats})')
                    pct.number_format = '0.0%'
                    pct.font = F_BODY
                    pct.alignment = ALIGN_CENTER
                    pct.border = BORDER
                    if i % 2 == 1:
                        for c in (1, 2, 3):
                            wsp.cell(row=r_, column=c).fill = FILL_ALT
                wsp.cell(row=row_total_stats, column=2, value=f'=SUM(B{first_opt_row}:B{last_opt_row})').font = F_BODY
                wsp.cell(row=row_total_stats, column=2).alignment = ALIGN_CENTER
            else:
                wsp.cell(row=row_total_stats, column=2, value=f'=COUNTIF({resp_range},"?*")').font = F_BODY
                wsp.cell(row=row_total_stats, column=2).alignment = ALIGN_CENTER
                wsp.cell(row=row_novacia, column=2, value=f'=COUNTIF({resp_range},"?*")').font = F_BODY
                wsp.cell(row=row_novacia, column=2).alignment = ALIGN_CENTER

            cov = wsp.cell(row=row_coverage, column=2, value=(f'=B{row_total_stats}/{universo}' if universo else 0))
            cov.number_format = '0.0%'
            cov.font = F_BODY
            cov.alignment = ALIGN_CENTER

            ws_idx.cell(row=idx_row, column=1, value=n).alignment = ALIGN_CENTER
            ws_idx.cell(row=idx_row, column=2, value=m.titulo).font = F_BODY
            ws_idx.cell(row=idx_row, column=3, value=TIPO_MOMENTO_LABEL.get(m.tipo, m.tipo)).alignment = ALIGN_CENTER
            ws_idx.cell(row=idx_row, column=4, value=p.texto).font = F_BODY
            ws_idx.cell(row=idx_row, column=4).alignment = ALIGN_WRAP
            ws_idx.cell(row=idx_row, column=5, value=p.tipo).alignment = ALIGN_CENTER
            ws_idx.cell(row=idx_row, column=6, value='Sí' if p.obligatoria else 'No').alignment = ALIGN_CENTER
            ws_idx.cell(row=idx_row, column=7, value=total_resp).alignment = ALIGN_CENTER
            link_cell = ws_idx.cell(row=idx_row, column=8, value='Ver pregunta →')
            link_cell.hyperlink = f"#'{sheet_title}'!A{block_start_row}"
            link_cell.font = F_LINK
            link_cell.alignment = ALIGN_CENTER
            for col in range(1, 9):
                ws_idx.cell(row=idx_row, column=col).border = BORDER
                if (idx_row - 3) % 2 == 1:
                    ws_idx.cell(row=idx_row, column=col).fill = FILL_ALT
            idx_row += 1

            row += 1

    order = ['Resumen', ws_idx.title, ws_p.title, ws_m.title]
    rest = [t for t in (s.title for s in wb.worksheets) if t not in order]
    wb._sheets = [wb[t] for t in order + rest]

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def construir_excel_response(jornada):
    contenido = generar_excel_jornada(jornada)
    response = HttpResponse(
        contenido,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    fecha = datetime.now().strftime('%Y%m%d')
    response['Content-Disposition'] = f'attachment; filename="reporte-{jornada.slug}-{fecha}.xlsx"'
    return response
