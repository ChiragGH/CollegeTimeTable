"""
Room domain model.

Represents a single room / lab / hall in the college inventory.
Schema defined in DATA_SCHEMA.md §2.2.
"""

from dataclasses import dataclass
from typing import Optional

from app.models.enums import RoomType


@dataclass
class Room:
    """
    One row from Rooms.xlsx.

    Attributes:
        room_id:    Unique identifier, e.g. ``R001``.
        room_name:  Display name, e.g. ``CC1``, ``L5``, ``DH2``.
        room_type:  One of :class:`RoomType` (LAB, LECTURE, DRAWING_HALL, WORKSHOP).
        branch:     Owning branch for labs (e.g. ``CSE``). ``None`` for shared rooms.
        is_shared:  ``True`` for lecture halls, drawing halls, and workshop rooms.
        active:     ``True`` if available for scheduling.
    """
    room_id: str
    room_name: str
    room_type: RoomType
    branch: Optional[str]
    is_shared: bool
    active: bool
