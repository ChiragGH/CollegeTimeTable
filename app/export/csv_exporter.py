"""
CSV export.

Produces RFC-4180-compliant, UTF-8 (with BOM, so Excel detects the
encoding) files:

* one **grid** file per view, all entities inside, separated by banner
  rows — human-readable, prints cleanly;
* one **flat** long-format file (one row per placement-slot) for
  machine consumption / re-import;
* one **conflicts** file and one **unscheduled** file so that nothing
  about the schedule state is ever hidden.

Practical blocks occupy one CSV cell per covered period with identical
content (no ambiguous "cont." markers).  Conflicted cells are prefixed
with ``⚠ CONFLICT — ``.
"""

import csv
from pathlib import Path
from typing import List, Sequence

from app.models.placement import Placement

from app.export.conflicts import ConflictReport
from app.export.context import ExportContext
from app.export.grid import COL_LUNCH, GRID_COLUMNS, lunch_label, period_time, LUNCH_START, LUNCH_END
from app.export.views import (
    CellEntry,
    GridView,
    VIEW_TITLES,
    VIEW_CLASS,
    VIEW_GROUP,
    VIEW_ROOM,
    VIEW_SECTION,
    VIEW_TEACHER,
)

CONFLICT_MARK = "⚠ CONFLICT — "


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def export_view_csv(
    views: Sequence[GridView],
    view_kind: str,
    ctx: ExportContext,
    path: Path,
) -> Path:
    """Write all entity grids of one view kind into a single CSV file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        _file_header(writer, VIEW_TITLES[view_kind], ctx)

        if not views:
            writer.writerow(["(no entities to display)"])
            return path

        for i, view in enumerate(views):
            if i:
                writer.writerow([])
            _entity_block(writer, view)

    return path


def export_flat_csv(
    placements: Sequence[Placement],
    ctx: ExportContext,
    report: ConflictReport,
    path: Path,
) -> Path:
    """
    Long-format export: one row per (placement, slot).

    Columns cover every dimension a downstream system needs, including
    block membership and conflict flags.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conflict_by_slot = _conflicts_by_slot(report)

    header = [
        "placement_id", "day", "period", "time_start", "time_end",
        "branch", "semester", "section", "group", "activity_type",
        "subject_id", "subject_code", "subject_name",
        "teacher_id", "teacher_name", "room_id", "room_name",
        "block_size", "block_slot", "conflicts",
    ]

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for p in placements:
            a = p.assignment
            slots = sorted(p.slots, key=lambda s: (s.day.value, s.period))
            block_size = len(slots)
            subject = ctx.subjects.get(a.subject_id)
            for i, s in enumerate(slots):
                start, end = _slot_times(s.period)
                conflicts = conflict_by_slot.get(
                    (p.placement_id, s.day.name, s.period), []
                )
                writer.writerow([
                    p.placement_id,
                    s.day.value,          # Monday … Friday
                    s.period,
                    start, end,
                    a.branch or ctx.branch,
                    a.semester if a.semester else ctx.semester,
                    a.section,
                    a.group,
                    _activity_value(a.activity_type),
                    a.subject_id,
                    subject.subject_code if subject else "",
                    subject.subject_name if subject else a.subject_id,
                    a.teacher_id,
                    ctx.teacher_name(a.teacher_id),
                    p.room_id,
                    ctx.room_name(p.room_id),
                    block_size if block_size > 1 else 1,
                    f"{i + 1}/{block_size}",
                    "; ".join(conflicts),
                ])

    return path


def export_conflicts_csv(
    report: ConflictReport,
    ctx: ExportContext,
    path: Path,
) -> Path:
    """Flat list of every conflict found by the audit."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "type", "entity_id", "day", "period", "time",
            "description", "placement_a", "placement_b",
        ])
        if report.is_clean:
            writer.writerow([
                "NONE", "", "", "", "",
                "No conflicts detected — timetable passes all hard "
                "constraint checks (C1–C3, C6).",
                "", "",
            ])
            return path

        for c in report.conflicts:
            writer.writerow([
                c.conflict_type,
                c.entity_id,
                c.day,
                c.period if c.period else "",
                _conflict_time(c),
                c.description,
                c.placement_a,
                c.placement_b,
            ])
    return path


def export_unscheduled_csv(
    report: ConflictReport,
    ctx: ExportContext,
    path: Path,
) -> Path:
    """Sessions the scheduler could not place, with their reasons."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "assignment_id", "subject_id", "subject_name", "section",
            "group", "activity_type", "teacher_id", "session_index",
            "block_size", "reasons",
        ])
        if not report.unscheduled:
            writer.writerow([
                "", "", "", "", "", "", "", "", "",
                "(none — every session was placed)",
            ])
            return path

        for u in report.unscheduled:
            writer.writerow([
                u.get("assignment_id", ""),
                u.get("subject_id", ""),
                ctx.subject_name(u.get("subject_id", "")),
                u.get("section", ""),
                u.get("group", ""),
                u.get("activity_type", ""),
                u.get("teacher_id", ""),
                u.get("session_index", ""),
                u.get("block_size", ""),
                " | ".join(u.get("reasons", [])),
            ])
    return path


# ----------------------------------------------------------------------
# Grid rendering
# ----------------------------------------------------------------------

def _file_header(writer, title: str, ctx: ExportContext) -> None:
    writer.writerow([ctx.college_name])
    writer.writerow([title])
    meta = f"Session: {ctx.session_id}" if ctx.session_id else ""
    if ctx.academic_year:
        meta += f"  |  Academic Year: {ctx.academic_year}"
    if meta:
        writer.writerow([meta])
    writer.writerow([f"Generated: {ctx.generated_at}"])


def _entity_block(writer, view: GridView) -> None:
    banner = "=" * 60
    writer.writerow([banner])
    writer.writerow([f"{view.title}   [{view.entity_id}]"])
    if view.subtitle:
        writer.writerow([view.subtitle])
    stats = f"Scheduled periods: {view.weekly_periods}"
    if view.activities_present:
        stats += "  |  Activities: " + ", ".join(
            t for t in (_activity_tag(a) for a in view.activities_present) if t
        )
    writer.writerow([stats])
    for note in view.notes:
        writer.writerow([f"Note: {note}"])
    writer.writerow([banner])

    writer.writerow(_header_row())

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    for day_idx, day_name in enumerate(day_names):
        row = [day_name]
        for col_idx in range(len(GRID_COLUMNS)):
            if GRID_COLUMNS[col_idx] == COL_LUNCH:
                row.append(lunch_label())
                continue
            row.append(_cell_text(view.cell(day_idx, col_idx)))
        writer.writerow(row)


def _header_row() -> List[str]:
    row = ["Day"]
    for col in GRID_COLUMNS:
        if col == COL_LUNCH:
            row.append(f"{COL_LUNCH}\n{LUNCH_START}-{LUNCH_END}")
        else:
            row.append(f"P{col}\n{period_time(int(col))}")
    return row


def _cell_text(cell) -> str:
    if cell.is_empty:
        return ""
    parts: List[str] = []
    for e in cell.entries:
        text = "; ".join(line for line in e.lines if line)
        if e.conflict:
            text = CONFLICT_MARK + text
        parts.append(text)
    return "\n".join(parts)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _conflicts_by_slot(report: ConflictReport):
    out = {}
    for c in report.conflicts:
        for pid in (c.placement_a, c.placement_b):
            if pid:
                out.setdefault((pid, c.day, c.period), []).append(
                    c.description
                )
    return out


def _slot_times(period: int):
    from app.export.grid import PERIOD_TIMES

    return PERIOD_TIMES.get(period, ("", ""))


def _conflict_time(c) -> str:
    from app.export.grid import PERIOD_TIMES

    if c.period:
        return "-".join(PERIOD_TIMES.get(c.period, ("", "")))
    return ""


def _activity_value(activity_type) -> str:
    return (
        activity_type.value
        if hasattr(activity_type, "value")
        else str(activity_type)
    )


def _activity_tag(activity: str) -> str:
    from app.export.views import ACTIVITY_TAGS

    return ACTIVITY_TAGS.get(activity, activity) or "Lecture"
