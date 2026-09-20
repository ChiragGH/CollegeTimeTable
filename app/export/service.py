"""
Export orchestration.

:class:`TimetableExporter` is the single entry point used by both the
Flask API and batch scripts.  It owns the pipeline:

    placements ──► conflict audit ──► view models ──► CSV / XLSX / PDF

Usage::

    ctx = ExportContext(session_id="2026-27_CSE_Sem3", ...)
    exporter = TimetableExporter(result.placements, ctx,
                                 unscheduled=[u.to_dict() for u in result.unscheduled])

    # one file (e.g. a web download)
    path = exporter.export_view("section", "xlsx")

    # the complete bundle
    files = exporter.export_all(out_dir="Data/sessions/2026-27_CSE_Sem3/exports")

Views are built lazily and cached; the conflict audit runs once.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from app.models.placement import Placement

from app.export.conflicts import ConflictReport, audit_placements
from app.export.context import ExportContext
from app.export.csv_exporter import (
    export_conflicts_csv,
    export_flat_csv,
    export_unscheduled_csv,
    export_view_csv,
)
from app.export.pdf_exporter import export_view_pdf
from app.export.views import (
    VIEW_KINDS,
    VIEW_TITLES,
    build_views,
)
from app.export.xlsx_exporter import export_view_xlsx
from app.export.college_timetable import (
    build_college_cells,
    export_college_csv,
    export_college_xlsx,
    export_college_pdf,
    validate_for_college_export,
)

FORMATS = ("csv", "xlsx", "pdf")

AUX_CSV_FILES = {
    "flat": "Timetable_Flat.csv",
    "conflicts": "Conflicts.csv",
    "unscheduled": "Unscheduled_Sessions.csv",
}


class ExportError(Exception):
    """Raised when an export operation cannot be completed."""


@dataclass
class ExportResult:
    """What was written, plus the audit outcome."""
    files: List[Path] = field(default_factory=list)
    report: Optional[ConflictReport] = None

    @property
    def is_clean(self) -> bool:
        return bool(self.report and self.report.is_clean)


class TimetableExporter:
    """
    Builds all five views from placements and renders them in any
    supported format.

    Args:
        placements:   The scheduled placements to export.
        ctx:          Reference data / session metadata.
        unscheduled:  Optional list of unscheduled-session dicts
                      (``UnscheduledSession.to_dict()``) — included in
                      every audit report so nothing is hidden.
    """

    def __init__(
        self,
        placements: Sequence[Placement],
        ctx: ExportContext,
        unscheduled: Optional[Sequence[dict]] = None,
    ):
        self.ctx = ctx
        self.report = audit_placements(placements, unscheduled or [])
        self.placements = list(placements)
        self._view_cache: Dict[str, list] = {}

    # ------------------------------------------------------------------
    # View access
    # ------------------------------------------------------------------

    def views(self, view_kind: str) -> list:
        """All entity grids for a view kind (built once, then cached)."""
        if view_kind not in VIEW_KINDS:
            raise ExportError(
                f"Unknown view {view_kind!r}. Valid: {', '.join(VIEW_KINDS)}"
            )
        if view_kind not in self._view_cache:
            self._view_cache[view_kind] = build_views(
                self.placements, self.ctx, self.report, view_kind,
            )
        return self._view_cache[view_kind]

    def conflicts(self) -> ConflictReport:
        return self.report

    # ------------------------------------------------------------------
    # Single-file export (web downloads)
    # ------------------------------------------------------------------

    def export_view(
        self,
        view_kind: str,
        fmt: str,
        entity: Optional[str] = None,
        out_dir: Optional[Path] = None,
        filename: Optional[str] = None,
    ) -> Path:
        """
        Export one view (or one entity of it) to ``fmt``.

        Args:
            view_kind: class | section | group | teacher | room.
            fmt:       csv | xlsx | pdf.
            entity:    Optional entity id to export a single grid
                       (e.g. ``"CSE-3-A"`` or ``"T001"``).
            out_dir:   Defaults to the system temp dir when omitted.
            filename:  Overrides the default file name.
        """
        views = self.views(view_kind)
        if entity:
            views = [v for v in views if v.entity_id == entity]
            if not views:
                raise ExportError(
                    f"Entity {entity!r} not found in {view_kind!r} view"
                )

        target = self._target_path(
            out_dir, filename, view_kind, fmt, entity,
        )

        if fmt == "csv":
            return export_view_csv(views, view_kind, self.ctx, target)
        if fmt == "xlsx":
            return export_view_xlsx(views, view_kind, self.ctx, self.report, target)
        if fmt == "pdf":
            return export_view_pdf(views, view_kind, self.ctx, self.report, target)

        raise ExportError(
            f"Unknown format {fmt!r}. Valid: {', '.join(FORMATS)}"
        )

    def export_aux(self, kind: str, out_dir: Optional[Path] = None) -> Path:
        """Export one auxiliary CSV: ``flat`` | ``conflicts`` | ``unscheduled`` | ``college_csv``."""
        if kind in ("college_csv", "human_csv"):
            return self.export_college_csv(out_dir=out_dir, filename="College_Timetable.csv")
        if kind not in AUX_CSV_FILES:
            raise ExportError(
                f"Unknown aux export {kind!r}. Valid: {', '.join(AUX_CSV_FILES)}"
            )
        target = self._resolve_out(out_dir) / AUX_CSV_FILES[kind]
        if kind == "flat":
            return export_flat_csv(self.placements, self.ctx, self.report, target)
        if kind == "conflicts":
            return export_conflicts_csv(self.report, self.ctx, target)
        if kind in ("college_csv", "human_csv"):
            return self.export_college_csv(out_dir=out_dir, filename=AUX_CSV_FILES[kind])
        return export_unscheduled_csv(self.report, self.ctx, target)

    # ------------------------------------------------------------------
    # College-style human-readable timetable export
    # ------------------------------------------------------------------

    def export_college_csv(
        self,
        section: Optional[str] = None,
        out_dir: Optional[Path] = None,
        filename: Optional[str] = None,
    ) -> Path:
        """
        Export official college-style human-readable timetable CSV.
        Layout: DAY | TIME | PERIOD | SUBJECT | CLASSROOM/LAB | TEACHER NAME
        """
        sec_label = section or (self.ctx.sections[0].label if self.ctx.sections else "A")
        cells = build_college_cells(self.placements, self.ctx, sec_label)
        title = f"{self.ctx.college_name} — Section {sec_label} Timetable"
        name = filename or f"College_Timetable_{sec_label}.csv"
        target = self._resolve_out(out_dir) / name
        return export_college_csv(cells, target, title=title)

    def export_college_xlsx(
        self,
        section: Optional[str] = None,
        out_dir: Optional[Path] = None,
        filename: Optional[str] = None,
    ) -> Path:
        """
        Export official college-style human-readable timetable XLSX.
        Includes bold headers, vertical practical merges, and Recess rows.
        """
        sec_label = section or (self.ctx.sections[0].label if self.ctx.sections else "A")
        cells = build_college_cells(self.placements, self.ctx, sec_label)
        title = f"{self.ctx.college_name} — Section {sec_label} Timetable"
        subtitle = (
            f"Branch: {self.ctx.branch} | Semester: {self.ctx.semester} | "
            f"Generated: {self.ctx.generated_at}"
        )
        name = filename or f"College_Timetable_{sec_label}.xlsx"
        target = self._resolve_out(out_dir) / name
        return export_college_xlsx(cells, target, title=title, subtitle=subtitle)

    def export_college_pdf(
        self,
        section: Optional[str] = None,
        out_dir: Optional[Path] = None,
        filename: Optional[str] = None,
    ) -> Path:
        """
        Export official print-ready college-style timetable PDF.
        """
        sec_label = section or (self.ctx.sections[0].label if self.ctx.sections else "A")
        cells = build_college_cells(self.placements, self.ctx, sec_label)
        title = f"Section {sec_label} Timetable"
        subtitle = (
            f"Branch: {self.ctx.branch} | Semester: {self.ctx.semester} | "
            f"Session: {self.ctx.session_id}"
        )
        name = filename or f"College_Timetable_{sec_label}.pdf"
        target = self._resolve_out(out_dir) / name
        return export_college_pdf(
            cells, target, title=title, subtitle=subtitle,
            college_name=self.ctx.college_name,
        )

    def export_college_timetable(
        self,
        fmt: str,
        section: Optional[str] = None,
        out_dir: Optional[Path] = None,
        filename: Optional[str] = None,
    ) -> Path:
        """Export college timetable in requested format (csv, xlsx, pdf)."""
        fmt = fmt.lower()
        if fmt == "csv":
            return self.export_college_csv(section=section, out_dir=out_dir, filename=filename)
        elif fmt == "xlsx":
            return self.export_college_xlsx(section=section, out_dir=out_dir, filename=filename)
        elif fmt == "pdf":
            return self.export_college_pdf(section=section, out_dir=out_dir, filename=filename)
        else:
            raise ExportError(f"Unsupported college timetable format: {fmt}")

    # ------------------------------------------------------------------
    # Full bundle
    # ------------------------------------------------------------------

    def export_all(
        self,
        out_dir: Optional[Path] = None,
        views: Sequence[str] = VIEW_KINDS,
        formats: Sequence[str] = FORMATS,
    ) -> ExportResult:
        """
        Write the complete export bundle:

        ``Timetable_<View>.<fmt>`` for every requested view/format,
        plus the flat, conflicts, and unscheduled CSVs.

        Returns an :class:`ExportResult` with every written path.
        """
        files: List[Path] = []
        base = self._resolve_out(out_dir)

        for view_kind in views:
            for fmt in formats:
                files.append(self.export_view(view_kind, fmt, out_dir=base))

        for kind in AUX_CSV_FILES:
            files.append(self.export_aux(kind, out_dir=base))

        return ExportResult(files=files, report=self.report)

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def default_filename(self, view_kind: str, fmt: str,
                         entity: Optional[str] = None) -> str:
        stem = f"Timetable_{view_kind.capitalize()}"
        if entity:
            stem += f"_{_safe_name(entity)}"
        return f"{stem}.{fmt}"

    def _target_path(self, out_dir, filename, view_kind, fmt, entity) -> Path:
        name = filename or self.default_filename(view_kind, fmt, entity)
        return self._resolve_out(out_dir) / name

    @staticmethod
    def _resolve_out(out_dir: Optional[Path]) -> Path:
        import tempfile

        return Path(out_dir) if out_dir else Path(tempfile.gettempdir())


def _safe_name(text: str) -> str:
    for ch in '\\/:*?"<>| ':
        text = text.replace(ch, "-")
    return text
