"""
Placement domain model.

Represents a scheduled activity: an Assignment placed at specific
TimeSlots in a specific Room.  Defined in ARCHITECTURE.md §3.1.
"""

from dataclasses import dataclass
from typing import List

from app.models.assignment import Assignment
from app.models.slot import TimeSlot


@dataclass
class Placement:
    """
    An Assignment placed into the timetable grid.

    Attributes:
        placement_id: Unique identifier for this placement.
        assignment:   The parent Assignment being scheduled.
        slots:        List of consecutive TimeSlots occupied by this session.
        room_id:      The resolved room for this placement.
    """
    placement_id: str
    assignment: Assignment
    slots: List[TimeSlot]
    room_id: str
