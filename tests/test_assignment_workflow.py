"""
Tests for the Teaching Assignment workflow fixes:

1.  Teacher eligibility (backend domain logic + API) — a CSE timetable
    must not offer teachers from unrelated departments.
2.  Weekly periods derived from master workload (never manually set).
3.  Lecture uses lecture_periods_per_week; practical uses
    practical_periods_per_week.
4.  Block size x sessions per week must equal weekly periods.
5.  Zero-workload subject/activity combinations cannot be assigned.
6.  Auto Add Test Assignment creates exactly one valid assignment per
    click, walking through remaining combinations instead of duplicating.
7.  Master workload data remains unchanged after assignment creation.
8.  Changing the session context cannot submit stale selections
    (subject must belong to the session's branch + semester).

Domain-level tests use in-memory master data; API tests build synthetic
master .xlsx files and exercise the Flask endpoints end to end.
"""

import openpyxl
import pytest

from app.models.teacher import Teacher
from app.models.room import Room
from app.models.subject import Subject
from app.models.workload import Workload
from app.models.section import Section
from app.models.assignment import Assignment
from app.models.session import TimetableSetup
from app.models.enums import ActivityType, RoomType
from app.setup.filters import SetupFilters, SHARED_SERVICE_DEPARTMENTS
from app.setup.assignment_manager import AssignmentManager
from app.setup.session_manager import SessionManager
from app.web.server import create_app


# ================================================================
# Shared in-memory master data
# ================================================================

def make_teachers():
    return [
        Teacher(teacher_id="T001", teacher_name="RJS", department="CSE", active=True),
        Teacher(teacher_id="T002", teacher_name="ABS", department="CSE", active=True),
        Teacher(teacher_id="T003", teacher_name="CSE_INACT", department="CSE", active=False),
        Teacher(teacher_id="T013", teacher_name="VKA", department="EE", active=True),
        Teacher(teacher_id="T025", teacher_name="AG", department="ECE", active=True),
        Teacher(teacher_id="T033", teacher_name="ASHISH", department="ME", active=True),
        Teacher(teacher_id="T042", teacher_name="SR", department="Civil", active=True),
        Teacher(teacher_id="T051", teacher_name="MT", department="Applied Science", active=True),
        Teacher(teacher_id="T052", teacher_name="GA", department="Applied Science", active=True),
        Teacher(teacher_id="T060", teacher_name="KK", department="Workshop", active=True),
    ]


def make_subjects():
    return [
        # CSE semester 2: lecture-only, lecture+practical, practical-only
        Subject(subject_id="SUB101", subject_code="2.1", subject_name="Advances in IT",
                branch="CSE", semester=2, active=True),
        Subject(subject_id="SUB102", subject_code="2.2", subject_name="Analog Electronics",
                branch="CSE", semester=2, active=True),
        Subject(subject_id="SUB103", subject_code="2.3", subject_name="Engineering Graphics",
                branch="CSE", semester=2, active=True),
        Subject(subject_id="SUB199", subject_code="2.9", subject_name="No Workload Subject",
                branch="CSE", semester=2, active=True),
        # Decoys: wrong branch / wrong semester
        Subject(subject_id="SUB901", subject_code="3.2", subject_name="OS (other branch)",
                branch="EE", semester=2, active=True),
        Subject(subject_id="SUB902", subject_code="3.1", subject_name="CSE Sem3",
                branch="CSE", semester=3, active=True),
    ]


def make_workloads():
    return [
        Workload(workload_id="W101", subject_id="SUB101", branch="CSE", semester=2,
                 lecture_periods_per_week=3, practical_periods_per_week=0,
                 total_periods_per_week=3),
        Workload(workload_id="W102", subject_id="SUB102", branch="CSE", semester=2,
                 lecture_periods_per_week=2, practical_periods_per_week=4,
                 total_periods_per_week=6),
        Workload(workload_id="W103", subject_id="SUB103", branch="CSE", semester=2,
                 lecture_periods_per_week=0, practical_periods_per_week=6,
                 total_periods_per_week=6),
    ]


def make_rooms():
    return [
        Room(room_id="R030", room_name="L1", room_type=RoomType.LECTURE, branch=None,
             is_shared=True, active=True),
        Room(room_id="R001", room_name="CC1", room_type=RoomType.LAB, branch="CSE",
             is_shared=False, active=True),
        Room(room_id="R007", room_name="FOEE", room_type=RoomType.LAB, branch="EE",
             is_shared=False, active=True),
    ]


@pytest.fixture
def filters():
    return SetupFilters(make_teachers(), make_rooms(), make_subjects(), make_workloads())


@pytest.fixture
def am(filters):
    return AssignmentManager(filters)


def make_setup(assignments=None, sections=None):
    return TimetableSetup(
        session_id="test-session", academic_year="2026-27",
        branch="CSE", semester=2,
        sections=sections or [Section(branch="CSE", semester=2, label="A")],
        assignments=assignments or [],
    )


# ================================================================
# 1. Teacher eligibility (Bug #1 fix — domain layer)
# ================================================================

class TestTeacherEligibility:
    def test_cse_branch_excludes_unrelated_departments(self, filters):
        eligible = filters.get_eligible_teachers("CSE")
        ids = {t.teacher_id for t in eligible}
        # Same department + shared-service departments only
        assert ids == {"T001", "T002", "T051", "T052", "T060"}

    def test_ee_branch_excludes_cse_teachers(self, filters):
        eligible = filters.get_eligible_teachers("EE")
        depts = {t.department for t in eligible}
        assert "CSE" not in depts
        assert "EE" in depts
        assert "Applied Science" in depts  # shared-service department

    def test_inactive_teachers_never_eligible(self, filters):
        eligible = filters.get_eligible_teachers("CSE")
        assert "T003" not in {t.teacher_id for t in eligible}

    def test_shared_service_departments_constant(self):
        assert "Applied Science" in SHARED_SERVICE_DEPARTMENTS
        assert "Workshop" in SHARED_SERVICE_DEPARTMENTS

    def test_subject_and_activity_context_accepted(self, filters):
        """Context params refine nothing yet, but must be accepted."""
        base = {t.teacher_id for t in filters.get_eligible_teachers("CSE")}
        with_ctx = {
            t.teacher_id for t in filters.get_eligible_teachers(
                "CSE", subject_id="SUB102", activity_type=ActivityType.PRACTICAL
            )
        }
        assert base == with_ctx

    def test_subject_specific_eligibility_hook(self, filters, monkeypatch):
        """When a subject-level eligibility source exists, it wins."""
        monkeypatch.setattr(
            filters, "get_subject_teacher_eligibility",
            lambda subject_id: frozenset({"T013"}) if subject_id == "SUB102" else None,
        )
        eligible = filters.get_eligible_teachers("CSE", subject_id="SUB102")
        assert {t.teacher_id for t in eligible} == {"T013"}

    def test_no_eligibility_data_invented(self, filters):
        """Without a source, the hook must return None (no invented mappings)."""
        assert filters.get_subject_teacher_eligibility("SUB102") is None


# ================================================================
# 2-5. Workload-derived weekly periods (Bug #2 fix — domain layer)
# ================================================================

class TestWorkloadDerivation:
    def test_lecture_uses_lecture_periods(self, am):
        assert am.get_workload_for_activity("SUB102", ActivityType.LECTURE) == 2
        assert am.get_workload_for_activity("SUB101", ActivityType.LECTURE) == 3

    def test_practical_uses_practical_periods(self, am):
        assert am.get_workload_for_activity("SUB102", ActivityType.PRACTICAL) == 4
        assert am.get_workload_for_activity("SUB103", ActivityType.PRACTICAL) == 6

    def test_zero_workload_activity_is_zero(self, am):
        # SUB101 has practical = 0
        assert am.get_workload_for_activity("SUB101", ActivityType.PRACTICAL) == 0
        # SUB103 has lecture = 0
        assert am.get_workload_for_activity("SUB103", ActivityType.LECTURE) == 0

    def test_missing_workload_row_is_zero(self, am):
        assert am.get_workload_for_activity("SUB199", ActivityType.LECTURE) == 0

    def test_activities_without_workload_source_are_zero(self, am):
        # WORKLOAD_FIELD_BY_ACTIVITY has no entry for these — never invent values
        assert am.get_workload_for_activity("SUB102", ActivityType.WORKSHOP) == 0
        assert am.get_workload_for_activity("SUB102", ActivityType.DRAWING) == 0

    def test_compute_block_config_practical_default(self, am):
        assert am.compute_block_config(ActivityType.PRACTICAL, 4) == (2, 2)
        assert am.compute_block_config(ActivityType.PRACTICAL, 6) == (2, 3)

    def test_compute_block_config_falls_back_to_one(self, am):
        # 5 periods cannot be split into blocks of 2 -> valid fallback: 1x5
        assert am.compute_block_config(ActivityType.PRACTICAL, 5) == (1, 5)

    def test_compute_block_config_lecture_default(self, am):
        assert am.compute_block_config(ActivityType.LECTURE, 3) == (1, 3)

    def test_compute_block_config_zero(self, am):
        assert am.compute_block_config(ActivityType.LECTURE, 0) == (0, 0)


class TestPrepareAssignment:
    def test_lecture_periods_derived_not_requested(self, am):
        """weekly_periods is derived from master workload; no override param."""
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB101",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
        )
        assert errors == []
        assert a.weekly_periods == 3      # from lecture_periods_per_week
        assert a.block_size == 1
        assert a.sessions_per_week == 3
        assert a.room_type == RoomType.LECTURE

    def test_practical_periods_derived(self, am):
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB102",
            section="A", group="G1", activity_type=ActivityType.PRACTICAL,
        )
        assert errors == []
        assert a.weekly_periods == 4      # from practical_periods_per_week
        assert a.block_size == 2
        assert a.sessions_per_week == 2
        assert a.room_type == RoomType.LAB

    def test_teacher_from_unrelated_department_rejected(self, am):
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T013",  # EE teacher on a CSE timetable
            subject_id="SUB101", section="A", group="ALL",
            activity_type=ActivityType.LECTURE,
        )
        assert a is None
        assert any("not eligible" in e for e in errors)

    def test_inactive_teacher_rejected(self, am):
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T003",
            subject_id="SUB101", section="A", group="ALL",
            activity_type=ActivityType.LECTURE,
        )
        assert a is None
        assert any("not active" in e for e in errors)

    def test_missing_teacher_rejected(self, am):
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T999",
            subject_id="SUB101", section="A", group="ALL",
            activity_type=ActivityType.LECTURE,
        )
        assert a is None
        assert any("not found" in e for e in errors)

    def test_zero_workload_rejected_with_clear_message(self, am):
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB101",
            section="A", group="G1", activity_type=ActivityType.PRACTICAL,
        )
        assert a is None
        assert any("No practical workload exists" in e for e in errors)

    def test_missing_workload_row_rejected(self, am):
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB199",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
        )
        assert a is None
        assert any("No workload exists" in e for e in errors)

    def test_workshop_rejected_without_workload_source(self, am):
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB102",
            section="A", group="G1", activity_type=ActivityType.WORKSHOP,
        )
        assert a is None
        assert errors  # clear rejection — no invented workload values

    def test_subject_from_other_branch_rejected(self, am):
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB901",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
        )
        assert a is None
        assert any("belongs to" in e for e in errors)

    def test_subject_from_other_semester_rejected(self, am):
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB902",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
        )
        assert a is None
        assert any("belongs to" in e for e in errors)

    def test_capacity_exceeded_rejected(self, am):
        setup = make_setup()
        a1, errors = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB101",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
        )
        assert a1 is not None and errors == []
        a2, errors = am.prepare_assignment(
            setup, teacher_id="T002", subject_id="SUB101",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
        )
        assert a2 is None
        assert any("exceed the subject's configured workload" in e for e in errors)

    def test_block_size_must_divide_weekly_periods(self, am):
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB101",
            section="A", group="ALL", activity_type=ActivityType.LECTURE,
            block_size=2,  # 3 periods cannot be split into blocks of 2
        )
        assert a is None
        assert any("does not equal weekly periods" in e for e in errors)

    def test_lecture_group_must_be_all(self, am):
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB101",
            section="A", group="G1", activity_type=ActivityType.LECTURE,
        )
        assert a is None
        assert any("must use group 'ALL'" in e for e in errors)

    def test_practical_group_not_in_section_rejected(self, am):
        setup = make_setup(
            sections=[Section(branch="CSE", semester=2, label="A", groups=["G1"])]
        )
        a, errors = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB102",
            section="A", group="G2", activity_type=ActivityType.PRACTICAL,
        )
        assert a is None
        assert any("not configured for section" in e for e in errors)

    def test_room_type_mismatch_rejected(self, am):
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB102",
            section="A", group="G1", activity_type=ActivityType.PRACTICAL,
            room_id="R030",  # lecture room for a practical
        )
        assert a is None
        assert any("has type" in e for e in errors)

    def test_valid_preferred_room_accepted(self, am):
        setup = make_setup()
        a, errors = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB102",
            section="A", group="G1", activity_type=ActivityType.PRACTICAL,
            room_id="R001",
        )
        assert errors == []
        assert a.room_id == "R001"

    def test_practical_capacity_is_per_group(self, am):
        """G1 and G2 practicals are parallel sessions — each consumes the
        subject's practical workload for its own group."""
        setup = make_setup()
        a1, e1 = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB102",
            section="A", group="G1", activity_type=ActivityType.PRACTICAL,
        )
        a2, e2 = am.prepare_assignment(
            setup, teacher_id="T002", subject_id="SUB102",
            section="A", group="G2", activity_type=ActivityType.PRACTICAL,
        )
        assert a1 is not None and e1 == []
        assert a2 is not None and e2 == []
        # ...but a third G1 practical would exceed the workload
        a3, e3 = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB102",
            section="A", group="G1", activity_type=ActivityType.PRACTICAL,
        )
        assert a3 is None
        assert any("exceed" in e for e in e3)


# ================================================================
# 6. Auto Add Test Assignment (domain layer)
# ================================================================

class TestAutoAssignment:
    def test_creates_exactly_one_valid_assignment(self, am):
        setup = make_setup()
        a, description = am.auto_create_assignment(setup)
        assert a is not None
        assert len(setup.assignments) == 1
        assert a.weekly_periods == 3       # SUB101 lecture = 3
        assert a.activity_type == ActivityType.LECTURE
        assert a.group == "ALL"
        assert "Advances in IT" in description

    def test_repeated_calls_walk_through_combinations(self, am):
        setup = make_setup()
        seen = []
        for _ in range(6):
            a, desc = am.auto_create_assignment(setup)
            assert a is not None, desc
            seen.append((a.subject_id, a.activity_type.value, a.section, a.group))
        # Order: SUB101 lecture ALL, then SUB102 lecture ALL,
        # then SUB102 practical G1, SUB102 practical G2,
        # then SUB103 practical G1, SUB103 practical G2
        assert seen == [
            ("SUB101", "LECTURE", "A", "ALL"),
            ("SUB102", "LECTURE", "A", "ALL"),
            ("SUB102", "PRACTICAL", "A", "G1"),
            ("SUB102", "PRACTICAL", "A", "G2"),
            ("SUB103", "PRACTICAL", "A", "G1"),
            ("SUB103", "PRACTICAL", "A", "G2"),
        ]

    def test_repeated_calls_never_duplicate(self, am):
        setup = make_setup()
        combos = []
        for _ in range(20):
            a, _ = am.auto_create_assignment(setup)
            if a is None:
                break
            combo = (a.subject_id, a.activity_type, a.section, a.group)
            assert combo not in combos
            combos.append(combo)

    def test_exhaustion_reports_clear_message(self, am):
        setup = make_setup()
        for _ in range(6):
            a, _ = am.auto_create_assignment(setup)
        assert a is not None
        a, message = am.auto_create_assignment(setup)
        assert a is None
        assert "already assigned" in message
        # and the setup was not mutated by the failed attempt
        assert len(setup.assignments) == 6

    def test_skips_zero_workload_activities(self, am):
        setup = make_setup()
        # SUB101 practical = 0; auto flow must never try to assign it
        for _ in range(6):
            a, _ = am.auto_create_assignment(setup)
        combos = {(a.subject_id, a.activity_type) for a in setup.assignments}
        assert ("SUB101", ActivityType.PRACTICAL) not in combos

    def test_least_loaded_teacher_chosen(self, am):
        setup = make_setup(
            assignments=[Assignment(
                assignment_id="A001", session_id="test-session",
                teacher_id="T001", subject_id="SUB101", branch="CSE",
                semester=2, section="A", group="ALL",
                activity_type=ActivityType.LECTURE, weekly_periods=3,
                block_size=1, sessions_per_week=3,
            )]
        )
        # SUB101 lecture is taken; next candidate is SUB102 lecture —
        # T001 already carries 3 periods, so T002 must be chosen.
        a, _ = am.auto_create_assignment(setup)
        assert a.subject_id == "SUB102"
        assert a.teacher_id == "T002"

    def test_no_subjects_message(self, am, monkeypatch):
        monkeypatch.setattr(
            am.filters, "get_subjects", lambda *args, **kwargs: []
        )
        a, message = am.auto_create_assignment(make_setup())
        assert a is None
        assert "No subjects found" in message

    def test_auto_pick_does_not_mutate(self, am):
        setup = make_setup()
        candidate, _ = am.auto_pick_assignment(setup)
        assert candidate == {
            "teacher_id": "T001", "subject_id": "SUB101", "section": "A",
            "group": "ALL", "activity_type": ActivityType.LECTURE,
            "block_size": 1,
        }
        assert len(setup.assignments) == 0


# ================================================================
# 7. Master workload integrity
# ================================================================

class TestMasterDataIntegrity:
    def test_master_workload_unchanged_after_assignments(self, filters, am):
        before = [(w.subject_id, w.lecture_periods_per_week,
                   w.practical_periods_per_week, w.total_periods_per_week)
                  for w in filters._workloads]
        setup = make_setup()
        for _ in range(6):
            am.auto_create_assignment(setup)
        after = [(w.subject_id, w.lecture_periods_per_week,
                  w.practical_periods_per_week, w.total_periods_per_week)
                 for w in filters._workloads]
        assert before == after

    def test_assignment_references_master_values(self, am):
        """Assignments must mirror the master workload, not user input."""
        setup = make_setup()
        wl = am.filters.get_workload_for_subject("SUB102")
        a, _ = am.prepare_assignment(
            setup, teacher_id="T001", subject_id="SUB102",
            section="A", group="G1", activity_type=ActivityType.PRACTICAL,
        )
        assert a.weekly_periods == wl.practical_periods_per_week


# ================================================================
# Batch validation rules (V-A7 .. V-A10)
# ================================================================

class TestValidationRules:
    def test_va7_ineligible_teacher_flagged(self, filters, am):
        a = Assignment(
            assignment_id="A001", session_id="test-session",
            teacher_id="T013", subject_id="SUB101", branch="CSE",
            semester=2, section="A", group="ALL",
            activity_type=ActivityType.LECTURE, weekly_periods=3,
            block_size=1, sessions_per_week=3,
        )
        setup = make_setup([a])
        result = am.validate_assignments(setup)
        assert any(e.rule_id == "V-A7" for e in result.errors)

    def test_va8_block_mismatch_flagged(self, filters, am):
        a = Assignment(
            assignment_id="A001", session_id="test-session",
            teacher_id="T001", subject_id="SUB102", branch="CSE",
            semester=2, section="A", group="G1",
            activity_type=ActivityType.PRACTICAL, weekly_periods=4,
            block_size=3, sessions_per_week=2,  # 3 x 2 = 6 != 4
        )
        setup = make_setup([a])
        result = am.validate_assignments(setup)
        assert any(e.rule_id == "V-A8" for e in result.errors)

    def test_va9_workload_mismatch_flagged(self, filters, am):
        a = Assignment(
            assignment_id="A001", session_id="test-session",
            teacher_id="T001", subject_id="SUB101", branch="CSE",
            semester=2, section="A", group="ALL",
            activity_type=ActivityType.LECTURE, weekly_periods=9,  # master says 3
            block_size=1, sessions_per_week=9,
        )
        setup = make_setup([a])
        result = am.validate_assignments(setup)
        assert any(e.rule_id == "V-A9" for e in result.errors)

    def test_va10_capacity_exceeded_flagged(self, filters, am):
        def mk(aid, tid):
            return Assignment(
                assignment_id=aid, session_id="test-session",
                teacher_id=tid, subject_id="SUB101", branch="CSE",
                semester=2, section="A", group="ALL",
                activity_type=ActivityType.LECTURE, weekly_periods=3,
                block_size=1, sessions_per_week=3,
            )
        setup = make_setup([mk("A001", "T001"), mk("A002", "T002")])
        result = am.validate_assignments(setup)
        assert any(e.rule_id == "V-A10" for e in result.errors)

    def test_clean_setup_passes(self, am):
        setup = make_setup()
        for _ in range(6):
            am.auto_create_assignment(setup)
        result = am.validate_assignments(setup)
        assert [e for e in result.errors] == []


# ================================================================
# API tests (Flask test client over synthetic master .xlsx)
# ================================================================

def _write_master_xlsx(data_dir):
    """Create a synthetic master dataset: CSE/EE/Applied Science teachers,
    CSE Sem-2 subjects, lecture + CSE lab rooms."""
    def sheet(filename, headers, rows):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(headers)
        for r in rows:
            ws.append(r)
        wb.save(data_dir / filename)

    sheet("Teachers.xlsx",
          ["teacher_id", "teacher_name", "department", "active"],
          [["T001", "RJS", "CSE", "TRUE"],
           ["T002", "ABS", "CSE", "TRUE"],
           ["T013", "VKA", "EE", "TRUE"],
           ["T051", "MT", "Applied Science", "TRUE"]])
    sheet("Subjects.xlsx",
          ["subject_id", "subject_code", "subject_name", "branch", "semester", "active"],
          [["SUB101", "2.1", "Advances in IT", "CSE", 2, "TRUE"],
           ["SUB102", "2.2", "Analog Electronics", "CSE", 2, "TRUE"],
           ["SUB103", "2.3", "Engineering Graphics", "CSE", 2, "TRUE"],
           ["SUB901", "3.1", "CSE Sem3 subject", "CSE", 3, "TRUE"]])
    sheet("Workloads.xlsx",
          ["workload_id", "subject_id", "branch", "semester",
           "lecture_periods_per_week", "practical_periods_per_week", "total_periods_per_week"],
          [["W101", "SUB101", "CSE", 2, 3, 0, 3],
           ["W102", "SUB102", "CSE", 2, 2, 4, 6],
           ["W103", "SUB103", "CSE", 2, 0, 6, 6],
           ["W901", "SUB901", "CSE", 3, 3, 0, 3]])
    sheet("Rooms.xlsx",
          ["room_id", "room_name", "room_type", "branch", "is_shared", "active"],
          [["R030", "L1", "LECTURE", None, "TRUE", "TRUE"],
           ["R001", "CC1", "LAB", "CSE", "FALSE", "TRUE"],
           ["R007", "FOEE", "LAB", "EE", "FALSE", "TRUE"]])


@pytest.fixture
def api(tmp_path):
    data_dir = tmp_path / "master"
    data_dir.mkdir()
    _write_master_xlsx(data_dir)
    app = create_app(data_dir=str(data_dir))
    app.config["TESTING"] = True
    client = app.test_client()

    # Create a CSE Sem-2 session with one section
    resp = client.post("/api/session/create", json={
        "session_id": "api-test", "branch": "CSE", "semester": 2,
        "academic_year": "2026-27",
    })
    assert resp.status_code == 200
    resp = client.post("/api/session/api-test/sections", json={"sections": ["A"]})
    assert resp.status_code == 200
    return client


class TestTeacherAPI:
    def test_cse_branch_returns_no_unrelated_teachers(self, api):
        resp = api.get("/api/filters/teachers?branch=CSE")
        assert resp.status_code == 200
        ids = {t["teacher_id"] for t in resp.get_json()}
        assert ids == {"T001", "T002", "T051"}  # no EE teacher T013
        assert "T013" not in ids

    def test_legacy_department_filter_still_works(self, api):
        resp = api.get("/api/filters/teachers?department=EE")
        assert resp.status_code == 200
        assert [t["teacher_id"] for t in resp.get_json()] == ["T013"]

    def test_invalid_activity_type_rejected(self, api):
        resp = api.get("/api/filters/teachers?branch=CSE&activity_type=BOGUS")
        assert resp.status_code == 400


class TestAssignmentAPI:
    def test_add_lecture_assignment(self, api):
        resp = api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB101", "teacher_id": "T001",
                "section": "A", "group": "ALL",
                "activity_type": "LECTURE", "block_size": 1,
            }
        })
        assert resp.status_code == 200
        a = resp.get_json()["assignment"]
        assert a["weekly_periods"] == 3      # derived from master workload
        assert a["sessions_per_week"] == 3
        assert a["room_type"] == "LECTURE"

    def test_add_practical_uses_practical_workload(self, api):
        resp = api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB102", "teacher_id": "T001",
                "section": "A", "group": "G1",
                "activity_type": "PRACTICAL", "block_size": 2,
            }
        })
        assert resp.status_code == 200
        a = resp.get_json()["assignment"]
        assert a["weekly_periods"] == 4      # practical_periods_per_week
        assert a["sessions_per_week"] == 2

    def test_weekly_periods_cannot_be_overridden(self, api):
        """A forged weekly_periods in the payload must not leak into storage."""
        resp = api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB101", "teacher_id": "T001",
                "section": "A", "group": "ALL",
                "activity_type": "LECTURE", "block_size": 1,
                "weekly_periods": 99,  # forged client value
            }
        })
        assert resp.status_code == 200
        assert resp.get_json()["assignment"]["weekly_periods"] == 3

    def test_inconsistent_block_config_rejected(self, api):
        resp = api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB101", "teacher_id": "T001",
                "section": "A", "group": "ALL",
                "activity_type": "LECTURE", "block_size": 2,  # 2 x ? != 3
            }
        })
        assert resp.status_code == 400
        assert "does not equal weekly periods" in resp.get_json()["error"]

    def test_unrelated_teacher_rejected(self, api):
        resp = api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB101", "teacher_id": "T013",  # EE
                "section": "A", "group": "ALL",
                "activity_type": "LECTURE", "block_size": 1,
            }
        })
        assert resp.status_code == 400
        assert "not eligible" in resp.get_json()["error"]

    def test_zero_workload_activity_rejected(self, api):
        resp = api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB101", "teacher_id": "T001",
                "section": "A", "group": "G1",
                "activity_type": "PRACTICAL",  # SUB101 practical = 0
                "block_size": 2,
            }
        })
        assert resp.status_code == 400
        assert "No practical workload exists" in resp.get_json()["error"]

    def test_workshop_rejected_without_workload_source(self, api):
        resp = api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB102", "teacher_id": "T001",
                "section": "A", "group": "G1",
                "activity_type": "WORKSHOP", "block_size": 3,
            }
        })
        assert resp.status_code == 400

    def test_capacity_exceeded_rejected(self, api):
        first = api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB101", "teacher_id": "T001",
                "section": "A", "group": "ALL",
                "activity_type": "LECTURE", "block_size": 1,
            }
        })
        assert first.status_code == 200
        second = api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB101", "teacher_id": "T002",
                "section": "A", "group": "ALL",
                "activity_type": "LECTURE", "block_size": 1,
            }
        })
        assert second.status_code == 400
        assert "exceed" in second.get_json()["error"]

    def test_stale_subject_rejected(self, api):
        """A subject outside the session branch/semester cannot be submitted."""
        resp = api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB901",  # CSE Sem 3, session is Sem 2
                "teacher_id": "T001", "section": "A", "group": "ALL",
                "activity_type": "LECTURE", "block_size": 1,
            }
        })
        assert resp.status_code == 400
        assert "belongs to" in resp.get_json()["error"]

    def test_invalid_activity_type_rejected(self, api):
        resp = api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB101", "teacher_id": "T001",
                "section": "A", "group": "ALL",
                "activity_type": "BOGUS", "block_size": 1,
            }
        })
        assert resp.status_code == 400

    def test_delete_then_add_no_id_collision(self, api):
        r1 = api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB101", "teacher_id": "T001",
                "section": "A", "group": "ALL",
                "activity_type": "LECTURE", "block_size": 1,
            }
        })
        aid = r1.get_json()["assignment"]["assignment_id"]
        api.delete(f"/api/session/api-test/assignments/{aid}")
        r2 = api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB101", "teacher_id": "T001",
                "section": "A", "group": "ALL",
                "activity_type": "LECTURE", "block_size": 1,
            }
        })
        assert r2.status_code == 200
        assert r2.get_json()["assignment"]["assignment_id"] == aid  # reused, not collided


class TestAutoAssignmentAPI:
    def test_auto_add_creates_exactly_one(self, api):
        resp = api.post("/api/session/api-test/assignments/auto", json={})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["created"] is True
        assert data["total"] == 1
        assert data["assignment"]["weekly_periods"] > 0
        assert data["assignment"]["room_id"] is None  # rooms stay a separate concern

    def test_repeated_clicks_create_different_assignments(self, api):
        seen = []
        for _ in range(6):
            resp = api.post("/api/session/api-test/assignments/auto", json={"mode": "single"})
            data = resp.get_json()
            assert data["created"] is True
            a = data["assignment"]
            combo = (a["subject_id"], a["activity_type"], a["section"], a["group"])
            assert combo not in seen  # never blindly duplicates
            seen.append(combo)
        assert len(seen) == 6

    def test_auto_add_exhausts_cleanly(self, api):
        for _ in range(6):
            api.post("/api/session/api-test/assignments/auto", json={})
        resp = api.post("/api/session/api-test/assignments/auto", json={})
        data = resp.get_json()
        assert data["created"] is False
        assert "already assigned" in data["message"]

    def test_auto_fill_dry_run_saves_nothing(self, api):
        resp = api.post("/api/session/api-test/assignments/auto",
                        json={"dry_run": True})
        data = resp.get_json()
        assert data["proposed"] is not None
        assert data["proposed"]["subject_id"] == "SUB101"
        assert data["proposed"]["activity_type"] == "LECTURE"
        sess = api.get("/api/session/api-test").get_json()
        assert sess["assignments"] == []  # nothing persisted


class TestWorkloadSummaryAPI:
    def test_summary_reflects_assignments(self, api):
        api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB102", "teacher_id": "T001",
                "section": "A", "group": "G1",
                "activity_type": "PRACTICAL", "block_size": 2,
            }
        })
        resp = api.get("/api/session/api-test/workload-summary?section=A&group=G1")
        assert resp.status_code == 200
        summary = {e["subject_id"]: e for e in resp.get_json()}
        assert summary["SUB102"]["practical"] == {
            "required": 4, "assigned": 4, "remaining": 0}
        assert summary["SUB102"]["lecture"]["remaining"] == 2
        assert summary["SUB101"]["lecture"]["remaining"] == 3

    def test_master_workloads_endpoint_unchanged_after_assignments(self, api):
        before = api.get("/api/master/workloads").get_json()
        for _ in range(6):
            api.post("/api/session/api-test/assignments/auto", json={})
        after = api.get("/api/master/workloads").get_json()
        assert before == after


class TestSessionEndpointRegression:
    def test_get_session_after_generation_is_serializable(self, api):
        """Regression: the live ScheduleResult must not leak into the
        session JSON (it made GET /api/session/<id> fail after generate)."""
        api.post("/api/session/api-test/assignments", json={
            "assignment": {
                "subject_id": "SUB101", "teacher_id": "T001",
                "section": "A", "group": "ALL",
                "activity_type": "LECTURE", "block_size": 1,
            }
        })
        gen = api.post("/api/session/api-test/generate", json={})
        assert gen.status_code == 200
        resp = api.get("/api/session/api-test")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["result"] is not None
        assert "result_obj" not in data
