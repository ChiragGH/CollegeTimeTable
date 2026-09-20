"""
Subject domain model.

Represents a single subject offering (unique by branch + semester + subject code).
Schema defined in DATA_SCHEMA.md §2.3.
"""

from dataclasses import dataclass


@dataclass
class Subject:
    """
    One row from Subjects.xlsx.

    Attributes:
        subject_id:   Unique sequential ID, e.g. ``SUB001``.
        subject_code: Code from study scheme, e.g. ``1.4``.
        subject_name: Full name, e.g. ``Fundamentals of IT``.
        branch:       Branch code — ``CSE``, ``ME``, ``ECE``, ``Civil``, ``EE``.
        semester:     Semester number (1–6).
        active:       ``True`` if currently offered.
        short_name:   Timetable display label, e.g. ``DE``, ``OS``.
    """
    subject_id: str
    subject_code: str
    subject_name: str
    branch: str
    semester: int
    active: bool = True
    short_name: str = ""

    def __post_init__(self):
        if not self.short_name:
            self.short_name = self.subject_code or self.subject_name or self.subject_id
