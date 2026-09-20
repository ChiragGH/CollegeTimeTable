"""
Session manager for timetable setup.

Handles creation, persistence, and loading of :class:`TimetableSetup`
instances.  Sessions are stored under ``data/sessions/<session_id>/``:

    data/sessions/
    +-- 2026-27_CSE_Sem3/
    |   +-- session.json      # metadata + sections
    |   +-- Setup.xlsx        # assignments (DATA_SCHEMA.md §3.1 format)

Persistence uses JSON for metadata (round-trips perfectly) and
openpyxl for the Setup.xlsx export.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill

from app.models.section import Section
from app.models.assignment import Assignment
from app.models.session import TimetableSetup
from app.models.enums import ActivityType, RoomType


class SessionError(Exception):
    """Raised when a session operation fails."""


class SessionManager:
    """
    Creates, saves, loads, and lists timetable setup sessions.

    Args:
        sessions_dir: Root directory for session storage.
                      Defaults to ``data/sessions``.
    """

    def __init__(self, sessions_dir: str = "data/sessions"):
        self.sessions_dir = Path(sessions_dir)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_session(
        self,
        academic_year: str,
        branch: str,
        semester: int,
        sections: Optional[List[Section]] = None,
        session_id: Optional[str] = None,
    ) -> TimetableSetup:
        """
        Create a new timetable setup session.

        Args:
            academic_year: Academic year label, e.g. ``2026-27``.
            branch: Branch code, e.g. ``CSE``.
            semester: Semester number (1--6).
            sections: Optional list of sections. Defaults to one section ``A``
                      with groups ``["G1", "G2"]``.
            session_id: Optional explicit session ID. If omitted, generated
                        as ``<academic_year>_<branch>_Sem<semester>``.

        Returns:
            A new :class:`TimetableSetup` instance.

        Raises:
            SessionError: If a session with the same ID already exists.
        """
        if session_id is None:
            session_id = f"{academic_year}_{branch}_Sem{semester}"

        session_dir = self.sessions_dir / session_id
        if session_dir.exists():
            raise SessionError(
                f"Session '{session_id}' already exists at {session_dir}. "
                f"Use load_session() or delete it first."
            )

        if sections is None:
            sections = [
                Section(branch=branch, semester=semester, label="A"),
            ]

        setup = TimetableSetup(
            session_id=session_id,
            academic_year=academic_year,
            branch=branch,
            semester=semester,
            sections=sections,
            assignments=[],
            created_at=datetime.now().isoformat(timespec="seconds"),
        )

        return setup

    # ------------------------------------------------------------------
    # Add sections
    # ------------------------------------------------------------------

    def add_section(
        self,
        setup: TimetableSetup,
        label: str,
        groups: Optional[List[str]] = None,
    ) -> Section:
        """
        Add a new section to an existing setup.

        Args:
            setup: The timetable setup to modify.
            label: Section label, e.g. ``B``.
            groups: Subgroups. Defaults to ``["G1", "G2"]``.

        Returns:
            The newly created :class:`Section`.

        Raises:
            SessionError: If a section with that label already exists.
        """
        existing_labels = {s.label for s in setup.sections}
        if label in existing_labels:
            raise SessionError(
                f"Section '{label}' already exists in session '{setup.session_id}'."
            )

        section = Section(
            branch=setup.branch,
            semester=setup.semester,
            label=label,
            groups=groups if groups is not None else ["G1", "G2"],
        )
        setup.sections.append(section)
        return section

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_session(self, setup: TimetableSetup) -> Path:
        """
        Persist a session to disk.

        Creates the session directory, writes ``session.json`` (metadata
        + sections + assignments) and ``Setup.xlsx`` (assignments in
        DATA_SCHEMA.md §3.1 format).

        Returns:
            Path to the session directory.
        """
        session_dir = self.sessions_dir / setup.session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # --- Write session.json ---
        data = {
            "session_id": setup.session_id,
            "academic_year": setup.academic_year,
            "branch": setup.branch,
            "semester": setup.semester,
            "created_at": setup.created_at,
            "sections": [
                {
                    "branch": sec.branch,
                    "semester": sec.semester,
                    "label": sec.label,
                    "groups": sec.groups,
                }
                for sec in setup.sections
            ],
            "assignments": [
                self.assignment_to_dict(a)
                for a in setup.assignments
            ],
        }

        json_path = session_dir / "session.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # --- Write Setup.xlsx ---
        if setup.assignments:
            xlsx_path = session_dir / "Setup.xlsx"
            self._write_setup_xlsx(setup, xlsx_path)

        return session_dir

    @staticmethod
    def assignment_to_dict(a: Assignment) -> dict:
        """Serialize an Assignment to a JSON-safe dict."""
        """Serialize an Assignment to a JSON-safe dict."""
        return {
            "assignment_id": a.assignment_id,
            "session_id": a.session_id,
            "teacher_id": a.teacher_id,
            "subject_id": a.subject_id,
            "branch": a.branch,
            "semester": a.semester,
            "section": a.section,
            "group": a.group,
            "activity_type": a.activity_type.value if isinstance(a.activity_type, ActivityType) else str(a.activity_type),
            "weekly_periods": a.weekly_periods,
            "room_id": a.room_id,
            "room_type": a.room_type.value if isinstance(a.room_type, RoomType) else a.room_type,
            "block_size": a.block_size,
            "sessions_per_week": a.sessions_per_week,
        }

    def _write_setup_xlsx(self, setup: TimetableSetup, path: Path) -> None:
        """Write assignments to Setup.xlsx in DATA_SCHEMA §3.1 format."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Setup"

        # Header row
        headers = [
            "assignment_id", "session_id", "teacher_id", "subject_id",
            "branch", "semester", "section", "group", "activity_type",
            "room_id", "block_size", "sessions_per_week",
            "weekly_periods", "room_type",
        ]

        header_font = Font(bold=True)
        header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")

        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        # Data rows
        for row_idx, a in enumerate(setup.assignments, start=2):
            ws.cell(row=row_idx, column=1, value=a.assignment_id)
            ws.cell(row=row_idx, column=2, value=a.session_id)
            ws.cell(row=row_idx, column=3, value=a.teacher_id)
            ws.cell(row=row_idx, column=4, value=a.subject_id)
            ws.cell(row=row_idx, column=5, value=a.branch)
            ws.cell(row=row_idx, column=6, value=a.semester)
            ws.cell(row=row_idx, column=7, value=a.section)
            ws.cell(row=row_idx, column=8, value=a.group)
            ws.cell(row=row_idx, column=9, value=(
                a.activity_type.value
                if isinstance(a.activity_type, ActivityType)
                else str(a.activity_type)
            ))
            ws.cell(row=row_idx, column=10, value=a.room_id or "")
            ws.cell(row=row_idx, column=11, value=a.block_size)
            ws.cell(row=row_idx, column=12, value=a.sessions_per_week)
            ws.cell(row=row_idx, column=13, value=a.weekly_periods)
            ws.cell(row=row_idx, column=14, value=(
                a.room_type.value
                if isinstance(a.room_type, RoomType)
                else (a.room_type or "")
            ))

        # Auto-width columns
        for col in ws.columns:
            max_len = 0
            for cell in col:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            ws.column_dimensions[col[0].column_letter].width = max_len + 3

        wb.save(path)

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_session(self, session_id: str) -> TimetableSetup:
        """
        Load a previously saved session from disk.

        Args:
            session_id: The session identifier.

        Returns:
            A :class:`TimetableSetup` populated from the saved data.

        Raises:
            SessionError: If the session directory or JSON file is missing.
        """
        session_dir = self.sessions_dir / session_id
        json_path = session_dir / "session.json"

        if not json_path.exists():
            raise SessionError(
                f"Session '{session_id}' not found. "
                f"Expected {json_path} to exist."
            )

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        sections = [
            Section(
                branch=sec["branch"],
                semester=sec["semester"],
                label=sec["label"],
                groups=sec.get("groups", ["G1", "G2"]),
            )
            for sec in data.get("sections", [])
        ]

        assignments = [
            self.dict_to_assignment(ad)
            for ad in data.get("assignments", [])
        ]

        return TimetableSetup(
            session_id=data["session_id"],
            academic_year=data["academic_year"],
            branch=data["branch"],
            semester=data["semester"],
            sections=sections,
            assignments=assignments,
            created_at=data.get("created_at", ""),
        )

    @staticmethod
    def dict_to_assignment(d: dict) -> Assignment:
        """Deserialize a dict to an Assignment."""
        # Parse activity_type
        try:
            activity_type = ActivityType(d["activity_type"])
        except (ValueError, KeyError):
            activity_type = ActivityType.LECTURE

        # Parse room_type (optional)
        room_type = None
        rt_val = d.get("room_type")
        if rt_val:
            try:
                room_type = RoomType(rt_val)
            except ValueError:
                pass

        return Assignment(
            assignment_id=d["assignment_id"],
            session_id=d["session_id"],
            teacher_id=d["teacher_id"],
            subject_id=d["subject_id"],
            branch=d["branch"],
            semester=d["semester"],
            section=d["section"],
            group=d.get("group", "ALL"),
            activity_type=activity_type,
            weekly_periods=d.get("weekly_periods", 0),
            room_id=d.get("room_id"),
            room_type=room_type,
            block_size=d.get("block_size", 1),
            sessions_per_week=d.get("sessions_per_week", 0),
        )

    # ------------------------------------------------------------------
    # List / Delete
    # ------------------------------------------------------------------

    def list_sessions(self) -> List[str]:
        """Return IDs of all saved sessions."""
        if not self.sessions_dir.exists():
            return []
        return sorted([
            d.name
            for d in self.sessions_dir.iterdir()
            if d.is_dir() and (d / "session.json").exists()
        ])

    def delete_session(self, session_id: str) -> None:
        """
        Delete a saved session and all its files.

        Raises:
            SessionError: If the session does not exist.
        """
        session_dir = self.sessions_dir / session_id
        if not session_dir.exists():
            raise SessionError(f"Session '{session_id}' not found.")

        import shutil
        shutil.rmtree(session_dir)

    def session_exists(self, session_id: str) -> bool:
        """Check if a session with the given ID exists on disk."""
        return (self.sessions_dir / session_id / "session.json").exists()
