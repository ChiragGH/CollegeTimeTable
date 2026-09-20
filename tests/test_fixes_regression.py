"""
Comprehensive automated tests verifying Bug fixes #1 through #4,
Subject short_name integration, Branch canonicalization,
Teacher eligibility filtering, and Timetable display architecture.
"""

import pytest
from app.web.server import create_app
from app.models.branch import CANONICAL_BRANCHES, normalize_branch
from app.models.subject import Subject
from app.data.loader import DataLoader
from app.setup.filters import SetupFilters
from app.setup.assignment_manager import AssignmentManager
from app.models.session import TimetableSetup
from app.models.section import Section
from app.models.enums import ActivityType


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ====================================================================
# TEST A: Master Data Endpoints (No 500 Error)
# ====================================================================

def test_master_data_teachers_endpoint(client):
    res = client.get("/api/master/teachers")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)
    assert len(data) > 0
    t0 = data[0]
    assert "teacher_id" in t0
    assert "teacher_name" in t0
    assert "department" in t0
    assert "designation" in t0
    assert "active" in t0


def test_master_data_rooms_endpoint(client):
    res = client.get("/api/master/rooms")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)
    assert len(data) > 0
    r0 = data[0]
    assert "room_id" in r0
    assert "room_name" in r0
    assert "room_type" in r0


def test_master_data_subjects_endpoint(client):
    res = client.get("/api/master/subjects")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)
    assert len(data) > 0
    s0 = data[0]
    assert "subject_id" in s0
    assert "subject_code" in s0
    assert "subject_name" in s0
    assert "short_name" in s0
    assert "branch" in s0
    assert "semester" in s0


def test_master_data_workloads_endpoint(client):
    res = client.get("/api/master/workloads")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)
    assert len(data) > 0
    w0 = data[0]
    assert "workload_id" in w0
    assert "subject_id" in w0
    assert "total_periods_per_week" in w0


def test_master_data_validate_endpoint(client):
    res = client.get("/api/master/validate")
    assert res.status_code == 200
    data = res.get_json()
    assert "valid" in data
    assert "errors" in data
    assert "warnings" in data
    assert isinstance(data["errors"], list)
    assert isinstance(data["warnings"], list)


# ====================================================================
# TEST B: Subject Schema & short_name Fallback
# ====================================================================

def test_subject_sub016_de():
    loader = DataLoader("Data/master")
    subjects = loader.load_subjects()
    sub16 = next((s for s in subjects if s.subject_id == "SUB016"), None)
    assert sub16 is not None
    assert sub16.subject_code == "3.3"
    assert sub16.subject_name == "Digital Electronics"
    assert sub16.short_name == "DE"
    assert sub16.branch == "CSE"
    assert sub16.semester == 3
    assert sub16.active is True


def test_subject_sub015_os():
    loader = DataLoader("Data/master")
    subjects = loader.load_subjects()
    sub15 = next((s for s in subjects if s.subject_id == "SUB015"), None)
    assert sub15 is not None
    assert sub15.subject_code == "3.2"
    assert sub15.subject_name == "Operating Systems"
    assert sub15.short_name == "OS"


def test_subject_fallback_behavior():
    # When short_name is empty, post_init falls back to subject_code
    s1 = Subject(subject_id="SUB999", subject_code="9.9", subject_name="Advanced AI", branch="CSE", semester=5)
    assert s1.short_name == "9.9"

    # Positional instantiation compatibility
    s2 = Subject("SUB998", "9.8", "Computer Vision", "CSE", 6, True)
    assert s2.short_name == "9.8"


# ====================================================================
# TEST C: Branch Dropdown (Canonical branches, not short names)
# ====================================================================

def test_branch_dropdown_values(client):
    res = client.get("/api/filters/branches")
    assert res.status_code == 200
    branches = res.get_json()
    assert "CSE" in branches
    assert "ECE" in branches
    assert "EE" in branches
    assert "ME" in branches
    assert "Civil" in branches

    # Must NOT contain subject short names
    subject_short_names = ["A.Mech.", "AC", "ADC", "ADE", "ADUWF", "AE", "AIT", "AM-I", "AM-II", "AP-I", "AP-II", "DE", "OS", "PIC"]
    for sn in subject_short_names:
        assert sn not in branches, f"Subject short_name '{sn}' found in branch dropdown!"


def test_branch_normalization():
    assert normalize_branch("CSE") == "CSE"
    assert normalize_branch("CE") == "Civil"
    assert normalize_branch("Civil") == "Civil"
    assert normalize_branch("civil") == "Civil"
    assert normalize_branch("ce") == "Civil"
    assert normalize_branch("Applied Science") == "Applied Science"
    assert normalize_branch("Workshop") == "Workshop"


# ====================================================================
# TEST D: Subject Filter (CSE Semester 3)
# ====================================================================

def test_filter_cse_semester_3_subjects(client):
    res = client.get("/api/filters/subjects?branch=CSE&semester=3")
    assert res.status_code == 200
    subjects = res.get_json()
    assert len(subjects) > 0

    sub_map = {s["subject_id"]: s for s in subjects}
    assert "SUB015" in sub_map  # Operating Systems
    assert sub_map["SUB015"]["short_name"] == "OS"

    assert "SUB016" in sub_map  # Digital Electronics
    assert sub_map["SUB016"]["short_name"] == "DE"

    assert "SUB017" in sub_map  # Programming in C
    assert sub_map["SUB017"]["short_name"] == "PIC"

    assert "SUB018" in sub_map  # DBMS
    assert sub_map["SUB018"]["short_name"] == "DBMS"


# ====================================================================
# TEST E: Teacher Eligibility Filtering
# ====================================================================

def test_teacher_filter_cse_eligibility(client):
    res = client.get("/api/filters/teachers?branch=CSE")
    assert res.status_code == 200
    teachers = res.get_json()
    assert len(teachers) > 0

    depts = {t["department"] for t in teachers}
    assert "CSE" in depts
    assert "Applied Science" in depts
    assert "Workshop" in depts

    # Excluded: dedicated teachers from other engineering branches
    assert "EE" not in depts
    assert "ECE" not in depts
    assert "ME" not in depts
    assert "Civil" not in depts


def test_teacher_filter_ce_alias_eligibility(client):
    # Testing CE alias maps to Civil
    res = client.get("/api/filters/teachers?branch=CE")
    assert res.status_code == 200
    teachers = res.get_json()
    depts = {t["department"] for t in teachers}
    assert "Civil" in depts
    assert "Applied Science" in depts
    assert "Workshop" in depts
    assert "CSE" not in depts
    assert "EE" not in depts


# ====================================================================
# TEST F & G: Teaching Assignment & Auto Add Progression
# ====================================================================

def test_auto_add_test_assignment_progression():
    loader = DataLoader("Data/master")
    teachers = loader.load_teachers()
    rooms = loader.load_rooms()
    subjects = loader.load_subjects()
    workloads = loader.load_workloads()
    filters = SetupFilters(teachers, rooms, subjects, workloads)
    mgr = AssignmentManager(filters)

    setup = TimetableSetup(
        session_id="CSE-SEM3-TEST-AUTO",
        academic_year="2026-27",
        branch="CSE",
        semester=3,
        sections=[Section(branch="CSE", semester=3, label="A", groups=["G1", "G2"])],
        assignments=[],
    )

    created_assignments = []
    for _ in range(8):
        a, desc = mgr.auto_create_assignment(setup)
        assert a is not None, f"Failed to create auto assignment: {desc}"
        created_assignments.append(a)

        # Verify teacher eligibility
        teacher = filters.get_teacher(a.teacher_id)
        assert teacher is not None
        assert teacher.department in ("CSE", "Applied Science", "Workshop")

        # Verify subject belongs to CSE Sem 3
        subj = filters.get_subject(a.subject_id)
        assert subj is not None
        assert subj.branch == "CSE"
        assert subj.semester == 3

        # Verify workload consistency
        wl = filters.get_workload_for_subject(a.subject_id)
        assert wl is not None
        if a.activity_type == ActivityType.LECTURE:
            assert a.weekly_periods == wl.lecture_periods_per_week
            assert a.group == "ALL"
        elif a.activity_type == ActivityType.PRACTICAL:
            assert a.weekly_periods == wl.practical_periods_per_week
            assert a.group in ("G1", "G2")

    # Verify no duplicate assignments
    keys = [(a.subject_id, a.activity_type, a.section, a.group) for a in created_assignments]
    assert len(keys) == len(set(keys)), "Duplicate assignment keys created!"


# ====================================================================
# TEST H: Timetable Display (DE and OS in generated timetable placements)
# ====================================================================

def test_timetable_generation_display_short_names(client):
    # 1. Create a session
    res = client.post("/api/session/create", json={
        "session_id": "TEST-CSE-SEM3-DISP",
        "branch": "CSE",
        "semester": 3,
        "academic_year": "2026-27",
    })
    assert res.status_code == 200

    # 2. Add sections
    res = client.post("/api/session/TEST-CSE-SEM3-DISP/sections", json={
        "sections": [{"branch": "CSE", "semester": 3, "label": "A", "groups": ["G1", "G2"]}]
    })
    assert res.status_code == 200

    # 3. Add auto assignments (4 subject packages cover SUB014-SUB017 including OS, DE, PIC)
    for _ in range(4):
        res = client.post("/api/session/TEST-CSE-SEM3-DISP/assignments/auto", json={})
        assert res.status_code == 200
        assert res.get_json()["created"] is True

    # 4. Generate timetable
    res = client.post("/api/session/TEST-CSE-SEM3-DISP/generate", json={})
    assert res.status_code == 200
    gen_data = res.get_json()
    assert "placements" in gen_data
    assert len(gen_data["placements"]) > 0

    # 5. Check timetable placements carry short_name and internal subject_id
    for p in gen_data["placements"]:
        assert "subject_id" in p
        assert "short_name" in p
        assert p["short_name"] != ""

        if p["subject_id"] == "SUB015":
            assert p["short_name"] == "OS"
        elif p["subject_id"] == "SUB016":
            assert p["short_name"] == "DE"
        elif p["subject_id"] == "SUB017":
            assert p["short_name"] == "PIC"
