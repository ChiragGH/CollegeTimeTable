"""
Excel data loader.

Reads master data workbooks (Teachers, Rooms, Subjects, Workloads) from
``Data/master/*.xlsx`` and returns lists of domain model instances.

Uses ``openpyxl`` for .xlsx parsing as specified in ARCHITECTURE.md §6.
"""

from pathlib import Path
from typing import List, Optional

import openpyxl

from app.models.teacher import Teacher
from app.models.room import Room
from app.models.subject import Subject
from app.models.workload import Workload
from app.models.enums import RoomType


class DataLoadError(Exception):
    """Raised when a master data file cannot be loaded or parsed."""


def _str_val(value) -> Optional[str]:
    """Coerce a cell value to stripped string, or None if blank."""
    if value is None:
        return None
    return str(value).strip()


def _bool_val(value) -> Optional[bool]:
    """
    Coerce a cell value to bool.

    Handles Excel booleans (True/False) and string representations
    ('TRUE'/'FALSE', 'Yes'/'No', '1'/'0').
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().upper()
    if s in ("TRUE", "YES", "1"):
        return True
    if s in ("FALSE", "NO", "0"):
        return False
    return None


def _int_val(value) -> Optional[int]:
    """Coerce a cell value to int, or None if blank / non-numeric."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


class DataLoader:
    """
    Reads Excel master data files and returns domain model instances.

    Usage::

        loader = DataLoader(data_dir="Data/master")
        teachers = loader.load_teachers()
        rooms = loader.load_rooms()
        subjects = loader.load_subjects()
        workloads = loader.load_workloads()
    """

    def __init__(self, data_dir: str = "Data/master"):
        self.data_dir = Path(data_dir)

    def _resolve_path(self, filename: str) -> Path:
        """Resolve a filename against the data directory (case-insensitive)."""
        path = self.data_dir / filename
        # Try exact match first
        if path.exists():
            return path
        # Try case-insensitive match (directory must exist)
        try:
            lower = filename.lower()
            for child in self.data_dir.iterdir():
                if child.name.lower() == lower:
                    return child
        except (FileNotFoundError, OSError) as exc:
            raise DataLoadError(
                f"Data directory not found: {self.data_dir}"
            ) from exc
        raise DataLoadError(
            f"File not found: {path}  (also tried case-insensitive match in {self.data_dir})"
        )

    def _open_workbook(self, filename: str) -> openpyxl.Workbook:
        """Open an Excel workbook, raising DataLoadError on failure."""
        path = self._resolve_path(filename)
        try:
            return openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:
            raise DataLoadError(f"Cannot read {path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Teachers
    # ------------------------------------------------------------------

    def load_teachers(self, filename: str = "Teachers.xlsx") -> List[Teacher]:
        """
        Load the teacher roster from ``Teachers.xlsx``.

        Expected columns: teacher_id, teacher_name, department, active, [designation].
        """
        wb = self._open_workbook(filename)
        ws = wb.active
        teachers: List[Teacher] = []

        # Inspect header row (row 1) to locate columns dynamically
        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        col_map = {}
        if header_row:
            for idx, cell in enumerate(header_row):
                if cell is not None:
                    col_map[str(cell).strip().lower().replace(" ", "_")] = idx

        id_idx = col_map.get("teacher_id", 0)
        name_idx = col_map.get("teacher_name", 1)
        dept_idx = col_map.get("department", 2)
        active_idx = col_map.get("active", 3)
        desig_idx = col_map.get("designation", None)

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not row or all(c is None for c in row):
                continue  # skip blank rows

            teacher_id = _str_val(row[id_idx]) if len(row) > id_idx else None
            teacher_name = _str_val(row[name_idx]) if len(row) > name_idx else None
            department = _str_val(row[dept_idx]) if len(row) > dept_idx else None
            active = _bool_val(row[active_idx]) if len(row) > active_idx else None
            designation = _str_val(row[desig_idx]) if (desig_idx is not None and len(row) > desig_idx) else ""

            if teacher_id is None:
                continue  # skip rows without an ID

            teachers.append(Teacher(
                teacher_id=teacher_id,
                teacher_name=teacher_name or "",
                department=department or "",
                active=active if active is not None else True,
                designation=designation or "",
            ))

        wb.close()
        return teachers

    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------

    def load_rooms(self, filename: str = "Rooms.xlsx") -> List[Room]:
        """
        Load the room inventory from ``Rooms.xlsx``.

        Expected columns: room_id, room_name, room_type, branch, is_shared, active.
        """
        wb = self._open_workbook(filename)
        ws = wb.active
        rooms: List[Room] = []

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not row or all(c is None for c in row):
                continue

            room_id = _str_val(row[0]) if len(row) > 0 else None
            room_name = _str_val(row[1]) if len(row) > 1 else None
            room_type_str = _str_val(row[2]) if len(row) > 2 else None
            branch = _str_val(row[3]) if len(row) > 3 else None
            is_shared = _bool_val(row[4]) if len(row) > 4 else None
            active = _bool_val(row[5]) if len(row) > 5 else None

            if room_id is None:
                continue

            # Parse room_type — store raw string if unrecognised; validation catches it.
            try:
                room_type = RoomType(room_type_str) if room_type_str else RoomType.LECTURE
            except ValueError:
                # Store with a sentinel so the validator can report the bad value.
                # We use a small wrapper to carry the raw string through.
                room_type = room_type_str  # type: ignore[assignment]

            rooms.append(Room(
                room_id=room_id,
                room_name=room_name or "",
                room_type=room_type,
                branch=branch if branch and branch.upper() != "NONE" else None,
                is_shared=is_shared if is_shared is not None else False,
                active=active if active is not None else True,
            ))

        wb.close()
        return rooms

    # ------------------------------------------------------------------
    # Subjects
    # ------------------------------------------------------------------

    def load_subjects(self, filename: str = "Subjects.xlsx") -> List[Subject]:
        """
        Load the subject catalogue from ``Subjects.xlsx``.

        Supports both the new format with ``short_name``:
            subject_id, subject_code, subject_name, short_name, branch, semester, active
        and legacy format without ``short_name``:
            subject_id, subject_code, subject_name, branch, semester, active
        """
        wb = self._open_workbook(filename)
        ws = wb.active
        subjects: List[Subject] = []

        # Inspect header row (row 1) to determine column positions dynamically
        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        col_map = {}
        if header_row:
            for idx, cell in enumerate(header_row):
                if cell is not None:
                    col_map[str(cell).strip().lower().replace(" ", "_")] = idx

        has_short_name_header = "short_name" in col_map
        id_idx = col_map.get("subject_id", 0)
        code_idx = col_map.get("subject_code", 1)
        name_idx = col_map.get("subject_name", 2)
        short_name_idx = col_map.get("short_name", 3 if has_short_name_header else None)
        branch_idx = col_map.get("branch", 4 if has_short_name_header else 3)
        sem_idx = col_map.get("semester", 5 if has_short_name_header else 4)
        active_idx = col_map.get("active", 6 if has_short_name_header else 5)

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not row or all(c is None for c in row):
                continue

            # Fallback heuristic if no header row was found: 7 columns means short_name is column 3
            if not col_map and len(row) >= 7:
                id_idx, code_idx, name_idx, short_name_idx, branch_idx, sem_idx, active_idx = 0, 1, 2, 3, 4, 5, 6

            subject_id = _str_val(row[id_idx]) if len(row) > id_idx else None
            subject_code = _str_val(row[code_idx]) if len(row) > code_idx else None
            subject_name = _str_val(row[name_idx]) if len(row) > name_idx else None
            short_name = (
                _str_val(row[short_name_idx])
                if (short_name_idx is not None and len(row) > short_name_idx)
                else None
            )
            branch = _str_val(row[branch_idx]) if len(row) > branch_idx else None
            semester = _int_val(row[sem_idx]) if len(row) > sem_idx else None
            active = _bool_val(row[active_idx]) if len(row) > active_idx else None

            if subject_id is None:
                continue

            # Human-readable timetable display fallback
            resolved_short_name = short_name or subject_code or subject_name or subject_id

            subjects.append(Subject(
                subject_id=subject_id,
                subject_code=subject_code or "",
                subject_name=subject_name or "",
                branch=branch or "",
                semester=semester if semester is not None else 0,
                active=active if active is not None else True,
                short_name=resolved_short_name or "",
            ))

        wb.close()
        return subjects

    # ------------------------------------------------------------------
    # Workloads
    # ------------------------------------------------------------------

    def load_workloads(self, filename: str = "Workloads.xlsx") -> List[Workload]:
        """
        Load workload entries from ``Workloads.xlsx``.

        Expected columns: workload_id, subject_id, branch, semester,
            lecture_periods_per_week, practical_periods_per_week, total_periods_per_week.
        """
        wb = self._open_workbook(filename)
        ws = wb.active
        workloads: List[Workload] = []

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not row or all(c is None for c in row):
                continue

            workload_id = _str_val(row[0]) if len(row) > 0 else None
            subject_id = _str_val(row[1]) if len(row) > 1 else None
            branch = _str_val(row[2]) if len(row) > 2 else None
            semester = _int_val(row[3]) if len(row) > 3 else None
            lec = _int_val(row[4]) if len(row) > 4 else None
            prac = _int_val(row[5]) if len(row) > 5 else None
            total = _int_val(row[6]) if len(row) > 6 else None

            if workload_id is None:
                continue

            workloads.append(Workload(
                workload_id=workload_id,
                subject_id=subject_id or "",
                branch=branch or "",
                semester=semester if semester is not None else 0,
                lecture_periods_per_week=lec if lec is not None else 0,
                practical_periods_per_week=prac if prac is not None else 0,
                total_periods_per_week=total if total is not None else 0,
            ))

        wb.close()
        return workloads
