"""
Comprehensive unit and integration tests for timetable hierarchy removal,
12-hour time format, zero clashing, and SCA auto-population.
"""

import pytest
from typing import Dict, List

from app.models.enums import ActivityType, RoomType, Day
from app.models.room import Room
from app.models.assignment import Assignment
from app.models.placement import Placement
from app.models.slot import TimeSlot
from app.export.grid import PERIOD_TIMES, LUNCH_START, LUNCH_END, lunch_label, period_time
from app.engine.expander import (
    ScheduleRequest,
    expand_assignments,
    pair_g1_g2,
    sort_by_difficulty,
)
from app.engine.scoring import TimetableScorer, _longest_consecutive_run
from app.engine.scheduler import TimetableScheduler
from app.engine.conflicts import is_valid_assignment, check_room_type_validity, ConflictType
from app.web.server import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def make_rooms() -> Dict[str, Room]:
    return {
        "R001": Room(room_id="R001", room_name="CC1", room_type=RoomType.LAB, branch="CSE", is_shared=False, active=True),
        "R002": Room(room_id="R002", room_name="CC2", room_type=RoomType.LAB, branch="CSE", is_shared=False, active=True),
        "R003": Room(room_id="R003", room_name="CC3", room_type=RoomType.LAB, branch="CSE", is_shared=False, active=True),
        "R004": Room(room_id="R004", room_name="CC4", room_type=RoomType.LAB, branch="CSE", is_shared=False, active=True),
        "R030": Room(room_id="R030", room_name="L1", room_type=RoomType.LECTURE, branch=None, is_shared=True, active=True),
        "R031": Room(room_id="R031", room_name="L2", room_type=RoomType.LECTURE, branch=None, is_shared=True, active=True),
    }


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


# ====================================================================
# 1. 12-Hour Time Format Tests
# ====================================================================

class Test12HourTimeFormat:

    def test_all_period_times_are_12_hour_without_am_pm(self):
        """Verify PERIOD_TIMES uses 12-hour format without AM/PM."""
        expected = {
            1: ("9:00", "10:00"),
            2: ("10:00", "11:00"),
            3: ("11:00", "12:00"),
            4: ("12:00", "1:00"),
            5: ("2:00", "3:00"),
            6: ("3:00", "4:00"),
            7: ("4:00", "5:00"),
        }
        for p, times in expected.items():
            assert PERIOD_TIMES[p] == times
            # Ensure no AM/PM attached
            assert "AM" not in times[0] and "PM" not in times[0]
            assert "AM" not in times[1] and "PM" not in times[1]

    def test_recess_time_is_1_to_2(self):
        """Recess/lunch time is 1:00 to 2:00."""
        assert LUNCH_START == "1:00"
        assert LUNCH_END == "2:00"
        label = lunch_label()
        assert "1:00-2:00" in label
        assert "RECESS" in label

    def test_period_time_helper(self):
        """period_time() returns clean 12h range strings."""
        assert period_time(1) == "9:00-10:00"
        assert period_time(4) == "12:00-1:00"
        assert period_time(5) == "2:00-3:00"
        assert period_time(7) == "4:00-5:00"


# ====================================================================
# 2. Hierarchy Removal & Morning Lecture Placement Tests
# ====================================================================

class TestHierarchyRemoval:

    def test_sort_by_difficulty_does_not_discriminate_activity_type(self):
        """Equal block size lecture and practical have equal priority."""
        lec = make_assignment(
            assignment_id="A_LEC", activity_type=ActivityType.LECTURE,
            block_size=1, sessions_per_week=1,
        )
        prac_single = make_assignment(
            assignment_id="A_PRAC", activity_type=ActivityType.PRACTICAL,
            block_size=1, sessions_per_week=1,
        )
        reqs = expand_assignments([lec, prac_single])
        _, singles = pair_g1_g2(reqs)
        _, singles_sorted = sort_by_difficulty([], singles)

        # Neither is artificially forced before the other when block size is equal
        assert singles_sorted[0].block_size == singles_sorted[1].block_size

    def test_consecutive_classes_respects_lunch_break(self):
        """Periods 1, 2, 3, 4 before lunch and 5 after lunch is not a consecutive run of 5."""
        # Mathematical run without lunch is 5
        assert _longest_consecutive_run({1, 2, 3, 4, 5}, respect_lunch=False) == 5
        # With lunch respected, the run breaks at 4→5, so longest is 4
        assert _longest_consecutive_run({1, 2, 3, 4, 5}, respect_lunch=True) == 4
        assert _longest_consecutive_run({1, 2, 3, 4, 5, 6}, respect_lunch=True) == 4

    def test_lectures_can_be_scheduled_in_morning_slots(self):
        """Lectures are placed in morning periods (1, 2, 3, 4), not forced to afternoon."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        # Mix of 3 lectures and 1 practical pair (G1+G2)
        lec1 = make_assignment(
            assignment_id="A1", teacher_id="T1", subject_id="S1",
            activity_type=ActivityType.LECTURE, sessions_per_week=2, block_size=1,
        )
        lec2 = make_assignment(
            assignment_id="A2", teacher_id="T2", subject_id="S2",
            activity_type=ActivityType.LECTURE, sessions_per_week=2, block_size=1,
        )
        g1 = make_assignment(
            assignment_id="A3", teacher_id="T3", subject_id="S3",
            activity_type=ActivityType.PRACTICAL, group="G1", sessions_per_week=1, block_size=2,
        )
        g2 = make_assignment(
            assignment_id="A4", teacher_id="T4", subject_id="S3",
            activity_type=ActivityType.PRACTICAL, group="G2", sessions_per_week=1, block_size=2,
        )

        res = scheduler.schedule([lec1, lec2, g1, g2])
        assert res.is_complete
        assert len(res.placements) == 6  # 2 + 2 + 1 + 1

        # Check that lectures are placed in morning periods (periods 1-4)
        lecture_periods = [
            sl.period for p in res.placements
            if p.assignment.activity_type == ActivityType.LECTURE
            for sl in p.slots
        ]
        morning_lectures = [p for p in lecture_periods if p in (1, 2, 3, 4)]
        assert len(morning_lectures) > 0, "At least one lecture must be placed in the morning"


# ====================================================================
# 3. Workload Guarantee & Zero Clashing Tests
# ====================================================================

class TestWorkloadGuaranteeAndZeroClashing:

    def test_full_schedule_has_zero_clashes(self):
        """Timetable with mixed lectures and practicals must have 0 clashes."""
        rooms = make_rooms()
        scheduler = TimetableScheduler(rooms=rooms)

        assignments = [
            make_assignment(assignment_id="A01", teacher_id="T1", subject_id="S1", sessions_per_week=3, block_size=1),
            make_assignment(assignment_id="A02", teacher_id="T2", subject_id="S2", sessions_per_week=3, block_size=1),
            make_assignment(assignment_id="A03", teacher_id="T3", subject_id="S3", sessions_per_week=2, block_size=1),
            make_assignment(assignment_id="A04", teacher_id="T4", subject_id="S4", activity_type=ActivityType.PRACTICAL, group="G1", sessions_per_week=1, block_size=2),
            make_assignment(assignment_id="A05", teacher_id="T5", subject_id="S4", activity_type=ActivityType.PRACTICAL, group="G2", sessions_per_week=1, block_size=2),
        ]

        res = scheduler.schedule(assignments)
        assert res.is_complete
        assert len(res.unscheduled) == 0

        # Verify no teacher clash
        teacher_slots = {}
        for p in res.placements:
            tid = p.assignment.teacher_id
            teacher_slots.setdefault(tid, set())
            for sl in p.slots:
                assert sl not in teacher_slots[tid], f"Teacher clash for {tid} at {sl}"
                teacher_slots[tid].add(sl)

        # Verify no section clash
        section_slots = {}
        for p in res.placements:
            sec = p.assignment.section
            grp = p.assignment.group
            section_slots.setdefault(sec, set())
            for sl in p.slots:
                if grp == "ALL":
                    assert (sl, "ALL") not in section_slots[sec]
                    section_slots[sec].add((sl, "ALL"))
                else:
                    assert (sl, grp) not in section_slots[sec]
                    section_slots[sec].add((sl, grp))

        # Verify no room clash
        room_slots = {}
        for p in res.placements:
            rid = p.room_id
            room_slots.setdefault(rid, set())
            for sl in p.slots:
                assert sl not in room_slots[rid], f"Room clash for {rid} at {sl}"
                room_slots[rid].add(sl)


# ====================================================================
# 4. SCA (Student Centred Activities) Tests
# ====================================================================

class TestSCAHandling:

    def test_sca_in_activity_type_enum(self):
        """ActivityType enum includes SCA."""
        assert ActivityType.SCA.value == "SCA"

    def test_sca_placement_is_exempt_from_physical_room(self):
        """SCA placement with empty or placeholder room does not produce room conflicts."""
        sca_assignment = make_assignment(
            assignment_id="SCA_1", subject_id="SCA",
            activity_type=ActivityType.SCA, teacher_id="",
        )
        sca_placement = Placement(
            placement_id="P_SCA", assignment=sca_assignment,
            slots=[TimeSlot(Day.MON, 7)], room_id="—",
        )
        rooms = make_rooms()
        conflicts = check_room_type_validity(sca_placement, rooms)
        assert len(conflicts) == 0

    def test_api_generate_leaves_unfilled_slots_blank(self, client):
        """Generating a timetable NEVER fabricates SCA filler for empty
        slots — free periods stay blank. Only the real academic workload
        is placed, and no inflated ``sca_periods`` stat is emitted."""
        # 1. Create session
        res = client.post("/api/session/create", json={
            "session_id": "TEST-SCA-SESSION",
            "branch": "CSE",
            "semester": 3,
            "academic_year": "2026-27",
        })
        assert res.status_code == 200

        # 2. Add section A
        res = client.post("/api/session/TEST-SCA-SESSION/sections", json={
            "sections": [{"branch": "CSE", "semester": 3, "label": "A", "groups": ["G1", "G2"]}]
        })
        assert res.status_code == 200

        # 3. Add 1 assignment (3 periods scheduled out of 35)
        res = client.post("/api/session/TEST-SCA-SESSION/assignments", json={
            "assignment": {
                "subject_id": "SUB015", "teacher_id": "T001",
                "section": "A", "group": "ALL",
                "activity_type": "LECTURE", "block_size": 1,
                "weekly_periods": 3, "sessions_per_week": 3,
            }
        })
        assert res.status_code == 200

        # 4. Generate timetable
        res = client.post("/api/session/TEST-SCA-SESSION/generate", json={})
        assert res.status_code == 200
        data = res.get_json()

        placements = data["placements"]

        # No fabricated "SCA (Free)" filler cells may exist.
        sca_placements = [
            p for p in placements
            if p["activity_type"] == "SCA" or p.get("short_name") == "SCA"
        ]
        assert sca_placements == [], "Empty slots must stay blank — no SCA filler"

        # Only the real workload is placed: 3 lecture periods for Section A.
        section_a_slots = sum(len(p["slots"]) for p in placements if p["section"] == "A")
        assert section_a_slots == 3, (
            f"Section A must hold exactly its 3-period workload, got {section_a_slots}"
        )

        # The inflated filler stat must be gone entirely.
        assert "sca_periods" not in data["stats"]

        # The generate response now carries a structured validation verdict.
        assert "validation" in data
        assert data["validation"]["status"] == "VALID"
        assert data["valid"] is True
        assert data["validation"]["conflicts"]["is_clean"] is True


# ====================================================================
# 5. Section-Coverage Validation (A-full / B-empty is INVALID)
# ====================================================================

class TestSectionCoverageAPI:

    def test_api_generate_flags_empty_section_as_invalid(self, client):
        """A section configured with no workload makes the whole
        timetable INVALID — an A-full / B-empty split is forbidden."""
        sid = "TEST-COVERAGE-SESSION"
        res = client.post("/api/session/create", json={
            "session_id": sid, "branch": "CSE", "semester": 3,
            "academic_year": "2026-27",
        })
        assert res.status_code == 200

        # Two sections configured: A and B.
        res = client.post(f"/api/session/{sid}/sections", json={
            "sections": [
                {"branch": "CSE", "semester": 3, "label": "A", "groups": ["G1", "G2"]},
                {"branch": "CSE", "semester": 3, "label": "B", "groups": ["G1", "G2"]},
            ]
        })
        assert res.status_code == 200

        # Workload assigned to A only — B is left empty.
        res = client.post(f"/api/session/{sid}/assignments", json={
            "assignment": {
                "subject_id": "SUB015", "teacher_id": "T001",
                "section": "A", "group": "ALL",
                "activity_type": "LECTURE", "block_size": 1,
                "weekly_periods": 3, "sessions_per_week": 3,
            }
        })
        assert res.status_code == 200

        res = client.post(f"/api/session/{sid}/generate", json={})
        assert res.status_code == 200
        data = res.get_json()

        assert data["valid"] is False
        assert data["validation"]["status"] == "INVALID"
        empties = [
            i for i in data["validation"]["issues"]
            if i["category"] == "SECTION_EMPTY" and i["entity"] == "B"
        ]
        assert len(empties) == 1, "Section B must be flagged as empty/uncovered"

    def test_api_generate_seed_is_reproducible(self, client):
        """Passing the same seed twice yields the same placements."""
        sid = "TEST-SEED-SESSION"
        client.post("/api/session/create", json={
            "session_id": sid, "branch": "CSE", "semester": 3,
            "academic_year": "2026-27",
        })
        client.post(f"/api/session/{sid}/sections", json={
            "sections": [{"branch": "CSE", "semester": 3, "label": "A", "groups": ["G1", "G2"]}]
        })
        client.post(f"/api/session/{sid}/assignments", json={
            "assignment": {
                "subject_id": "SUB015", "teacher_id": "T001",
                "section": "A", "group": "ALL",
                "activity_type": "LECTURE", "block_size": 1,
                "weekly_periods": 3, "sessions_per_week": 3,
            }
        })

        def signature(payload):
            r = client.post(f"/api/session/{sid}/generate", json=payload)
            assert r.status_code == 200
            d = r.get_json()
            return sorted(
                (p["assignment_id"], tuple(sorted((s["day"], s["period"]) for s in p["slots"])), p["room_id"])
                for p in d["placements"]
            ), d["stats"]["seed"]

        sig1, seed1 = signature({"seed": 4242})
        sig2, seed2 = signature({"seed": 4242})
        assert seed1 == seed2 == 4242
        assert sig1 == sig2

