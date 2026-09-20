"""
Tests for the timetable quality scoring system.

Tests cover:
    - Helper functions (consecutive runs, gap counting)
    - DayTracker incremental statistics
    - Individual penalty functions (S1--S6)
    - Full timetable scoring
    - Candidate scoring (used by scheduler for best-first selection)
    - Integration with the scheduler (score in result)
"""

import pytest
from typing import Dict, List

from app.models.enums import ActivityType, RoomType, Day
from app.models.room import Room
from app.models.assignment import Assignment
from app.models.slot import TimeSlot
from app.models.placement import Placement
from app.engine.scoring import (
    TimetableScorer,
    ScoreReport,
    ScoringWeights,
    SoftPenalty,
    DayTracker,
    _longest_consecutive_run,
    _count_gaps,
)
from app.engine.scheduler import TimetableScheduler


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


def make_placement(
    assignment=None, slots=None, room_id="R030", placement_id="P001",
):
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
        "R003": Room(room_id="R003", room_name="CC3", room_type=RoomType.LAB, branch="CSE", is_shared=False, active=True),
        "R030": Room(room_id="R030", room_name="L1", room_type=RoomType.LECTURE, branch=None, is_shared=True, active=True),
        "R031": Room(room_id="R031", room_name="L2", room_type=RoomType.LECTURE, branch=None, is_shared=True, active=True),
        "R040": Room(room_id="R040", room_name="DH1", room_type=RoomType.DRAWING_HALL, branch=None, is_shared=True, active=True),
        "R050": Room(room_id="R050", room_name="WS1", room_type=RoomType.WORKSHOP, branch=None, is_shared=True, active=True),
    }


# ================================================================
# Helper Function Tests
# ================================================================

class TestLongestConsecutiveRun:
    def test_empty(self):
        assert _longest_consecutive_run(set()) == 0

    def test_single(self):
        assert _longest_consecutive_run({3}) == 1

    def test_consecutive(self):
        assert _longest_consecutive_run({1, 2, 3}) == 3

    def test_with_gap(self):
        assert _longest_consecutive_run({1, 2, 4, 5, 6}) == 3

    def test_non_consecutive(self):
        assert _longest_consecutive_run({1, 3, 5, 7}) == 1

    def test_full_day(self):
        assert _longest_consecutive_run({1, 2, 3, 4, 5, 6, 7}) == 7


class TestCountGaps:
    def test_empty(self):
        assert _count_gaps(set()) == 0

    def test_single(self):
        assert _count_gaps({3}) == 0

    def test_consecutive_no_gaps(self):
        assert _count_gaps({1, 2, 3}) == 0

    def test_one_gap(self):
        assert _count_gaps({1, 3}) == 1

    def test_two_period_gap(self):
        assert _count_gaps({1, 4}) == 2

    def test_lunch_gap_not_counted(self):
        """Gap between period 4 and 5 (lunch) is not a gap."""
        assert _count_gaps({4, 5}) == 0

    def test_lunch_gap_with_real_gap(self):
        """Period 4 to 6 has lunch gap (OK) + real gap at period 5→6? No, 5 is missing."""
        assert _count_gaps({3, 4, 6}) == 1  # gap at 5→6 (5 missing)

    def test_complex(self):
        # {1, 2, 4, 5, 7} → gap at 3 (between 2 and 4), gap at 6 (between 5 and 7)
        # but 4→5 is lunch, not counted
        assert _count_gaps({1, 2, 4, 5, 7}) == 2  # gap at period 3 and 6


# ================================================================
# DayTracker Tests
# ================================================================

class TestDayTracker:
    def test_add_placement(self):
        tracker = DayTracker()
        p = make_placement(slots=[TimeSlot(Day.MON, 1), TimeSlot(Day.MON, 2)])
        tracker.add_placement(p)

        assert tracker.teacher_periods_on_day("T001", Day.MON) == 2
        assert tracker.section_periods_on_day("A", Day.MON) == {1, 2}
        assert Day.MON in tracker.subject_days("SUB001", "A")

    def test_remove_placement(self):
        tracker = DayTracker()
        p = make_placement(slots=[TimeSlot(Day.MON, 1)])
        tracker.add_placement(p)
        tracker.remove_placement(p)

        assert tracker.teacher_periods_on_day("T001", Day.MON) == 0

    def test_multiple_placements(self):
        tracker = DayTracker()
        p1 = make_placement(
            placement_id="P001",
            slots=[TimeSlot(Day.MON, 1)],
        )
        p2 = make_placement(
            assignment=make_assignment(assignment_id="A002", subject_id="SUB002"),
            placement_id="P002",
            slots=[TimeSlot(Day.MON, 2)],
        )
        tracker.add_placement(p1)
        tracker.add_placement(p2)

        assert tracker.teacher_periods_on_day("T001", Day.MON) == 2
        assert tracker.section_periods_on_day("A", Day.MON) == {1, 2}

    def test_different_days(self):
        tracker = DayTracker()
        p1 = make_placement(
            placement_id="P001",
            slots=[TimeSlot(Day.MON, 1)],
        )
        p2 = make_placement(
            assignment=make_assignment(assignment_id="A002", subject_id="SUB002"),
            placement_id="P002",
            slots=[TimeSlot(Day.TUE, 1)],
        )
        tracker.add_placement(p1)
        tracker.add_placement(p2)

        assert tracker.teacher_periods_on_day("T001", Day.MON) == 1
        assert tracker.teacher_periods_on_day("T001", Day.TUE) == 1


# ================================================================
# Full Timetable Scoring Tests
# ================================================================

class TestFullScoring:
    def test_empty_timetable_perfect(self):
        scorer = TimetableScorer()
        report = scorer.score_timetable([])
        assert report.total_score == 100.0
        assert report.hard_violation_count == 0

    def test_single_placement_high_score(self):
        scorer = TimetableScorer()
        p = make_placement(slots=[TimeSlot(Day.MON, 1)])
        report = scorer.score_timetable([p])
        assert report.total_score > 80.0

    def test_subject_distribution_penalised(self):
        """Two sessions of the same subject on the same day → penalty."""
        scorer = TimetableScorer()
        a = make_assignment()
        p1 = make_placement(assignment=a, placement_id="P001",
                            slots=[TimeSlot(Day.MON, 1)])
        p2 = make_placement(assignment=a, placement_id="P002",
                            slots=[TimeSlot(Day.MON, 2)])
        report = scorer.score_timetable([p1, p2])

        dist_penalty = next(
            p for p in report.penalties if p.name == "subject_distribution"
        )
        assert dist_penalty.raw_penalty > 0

    def test_subject_distribution_good(self):
        """Sessions on different days → no distribution penalty."""
        scorer = TimetableScorer()
        a = make_assignment()
        p1 = make_placement(assignment=a, placement_id="P001",
                            slots=[TimeSlot(Day.MON, 1)])
        p2 = make_placement(assignment=a, placement_id="P002",
                            slots=[TimeSlot(Day.TUE, 1)])
        report = scorer.score_timetable([p1, p2])

        dist_penalty = next(
            p for p in report.penalties if p.name == "subject_distribution"
        )
        assert dist_penalty.raw_penalty == 0

    def test_teacher_overload_penalised(self):
        """Teacher with 7 periods on one day → exceeds threshold of 6."""
        scorer = TimetableScorer()
        placements = []
        for i in range(7):
            placements.append(make_placement(
                assignment=make_assignment(
                    assignment_id=f"A{i:03d}",
                    subject_id=f"SUB{i:03d}",
                ),
                placement_id=f"P{i:03d}",
                slots=[TimeSlot(Day.MON, i + 1)],
            ))
        report = scorer.score_timetable(placements)

        teacher_penalty = next(
            p for p in report.penalties if p.name == "teacher_daily_load"
        )
        assert teacher_penalty.raw_penalty > 0

    def test_gaps_penalised(self):
        """Periods 1 and 3 with gap at 2 → gap penalty."""
        scorer = TimetableScorer()
        a1 = make_assignment(assignment_id="A001", subject_id="SUB001")
        a2 = make_assignment(assignment_id="A002", subject_id="SUB002",
                             teacher_id="T002")
        p1 = make_placement(assignment=a1, placement_id="P001",
                            slots=[TimeSlot(Day.MON, 1)])
        p2 = make_placement(assignment=a2, placement_id="P002",
                            slots=[TimeSlot(Day.MON, 3)])
        report = scorer.score_timetable([p1, p2])

        gap_penalty = next(
            p for p in report.penalties if p.name == "section_gaps"
        )
        assert gap_penalty.raw_penalty > 0

    def test_no_gaps(self):
        """Consecutive periods → no gap penalty."""
        scorer = TimetableScorer()
        a1 = make_assignment(assignment_id="A001", subject_id="SUB001")
        a2 = make_assignment(assignment_id="A002", subject_id="SUB002",
                             teacher_id="T002")
        p1 = make_placement(assignment=a1, placement_id="P001",
                            slots=[TimeSlot(Day.MON, 1)])
        p2 = make_placement(assignment=a2, placement_id="P002",
                            slots=[TimeSlot(Day.MON, 2)])
        report = scorer.score_timetable([p1, p2])

        gap_penalty = next(
            p for p in report.penalties if p.name == "section_gaps"
        )
        assert gap_penalty.raw_penalty == 0

    def test_room_preference_honoured(self):
        """Preferred room used → no room preference penalty."""
        scorer = TimetableScorer()
        a = make_assignment(room_id="R030")
        p = make_placement(assignment=a, room_id="R030")
        report = scorer.score_timetable([p])

        pref_penalty = next(
            p for p in report.penalties if p.name == "room_preference"
        )
        assert pref_penalty.raw_penalty == 0

    def test_room_preference_violated(self):
        """Preferred room not used → penalty."""
        scorer = TimetableScorer()
        a = make_assignment(room_id="R030")
        p = make_placement(assignment=a, room_id="R031")
        report = scorer.score_timetable([p])

        pref_penalty = next(
            p for p in report.penalties if p.name == "room_preference"
        )
        assert pref_penalty.raw_penalty > 0

    def test_score_report_serialization(self):
        scorer = TimetableScorer()
        p = make_placement(slots=[TimeSlot(Day.MON, 1)])
        report = scorer.score_timetable([p])
        d = report.to_dict()

        assert "total_score" in d
        assert "penalties" in d
        assert "hard_violation_count" in d
        assert isinstance(d["penalties"], list)
        assert len(d["penalties"]) == 6  # 6 soft constraints

    def test_six_penalties_always_present(self):
        scorer = TimetableScorer()
        p = make_placement(slots=[TimeSlot(Day.MON, 1)])
        report = scorer.score_timetable([p])

        names = {pen.name for pen in report.penalties}
        expected = {
            "subject_distribution",
            "consecutive_classes",
            "teacher_daily_load",
            "section_gaps",
            "practical_organisation",
            "room_preference",
        }
        assert names == expected


# ================================================================
# Candidate Scoring Tests
# ================================================================

class TestCandidateScoring:
    def test_prefer_different_day(self):
        """Candidate on a new day should score better than same day."""
        scorer = TimetableScorer()
        tracker = DayTracker()

        a = make_assignment()
        # Already have a session on Monday
        p1 = make_placement(assignment=a, slots=[TimeSlot(Day.MON, 1)])
        tracker.add_placement(p1)

        # Score Monday vs Tuesday
        score_mon = scorer.score_candidate(
            [TimeSlot(Day.MON, 2)], "R030", a, tracker,
        )
        score_tue = scorer.score_candidate(
            [TimeSlot(Day.TUE, 1)], "R030", a, tracker,
        )

        assert score_tue < score_mon  # Tuesday is better

    def test_prefer_less_loaded_teacher_day(self):
        """Teacher with 5 periods today → Tuesday should be preferred."""
        scorer = TimetableScorer()
        tracker = DayTracker()

        a = make_assignment()
        for i in range(5):
            p = make_placement(
                assignment=make_assignment(assignment_id=f"A{i:03d}", subject_id=f"SUB{i:03d}"),
                placement_id=f"P{i:03d}",
                slots=[TimeSlot(Day.MON, i + 1)],
            )
            tracker.add_placement(p)

        score_mon = scorer.score_candidate(
            [TimeSlot(Day.MON, 6)], "R030", a, tracker,
        )
        score_tue = scorer.score_candidate(
            [TimeSlot(Day.TUE, 1)], "R030", a, tracker,
        )

        assert score_tue < score_mon

    def test_prefer_no_gap(self):
        """Slot that avoids gaps should score better."""
        scorer = TimetableScorer()
        tracker = DayTracker()

        a = make_assignment()
        # Section has period 1 on Monday
        p1 = make_placement(
            assignment=make_assignment(assignment_id="A000", subject_id="SUB000", teacher_id="T000"),
            slots=[TimeSlot(Day.MON, 1)],
        )
        tracker.add_placement(p1)

        # Period 2 (no gap) vs period 4 (gap at 2, 3)
        score_2 = scorer.score_candidate(
            [TimeSlot(Day.MON, 2)], "R030", a, tracker,
        )
        score_4 = scorer.score_candidate(
            [TimeSlot(Day.MON, 4)], "R030", a, tracker,
        )

        assert score_2 < score_4  # Period 2 is better (no gap)

    def test_preferred_room_bonus(self):
        """Candidate using preferred room should score better."""
        scorer = TimetableScorer()
        tracker = DayTracker()

        a = make_assignment(room_id="R030")  # Prefers R030

        score_preferred = scorer.score_candidate(
            [TimeSlot(Day.MON, 1)], "R030", a, tracker,
        )
        score_other = scorer.score_candidate(
            [TimeSlot(Day.MON, 1)], "R031", a, tracker,
        )

        assert score_preferred < score_other

    def test_practical_clean_start_bonus(self):
        """Practical at slot 1 (clean start) should score better than slot 2."""
        scorer = TimetableScorer()
        tracker = DayTracker()

        a = make_assignment(activity_type=ActivityType.PRACTICAL, group="G1")

        score_1 = scorer.score_candidate(
            [TimeSlot(Day.MON, 1), TimeSlot(Day.MON, 2)], "R001", a, tracker,
        )
        score_2 = scorer.score_candidate(
            [TimeSlot(Day.MON, 2), TimeSlot(Day.MON, 3)], "R001", a, tracker,
        )

        assert score_1 < score_2  # Slot 1 is cleaner


# ================================================================
# Scheduler Integration Tests
# ================================================================

class TestSchedulerWithScoring:
    def test_result_has_score_report(self):
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)
        a = make_assignment(sessions_per_week=1, block_size=1, weekly_periods=1)
        result = scheduler.schedule([a])

        assert result.score_report is not None
        assert result.score > 0
        assert len(result.score_report.penalties) == 6

    def test_score_in_to_dict(self):
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)
        a = make_assignment(sessions_per_week=1, block_size=1, weekly_periods=1)
        result = scheduler.schedule([a])

        d = result.to_dict()
        assert "score" in d
        assert "score_report" in d
        assert d["score_report"]["hard_violation_count"] == 0

    def test_subjects_distributed_across_days(self):
        """With scoring, 3 sessions of one subject should land on 3 different days."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        a = make_assignment(sessions_per_week=3, block_size=1)
        result = scheduler.schedule([a])

        assert result.is_complete
        days = {p.slots[0].day for p in result.placements}
        assert len(days) == 3  # 3 different days

    def test_two_subjects_avoid_same_slot(self):
        """Two subjects for the same section should be on different slots."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        a1 = make_assignment(
            assignment_id="A001", teacher_id="T001", subject_id="SUB001",
            sessions_per_week=2, block_size=1, weekly_periods=2,
        )
        a2 = make_assignment(
            assignment_id="A002", teacher_id="T002", subject_id="SUB002",
            sessions_per_week=2, block_size=1, weekly_periods=2,
        )
        result = scheduler.schedule([a1, a2])

        assert result.is_complete
        assert result.score > 60  # Should be a reasonable score

    def test_scoring_with_custom_weights(self):
        rooms = make_rooms()
        weights = ScoringWeights(
            subject_distribution=30.0,
            room_preference=10.0,
        )
        scheduler = TimetableScheduler(rooms=rooms, weights=weights)
        a = make_assignment(sessions_per_week=2, block_size=1, weekly_periods=2)
        result = scheduler.schedule([a])

        assert result.is_complete
        assert result.score_report is not None

    def test_hard_constraints_never_violated(self):
        """Even with scoring, hard constraints must hold."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        assignments = [
            make_assignment(
                assignment_id=f"A{i:03d}",
                teacher_id=f"T{(i % 3) + 1:03d}",
                subject_id=f"SUB{i:03d}",
                sessions_per_week=2,
                block_size=1,
                weekly_periods=2,
            )
            for i in range(6)
        ]
        result = scheduler.schedule(assignments)

        # Verify no teacher overlaps
        teacher_slots = {}
        for p in result.placements:
            tid = p.assignment.teacher_id
            if tid not in teacher_slots:
                teacher_slots[tid] = set()
            for s in p.slots:
                assert s not in teacher_slots[tid], f"Teacher {tid} overlap at {s}"
                teacher_slots[tid].add(s)

        # Verify no section overlaps (all group=ALL)
        section_slots = set()
        for p in result.placements:
            for s in p.slots:
                assert s not in section_slots, f"Section overlap at {s}"
                section_slots.add(s)

    def test_empty_schedule_perfect_score(self):
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)
        result = scheduler.schedule([])
        assert result.score == 100.0
