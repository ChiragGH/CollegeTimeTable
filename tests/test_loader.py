"""
Unit tests for the Excel data loader.

Tests that the loader can read each master data file and produce the
expected domain model instances with correct types and field values.
"""

import pytest
from pathlib import Path

from app.data.loader import DataLoader, DataLoadError
from app.models.teacher import Teacher
from app.models.room import Room
from app.models.subject import Subject
from app.models.workload import Workload
from app.models.enums import RoomType


# Resolve the real data directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "Data" / "master"

# Skip all tests if real data files aren't available
pytestmark = pytest.mark.skipif(
    not DATA_DIR.exists(),
    reason=f"Test data directory not found: {DATA_DIR}",
)


@pytest.fixture
def loader():
    return DataLoader(data_dir=str(DATA_DIR))


class TestLoadTeachers:
    def test_loads_all_rows(self, loader):
        teachers = loader.load_teachers()
        assert len(teachers) == 68  # per DATA_SCHEMA.md

    def test_returns_teacher_instances(self, loader):
        teachers = loader.load_teachers()
        assert all(isinstance(t, Teacher) for t in teachers)

    def test_first_teacher_fields(self, loader):
        teachers = loader.load_teachers()
        t = teachers[0]
        assert t.teacher_id == "T001"
        assert t.teacher_name == "RJS"
        assert t.department == "CSE"
        assert t.active is True

    def test_teacher_id_types(self, loader):
        teachers = loader.load_teachers()
        for t in teachers:
            assert isinstance(t.teacher_id, str)
            assert isinstance(t.teacher_name, str)
            assert isinstance(t.department, str)
            assert isinstance(t.active, bool)


class TestLoadRooms:
    def test_loads_all_rows(self, loader):
        rooms = loader.load_rooms()
        assert len(rooms) == 41  # per DATA_SCHEMA.md

    def test_returns_room_instances(self, loader):
        rooms = loader.load_rooms()
        assert all(isinstance(r, Room) for r in rooms)

    def test_first_room_fields(self, loader):
        rooms = loader.load_rooms()
        r = rooms[0]
        assert r.room_id == "R001"
        assert r.room_name == "CC1"
        assert r.room_type == RoomType.LAB
        assert r.branch == "CSE"
        assert r.is_shared is False
        assert r.active is True

    def test_lecture_room_shared(self, loader):
        rooms = loader.load_rooms()
        lecture_rooms = [r for r in rooms if r.room_type == RoomType.LECTURE]
        assert len(lecture_rooms) == 13  # per DATA_SCHEMA.md
        for r in lecture_rooms:
            assert r.is_shared is True

    def test_room_type_is_enum(self, loader):
        rooms = loader.load_rooms()
        for r in rooms:
            assert isinstance(r.room_type, RoomType)


class TestLoadSubjects:
    def test_loads_all_rows(self, loader):
        subjects = loader.load_subjects()
        assert len(subjects) == 193  # per DATA_SCHEMA.md

    def test_returns_subject_instances(self, loader):
        subjects = loader.load_subjects()
        assert all(isinstance(s, Subject) for s in subjects)

    def test_first_subject_fields(self, loader):
        subjects = loader.load_subjects()
        s = subjects[0]
        assert s.subject_id == "SUB001"
        assert s.subject_code == "1.1"
        assert s.subject_name == "English and Communication Skills - I"
        assert s.branch == "CSE"
        assert s.semester == 1
        assert s.active is True

    def test_semesters_in_range(self, loader):
        subjects = loader.load_subjects()
        for s in subjects:
            assert 1 <= s.semester <= 6


class TestLoadWorkloads:
    def test_loads_all_rows(self, loader):
        workloads = loader.load_workloads()
        assert len(workloads) == 193  # 1:1 with subjects

    def test_returns_workload_instances(self, loader):
        workloads = loader.load_workloads()
        assert all(isinstance(w, Workload) for w in workloads)

    def test_first_workload_fields(self, loader):
        workloads = loader.load_workloads()
        w = workloads[0]
        assert w.workload_id == "W001"
        assert w.subject_id == "SUB001"
        assert w.branch == "CSE"
        assert w.semester == 1
        assert w.lecture_periods_per_week == 2
        assert w.practical_periods_per_week == 2
        assert w.total_periods_per_week == 4

    def test_non_negative_periods(self, loader):
        workloads = loader.load_workloads()
        for w in workloads:
            assert w.lecture_periods_per_week >= 0
            assert w.practical_periods_per_week >= 0
            assert w.total_periods_per_week >= 0

    def test_total_equals_sum(self, loader):
        workloads = loader.load_workloads()
        for w in workloads:
            assert w.total_periods_per_week == (
                w.lecture_periods_per_week + w.practical_periods_per_week
            ), f"{w.workload_id}: total mismatch"


class TestLoaderErrors:
    def test_missing_file(self):
        loader = DataLoader(data_dir="nonexistent_dir")
        with pytest.raises(DataLoadError):
            loader.load_teachers()
