"""
Workload domain model.

Represents the weekly lecture + practical periods for a single subject.
Schema defined in DATA_SCHEMA.md §2.4.
"""

from dataclasses import dataclass


@dataclass
class Workload:
    """
    One row from Workloads.xlsx.

    Attributes:
        workload_id:               Unique sequential ID, e.g. ``W001``.
        subject_id:                FK → Subjects.xlsx, e.g. ``SUB001``.
        branch:                    Branch code (denormalised from Subjects).
        semester:                  Semester number (denormalised).
        lecture_periods_per_week:  Weekly lecture periods. ``0`` if practical-only.
        practical_periods_per_week: Weekly practical periods. ``0`` if theory-only.
        total_periods_per_week:    ``lecture + practical`` total.
    """
    workload_id: str
    subject_id: str
    branch: str
    semester: int
    lecture_periods_per_week: int
    practical_periods_per_week: int
    total_periods_per_week: int
