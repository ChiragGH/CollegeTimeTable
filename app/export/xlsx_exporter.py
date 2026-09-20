"""
XLSX export (openpyxl).

One workbook per view kind — one sheet per entity plus a trailing
**Conflicts** sheet, so every workbook is self-verifying.

Formatting features:

* merged title/subtitle bands, frozen header, no sheet gridlines;
* **practical blocks merged horizontally** across their period columns
  (a 2-period practical is one tall merged cell; continuation slots
  render empty inside the merge);
* **parallel G1/G2** practicals render as two labelled entries inside
  the same cell;
* colour-coded activities (legend included), grey lunch column with
  vertical text;
* **conflicts are impossible to miss**: red fill + red borders on the
  offending cells and a fully detailed Conflicts sheet;
* landscape print setup, fit-to-width.
"""

from pathlib import Path
from typing import Sequence

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from app.models.enums import ActivityType

from app.export.conflicts import ConflictReport
from app.export.context import ExportContext
from app.export.grid import COL_LUNCH, GRID_COLUMNS, PERIOD_TIMES, lunch_label
from app.export.views import (
    ACTIVITY_TAGS,
    GridCell,
    GridView,
    VIEW_TITLES,
)

# ----------------------------------------------------------------------
# Style palette
# ----------------------------------------------------------------------

HEADER_FILL = PatternFill("solid", start_color="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
TITLE_FONT = Font(bold=True, size=14, color="1F3864")
SUBTITLE_FONT = Font(italic=True, size=10, color="595959")
STATS_FONT = Font(size=9, color="595959")
DAY_FILL = PatternFill("solid", start_color="D9E1F2")
DAY_FONT = Font(bold=True, size=10)
LUNCH_FILL = PatternFill("solid", start_color="F2F2F2")
LUNCH_FONT = Font(italic=True, size=9, color="808080")
FREE_FILL = PatternFill("solid", start_color="FAFAFA")
NOTE_FONT = Font(italic=True, size=9, color="BF8F00")
LEGEND_FONT = Font(size=9)

CONFLICT_FILL = PatternFill("solid", start_color="FFC7CE")
CONFLICT_FONT = Font(bold=True, color="9C0006", size=9)
CONFLICT_BORDER = Border(*[
    Side(style="medium", color="C00000"),
] * 4)

ACTIVITY_FILLS = {
    ActivityType.LECTURE.value: PatternFill("solid", start_color="DDEBF7"),
    ActivityType.PRACTICAL.value: PatternFill("solid", start_color="E2EFDA"),
    ActivityType.WORKSHOP.value: PatternFill("solid", start_color="FCE4D6"),
    ActivityType.DRAWING.value: PatternFill("solid", start_color="E4DFEC"),
    ActivityType.PROJECT.value: PatternFill("solid", start_color="FFF2CC"),
    ActivityType.TRAINING.value: PatternFill("solid", start_color="EDEDED"),
}

THIN_GREY = Side(style="thin", color="BFBFBF")
CELL_BORDER = Border(left=THIN_GREY, right=THIN_GREY, top=THIN_GREY, bottom=THIN_GREY)

CELL_FONT = Font(size=9)
CELL_ALIGN = Alignment(horizontal="left", vertical="center", wrap_text=True)
CENTER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)

#: Grid geometry — column A is the day gutter, then the 8 grid columns.
N_COLS = 1 + len(GRID_COLUMNS)
HEADER_ROW = 4
FIRST_DAY_ROW = 5
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def export_view_xlsx(
    views: Sequence[GridView],
    view_kind: str,
    ctx: ExportContext,
    report: ConflictReport,
    path: Path,
) -> Path:
    """Write one workbook containing every entity of the view kind."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    used_names = set()
    for view in views:
        ws = wb.create_sheet(title=_sheet_name(view, used_names))
        _render_sheet(ws, view, ctx)

    _render_conflicts_sheet(wb.create_sheet(title="Conflicts"), ctx, report)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ----------------------------------------------------------------------
# Entity sheet
# ----------------------------------------------------------------------

def _render_sheet(ws, view: GridView, ctx: ExportContext) -> None:
    ws.sheet_view.showGridLines = False

    # Column widths: A = day gutter, B..I = grid columns.
    ws.column_dimensions["A"].width = 12
    for col_idx in range(2, N_COLS + 1):
        letter = get_column_letter(col_idx)
        if GRID_COLUMNS[col_idx - 2] == COL_LUNCH:
            ws.column_dimensions[letter].width = 4.5
        else:
            ws.column_dimensions[letter].width = 17

    _title_block(ws, view, ctx)
    _header_row(ws)
    _day_rows(ws, view)
    _legend_block(ws, view)
    _page_setup(ws)


def _title_block(ws, view: GridView, ctx: ExportContext) -> None:
    last = get_column_letter(N_COLS)
    ws.merge_cells(f"A1:{last}1")
    ws.merge_cells(f"A2:{last}2")
    ws.merge_cells(f"A3:{last}3")

    ws["A1"] = f"{VIEW_TITLES[view.view_kind]} — {view.title}"
    ws["A1"].font = TITLE_FONT
    ws["A1"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 24

    subtitle = view.subtitle or ""
    ws["A2"] = subtitle
    ws["A2"].font = SUBTITLE_FONT
    ws["A2"].alignment = Alignment(vertical="center")
    ws.row_dimensions[2].height = 15

    stats = f"Scheduled periods: {view.weekly_periods}    Generated: {ctx.generated_at}"
    ws["A3"] = stats
    ws["A3"].font = STATS_FONT
    ws["A3"].alignment = Alignment(vertical="center")
    ws.row_dimensions[3].height = 13
    ws.row_dimensions[HEADER_ROW].height = 26


def _header_row(ws) -> None:
    ws.cell(row=HEADER_ROW, column=1, value="Day")
    for col_idx, col in enumerate(GRID_COLUMNS, start=2):
        if col == COL_LUNCH:
            label = COL_LUNCH
        else:
            p = int(col)
            start, end = PERIOD_TIMES[p]
            label = f"P{p}\n{start}-{end}"
        ws.cell(row=HEADER_ROW, column=col_idx, value=label)

    for col_idx in range(1, N_COLS + 1):
        cell = ws.cell(row=HEADER_ROW, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = CENTER_ALIGN
        cell.border = CELL_BORDER


def _day_rows(ws, view: GridView) -> None:
    """Render the five day rows, merging practical blocks."""
    merges = _plan_merges(view)
    covered = set()
    for (d, c0), span in merges.items():
        for off in range(1, span):
            covered.add((d, c0 + off))

    for day_idx, day_name in enumerate(DAY_NAMES):
        row = FIRST_DAY_ROW + day_idx
        ws.row_dimensions[row].height = _row_height(view, day_idx, covered)

        day_cell = ws.cell(row=row, column=1, value=day_name)
        day_cell.fill = DAY_FILL
        day_cell.font = DAY_FONT
        day_cell.alignment = CENTER_ALIGN
        day_cell.border = CELL_BORDER

        for col_idx in range(2, N_COLS + 1):
            grid_col = GRID_COLUMNS[col_idx - 2]
            cell = ws.cell(row=row, column=col_idx)
            if grid_col == COL_LUNCH:
                _style_lunch(cell)
                continue

            if (day_idx, col_idx - 2) in covered:
                continue  # hidden inside a merge — styled below

            _write_grid_cell(ws, row, col_idx, view.cell(day_idx, col_idx - 2))

    # Apply merges and style every covered cell so the merged region
    # reads as one continuous coloured block.
    for (day_idx, start_col), span in merges.items():
        row = FIRST_DAY_ROW + day_idx
        grid_cell = view.cell(day_idx, start_col)
        ws.merge_cells(
            start_row=row, start_column=start_col + 2,
            end_row=row, end_column=start_col + span + 1,
        )
        for col_idx in range(start_col + 2, start_col + span + 2):
            c = ws.cell(row=row, column=col_idx)
            c.border = _cell_border(grid_cell)
            c.fill = _cell_fill(grid_cell)

    # Lunch column: one tall merged cell across all day rows.
    lunch_col = GRID_COLUMNS.index(COL_LUNCH) + 2
    ws.merge_cells(
        start_row=FIRST_DAY_ROW, start_column=lunch_col,
        end_row=FIRST_DAY_ROW + len(DAY_NAMES) - 1, end_column=lunch_col,
    )
    ws.cell(row=FIRST_DAY_ROW, column=lunch_col).value = lunch_label()


def _plan_merges(view: GridView) -> dict:
    """
    Find mergeable block starts: ``(day_idx, col_idx) → span``.

    A block may only merge when every covered cell holds entries from
    that placement alone (parallel-pair notes are ignored).  When two
    placements share the block's columns — overlapping sections in the
    class view, or a conflicting placement — the block renders unmerged
    with its content repeated per column, so nothing is ever hidden.
    """
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


def _write_grid_cell(ws, row: int, col_idx: int, cell: GridCell) -> None:
    """Write one grid cell with activity colours and conflict styling.
    Multiple entries are separated by a dotted divider line."""
    texts = [_entry_text(e) for e in cell.entries if e.lines]
    real_count = sum(1 for e in cell.entries if not e.is_note and e.lines)
    if real_count > 1:
        joined = []
        for e in cell.entries:
            if not e.lines:
                continue
            if joined and not e.is_note:
                joined.append("· · · · · · · · · ·")
            joined.append(_entry_text(e))
        text = "\n".join(joined)
    else:
        text = "\n".join(texts)
    cell_obj = ws.cell(row=row, column=col_idx, value=text or None)

    cell_obj.font = CONFLICT_FONT if cell.conflict else CELL_FONT
    cell_obj.alignment = CELL_ALIGN
    cell_obj.border = _cell_border(cell)
    cell_obj.fill = _cell_fill(cell)


def _cell_fill(cell: GridCell) -> PatternFill:
    if cell.conflict:
        return CONFLICT_FILL
    for e in cell.entries:
        if not e.is_note:
            return ACTIVITY_FILLS.get(
                e.activity, ACTIVITY_FILLS[ActivityType.LECTURE.value],
            )
    return FREE_FILL


def _cell_border(cell: GridCell) -> Border:
    return CONFLICT_BORDER if cell.conflict else CELL_BORDER


def _style_lunch(cell) -> None:
    cell.fill = LUNCH_FILL
    cell.font = LUNCH_FONT
    cell.alignment = Alignment(
        horizontal="center", vertical="center", textRotation=90,
    )
    cell.border = CELL_BORDER


def _row_height(view: GridView, day_idx: int, covered: set = frozenset()) -> float:
    """Taller rows where cells carry more text lines."""
    max_lines = 1
    for col_idx in range(len(GRID_COLUMNS)):
        if (day_idx, col_idx) in covered:
            continue  # hidden inside a merge
        cell = view.cell(day_idx, col_idx)
        if cell.is_empty:
            continue
        lines = sum(
            len(e.lines) + (1 if e.conflict else 0) for e in cell.entries
        )
        real_count = sum(1 for e in cell.entries if not e.is_note)
        if real_count > 1:
            lines += real_count - 1  # divider lines between entries
        max_lines = max(max_lines, lines)
    return max(30, 12 * max_lines + 10)


def _legend_block(ws, view: GridView) -> None:
    """Colour-key for the activities on this sheet, plus notes."""
    row = FIRST_DAY_ROW + len(DAY_NAMES) + 1
    ws.cell(row=row, column=1, value="Legend:").font = Font(bold=True, size=9)

    col = 2
    for activity in view.activities_present:
        tag = ACTIVITY_TAGS.get(activity, activity) or "Lecture"
        c = ws.cell(row=row, column=col, value=tag)
        c.fill = ACTIVITY_FILLS.get(activity, FREE_FILL)
        c.font = LEGEND_FONT
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = CELL_BORDER
        col += 1

    if any(cell.conflict for cell in view.cells.values()):
        c = ws.cell(row=row, column=col, value="Conflict")
        c.fill = CONFLICT_FILL
        c.font = CONFLICT_FONT
        c.border = CONFLICT_BORDER
        c.alignment = Alignment(horizontal="center", vertical="center")

    note_row = row + 1
    for note in view.notes:
        ws.merge_cells(
            start_row=note_row, start_column=1,
            end_row=note_row, end_column=N_COLS,
        )
        ws.cell(row=note_row, column=1, value=f"Note: {note}").font = NOTE_FONT
        note_row += 1


# ----------------------------------------------------------------------
# Conflicts sheet
# ----------------------------------------------------------------------

def _render_conflicts_sheet(ws, ctx: ExportContext, report: ConflictReport) -> None:
    ws.sheet_view.showGridLines = False
    widths = {"A": 12, "B": 12, "C": 10, "D": 8, "E": 13, "F": 80}
    for letter, width in widths.items():
        ws.column_dimensions[letter].width = width

    if report.is_clean:
        ws["A1"] = "✓ No conflicts detected"
        ws["A1"].font = Font(bold=True, size=13, color="006100")
        ws["A2"] = (
            "All placements pass the hard-constraint audit "
            "(C1 teacher, C2 room, C3 section/group, C6 parallel alignment)."
        )
        ws["A2"].font = SUBTITLE_FONT
    else:
        counts = report.count_by_type()
        summary = ", ".join(f"{v}× {k}" for k, v in sorted(counts.items()))
        ws["A1"] = f"✗ {len(report.conflicts)} conflict(s) detected — {summary}"
        ws["A1"].font = Font(bold=True, size=13, color="9C0006")

        headers = ["Type", "Entity", "Day", "Period", "Time", "Details"]
        for i, h in enumerate(headers, start=1):
            c = ws.cell(row=3, column=i, value=h)
            c.fill = HEADER_FILL
            c.font = HEADER_FONT
            c.border = CELL_BORDER
            c.alignment = CENTER_ALIGN

        row = 4
        for cflt in report.conflicts:
            time_str = (
                f"{PERIOD_TIMES[cflt.period][0]}-{PERIOD_TIMES[cflt.period][1]}"
                if cflt.period in PERIOD_TIMES else ""
            )
            values = [
                cflt.conflict_type, cflt.entity_id, cflt.day,
                f"P{cflt.period}" if cflt.period else "—", time_str,
                cflt.description,
            ]
            for i, v in enumerate(values, start=1):
                c = ws.cell(row=row, column=i, value=v)
                c.font = CONFLICT_FONT
                c.border = CELL_BORDER
                c.alignment = CELL_ALIGN
            row += 1

    _render_unscheduled_block(ws, report, start_row=(ws.max_row + 2))


def _render_unscheduled_block(ws, report: ConflictReport, start_row: int) -> None:
    if not report.unscheduled:
        ws.cell(row=start_row, column=1, value="Unscheduled sessions: none")
        ws.cell(row=start_row, column=1).font = SUBTITLE_FONT
        return

    ws.cell(row=start_row, column=1, value=(
        f"⚠ Unscheduled sessions ({len(report.unscheduled)}) — "
        f"these are NOT on any timetable:"
    )).font = Font(bold=True, size=11, color="BF8F00")

    headers = ["Assignment", "Subject", "Section", "Group", "Activity", "Reasons"]
    header_row = start_row + 1
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=header_row, column=i, value=h)
        c.font = Font(bold=True, size=9)
        c.border = CELL_BORDER

    row = header_row + 1
    for u in report.unscheduled:
        values = [
            u.get("assignment_id", ""),
            u.get("subject_id", ""),
            u.get("section", ""),
            u.get("group", ""),
            u.get("activity_type", ""),
            " | ".join(u.get("reasons", [])),
        ]
        for i, v in enumerate(values, start=1):
            c = ws.cell(row=row, column=i, value=v)
            c.font = CELL_FONT
            c.border = CELL_BORDER
            c.alignment = CELL_ALIGN
        row += 1


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _sheet_name(view: GridView, used: set) -> str:
    base = (
        view.entity_id.replace("/", "-").replace("\\", "-")
        .replace("*", "").replace("?", "").replace(":", " ")
        .replace("[", "(").replace("]", ")")
    )[:28] or "Sheet"
    name = base
    n = 2
    while name.lower() in used:
        suffix = f" ({n})"
        name = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(name.lower())
    return name


def _entry_text(entry) -> str:
    text = "\n".join(line for line in entry.lines if line)
    if entry.conflict:
        text = "⚠ " + text
    return text


def _page_setup(ws) -> None:
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
