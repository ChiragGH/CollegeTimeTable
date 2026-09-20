"""
Section domain model.

Represents a student cohort within a branch-semester.
Sections are created during timetable setup (PROJECT_SPEC.md §5),
NOT stored as permanent master data.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Section:
    """
    A section of students in a specific branch-semester.

    Attributes:
        branch:   Branch code, e.g. ``CSE``.
        semester:  Semester number (1--6).
        label:    Section label, e.g. ``A``, ``B``.
        groups:   Subgroups for practicals, e.g. ``["G1", "G2"]``.
    """
    branch: str
    semester: int
    label: str
    groups: List[str] = field(default_factory=lambda: ["G1", "G2"])

    @property
    def section_id(self) -> str:
        """Composite identifier, e.g. ``CSE-3-A``."""
        return f"{self.branch}-{self.semester}-{self.label}"

    def __str__(self) -> str:
        return self.section_id
