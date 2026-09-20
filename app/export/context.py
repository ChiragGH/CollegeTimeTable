"""
Export context: reference data needed to render human-readable views.

The context carries the master-data dictionaries (teachers, rooms,
subjects), session metadata, and the declaration of sections/groups so
that view builders can resolve IDs into display names with graceful
fallbacks when a lookup is missing.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from app.models.section import Section
from app.models.subject import Subject
from app.models.teacher import Teacher
from app.models.room import Room
from app.models.enums import RoomType


@dataclass
class ExportContext:
    """
    Everything the exporters need besides the placements themselves.

    Attributes:
        session_id:    Session identifier.
        academic_year: e.g. ``2026-27``.
        branch:        Branch code for the session, e.g. ``CSE``.
        semester:      Semester number.
        sections:      Section metadata (labels + groups).
        teachers:      teacher_id → Teacher.
        rooms:         room_id → Room.
        subjects:      subject_id → Subject.
        college_name:  Display name used in report headers.
        generated_at:  Timestamp written into exports.
    """
    session_id: str = ""
    academic_year: str = ""
    branch: str = ""
    semester: Optional[int] = None
    sections: List[Section] = field(default_factory=list)
    teachers: Dict[str, Teacher] = field(default_factory=dict)
    rooms: Dict[str, Room] = field(default_factory=dict)
    subjects: Dict[str, Subject] = field(default_factory=dict)
    college_name: str = "College Timetable System (CRG)"
    generated_at: str = field(
        default_factory=lambda: datetime.now().strftime("%d %b %Y, %H:%M")
    )

    # ------------------------------------------------------------------
    # Display resolvers (never raise — fall back to raw IDs)
    # ------------------------------------------------------------------

    def teacher_name(self, teacher_id: str) -> str:
        t = self.teachers.get(teacher_id)
        return t.teacher_name if t else teacher_id

    def teacher_department(self, teacher_id: str) -> str:
        t = self.teachers.get(teacher_id)
        return t.department if t else ""

    def room_name(self, room_id: str) -> str:
        r = self.rooms.get(room_id)
        return r.room_name if r else room_id

    def room_type(self, room_id: str):
        r = self.rooms.get(room_id)
        if r is None:
            return None
        return r.room_type.value if isinstance(r.room_type, RoomType) else r.room_type

    def room_is_lab(self, room_id: str) -> bool:
        return self.room_type(room_id) == RoomType.LAB.value

    def subject_code(self, subject_id: str) -> str:
        s = self.subjects.get(subject_id)
        return s.subject_code if s else ""

    def subject_name(self, subject_id: str) -> str:
        s = self.subjects.get(subject_id)
        return s.subject_name if s else subject_id

    def subject_display(self, subject_id: str, max_len: int = 34) -> str:
        """``3.2 Data Structures`` style single-line display name."""
        s = self.subjects.get(subject_id)
        if s:
            text = f"{s.subject_code} {s.subject_name}"
        else:
            text = subject_id
        return _truncate(text, max_len)

    def subject_short_name(self, subject_id: str) -> str:
        """Human-readable timetable display label, e.g. ``DE``, ``OS``."""
        s = self.subjects.get(subject_id)
        if s and getattr(s, "short_name", None):
            return s.short_name
        if s and s.subject_code:
            return s.subject_code
        if s and s.subject_name:
            return s.subject_name
        return subject_id

    # ------------------------------------------------------------------
    # Section helpers
    # ------------------------------------------------------------------

    def section_label(self, section: str) -> str:
        """``CSE-3-A`` — the section key used across all exports."""
        return section

    def section_title(self, section: str) -> str:
        """Human title, e.g. ``Section CSE-3-A``."""
        return f"Section {section}"

    def groups_of_section(self, section: str) -> List[str]:
        """Declared groups for a section; falls back to G1/G2 if used."""
        for s in self.sections:
            if s.label == section or s.section_id == section:
                return list(s.groups)
        return []

    @staticmethod
    def class_key(branch: str, semester: int) -> str:
        """Stable class identifier, e.g. ``CSE-3``."""
        return f"{branch}-{semester}"

    @staticmethod
    def class_title(branch: str, semester: int) -> str:
        """Human class title, e.g. ``CSE — Semester 3``."""
        return f"{branch} — Semester {semester}"


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"
