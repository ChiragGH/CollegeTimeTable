"""
Teacher domain model.

Represents a single teacher/instructor in the college roster.
Schema defined in DATA_SCHEMA.md §2.1.
"""

from dataclasses import dataclass


@dataclass
class Teacher:
    """
    One row from Teachers.xlsx.

    Attributes:
        teacher_id:   Unique identifier, e.g. ``T001``.
        teacher_name: Short name / initials, e.g. ``RJS``.
        department:   Home department — one of the 7 valid codes.
        active:       ``True`` if available for assignment this term.
        designation:  Optional designation / rank, e.g. ``Assistant Professor``.
    """
    teacher_id: str
    teacher_name: str
    department: str
    active: bool = True
    designation: str = ""
