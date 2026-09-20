"""
TimeSlot value object.

Represents a single (day, period) pair in the weekly timetable grid.
Defined in ARCHITECTURE.md §3.1.
"""

from dataclasses import dataclass

from app.models.enums import Day


@dataclass(frozen=True)
class TimeSlot:
    """
    An immutable (day, period) pair.

    Attributes:
        day:    Day of the week (MON--FRI).
        period: Period number (1--7, excluding lunch between 4 and 5).

    The string representation uses the format ``MON_2`` for easy readability
    and JSON serialisation.
    """
    day: Day
    period: int

    def __str__(self) -> str:
        return f"{self.day.name}_{self.period}"

    def __repr__(self) -> str:
        return f"TimeSlot({self.day.name}, {self.period})"
