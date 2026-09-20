"""
Enumerations used across the domain models.

Defined per ARCHITECTURE.md §3.1.
"""

from enum import Enum


class RoomType(Enum):
    """Valid room types from DATA_SCHEMA.md §2.2."""
    LAB = "LAB"
    LECTURE = "LECTURE"
    DRAWING_HALL = "DRAWING_HALL"
    WORKSHOP = "WORKSHOP"


class ActivityType(Enum):
    """Activity types from PROJECT_SPEC.md §4."""
    LECTURE = "LECTURE"
    PRACTICAL = "PRACTICAL"
    WORKSHOP = "WORKSHOP"
    DRAWING = "DRAWING"
    PROJECT = "PROJECT"
    TRAINING = "TRAINING"
    SCA = "SCA"


class Day(Enum):
    """Working days — Monday through Friday."""
    MON = "Monday"
    TUE = "Tuesday"
    WED = "Wednesday"
    THU = "Thursday"
    FRI = "Friday"
