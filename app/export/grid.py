"""
Timetable time grid.

Single source of truth for the weekly grid layout used by every
exporter (CSV / XLSX / PDF), per PROJECT_SPEC.md §3:

    Monday--Friday, 7 periods/day, 60 minutes each (12-hour clock, no AM/PM).

    Slots 1--4 : 9:00--1:00
    RECESS     : 1:00--2:00
    Slots 5--7 : 2:00--5:00
"""

from typing import Dict, List, Optional, Tuple

from app.models.enums import Day

# ----------------------------------------------------------------------
# Period times
# ----------------------------------------------------------------------

#: period number → (start_time, end_time) in 12-hour format (no AM/PM)
PERIOD_TIMES: Dict[int, Tuple[str, str]] = {
    1: ("9:00", "10:00"),
    2: ("10:00", "11:00"),
    3: ("11:00", "12:00"),
    4: ("12:00", "1:00"),
    5: ("2:00", "3:00"),
    6: ("3:00", "4:00"),
    7: ("4:00", "5:00"),
}

#: The lunch/recess break sits between these periods (i.e. after period 4).
LUNCH_AFTER_PERIOD: int = 4

LUNCH_START: str = "1:00"
LUNCH_END: str = "2:00"

PERIODS_PER_DAY: int = 7

#: Ordered period numbers, morning before recess, afternoon after.
PERIOD_ORDER: Tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)

#: Ordered working days.
DAYS: Tuple[Day, ...] = (
    Day.MON, Day.TUE, Day.WED, Day.THU, Day.FRI,
)

#: Grid column identifiers, in render order.  ``LUNCH`` / ``RECESS`` is a real column
#: so the break is visible in every view; period columns keep their
#: natural numbering for machine readability.
COL_LUNCH = "RECESS"
COL_RECESS = COL_LUNCH

GRID_COLUMNS: Tuple[str, ...] = (
    "1", "2", "3", "4", COL_LUNCH, "5", "6", "7",
)


def period_time(period: int) -> str:
    """``9:00-10:00`` style label for a period column in 12-hour format."""
    start, end = PERIOD_TIMES[period]
    return f"{start}-{end}"


def period_header(period: int) -> str:
    """Short two-line header label, e.g. ``P1\\n9:00-10:00``."""
    return f"P{period}\n{period_time(period)}"


def period_time_range(period: int) -> Tuple[str, str]:
    """(start, end) clock times for a period."""
    return PERIOD_TIMES[period]


def lunch_label() -> str:
    return f"RECESS {LUNCH_START}-{LUNCH_END}"


def slots_are_consecutive(slots: List) -> bool:
    """
    True if the slots form a valid teaching block: same day, strictly
    increasing periods, and not crossing the lunch break.
    """
    if not slots:
        return False
    if len({s.day for s in slots}) != 1:
        return False
    periods = sorted(s.period for s in slots)
    for a, b in zip(periods, periods[1:]):
        if b != a + 1:
            return False
        if a == LUNCH_AFTER_PERIOD:  # 4 → 5 would jump the lunch break
            return False
    return True


def day_sort_key(day: Day) -> int:
    """Position of a Day in the working week."""
    try:
        return [d.value for d in DAYS].index(day.value)
    except ValueError:
        return len(DAYS)


def column_index(period: int) -> Optional[int]:
    """Position of a period in :data:`GRID_COLUMNS` (None if invalid)."""
    key = str(period)
    try:
        return GRID_COLUMNS.index(key)
    except ValueError:
        return None
