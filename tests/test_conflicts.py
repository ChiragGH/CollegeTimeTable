"""
Unit tests for the timetable conflict-validation engine.

Tests every checker function individually and the is_valid_assignment
orchestrator.  Covers:

    C1  Teacher overlap
    C2  Room overlap
    C3  Section overlap
    C4  Group overlap
    C5  Consecutive-slot violations (gaps, different days, lunch span)
    C6  G1/G2 synchronisation violations
    C7a Invalid room type
    C7b Invalid branch-specific room usage

Also tests ScheduleState add/remove and the ConflictReport format.
"""

import pytest
from typing import Dict, List

from app.models.enums import ActivityType, RoomType, Day
from app.models.room import Room
from app.models.assignment import Assignment
from app.models.slot import TimeSlot
from app.models.placement import Placement
from app.engine.state import ScheduleState
from app.engine.conflicts import (
    ConflictType,
    ConflictReport,
    check_teacher_overlap,
    check_room_overlap,
    check_section_overlap,
    check_group_overlap,
    check_room_type_validity,
    check_room_branch_validity,
    check_consecutive_slots,
    check_g1_g2_sync,
    is_valid_assignment,
)


# ---- Factories ----

def make_assignment(**overrides) -> Assignment:
    defaults = dict(
        assignment_id="A001",
        session_id="test",
        teacher_id="T001",
        subject_id="SUB001",
        branch="CSE",
        semester=3,
        section="A",
        group="ALL",
        activity_type=ActivityType.LECTURE,
        weekly_periods=2,
        block_size=1,
        sessions_per_week=2,
    )
    defaults.update(overrides)
    return Assignment(**defaults)


def make_placement(
    assignment: Assignment = None,
    slots: List[TimeSlot] = None,
    room_id: str = "R030",
    placement_id: str = "P001",
) -> Placement:
    if assignment is None:
        assignment = make_assignment()
    if slots is None:
        slots = [TimeSlot(Day.MON, 1)]
    return Placement(
        placement_id=placement_id,
        assignment=assignment,
        slots=slots,
        room_id=room_id,
    )


def make_rooms() -> Dict[str, Room]:
    return {
        "R001": Room(room_id="R001", room_name="CC1", room_type=RoomType.LAB, branch="CSE", is_shared=False, active=True),
        "R002": Room(room_id="R002", room_name="CC2", room_type=RoomType.LAB, branch="CSE", is_shared=False, active=True),
        "R010": Room(room_id="R010", room_name="DR", room_type=RoomType.LAB, branch="ECE", is_shared=False, active=True),
        "R030": Room(room_id="R030", room_name="L1", room_type=RoomType.LECTURE, branch=None, is_shared=True, active=True),
        "R031": Room(room_id="R031", room_name="L2", room_type=RoomType.LECTURE, branch=None, is_shared=True, active=True),
        "R040": Room(room_id="R040", room_name="DH1", room_type=RoomType.DRAWING_HALL, branch=None, is_shared=True, active=True),
        "R050": Room(room_id="R050", room_name="WS1", room_type=RoomType.WORKSHOP, branch=None, is_shared=True, active=True),
    }


# ================================================================
# ScheduleState Tests
# ================================================================

class TestScheduleState:
    def test_empty_state(self):
        state = ScheduleState()
        assert state.is_teacher_free("T001", [TimeSlot(Day.MON, 1)])
        assert state.is_room_free("R001", [TimeSlot(Day.MON, 1)])
        assert state.is_section_free("A", "ALL", [TimeSlot(Day.MON, 1)])

    def test_add_placement_occupies_teacher(self):
        state = ScheduleState()
        p = make_placement(slots=[TimeSlot(Day.MON, 1)])
        state.add_placement(p)
        assert not state.is_teacher_free("T001", [TimeSlot(Day.MON, 1)])
        assert state.is_teacher_free("T001", [TimeSlot(Day.MON, 2)])
        assert state.is_teacher_free("T002", [TimeSlot(Day.MON, 1)])

    def test_add_placement_occupies_room(self):
        state = ScheduleState()
        p = make_placement(room_id="R030", slots=[TimeSlot(Day.TUE, 3)])
        state.add_placement(p)
        assert not state.is_room_free("R030", [TimeSlot(Day.TUE, 3)])
        assert state.is_room_free("R030", [TimeSlot(Day.TUE, 4)])
        assert state.is_room_free("R031", [TimeSlot(Day.TUE, 3)])

    def test_add_placement_occupies_section_group(self):
        state = ScheduleState()
        a = make_assignment(group="G1")
        p = make_placement(assignment=a, slots=[TimeSlot(Day.WED, 2)])
        state.add_placement(p)

        # G1 is busy
        assert not state.is_section_free("A", "G1", [TimeSlot(Day.WED, 2)])
        # G2 is free (parallel allowed)
        assert state.is_section_free("A", "G2", [TimeSlot(Day.WED, 2)])
        # ALL is NOT free (would conflict with G1)
        assert not state.is_section_free("A", "ALL", [TimeSlot(Day.WED, 2)])

    def test_all_group_blocks_both_g1_g2(self):
        state = ScheduleState()
        a = make_assignment(group="ALL")
        p = make_placement(assignment=a, slots=[TimeSlot(Day.MON, 5)])
        state.add_placement(p)

        assert not state.is_section_free("A", "ALL", [TimeSlot(Day.MON, 5)])
        assert not state.is_section_free("A", "G1", [TimeSlot(Day.MON, 5)])
        assert not state.is_section_free("A", "G2", [TimeSlot(Day.MON, 5)])

    def test_remove_placement(self):
        state = ScheduleState()
        p = make_placement(slots=[TimeSlot(Day.MON, 1)])
        state.add_placement(p)
        assert not state.is_teacher_free("T001", [TimeSlot(Day.MON, 1)])

        state.remove_placement(p)
        assert state.is_teacher_free("T001", [TimeSlot(Day.MON, 1)])
        assert state.is_room_free("R030", [TimeSlot(Day.MON, 1)])

    def test_workload_counter(self):
        state = ScheduleState()
        p = make_placement(slots=[TimeSlot(Day.MON, 1)])
        state.add_placement(p)
        assert state.workload_counter[("SUB001", "A", "ALL")] == 1

        state.remove_placement(p)
        assert state.workload_counter[("SUB001", "A", "ALL")] == 0


# ================================================================
# C1: Teacher Overlap
# ================================================================

class TestTeacherOverlap:
    def test_no_conflict_different_slot(self):
        state = ScheduleState()
        existing = make_placement(slots=[TimeSlot(Day.MON, 1)])
        state.add_placement(existing)

        proposed = make_placement(
            placement_id="P002",
            slots=[TimeSlot(Day.MON, 2)],
        )
        conflicts = check_teacher_overlap(proposed, state)
        assert len(conflicts) == 0

    def test_conflict_same_slot(self):
        state = ScheduleState()
        existing = make_placement(slots=[TimeSlot(Day.MON, 1)])
        state.add_placement(existing)

        proposed = make_placement(
            assignment=make_assignment(assignment_id="A002", subject_id="SUB002"),
            placement_id="P002",
            slots=[TimeSlot(Day.MON, 1)],
        )
        conflicts = check_teacher_overlap(proposed, state)
        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.TEACHER_CONFLICT
        assert conflicts[0].teacher_id == "T001"
        assert conflicts[0].slot == "MON_1"

    def test_no_conflict_different_teacher(self):
        state = ScheduleState()
        existing = make_placement(slots=[TimeSlot(Day.MON, 1)])
        state.add_placement(existing)

        proposed = make_placement(
            assignment=make_assignment(assignment_id="A002", teacher_id="T002"),
            placement_id="P002",
            slots=[TimeSlot(Day.MON, 1)],
        )
        conflicts = check_teacher_overlap(proposed, state)
        assert len(conflicts) == 0

    def test_multiple_slot_conflicts(self):
        state = ScheduleState()
        existing = make_placement(
            slots=[TimeSlot(Day.MON, 1), TimeSlot(Day.MON, 2)],
        )
        state.add_placement(existing)

        proposed = make_placement(
            assignment=make_assignment(assignment_id="A002", subject_id="SUB002"),
            placement_id="P002",
            slots=[TimeSlot(Day.MON, 1), TimeSlot(Day.MON, 2)],
        )
        conflicts = check_teacher_overlap(proposed, state)
        assert len(conflicts) == 2


# ================================================================
# C2: Room Overlap
# ================================================================

class TestRoomOverlap:
    def test_no_conflict_different_room(self):
        state = ScheduleState()
        existing = make_placement(room_id="R030", slots=[TimeSlot(Day.MON, 1)])
        state.add_placement(existing)

        proposed = make_placement(
            assignment=make_assignment(assignment_id="A002", teacher_id="T002"),
            placement_id="P002",
            room_id="R031",
            slots=[TimeSlot(Day.MON, 1)],
        )
        conflicts = check_room_overlap(proposed, state)
        assert len(conflicts) == 0

    def test_conflict_same_room_same_slot(self):
        state = ScheduleState()
        existing = make_placement(room_id="R030", slots=[TimeSlot(Day.MON, 1)])
        state.add_placement(existing)

        proposed = make_placement(
            assignment=make_assignment(assignment_id="A002", teacher_id="T002"),
            placement_id="P002",
            room_id="R030",
            slots=[TimeSlot(Day.MON, 1)],
        )
        conflicts = check_room_overlap(proposed, state)
        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.ROOM_CONFLICT
        assert conflicts[0].room_id == "R030"


# ================================================================
# C3: Section Overlap
# ================================================================

class TestSectionOverlap:
    def test_all_conflicts_with_all(self):
        """ALL placement blocks another ALL at same slot."""
        state = ScheduleState()
        existing = make_placement(
            assignment=make_assignment(group="ALL"),
            slots=[TimeSlot(Day.MON, 1)],
        )
        state.add_placement(existing)

        proposed = make_placement(
            assignment=make_assignment(assignment_id="A002", subject_id="SUB002", group="G1"),
            placement_id="P002",
            slots=[TimeSlot(Day.MON, 1)],
        )
        conflicts = check_section_overlap(proposed, state)
        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.SECTION_CONFLICT

    def test_no_section_conflict_different_section(self):
        state = ScheduleState()
        existing = make_placement(
            assignment=make_assignment(section="A", group="ALL"),
            slots=[TimeSlot(Day.MON, 1)],
        )
        state.add_placement(existing)

        proposed = make_placement(
            assignment=make_assignment(assignment_id="A002", section="B", group="ALL"),
            placement_id="P002",
            slots=[TimeSlot(Day.MON, 1)],
        )
        conflicts = check_section_overlap(proposed, state)
        assert len(conflicts) == 0


# ================================================================
# C4: Group Overlap
# ================================================================

class TestGroupOverlap:
    def test_g1_conflicts_with_g1(self):
        state = ScheduleState()
        existing = make_placement(
            assignment=make_assignment(group="G1"),
            slots=[TimeSlot(Day.MON, 1)],
        )
        state.add_placement(existing)

        proposed = make_placement(
            assignment=make_assignment(assignment_id="A002", subject_id="SUB002", group="G1"),
            placement_id="P002",
            slots=[TimeSlot(Day.MON, 1)],
        )
        conflicts = check_group_overlap(proposed, state)
        assert len(conflicts) >= 1
        assert any(c.type == ConflictType.GROUP_CONFLICT for c in conflicts)

    def test_g1_does_not_conflict_with_g2(self):
        """G1 and G2 can run in parallel -- no conflict."""
        state = ScheduleState()
        existing = make_placement(
            assignment=make_assignment(group="G1"),
            slots=[TimeSlot(Day.MON, 1)],
        )
        state.add_placement(existing)

        proposed = make_placement(
            assignment=make_assignment(assignment_id="A002", teacher_id="T002", subject_id="SUB002", group="G2"),
            placement_id="P002",
            slots=[TimeSlot(Day.MON, 1)],
        )
        conflicts = check_group_overlap(proposed, state)
        assert len(conflicts) == 0

    def test_all_conflicts_with_g1(self):
        """ALL (lecture) conflicts with existing G1."""
        state = ScheduleState()
        existing = make_placement(
            assignment=make_assignment(group="G1"),
            slots=[TimeSlot(Day.MON, 1)],
        )
        state.add_placement(existing)

        proposed = make_placement(
            assignment=make_assignment(assignment_id="A002", subject_id="SUB002", group="ALL"),
            placement_id="P002",
            slots=[TimeSlot(Day.MON, 1)],
        )
        conflicts = check_group_overlap(proposed, state)
        assert len(conflicts) >= 1

    def test_g1_conflicts_with_all(self):
        """G1 placement conflicts with existing ALL."""
        state = ScheduleState()
        existing = make_placement(
            assignment=make_assignment(group="ALL"),
            slots=[TimeSlot(Day.MON, 1)],
        )
        state.add_placement(existing)

        proposed = make_placement(
            assignment=make_assignment(assignment_id="A002", subject_id="SUB002", group="G1",
                                      activity_type=ActivityType.PRACTICAL),
            placement_id="P002",
            slots=[TimeSlot(Day.MON, 1)],
        )
        conflicts = check_group_overlap(proposed, state)
        assert len(conflicts) >= 1


# ================================================================
# C5: Consecutive Slots
# ================================================================

class TestConsecutiveSlots:
    def test_single_slot_always_valid(self):
        p = make_placement(slots=[TimeSlot(Day.MON, 3)])
        conflicts = check_consecutive_slots(p)
        assert len(conflicts) == 0

    def test_consecutive_slots_valid(self):
        p = make_placement(slots=[TimeSlot(Day.MON, 1), TimeSlot(Day.MON, 2)])
        conflicts = check_consecutive_slots(p)
        assert len(conflicts) == 0

    def test_three_consecutive_valid(self):
        p = make_placement(slots=[
            TimeSlot(Day.TUE, 5), TimeSlot(Day.TUE, 6), TimeSlot(Day.TUE, 7)
        ])
        conflicts = check_consecutive_slots(p)
        assert len(conflicts) == 0

    def test_non_consecutive_gap(self):
        """Gap between slot 2 and 4."""
        p = make_placement(slots=[TimeSlot(Day.MON, 2), TimeSlot(Day.MON, 4)])
        conflicts = check_consecutive_slots(p)
        assert any(c.type == ConflictType.NON_CONSECUTIVE_SLOTS for c in conflicts)

    def test_different_days(self):
        p = make_placement(slots=[TimeSlot(Day.MON, 1), TimeSlot(Day.TUE, 2)])
        conflicts = check_consecutive_slots(p)
        assert any(c.type == ConflictType.DIFFERENT_DAYS for c in conflicts)

    def test_lunch_span_blocked(self):
        """Slots 4-5 span lunch -- blocked by default."""
        p = make_placement(slots=[TimeSlot(Day.WED, 4), TimeSlot(Day.WED, 5)])
        conflicts = check_consecutive_slots(p)
        assert any(c.type == ConflictType.LUNCH_SPAN for c in conflicts)

    def test_lunch_span_allowed(self):
        """Slots 4-5 allowed when allow_lunch_span=True."""
        p = make_placement(slots=[TimeSlot(Day.WED, 4), TimeSlot(Day.WED, 5)])
        conflicts = check_consecutive_slots(p, allow_lunch_span=True)
        assert not any(c.type == ConflictType.LUNCH_SPAN for c in conflicts)

    def test_three_slot_block_spanning_lunch(self):
        """Slots 3-4-5 span lunch."""
        p = make_placement(slots=[
            TimeSlot(Day.THU, 3), TimeSlot(Day.THU, 4), TimeSlot(Day.THU, 5)
        ])
        conflicts = check_consecutive_slots(p)
        assert any(c.type == ConflictType.LUNCH_SPAN for c in conflicts)

    def test_before_lunch_block_valid(self):
        """Slots 3-4 are consecutive and before lunch -- valid."""
        p = make_placement(slots=[TimeSlot(Day.FRI, 3), TimeSlot(Day.FRI, 4)])
        conflicts = check_consecutive_slots(p)
        assert len(conflicts) == 0

    def test_after_lunch_block_valid(self):
        """Slots 5-6 are consecutive and after lunch -- valid."""
        p = make_placement(slots=[TimeSlot(Day.FRI, 5), TimeSlot(Day.FRI, 6)])
        conflicts = check_consecutive_slots(p)
        assert len(conflicts) == 0


# ================================================================
# C6: G1/G2 Sync
# ================================================================

class TestG1G2Sync:
    def test_no_partner_no_conflict(self):
        """If only G1 is placed, no sync check needed yet."""
        state = ScheduleState()
        a = make_assignment(group="G1", activity_type=ActivityType.PRACTICAL)
        p = make_placement(assignment=a, slots=[TimeSlot(Day.MON, 1), TimeSlot(Day.MON, 2)])
        conflicts = check_g1_g2_sync(p, state)
        assert len(conflicts) == 0

    def test_sync_ok(self):
        """G1 and G2 at the same slots -- valid."""
        state = ScheduleState()
        g1_a = make_assignment(
            assignment_id="A001", group="G1", teacher_id="T001",
            activity_type=ActivityType.PRACTICAL,
        )
        g1_p = make_placement(
            assignment=g1_a,
            slots=[TimeSlot(Day.MON, 1), TimeSlot(Day.MON, 2)],
            room_id="R001",
        )
        state.add_placement(g1_p)

        g2_a = make_assignment(
            assignment_id="A002", group="G2", teacher_id="T002",
            activity_type=ActivityType.PRACTICAL,
        )
        g2_p = make_placement(
            assignment=g2_a,
            placement_id="P002",
            slots=[TimeSlot(Day.MON, 1), TimeSlot(Day.MON, 2)],
            room_id="R002",
        )
        conflicts = check_g1_g2_sync(g2_p, state)
        assert len(conflicts) == 0

    def test_sync_violation(self):
        """G1 at MON 1-2, G2 proposed at TUE 3-4 -- violation."""
        state = ScheduleState()
        g1_a = make_assignment(
            assignment_id="A001", group="G1", teacher_id="T001",
            activity_type=ActivityType.PRACTICAL,
        )
        g1_p = make_placement(
            assignment=g1_a,
            slots=[TimeSlot(Day.MON, 1), TimeSlot(Day.MON, 2)],
            room_id="R001",
        )
        state.add_placement(g1_p)

        g2_a = make_assignment(
            assignment_id="A002", group="G2", teacher_id="T002",
            activity_type=ActivityType.PRACTICAL,
        )
        g2_p = make_placement(
            assignment=g2_a,
            placement_id="P002",
            slots=[TimeSlot(Day.TUE, 3), TimeSlot(Day.TUE, 4)],
            room_id="R002",
        )
        conflicts = check_g1_g2_sync(g2_p, state)
        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.G1_G2_SYNC
        assert conflicts[0].subject_id == "SUB001"

    def test_all_group_skipped(self):
        """group=ALL (lectures) skip the G1/G2 sync check."""
        state = ScheduleState()
        p = make_placement(
            assignment=make_assignment(group="ALL"),
            slots=[TimeSlot(Day.MON, 1)],
        )
        conflicts = check_g1_g2_sync(p, state)
        assert len(conflicts) == 0

    def test_lecture_activity_skipped(self):
        """LECTURE activities skip the G1/G2 sync check."""
        state = ScheduleState()
        p = make_placement(
            assignment=make_assignment(group="G1", activity_type=ActivityType.LECTURE),
            slots=[TimeSlot(Day.MON, 1)],
        )
        conflicts = check_g1_g2_sync(p, state)
        assert len(conflicts) == 0


# ================================================================
# C7a: Room Type Validity
# ================================================================

class TestRoomTypeValidity:
    def test_lecture_in_lecture_room(self):
        rooms = make_rooms()
        p = make_placement(
            assignment=make_assignment(activity_type=ActivityType.LECTURE),
            room_id="R030",
        )
        conflicts = check_room_type_validity(p, rooms)
        assert len(conflicts) == 0

    def test_practical_in_lab(self):
        rooms = make_rooms()
        p = make_placement(
            assignment=make_assignment(activity_type=ActivityType.PRACTICAL),
            room_id="R001",
        )
        conflicts = check_room_type_validity(p, rooms)
        assert len(conflicts) == 0

    def test_lecture_in_lab_invalid(self):
        rooms = make_rooms()
        p = make_placement(
            assignment=make_assignment(activity_type=ActivityType.LECTURE),
            room_id="R001",  # LAB room
        )
        conflicts = check_room_type_validity(p, rooms)
        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.INVALID_ROOM_TYPE

    def test_practical_in_lecture_room_invalid(self):
        rooms = make_rooms()
        p = make_placement(
            assignment=make_assignment(activity_type=ActivityType.PRACTICAL),
            room_id="R030",  # LECTURE room
        )
        conflicts = check_room_type_validity(p, rooms)
        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.INVALID_ROOM_TYPE

    def test_drawing_in_drawing_hall(self):
        rooms = make_rooms()
        p = make_placement(
            assignment=make_assignment(activity_type=ActivityType.DRAWING),
            room_id="R040",
        )
        conflicts = check_room_type_validity(p, rooms)
        assert len(conflicts) == 0

    def test_workshop_in_workshop_room(self):
        rooms = make_rooms()
        p = make_placement(
            assignment=make_assignment(activity_type=ActivityType.WORKSHOP),
            room_id="R050",
        )
        conflicts = check_room_type_validity(p, rooms)
        assert len(conflicts) == 0

    def test_unknown_room_id(self):
        rooms = make_rooms()
        p = make_placement(room_id="RXXXX")
        conflicts = check_room_type_validity(p, rooms)
        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.INVALID_ROOM_TYPE


# ================================================================
# C7b: Room Branch Validity
# ================================================================

class TestRoomBranchValidity:
    def test_cse_lab_for_cse_assignment(self):
        rooms = make_rooms()
        p = make_placement(
            assignment=make_assignment(branch="CSE", activity_type=ActivityType.PRACTICAL),
            room_id="R001",  # CSE lab
        )
        conflicts = check_room_branch_validity(p, rooms)
        assert len(conflicts) == 0

    def test_ece_lab_for_cse_assignment_invalid(self):
        rooms = make_rooms()
        p = make_placement(
            assignment=make_assignment(branch="CSE", activity_type=ActivityType.PRACTICAL),
            room_id="R010",  # ECE lab
        )
        conflicts = check_room_branch_validity(p, rooms)
        assert len(conflicts) == 1
        assert conflicts[0].type == ConflictType.INVALID_ROOM_BRANCH

    def test_lecture_room_no_branch_check(self):
        """Shared rooms (LECTURE) have no branch constraint."""
        rooms = make_rooms()
        p = make_placement(
            assignment=make_assignment(branch="CSE", activity_type=ActivityType.LECTURE),
            room_id="R030",
        )
        conflicts = check_room_branch_validity(p, rooms)
        assert len(conflicts) == 0

    def test_drawing_hall_no_branch_check(self):
        rooms = make_rooms()
        p = make_placement(
            assignment=make_assignment(branch="CSE", activity_type=ActivityType.DRAWING),
            room_id="R040",
        )
        conflicts = check_room_branch_validity(p, rooms)
        assert len(conflicts) == 0


# ================================================================
# is_valid_assignment (orchestrator)
# ================================================================

class TestIsValidAssignment:
    def test_valid_placement(self):
        state = ScheduleState()
        rooms = make_rooms()
        p = make_placement(
            assignment=make_assignment(activity_type=ActivityType.LECTURE),
            room_id="R030",
            slots=[TimeSlot(Day.MON, 1)],
        )
        report = is_valid_assignment(p, state, rooms)
        assert report.valid
        assert len(report.conflicts) == 0

    def test_multiple_conflicts_detected(self):
        """A placement with both teacher and room conflicts."""
        state = ScheduleState()
        rooms = make_rooms()

        existing = make_placement(
            assignment=make_assignment(activity_type=ActivityType.LECTURE),
            room_id="R030",
            slots=[TimeSlot(Day.MON, 1)],
        )
        state.add_placement(existing)

        # Same teacher, same room, same slot
        proposed = make_placement(
            assignment=make_assignment(
                assignment_id="A002", subject_id="SUB002",
                activity_type=ActivityType.LECTURE,
            ),
            placement_id="P002",
            room_id="R030",
            slots=[TimeSlot(Day.MON, 1)],
        )

        report = is_valid_assignment(proposed, state, rooms)
        assert not report.valid
        conflict_types = {c.type for c in report.conflicts}
        assert ConflictType.TEACHER_CONFLICT in conflict_types
        assert ConflictType.ROOM_CONFLICT in conflict_types

    def test_room_type_mismatch_in_orchestrator(self):
        state = ScheduleState()
        rooms = make_rooms()
        p = make_placement(
            assignment=make_assignment(activity_type=ActivityType.LECTURE),
            room_id="R001",  # LAB, not LECTURE
            slots=[TimeSlot(Day.MON, 1)],
        )
        report = is_valid_assignment(p, state, rooms)
        assert not report.valid
        assert any(c.type == ConflictType.INVALID_ROOM_TYPE for c in report.conflicts)

    def test_lunch_span_in_orchestrator(self):
        state = ScheduleState()
        rooms = make_rooms()
        p = make_placement(
            assignment=make_assignment(
                activity_type=ActivityType.PRACTICAL, group="G1",
                block_size=2,
            ),
            room_id="R001",
            slots=[TimeSlot(Day.MON, 4), TimeSlot(Day.MON, 5)],
        )
        report = is_valid_assignment(p, state, rooms)
        assert not report.valid
        assert any(c.type == ConflictType.LUNCH_SPAN for c in report.conflicts)

    def test_to_dict_format(self):
        """Verify the output matches the user's JSON format."""
        state = ScheduleState()
        rooms = make_rooms()

        existing = make_placement(
            room_id="R030",
            slots=[TimeSlot(Day.MON, 2)],
        )
        state.add_placement(existing)

        proposed = make_placement(
            assignment=make_assignment(
                assignment_id="A002", subject_id="SUB002",
                activity_type=ActivityType.LECTURE,
            ),
            placement_id="P002",
            room_id="R030",
            slots=[TimeSlot(Day.MON, 2)],
        )

        report = is_valid_assignment(proposed, state, rooms)
        d = report.to_dict()

        assert d["valid"] is False
        assert isinstance(d["conflicts"], list)
        assert len(d["conflicts"]) > 0

        # Check structure of first conflict
        first = d["conflicts"][0]
        assert "type" in first
        assert "message" in first

    def test_g1_g2_sync_in_orchestrator(self):
        state = ScheduleState()
        rooms = make_rooms()

        # Place G1 at MON 1-2
        g1_a = make_assignment(
            assignment_id="A001", group="G1", teacher_id="T001",
            activity_type=ActivityType.PRACTICAL, block_size=2,
        )
        g1_p = make_placement(
            assignment=g1_a,
            slots=[TimeSlot(Day.MON, 1), TimeSlot(Day.MON, 2)],
            room_id="R001",
        )
        state.add_placement(g1_p)

        # Propose G2 at TUE 1-2 (wrong day)
        g2_a = make_assignment(
            assignment_id="A002", group="G2", teacher_id="T002",
            activity_type=ActivityType.PRACTICAL, block_size=2,
        )
        g2_p = make_placement(
            assignment=g2_a,
            placement_id="P002",
            slots=[TimeSlot(Day.TUE, 1), TimeSlot(Day.TUE, 2)],
            room_id="R002",
        )
        report = is_valid_assignment(g2_p, state, rooms)
        assert not report.valid
        assert any(c.type == ConflictType.G1_G2_SYNC for c in report.conflicts)

    def test_clean_valid_practical_block(self):
        """Valid practical: G1, consecutive before lunch, correct room."""
        state = ScheduleState()
        rooms = make_rooms()
        a = make_assignment(
            activity_type=ActivityType.PRACTICAL,
            group="G1", block_size=2,
        )
        p = make_placement(
            assignment=a,
            room_id="R001",  # CSE LAB
            slots=[TimeSlot(Day.WED, 1), TimeSlot(Day.WED, 2)],
        )
        report = is_valid_assignment(p, state, rooms)
        assert report.valid


# ================================================================
# ConflictReport / Conflict Tests
# ================================================================

class TestConflictReport:
    def test_empty_report_valid(self):
        report = ConflictReport(valid=True, conflicts=[])
        assert report.valid
        d = report.to_dict()
        assert d == {"valid": True, "conflicts": []}

    def test_conflict_to_dict_includes_all_fields(self):
        from app.engine.conflicts import Conflict
        c = Conflict(
            type=ConflictType.TEACHER_CONFLICT,
            message="Teacher T001 busy",
            slot="MON_2",
            teacher_id="T001",
        )
        d = c.to_dict()
        assert d["type"] == "TEACHER_CONFLICT"
        assert d["slot"] == "MON_2"
        assert d["teacher_id"] == "T001"
        assert d["message"] == "Teacher T001 busy"
        # Omitted None fields
        assert "room_id" not in d

    def test_conflict_str(self):
        from app.engine.conflicts import Conflict
        c = Conflict(
            type=ConflictType.ROOM_CONFLICT,
            message="Room R030 busy",
            slot="TUE_3",
            room_id="R030",
        )
        s = str(c)
        assert "ROOM_CONFLICT" in s
        assert "R030" in s


# ================================================================
# TimeSlot Tests
# ================================================================

class TestTimeSlot:
    def test_str_format(self):
        slot = TimeSlot(Day.MON, 2)
        assert str(slot) == "MON_2"

    def test_frozen(self):
        slot = TimeSlot(Day.MON, 1)
        with pytest.raises(AttributeError):
            slot.period = 2

    def test_hashable(self):
        s1 = TimeSlot(Day.MON, 1)
        s2 = TimeSlot(Day.MON, 1)
        assert s1 == s2
        assert hash(s1) == hash(s2)
        assert len({s1, s2}) == 1

    def test_different_slots_not_equal(self):
        s1 = TimeSlot(Day.MON, 1)
        s2 = TimeSlot(Day.MON, 2)
        assert s1 != s2

    def test_different_days_not_equal(self):
        s1 = TimeSlot(Day.MON, 1)
        s2 = TimeSlot(Day.TUE, 1)
        assert s1 != s2
