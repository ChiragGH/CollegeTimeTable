"""
Slot allocator.

Generates valid (day, start_period, room) candidates for schedule
requests, respecting the college time grid and pre-computed room
eligibility.

College time grid (from PROJECT_SPEC.md):

    Monday--Friday
    Slots 1--4:  09:00--13:00 (morning)
    LUNCH:       13:00--14:00
    Slots 5--7:  14:00--17:00 (afternoon)

Valid block positions for block_size=2:

    Start 1 → slots 1,2  ✓
    Start 2 → slots 2,3  ✓
    Start 3 → slots 3,4  ✓
    Start 4 → slots 4,5  ✗ (crosses lunch)
    Start 5 → slots 5,6  ✓
    Start 6 → slots 6,7  ✓
"""

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.models.room import Room
from app.models.slot import TimeSlot
from app.models.placement import Placement
from app.models.enums import ActivityType, RoomType, Day
from app.engine.state import ScheduleState
from app.engine.expander import ScheduleRequest
from app.engine.conflicts import ACTIVITY_ROOM_MAP


# ====================================================================
# Scheduler Configuration
# ====================================================================

@dataclass
class SchedulerConfig:
    """
    Configurable parameters for the scheduling engine.

    Mirrors ARCHITECTURE.md §5.
    """
    # Time grid
    days: List[Day] = field(default_factory=lambda: [
        Day.MON, Day.TUE, Day.WED, Day.THU, Day.FRI,
    ])
    periods_per_day: int = 7
    lunch_after_period: int = 4  # lunch sits between period 4 and 5

    # Behaviour
    allow_lunch_span: bool = False


# ====================================================================
# Slot Allocator
# ====================================================================

class SlotAllocator:
    """
    Generates valid slot-room candidates for schedule requests.

    Pre-computes room eligibility indexes for O(1) lookup and generates
    only time-grid-valid block positions.

    Args:
        rooms: Dict of room_id → Room.
        config: Scheduling configuration.
    """

    def __init__(
        self,
        rooms: Dict[str, Room],
        config: Optional[SchedulerConfig] = None,
    ):
        self.rooms = rooms
        self.config = config or SchedulerConfig()
        self._room_index = self._build_room_index()

    # ------------------------------------------------------------------
    # Room index
    # ------------------------------------------------------------------

    def _build_room_index(self) -> Dict[Tuple[RoomType, Optional[str]], List[Room]]:
        """
        Build an index: (room_type, branch_or_None) → List[Room].

        For LAB rooms, branch is included. For shared rooms, branch is None.
        Only active rooms are indexed.
        """
        idx: Dict[Tuple[RoomType, Optional[str]], List[Room]] = {}

        for r in self.rooms.values():
            if not r.active:
                continue
            if not isinstance(r.room_type, RoomType):
                continue

            # For LABs, index by (LAB, branch) AND (LAB, None) for global lookup
            if r.room_type == RoomType.LAB:
                key_specific = (RoomType.LAB, r.branch)
                idx.setdefault(key_specific, []).append(r)
            else:
                key_shared = (r.room_type, None)
                idx.setdefault(key_shared, []).append(r)

        return idx

    def get_eligible_rooms(
        self,
        activity_type: ActivityType,
        branch: Optional[str] = None,
    ) -> List[Room]:
        """
        Return rooms eligible for a given activity type and branch.

        Implements the cascading rules:
        - LECTURE   → LECTURE rooms
        - PRACTICAL → LAB rooms for the specific branch
        - WORKSHOP  → WORKSHOP rooms
        - DRAWING   → DRAWING_HALL rooms
        """
        valid_room_types = ACTIVITY_ROOM_MAP.get(activity_type, [])
        result = []

        for rt in valid_room_types:
            if rt == RoomType.LAB and branch:
                result.extend(self._room_index.get((RoomType.LAB, branch), []))
            else:
                result.extend(self._room_index.get((rt, None), []))

        return result

    # ------------------------------------------------------------------
    # Time grid
    # ------------------------------------------------------------------

    def get_valid_start_periods(self, block_size: int) -> List[int]:
        """
        Return valid start periods for a block of the given size.

        A start period ``s`` is valid if:
        - ``s + block_size - 1 <= periods_per_day``  (fits in the day)
        - The block does not span the lunch break

        The lunch break is between ``lunch_after_period`` and
        ``lunch_after_period + 1``.
        """
        valid = []
        lunch = self.config.lunch_after_period
        total = self.config.periods_per_day

        for s in range(1, total + 1):
            end = s + block_size - 1
            if end > total:
                continue  # exceeds grid

            if not self.config.allow_lunch_span:
                # Block spans lunch if it contains both ≤lunch and ≥lunch+1
                if s <= lunch and end >= lunch + 1:
                    continue

            valid.append(s)

        return valid

    def get_all_candidate_slots(
        self,
        block_size: int,
    ) -> List[Tuple[Day, int, List[TimeSlot]]]:
        """
        Generate all (day, start_period, slots) across the week.

        Returns:
            List of (day, start_period, [TimeSlot, ...]) tuples.
        """
        valid_starts = self.get_valid_start_periods(block_size)
        candidates = []

        for day in self.config.days:
            for start in valid_starts:
                slots = [
                    TimeSlot(day, start + offset)
                    for offset in range(block_size)
                ]
                candidates.append((day, start, slots))

        return candidates

    # ------------------------------------------------------------------
    # Single request: find valid placements
    # ------------------------------------------------------------------

    def find_valid_placements(
        self,
        request: ScheduleRequest,
        state: ScheduleState,
        rng: Optional[random.Random] = None,
    ) -> List[Tuple[List[TimeSlot], str]]:
        """
        Find all valid (slots, room_id) combinations for a single request.

        Checks:
        1. Teacher must be free at proposed slots
        2. Section/group must be free at proposed slots
        3. Room must be free and eligible for the activity type

        The candidate slots are enumerated day-then-period (stable
        order); the scheduler is what picks among them at random.  When
        ``rng`` is given and no room is explicitly required, the eligible
        rooms are shuffled so room choice varies between seeds instead of
        always taking the first free room — this adds no placement
        preference, only variety.

        Args:
            request: The schedule request.
            state:   Current schedule state.
            rng:     Optional RNG for room-choice variety.

        Returns:
            List of (slots, room_id) tuples, in day-then-period order.
        """
        a = request.assignment
        eligible_rooms = self.get_eligible_rooms(a.activity_type, a.branch)

        if not eligible_rooms:
            return []

        # Preferred room first (if explicitly required and eligible);
        # otherwise randomise room order for variety when an RNG is given.
        if a.room_id:
            eligible_rooms = sorted(
                eligible_rooms,
                key=lambda r: (0 if r.room_id == a.room_id else 1, r.room_id),
            )
        elif rng is not None:
            eligible_rooms = list(eligible_rooms)
            rng.shuffle(eligible_rooms)

        candidates = self.get_all_candidate_slots(request.block_size)
        valid = []

        for day, start, slots in candidates:
            # 1. Teacher free?
            if not state.is_teacher_free(a.teacher_id, slots):
                continue

            # 2. Section/group free?
            if not state.is_section_free(a.section, a.group, slots):
                continue

            # 3. Find a free eligible room
            for room in eligible_rooms:
                if state.is_room_free(room.room_id, slots):
                    valid.append((slots, room.room_id))
                    break  # Take first available room for this time slot

        return valid

    # ------------------------------------------------------------------
    # Paired G1/G2: find valid placements
    # ------------------------------------------------------------------

    def find_valid_paired_placements(
        self,
        g1_request: ScheduleRequest,
        g2_request: ScheduleRequest,
        state: ScheduleState,
        rng: Optional[random.Random] = None,
    ) -> List[Tuple[List[TimeSlot], str, str]]:
        """
        Find valid (slots, room_g1, room_g2) for paired G1/G2 practicals.

        Both groups must be placed at the SAME time slots but in
        DIFFERENT rooms.  Each needs its own teacher to be free.

        Args:
            g1_request: The G1 schedule request.
            g2_request: The G2 schedule request.
            state:      Current schedule state.

        Returns:
            List of (slots, room_id_g1, room_id_g2) tuples.
        """
        g1_a = g1_request.assignment
        g2_a = g2_request.assignment

        # Same teacher for both groups → impossible (teacher can't be in 2 rooms)
        if g1_a.teacher_id == g2_a.teacher_id:
            return []

        # Both should have the same activity type and block size
        block_size = g1_request.block_size
        eligible_rooms = self.get_eligible_rooms(g1_a.activity_type, g1_a.branch)

        if len(eligible_rooms) < 2:
            return []  # Need at least 2 rooms for parallel groups

        # Randomise room order for variety when neither group requires a
        # specific room (preferred rooms are still honoured below).
        if rng is not None and not g1_a.room_id and not g2_a.room_id:
            eligible_rooms = list(eligible_rooms)
            rng.shuffle(eligible_rooms)

        candidates = self.get_all_candidate_slots(block_size)
        valid = []

        for day, start, slots in candidates:
            # Teachers must be free
            if not state.is_teacher_free(g1_a.teacher_id, slots):
                continue
            if not state.is_teacher_free(g2_a.teacher_id, slots):
                continue

            # Section groups must be free (G1 and G2 don't conflict with
            # each other, but each conflicts with ALL)
            if not state.is_section_free(g1_a.section, "G1", slots):
                continue
            if not state.is_section_free(g2_a.section, "G2", slots):
                continue

            # Find 2 free eligible rooms
            free_rooms = [
                r for r in eligible_rooms
                if state.is_room_free(r.room_id, slots)
            ]

            if len(free_rooms) < 2:
                continue

            # Respect preferred rooms
            g1_room = free_rooms[0]
            g2_room = free_rooms[1]

            if g1_a.room_id:
                for r in free_rooms:
                    if r.room_id == g1_a.room_id:
                        g1_room = r
                        break

            remaining = [r for r in free_rooms if r.room_id != g1_room.room_id]
            if not remaining:
                continue

            if g2_a.room_id:
                for r in remaining:
                    if r.room_id == g2_a.room_id:
                        g2_room = r
                        break
                else:
                    g2_room = remaining[0]
            else:
                g2_room = remaining[0]

            valid.append((slots, g1_room.room_id, g2_room.room_id))

        return valid

    # ------------------------------------------------------------------
    # Failure reason diagnostics
    # ------------------------------------------------------------------

    def get_failure_reasons(
        self,
        request: ScheduleRequest,
        state: ScheduleState,
    ) -> List[str]:
        """
        Explain why no valid placement exists for a request.

        Checks each candidate slot and records the specific constraint
        that blocks it, then summarises.
        """
        a = request.assignment
        eligible_rooms = self.get_eligible_rooms(a.activity_type, a.branch)

        if not eligible_rooms:
            return [
                f"No eligible rooms: activity {a.activity_type.value} "
                f"requires {[rt.value for rt in ACTIVITY_ROOM_MAP.get(a.activity_type, [])]} "
                f"rooms for branch {a.branch}, but none are available."
            ]

        candidates = self.get_all_candidate_slots(request.block_size)
        teacher_blocked = 0
        section_blocked = 0
        all_rooms_busy = 0

        for day, start, slots in candidates:
            if not state.is_teacher_free(a.teacher_id, slots):
                teacher_blocked += 1
                continue
            if not state.is_section_free(a.section, a.group, slots):
                section_blocked += 1
                continue

            # Teacher and section free, but no room available
            has_room = any(
                state.is_room_free(r.room_id, slots)
                for r in eligible_rooms
            )
            if not has_room:
                all_rooms_busy += 1

        total = len(candidates)
        reasons = []

        if teacher_blocked > 0:
            reasons.append(
                f"Teacher {a.teacher_id} is busy at {teacher_blocked}/{total} "
                f"candidate time slots."
            )
        if section_blocked > 0:
            reasons.append(
                f"Section {a.section} (group {a.group}) is busy at "
                f"{section_blocked}/{total} candidate time slots."
            )
        if all_rooms_busy > 0:
            room_names = [r.room_name for r in eligible_rooms[:5]]
            reasons.append(
                f"All {len(eligible_rooms)} eligible rooms "
                f"({', '.join(room_names)}{'...' if len(eligible_rooms) > 5 else ''}) "
                f"are occupied at {all_rooms_busy}/{total} remaining candidate slots."
            )

        if not reasons:
            reasons.append(
                f"No valid {request.block_size}-slot blocks available in the time grid."
            )

        return reasons

    def get_paired_failure_reasons(
        self,
        g1_request: ScheduleRequest,
        g2_request: ScheduleRequest,
        state: ScheduleState,
    ) -> List[str]:
        """Explain why no valid paired placement exists."""
        g1_a = g1_request.assignment
        g2_a = g2_request.assignment

        # Same teacher for both groups → impossible
        if g1_a.teacher_id == g2_a.teacher_id:
            return [
                f"G1/G2 pairing impossible: same teacher {g1_a.teacher_id} "
                f"assigned to both groups for subject {g1_a.subject_id}."
            ]

        eligible_rooms = self.get_eligible_rooms(g1_a.activity_type, g1_a.branch)
        if len(eligible_rooms) < 2:
            return [
                f"G1/G2 pairing needs at least 2 eligible rooms, "
                f"but only {len(eligible_rooms)} "
                f"{g1_a.activity_type.value} room(s) available for branch {g1_a.branch}."
            ]

        candidates = self.get_all_candidate_slots(g1_request.block_size)
        g1_teacher_busy = 0
        g2_teacher_busy = 0
        section_busy = 0
        rooms_short = 0

        for day, start, slots in candidates:
            if not state.is_teacher_free(g1_a.teacher_id, slots):
                g1_teacher_busy += 1
                continue
            if not state.is_teacher_free(g2_a.teacher_id, slots):
                g2_teacher_busy += 1
                continue
            if not state.is_section_free(g1_a.section, "G1", slots):
                section_busy += 1
                continue
            if not state.is_section_free(g2_a.section, "G2", slots):
                section_busy += 1
                continue

            free_rooms = [
                r for r in eligible_rooms
                if state.is_room_free(r.room_id, slots)
            ]
            if len(free_rooms) < 2:
                rooms_short += 1

        total = len(candidates)
        reasons = []

        if g1_teacher_busy:
            reasons.append(
                f"G1 teacher {g1_a.teacher_id} busy at {g1_teacher_busy}/{total} slots."
            )
        if g2_teacher_busy:
            reasons.append(
                f"G2 teacher {g2_a.teacher_id} busy at {g2_teacher_busy}/{total} slots."
            )
        if section_busy:
            reasons.append(
                f"Section {g1_a.section} groups busy at {section_busy}/{total} slots."
            )
        if rooms_short:
            reasons.append(
                f"Fewer than 2 free rooms at {rooms_short}/{total} remaining slots."
            )

        if not reasons:
            reasons.append("No valid paired slot found (all candidates exhausted).")

        return reasons
