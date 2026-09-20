"""
Unit tests for the data validation layer.

Tests every validation rule defined in DATA_SCHEMA.md §6.1 and the
user-requested checks (duplicate IDs, missing fields, invalid enums,
negative values, cross-file referential integrity).
"""

import pytest

from app.models.teacher import Teacher
from app.models.room import Room
from app.models.subject import Subject
from app.models.workload import Workload
from app.models.enums import RoomType
from app.data.validators import (
    DataValidator,
    Severity,
    VALID_DEPARTMENTS,
    VALID_SUBJECT_BRANCHES,
)


# ---- Helpers ----

def make_teacher(**overrides) -> Teacher:
    defaults = {
        "teacher_id": "T001",
        "teacher_name": "RJS",
        "department": "CSE",
        "active": True,
    }
    defaults.update(overrides)
    return Teacher(**defaults)


def make_room(**overrides) -> Room:
    defaults = {
        "room_id": "R001",
        "room_name": "CC1",
        "room_type": RoomType.LAB,
        "branch": "CSE",
        "is_shared": False,
        "active": True,
    }
    defaults.update(overrides)
    return Room(**defaults)


def make_subject(**overrides) -> Subject:
    defaults = {
        "subject_id": "SUB001",
        "subject_code": "1.1",
        "subject_name": "English",
        "branch": "CSE",
        "semester": 1,
        "active": True,
    }
    defaults.update(overrides)
    return Subject(**defaults)


def make_workload(**overrides) -> Workload:
    defaults = {
        "workload_id": "W001",
        "subject_id": "SUB001",
        "branch": "CSE",
        "semester": 1,
        "lecture_periods_per_week": 2,
        "practical_periods_per_week": 2,
        "total_periods_per_week": 4,
    }
    defaults.update(overrides)
    return Workload(**defaults)


def error_rule_ids(result):
    """Extract rule_ids of ERROR-severity findings."""
    return [e.rule_id for e in result.errors if e.severity == Severity.ERROR]


def warning_rule_ids(result):
    """Extract rule_ids of WARNING-severity findings."""
    return [e.rule_id for e in result.errors if e.severity == Severity.WARNING]


# ================================================================
# Teacher Validation Tests
# ================================================================

class TestTeacherValidation:
    def setup_method(self):
        self.validator = DataValidator()

    def test_valid_teacher(self):
        result = self.validator.validate_teachers([make_teacher()])
        assert result.is_valid
        assert result.error_count == 0

    def test_duplicate_teacher_id(self):
        """V-T1: Duplicate teacher_id → ERROR."""
        teachers = [
            make_teacher(teacher_id="T001"),
            make_teacher(teacher_id="T001", teacher_name="DUP"),
        ]
        result = self.validator.validate_teachers(teachers)
        assert "V-T1" in error_rule_ids(result)
        assert not result.is_valid

    def test_missing_teacher_id(self):
        """Missing mandatory teacher_id → ERROR."""
        result = self.validator.validate_teachers([make_teacher(teacher_id="")])
        assert "V-T0" in error_rule_ids(result)

    def test_missing_teacher_name(self):
        """Missing mandatory teacher_name → ERROR."""
        result = self.validator.validate_teachers([make_teacher(teacher_name="")])
        assert "V-T0" in error_rule_ids(result)

    def test_missing_department(self):
        """Missing mandatory department → ERROR."""
        result = self.validator.validate_teachers([make_teacher(department="")])
        assert "V-T0" in error_rule_ids(result)

    def test_invalid_department(self):
        """V-T2: Invalid department → ERROR."""
        result = self.validator.validate_teachers(
            [make_teacher(department="INVALID_DEPT")]
        )
        assert "V-T2" in error_rule_ids(result)

    @pytest.mark.parametrize("dept", sorted(VALID_DEPARTMENTS))
    def test_all_valid_departments(self, dept):
        """Every valid department passes V-T2."""
        result = self.validator.validate_teachers([make_teacher(department=dept)])
        assert "V-T2" not in error_rule_ids(result)

    def test_multiple_valid_teachers(self):
        """Multiple distinct teachers pass."""
        teachers = [
            make_teacher(teacher_id="T001"),
            make_teacher(teacher_id="T002", teacher_name="ABS"),
        ]
        result = self.validator.validate_teachers(teachers)
        assert result.is_valid


# ================================================================
# Room Validation Tests
# ================================================================

class TestRoomValidation:
    def setup_method(self):
        self.validator = DataValidator()

    def test_valid_lab_room(self):
        result = self.validator.validate_rooms([make_room()])
        assert result.is_valid

    def test_valid_lecture_room(self):
        room = make_room(
            room_id="R100",
            room_name="L1",
            room_type=RoomType.LECTURE,
            branch=None,
            is_shared=True,
        )
        result = self.validator.validate_rooms([room])
        assert result.is_valid

    def test_duplicate_room_id(self):
        """V-R1: Duplicate room_id → ERROR."""
        rooms = [
            make_room(room_id="R001"),
            make_room(room_id="R001", room_name="DUP"),
        ]
        result = self.validator.validate_rooms(rooms)
        assert "V-R1" in error_rule_ids(result)

    def test_invalid_room_type(self):
        """V-R2: Invalid room_type → ERROR."""
        room = make_room(room_type="INVALID_TYPE")
        result = self.validator.validate_rooms([room])
        assert "V-R2" in error_rule_ids(result)

    def test_lab_without_branch(self):
        """V-R3: LAB room with no branch → ERROR."""
        room = make_room(branch=None)
        result = self.validator.validate_rooms([room])
        assert "V-R3" in error_rule_ids(result)

    def test_lab_with_invalid_branch(self):
        """V-R3: LAB room with invalid branch → ERROR."""
        room = make_room(branch="XYZZY")
        result = self.validator.validate_rooms([room])
        assert "V-R3" in error_rule_ids(result)

    def test_lecture_room_not_shared(self):
        """V-R4: LECTURE room with is_shared=FALSE → WARNING."""
        room = make_room(
            room_type=RoomType.LECTURE,
            branch=None,
            is_shared=False,
        )
        result = self.validator.validate_rooms([room])
        assert "V-R4" in warning_rule_ids(result)

    def test_drawing_hall_not_shared(self):
        """V-R4: DRAWING_HALL room with is_shared=FALSE → WARNING."""
        room = make_room(
            room_type=RoomType.DRAWING_HALL,
            branch=None,
            is_shared=False,
        )
        result = self.validator.validate_rooms([room])
        assert "V-R4" in warning_rule_ids(result)

    def test_missing_room_id(self):
        result = self.validator.validate_rooms([make_room(room_id="")])
        assert "V-R0" in error_rule_ids(result)

    def test_missing_room_name(self):
        result = self.validator.validate_rooms([make_room(room_name="")])
        assert "V-R0" in error_rule_ids(result)


# ================================================================
# Subject Validation Tests
# ================================================================

class TestSubjectValidation:
    def setup_method(self):
        self.validator = DataValidator()

    def test_valid_subject(self):
        result = self.validator.validate_subjects([make_subject()])
        assert result.is_valid

    def test_duplicate_subject_id(self):
        """V-S1: Duplicate subject_id → ERROR."""
        subjects = [
            make_subject(subject_id="SUB001"),
            make_subject(subject_id="SUB001", subject_name="DUP"),
        ]
        result = self.validator.validate_subjects(subjects)
        assert "V-S1" in error_rule_ids(result)

    def test_missing_subject_id(self):
        result = self.validator.validate_subjects([make_subject(subject_id="")])
        assert "V-S0" in error_rule_ids(result)

    def test_missing_subject_code(self):
        result = self.validator.validate_subjects([make_subject(subject_code="")])
        assert "V-S0" in error_rule_ids(result)

    def test_missing_subject_name(self):
        result = self.validator.validate_subjects([make_subject(subject_name="")])
        assert "V-S0" in error_rule_ids(result)

    def test_missing_branch(self):
        result = self.validator.validate_subjects([make_subject(branch="")])
        assert "V-S0" in error_rule_ids(result)

    def test_invalid_branch(self):
        """Invalid branch name → ERROR."""
        result = self.validator.validate_subjects(
            [make_subject(branch="NONEXISTENT")]
        )
        assert "V-S1b" in error_rule_ids(result)

    @pytest.mark.parametrize("branch", sorted(VALID_SUBJECT_BRANCHES))
    def test_all_valid_branches(self, branch):
        result = self.validator.validate_subjects(
            [make_subject(branch=branch)]
        )
        assert "V-S1b" not in error_rule_ids(result)

    def test_invalid_semester_zero(self):
        """Semester 0 → ERROR."""
        result = self.validator.validate_subjects([make_subject(semester=0)])
        assert "V-S1c" in error_rule_ids(result)

    def test_invalid_semester_seven(self):
        """Semester 7 → ERROR."""
        result = self.validator.validate_subjects([make_subject(semester=7)])
        assert "V-S1c" in error_rule_ids(result)

    @pytest.mark.parametrize("sem", [1, 2, 3, 4, 5, 6])
    def test_valid_semesters(self, sem):
        result = self.validator.validate_subjects([make_subject(semester=sem)])
        assert "V-S1c" not in error_rule_ids(result)


# ================================================================
# Workload Validation Tests
# ================================================================

class TestWorkloadValidation:
    def setup_method(self):
        self.validator = DataValidator()
        self.subjects = [make_subject(subject_id="SUB001")]

    def test_valid_workload(self):
        result = self.validator.validate_workloads(
            [make_workload()], self.subjects
        )
        # Only warnings (V-S4 gap) expected, no errors
        assert result.is_valid or result.error_count == 0

    def test_duplicate_workload_id(self):
        """V-W1: Duplicate workload_id → ERROR."""
        workloads = [
            make_workload(workload_id="W001"),
            make_workload(workload_id="W001", subject_id="SUB001"),
        ]
        result = self.validator.validate_workloads(workloads, self.subjects)
        assert "V-W1" in error_rule_ids(result)

    def test_missing_subject_reference(self):
        """V-S2: subject_id not found in Subjects → ERROR."""
        workloads = [make_workload(subject_id="SUB_GHOST")]
        result = self.validator.validate_workloads(workloads, self.subjects)
        assert "V-S2" in error_rule_ids(result)

    def test_zero_total_periods(self):
        """V-S3: L + P == 0 → ERROR."""
        workloads = [make_workload(
            lecture_periods_per_week=0,
            practical_periods_per_week=0,
            total_periods_per_week=0,
        )]
        result = self.validator.validate_workloads(workloads, self.subjects)
        assert "V-S3" in error_rule_ids(result)

    def test_total_mismatch(self):
        """V-W2: total ≠ L + P → ERROR."""
        workloads = [make_workload(
            lecture_periods_per_week=2,
            practical_periods_per_week=2,
            total_periods_per_week=5,  # should be 4
        )]
        result = self.validator.validate_workloads(workloads, self.subjects)
        assert "V-W2" in error_rule_ids(result)

    def test_negative_lecture_periods(self):
        """Negative lecture periods → ERROR."""
        workloads = [make_workload(
            lecture_periods_per_week=-1,
            practical_periods_per_week=2,
            total_periods_per_week=1,
        )]
        result = self.validator.validate_workloads(workloads, self.subjects)
        assert "V-W-NEG" in error_rule_ids(result)

    def test_negative_practical_periods(self):
        """Negative practical periods → ERROR."""
        workloads = [make_workload(
            lecture_periods_per_week=2,
            practical_periods_per_week=-1,
            total_periods_per_week=1,
        )]
        result = self.validator.validate_workloads(workloads, self.subjects)
        assert "V-W-NEG" in error_rule_ids(result)

    def test_negative_total_periods(self):
        """Negative total periods → ERROR."""
        workloads = [make_workload(
            lecture_periods_per_week=2,
            practical_periods_per_week=2,
            total_periods_per_week=-4,
        )]
        result = self.validator.validate_workloads(workloads, self.subjects)
        assert "V-W-NEG" in error_rule_ids(result)

    def test_invalid_branch(self):
        """Invalid branch in workload → ERROR."""
        workloads = [make_workload(branch="XYZZY")]
        result = self.validator.validate_workloads(workloads, self.subjects)
        assert "V-W0b" in error_rule_ids(result)

    def test_invalid_semester(self):
        """Invalid semester in workload → ERROR."""
        workloads = [make_workload(semester=0)]
        result = self.validator.validate_workloads(workloads, self.subjects)
        assert "V-W0" in error_rule_ids(result)

    def test_branch_semester_exceeds_35(self):
        """V-S4: total > 35 for a branch-semester → ERROR."""
        # Create a subject and workload that pushes total above 35
        subjects = [
            make_subject(subject_id="SUB001"),
            make_subject(subject_id="SUB002", subject_code="1.2"),
        ]
        workloads = [
            make_workload(
                workload_id="W001",
                subject_id="SUB001",
                lecture_periods_per_week=20,
                practical_periods_per_week=0,
                total_periods_per_week=20,
            ),
            make_workload(
                workload_id="W002",
                subject_id="SUB002",
                lecture_periods_per_week=16,
                practical_periods_per_week=0,
                total_periods_per_week=16,
            ),
        ]
        result = self.validator.validate_workloads(workloads, subjects)
        assert "V-S4" in error_rule_ids(result)

    def test_branch_semester_gap_warning(self):
        """V-S4: total < 35 for a branch-semester → WARNING (SCA gap)."""
        result = self.validator.validate_workloads(
            [make_workload()], self.subjects
        )
        assert "V-S4" in warning_rule_ids(result)

    def test_missing_workload_id(self):
        workloads = [make_workload(workload_id="")]
        result = self.validator.validate_workloads(workloads, self.subjects)
        assert "V-W0" in error_rule_ids(result)

    def test_missing_subject_id(self):
        workloads = [make_workload(subject_id="")]
        result = self.validator.validate_workloads(workloads, self.subjects)
        assert "V-W0" in error_rule_ids(result)

    def test_missing_branch(self):
        workloads = [make_workload(branch="")]
        result = self.validator.validate_workloads(workloads, self.subjects)
        assert "V-W0" in error_rule_ids(result)


# ================================================================
# Full validate_all Tests
# ================================================================

class TestValidateAll:
    def setup_method(self):
        self.validator = DataValidator()

    def test_all_valid(self):
        """Full validation with valid data — only warnings expected."""
        teachers = [make_teacher()]
        rooms = [make_room()]
        subjects = [make_subject()]
        workloads = [make_workload()]

        result = self.validator.validate_all(teachers, rooms, subjects, workloads)
        # Should pass (is_valid=True); only V-S4 gap warning expected
        assert result.is_valid

    def test_cross_file_errors(self):
        """Workload referencing nonexistent subject → ERROR in validate_all."""
        teachers = [make_teacher()]
        rooms = [make_room()]
        subjects = [make_subject(subject_id="SUB999")]
        workloads = [make_workload(subject_id="SUB001")]  # SUB001 doesn't exist

        result = self.validator.validate_all(teachers, rooms, subjects, workloads)
        assert "V-S2" in error_rule_ids(result)
        assert not result.is_valid

    def test_empty_data(self):
        """Empty lists should pass validation (nothing to validate)."""
        result = self.validator.validate_all([], [], [], [])
        assert result.is_valid

    def test_result_merge(self):
        """Errors from all entity types appear in combined result."""
        teachers = [make_teacher(department="BAD")]
        rooms = [make_room(room_type="BAD")]
        subjects = [make_subject(branch="BAD")]
        workloads = [make_workload(subject_id="GHOST")]

        result = self.validator.validate_all(teachers, rooms, subjects, workloads)
        rule_ids = error_rule_ids(result)
        assert "V-T2" in rule_ids
        assert "V-R2" in rule_ids
        assert "V-S1b" in rule_ids
        assert "V-S2" in rule_ids


# ================================================================
# ValidationResult Tests
# ================================================================

class TestValidationResult:
    def test_is_valid_with_no_errors(self):
        from app.data.validators import ValidationResult
        result = ValidationResult()
        assert result.is_valid
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_is_valid_with_only_warnings(self):
        from app.data.validators import ValidationResult, ValidationError
        result = ValidationResult()
        result.add(ValidationError(
            rule_id="TEST",
            severity=Severity.WARNING,
            entity_type="Test",
            entity_id="X",
            field="f",
            message="warning only",
        ))
        assert result.is_valid  # Warnings don't invalidate
        assert result.warning_count == 1
        assert result.error_count == 0

    def test_is_invalid_with_errors(self):
        from app.data.validators import ValidationResult, ValidationError
        result = ValidationResult()
        result.add(ValidationError(
            rule_id="TEST",
            severity=Severity.ERROR,
            entity_type="Test",
            entity_id="X",
            field="f",
            message="real error",
        ))
        assert not result.is_valid
        assert result.error_count == 1
