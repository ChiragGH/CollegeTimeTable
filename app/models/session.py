"""
TimetableSetup domain model.

Container for all the data needed to generate one timetable:
session metadata, sections, and teaching assignments.
"""

from dataclasses import dataclass, field
from typing import List

from app.models.section import Section
from app.models.assignment import Assignment


@dataclass
class TimetableSetup:
    """
    A complete timetable setup for one branch-semester combination.

    Attributes:
        session_id:     Unique session identifier, e.g. ``2026-27_CSE_Sem3``.
        academic_year:  Academic year label, e.g. ``2026-27``.
        branch:         Branch code, e.g. ``CSE``.
        semester:       Semester number (1--6).
        sections:       List of sections created for this setup.
        assignments:    Teaching assignments (teacher-subject mappings).
        created_at:     ISO-8601 timestamp of creation.
    """
    session_id: str
    academic_year: str
    branch: str
    semester: int
    sections: List[Section] = field(default_factory=list)
    assignments: List[Assignment] = field(default_factory=list)
    created_at: str = ""
