"""
Domain models for the College Timetable system.

All entities are pure data containers (dataclasses) with no I/O logic.
"""

from app.models.enums import RoomType, ActivityType, Day
from app.models.teacher import Teacher
from app.models.room import Room
from app.models.subject import Subject
from app.models.workload import Workload
from app.models.section import Section
from app.models.assignment import Assignment
from app.models.session import TimetableSetup
from app.models.slot import TimeSlot
from app.models.placement import Placement
from app.models.branch import Branch, CANONICAL_BRANCHES, normalize_branch
from app.models.timetable import Timetable, TimetablePlacement, TimetableHistoryEntry

__all__ = [
    "RoomType",
    "ActivityType",
    "Day",
    "Teacher",
    "Room",
    "Subject",
    "Workload",
    "Section",
    "Assignment",
    "TimetableSetup",
    "TimeSlot",
    "Placement",
    "Branch",
    "CANONICAL_BRANCHES",
    "normalize_branch",
    "Timetable",
    "TimetablePlacement",
    "TimetableHistoryEntry",
]
