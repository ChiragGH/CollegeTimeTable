"""
Timetable conflict detection engine.

Provides 8 reusable constraint-checker functions and the
:func:`is_valid_assignment` orchestrator that returns structured
conflict information.

Constraint mapping (from ARCHITECTURE.md §3.5):

    C1  check_teacher_overlap     -- No teacher double-booking
    C2  check_room_overlap        -- No room double-booking
    C3  check_section_overlap     -- No section double-booking
    C4  check_group_overlap       -- No group double-booking within section
    C5  check_consecutive_slots   -- Blocks must be consecutive, same day,
                                     no lunch spanning
    C6  check_g1_g2_sync          -- Parallel G1/G2 must share same slots
    C7a check_room_type_validity  -- Room type must match activity type
    C7b check_room_branch_validity -- LAB rooms must match assignment branch
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.models.room import Room
from app.models.placement import Placement
from app.models.slot import TimeSlot
from app.models.enums import ActivityType, RoomType, Day
from app.engine.state import ScheduleState


# ---- Lunch break configuration ----
# Slots 1-4 are before lunch, 5-7 are after.
# A block that includes both slot 4 and slot 5 spans the lunch break.
LAST_SLOT_BEFORE_LUNCH = 4
FIRST_SLOT_AFTER_LUNCH = 5


# ---- Activity --> valid room types ----
ACTIVITY_ROOM_MAP: Dict[ActivityType, List[RoomType]] = {
    ActivityType.LECTURE:   [RoomType.LECTURE],
    ActivityType.PRACTICAL: [RoomType.LAB],
    ActivityType.WORKSHOP:  [RoomType.WORKSHOP],
    ActivityType.DRAWING:   [RoomType.DRAWING_HALL],
    ActivityType.SCA:       [RoomType.LECTURE],
}


# ====================================================================
# Conflict types and data structures
# ====================================================================

class ConflictType(Enum):
    """Enumeration of all conflict types the engine can detect."""
    TEACHER_CONFLICT = "TEACHER_CONFLICT"
    ROOM_CONFLICT = "ROOM_CONFLICT"
    SECTION_CONFLICT = "SECTION_CONFLICT"
    GROUP_CONFLICT = "GROUP_CONFLICT"
    INVALID_ROOM_TYPE = "INVALID_ROOM_TYPE"
    INVALID_ROOM_BRANCH = "INVALID_ROOM_BRANCH"
    NON_CONSECUTIVE_SLOTS = "NON_CONSECUTIVE_SLOTS"
    DIFFERENT_DAYS = "DIFFERENT_DAYS"
    LUNCH_SPAN = "LUNCH_SPAN"
    G1_G2_SYNC = "G1_G2_SYNC"


@dataclass
class Conflict:
    """
    A single detected conflict with structured details.

    The ``to_dict()`` output matches the user's requested format::

        {
            "type": "TEACHER_CONFLICT",
            "teacher_id": "T001",
            "slot": "MON_2",
            "message": "Teacher T001 already scheduled at MON_2"
        }
    """
    type: ConflictType
    message: str
    slot: Optional[str] = None
    teacher_id: Optional[str] = None
    room_id: Optional[str] = None
    section: Optional[str] = None
    group: Optional[str] = None
    subject_id: Optional[str] = None
    expected_slots: Optional[str] = None
    actual_slots: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a flat dict, omitting None fields."""
        d: Dict[str, Any] = {"type": self.type.value}
        for attr in (
            "slot", "teacher_id", "room_id", "section", "group",
            "subject_id", "expected_slots", "actual_slots", "message",
        ):
            val = getattr(self, attr)
            if val is not None:
                d[attr] = val
        return d

    def __str__(self) -> str:
        parts = [f"[{self.type.value}]"]
        if self.slot:
            parts.append(f"slot={self.slot}")
        if self.teacher_id:
            parts.append(f"teacher={self.teacher_id}")
        if self.room_id:
            parts.append(f"room={self.room_id}")
        if self.section:
            parts.append(f"section={self.section}")
        if self.group:
            parts.append(f"group={self.group}")
        parts.append(f"-- {self.message}")
        return " ".join(parts)


@dataclass
class ConflictReport:
    """
    Result of :func:`is_valid_assignment`.

    Attributes:
        valid:     ``True`` if no conflicts were detected.
        conflicts: List of all detected conflicts.
    """
    valid: bool
    conflicts: List[Conflict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to the JSON-compatible format requested by the user::

            {
                "valid": false,
                "conflicts": [
                    {"type": "TEACHER_CONFLICT", "teacher_id": "T001", "slot": "MON_2", ...}
                ]
            }
        """
        return {
            "valid": self.valid,
            "conflicts": [c.to_dict() for c in self.conflicts],
        }


# ====================================================================
# Individual checker functions (reusable)
# ====================================================================

def check_teacher_overlap(
    placement: Placement,
    state: ScheduleState,
) -> List[Conflict]:
    """
    C1: Detect teacher double-booking.

    Returns a Conflict for each slot where the teacher is already occupied.
    """
    teacher_id = placement.assignment.teacher_id
    conflicting_slots = state.get_teacher_conflicts(teacher_id, placement.slots)

    return [
        Conflict(
            type=ConflictType.TEACHER_CONFLICT,
            message=f"Teacher {teacher_id} already scheduled at {slot}.",
            slot=str(slot),
            teacher_id=teacher_id,
        )
        for slot in conflicting_slots
    ]


def check_room_overlap(
    placement: Placement,
    state: ScheduleState,
) -> List[Conflict]:
    """
    C2: Detect room double-booking.

    Returns a Conflict for each slot where the room is already occupied.
    """
    room_id = placement.room_id
    conflicting_slots = state.get_room_conflicts(room_id, placement.slots)

    return [
        Conflict(
            type=ConflictType.ROOM_CONFLICT,
            message=f"Room {room_id} already occupied at {slot}.",
            slot=str(slot),
            room_id=room_id,
        )
        for slot in conflicting_slots
    ]


def check_section_overlap(
    placement: Placement,
    state: ScheduleState,
) -> List[Conflict]:
    """
    C3: Detect section-level double-booking.

    A section conflict occurs when the FULL section (group=ALL) is
    already busy at a slot.  This applies regardless of the proposed
    placement's group.
    """
    a = placement.assignment
    conflicts = []

    # Check only against "ALL" placements for section-level conflicts
    sec_groups = state.section_slots.get(a.section, {})
    all_occupied = sec_groups.get("ALL", set())

    for slot in placement.slots:
        if slot in all_occupied:
            conflicts.append(Conflict(
                type=ConflictType.SECTION_CONFLICT,
                message=(
                    f"Section {a.section} has a full-section activity at {slot}."
                ),
                slot=str(slot),
                section=a.section,
            ))

    return conflicts


def check_group_overlap(
    placement: Placement,
    state: ScheduleState,
) -> List[Conflict]:
    """
    C3/C4: Detect group-level double-booking within a section.

    Overlap logic (per ARCHITECTURE.md §3.5, C3):
    - ``ALL`` proposed: conflicts with any existing G1, G2, or ALL
    - ``G1``  proposed: conflicts with existing G1 or ALL (not G2)
    - ``G2``  proposed: conflicts with existing G2 or ALL (not G1)
    """
    a = placement.assignment
    section_conflicts = state.get_section_conflicts(
        a.section, a.group, placement.slots
    )

    return [
        Conflict(
            type=ConflictType.GROUP_CONFLICT,
            message=(
                f"Group {a.group} of section {a.section} conflicts with "
                f"existing group {conf_group} at {slot}."
            ),
            slot=str(slot),
            section=a.section,
            group=conf_group,
        )
        for conf_group, slot in section_conflicts
    ]


def check_room_type_validity(
    placement: Placement,
    rooms: Dict[str, Room],
) -> List[Conflict]:
    """
    C7a: Validate that the room type matches the activity type.

    Rules (ARCHITECTURE.md §3.5):
    - LECTURE   --> room_type must be LECTURE
    - PRACTICAL --> room_type must be LAB
    - WORKSHOP  --> room_type must be WORKSHOP
    - DRAWING   --> room_type must be DRAWING_HALL
    """
    if placement.assignment.activity_type == ActivityType.SCA:
        if placement.room_id in ("", "—", "NONE", None) or placement.room_id not in rooms:
            return []

    room = rooms.get(placement.room_id)
    if room is None:
        return [Conflict(
            type=ConflictType.INVALID_ROOM_TYPE,
            message=f"Room '{placement.room_id}' not found.",
            room_id=placement.room_id,
        )]

    activity = placement.assignment.activity_type
    valid_types = ACTIVITY_ROOM_MAP.get(activity, [])

    if not isinstance(room.room_type, RoomType):
        return [Conflict(
            type=ConflictType.INVALID_ROOM_TYPE,
            message=f"Room '{room.room_id}' has invalid room_type '{room.room_type}'.",
            room_id=room.room_id,
        )]

    if room.room_type not in valid_types:
        return [Conflict(
            type=ConflictType.INVALID_ROOM_TYPE,
            message=(
                f"Activity {activity.value} requires room type "
                f"{[rt.value for rt in valid_types]}, but room "
                f"'{room.room_id}' ({room.room_name}) is {room.room_type.value}."
            ),
            room_id=room.room_id,
        )]

    return []


def check_room_branch_validity(
    placement: Placement,
    rooms: Dict[str, Room],
) -> List[Conflict]:
    """
    C7b: Validate branch-specific room usage.

    LAB rooms must belong to the same branch as the assignment.
    Shared rooms (LECTURE, DRAWING_HALL, WORKSHOP) have no branch constraint.
    """
    room = rooms.get(placement.room_id)
    if room is None:
        return []  # Already reported by check_room_type_validity

    if not isinstance(room.room_type, RoomType):
        return []

    # Only LAB rooms have branch restrictions
    if room.room_type != RoomType.LAB:
        return []

    assignment_branch = placement.assignment.branch
    if room.branch and room.branch != assignment_branch:
        return [Conflict(
            type=ConflictType.INVALID_ROOM_BRANCH,
            message=(
                f"LAB room '{room.room_id}' ({room.room_name}) belongs to "
                f"branch {room.branch}, but assignment is for {assignment_branch}."
            ),
            room_id=room.room_id,
            section=placement.assignment.section,
        )]

    return []


def check_consecutive_slots(
    placement: Placement,
    allow_lunch_span: bool = False,
) -> List[Conflict]:
    """
    C5: Validate that practical/workshop blocks use consecutive slots.

    Checks:
    1. All slots must be on the same day.
    2. Periods must be consecutive (no gaps).
    3. The block must not span the lunch break (slots 4-->5)
       unless ``allow_lunch_span`` is True.

    Single-slot placements (block_size=1) always pass.
    """
    slots = placement.slots
    if len(slots) <= 1:
        return []

    conflicts = []

    # 1. All slots must be on the same day
    days = {s.day for s in slots}
    if len(days) > 1:
        conflicts.append(Conflict(
            type=ConflictType.DIFFERENT_DAYS,
            message=(
                f"Block spans multiple days: {sorted(d.name for d in days)}. "
                f"All slots in a block must be on the same day."
            ),
        ))
        return conflicts  # Can't check consecutiveness across days

    # 2. Periods must be consecutive
    periods = sorted(s.period for s in slots)
    for i in range(len(periods) - 1):
        if periods[i + 1] != periods[i] + 1:
            conflicts.append(Conflict(
                type=ConflictType.NON_CONSECUTIVE_SLOTS,
                message=(
                    f"Slots are not consecutive: periods {periods}. "
                    f"Gap between slot {periods[i]} and {periods[i + 1]}."
                ),
                slot=str(slots[0]),
            ))
            break

    # 3. No lunch spanning
    if not allow_lunch_span:
        min_period = periods[0]
        max_period = periods[-1]
        if min_period <= LAST_SLOT_BEFORE_LUNCH and max_period >= FIRST_SLOT_AFTER_LUNCH:
            conflicts.append(Conflict(
                type=ConflictType.LUNCH_SPAN,
                message=(
                    f"Block spans the lunch break (slots {min_period}-{max_period}). "
                    f"Periods 4 and 5 are separated by lunch (13:00-14:00)."
                ),
                slot=str(slots[0]),
            ))

    return conflicts


def check_g1_g2_sync(
    placement: Placement,
    state: ScheduleState,
) -> List[Conflict]:
    """
    C6: Validate parallel G1/G2 synchronisation.

    When a section is split into groups, the G1 and G2 practicals for
    the **same subject** must occupy the **same time-slot range** (they
    run in parallel in different rooms with different teachers).

    If G1 is already placed at certain slots, G2 for the same
    subject-section must be placed at exactly those slots, and vice versa.
    """
    a = placement.assignment

    # Only applies to group-specific (non-ALL) placements
    if a.group == "ALL":
        return []

    # Only applies to block activities (practicals, workshops, etc.)
    if a.activity_type == ActivityType.LECTURE:
        return []

    # Determine the partner group
    partner_group = "G2" if a.group == "G1" else "G1"

    # Find existing placements for the same subject-section in the partner group
    existing = state.get_placements_for_subject_section(a.subject_id, a.section)
    partner_placements = [
        p for p in existing
        if p.assignment.group == partner_group
    ]

    if not partner_placements:
        return []  # No partner placed yet; nothing to check

    # Check that the proposed slots match the partner's slots
    proposed_slots = set(placement.slots)

    conflicts = []
    for pp in partner_placements:
        partner_slots = set(pp.slots)
        if proposed_slots != partner_slots:
            conflicts.append(Conflict(
                type=ConflictType.G1_G2_SYNC,
                message=(
                    f"G1/G2 sync violation for subject {a.subject_id} "
                    f"section {a.section}: {a.group} proposed at "
                    f"{[str(s) for s in placement.slots]}, but "
                    f"{partner_group} is at "
                    f"{[str(s) for s in pp.slots]}."
                ),
                section=a.section,
                group=a.group,
                subject_id=a.subject_id,
                expected_slots=", ".join(str(s) for s in sorted(pp.slots, key=lambda s: (s.day.name, s.period))),
                actual_slots=", ".join(str(s) for s in sorted(placement.slots, key=lambda s: (s.day.name, s.period))),
            ))

    return conflicts


# ====================================================================
# Orchestrator
# ====================================================================

def is_valid_assignment(
    placement: Placement,
    state: ScheduleState,
    rooms: Dict[str, Room],
    allow_lunch_span: bool = False,
) -> ConflictReport:
    """
    Run all conflict checks on a proposed placement.

    This is the main entry point for the conflict-validation engine.
    It runs all 8 checker functions and returns a structured
    :class:`ConflictReport`.

    Args:
        placement:        The proposed placement to validate.
        state:            Current schedule state (existing placements).
        rooms:            Room lookup dict (room_id --> Room).
        allow_lunch_span: If True, allow blocks to span the lunch break.

    Returns:
        A :class:`ConflictReport` with ``valid=True`` if no conflicts,
        or ``valid=False`` with a list of all detected conflicts.

    Example::

        report = is_valid_assignment(placement, state, rooms)
        if not report.valid:
            for c in report.conflicts:
                print(c)
        # Or as JSON:
        print(report.to_dict())
    """
    all_conflicts: List[Conflict] = []

    # C1: Teacher overlap
    all_conflicts.extend(check_teacher_overlap(placement, state))

    # C2: Room overlap
    all_conflicts.extend(check_room_overlap(placement, state))

    # C3: Section overlap (full-section vs any)
    all_conflicts.extend(check_section_overlap(placement, state))

    # C4: Group overlap (within section)
    all_conflicts.extend(check_group_overlap(placement, state))

    # C5: Consecutive-slot block validity
    all_conflicts.extend(check_consecutive_slots(placement, allow_lunch_span))

    # C6: G1/G2 parallel sync
    all_conflicts.extend(check_g1_g2_sync(placement, state))

    # C7a: Room type matches activity type
    all_conflicts.extend(check_room_type_validity(placement, rooms))

    # C7b: Branch-specific room usage
    all_conflicts.extend(check_room_branch_validity(placement, rooms))

    return ConflictReport(
        valid=len(all_conflicts) == 0,
        conflicts=all_conflicts,
    )
