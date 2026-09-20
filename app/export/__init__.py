"""
Timetable export package.

Production-quality export of generated timetables in three formats:

* **CSV** — human-readable grid files (one per view) plus a flat
  long-format file, a conflict report and an unscheduled-sessions list.
* **XLSX** — one workbook per view, one sheet per entity, merged
  practical blocks, colour-coded activities, conflict sheet.
* **PDF** — one landscape document per view: audit page + one page per
  entity.

Views: class-wise, section-wise, group-wise, teacher-wise, room-wise.

Typical usage::

    from app.export import ExportContext, TimetableExporter

    ctx = ExportContext(session_id="2026-27_CSE_Sem3", ...)
    exporter = TimetableExporter(result.placements, ctx)
    files = exporter.export_all(out_dir="exports/")

Guarantee: every export embeds the results of an independent
hard-constraint audit (C1–C3, C6) — conflicts are flagged inline on the
offending cells and listed in full; unscheduled sessions are reported
too.  No hidden conflicts.
"""

from app.export.conflicts import Conflict, ConflictReport, audit_placements
from app.export.context import ExportContext
from app.export.grid import (
    DAYS,
    GRID_COLUMNS,
    PERIOD_TIMES,
    PERIODS_PER_DAY,
    period_header,
    period_time,
)
from app.export.rebuild import placements_from_result_data
from app.export.service import (
    FORMATS,
    ExportError,
    ExportResult,
    TimetableExporter,
)
from app.export.views import (
    VIEW_CLASS,
    VIEW_GROUP,
    VIEW_KINDS,
    VIEW_ROOM,
    VIEW_SECTION,
    VIEW_TEACHER,
    VIEW_TITLES,
    GridView,
    build_views,
)
from app.export.college_timetable import (
    TimetableCell,
    build_college_cells,
    export_college_csv,
    export_college_xlsx,
    export_college_pdf,
    validate_for_college_export,
)

__all__ = [
    # service
    "TimetableExporter",
    "TimetableCell",
    "build_college_cells",
    "export_college_csv",
    "export_college_xlsx",
    "export_college_pdf",
    "validate_for_college_export",
    "ExportError",
    "ExportResult",
    "FORMATS",
    # context / inputs
    "ExportContext",
    "placements_from_result_data",
    # audit
    "Conflict",
    "ConflictReport",
    "audit_placements",
    # views
    "VIEW_KINDS",
    "VIEW_TITLES",
    "VIEW_CLASS",
    "VIEW_SECTION",
    "VIEW_GROUP",
    "VIEW_TEACHER",
    "VIEW_ROOM",
    "GridView",
    "build_views",
    # grid
    "DAYS",
    "GRID_COLUMNS",
    "PERIOD_TIMES",
    "PERIODS_PER_DAY",
    "period_header",
    "period_time",
]
