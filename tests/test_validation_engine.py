"""
Tests for the timetable validation engine (app/engine/validation.py).

Covers the hard-requirement verdicts the spec demands:
    - VALID only when the full workload is placed with zero clashes
    - NO_VALID_TIMETABLE when the workload is incomplete but clash-free
    - INVALID on any hard-constraint clash
    - INVALID on section-coverage gaps (A-full / B-empty is forbidden)
    - G1/G2 practicals validated per group (no double-count)
    - never fabricates filler to hide a gap
"""

import pytest
from typing import List

from app.models.enums import ActivityType, Day
from app.models.assignment import Assignment
from app.models.section import Section
from app.models.slot import TimeSlot
from app.models.placement import Placement
from app.engine.validation import (
    validate_timetable,
    VALID,
    INVALID,
    NO_VALID_TIMETABLE,
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
        weekly_periods=3,
        block_size=1,
        sessions_per_week=3,
    )
    defaults.update(overrides)
    return Assignment(**defaults)


def make_section(label="A", groups=None) -> Section:
    return Section(branch="CSE", semester=3, label=label,
                   groups=groups or ["G1", "G2"])


def placement(pid, assignment, slots, room_id) -> Placement:
    return Placement(placement_id=pid, assignment=assignment,
                     slots=slots, room_id=room_id)


def slots(day, *periods) -> List[TimeSlot]:
    return [TimeSlot(day, p) for p in periods]


# ================================================================
# VALID
# ================================================================

class TestValidStatus:

    def test_complete_workload_zero_clash_is_valid(self):
        """Full workload placed, no clashes → VALID."""
        a = make_assignment(weekly_periods=3, sessions_per_week=3)
        placements = [
            placement("P1", a, slots(Day.MON, 1), "R030"),
            placement("P2", a, slots(Day.TUE, 1), "R030"),
            placement("P3", a, slots(Day.WED, 1), "R030"),
        ]
        report = validate_timetable([a], placements, [make_section("A")])
        assert report.status == VALID
        assert report.is_valid
        assert report.issues == []
        assert "VALID" in report.headline

    def test_g1_g2_no_double_count_is_valid(self):
        """G1=4 and G2=4 practical fully placed on shared slots → VALID.

        Each group is validated against its own 4-period workload; the
        shared academic periods are never counted twice."""
        g1 = make_assignment(
            assignment_id="A_G1", subject_id="SUB009", group="G1",
            activity_type=ActivityType.PRACTICAL,
            weekly_periods=4, block_size=2, sessions_per_week=2,
        )
        g2 = make_assignment(
            assignment_id="A_G2", subject_id="SUB009", group="G2",
            teacher_id="T002",
            activity_type=ActivityType.PRACTICAL,
            weekly_periods=4, block_size=2, sessions_per_week=2,
        )
        placements = [
            placement("P1", g1, slots(Day.MON, 1, 2), "R001"),
            placement("P2", g1, slots(Day.TUE, 1, 2), "R001"),
            placement("P3", g2, slots(Day.MON, 1, 2), "R002"),
            placement("P4", g2, slots(Day.TUE, 1, 2), "R002"),
        ]
        report = validate_timetable([g1, g2], placements, [make_section("A")])
        assert report.status == VALID


# ================================================================
# NO_VALID_TIMETABLE (incomplete but clean)
# ================================================================

class TestNoValidTimetable:

    def test_incomplete_workload_reports_no_valid_timetable(self):
        """Assignment needs 3 periods, only 2 placed → NO_VALID_TIMETABLE."""
        a = make_assignment(weekly_periods=3, sessions_per_week=3)
        placements = [
            placement("P1", a, slots(Day.MON, 1), "R030"),
            placement("P2", a, slots(Day.TUE, 1), "R030"),
        ]
        report = validate_timetable([a], placements, [make_section("A")])
        assert report.status == NO_VALID_TIMETABLE
        assert not report.is_valid
        assert report.headline == "NO VALID TIMETABLE FOUND"
        incomplete = [i for i in report.issues if i.category == "WORKLOAD_INCOMPLETE"]
        assert len(incomplete) == 1
        assert incomplete[0].detail["missing"] == 1
        assert incomplete[0].detail["placed"] == 2
        assert incomplete[0].detail["required"] == 3

    def test_no_filler_is_ever_invented(self):
        """Validation never adds placements to hide a gap — it only reads."""
        a = make_assignment(weekly_periods=3, sessions_per_week=3)
        placements = [placement("P1", a, slots(Day.MON, 1), "R030")]
        before = len(placements)
        validate_timetable([a], placements, [make_section("A")])
        assert len(placements) == before  # untouched


# ================================================================
# INVALID — clashes
# ================================================================

class TestClashInvalid:

    def test_teacher_double_booking_is_invalid(self):
        """Same teacher, two subjects, same slot → INVALID with a CLASH."""
        a1 = make_assignment(assignment_id="A1", subject_id="S1",
                             teacher_id="T001", weekly_periods=1,
                             sessions_per_week=1)
        a2 = make_assignment(assignment_id="A2", subject_id="S2",
                             teacher_id="T001", weekly_periods=1,
                             sessions_per_week=1)
        placements = [
            placement("P1", a1, slots(Day.MON, 1), "R030"),
            placement("P2", a2, slots(Day.MON, 1), "R031"),
        ]
        report = validate_timetable([a1, a2], placements, [make_section("A")])
        assert report.status == INVALID
        clashes = [i for i in report.issues if i.category == "CLASH"]
        assert any("T001" in c.entity for c in clashes)

    def test_room_double_booking_is_invalid(self):
        """Same room, two sections, same slot → INVALID."""
        a1 = make_assignment(assignment_id="A1", section="A", teacher_id="T001",
                             weekly_periods=1, sessions_per_week=1)
        a2 = make_assignment(assignment_id="A2", section="B", teacher_id="T002",
                             weekly_periods=1, sessions_per_week=1)
        placements = [
            placement("P1", a1, slots(Day.MON, 1), "R030"),
            placement("P2", a2, slots(Day.MON, 1), "R030"),
        ]
        report = validate_timetable(
            [a1, a2], placements, [make_section("A"), make_section("B")],
        )
        assert report.status == INVALID
        assert any(i.category == "CLASH" for i in report.issues)


# ================================================================
# INVALID — section coverage
# ================================================================

class TestSectionCoverage:

    def test_configured_section_with_no_assignments_is_invalid(self):
        """A-full / B-configured-but-empty → INVALID (SECTION_EMPTY)."""
        a = make_assignment(section="A", weekly_periods=3, sessions_per_week=3)
        placements = [
            placement("P1", a, slots(Day.MON, 1), "R030"),
            placement("P2", a, slots(Day.TUE, 1), "R030"),
            placement("P3", a, slots(Day.WED, 1), "R030"),
        ]
        sections = [make_section("A"), make_section("B")]
        report = validate_timetable([a], placements, sections)
        assert report.status == INVALID
        empties = [i for i in report.issues if i.category == "SECTION_EMPTY"]
        assert len(empties) == 1
        assert empties[0].entity == "B"

    def test_section_with_assignments_but_no_placements_is_invalid(self):
        """Section B has workload requested but none placed → INVALID."""
        a_a = make_assignment(assignment_id="AA", section="A", teacher_id="T001",
                              weekly_periods=1, sessions_per_week=1)
        a_b = make_assignment(assignment_id="AB", section="B", teacher_id="T002",
                              weekly_periods=2, sessions_per_week=2)
        placements = [placement("P1", a_a, slots(Day.MON, 1), "R030")]
        sections = [make_section("A"), make_section("B")]
        report = validate_timetable([a_a, a_b], placements, sections)
        assert report.status == INVALID
        # B is empty AND its workload is incomplete; both are reported.
        assert any(i.category == "SECTION_EMPTY" and i.entity == "B"
                   for i in report.issues)

    def test_clash_takes_precedence_over_incomplete(self):
        """A clash makes the grid INVALID even if workload is also short."""
        a1 = make_assignment(assignment_id="A1", teacher_id="T001",
                             weekly_periods=2, sessions_per_week=2)
        a2 = make_assignment(assignment_id="A2", teacher_id="T001", subject_id="S2",
                             weekly_periods=1, sessions_per_week=1)
        placements = [
            placement("P1", a1, slots(Day.MON, 1), "R030"),  # A1 short (1/2)
            placement("P2", a2, slots(Day.MON, 1), "R031"),  # clashes w/ P1 teacher
        ]
        report = validate_timetable([a1, a2], placements, [make_section("A")])
        assert report.status == INVALID  # not NO_VALID_TIMETABLE


# ================================================================
# Serialization
# ================================================================

class TestReportSerialization:

    def test_to_dict_shape(self):
        a = make_assignment(weekly_periods=1, sessions_per_week=1)
        placements = [placement("P1", a, slots(Day.MON, 1), "R030")]
        d = validate_timetable([a], placements, [make_section("A")]).to_dict()
        assert d["status"] == VALID
        assert d["is_valid"] is True
        assert d["issue_count"] == 0
        assert "counts" in d and "issues" in d and "conflicts" in d
        assert d["conflicts"]["is_clean"] is True

    def test_no_sections_only_checks_workload(self):
        """With no configured sections, only assignment workload matters."""
        a = make_assignment(weekly_periods=2, sessions_per_week=2)
        placements = [
            placement("P1", a, slots(Day.MON, 1), "R030"),
            placement("P2", a, slots(Day.TUE, 1), "R030"),
        ]
        report = validate_timetable([a], placements, sections=[])
        assert report.status == VALID
