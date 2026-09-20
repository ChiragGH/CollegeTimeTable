"""
Unit tests for the setup module: session manager, assignment manager,
and end-to-end setup workflow.

Tests cover:
- Session creation, save, load, list, delete
- Assignment creation with auto-computed fields
- Assignment validation rules V-A1 through V-A6
- Workload-driven auto-assignment
- Round-trip persistence (JSON + Excel)
"""

import pytest
import shutil
from pathlib import Path

from app.models.teacher import Teacher
from app.models.room import Room
from app.models.subject import Subject
from app.models.workload import Workload
from app.models.section import Section
from app.models.assignment import Assignment
from app.models.session import TimetableSetup
from app.models.enums import ActivityType, RoomType
from app.data.validators import Severity
from app.setup.filters import SetupFilters
from app.setup.session_manager import SessionManager, SessionError
from app.setup.assignment_manager import AssignmentManager


# ---- Shared fixtures ----

@pytest.fixture
def teachers():
    return [
        Teacher(teacher_id="T001", teacher_name="RJS", department="CSE", active=True),
        Teacher(teacher_id="T002", teacher_name="ABS", department="CSE", active=True),
        Teacher(teacher_id="T003", teacher_name="INACT", department="CSE", active=False),
    ]


@pytest.fixture
def rooms():
    return [
        Room(room_id="R001", room_name="CC1", room_type=RoomType.LAB, branch="CSE", is_shared=False, active=True),
        Room(room_id="R030", room_name="L1", room_type=RoomType.LECTURE, branch=None, is_shared=True, active=True),
        Room(room_id="R040", room_name="DH1", room_type=RoomType.DRAWING_HALL, branch=None, is_shared=True, active=True),
        Room(room_id="R099", room_name="OLD", room_type=RoomType.LECTURE, branch=None, is_shared=True, active=False),
    ]


@pytest.fixture
def subjects():
    return [
        Subject(subject_id="SUB001", subject_code="1.1", subject_name="English", branch="CSE", semester=1, active=True),
        Subject(subject_id="SUB002", subject_code="1.2", subject_name="Math", branch="CSE", semester=1, active=True),
        Subject(subject_id="SUB010", subject_code="3.1", subject_name="DSA", branch="CSE", semester=3, active=True),
    ]


@pytest.fixture
def workloads():
    return [
        Workload(workload_id="W001", subject_id="SUB001", branch="CSE", semester=1, lecture_periods_per_week=2, practical_periods_per_week=2, total_periods_per_week=4),
        Workload(workload_id="W002", subject_id="SUB002", branch="CSE", semester=1, lecture_periods_per_week=4, practical_periods_per_week=0, total_periods_per_week=4),
        Workload(workload_id="W010", subject_id="SUB010", branch="CSE", semester=3, lecture_periods_per_week=3, practical_periods_per_week=2, total_periods_per_week=5),
    ]


@pytest.fixture
def filters(teachers, rooms, subjects, workloads):
    return SetupFilters(teachers, rooms, subjects, workloads)


@pytest.fixture
def tmp_sessions_dir(tmp_path):
    """Use a temp directory for session persistence tests."""
    return str(tmp_path / "sessions")


# ================================================================
# Section Model Tests
# ================================================================

class TestSectionModel:
    def test_section_id(self):
        s = Section(branch="CSE", semester=3, label="A")
        assert s.section_id == "CSE-3-A"

    def test_section_default_groups(self):
        s = Section(branch="CSE", semester=1, label="B")
        assert s.groups == ["G1", "G2"]

    def test_section_custom_groups(self):
        s = Section(branch="ME", semester=2, label="A", groups=["G1", "G2", "G3"])
        assert len(s.groups) == 3

    def test_section_str(self):
        s = Section(branch="ECE", semester=5, label="A")
        assert str(s) == "ECE-5-A"


# ================================================================
# Session Manager Tests
# ================================================================

class TestSessionManager:
    def test_create_session(self, tmp_sessions_dir):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        setup = mgr.create_session("2026-27", "CSE", 3)
        assert setup.session_id == "2026-27_CSE_Sem3"
        assert setup.academic_year == "2026-27"
        assert setup.branch == "CSE"
        assert setup.semester == 3
        assert len(setup.sections) == 1
        assert setup.sections[0].label == "A"
        assert setup.created_at != ""

    def test_create_session_custom_id(self, tmp_sessions_dir):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        setup = mgr.create_session("2026-27", "CSE", 3, session_id="custom-id")
        assert setup.session_id == "custom-id"

    def test_create_session_with_sections(self, tmp_sessions_dir):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        sections = [
            Section(branch="CSE", semester=3, label="A"),
            Section(branch="CSE", semester=3, label="B"),
        ]
        setup = mgr.create_session("2026-27", "CSE", 3, sections=sections)
        assert len(setup.sections) == 2

    def test_duplicate_session_fails(self, tmp_sessions_dir):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        setup = mgr.create_session("2026-27", "CSE", 3)
        mgr.save_session(setup)
        with pytest.raises(SessionError, match="already exists"):
            mgr.create_session("2026-27", "CSE", 3)

    def test_add_section(self, tmp_sessions_dir):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        setup = mgr.create_session("2026-27", "CSE", 3)
        sec = mgr.add_section(setup, "B")
        assert sec.label == "B"
        assert sec.branch == "CSE"
        assert len(setup.sections) == 2

    def test_add_duplicate_section_fails(self, tmp_sessions_dir):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        setup = mgr.create_session("2026-27", "CSE", 3)
        with pytest.raises(SessionError, match="already exists"):
            mgr.add_section(setup, "A")  # "A" is the default

    def test_save_and_load(self, tmp_sessions_dir, filters):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        setup = mgr.create_session("2026-27", "CSE", 1)
        mgr.add_section(setup, "B", groups=["G1", "G2", "G3"])

        # Add an assignment
        am = AssignmentManager(filters)
        am.create_assignment(
            setup=setup,
            teacher_id="T001",
            subject_id="SUB001",
            section="A",
            group="ALL",
            activity_type=ActivityType.LECTURE,
            weekly_periods=2,
        )

        # Save
        mgr.save_session(setup)

        # Load
        loaded = mgr.load_session(setup.session_id)
        assert loaded.session_id == setup.session_id
        assert loaded.academic_year == "2026-27"
        assert loaded.branch == "CSE"
        assert loaded.semester == 1
        assert len(loaded.sections) == 2
        assert loaded.sections[1].label == "B"
        assert loaded.sections[1].groups == ["G1", "G2", "G3"]
        assert len(loaded.assignments) == 1
        assert loaded.assignments[0].teacher_id == "T001"
        assert loaded.assignments[0].activity_type == ActivityType.LECTURE

    def test_load_nonexistent_session(self, tmp_sessions_dir):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        with pytest.raises(SessionError, match="not found"):
            mgr.load_session("nonexistent")

    def test_list_sessions_empty(self, tmp_sessions_dir):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        assert mgr.list_sessions() == []

    def test_list_sessions(self, tmp_sessions_dir):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        s1 = mgr.create_session("2026-27", "CSE", 1)
        mgr.save_session(s1)
        s2 = mgr.create_session("2026-27", "CSE", 3)
        mgr.save_session(s2)
        sessions = mgr.list_sessions()
        assert len(sessions) == 2
        assert "2026-27_CSE_Sem1" in sessions
        assert "2026-27_CSE_Sem3" in sessions

    def test_delete_session(self, tmp_sessions_dir):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        setup = mgr.create_session("2026-27", "CSE", 1)
        mgr.save_session(setup)
        assert mgr.session_exists(setup.session_id)
        mgr.delete_session(setup.session_id)
        assert not mgr.session_exists(setup.session_id)

    def test_delete_nonexistent(self, tmp_sessions_dir):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        with pytest.raises(SessionError, match="not found"):
            mgr.delete_session("ghost")

    def test_save_creates_setup_xlsx(self, tmp_sessions_dir, filters):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        setup = mgr.create_session("2026-27", "CSE", 1)

        am = AssignmentManager(filters)
        am.create_assignment(
            setup=setup, teacher_id="T001", subject_id="SUB001",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
            weekly_periods=2,
        )

        path = mgr.save_session(setup)
        xlsx_path = path / "Setup.xlsx"
        assert xlsx_path.exists()

    def test_session_exists(self, tmp_sessions_dir):
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        assert not mgr.session_exists("nope")
        setup = mgr.create_session("2026-27", "ECE", 1)
        mgr.save_session(setup)
        assert mgr.session_exists(setup.session_id)


# ================================================================
# Assignment Manager Tests
# ================================================================

class TestAssignmentManager:
    def test_create_lecture_assignment(self, filters):
        am = AssignmentManager(filters)
        setup = TimetableSetup(
            session_id="test", academic_year="2026-27",
            branch="CSE", semester=1,
            sections=[Section(branch="CSE", semester=1, label="A")],
        )

        a = am.create_assignment(
            setup=setup, teacher_id="T001", subject_id="SUB001",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
            weekly_periods=2,
        )

        assert a.assignment_id == "A001"
        assert a.teacher_id == "T001"
        assert a.block_size == 1  # default for LECTURE
        assert a.sessions_per_week == 2
        assert a.room_type == RoomType.LECTURE  # auto-inferred
        assert len(setup.assignments) == 1

    def test_create_practical_assignment(self, filters):
        am = AssignmentManager(filters)
        setup = TimetableSetup(
            session_id="test", academic_year="2026-27",
            branch="CSE", semester=1,
            sections=[Section(branch="CSE", semester=1, label="A")],
        )

        a = am.create_assignment(
            setup=setup, teacher_id="T001", subject_id="SUB001",
            section="A", group="G1", activity_type=ActivityType.PRACTICAL,
            weekly_periods=2,
        )

        assert a.block_size == 2  # default for PRACTICAL
        assert a.sessions_per_week == 1  # 2 / 2
        assert a.room_type == RoomType.LAB

    def test_create_workshop_assignment(self, filters):
        am = AssignmentManager(filters)
        setup = TimetableSetup(
            session_id="test", academic_year="2026-27",
            branch="CSE", semester=1,
            sections=[Section(branch="CSE", semester=1, label="A")],
        )

        a = am.create_assignment(
            setup=setup, teacher_id="T001", subject_id="SUB001",
            section="A", group="G1", activity_type=ActivityType.WORKSHOP,
            weekly_periods=3,
        )

        assert a.block_size == 3  # default for WORKSHOP
        assert a.sessions_per_week == 1
        assert a.room_type == RoomType.WORKSHOP

    def test_custom_block_size(self, filters):
        am = AssignmentManager(filters)
        setup = TimetableSetup(
            session_id="test", academic_year="2026-27",
            branch="CSE", semester=1,
            sections=[Section(branch="CSE", semester=1, label="A")],
        )

        a = am.create_assignment(
            setup=setup, teacher_id="T001", subject_id="SUB001",
            section="A", group="G1", activity_type=ActivityType.PRACTICAL,
            weekly_periods=6, block_size=3,
        )

        assert a.block_size == 3
        assert a.sessions_per_week == 2  # 6 / 3

    def test_assignment_ids_increment(self, filters):
        am = AssignmentManager(filters)
        setup = TimetableSetup(
            session_id="test", academic_year="2026-27",
            branch="CSE", semester=1,
            sections=[Section(branch="CSE", semester=1, label="A")],
        )

        a1 = am.create_assignment(
            setup=setup, teacher_id="T001", subject_id="SUB001",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
            weekly_periods=2,
        )
        a2 = am.create_assignment(
            setup=setup, teacher_id="T002", subject_id="SUB002",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
            weekly_periods=4,
        )

        assert a1.assignment_id == "A001"
        assert a2.assignment_id == "A002"

    def test_remove_assignment(self, filters):
        am = AssignmentManager(filters)
        setup = TimetableSetup(
            session_id="test", academic_year="2026-27",
            branch="CSE", semester=1,
            sections=[Section(branch="CSE", semester=1, label="A")],
        )

        a = am.create_assignment(
            setup=setup, teacher_id="T001", subject_id="SUB001",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
            weekly_periods=2,
        )

        assert len(setup.assignments) == 1
        assert am.remove_assignment(setup, a.assignment_id)
        assert len(setup.assignments) == 0

    def test_remove_nonexistent_returns_false(self, filters):
        am = AssignmentManager(filters)
        setup = TimetableSetup(
            session_id="test", academic_year="2026-27",
            branch="CSE", semester=1,
            sections=[Section(branch="CSE", semester=1, label="A")],
        )
        assert not am.remove_assignment(setup, "NONEXISTENT")

    def test_preferred_room_stored(self, filters):
        am = AssignmentManager(filters)
        setup = TimetableSetup(
            session_id="test", academic_year="2026-27",
            branch="CSE", semester=1,
            sections=[Section(branch="CSE", semester=1, label="A")],
        )

        a = am.create_assignment(
            setup=setup, teacher_id="T001", subject_id="SUB001",
            section="A", group="G1", activity_type=ActivityType.PRACTICAL,
            weekly_periods=2, room_id="R001", room_type=RoomType.LAB,
        )

        assert a.room_id == "R001"
        assert a.room_type == RoomType.LAB


# ================================================================
# Auto-assignment from Workload
# ================================================================

class TestAutoAssignment:
    def test_create_from_workload_lecture_and_practical(self, filters):
        am = AssignmentManager(filters)
        setup = TimetableSetup(
            session_id="test", academic_year="2026-27",
            branch="CSE", semester=1,
            sections=[Section(branch="CSE", semester=1, label="A")],
        )

        created = am.create_assignments_from_workload(
            setup=setup, subject_id="SUB001", section="A",
            teacher_id_lecture="T001", teacher_id_practical="T002",
            practical_group="G1",
        )

        assert len(created) == 2
        lec = [a for a in created if a.activity_type == ActivityType.LECTURE][0]
        prac = [a for a in created if a.activity_type == ActivityType.PRACTICAL][0]
        assert lec.weekly_periods == 2
        assert lec.group == "ALL"
        assert prac.weekly_periods == 2
        assert prac.group == "G1"

    def test_create_from_workload_theory_only(self, filters):
        am = AssignmentManager(filters)
        setup = TimetableSetup(
            session_id="test", academic_year="2026-27",
            branch="CSE", semester=1,
            sections=[Section(branch="CSE", semester=1, label="A")],
        )

        # SUB002 has L=4, P=0
        created = am.create_assignments_from_workload(
            setup=setup, subject_id="SUB002", section="A",
            teacher_id_lecture="T001",
        )

        assert len(created) == 1
        assert created[0].activity_type == ActivityType.LECTURE
        assert created[0].weekly_periods == 4

    def test_create_from_workload_missing_subject(self, filters):
        am = AssignmentManager(filters)
        setup = TimetableSetup(
            session_id="test", academic_year="2026-27",
            branch="CSE", semester=1,
            sections=[Section(branch="CSE", semester=1, label="A")],
        )

        created = am.create_assignments_from_workload(
            setup=setup, subject_id="SUB_GHOST", section="A",
            teacher_id_lecture="T001",
        )

        assert created == []


# ================================================================
# Assignment Validation Tests (V-A1 through V-A6)
# ================================================================

class TestAssignmentValidation:
    def _make_setup(self, assignments=None):
        return TimetableSetup(
            session_id="test", academic_year="2026-27",
            branch="CSE", semester=1,
            sections=[Section(branch="CSE", semester=1, label="A")],
            assignments=assignments or [],
        )

    def _make_assignment(self, **overrides):
        defaults = {
            "assignment_id": "A001",
            "session_id": "test",
            "teacher_id": "T001",
            "subject_id": "SUB001",
            "branch": "CSE",
            "semester": 1,
            "section": "A",
            "group": "ALL",
            "activity_type": ActivityType.LECTURE,
            "weekly_periods": 2,
            "block_size": 1,
            "sessions_per_week": 2,
        }
        defaults.update(overrides)
        return Assignment(**defaults)

    def test_valid_assignment(self, filters):
        am = AssignmentManager(filters)
        a = self._make_assignment()
        setup = self._make_setup([a])
        result = am.validate_assignments(setup)
        errors = [e for e in result.errors if e.severity == Severity.ERROR]
        assert len(errors) == 0

    def test_va1_teacher_not_found(self, filters):
        """V-A1: teacher_id not in Teachers.xlsx."""
        am = AssignmentManager(filters)
        a = self._make_assignment(teacher_id="T999")
        setup = self._make_setup([a])
        result = am.validate_assignments(setup)
        rule_ids = [e.rule_id for e in result.errors if e.severity == Severity.ERROR]
        assert "V-A1" in rule_ids

    def test_va1_teacher_inactive(self, filters):
        """V-A1: teacher exists but is inactive."""
        am = AssignmentManager(filters)
        a = self._make_assignment(teacher_id="T003")
        setup = self._make_setup([a])
        result = am.validate_assignments(setup)
        rule_ids = [e.rule_id for e in result.errors if e.severity == Severity.ERROR]
        assert "V-A1" in rule_ids

    def test_va2_subject_not_found(self, filters):
        """V-A2: subject_id not in Subjects.xlsx."""
        am = AssignmentManager(filters)
        a = self._make_assignment(subject_id="SUB_GHOST")
        setup = self._make_setup([a])
        result = am.validate_assignments(setup)
        rule_ids = [e.rule_id for e in result.errors if e.severity == Severity.ERROR]
        assert "V-A2" in rule_ids

    def test_va3_room_not_found(self, filters):
        """V-A3: room_id not in Rooms.xlsx."""
        am = AssignmentManager(filters)
        a = self._make_assignment(room_id="R999")
        setup = self._make_setup([a])
        result = am.validate_assignments(setup)
        rule_ids = [e.rule_id for e in result.errors if e.severity == Severity.ERROR]
        assert "V-A3" in rule_ids

    def test_va3_room_inactive(self, filters):
        """V-A3: room exists but is not active."""
        am = AssignmentManager(filters)
        a = self._make_assignment(room_id="R099")
        setup = self._make_setup([a])
        result = am.validate_assignments(setup)
        rule_ids = [e.rule_id for e in result.errors if e.severity == Severity.ERROR]
        assert "V-A3" in rule_ids

    def test_va3_room_type_mismatch(self, filters):
        """V-A3: room type does not match activity type."""
        am = AssignmentManager(filters)
        # LAB room for a LECTURE activity
        a = self._make_assignment(room_id="R001", activity_type=ActivityType.LECTURE)
        setup = self._make_setup([a])
        result = am.validate_assignments(setup)
        rule_ids = [e.rule_id for e in result.errors if e.severity == Severity.ERROR]
        assert "V-A3" in rule_ids

    def test_va3_room_valid(self, filters):
        """V-A3: correct room type --> no error."""
        am = AssignmentManager(filters)
        a = self._make_assignment(room_id="R030")  # LECTURE room for LECTURE
        setup = self._make_setup([a])
        result = am.validate_assignments(setup)
        va3_errors = [e for e in result.errors if e.rule_id == "V-A3"]
        assert len(va3_errors) == 0

    def test_va5_duplicate_assignment(self, filters):
        """V-A5: duplicate subject-section-group."""
        am = AssignmentManager(filters)
        a1 = self._make_assignment(assignment_id="A001")
        a2 = self._make_assignment(assignment_id="A002")
        setup = self._make_setup([a1, a2])
        result = am.validate_assignments(setup)
        rule_ids = [e.rule_id for e in result.errors if e.severity == Severity.ERROR]
        assert "V-A5" in rule_ids

    def test_va6_lecture_wrong_group(self, filters):
        """V-A6: lecture with group != ALL."""
        am = AssignmentManager(filters)
        a = self._make_assignment(group="G1")
        setup = self._make_setup([a])
        result = am.validate_assignments(setup)
        rule_ids = [e.rule_id for e in result.errors if e.severity == Severity.WARNING]
        assert "V-A6" in rule_ids

    def test_invalid_group(self, filters):
        """Invalid group value."""
        am = AssignmentManager(filters)
        a = self._make_assignment(group="INVALID")
        setup = self._make_setup([a])
        result = am.validate_assignments(setup)
        rule_ids = [e.rule_id for e in result.errors if e.severity == Severity.ERROR]
        assert "V-A0" in rule_ids

    def test_nonpositive_weekly_periods(self, filters):
        """weekly_periods must be > 0."""
        am = AssignmentManager(filters)
        a = self._make_assignment(weekly_periods=0)
        setup = self._make_setup([a])
        result = am.validate_assignments(setup)
        rule_ids = [e.rule_id for e in result.errors if e.severity == Severity.ERROR]
        assert "V-A0" in rule_ids

    def test_section_not_in_setup(self, filters):
        """Section label must match one in setup.sections."""
        am = AssignmentManager(filters)
        a = self._make_assignment(section="Z")
        setup = self._make_setup([a])
        result = am.validate_assignments(setup)
        rule_ids = [e.rule_id for e in result.errors if e.severity == Severity.ERROR]
        assert "V-A0" in rule_ids


# ================================================================
# Workload Summary
# ================================================================

class TestWorkloadSummary:
    def test_summary_shows_required_and_assigned(self, filters):
        am = AssignmentManager(filters)
        setup = TimetableSetup(
            session_id="test", academic_year="2026-27",
            branch="CSE", semester=1,
            sections=[Section(branch="CSE", semester=1, label="A")],
        )

        am.create_assignment(
            setup=setup, teacher_id="T001", subject_id="SUB001",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
            weekly_periods=2,
        )

        summary = am.get_workload_summary(setup)
        assert "SUB001" in summary
        assert summary["SUB001"]["lecture_required"] == 2
        assert summary["SUB001"]["lecture_assigned"] == 2
        assert summary["SUB001"]["practical_required"] == 2
        assert summary["SUB001"]["practical_assigned"] == 0  # not yet assigned


# ================================================================
# End-to-End Workflow
# ================================================================

class TestEndToEndSetup:
    def test_full_setup_workflow(self, filters, tmp_sessions_dir):
        """Complete workflow: create session --> add sections -->
        auto-load subjects --> create assignments --> validate --> save --> load."""

        # 1. Create session
        mgr = SessionManager(sessions_dir=tmp_sessions_dir)
        setup = mgr.create_session("2026-27", "CSE", 1)
        assert setup.session_id == "2026-27_CSE_Sem1"

        # 2. Add section B
        mgr.add_section(setup, "B")
        assert len(setup.sections) == 2

        # 3. Auto-load subjects for CSE Sem 1
        subjs = filters.get_subjects("CSE", 1)
        assert len(subjs) == 2

        # 4. Get workloads
        for s in subjs:
            wl = filters.get_workload_for_subject(s.subject_id)
            assert wl is not None

        # 5. Create assignments
        am = AssignmentManager(filters)
        am.create_assignments_from_workload(
            setup=setup, subject_id="SUB001", section="A",
            teacher_id_lecture="T001", teacher_id_practical="T002",
            practical_group="G1",
        )
        am.create_assignment(
            setup=setup, teacher_id="T001", subject_id="SUB002",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
            weekly_periods=4,
        )

        assert len(setup.assignments) == 3

        # 6. Validate
        result = am.validate_assignments(setup)
        errors = [e for e in result.errors if e.severity == Severity.ERROR]
        assert len(errors) == 0

        # 7. Save
        mgr.save_session(setup)

        # 8. Load and verify
        loaded = mgr.load_session(setup.session_id)
        assert loaded.session_id == setup.session_id
        assert len(loaded.assignments) == 3
        assert loaded.assignments[0].teacher_id == "T001"
