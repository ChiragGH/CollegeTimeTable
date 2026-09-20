"""
Master data validation layer.

Implements validation rules V-T1 through V-W2 from DATA_SCHEMA.md §6.1,
plus the user-requested checks for duplicate IDs, missing mandatory fields,
invalid enums, negative values, and cross-file referential integrity.

Usage::

    validator = DataValidator()
    result = validator.validate_all(teachers, rooms, subjects, workloads)
    if not result.is_valid:
        for error in result.errors:
            print(error)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from app.models.teacher import Teacher
from app.models.room import Room
from app.models.subject import Subject
from app.models.workload import Workload
from app.models.enums import RoomType


# ---- Valid domain values (from PROJECT_SPEC.md §3.1 and DATA_SCHEMA.md) ----

VALID_DEPARTMENTS = frozenset({
    "CSE",
    "EE",
    "ECE",
    "ME",
    "Civil",
    "Applied Science",
    "Workshop",
})

VALID_SUBJECT_BRANCHES = frozenset({
    "CSE",
    "ME",
    "ECE",
    "Civil",
    "EE",
})

VALID_ROOM_BRANCHES = frozenset({
    "CSE",
    "ME",
    "ECE",
    "Civil",
    "EE",
})

VALID_ROOM_TYPES = frozenset(rt.value for rt in RoomType)

VALID_SEMESTERS = frozenset(range(1, 7))  # 1 through 6

MAX_PERIODS_PER_WEEK = 35


# ---- Severity ----

class Severity(Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


# ---- Validation result types ----

@dataclass
class ValidationError:
    """A single validation finding."""
    rule_id: str
    severity: Severity
    entity_type: str
    entity_id: str
    field: str
    message: str

    def __str__(self) -> str:
        icon = "[ERROR]" if self.severity == Severity.ERROR else "[WARN]"
        return (
            f"{icon} [{self.rule_id}] {self.entity_type}"
            f" '{self.entity_id}' -- {self.field}: {self.message}"
        )

    @property
    def code(self) -> str:
        """Alias for rule_id for API and serializer compatibility."""
        return self.rule_id


@dataclass
class ValidationResult:
    """Aggregated validation report."""
    errors: List[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True when there are no ERROR-severity findings."""
        return not any(e.severity == Severity.ERROR for e in self.errors)

    @property
    def error_count(self) -> int:
        return sum(1 for e in self.errors if e.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for e in self.errors if e.severity == Severity.WARNING)

    @property
    def warnings(self) -> List[ValidationError]:
        """Return all findings with WARNING severity."""
        return [e for e in self.errors if e.severity == Severity.WARNING]

    def add(self, error: ValidationError) -> None:
        self.errors.append(error)

    def merge(self, other: "ValidationResult") -> None:
        self.errors.extend(other.errors)


# ---- Validator ----

class DataValidator:
    """
    Validates master data integrity.

    Each ``validate_*`` method checks one entity type and returns a
    :class:`ValidationResult`.  Use :meth:`validate_all` for a full report.
    """

    # ------------------------------------------------------------------
    # Teachers  (V-T1, V-T2 + mandatory-field checks)
    # ------------------------------------------------------------------

    def validate_teachers(self, teachers: List[Teacher]) -> ValidationResult:
        result = ValidationResult()
        seen_ids: dict[str, int] = {}

        for idx, t in enumerate(teachers):
            # Mandatory fields
            if not t.teacher_id:
                result.add(ValidationError(
                    rule_id="V-T0",
                    severity=Severity.ERROR,
                    entity_type="Teacher",
                    entity_id=f"row {idx + 2}",
                    field="teacher_id",
                    message="Missing mandatory teacher_id.",
                ))
                continue

            if not t.teacher_name:
                result.add(ValidationError(
                    rule_id="V-T0",
                    severity=Severity.ERROR,
                    entity_type="Teacher",
                    entity_id=t.teacher_id,
                    field="teacher_name",
                    message="Missing mandatory teacher_name.",
                ))

            if not t.department:
                result.add(ValidationError(
                    rule_id="V-T0",
                    severity=Severity.ERROR,
                    entity_type="Teacher",
                    entity_id=t.teacher_id,
                    field="department",
                    message="Missing mandatory department.",
                ))

            # V-T1: Unique teacher_id
            if t.teacher_id in seen_ids:
                result.add(ValidationError(
                    rule_id="V-T1",
                    severity=Severity.ERROR,
                    entity_type="Teacher",
                    entity_id=t.teacher_id,
                    field="teacher_id",
                    message=(
                        f"Duplicate teacher_id. First seen at row {seen_ids[t.teacher_id]},"
                        f" duplicate at row {idx + 2}."
                    ),
                ))
            else:
                seen_ids[t.teacher_id] = idx + 2

            # V-T2: Valid department
            if t.department and t.department not in VALID_DEPARTMENTS:
                result.add(ValidationError(
                    rule_id="V-T2",
                    severity=Severity.ERROR,
                    entity_type="Teacher",
                    entity_id=t.teacher_id,
                    field="department",
                    message=(
                        f"Invalid department '{t.department}'. "
                        f"Must be one of: {sorted(VALID_DEPARTMENTS)}."
                    ),
                ))

        return result

    # ------------------------------------------------------------------
    # Rooms  (V-R1 through V-R4 + mandatory-field checks)
    # ------------------------------------------------------------------

    def validate_rooms(self, rooms: List[Room]) -> ValidationResult:
        result = ValidationResult()
        seen_ids: dict[str, int] = {}

        for idx, r in enumerate(rooms):
            # Mandatory fields
            if not r.room_id:
                result.add(ValidationError(
                    rule_id="V-R0",
                    severity=Severity.ERROR,
                    entity_type="Room",
                    entity_id=f"row {idx + 2}",
                    field="room_id",
                    message="Missing mandatory room_id.",
                ))
                continue

            if not r.room_name:
                result.add(ValidationError(
                    rule_id="V-R0",
                    severity=Severity.ERROR,
                    entity_type="Room",
                    entity_id=r.room_id,
                    field="room_name",
                    message="Missing mandatory room_name.",
                ))

            # V-R1: Unique room_id
            if r.room_id in seen_ids:
                result.add(ValidationError(
                    rule_id="V-R1",
                    severity=Severity.ERROR,
                    entity_type="Room",
                    entity_id=r.room_id,
                    field="room_id",
                    message=(
                        f"Duplicate room_id. First seen at row {seen_ids[r.room_id]},"
                        f" duplicate at row {idx + 2}."
                    ),
                ))
            else:
                seen_ids[r.room_id] = idx + 2

            # V-R2: Valid room_type
            if not isinstance(r.room_type, RoomType):
                result.add(ValidationError(
                    rule_id="V-R2",
                    severity=Severity.ERROR,
                    entity_type="Room",
                    entity_id=r.room_id,
                    field="room_type",
                    message=(
                        f"Invalid room_type '{r.room_type}'. "
                        f"Must be one of: {sorted(VALID_ROOM_TYPES)}."
                    ),
                ))
                continue  # Can't check R3/R4 without a valid room_type

            # V-R3: LAB rooms must have a non-null branch
            if r.room_type == RoomType.LAB and not r.branch:
                result.add(ValidationError(
                    rule_id="V-R3",
                    severity=Severity.ERROR,
                    entity_type="Room",
                    entity_id=r.room_id,
                    field="branch",
                    message="LAB rooms must have a non-null branch.",
                ))

            # Validate branch value if present
            if r.branch and r.branch not in VALID_ROOM_BRANCHES:
                result.add(ValidationError(
                    rule_id="V-R3",
                    severity=Severity.ERROR,
                    entity_type="Room",
                    entity_id=r.room_id,
                    field="branch",
                    message=(
                        f"Invalid branch '{r.branch}'. "
                        f"Must be one of: {sorted(VALID_ROOM_BRANCHES)}."
                    ),
                ))

            # V-R4: LECTURE and DRAWING_HALL rooms must be shared
            if r.room_type in (RoomType.LECTURE, RoomType.DRAWING_HALL) and not r.is_shared:
                result.add(ValidationError(
                    rule_id="V-R4",
                    severity=Severity.WARNING,
                    entity_type="Room",
                    entity_id=r.room_id,
                    field="is_shared",
                    message=(
                        f"{r.room_type.value} rooms should have is_shared=TRUE."
                    ),
                ))

        return result

    # ------------------------------------------------------------------
    # Subjects  (V-S1, V-S2 partial + mandatory fields + branch/semester)
    # ------------------------------------------------------------------

    def validate_subjects(self, subjects: List[Subject]) -> ValidationResult:
        result = ValidationResult()
        seen_ids: dict[str, int] = {}

        for idx, s in enumerate(subjects):
            # Mandatory fields
            if not s.subject_id:
                result.add(ValidationError(
                    rule_id="V-S0",
                    severity=Severity.ERROR,
                    entity_type="Subject",
                    entity_id=f"row {idx + 2}",
                    field="subject_id",
                    message="Missing mandatory subject_id.",
                ))
                continue

            if not s.subject_code:
                result.add(ValidationError(
                    rule_id="V-S0",
                    severity=Severity.ERROR,
                    entity_type="Subject",
                    entity_id=s.subject_id,
                    field="subject_code",
                    message="Missing mandatory subject_code.",
                ))

            if not s.subject_name:
                result.add(ValidationError(
                    rule_id="V-S0",
                    severity=Severity.ERROR,
                    entity_type="Subject",
                    entity_id=s.subject_id,
                    field="subject_name",
                    message="Missing mandatory subject_name.",
                ))

            if not s.branch:
                result.add(ValidationError(
                    rule_id="V-S0",
                    severity=Severity.ERROR,
                    entity_type="Subject",
                    entity_id=s.subject_id,
                    field="branch",
                    message="Missing mandatory branch.",
                ))

            # V-S1: Unique subject_id
            if s.subject_id in seen_ids:
                result.add(ValidationError(
                    rule_id="V-S1",
                    severity=Severity.ERROR,
                    entity_type="Subject",
                    entity_id=s.subject_id,
                    field="subject_id",
                    message=(
                        f"Duplicate subject_id. First seen at row {seen_ids[s.subject_id]},"
                        f" duplicate at row {idx + 2}."
                    ),
                ))
            else:
                seen_ids[s.subject_id] = idx + 2

            # Branch validation
            if s.branch and s.branch not in VALID_SUBJECT_BRANCHES:
                result.add(ValidationError(
                    rule_id="V-S1b",
                    severity=Severity.ERROR,
                    entity_type="Subject",
                    entity_id=s.subject_id,
                    field="branch",
                    message=(
                        f"Invalid branch '{s.branch}'. "
                        f"Must be one of: {sorted(VALID_SUBJECT_BRANCHES)}."
                    ),
                ))

            # Semester validation
            if s.semester not in VALID_SEMESTERS:
                result.add(ValidationError(
                    rule_id="V-S1c",
                    severity=Severity.ERROR,
                    entity_type="Subject",
                    entity_id=s.subject_id,
                    field="semester",
                    message=(
                        f"Invalid semester {s.semester}. "
                        f"Must be 1–6."
                    ),
                ))

            # Short name advisory check (controlled fallback rather than error)
            if not getattr(s, "short_name", None):
                result.add(ValidationError(
                    rule_id="V-S0w",
                    severity=Severity.WARNING,
                    entity_type="Subject",
                    entity_id=s.subject_id,
                    field="short_name",
                    message="Missing short_name for subject; falling back to subject_code.",
                ))

        return result

    # ------------------------------------------------------------------
    # Workloads  (V-W1, V-W2, V-S2, V-S3, V-S4 + mandatory fields)
    # ------------------------------------------------------------------

    def validate_workloads(
        self,
        workloads: List[Workload],
        subjects: List[Subject],
    ) -> ValidationResult:
        result = ValidationResult()
        seen_ids: dict[str, int] = {}
        subject_ids = {s.subject_id for s in subjects}

        # For V-S4: accumulate per branch-semester totals
        branch_sem_totals: dict[tuple[str, int], int] = {}

        for idx, w in enumerate(workloads):
            # Mandatory fields
            if not w.workload_id:
                result.add(ValidationError(
                    rule_id="V-W0",
                    severity=Severity.ERROR,
                    entity_type="Workload",
                    entity_id=f"row {idx + 2}",
                    field="workload_id",
                    message="Missing mandatory workload_id.",
                ))
                continue

            if not w.subject_id:
                result.add(ValidationError(
                    rule_id="V-W0",
                    severity=Severity.ERROR,
                    entity_type="Workload",
                    entity_id=w.workload_id,
                    field="subject_id",
                    message="Missing mandatory subject_id.",
                ))

            if not w.branch:
                result.add(ValidationError(
                    rule_id="V-W0",
                    severity=Severity.ERROR,
                    entity_type="Workload",
                    entity_id=w.workload_id,
                    field="branch",
                    message="Missing mandatory branch.",
                ))

            if w.semester not in VALID_SEMESTERS:
                result.add(ValidationError(
                    rule_id="V-W0",
                    severity=Severity.ERROR,
                    entity_type="Workload",
                    entity_id=w.workload_id,
                    field="semester",
                    message=(
                        f"Invalid semester {w.semester}. Must be 1–6."
                    ),
                ))

            # V-W1: Unique workload_id
            if w.workload_id in seen_ids:
                result.add(ValidationError(
                    rule_id="V-W1",
                    severity=Severity.ERROR,
                    entity_type="Workload",
                    entity_id=w.workload_id,
                    field="workload_id",
                    message=(
                        f"Duplicate workload_id. First seen at row {seen_ids[w.workload_id]},"
                        f" duplicate at row {idx + 2}."
                    ),
                ))
            else:
                seen_ids[w.workload_id] = idx + 2

            # V-S2: subject_id must exist in Subjects.xlsx
            if w.subject_id and w.subject_id not in subject_ids:
                result.add(ValidationError(
                    rule_id="V-S2",
                    severity=Severity.ERROR,
                    entity_type="Workload",
                    entity_id=w.workload_id,
                    field="subject_id",
                    message=(
                        f"Referenced subject_id '{w.subject_id}' not found in Subjects.xlsx."
                    ),
                ))

            # Negative value checks
            if w.lecture_periods_per_week < 0:
                result.add(ValidationError(
                    rule_id="V-W-NEG",
                    severity=Severity.ERROR,
                    entity_type="Workload",
                    entity_id=w.workload_id,
                    field="lecture_periods_per_week",
                    message=(
                        f"Negative value: {w.lecture_periods_per_week}."
                    ),
                ))

            if w.practical_periods_per_week < 0:
                result.add(ValidationError(
                    rule_id="V-W-NEG",
                    severity=Severity.ERROR,
                    entity_type="Workload",
                    entity_id=w.workload_id,
                    field="practical_periods_per_week",
                    message=(
                        f"Negative value: {w.practical_periods_per_week}."
                    ),
                ))

            if w.total_periods_per_week < 0:
                result.add(ValidationError(
                    rule_id="V-W-NEG",
                    severity=Severity.ERROR,
                    entity_type="Workload",
                    entity_id=w.workload_id,
                    field="total_periods_per_week",
                    message=(
                        f"Negative value: {w.total_periods_per_week}."
                    ),
                ))

            # V-S3: L + P must be > 0
            if (
                w.lecture_periods_per_week >= 0
                and w.practical_periods_per_week >= 0
                and w.lecture_periods_per_week + w.practical_periods_per_week == 0
            ):
                result.add(ValidationError(
                    rule_id="V-S3",
                    severity=Severity.ERROR,
                    entity_type="Workload",
                    entity_id=w.workload_id,
                    field="total_periods",
                    message=(
                        "lecture_periods_per_week + practical_periods_per_week must be > 0."
                    ),
                ))

            # V-W2: total == L + P
            expected_total = w.lecture_periods_per_week + w.practical_periods_per_week
            if w.total_periods_per_week != expected_total:
                result.add(ValidationError(
                    rule_id="V-W2",
                    severity=Severity.ERROR,
                    entity_type="Workload",
                    entity_id=w.workload_id,
                    field="total_periods_per_week",
                    message=(
                        f"Total {w.total_periods_per_week} != "
                        f"L({w.lecture_periods_per_week}) + P({w.practical_periods_per_week}) "
                        f"= {expected_total}."
                    ),
                ))

            # Branch validation
            if w.branch and w.branch not in VALID_SUBJECT_BRANCHES:
                result.add(ValidationError(
                    rule_id="V-W0b",
                    severity=Severity.ERROR,
                    entity_type="Workload",
                    entity_id=w.workload_id,
                    field="branch",
                    message=(
                        f"Invalid branch '{w.branch}'. "
                        f"Must be one of: {sorted(VALID_SUBJECT_BRANCHES)}."
                    ),
                ))

            # Accumulate for V-S4
            if w.branch and w.semester in VALID_SEMESTERS:
                key = (w.branch, w.semester)
                branch_sem_totals[key] = (
                    branch_sem_totals.get(key, 0) + w.total_periods_per_week
                )

        # V-S4: Per branch-semester total ≤ 35 (warn if not equal)
        for (branch, semester), total in sorted(branch_sem_totals.items()):
            if total > MAX_PERIODS_PER_WEEK:
                result.add(ValidationError(
                    rule_id="V-S4",
                    severity=Severity.ERROR,
                    entity_type="Workload",
                    entity_id=f"{branch}-Sem{semester}",
                    field="total_periods",
                    message=(
                        f"Branch-semester total {total} exceeds "
                        f"maximum {MAX_PERIODS_PER_WEEK} periods/week."
                    ),
                ))
            elif total < MAX_PERIODS_PER_WEEK:
                gap = MAX_PERIODS_PER_WEEK - total
                result.add(ValidationError(
                    rule_id="V-S4",
                    severity=Severity.WARNING,
                    entity_type="Workload",
                    entity_id=f"{branch}-Sem{semester}",
                    field="total_periods",
                    message=(
                        f"Branch-semester total is {total}/{MAX_PERIODS_PER_WEEK}. "
                        f"Gap of {gap} periods (likely SCA/free periods)."
                    ),
                ))

        return result

    # ------------------------------------------------------------------
    # Full validation
    # ------------------------------------------------------------------

    def validate_all(
        self,
        teachers: List[Teacher],
        rooms: List[Room],
        subjects: List[Subject],
        workloads: List[Workload],
    ) -> ValidationResult:
        """
        Run all master data validation checks.

        Returns a single :class:`ValidationResult` containing all findings.
        """
        result = ValidationResult()

        result.merge(self.validate_teachers(teachers))
        result.merge(self.validate_rooms(rooms))
        result.merge(self.validate_subjects(subjects))
        result.merge(self.validate_workloads(workloads, subjects))

        return result
