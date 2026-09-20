"""
Schedule state tracker.

Maintains O(1) occupancy maps for teachers, rooms, and sections/groups
so that conflict checks are fast.  This is the central mutable state
object used during scheduling (ARCHITECTURE.md §4.1).
"""

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from app.models.slot import TimeSlot
from app.models.placement import Placement


class ScheduleState:
    """
    Tracks all placed activities for fast constraint checking.

    Occupancy maps provide O(1) lookup to answer questions like
    "is teacher T001 free at MON slot 3?".

    Usage::

        state = ScheduleState()
        state.add_placement(placement)
        assert not state.is_teacher_free("T001", [TimeSlot(Day.MON, 3)])
    """

    def __init__(self):
        # entity_id --> Set[TimeSlot]
        self.teacher_slots: Dict[str, Set[TimeSlot]] = defaultdict(set)
        self.room_slots: Dict[str, Set[TimeSlot]] = defaultdict(set)

        # section_label --> group --> Set[TimeSlot]
        self.section_slots: Dict[str, Dict[str, Set[TimeSlot]]] = defaultdict(
            lambda: defaultdict(set)
        )

        # (subject_id, section, group) --> number of sessions placed
        self.workload_counter: Dict[Tuple[str, str, str], int] = defaultdict(int)

        # All placements (ordered, for undo / export)
        self.placements: List[Placement] = []

        # Quick lookup: placement_id --> Placement
        self._placement_index: Dict[str, Placement] = {}

    # ------------------------------------------------------------------
    # Add / Remove
    # ------------------------------------------------------------------

    def add_placement(self, p: Placement) -> None:
        """Register a placement in all occupancy maps."""
        a = p.assignment
        slot_set = set(p.slots)

        self.teacher_slots[a.teacher_id].update(slot_set)
        self.room_slots[p.room_id].update(slot_set)

        # Section/group tracking
        self.section_slots[a.section][a.group].update(slot_set)

        # Workload counter
        key = (a.subject_id, a.section, a.group)
        self.workload_counter[key] += 1

        self.placements.append(p)
        self._placement_index[p.placement_id] = p

    def remove_placement(self, p: Placement) -> None:
        """Unregister a placement from all occupancy maps (for backtracking)."""
        a = p.assignment
        slot_set = set(p.slots)

        self.teacher_slots[a.teacher_id].difference_update(slot_set)
        self.room_slots[p.room_id].difference_update(slot_set)

        self.section_slots[a.section][a.group].difference_update(slot_set)

        key = (a.subject_id, a.section, a.group)
        self.workload_counter[key] = max(0, self.workload_counter[key] - 1)

        if p in self.placements:
            self.placements.remove(p)
        self._placement_index.pop(p.placement_id, None)

    # ------------------------------------------------------------------
    # Occupancy queries
    # ------------------------------------------------------------------

    def is_teacher_free(self, teacher_id: str, slots: List[TimeSlot]) -> bool:
        """True if none of the given slots overlap the teacher's schedule."""
        occupied = self.teacher_slots.get(teacher_id, set())
        return not any(s in occupied for s in slots)

    def is_room_free(self, room_id: str, slots: List[TimeSlot]) -> bool:
        """True if none of the given slots overlap the room's schedule."""
        occupied = self.room_slots.get(room_id, set())
        return not any(s in occupied for s in slots)

    def is_section_free(
        self,
        section: str,
        group: str,
        slots: List[TimeSlot],
    ) -> bool:
        """
        True if the section/group has no conflicts at the given slots.

        Overlap logic:
        - ``ALL``: conflicts with ANY group (G1, G2, ALL).
        - ``G1``:  conflicts with G1 and ALL (not G2 -- they run in parallel).
        - ``G2``:  conflicts with G2 and ALL (not G1).
        """
        sec_groups = self.section_slots.get(section, {})
        conflicting_groups = self._get_conflicting_groups(group)

        for cg in conflicting_groups:
            occupied = sec_groups.get(cg, set())
            if any(s in occupied for s in slots):
                return False
        return True

    def get_teacher_conflicts(
        self,
        teacher_id: str,
        slots: List[TimeSlot],
    ) -> List[TimeSlot]:
        """Return the specific slots where the teacher has conflicts."""
        occupied = self.teacher_slots.get(teacher_id, set())
        return [s for s in slots if s in occupied]

    def get_room_conflicts(
        self,
        room_id: str,
        slots: List[TimeSlot],
    ) -> List[TimeSlot]:
        """Return the specific slots where the room has conflicts."""
        occupied = self.room_slots.get(room_id, set())
        return [s for s in slots if s in occupied]

    def get_section_conflicts(
        self,
        section: str,
        group: str,
        slots: List[TimeSlot],
    ) -> List[Tuple[str, TimeSlot]]:
        """
        Return (conflicting_group, slot) pairs for section conflicts.
        """
        sec_groups = self.section_slots.get(section, {})
        conflicting_groups = self._get_conflicting_groups(group)
        conflicts = []

        for cg in conflicting_groups:
            occupied = sec_groups.get(cg, set())
            for s in slots:
                if s in occupied:
                    conflicts.append((cg, s))

        return conflicts

    def get_placements_for_subject_section(
        self,
        subject_id: str,
        section: str,
    ) -> List[Placement]:
        """Return all placements for a given subject in a section."""
        return [
            p for p in self.placements
            if p.assignment.subject_id == subject_id
            and p.assignment.section == section
        ]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _get_conflicting_groups(group: str) -> List[str]:
        """
        Return the list of groups that would conflict with the given group.

        - ``ALL`` conflicts with everything: ALL, G1, G2
        - ``G1`` conflicts with: G1, ALL  (G2 runs in parallel)
        - ``G2`` conflicts with: G2, ALL  (G1 runs in parallel)
        """
        if group == "ALL":
            return ["ALL", "G1", "G2"]
        elif group == "G1":
            return ["G1", "ALL"]
        elif group == "G2":
            return ["G2", "ALL"]
        else:
            return [group, "ALL"]
