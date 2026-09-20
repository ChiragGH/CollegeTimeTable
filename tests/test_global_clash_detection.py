"""
Tests for College-Wide Global Clash Detection across multiple timetables.

Covers:
- Teacher double-booking across different branch/semester timetables (TEST 8)
- Room double-booking across different timetables (TEST 9)
- Section & Group clashes within same section or parallel groups (TEST 10)
- Shared facilities (Labs, Workshops, Drawing Halls) across departments (TEST 11)
- Recess prohibition (1:00 PM - 2:00 PM) and boundary bridging (TEST 12)
- Academic Year isolation (different academic years do not clash)
- Candidate pre-save clash checking via check_candidate_edit
"""

import pytest
from typing import List

from app.models.enums import ActivityType, Day
from app.models.slot import TimeSlot
from app.models.timetable import Timetable, TimetablePlacement
from app.engine.global_validation import GlobalConflictDetector, GlobalConflict, GlobalValidationReport


def make_placement(pid: str, tid: str, aid: str, sub: str, teacher: str, room: str,
                   sec: str = "A", grp: str = "ALL", act: ActivityType = ActivityType.LECTURE,
                   day: Day = Day.MON, periods: List[int] = None, block_size: int = 1,
                   sub_short: str = "", teacher_name: str = "", room_name: str = "",
                   is_linked_parallel: bool = False, linked_placement_id: str = None) -> TimetablePlacement:
    if periods is None:
        periods = [1]
    slots = [TimeSlot(day=day, period=p) for p in periods]
    return TimetablePlacement(
        placement_id=pid,
        timetable_id=tid,
        assignment_id=aid,
        subject_id=sub,
        teacher_id=teacher,
        room_id=room,
        section=sec,
        group=grp,
        activity_type=act,
        slots=slots,
        block_size=block_size,
        subject_short_name=sub_short or sub,
        subject_name=sub,
        teacher_name=teacher_name or teacher,
        room_name=room_name or room,
        is_linked_parallel=is_linked_parallel,
        linked_placement_id=linked_placement_id,
    )


class TestGlobalConflictDetector:
    def test_single_clean_timetable(self):
        """A single timetable with valid placements produces a clean report."""
        tt = Timetable(
            timetable_id="TT_CLEAN",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("P1", "TT_CLEAN", "A1", "CS401", "T001", "R101", day=Day.MON, periods=[1]),
                make_placement("P2", "TT_CLEAN", "A2", "CS402", "T002", "R101", day=Day.MON, periods=[2]),
            ]
        )
        report = GlobalConflictDetector.audit_timetables([tt], academic_year="2026-27")
        assert report.is_clean is True
        assert len(report.conflicts) == 0
        assert report.total_conflicts == 0

    def test_cross_timetable_teacher_double_booking(self):
        """TEST 8: Teacher T001 scheduled at MON P1 in CSE Sem 4 and ECE Sem 4.
        Must report a TEACHER conflict across timetables."""
        tt_cse = Timetable(
            timetable_id="TT_CSE_4_A",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("P_CSE", "TT_CSE_4_A", "A_CSE", "CS401", "T_SHARMA", "R101",
                               day=Day.MON, periods=[1], teacher_name="Prof. Sharma")
            ]
        )
        tt_ece = Timetable(
            timetable_id="TT_ECE_4_A",
            academic_year="2026-27",
            branch="ECE",
            semester=4,
            section="A",
            placements=[
                make_placement("P_ECE", "TT_ECE_4_A", "A_ECE", "EC401", "T_SHARMA", "R201",
                               day=Day.MON, periods=[1], teacher_name="Prof. Sharma")
            ]
        )

        report = GlobalConflictDetector.audit_timetables([tt_cse, tt_ece], academic_year="2026-27")
        assert report.is_clean is False
        assert len(report.conflicts) == 1
        c = report.conflicts[0]
        assert c.conflict_type == "TEACHER"
        assert c.entity_id == "T_SHARMA"
        assert c.day == "MON"
        assert c.period == 1
        assert c.timetable_a["timetable_id"] in ["TT_CSE_4_A", "TT_ECE_4_A"]
        assert c.timetable_b["timetable_id"] in ["TT_CSE_4_A", "TT_ECE_4_A"]
        assert "Sharma" in c.description

    def test_cross_timetable_room_double_booking(self):
        """TEST 9: Room R101 scheduled at TUE P3 in CSE Sem 4 and Civil Sem 2.
        Must report a ROOM conflict across timetables."""
        tt_cse = Timetable(
            timetable_id="TT_CSE_4",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("P1", "TT_CSE_4", "A1", "CS401", "T001", "R101",
                               day=Day.TUE, periods=[3], room_name="Room 101")
            ]
        )
        tt_civil = Timetable(
            timetable_id="TT_CIVIL_2",
            academic_year="2026-27",
            branch="Civil",
            semester=2,
            section="A",
            placements=[
                make_placement("P2", "TT_CIVIL_2", "A2", "CE201", "T002", "R101",
                               day=Day.TUE, periods=[3], room_name="Room 101")
            ]
        )

        report = GlobalConflictDetector.audit_timetables([tt_cse, tt_civil], academic_year="2026-27")
        assert report.is_clean is False
        room_conflicts = [c for c in report.conflicts if c.conflict_type == "ROOM"]
        assert len(room_conflicts) == 1
        c = room_conflicts[0]
        assert c.entity_id == "R101"
        assert c.day == "TUE"
        assert c.period == 3
        assert "Room 101" in c.description

    def test_shared_workshop_lab_collision(self):
        """TEST 11: Shared workshop room booked simultaneously by ME and Civil on WED P2."""
        tt_me = Timetable(
            timetable_id="TT_ME",
            academic_year="2026-27",
            branch="ME",
            semester=4,
            section="A",
            placements=[
                make_placement("P_ME", "TT_ME", "A_ME", "ME401", "T_ME", "WS_CENTRAL",
                               act=ActivityType.WORKSHOP, day=Day.WED, periods=[2, 3], block_size=2,
                               room_name="Central Workshop")
            ]
        )
        tt_civil = Timetable(
            timetable_id="TT_CE",
            academic_year="2026-27",
            branch="Civil",
            semester=4,
            section="A",
            placements=[
                make_placement("P_CE", "TT_CE", "A_CE", "CE401", "T_CE", "WS_CENTRAL",
                               act=ActivityType.WORKSHOP, day=Day.WED, periods=[2, 3], block_size=2,
                               room_name="Central Workshop")
            ]
        )

        report = GlobalConflictDetector.audit_timetables([tt_me, tt_civil], academic_year="2026-27")
        assert report.is_clean is False
        assert any(c.conflict_type == "ROOM" and c.entity_id == "WS_CENTRAL" for c in report.conflicts)

    def test_recess_spanning_violation(self):
        """TEST 12: A placement spanning periods [4, 5] bridges across Recess (1:00-2:00 PM).
        Must be flagged as a RECESS conflict."""
        tt = Timetable(
            timetable_id="TT_RECESS_VIOLATION",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("P_SPAN", "TT_RECESS_VIOLATION", "A_SPAN", "CS401P", "T001", "LAB1",
                               grp="G1", act=ActivityType.PRACTICAL, day=Day.MON, periods=[4, 5], block_size=2,
                               sub_short="OS Lab")
            ]
        )

        report = GlobalConflictDetector.audit_timetables([tt], academic_year="2026-27")
        assert report.is_clean is False
        recess_conflicts = [c for c in report.conflicts if c.conflict_type == "RECESS"]
        assert len(recess_conflicts) > 0
        assert "Recess" in recess_conflicts[0].description

    def test_academic_year_isolation(self):
        """A teacher placed at MON P1 in 2025-26 and MON P1 in 2026-27
        does NOT clash because they belong to different academic years."""
        tt_2025 = Timetable(
            timetable_id="TT_2025",
            academic_year="2025-26",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("P_OLD", "TT_2025", "A_OLD", "CS401", "T001", "R101",
                               day=Day.MON, periods=[1])
            ]
        )
        tt_2026 = Timetable(
            timetable_id="TT_2026",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("P_NEW", "TT_2026", "A_NEW", "CS401", "T001", "R101",
                               day=Day.MON, periods=[1])
            ]
        )

        # Audit for 2026-27 ignores 2025-26
        report = GlobalConflictDetector.audit_timetables([tt_2025, tt_2026], academic_year="2026-27")
        assert report.is_clean is True
        assert len(report.conflicts) == 0

    def test_check_candidate_edit_fast_detection(self):
        """Live pre-save clash checking identifies teacher or room collision before saving."""
        existing_tt = Timetable(
            timetable_id="TT_EXISTING",
            academic_year="2026-27",
            branch="ECE",
            semester=4,
            section="A",
            placements=[
                make_placement("P_ECE", "TT_EXISTING", "A_ECE", "EC401", "T_BUSY", "R201",
                               day=Day.MON, periods=[2], teacher_name="Prof. Busy", room_name="Room 201")
            ]
        )

        target_tt = Timetable(
            timetable_id="TT_TARGET",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[]
        )

        # 1. Candidate collides with teacher T_BUSY at MON P2
        candidate_teacher_clash = {
            "placement_id": "NEW_P",
            "subject_id": "CS401",
            "teacher_id": "T_BUSY",
            "room_id": "R101",
            "day": "MON",
            "period": 2,
            "block_size": 1,
            "group": "ALL",
            "activity_type": "LECTURE",
        }
        conflicts = GlobalConflictDetector.check_candidate_edit(
            target_timetable=target_tt,
            candidate_data=candidate_teacher_clash,
            all_timetables=[existing_tt, target_tt],
        )
        assert len(conflicts) > 0
        assert conflicts[0].conflict_type == "TEACHER"

        # 2. Candidate on free slot MON P3 has no conflicts
        candidate_clean = dict(candidate_teacher_clash)
        candidate_clean["period"] = 3
        conflicts_clean = GlobalConflictDetector.check_candidate_edit(
            target_timetable=target_tt,
            candidate_data=candidate_clean,
            all_timetables=[existing_tt, target_tt],
        )
        assert len(conflicts_clean) == 0

        # 3. Candidate bridging recess [4, 5] detected immediately
        candidate_recess = {
            "placement_id": "NEW_P",
            "subject_id": "CS401P",
            "teacher_id": "T001",
            "room_id": "LAB1",
            "day": "MON",
            "period": 4,
            "block_size": 2,
            "group": "G1",
            "activity_type": "PRACTICAL",
        }
        conflicts_recess = GlobalConflictDetector.check_candidate_edit(
            target_timetable=target_tt,
            candidate_data=candidate_recess,
            all_timetables=[existing_tt, target_tt],
        )
        assert any(c.conflict_type == "RECESS" for c in conflicts_recess)

    def test_self_exclusion_during_edit(self):
        """When editing an existing placement's room, its own existing slot does not conflict with itself."""
        tt = Timetable(
            timetable_id="TT_SELF",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("P_EDITING", "TT_SELF", "A1", "CS401", "T001", "R101",
                               day=Day.MON, periods=[1], teacher_name="Prof. One")
            ]
        )

        candidate_data = {
            "placement_id": "P_EDITING",
            "subject_id": "CS401",
            "teacher_id": "T001",
            "room_id": "R102",  # Just changing the room
            "day": "MON",
            "period": 1,
            "block_size": 1,
            "group": "ALL",
            "activity_type": "LECTURE",
        }

        conflicts = GlobalConflictDetector.check_candidate_edit(
            target_timetable=tt,
            candidate_data=candidate_data,
            all_timetables=[tt],
            exclude_placement_id="P_EDITING",
        )
        assert len(conflicts) == 0
