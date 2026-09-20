"""
Unit tests for cascading setup filters.

Tests every filter chain specified by the user:
    branch --> semester
    branch + semester --> subjects (+ workloads)
    activity_type --> valid rooms (with branch-specific LAB filtering)
"""

import pytest

from app.models.teacher import Teacher
from app.models.room import Room
from app.models.subject import Subject
from app.models.workload import Workload
from app.models.enums import ActivityType, RoomType
from app.setup.filters import SetupFilters


# ---- Test data fixtures ----

@pytest.fixture
def teachers():
    return [
        Teacher(teacher_id="T001", teacher_name="RJS", department="CSE", active=True),
        Teacher(teacher_id="T002", teacher_name="ABS", department="CSE", active=True),
        Teacher(teacher_id="T003", teacher_name="RB", department="ECE", active=True),
        Teacher(teacher_id="T004", teacher_name="PB", department="ME", active=False),
    ]


@pytest.fixture
def rooms():
    return [
        # CSE labs
        Room(room_id="R001", room_name="CC1", room_type=RoomType.LAB, branch="CSE", is_shared=False, active=True),
        Room(room_id="R002", room_name="CC2", room_type=RoomType.LAB, branch="CSE", is_shared=False, active=True),
        # ECE lab
        Room(room_id="R010", room_name="DR", room_type=RoomType.LAB, branch="ECE", is_shared=False, active=True),
        # ME lab (inactive)
        Room(room_id="R020", room_name="TD", room_type=RoomType.LAB, branch="ME", is_shared=False, active=False),
        # Lecture rooms
        Room(room_id="R030", room_name="L1", room_type=RoomType.LECTURE, branch=None, is_shared=True, active=True),
        Room(room_id="R031", room_name="L2", room_type=RoomType.LECTURE, branch=None, is_shared=True, active=True),
        # Drawing halls
        Room(room_id="R040", room_name="DH1", room_type=RoomType.DRAWING_HALL, branch=None, is_shared=True, active=True),
        # Workshop
        Room(room_id="R050", room_name="WS1", room_type=RoomType.WORKSHOP, branch=None, is_shared=True, active=True),
    ]


@pytest.fixture
def subjects():
    return [
        Subject(subject_id="SUB001", subject_code="1.1", subject_name="English", branch="CSE", semester=1, active=True),
        Subject(subject_id="SUB002", subject_code="1.2", subject_name="Math", branch="CSE", semester=1, active=True),
        Subject(subject_id="SUB010", subject_code="3.1", subject_name="DSA", branch="CSE", semester=3, active=True),
        Subject(subject_id="SUB011", subject_code="3.2", subject_name="OS", branch="CSE", semester=3, active=True),
        Subject(subject_id="SUB050", subject_code="1.1", subject_name="Physics", branch="ECE", semester=1, active=True),
        Subject(subject_id="SUB060", subject_code="5.1", subject_name="Inactive", branch="CSE", semester=5, active=False),
    ]


@pytest.fixture
def workloads():
    return [
        Workload(workload_id="W001", subject_id="SUB001", branch="CSE", semester=1, lecture_periods_per_week=2, practical_periods_per_week=2, total_periods_per_week=4),
        Workload(workload_id="W002", subject_id="SUB002", branch="CSE", semester=1, lecture_periods_per_week=4, practical_periods_per_week=0, total_periods_per_week=4),
        Workload(workload_id="W010", subject_id="SUB010", branch="CSE", semester=3, lecture_periods_per_week=3, practical_periods_per_week=2, total_periods_per_week=5),
        Workload(workload_id="W011", subject_id="SUB011", branch="CSE", semester=3, lecture_periods_per_week=4, practical_periods_per_week=0, total_periods_per_week=4),
        Workload(workload_id="W050", subject_id="SUB050", branch="ECE", semester=1, lecture_periods_per_week=3, practical_periods_per_week=3, total_periods_per_week=6),
    ]


@pytest.fixture
def filters(teachers, rooms, subjects, workloads):
    return SetupFilters(teachers, rooms, subjects, workloads)


# ================================================================
# Branch / Semester Filters
# ================================================================

class TestBranchSemesterFilters:
    def test_get_branches(self, filters):
        branches = filters.get_branches()
        assert "CSE" in branches
        assert "ECE" in branches

    def test_get_semesters_for_cse(self, filters):
        sems = filters.get_semesters_for_branch("CSE")
        assert 1 in sems
        assert 3 in sems

    def test_get_semesters_for_ece(self, filters):
        sems = filters.get_semesters_for_branch("ECE")
        assert sems == [1]

    def test_get_semesters_nonexistent_branch(self, filters):
        sems = filters.get_semesters_for_branch("XYZZY")
        assert sems == []


# ================================================================
# Subject / Workload Filters
# ================================================================

class TestSubjectFilters:
    def test_get_subjects_cse_sem1(self, filters):
        subjs = filters.get_subjects("CSE", 1)
        assert len(subjs) == 2
        ids = {s.subject_id for s in subjs}
        assert "SUB001" in ids
        assert "SUB002" in ids

    def test_get_subjects_cse_sem3(self, filters):
        subjs = filters.get_subjects("CSE", 3)
        assert len(subjs) == 2

    def test_get_subjects_ece_sem1(self, filters):
        subjs = filters.get_subjects("ECE", 1)
        assert len(subjs) == 1
        assert subjs[0].subject_id == "SUB050"

    def test_get_subjects_empty(self, filters):
        subjs = filters.get_subjects("ME", 1)
        assert subjs == []

    def test_get_subjects_excludes_inactive(self, filters):
        """Active-only filter excludes inactive subjects."""
        subjs = filters.get_subjects("CSE", 5, active_only=True)
        assert len(subjs) == 0

    def test_get_subjects_includes_inactive_when_asked(self, filters):
        subjs = filters.get_subjects("CSE", 5, active_only=False)
        assert len(subjs) == 1

    def test_get_workload_for_subject(self, filters):
        wl = filters.get_workload_for_subject("SUB001")
        assert wl is not None
        assert wl.lecture_periods_per_week == 2
        assert wl.practical_periods_per_week == 2

    def test_get_workload_missing(self, filters):
        wl = filters.get_workload_for_subject("SUB_GHOST")
        assert wl is None

    def test_get_subjects_with_workloads(self, filters):
        pairs = filters.get_subjects_with_workloads("CSE", 1)
        assert len(pairs) == 2
        for subj, wl in pairs:
            assert subj is not None
            assert wl is not None

    def test_get_subjects_with_workloads_preserves_order(self, filters):
        pairs = filters.get_subjects_with_workloads("CSE", 3)
        subject_ids = [s.subject_id for s, _ in pairs]
        assert subject_ids == ["SUB010", "SUB011"]


# ================================================================
# Room Filters (cascading by activity type + branch)
# ================================================================

class TestRoomFilters:
    def test_lecture_rooms(self, filters):
        """LECTURE --> only LECTURE-type rooms."""
        rooms = filters.get_rooms_for_activity(ActivityType.LECTURE)
        assert len(rooms) == 2
        for r in rooms:
            assert r.room_type == RoomType.LECTURE

    def test_practical_cse_labs(self, filters):
        """PRACTICAL + branch=CSE --> only CSE labs."""
        rooms = filters.get_rooms_for_activity(ActivityType.PRACTICAL, branch="CSE")
        assert len(rooms) == 2
        for r in rooms:
            assert r.room_type == RoomType.LAB
            assert r.branch == "CSE"

    def test_practical_ece_labs(self, filters):
        """PRACTICAL + branch=ECE --> only ECE labs."""
        rooms = filters.get_rooms_for_activity(ActivityType.PRACTICAL, branch="ECE")
        assert len(rooms) == 1
        assert rooms[0].room_name == "DR"

    def test_practical_me_labs_excludes_inactive(self, filters):
        """Inactive labs should be excluded by default."""
        rooms = filters.get_rooms_for_activity(ActivityType.PRACTICAL, branch="ME")
        assert len(rooms) == 0

    def test_practical_me_labs_includes_inactive(self, filters):
        rooms = filters.get_rooms_for_activity(
            ActivityType.PRACTICAL, branch="ME", active_only=False
        )
        assert len(rooms) == 1
        assert rooms[0].room_name == "TD"

    def test_drawing_rooms(self, filters):
        """DRAWING --> only DRAWING_HALL rooms."""
        rooms = filters.get_rooms_for_activity(ActivityType.DRAWING)
        assert len(rooms) == 1
        assert rooms[0].room_name == "DH1"

    def test_workshop_rooms(self, filters):
        """WORKSHOP --> only WORKSHOP rooms."""
        rooms = filters.get_rooms_for_activity(ActivityType.WORKSHOP)
        assert len(rooms) == 1
        assert rooms[0].room_name == "WS1"

    def test_practical_no_branch_returns_all_labs(self, filters):
        """PRACTICAL without branch filter returns all active labs."""
        rooms = filters.get_rooms_for_activity(ActivityType.PRACTICAL)
        assert len(rooms) == 3  # CC1, CC2, DR (ME is inactive)

    def test_get_rooms_by_type_lab(self, filters):
        rooms = filters.get_rooms_by_type(RoomType.LAB, branch="CSE")
        assert len(rooms) == 2

    def test_valid_room_types_for_lecture(self, filters):
        types = filters.get_valid_room_types_for_activity(ActivityType.LECTURE)
        assert types == [RoomType.LECTURE]

    def test_valid_room_types_for_practical(self, filters):
        types = filters.get_valid_room_types_for_activity(ActivityType.PRACTICAL)
        assert types == [RoomType.LAB]


# ================================================================
# Teacher Filters
# ================================================================

class TestTeacherFilters:
    def test_all_teachers(self, filters):
        ts = filters.get_teachers(active_only=False)
        assert len(ts) == 4

    def test_active_teachers(self, filters):
        ts = filters.get_teachers(active_only=True)
        assert len(ts) == 3

    def test_cse_teachers(self, filters):
        ts = filters.get_teachers(department="CSE")
        assert len(ts) == 2
        for t in ts:
            assert t.department == "CSE"

    def test_get_teacher_by_id(self, filters):
        t = filters.get_teacher("T001")
        assert t is not None
        assert t.teacher_name == "RJS"

    def test_get_teacher_missing(self, filters):
        assert filters.get_teacher("T999") is None


# ================================================================
# Lookup Helpers
# ================================================================

class TestLookups:
    def test_get_subject(self, filters):
        s = filters.get_subject("SUB001")
        assert s is not None
        assert s.subject_name == "English"

    def test_get_room(self, filters):
        r = filters.get_room("R030")
        assert r is not None
        assert r.room_name == "L1"

    def test_get_activity_types(self, filters):
        types = filters.get_activity_types()
        assert ActivityType.LECTURE in types
        assert ActivityType.PRACTICAL in types
        assert ActivityType.WORKSHOP in types
        assert ActivityType.DRAWING in types
