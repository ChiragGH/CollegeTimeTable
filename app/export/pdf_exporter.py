"""
PDF export (reportlab).

One landscape-A4 document per view kind:

* **Page 1 — audit summary**: session metadata, conflict verdict, the
  full conflict table, and any unscheduled sessions.  A reader never
  has to cross-reference another file to trust the timetable.
* **One page per entity**: the weekly grid with
  - practical blocks drawn as one cell spanning their period columns
    (reportlab ``SPAN``),
  - parallel G1/G2 practicals shown as two labelled entries in the
    same cell,
  - colour-coded activities and a legend,
  - conflicted cells boxed in red with a ``CONFLICT`` prefix.

Grid CSV/XLSX/PDF all consume the same :mod:`app.export.views` models,
so the three formats never disagree.
"""

from html import escape
from pathlib import Path
from typing import List, Optional, Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.export.conflicts import ConflictReport
from app.export.context import ExportContext
from app.export.grid import COL_LUNCH, GRID_COLUMNS, PERIOD_TIMES, lunch_label, LUNCH_START, LUNCH_END, LUNCH_AFTER_PERIOD
from app.export.views import (
    ACTIVITY_TAGS,
    GridCell,
    GridView,
    VIEW_CLASS,
    VIEW_TITLES,
)

# ----------------------------------------------------------------------
# Page geometry & palette
# ----------------------------------------------------------------------

PAGE_SIZE = landscape(A4)          # 841.89 x 595.27 pt
MARGIN = 16 * mm

DAY_COL_W = 64
LUNCH_COL_W = 26
PERIOD_COL_W = (PAGE_SIZE[0] - 2 * MARGIN - DAY_COL_W - LUNCH_COL_W) / 7.0

INK = colors.HexColor("#1F3864")
GRID_LINE = colors.HexColor("#BFBFBF")
DAY_FILL = colors.HexColor("#D9E1F2")
LUNCH_FILL = colors.HexColor("#F2F2F2")
FREE_FILL = colors.HexColor("#FAFAFA")
CONFLICT_FILL = colors.HexColor("#FFC7CE")
CONFLICT_EDGE = colors.HexColor("#C00000")

ACTIVITY_COLORS = {
    "LECTURE": colors.HexColor("#DDEBF7"),
    "PRACTICAL": colors.HexColor("#E2EFDA"),
    "WORKSHOP": colors.HexColor("#FCE4D6"),
    "DRAWING": colors.HexColor("#E4DFEC"),
    "PROJECT": colors.HexColor("#FFF2CC"),
    "TRAINING": colors.HexColor("#EDEDED"),
}

S_TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=15,
                         leading=19, textColor=INK, spaceAfter=2)
S_SUB = ParagraphStyle("sub", fontName="Helvetica-Oblique", fontSize=8.5,
                       leading=11, textColor=colors.HexColor("#595959"))
S_SMALL = ParagraphStyle("small", fontName="Helvetica", fontSize=8,
                         leading=10.5, textColor=colors.HexColor("#404040"))
S_HEAD = ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=8.5,
                        leading=10.5, textColor=colors.white)
S_CELL = ParagraphStyle("cell", fontName="Helvetica", fontSize=7.6,
                        leading=9.6, textColor=colors.HexColor("#111111"))
S_CELL_RED = ParagraphStyle("cellRed", parent=S_CELL,
                            textColor=colors.HexColor("#9C0006"),
                            fontName="Helvetica-Bold")
S_NOTE = ParagraphStyle("note", parent=S_CELL, fontName="Helvetica-Oblique",
                        textColor=colors.HexColor("#808080"), fontSize=6.8)
S_CELL_TIGHT = ParagraphStyle("cellTight", parent=S_CELL, fontSize=6.7,
                              leading=8.2)
S_H2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11.5,
                      leading=15, textColor=INK, spaceBefore=10, spaceAfter=4)
S_DAY = ParagraphStyle("day", fontName="Helvetica-Bold", fontSize=9,
                       leading=11, alignment=1)

# reportlab's built-in fonts use WinAnsi encoding — map glyphs it lacks.
_PDF_CHAR_MAP = {"⚠": "!!", "✓": "", "✗": "x", "∥": "||", "…": "..."}


def _pdf_safe(text: str) -> str:
    for bad, good in _PDF_CHAR_MAP.items():
        text = text.replace(bad, good)
    return text.encode("cp1252", "replace").decode("cp1252")


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def export_view_pdf(
    views: Sequence[GridView],
    view_kind: str,
    ctx: ExportContext,
    report: ConflictReport,
    path: Path,
) -> Path:
    """Write one PDF document: audit page + one page per entity."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(path), pagesize=PAGE_SIZE,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=14 * mm, bottomMargin=16 * mm,
        title=f"{VIEW_TITLES[view_kind]} — {ctx.session_id}",
        author=ctx.college_name,
    )

    story: List = []
    _summary_page(story, view_kind, ctx, report, views)
    for view in views:
        story.append(PageBreak())
        _entity_page(story, view, ctx, report)

    doc.build(story, onFirstPage=_make_footer(ctx), onLaterPages=_make_footer(ctx))
    return path


# ----------------------------------------------------------------------
# Page 1 — audit summary
# ----------------------------------------------------------------------

def _summary_page(story, view_kind, ctx, report, views) -> None:
    story.append(Paragraph(_pdf_safe(ctx.college_name), S_SUB))
    story.append(Paragraph(VIEW_TITLES[view_kind], S_TITLE))
    meta = f"Session: {_pdf_safe(ctx.session_id)}"
    if ctx.academic_year:
        meta += f"  ·  Academic Year: {_pdf_safe(ctx.academic_year)}"
    meta += f"  ·  Generated: {ctx.generated_at}"
    story.append(Paragraph(meta, S_SUB))
    story.append(Spacer(1, 6))

    # Times are derived from the live grid constants so this line can
    # never drift out of sync with the actual schedule (12-hour format).
    _periods = sorted(PERIOD_TIMES)
    _morning = [p for p in _periods if p <= LUNCH_AFTER_PERIOD]
    _afternoon = [p for p in _periods if p > LUNCH_AFTER_PERIOD]
    _am = (f"P{_morning[0]}–P{_morning[-1]} "
           f"({PERIOD_TIMES[_morning[0]][0]}–{PERIOD_TIMES[_morning[-1]][1]})")
    _pm = (f"P{_afternoon[0]}–P{_afternoon[-1]} "
           f"({PERIOD_TIMES[_afternoon[0]][0]}–{PERIOD_TIMES[_afternoon[-1]][1]})")
    entity_line = (
        f"{len(views)} {view_kind} schedule(s) in this document · "
        f"times are Monday–Friday, periods {_am}, lunch "
        f"{LUNCH_START}–{LUNCH_END}, {_pm}."
    )
    story.append(Paragraph(entity_line, S_SMALL))
    story.append(Spacer(1, 10))

    # --- Conflict verdict -------------------------------------------------
    if report.is_clean:
        story.append(Paragraph(
            "CONFLICT AUDIT — PASSED", S_H2))
        story.append(Paragraph(
            "No conflicts detected. Every placement passes the hard-constraint "
            "audit: C1 (teacher), C2 (room), C3 (section/group) and C6 "
            "(G1/G2 parallel alignment).", S_SMALL))
    else:
        story.append(Paragraph(
            f"CONFLICT AUDIT — {len(report.conflicts)} CONFLICT(S) FOUND", S_H2))
        story.append(_conflict_table(report))
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "The affected cells are flagged in red on the pages that follow.",
            S_SMALL))

    # --- Unscheduled sessions --------------------------------------------
    if report.unscheduled:
        story.append(Paragraph(
            f"UNSCHEDULED SESSIONS ({len(report.unscheduled)}) — "
            f"these are NOT on any timetable", S_H2))
        rows = [[Paragraph(_pdf_safe(h), S_HEAD) for h in
                 ["Assignment", "Subject", "Sec", "Grp", "Activity", "Reasons"]]]
        for u in report.unscheduled:
            rows.append([
                Paragraph(_pdf_safe(u.get("assignment_id", "")), S_CELL),
                Paragraph(_pdf_safe(_subject_label(u, ctx)), S_CELL),
                Paragraph(_pdf_safe(u.get("section", "")), S_CELL),
                Paragraph(_pdf_safe(u.get("group", "")), S_CELL),
                Paragraph(_pdf_safe(u.get("activity_type", "")), S_CELL),
                Paragraph(_pdf_safe(" | ".join(u.get("reasons", []))), S_CELL),
            ])
        story.append(_styled_table(rows, _unscheduled_widths()))

    # --- Contents ----------------------------------------------------------
    story.append(Paragraph("CONTENTS", S_H2))
    lines = ", ".join(v.title for v in views) or "(no entities)"
    story.append(Paragraph(_pdf_safe(lines), S_SMALL))


def _conflict_table(report: ConflictReport) -> Table:
    header = ["Type", "Entity", "Day", "Period", "Time", "Details"]
    rows = [[Paragraph(_pdf_safe(h), S_HEAD) for h in header]]
    for c in report.conflicts:
        time_str = (
            f"{PERIOD_TIMES[c.period][0]}-{PERIOD_TIMES[c.period][1]}"
            if c.period in PERIOD_TIMES else "—"
        )
        rows.append([
            Paragraph(_pdf_safe(c.conflict_type), S_CELL_RED),
            Paragraph(_pdf_safe(c.entity_id), S_CELL),
            Paragraph(_pdf_safe(c.day), S_CELL),
            Paragraph(f"P{c.period}" if c.period else "—", S_CELL),
            Paragraph(_pdf_safe(time_str), S_CELL),
            Paragraph(_pdf_safe(c.description), S_CELL),
        ])

    widths = [62, 55, 38, 44, 62, PAGE_SIZE[0] - 2 * MARGIN - 261]
    return _styled_table(rows, widths)


# ----------------------------------------------------------------------
# Entity pages
# ----------------------------------------------------------------------

def _entity_page(story, view: GridView, ctx: ExportContext, report: ConflictReport) -> None:
    story.append(Paragraph(f"{VIEW_TITLES[view.view_kind]} — {_pdf_safe(view.title)}", S_TITLE))
    if view.subtitle:
        story.append(Paragraph(_pdf_safe(view.subtitle), S_SUB))
    stats = (f"Scheduled periods: {view.weekly_periods}    ·    "
             f"Recess {LUNCH_START}-{LUNCH_END}    ·    Generated: {ctx.generated_at}")
    story.append(Paragraph(_pdf_safe(stats), S_SUB))
    story.append(Spacer(1, 8))

    story.append(_grid_table(view))
    story.append(Spacer(1, 6))
    story.append(_legend(view))

    entity_conflicts = report.conflicts_for(view.view_kind, view.entity_id)
    if entity_conflicts:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"⚠ {len(entity_conflicts)} conflict(s) involve this "
            f"{view.view_kind} — see the audit page.",
            ParagraphStyle("warn", parent=S_CELL_RED, fontSize=8.5),
        ))

    for note in view.notes:
        story.append(Spacer(1, 3))
        story.append(Paragraph(f"Note: {_pdf_safe(note)}", S_NOTE))


def _grid_table(view: GridView) -> Table:
    """The weekly grid: header row + five day rows, blocks spanned."""
    merges = _plan_merges(view)
    covered = set()
    for (d, c0), span in merges.items():
        for off in range(1, span):
            covered.add((d, c0 + off))

    data = [[Paragraph("", S_HEAD)] + [_header_cell(c) for c in GRID_COLUMNS]]
    for day_idx in range(5):
        row = [Paragraph(day_name(day_idx), S_DAY)]
        for col_idx in range(len(GRID_COLUMNS)):
            if GRID_COLUMNS[col_idx] == COL_LUNCH:
                row.append(_lunch_cell())
                continue
            if (day_idx, col_idx) in covered:
                row.append("")   # hidden inside a SPAN
                continue
            row.append(
                _cell_flowables(
                    view.cell(day_idx, col_idx),
                    style=S_CELL_TIGHT if view.view_kind == VIEW_CLASS else S_CELL,
                )
            )
        data.append(row)

    col_widths = [DAY_COL_W] + [
        LUNCH_COL_W if c == COL_LUNCH else PERIOD_COL_W for c in GRID_COLUMNS
    ]

    table = Table(
        data, colWidths=col_widths,
        repeatRows=1,  # repeat the period header if the grid splits
    )
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, GRID_LINE),
        ("BOX", (0, 0), (-1, -1), 1.1, INK),
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("VALIGN", (0, 1), (0, -1), "CENTER"),
        ("BACKGROUND", (0, 1), (0, -1), DAY_FILL),
        # Lunch column shading, header excluded (already dark)
        ("BACKGROUND", (5, 1), (5, -1), LUNCH_FILL),
        ("TOPPADDING", (0, 1), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 2),
    ]

    # Activity colours + conflict emphasis, cell by cell.
    for day_idx in range(5):
        r = day_idx + 1
        for col_idx in range(len(GRID_COLUMNS)):
            if GRID_COLUMNS[col_idx] == COL_LUNCH:
                continue
            c = col_idx + 1  # +1 for the Day column
            cell = view.cell(day_idx, col_idx)
            if (day_idx, col_idx) in merges:
                span = merges[(day_idx, col_idx)]
                style.append(("SPAN", (c, r), (c + span - 1, r)))
                style.append(("BACKGROUND", (c, r), (c + span - 1, r),
                              _cell_bg(cell)))
                if cell.conflict:
                    style.append(("BOX", (c, r), (c + span - 1, r), 1.2,
                                  CONFLICT_EDGE))
                continue
            if cell.is_empty:
                style.append(("BACKGROUND", (c, r), (c, r), FREE_FILL))
                continue
            style.append(("BACKGROUND", (c, r), (c, r), _cell_bg(cell)))
            if cell.conflict:
                style.append(("BOX", (c, r), (c, r), 1.2, CONFLICT_EDGE))

    table.setStyle(TableStyle(style))
    return table


def _header_cell(col: str) -> Paragraph:
    if col == COL_LUNCH:
        letters = "<br/>".join(COL_LUNCH)
        return Paragraph(f"<font size=7>{letters}</font>", S_HEAD)
    p = int(col)
    start, end = PERIOD_TIMES[p]
    return Paragraph(f"P{p}<br/><font size=6.5>{start}-{end}</font>", S_HEAD)


def _lunch_cell() -> Paragraph:
    letters = "<br/>".join(lunch_label().split()[0])   # L U N C H
    return Paragraph(f"<font size=7>{letters}</font>", S_NOTE)


def _cell_flowables(cell: GridCell, style: ParagraphStyle = None) -> List:
    """Paragraphs for one cell — every entry, every covered column of
    unmerged blocks (overlapping blocks repeat, nothing is hidden).
    Multiple entries get a thin divider so stacked activities read as
    distinct bookings."""
    base_style = style or S_CELL
    real_entries = [e for e in cell.entries if not e.is_note]
    flow: List = []
    for e in cell.entries:
        lines = [_pdf_safe(l) for l in e.lines if l]
        if not lines:
            continue
        if flow and not e.is_note:
            flow.append(Spacer(1, 1.5))
            flow.append(HRFlowable(
                width="92%", thickness=0.4, color=GRID_LINE,
                spaceBefore=0, spaceAfter=1.5,
            ))
        body = f"<b>{escape(lines[0])}</b>"
        if len(lines) > 1:
            body += "<br/>" + "<br/>".join(escape(l) for l in lines[1:])
        if e.conflict:
            body = "CONFLICT<br/>" + body
            flow.append(Paragraph(body, S_CELL_RED))
        elif e.is_note:
            flow.append(Paragraph(body, S_NOTE))
        else:
            flow.append(Paragraph(body, base_style))
    return flow or ""


def _legend(view: GridView) -> Table:
    items = []
    for activity in view.activities_present:
        tag = ACTIVITY_TAGS.get(activity, activity) or "Lecture"
        color = ACTIVITY_COLORS.get(activity, colors.white)
        items.append((tag, color))
    if any(cell.conflict for cell in view.cells.values()):
        items.append(("Conflict", CONFLICT_FILL))

    if not items:
        return Spacer(1, 2)

    cells = [Paragraph(
        f'<font backColor="{_hex(color)}">&nbsp;&nbsp;&nbsp;</font> '
        f"{_pdf_safe(tag)}", S_SMALL)
        for tag, color in items]
    t = Table([cells], colWidths=[110] * len(cells))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return t


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _plan_merges(view: GridView) -> dict:
    """Mergeable block starts ``(day_idx, col_idx) → span`` — same rule
    as the XLSX exporter: a block merges only when every covered cell
    holds entries from that placement alone; overlapping blocks repeat
    their content per column instead (nothing hidden)."""
    merges = {}
    for (day_idx, col_idx), cell in view.cells.items():
        for b in cell.blocks:
            if not b.is_start or b.span <= 1:
                continue
            safe = True
            for offset in range(b.span):
                cov = view.cell(day_idx, col_idx + offset)
                if any(
                    e.placement_id != b.placement_id
                    for e in cov.entries
                    if not e.is_note
                ):
                    safe = False
                    break
            if safe:
                merges[(day_idx, col_idx)] = b.span
    return merges


def _cell_bg(cell: GridCell) -> colors.Color:
    if cell.conflict:
        return CONFLICT_FILL
    for e in cell.entries:
        if not e.is_note:
            return ACTIVITY_COLORS.get(e.activity, colors.white)
    return FREE_FILL


def _hex(color: colors.Color) -> str:
    r, g, b = int(color.red * 255), int(color.green * 255), int(color.blue * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def _styled_table(rows, widths) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID_LINE),
        ("BOX", (0, 0), (-1, -1), 1, INK),
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F5F7FB")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def day_name(idx: int) -> str:
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"][idx]


def _unscheduled_widths():
    total = PAGE_SIZE[0] - 2 * MARGIN
    return [70, 200, 34, 34, 60, total - 398]


def _subject_label(u: dict, ctx: ExportContext) -> str:
    sid = u.get("subject_id", "")
    return f"{sid} {ctx.subject_name(sid)}" if sid else ""


def _make_footer(ctx: ExportContext):
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#808080"))
        canvas.drawString(
            MARGIN, 10 * mm,
            _pdf_safe(f"{ctx.college_name} — {ctx.session_id} — "
                      f"generated {ctx.generated_at} • by CRG"),
        )
        canvas.drawRightString(
            PAGE_SIZE[0] - MARGIN, 10 * mm,
            f"Page {canvas.getPageNumber()}",
        )
        canvas.restoreState()
    return footer
