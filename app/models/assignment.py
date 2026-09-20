"""
Assignment domain model.

Represents a single teacher-subject-section assignment for the current
timetable setup.  Assignments are **transient** -- they belong to a
scheduling session, NOT to permanent master data (PROJECT_SPEC.md §6).

Schema defined in DATA_SCHEMA.md §3.1.
"""

from dataclasses import dataclass
from typing import Optional

from app.models.enums import ActivityType, RoomType


@dataclass
class Assignment:
    """
    One row from Setup.xlsx -- a teaching assignment unit.

    Attributes:
        assignment_id:     Unique ID, e.g. ``A001``.
        session_id:        Parent session identifier, e.g. ``2026-odd``.
        teacher_id:        FK to Teachers.xlsx.
        subject_id:        FK to Subjects.xlsx.
        branch:            Target branch code.
        semester:          Target semester (1--6).
        section:           Section label, e.g. ``A``.
        group:             ``G1``, ``G2``, or ``ALL`` (lectures use ALL).
        activity_type:     LECTURE, PRACTICAL, WORKSHOP, or DRAWING.
        weekly_periods:    Total periods per week for this assignment.
        room_id:           Preferred/assigned room (optional, FK to Rooms.xlsx).
        room_type:         Preferred room type for filtering (optional).
        block_size:        Consecutive periods per session (1 for lectures).
        sessions_per_week: Number of sessions to schedule per week.
    """
    assignment_id: str
    session_id: str
    teacher_id: str
    subject_id: str
    branch: str
    semester: int
    section: str
    group: str
    activity_type: ActivityType
    weekly_periods: int
    room_id: Optional[str] = None
    room_type: Optional[RoomType] = None
    block_size: int = 1
    sessions_per_week: int = 0
