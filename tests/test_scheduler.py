"""
Comprehensive tests for the timetable scheduling engine.

Tests cover:
    - Session expansion (assignments → schedule requests)
    - G1/G2 pairing and priority sorting
    - Slot allocator (valid starts, room eligibility, candidate generation)
    - TimetableScheduler end-to-end scenarios:
        - Single lecture placement
        - Multiple lectures across days
        - Practical block placement (consecutive slots)
        - G1/G2 parallel practical placement
        - Teacher conflict avoidance
        - Room conflict avoidance
        - Room type enforcement
        - Branch-specific lab enforcement
        - Unscheduled session reporting with reasons
        - Full workload scheduling
        - Impossible schedule detection
"""

import pytest
from typing import Dict, List

from app.models.enums import ActivityType, RoomType, Day
from app.models.room import Room
from app.models.assignment import Assignment
from app.models.slot import TimeSlot
from app.models.placement import Placement
from app.engine.expander import (
    ScheduleRequest,
    expand_assignments,
    pair_g1_g2,
    sort_by_difficulty,
)
from app.engine.slot_allocator import SlotAllocator, SchedulerConfig
from app.engine.scheduler import TimetableScheduler, ScheduleResult
from app.engine.state import ScheduleState


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
        weekly_periods=3,
        block_size=1,
        sessions_per_week=3,
    )
    defaults.update(overrides)
    return Assignment(**defaults)


def make_rooms() -> Dict[str, Room]:
    return {
        # CSE labs (6 rooms)
        "R001": Room(room_id="R001", room_name="CC1", room_type=RoomType.LAB, branch="CSE", is_shared=False, active=True),
        "R002": Room(room_id="R002", room_name="CC2", room_type=RoomType.LAB, branch="CSE", is_shared=False, active=True),
        "R003": Room(room_id="R003", room_name="CC3", room_type=RoomType.LAB, branch="CSE", is_shared=False, active=True),
        # ECE lab
        "R010": Room(room_id="R010", room_name="DR", room_type=RoomType.LAB, branch="ECE", is_shared=False, active=True),
        # Lecture rooms
        "R030": Room(room_id="R030", room_name="L1", room_type=RoomType.LECTURE, branch=None, is_shared=True, active=True),
        "R031": Room(room_id="R031", room_name="L2", room_type=RoomType.LECTURE, branch=None, is_shared=True, active=True),
        # Drawing halls
        "R040": Room(room_id="R040", room_name="DH1", room_type=RoomType.DRAWING_HALL, branch=None, is_shared=True, active=True),
        # Workshop
        "R050": Room(room_id="R050", room_name="WS1", room_type=RoomType.WORKSHOP, branch=None, is_shared=True, active=True),
        # Inactive
        "R099": Room(room_id="R099", room_name="OLD", room_type=RoomType.LECTURE, branch=None, is_shared=True, active=False),
    }


# ================================================================
# Expander Tests
# ================================================================

class TestExpandAssignments:
    def test_single_lecture_3_sessions(self):
        a = make_assignment(sessions_per_week=3, block_size=1)
        requests = expand_assignments([a])
        assert len(requests) == 3
        for i, r in enumerate(requests, 1):
            assert r.session_index == i
            assert r.block_size == 1
            assert r.assignment is a

    def test_practical_1_session(self):
        a = make_assignment(
            sessions_per_week=1, block_size=2,
            activity_type=ActivityType.PRACTICAL,
        )
        requests = expand_assignments([a])
        assert len(requests) == 1
        assert requests[0].block_size == 2

    def test_zero_sessions_skipped(self):
        a = make_assignment(sessions_per_week=0)
        requests = expand_assignments([a])
        assert len(requests) == 0

    def test_multiple_assignments(self):
        a1 = make_assignment(assignment_id="A001", sessions_per_week=3)
        a2 = make_assignment(assignment_id="A002", sessions_per_week=2)
        requests = expand_assignments([a1, a2])
        assert len(requests) == 5  # 3 + 2

    def test_unique_request_ids(self):
        a = make_assignment(sessions_per_week=5)
        requests = expand_assignments([a])
        ids = [r.request_id for r in requests]
        assert len(set(ids)) == 5  # all unique


class TestPairG1G2:
    def test_pair_matching_g1_g2(self):
        g1 = make_assignment(
            assignment_id="A001", group="G1", teacher_id="T001",
            activity_type=ActivityType.PRACTICAL,
            sessions_per_week=1, block_size=2,
        )
        g2 = make_assignment(
            assignment_id="A002", group="G2", teacher_id="T002",
            activity_type=ActivityType.PRACTICAL,
            sessions_per_week=1, block_size=2,
        )
        requests = expand_assignments([g1, g2])
        pairs, unpaired = pair_g1_g2(requests)

        assert len(pairs) == 1
        assert len(unpaired) == 0
        # Verify the pair has one G1 and one G2
        groups = {pairs[0][0].assignment.group, pairs[0][1].assignment.group}
        assert groups == {"G1", "G2"}

    def test_lecture_not_paired(self):
        a1 = make_assignment(assignment_id="A001", group="ALL", sessions_per_week=3)
        requests = expand_assignments([a1])
        pairs, unpaired = pair_g1_g2(requests)
        assert len(pairs) == 0
        assert len(unpaired) == 3

    def test_single_g1_not_paired(self):
        """G1 without a matching G2 stays unpaired."""
        g1 = make_assignment(
            assignment_id="A001", group="G1",
            activity_type=ActivityType.PRACTICAL,
            sessions_per_week=1, block_size=2,
        )
        requests = expand_assignments([g1])
        pairs, unpaired = pair_g1_g2(requests)
        assert len(pairs) == 0
        assert len(unpaired) == 1

    def test_mixed_pairing(self):
        """Mix of lectures and paired practicals."""
        lec = make_assignment(
            assignment_id="A001", group="ALL",
            activity_type=ActivityType.LECTURE,
            sessions_per_week=3, block_size=1,
        )
        g1 = make_assignment(
            assignment_id="A002", group="G1",
            activity_type=ActivityType.PRACTICAL,
            sessions_per_week=1, block_size=2,
        )
        g2 = make_assignment(
            assignment_id="A003", group="G2", teacher_id="T002",
            activity_type=ActivityType.PRACTICAL,
            sessions_per_week=1, block_size=2,
        )

        requests = expand_assignments([lec, g1, g2])
        pairs, unpaired = pair_g1_g2(requests)

        assert len(pairs) == 1   # G1+G2 paired
        assert len(unpaired) == 3  # 3 lectures


class TestSortByDifficulty:
    def test_pairs_sorted_by_block_size(self):
        small_g1 = make_assignment(
            assignment_id="A001", group="G1", block_size=2,
            activity_type=ActivityType.PRACTICAL, sessions_per_week=1,
        )
        small_g2 = make_assignment(
            assignment_id="A002", group="G2", block_size=2, teacher_id="T002",
            activity_type=ActivityType.PRACTICAL, sessions_per_week=1,
        )
        big_g1 = make_assignment(
            assignment_id="A003", group="G1", block_size=3, subject_id="SUB002",
            activity_type=ActivityType.WORKSHOP, sessions_per_week=1,
        )
        big_g2 = make_assignment(
            assignment_id="A004", group="G2", block_size=3, teacher_id="T002",
            subject_id="SUB002",
            activity_type=ActivityType.WORKSHOP, sessions_per_week=1,
        )

        requests = expand_assignments([small_g1, small_g2, big_g1, big_g2])
        pairs, singles = pair_g1_g2(requests)
        pairs, singles = sort_by_difficulty(pairs, singles)

        # Big block pair should come first
        assert pairs[0][0].block_size == 3

    def test_practicals_before_lectures(self):
        lec = make_assignment(
            assignment_id="A001", sessions_per_week=1, block_size=1,
            activity_type=ActivityType.LECTURE,
        )
        prac = make_assignment(
            assignment_id="A002", sessions_per_week=1, block_size=2,
            group="G1", activity_type=ActivityType.PRACTICAL,
        )

        requests = expand_assignments([lec, prac])
        _, singles = pair_g1_g2(requests)
        _, singles = sort_by_difficulty([], singles)

        assert singles[0].assignment.activity_type == ActivityType.PRACTICAL


# ================================================================
# Slot Allocator Tests
# ================================================================

class TestSlotAllocator:
    def test_valid_starts_block_1(self):
        alloc = SlotAllocator(make_rooms())
        starts = alloc.get_valid_start_periods(1)
        assert starts == [1, 2, 3, 4, 5, 6, 7]

    def test_valid_starts_block_2(self):
        alloc = SlotAllocator(make_rooms())
        starts = alloc.get_valid_start_periods(2)
        # 4 is excluded (4-5 spans lunch), 7 is excluded (7-8 exceeds grid)
        assert starts == [1, 2, 3, 5, 6]

    def test_valid_starts_block_3(self):
        alloc = SlotAllocator(make_rooms())
        starts = alloc.get_valid_start_periods(3)
        # 3 excluded (3-4-5 spans lunch), 6 excluded (6-7-8 exceeds), 7 excluded
        assert starts == [1, 2, 5]

    def test_valid_starts_block_2_with_lunch_span(self):
        config = SchedulerConfig(allow_lunch_span=True)
        alloc = SlotAllocator(make_rooms(), config)
        starts = alloc.get_valid_start_periods(2)
        assert 4 in starts  # Now allowed

    def test_eligible_rooms_lecture(self):
        alloc = SlotAllocator(make_rooms())
        rooms = alloc.get_eligible_rooms(ActivityType.LECTURE)
        assert len(rooms) == 2  # L1, L2 (not inactive OLD)
        for r in rooms:
            assert r.room_type == RoomType.LECTURE

    def test_eligible_rooms_practical_cse(self):
        alloc = SlotAllocator(make_rooms())
        rooms = alloc.get_eligible_rooms(ActivityType.PRACTICAL, branch="CSE")
        assert len(rooms) == 3  # CC1, CC2, CC3
        for r in rooms:
            assert r.branch == "CSE"

    def test_eligible_rooms_practical_ece(self):
        alloc = SlotAllocator(make_rooms())
        rooms = alloc.get_eligible_rooms(ActivityType.PRACTICAL, branch="ECE")
        assert len(rooms) == 1  # DR

    def test_eligible_rooms_workshop(self):
        alloc = SlotAllocator(make_rooms())
        rooms = alloc.get_eligible_rooms(ActivityType.WORKSHOP)
        assert len(rooms) == 1  # WS1

    def test_eligible_rooms_drawing(self):
        alloc = SlotAllocator(make_rooms())
        rooms = alloc.get_eligible_rooms(ActivityType.DRAWING)
        assert len(rooms) == 1  # DH1

    def test_all_candidate_slots_block_1(self):
        alloc = SlotAllocator(make_rooms())
        candidates = alloc.get_all_candidate_slots(1)
        assert len(candidates) == 5 * 7  # 5 days × 7 periods

    def test_all_candidate_slots_block_2(self):
        alloc = SlotAllocator(make_rooms())
        candidates = alloc.get_all_candidate_slots(2)
        assert len(candidates) == 5 * 5  # 5 days × 5 valid starts

    def test_find_valid_placements_empty_state(self):
        alloc = SlotAllocator(make_rooms())
        state = ScheduleState()
        req = ScheduleRequest(
            request_id="SR0001",
            assignment=make_assignment(),
            block_size=1,
            session_index=1,
        )
        valid = alloc.find_valid_placements(req, state)
        assert len(valid) > 0
        # First should be MON slot 1
        slots, room_id = valid[0]
        assert slots[0].day == Day.MON
        assert slots[0].period == 1

    def test_find_valid_placements_teacher_busy(self):
        alloc = SlotAllocator(make_rooms())
        state = ScheduleState()

        # Occupy teacher T001 at MON slot 1
        existing = Placement(
            placement_id="P001",
            assignment=make_assignment(assignment_id="A999"),
            slots=[TimeSlot(Day.MON, 1)],
            room_id="R030",
        )
        state.add_placement(existing)

        req = ScheduleRequest(
            request_id="SR0001",
            assignment=make_assignment(),
            block_size=1,
            session_index=1,
        )
        valid = alloc.find_valid_placements(req, state)
        # Should skip MON slot 1
        for slots, _ in valid:
            assert not (slots[0].day == Day.MON and slots[0].period == 1)


# ================================================================
# TimetableScheduler End-to-End Tests
# ================================================================

class TestSchedulerSimple:
    """Basic scheduling scenarios."""

    def test_single_lecture(self):
        """One lecture, one session per week → placed at MON slot 1."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        a = make_assignment(sessions_per_week=1, block_size=1, weekly_periods=1)
        result = scheduler.schedule([a])

        assert result.is_complete
        assert len(result.placements) == 1
        p = result.placements[0]
        assert p.assignment is a
        assert len(p.slots) == 1
        assert p.room_id in ("R030", "R031")  # A lecture room

    def test_three_lectures_different_slots(self):
        """3 sessions per week → placed at 3 different time slots."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        a = make_assignment(sessions_per_week=3, block_size=1)
        result = scheduler.schedule([a])

        assert result.is_complete
        assert len(result.placements) == 3

        # All slots should be different
        all_slots = set()
        for p in result.placements:
            for s in p.slots:
                assert s not in all_slots
                all_slots.add(s)

    def test_practical_block_placed(self):
        """A 2-slot practical block is placed in consecutive slots."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        a = make_assignment(
            activity_type=ActivityType.PRACTICAL,
            group="G1",
            sessions_per_week=1,
            block_size=2,
            weekly_periods=2,
        )
        result = scheduler.schedule([a])

        assert result.is_complete
        assert len(result.placements) == 1
        p = result.placements[0]
        assert len(p.slots) == 2
        assert p.slots[0].day == p.slots[1].day  # Same day
        assert p.slots[1].period == p.slots[0].period + 1  # Consecutive
        assert p.room_id in ("R001", "R002", "R003")  # A CSE lab

    def test_practical_does_not_span_lunch(self):
        """Practical blocks never span the lunch break (slot 4→5)."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        a = make_assignment(
            activity_type=ActivityType.PRACTICAL,
            group="G1",
            sessions_per_week=1,
            block_size=2,
            weekly_periods=2,
        )
        result = scheduler.schedule([a])
        assert result.is_complete

        for p in result.placements:
            periods = [s.period for s in p.slots]
            assert not (4 in periods and 5 in periods)


class TestSchedulerParallel:
    """G1/G2 parallel practical placement."""

    def test_g1_g2_placed_same_slots(self):
        """G1 and G2 practicals must be at the same time, different rooms."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        g1 = make_assignment(
            assignment_id="A001", teacher_id="T001", group="G1",
            activity_type=ActivityType.PRACTICAL,
            sessions_per_week=1, block_size=2, weekly_periods=2,
        )
        g2 = make_assignment(
            assignment_id="A002", teacher_id="T002", group="G2",
            activity_type=ActivityType.PRACTICAL,
            sessions_per_week=1, block_size=2, weekly_periods=2,
        )

        result = scheduler.schedule([g1, g2])
        assert result.is_complete
        assert len(result.placements) == 2

        p1 = result.placements[0]
        p2 = result.placements[1]

        # Same time slots
        assert set(p1.slots) == set(p2.slots)
        # Different rooms
        assert p1.room_id != p2.room_id
        # Both are CSE labs
        for p in [p1, p2]:
            assert p.room_id in ("R001", "R002", "R003")

    def test_g1_g2_same_teacher_reported(self):
        """Same teacher for G1 and G2 → impossible, reported as unscheduled."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        g1 = make_assignment(
            assignment_id="A001", teacher_id="T001", group="G1",
            activity_type=ActivityType.PRACTICAL,
            sessions_per_week=1, block_size=2, weekly_periods=2,
        )
        g2 = make_assignment(
            assignment_id="A002", teacher_id="T001", group="G2",
            activity_type=ActivityType.PRACTICAL,
            sessions_per_week=1, block_size=2, weekly_periods=2,
        )

        result = scheduler.schedule([g1, g2])
        assert not result.is_complete
        assert len(result.unscheduled) == 2
        # Reason should mention the teacher conflict
        assert any("same teacher" in r.lower() for u in result.unscheduled for r in u.reasons)


class TestSchedulerConflicts:
    """Conflict avoidance tests."""

    def test_teacher_conflict_avoided(self):
        """Two assignments with the same teacher get different slots."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        a1 = make_assignment(
            assignment_id="A001", subject_id="SUB001",
            sessions_per_week=1, block_size=1,
        )
        a2 = make_assignment(
            assignment_id="A002", subject_id="SUB002",
            sessions_per_week=1, block_size=1,
        )

        result = scheduler.schedule([a1, a2])
        assert result.is_complete
        assert result.placements[0].slots != result.placements[1].slots

    def test_room_conflict_avoided(self):
        """Two assignments needing the same room type get different rooms or slots."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        a1 = make_assignment(
            assignment_id="A001", teacher_id="T001",
            sessions_per_week=1, block_size=1,
        )
        a2 = make_assignment(
            assignment_id="A002", teacher_id="T002", subject_id="SUB002",
            sessions_per_week=1, block_size=1,
        )

        result = scheduler.schedule([a1, a2])
        assert result.is_complete

        # If same slots, must be different rooms
        if set(result.placements[0].slots) == set(result.placements[1].slots):
            assert result.placements[0].room_id != result.placements[1].room_id

    def test_section_conflict_avoided(self):
        """Two ALL-group assignments for the same section get different slots."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        a1 = make_assignment(
            assignment_id="A001", teacher_id="T001",
            sessions_per_week=1, block_size=1,
        )
        a2 = make_assignment(
            assignment_id="A002", teacher_id="T002", subject_id="SUB002",
            sessions_per_week=1, block_size=1,
        )

        result = scheduler.schedule([a1, a2])
        assert result.is_complete
        # Both are group=ALL for section=A, so they can't overlap
        assert set(result.placements[0].slots) != set(result.placements[1].slots)

    def test_room_type_enforced(self):
        """Lectures go to lecture rooms, practicals to labs."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        lec = make_assignment(
            assignment_id="A001", activity_type=ActivityType.LECTURE,
            sessions_per_week=1, block_size=1,
        )
        prac = make_assignment(
            assignment_id="A002", teacher_id="T002",
            activity_type=ActivityType.PRACTICAL, group="G1",
            sessions_per_week=1, block_size=2, weekly_periods=2,
        )

        result = scheduler.schedule([lec, prac])
        assert result.is_complete

        for p in result.placements:
            room = rooms[p.room_id]
            if p.assignment.activity_type == ActivityType.LECTURE:
                assert room.room_type == RoomType.LECTURE
            else:
                assert room.room_type == RoomType.LAB

    def test_branch_lab_enforced(self):
        """CSE practicals go to CSE labs, not ECE labs."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        a = make_assignment(
            activity_type=ActivityType.PRACTICAL, group="G1",
            branch="CSE",
            sessions_per_week=1, block_size=2, weekly_periods=2,
        )

        result = scheduler.schedule([a])
        assert result.is_complete
        room = rooms[result.placements[0].room_id]
        assert room.branch == "CSE"


class TestSchedulerUnscheduled:
    """Tests for impossible schedules and unscheduled reporting."""

    def test_no_eligible_rooms(self):
        """No rooms of the right type → unscheduled with reason."""
        # Only lecture rooms, but assignment needs LAB
        rooms = {
            "R030": Room(room_id="R030", room_name="L1", room_type=RoomType.LECTURE,
                         branch=None, is_shared=True, active=True),
        }
        scheduler = TimetableScheduler(rooms=rooms)

        a = make_assignment(
            activity_type=ActivityType.PRACTICAL, group="G1",
            sessions_per_week=1, block_size=2, weekly_periods=2,
        )

        result = scheduler.schedule([a])
        assert not result.is_complete
        assert len(result.unscheduled) == 1
        assert any("no eligible" in r.lower() or "room" in r.lower()
                    for r in result.unscheduled[0].reasons)

    def test_teacher_saturated(self):
        """Teacher has more sessions than available slots → some unscheduled."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        # 35 sessions for one teacher (fills all 35 weekly slots)
        full = make_assignment(
            assignment_id="A001",
            sessions_per_week=35,
            block_size=1,
            weekly_periods=35,
        )
        # One more session for the same teacher → impossible
        extra = make_assignment(
            assignment_id="A002",
            subject_id="SUB999",
            sessions_per_week=1,
            block_size=1,
            weekly_periods=1,
        )

        result = scheduler.schedule([full, extra])
        assert not result.is_complete
        assert len(result.unscheduled) >= 1

    def test_unscheduled_has_reasons(self):
        """Unscheduled sessions must include diagnostic reasons."""
        # Only 1 room, but need 2 for G1/G2
        rooms = {
            "R001": Room(room_id="R001", room_name="CC1", room_type=RoomType.LAB,
                         branch="CSE", is_shared=False, active=True),
        }
        scheduler = TimetableScheduler(rooms=rooms)

        g1 = make_assignment(
            assignment_id="A001", teacher_id="T001", group="G1",
            activity_type=ActivityType.PRACTICAL,
            sessions_per_week=1, block_size=2, weekly_periods=2,
        )
        g2 = make_assignment(
            assignment_id="A002", teacher_id="T002", group="G2",
            activity_type=ActivityType.PRACTICAL,
            sessions_per_week=1, block_size=2, weekly_periods=2,
        )

        result = scheduler.schedule([g1, g2])
        assert not result.is_complete
        for u in result.unscheduled:
            assert len(u.reasons) > 0
            assert u.subject_id == "SUB001"

    def test_unscheduled_to_dict(self):
        """UnscheduledSession serializes properly."""
        rooms = {
            "R001": Room(room_id="R001", room_name="CC1", room_type=RoomType.LAB,
                         branch="CSE", is_shared=False, active=True),
        }
        scheduler = TimetableScheduler(rooms=rooms)

        g1 = make_assignment(
            assignment_id="A001", teacher_id="T001", group="G1",
            activity_type=ActivityType.PRACTICAL,
            sessions_per_week=1, block_size=2, weekly_periods=2,
        )
        g2 = make_assignment(
            assignment_id="A002", teacher_id="T002", group="G2",
            activity_type=ActivityType.PRACTICAL,
            sessions_per_week=1, block_size=2, weekly_periods=2,
        )

        result = scheduler.schedule([g1, g2])
        d = result.to_dict()
        assert d["is_complete"] is False
        assert d["unscheduled_count"] >= 2
        assert isinstance(d["unscheduled"], list)
        for u in d["unscheduled"]:
            assert "reasons" in u
            assert "subject_id" in u


class TestSchedulerStats:
    """Test result statistics."""

    def test_stats_populated(self):
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        a = make_assignment(sessions_per_week=3, block_size=1)
        result = scheduler.schedule([a])

        assert "total_sessions" in result.stats
        assert result.stats["total_sessions"] == 3
        assert result.stats["placed"] == 3
        assert result.stats["unscheduled"] == 0
        assert result.stats["completion_rate"] == 100.0
        assert result.stats["total_weekly_slots"] == 35

    def test_completion_rate_partial(self):
        """Completion rate reflects partial scheduling."""
        rooms = {
            "R030": Room(room_id="R030", room_name="L1", room_type=RoomType.LECTURE,
                         branch=None, is_shared=True, active=True),
        }
        scheduler = TimetableScheduler(rooms=rooms)

        # 2 sessions needing LECTURE room + 1 needing LAB (impossible)
        lec = make_assignment(
            assignment_id="A001", sessions_per_week=2, block_size=1,
        )
        prac = make_assignment(
            assignment_id="A002", teacher_id="T002",
            activity_type=ActivityType.PRACTICAL, group="G1",
            sessions_per_week=1, block_size=2, weekly_periods=2,
        )

        result = scheduler.schedule([lec, prac])
        assert result.stats["placed"] == 2
        assert result.stats["unscheduled"] == 1
        assert result.stats["completion_rate"] < 100.0


class TestSchedulerFullWorkload:
    """Test with a realistic multi-subject workload."""

    def test_multiple_subjects_one_section(self):
        """Schedule 4 subjects for section A (mix of lectures and practicals)."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        assignments = [
            # Subject 1: 3 lectures
            make_assignment(
                assignment_id="A001", teacher_id="T001", subject_id="SUB001",
                activity_type=ActivityType.LECTURE, group="ALL",
                sessions_per_week=3, block_size=1, weekly_periods=3,
            ),
            # Subject 2: 2 lectures
            make_assignment(
                assignment_id="A002", teacher_id="T002", subject_id="SUB002",
                activity_type=ActivityType.LECTURE, group="ALL",
                sessions_per_week=2, block_size=1, weekly_periods=2,
            ),
            # Subject 3: 1 practical G1
            make_assignment(
                assignment_id="A003", teacher_id="T003", subject_id="SUB003",
                activity_type=ActivityType.PRACTICAL, group="G1",
                sessions_per_week=1, block_size=2, weekly_periods=2,
            ),
            # Subject 3: 1 practical G2
            make_assignment(
                assignment_id="A004", teacher_id="T004", subject_id="SUB003",
                activity_type=ActivityType.PRACTICAL, group="G2",
                sessions_per_week=1, block_size=2, weekly_periods=2,
            ),
        ]

        result = scheduler.schedule(assignments)

        assert result.is_complete
        assert len(result.placements) == 7  # 3 + 2 + 1 + 1

        # Verify no teacher has overlapping slots
        teacher_slots: Dict[str, set] = {}
        for p in result.placements:
            tid = p.assignment.teacher_id
            if tid not in teacher_slots:
                teacher_slots[tid] = set()
            for s in p.slots:
                assert s not in teacher_slots[tid], f"Teacher {tid} has overlap at {s}"
                teacher_slots[tid].add(s)

        # Verify no room has overlapping slots
        room_slots: Dict[str, set] = {}
        for p in result.placements:
            rid = p.room_id
            if rid not in room_slots:
                room_slots[rid] = set()
            for s in p.slots:
                assert s not in room_slots[rid], f"Room {rid} has overlap at {s}"
                room_slots[rid].add(s)

    def test_workshop_3_block(self):
        """A 3-slot workshop block gets placed correctly."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        a = make_assignment(
            activity_type=ActivityType.WORKSHOP, group="G1",
            sessions_per_week=1, block_size=3, weekly_periods=3,
        )
        result = scheduler.schedule([a])

        assert result.is_complete
        p = result.placements[0]
        assert len(p.slots) == 3
        periods = sorted(s.period for s in p.slots)
        assert periods[2] - periods[0] == 2  # Consecutive
        assert p.room_id == "R050"  # Workshop room

    def test_schedule_result_serialization(self):
        """ScheduleResult.to_dict() produces valid output."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        a = make_assignment(sessions_per_week=2, block_size=1)
        result = scheduler.schedule([a])

        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["is_complete"] is True
        assert d["placed_count"] == 2
        assert d["unscheduled_count"] == 0
        assert "stats" in d

    def test_empty_assignments(self):
        """No assignments → empty result, 100% completion."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        result = scheduler.schedule([])
        assert result.is_complete
        assert len(result.placements) == 0
        assert result.stats["completion_rate"] == 100.0


# ================================================================
# Central Mandate: Seeded Random Valid Placement
# ================================================================

def _timetable_signature(result: ScheduleResult):
    """Canonical, order-independent fingerprint of a timetable.

    Two schedules with the same signature place exactly the same
    sessions in the same slots and rooms.  Used to assert per-seed
    reproducibility and cross-seed divergence.
    """
    return tuple(sorted(
        (
            p.assignment.assignment_id,
            p.assignment.group,
            tuple(sorted((s.day.value, s.period) for s in p.slots)),
            p.room_id,
        )
        for p in result.placements
    ))


class TestSchedulerSeededRandomValid:
    """Protect the central mandate: RANDOM VALID PLACEMENT +
    ZERO CLASHES + COMPLETE WORKLOAD, reproducible per seed."""

    def _mixed_workload(self) -> List[Assignment]:
        """A workload with a large valid-placement space (many free
        slots) so different seeds can diverge."""
        return [
            make_assignment(
                assignment_id="A001", teacher_id="T001", subject_id="SUB001",
                activity_type=ActivityType.LECTURE, group="ALL",
                sessions_per_week=3, block_size=1, weekly_periods=3,
            ),
            make_assignment(
                assignment_id="A002", teacher_id="T002", subject_id="SUB002",
                activity_type=ActivityType.LECTURE, group="ALL",
                sessions_per_week=3, block_size=1, weekly_periods=3,
            ),
            make_assignment(
                assignment_id="A003", teacher_id="T003", subject_id="SUB003",
                activity_type=ActivityType.LECTURE, group="ALL",
                sessions_per_week=2, block_size=1, weekly_periods=2,
            ),
        ]

    def test_same_seed_is_reproducible(self):
        """Identical seed → byte-for-byte identical timetable."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)
        assignments = self._mixed_workload()

        r1 = scheduler.schedule(assignments, seed=12345)
        r2 = scheduler.schedule(assignments, seed=12345)

        assert r1.is_complete and r2.is_complete
        assert _timetable_signature(r1) == _timetable_signature(r2)

    def test_default_seed_matches_explicit_default(self):
        """No seed argument uses DEFAULT_SEED (12345) reproducibly."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)
        assignments = self._mixed_workload()

        implicit = scheduler.schedule(assignments)
        explicit = scheduler.schedule(assignments, seed=12345)

        assert implicit.stats["seed"] == 12345
        assert _timetable_signature(implicit) == _timetable_signature(explicit)

    def test_different_seeds_diverge(self):
        """Different seeds explore different valid timetables.

        Probabilistic in principle, but with this many free slots and
        eight seeds the chance of a single collision across all of them
        is negligible; a failure here means the seed is being ignored."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)
        assignments = self._mixed_workload()

        seeds = [12345, 777, 2026, 99, 1, 42, 7, 100]
        signatures = {
            s: _timetable_signature(scheduler.schedule(assignments, seed=s))
            for s in seeds
        }
        assert len(set(signatures.values())) >= 2, (
            "Seed has no effect on placement — randomization is broken"
        )

    def test_every_sampled_seed_is_complete_and_clash_free(self):
        """The mandate must hold for every seed: full workload, zero
        teacher/room/section clashes."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)
        assignments = self._mixed_workload()

        for seed in [12345, 777, 2026, 99, 1, 42, 7, 100]:
            result = scheduler.schedule(assignments, seed=seed)
            assert result.is_complete, f"seed {seed}: incomplete workload"
            assert len(result.unscheduled) == 0, f"seed {seed}: unscheduled sessions"

            teacher_slots: Dict[str, set] = {}
            room_slots: Dict[str, set] = {}
            section_slots: Dict[tuple, set] = {}
            for p in result.placements:
                tid = p.assignment.teacher_id
                for s in p.slots:
                    assert s not in teacher_slots.setdefault(tid, set()), (
                        f"seed {seed}: teacher clash {tid} at {s}"
                    )
                    teacher_slots[tid].add(s)
                    assert s not in room_slots.setdefault(p.room_id, set()), (
                        f"seed {seed}: room clash {p.room_id} at {s}"
                    )
                    room_slots[p.room_id].add(s)
                    key = (p.assignment.section, p.assignment.group)
                    assert s not in section_slots.setdefault(key, set()), (
                        f"seed {seed}: section clash {key} at {s}"
                    )
                    section_slots[key].add(s)

    def test_g1_g2_no_double_count_at_scheduler_level(self):
        """A weekly=4 / block=2 practical yields G1=4 periods and G2=4
        periods occupying the SAME 4 academic periods — never 8.

        This protects the no-double-count rule at the placement layer:
        parallel groups share their exact slots, so the section spends
        only its true 4-period practical workload."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        g1 = make_assignment(
            assignment_id="A_G1", teacher_id="T001", subject_id="SUB009",
            activity_type=ActivityType.PRACTICAL, group="G1",
            sessions_per_week=2, block_size=2, weekly_periods=4,
        )
        g2 = make_assignment(
            assignment_id="A_G2", teacher_id="T002", subject_id="SUB009",
            activity_type=ActivityType.PRACTICAL, group="G2",
            sessions_per_week=2, block_size=2, weekly_periods=4,
        )

        result = scheduler.schedule([g1, g2], seed=12345)
        assert result.is_complete

        g1_p = [p for p in result.placements if p.assignment.group == "G1"]
        g2_p = [p for p in result.placements if p.assignment.group == "G2"]

        # Each group carries its own full workload of 4 periods.
        assert sum(len(p.slots) for p in g1_p) == 4
        assert sum(len(p.slots) for p in g2_p) == 4

        # Every G1 block is mirrored by a G2 block on the identical slots
        # in a different room — parallel, not sequential.
        g1_blocks = {frozenset(p.slots) for p in g1_p}
        g2_blocks = {frozenset(p.slots) for p in g2_p}
        assert g1_blocks == g2_blocks, "G1/G2 blocks are not on the same slots"
        for p1 in g1_p:
            mirror = [p for p in g2_p if set(p.slots) == set(p1.slots)]
            assert mirror, "G1 block has no parallel G2 block"
            assert mirror[0].room_id != p1.room_id, "G1/G2 share a room"

        # The section spends exactly 4 academic periods, NOT 8.
        academic_slots = set()
        for p in result.placements:
            academic_slots.update(p.slots)
        assert len(academic_slots) == 4, (
            f"Expected 4 shared academic periods, got {len(academic_slots)}"
        )
