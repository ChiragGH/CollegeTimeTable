"""
Timetable setup module.

Implements the pre-scheduling workflow: session creation, section
management, teacher-subject assignments, and cascading data filters.

Setup data is **transient** -- it belongs to a scheduling session,
not to permanent master data (PROJECT_SPEC.md §6).
"""

from app.setup.filters import SetupFilters
from app.setup.session_manager import SessionManager
from app.setup.assignment_manager import AssignmentManager

__all__ = [
    "SetupFilters",
    "SessionManager",
    "AssignmentManager",
]
