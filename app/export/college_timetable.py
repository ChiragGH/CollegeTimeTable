"""
College-style human-readable timetable representation and exporters.

Implements the official college timetable layout:
    DAY | TIME | PERIOD | SUBJECT | CLASSROOM/LAB | TEACHER NAME

Features:
- Master data short_name used for subjects (e.g., AE, DE, OS)
- Human teacher names used (e.g., RS, AMG)
- G1/G2 parallel practical slash notation (AE/AE, CC1/CC2, RS/AMG)
- Distinct Recess row (1:00-2:00 RECESS)
- Multi-period practical vertical merging (XLSX / PDF) and continuation (CSV)
- No internal placement IDs, database keys, or debug fields
- Pre-export validation
"""

import csv
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, portrait
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.assignment import Assignment
from app.models.enums import ActivityType, Day
from app.models.placement import Placement
from app.models.slot import TimeSlot
from app.export.context import ExportContext
from app.export.grid import PERIOD_TIMES, LUNCH_START, LUNCH_END


@dataclass
class TimetableCell:
    """
    Clean human-readable cell representing one scheduled slot in the college timetable.
    """
    day: str                # e.g. "MON", "TUE"
    day_full: str           # e.g. "Monday"
    time: str               # e.g. "9:00-10:00"
    period: str             # e.g. "1", "2", "RECESS", "5"
    period_num: Optional[int]
    subject: str            # e.g. "AE", "OS", "AE/AE", "RECESS", "SCA"
    classroom: str          # e.g. "CC1", "L2", "CC1/CC2", "—"
    teacher: str            # e.g. "RS", "PB", "RS/AMG", "—"
    activity_type: str      # e.g. "LECTURE", "PRACTICAL", "RECESS", "SCA"
    is_recess: bool = False
    block_size: int = 1
    is_block_start: bool = True
    section: str = ""


# Day display mapping
DAY_ABBR = {
    Day.MON: "MON",
    Day.TUE: "TUE",
    Day.WED: "WED",
    Day.THU: "THU",
    Day.FRI: "FRI",
}

DAYS_ORDER = [Day.MON, Day.TUE, Day.WED, Day.THU, Day.FRI]


# ====================================================================
# Pre-export validation
# ====================================================================

def validate_for_college_export(
    placements: Sequence[Placement],
    ctx: ExportContext,
) -> Tuple[bool, List[str]]:
    """
    Run pre-export audit checking all hard constraints.

    Returns:
        (is_valid, issues_list)
    """
    issues: List[str] = []

    teacher_slots: Dict[Tuple[str, Day, int], str] = {}
    room_slots: Dict[Tuple[str, Day, int], str] = {}
    section_slots: Dict[Tuple[str, str, Day, int], str] = {}

    for p in placements:
        a = p.assignment
        sec = a.section

        for s in p.slots:
            slot_key = (s.day, s.period)

            # Recess check
            if s.period not in PERIOD_TIMES:
                issues.append(
                    f"Placement {p.placement_id} ({a.subject_id}) scheduled outside "
                    f"valid teaching periods at period {s.period}."
                )

            # Teacher clash (if teacher assigned)
            if a.teacher_id and a.teacher_id not in ("—", ""):
                t_key = (a.teacher_id, s.day, s.period)
                if t_key in teacher_slots:
                    issues.append(
                        f"Teacher conflict: {ctx.teacher_name(a.teacher_id)} ({a.teacher_id}) "
                        f"double-booked at {s.day.value} P{s.period} ({teacher_slots[t_key]} vs {p.placement_id})."
                    )
                else:
                    teacher_slots[t_key] = p.placement_id

            # Room clash (if real room assigned)
            if p.room_id and p.room_id not in ("—", ""):
                r_key = (p.room_id, s.day, s.period)
                if r_key in room_slots:
                    issues.append(
                        f"Room conflict: {ctx.room_name(p.room_id)} ({p.room_id}) "
                        f"double-booked at {s.day.value} P{s.period} ({room_slots[r_key]} vs {p.placement_id})."
                    )
                else:
                    room_slots[r_key] = p.placement_id

            # Section & group clash
            grp = a.group or "ALL"
            sec_grp_key = (sec, grp, s.day, s.period)
            all_grp_key = (sec, "ALL", s.day, s.period)

            if grp == "ALL":
                # ALL conflicts with any group in this section
                if all_grp_key in section_slots:
                    issues.append(
                        f"Section conflict: Section {sec} double-booked at "
                        f"{s.day.value} P{s.period} ({section_slots[all_grp_key]} vs {p.placement_id})."
                    )
                section_slots[all_grp_key] = p.placement_id
            else:
                if sec_grp_key in section_slots:
                    issues.append(
                        f"Group conflict: Section {sec} Group {grp} double-booked at "
                        f"{s.day.value} P{s.period} ({section_slots[sec_grp_key]} vs {p.placement_id})."
                    )
                section_slots[sec_grp_key] = p.placement_id
                if all_grp_key in section_slots:
                    issues.append(
                        f"Section/Group conflict: Section {sec} has ALL and {grp} at "
                        f"{s.day.value} P{s.period} ({section_slots[all_grp_key]} vs {p.placement_id})."
                    )

    return (len(issues) == 0, issues)


# ====================================================================
# View Builder: College Timetable Cells
# ====================================================================

def build_college_cells(
    placements: Sequence[Placement],
    ctx: ExportContext,
    section_label: str,
) -> List[TimetableCell]:
    """
    Build structured timetable cells for a section following the college standard:
    - DAY | TIME | PERIOD | SUBJECT | CLASSROOM/LAB | TEACHER NAME
    - G1/G2 parallel slash format (AE/AE, CC1/CC2, RS/AMG)
    - RECESS row between Period 4 and 5
    """
    # Filter placements relevant to this section
    sec_placements = [
        p for p in placements if p.assignment.section == section_label
    ]

    # Map (day, period) -> List[Placement]
    by_slot: Dict[Tuple[Day, int], List[Placement]] = {}
    for p in sec_placements:
        for s in p.slots:
            by_slot.setdefault((s.day, s.period), []).append(p)

    cells: List[TimetableCell] = []

    for day in DAYS_ORDER:
        day_abbr = DAY_ABBR[day]
        day_full = day.value

        # Morning periods: 1 to 4
        for period in (1, 2, 3, 4):
            time_start, time_end = PERIOD_TIMES[period]
            time_str = f"{time_start}-{time_end}"
            plist = by_slot.get((day, period), [])
            cell = _make_cell_from_placements(
                day_abbr, day_full, time_str, str(period), period,
                plist, ctx, section_label,
            )
            cells.append(cell)

        # RECESS
        cells.append(TimetableCell(
            day=day_abbr,
            day_full=day_full,
            time=f"{LUNCH_START}-{LUNCH_END}",
            period="RECESS",
            period_num=None,
            subject="RECESS",
            classroom="—",
            teacher="—",
            activity_type="RECESS",
            is_recess=True,
            block_size=1,
            is_block_start=True,
            section=section_label,
        ))

        # Afternoon periods: 5 to 7
        for period in (5, 6, 7):
            time_start, time_end = PERIOD_TIMES[period]
            time_str = f"{time_start}-{time_end}"
            plist = by_slot.get((day, period), [])
            cell = _make_cell_from_placements(
                day_abbr, day_full, time_str, str(period), period,
                plist, ctx, section_label,
            )
            cells.append(cell)

    return cells


def _make_cell_from_placements(
    day_abbr: str,
    day_full: str,
    time_str: str,
    period_str: str,
    period_num: int,
    plist: List[Placement],
    ctx: ExportContext,
    section_label: str,
) -> TimetableCell:
    """Create one TimetableCell resolving parallel G1/G2 slash formatting."""
    if not plist:
        # A free period is a genuinely EMPTY cell — never a fabricated
        # "SCA (Free)" filler.  SCA appears only when a real SCA
        # assignment with workload was scheduled into this slot.
        return TimetableCell(
            day=day_abbr,
            day_full=day_full,
            time=time_str,
            period=period_str,
            period_num=period_num,
            subject="",
            classroom="",
            teacher="",
            activity_type="FREE",
            block_size=1,
            is_block_start=True,
            section=section_label,
        )

    # Check for parallel G1 and G2 placements
    g1_p = next((p for p in plist if p.assignment.group == "G1"), None)
    g2_p = next((p for p in plist if p.assignment.group == "G2"), None)

    if g1_p and g2_p:
        # Check parallel merging rule:
        # same day, same starting period, same block_size, same subject/activity
        slots_g1 = sorted(g1_p.slots, key=lambda s: s.period)
        slots_g2 = sorted(g2_p.slots, key=lambda s: s.period)
        same_start = slots_g1[0].period == slots_g2[0].period
        same_len = len(slots_g1) == len(slots_g2)
        same_subj = g1_p.assignment.subject_id == g2_p.assignment.subject_id

        if same_start and same_len and same_subj:
            # Merged parallel practical in slash format
            s_name = ctx.subject_short_name(g1_p.assignment.subject_id)
            r1 = ctx.room_name(g1_p.room_id)
            r2 = ctx.room_name(g2_p.room_id)
            t1 = ctx.teacher_name(g1_p.assignment.teacher_id)
            t2 = ctx.teacher_name(g2_p.assignment.teacher_id)

            is_start = (slots_g1[0].period == period_num)
            return TimetableCell(
                day=day_abbr,
                day_full=day_full,
                time=time_str,
                period=period_str,
                period_num=period_num,
                subject=f"{s_name}/{s_name}",
                classroom=f"{r1}/{r2}",
                teacher=f"{t1}/{t2}",
                activity_type=g1_p.assignment.activity_type.value,
                block_size=len(slots_g1),
                is_block_start=is_start,
                section=section_label,
            )

    # Single placement or separate placements
    p = plist[0]
    a = p.assignment
    slots = sorted(p.slots, key=lambda s: s.period)
    is_start = (slots[0].period == period_num)
    block_size = len(slots)

    subj_short = ctx.subject_short_name(a.subject_id)
    if a.group and a.group not in ("ALL", ""):
        subj_display = f"{subj_short} ({a.group})"
    else:
        subj_display = subj_short

    room_name = ctx.room_name(p.room_id) if p.room_id and p.room_id not in ("—", "") else "—"
    teacher_name = ctx.teacher_name(a.teacher_id) if a.teacher_id and a.teacher_id not in ("—", "") else "—"

    return TimetableCell(
        day=day_abbr,
        day_full=day_full,
        time=time_str,
        period=period_str,
        period_num=period_num,
        subject=subj_display,
        classroom=room_name,
        teacher=teacher_name,
        activity_type=a.activity_type.value if hasattr(a.activity_type, "value") else str(a.activity_type),
        block_size=block_size,
        is_block_start=is_start,
        section=section_label,
    )


# ====================================================================
# Exporters
# ====================================================================

def export_college_csv(
    cells: List[TimetableCell],
    path: Path,
    title: str = "",
) -> Path:
    """
    Export human-readable college timetable CSV.

    Columns:
        DAY | TIME | PERIOD | SUBJECT | CLASSROOM/LAB | TEACHER NAME
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    header = ["DAY", "TIME", "PERIOD", "SUBJECT", "CLASSROOM/LAB", "TEACHER NAME"]

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if title:
            writer.writerow([title])
            writer.writerow([])
        writer.writerow(header)

        for c in cells:
            writer.writerow([
                c.day,
                c.time,
                c.period,
                c.subject,
                c.classroom,
                c.teacher,
            ])

    return path


def export_college_xlsx(
    cells: List[TimetableCell],
    path: Path,
    title: str = "College Timetable",
    subtitle: str = "",
) -> Path:
    """
    Export human-readable college timetable XLSX with openpyxl.

    Includes:
    - Bold headers
    - Vertical merging for multi-period practical blocks
    - Shaded Recess rows
    - Clean typography and borders
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Timetable"
    ws.sheet_view.showGridLines = True

    # Styling Palette
    font_title = Font(name="Calibri", size=14, bold=True, color="1F3864")
    font_sub = Font(name="Calibri", size=10, italic=True, color="595959")
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_day = Font(name="Calibri", size=10, bold=True)
    font_cell = Font(name="Calibri", size=10)
    font_recess = Font(name="Calibri", size=10, bold=True, color="7F7F7F")

    fill_header = PatternFill("solid", start_color="1F3864")
    fill_day = PatternFill("solid", start_color="D9E1F2")
    fill_recess = PatternFill("solid", start_color="F2F2F2")
    fill_practical = PatternFill("solid", start_color="E2EFDA")
    fill_lecture = PatternFill("solid", start_color="FFFFFF")

    thin_border = Side(style="thin", color="BFBFBF")
    border_cell = Border(left=thin_border, right=thin_border, top=thin_border, bottom=thin_border)

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")

    # Titles
    ws.merge_cells("A1:F1")
    ws["A1"] = title
    ws["A1"].font = font_title
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 25

    if subtitle:
        ws.merge_cells("A2:F2")
        ws["A2"] = subtitle
        ws["A2"].font = font_sub
        ws["A2"].alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[2].height = 18
        header_row = 4
    else:
        header_row = 3

    # Headers
    headers = ["DAY", "TIME", "PERIOD", "SUBJECT", "CLASSROOM/LAB", "TEACHER NAME"]
    ws.row_dimensions[header_row].height = 24
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = border_cell

    # Column widths
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 20
    ws.column_dimensions["E"].width = 18
    ws.column_dimensions["F"].width = 18

    start_data_row = header_row + 1
    current_row = start_data_row

    # Render cell rows and track merges for practical blocks
    merges_to_apply = []  # (col_idx, start_row, end_row)

    idx = 0
    while idx < len(cells):
        c = cells[idx]
        row_num = current_row

        ws.row_dimensions[row_num].height = 20

        ws.cell(row=row_num, column=1, value=c.day).alignment = align_center
        ws.cell(row=row_num, column=1).font = font_day
        ws.cell(row=row_num, column=1).fill = fill_day
        ws.cell(row=row_num, column=1).border = border_cell

        ws.cell(row=row_num, column=2, value=c.time).alignment = align_center
        ws.cell(row=row_num, column=2).font = font_cell
        ws.cell(row=row_num, column=2).border = border_cell

        ws.cell(row=row_num, column=3, value=c.period).alignment = align_center
        ws.cell(row=row_num, column=3).font = font_recess if c.is_recess else font_cell
        ws.cell(row=row_num, column=3).border = border_cell

        subj_cell = ws.cell(row=row_num, column=4, value=c.subject)
        subj_cell.alignment = align_center
        subj_cell.border = border_cell

        room_cell = ws.cell(row=row_num, column=5, value=c.classroom)
        room_cell.alignment = align_center
        room_cell.border = border_cell

        teacher_cell = ws.cell(row=row_num, column=6, value=c.teacher)
        teacher_cell.alignment = align_center
        teacher_cell.border = border_cell

        if c.is_recess:
            for col in range(2, 7):
                ws.cell(row=row_num, column=col).fill = fill_recess
                ws.cell(row=row_num, column=col).font = font_recess
        elif c.block_size > 1 and c.is_block_start:
            # Multi-period practical block: vertical merge for subject, room, teacher
            span = c.block_size
            end_row = row_num + span - 1
            merges_to_apply.append((4, row_num, end_row))
            merges_to_apply.append((5, row_num, end_row))
            merges_to_apply.append((6, row_num, end_row))
            for r_offset in range(span):
                for col in range(4, 7):
                    ws.cell(row=row_num + r_offset, column=col).fill = fill_practical
        else:
            if not (c.block_size > 1 and not c.is_block_start):
                for col in range(4, 7):
                    ws.cell(row=row_num, column=col).fill = fill_lecture

        current_row += 1
        idx += 1

    # Apply vertical merges for multi-period blocks
    for col_idx, r_start, r_end in merges_to_apply:
        ws.merge_cells(
            start_row=r_start, start_column=col_idx,
            end_row=r_end, end_column=col_idx,
        )

    # Day merges (merge Day column vertically per day)
    day_start = start_data_row
    # 7 periods + 1 recess = 8 rows per day
    for _ in range(len(DAYS_ORDER)):
        ws.merge_cells(
            start_row=day_start, start_column=1,
            end_row=day_start + 7, end_column=1,
        )
        day_start += 8

    wb.save(path)
    return path


def export_college_pdf(
    cells: List[TimetableCell],
    path: Path,
    title: str = "College Timetable",
    subtitle: str = "",
    college_name: str = "College Timetable System",
) -> Path:
    """
    Export human-readable print-ready college timetable PDF using ReportLab.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(path),
        pagesize=portrait(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    story = []

    style_college = ParagraphStyle(
        "CollegeHead",
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#1F3864"),
        alignment=1,
    )
    style_title = ParagraphStyle(
        "TitleHead",
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#333333"),
        alignment=1,
    )
    style_sub = ParagraphStyle(
        "SubHead",
        fontName="Helvetica-Oblique",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#666666"),
        alignment=1,
    )

    story.append(Paragraph(escape(college_name), style_college))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(escape(title), style_title))
    if subtitle:
        story.append(Spacer(1, 1 * mm))
        story.append(Paragraph(escape(subtitle), style_sub))
    story.append(Spacer(1, 4 * mm))

    # Build PDF Table
    header = ["DAY", "TIME", "PERIOD", "SUBJECT", "CLASSROOM/LAB", "TEACHER NAME"]
    table_data = [[Paragraph(f"<b>{h}</b>", ParagraphStyle("TH", fontName="Helvetica-Bold", fontSize=8, textColor=colors.white, alignment=1)) for h in header]]

    t_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFBFBF")),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]

    cell_style = ParagraphStyle("TD", fontName="Helvetica", fontSize=7.5, leading=9.5, alignment=1)
    recess_style = ParagraphStyle("TR", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, textColor=colors.HexColor("#666666"), alignment=1)
    day_style = ParagraphStyle("TDAY", fontName="Helvetica-Bold", fontSize=8, leading=10, alignment=1)

    row_index = 1
    merges_to_apply = []

    for idx, c in enumerate(cells):
        if c.is_recess:
            row = [
                Paragraph(c.day, day_style),
                Paragraph(c.time, recess_style),
                Paragraph(c.period, recess_style),
                Paragraph(c.subject, recess_style),
                Paragraph(c.classroom, recess_style),
                Paragraph(c.teacher, recess_style),
            ]
            t_style.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#F2F2F2")))
        else:
            row = [
                Paragraph(c.day, day_style),
                Paragraph(c.time, cell_style),
                Paragraph(c.period, cell_style),
                Paragraph(c.subject, cell_style),
                Paragraph(c.classroom, cell_style),
                Paragraph(c.teacher, cell_style),
            ]
            if c.block_size > 1 and c.is_block_start:
                span = c.block_size
                end_r = row_index + span - 1
                merges_to_apply.append((3, row_index, 3, end_r))
                merges_to_apply.append((4, row_index, 4, end_r))
                merges_to_apply.append((5, row_index, 5, end_r))
                t_style.append(("BACKGROUND", (3, row_index), (5, end_r), colors.HexColor("#E2EFDA")))

        table_data.append(row)
        row_index += 1

    # Merge day column (8 rows per day)
    for day_idx in range(len(DAYS_ORDER)):
        d_start = 1 + day_idx * 8
        d_end = d_start + 7
        t_style.append(("SPAN", (0, d_start), (0, d_end)))
        t_style.append(("BACKGROUND", (0, d_start), (0, d_end), colors.HexColor("#D9E1F2")))

    # Apply vertical practical merges
    for c_start, r_start, c_end, r_end in merges_to_apply:
        t_style.append(("SPAN", (c_start, r_start), (c_end, r_end)))

    col_widths = [16 * mm, 26 * mm, 20 * mm, 40 * mm, 38 * mm, 38 * mm]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(t_style))
    story.append(t)

    doc.build(story)
    return path
