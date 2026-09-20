"""
Cascading selection and filtering for timetable setup.

Implements the filter chains described by the user:

    branch --> semester
    branch + semester --> subjects (+ their workloads)
    activity_type --> valid rooms
    branch + LAB --> branch-specific labs
    LECTURE --> lecture rooms
    DRAWING_HALL --> drawing halls
    WORKSHOP --> shared workshop rooms

All filter methods are pure functions over the master data lists
that were loaded at startup.  No I/O is performed here.
"""

from typing import Dict, List, Optional, Tuple

from app.models.teacher import Teacher
from app.models.room import Room
from app.models.subject import Subject
from app.models.workload import Workload
from app.models.branch import Branch, CANONICAL_BRANCHES, normalize_branch
from app.models.enums import ActivityType, RoomType


# Mapping from ActivityType to the RoomType(s) that can host it.
# Defined in ARCHITECTURE.md §3.5 (room_eligibility.py).
ACTIVITY_ROOM_MAP: Dict[ActivityType, List[RoomType]] = {
    ActivityType.LECTURE:   [RoomType.LECTURE],
    ActivityType.PRACTICAL: [RoomType.LAB],
    ActivityType.WORKSHOP:  [RoomType.WORKSHOP],
    ActivityType.DRAWING:   [RoomType.DRAWING_HALL],
}


# Departments that serve every branch (common-service departments).
# Applied Science teaches Mathematics/Physics/English across all
# engineering branches; Workshop staff run workshop practice for all
# branches.  These are included in teacher eligibility for any branch.
# Per-branch exclusions/subject-specific eligibility can be layered on
# top once the college supplies such rules (see get_eligible_teachers).
SHARED_SERVICE_DEPARTMENTS = frozenset({"Applied Science", "Workshop"})


class SetupFilters:
    """
    Provides cascading selection/filtering over master data.

    Usage::

        filters = SetupFilters(teachers, rooms, subjects, workloads)

        # Branch --> available semesters
        semesters = filters.get_semesters_for_branch("CSE")

        # Branch + semester --> subjects & workloads
        subjs = filters.get_subjects("CSE", 3)
        wl    = filters.get_workload_for_subject("SUB042")

        # Activity type --> valid rooms
        rooms = filters.get_rooms_for_activity("PRACTICAL", branch="CSE")
    """

    def __init__(
        self,
        teachers: List[Teacher],
        rooms: List[Room],
        subjects: List[Subject],
        workloads: List[Workload],
    ):
        self._teachers = teachers
        self._rooms = rooms
        self._subjects = subjects
        self._workloads = workloads

        # Build lookup indexes for fast access
        self._teacher_by_id: Dict[str, Teacher] = {
            t.teacher_id: t for t in teachers
        }
        self._subject_by_id: Dict[str, Subject] = {
            s.subject_id: s for s in subjects
        }
        self._workload_by_subject: Dict[str, Workload] = {
            w.subject_id: w for w in workloads
        }
        self._room_by_id: Dict[str, Room] = {
            r.room_id: r for r in rooms
        }

    # ------------------------------------------------------------------
    # Branch / Semester filters
    # ------------------------------------------------------------------

    def get_branches(self) -> List[str]:
        """
        Return distinct canonical branch codes present in the subject catalogue.

        Guarantees that only valid canonical branch codes (e.g. CSE, ECE, EE, ME, Civil)
        are returned, never subject short names or ad-hoc codes.
        """
        branches = sorted({
            normalize_branch(s.branch)
            for s in self._subjects
            if s.branch and normalize_branch(s.branch)
        })
        return branches

    def get_branch_objects(self) -> List[Branch]:
        """Return authoritative Branch domain models for all active branches."""
        active_branch_ids = set(self.get_branches())
        return [b for b in CANONICAL_BRANCHES if b.branch_id in active_branch_ids]

    def get_semesters_for_branch(self, branch: str) -> List[int]:
        """
        Given a branch, return the semesters that have subjects defined.

        Handles aliases such as ``CE`` -> ``Civil`` transparently.
        """
        norm_branch = normalize_branch(branch)
        return sorted({
            s.semester
            for s in self._subjects
            if normalize_branch(s.branch) == norm_branch and s.active
        })

    # ------------------------------------------------------------------
    # Subject / Workload filters
    # ------------------------------------------------------------------

    def get_subjects(
        self,
        branch: str,
        semester: int,
        active_only: bool = True,
    ) -> List[Subject]:
        """
        Return subjects for a given branch + semester.

        This is the auto-load behaviour: after selecting branch + semester,
        the corresponding subjects are loaded automatically.
        """
        norm_branch = normalize_branch(branch)
        return [
            s for s in self._subjects
            if normalize_branch(s.branch) == norm_branch
            and s.semester == semester
            and (not active_only or s.active)
        ]

    def get_workload_for_subject(self, subject_id: str) -> Optional[Workload]:
        """Return the workload entry for a subject, or None."""
        return self._workload_by_subject.get(subject_id)

    def has_workload_row(self, subject_id: str) -> bool:
        """Return True if the subject has a workload row in master data."""
        return subject_id in self._workload_by_subject

    def get_subjects_with_workloads(
        self,
        branch: str,
        semester: int,
    ) -> List[Tuple[Subject, Optional[Workload]]]:
        """
        Return (subject, workload) pairs for a branch + semester.

        Convenience method that joins subjects with their workloads in
        a single call.
        """
        subjects = self.get_subjects(branch, semester)
        return [
            (s, self._workload_by_subject.get(s.subject_id))
            for s in subjects
        ]

    # ------------------------------------------------------------------
    # Teacher filters
    # ------------------------------------------------------------------

    def get_teachers(
        self,
        department: Optional[str] = None,
        active_only: bool = True,
    ) -> List[Teacher]:
        """
        Return teachers, optionally filtered by department.

        Args:
            department: If given, only teachers from this department.
            active_only: If True (default), only active teachers.
        """
        return [
            t for t in self._teachers
            if (department is None or t.department == department)
            and (not active_only or t.active)
        ]

    def get_teacher(self, teacher_id: str) -> Optional[Teacher]:
        """Look up a teacher by ID."""
        return self._teacher_by_id.get(teacher_id)

    def get_eligible_teachers(
        self,
        branch: str,
        semester: Optional[int] = None,
        subject_id: Optional[str] = None,
        activity_type: Optional[ActivityType] = None,
        active_only: bool = True,
    ) -> List[Teacher]:
        """
        Return teachers eligible for a timetable context.

        Eligibility rules, applied in order (first match wins per teacher):

        1. **Subject-specific eligibility** -- if ``subject_id`` is given and
           the subject has an explicit eligible-teacher mapping (a future
           master-data extension; none exists in the current data), only
           those teachers are returned.
        2. **Same-department** -- teachers whose home department equals the
           timetable ``branch`` (normalized, e.g. ``CE`` -> ``Civil``).
        3. **Shared-service departments** -- teachers from departments in
           :data:`SHARED_SERVICE_DEPARTMENTS` (Applied Science, Workshop),
           which teach common subjects for every branch.

        Args:
            branch:        Timetable branch code, e.g. ``CSE``, ``CE``, ``Civil``.
            semester:      Selected semester (optional context).
            subject_id:    Selected subject (optional context).
            activity_type: Selected activity (optional context).
            active_only:   If True (default), only active teachers.
        """
        del activity_type  # reserved for future activity-based eligibility
        del semester       # context parameter for cascading filtering

        norm_branch = normalize_branch(branch)
        explicit = self.get_subject_teacher_eligibility(subject_id) if subject_id else None
        if explicit is not None:
            return [
                t for t in self._teachers
                if t.teacher_id in explicit
                and (not active_only or t.active)
            ]

        return [
            t for t in self._teachers
            if (normalize_branch(t.department) == norm_branch or t.department in SHARED_SERVICE_DEPARTMENTS)
            and (not active_only or t.active)
        ]

    def get_subject_teacher_eligibility(
        self,
        subject_id: str,
    ) -> Optional[frozenset]:
        """
        Return the explicit set of eligible teacher IDs for a subject, or
        ``None`` when no subject-specific eligibility source exists.

        Hook for a future ``TeacherSubjectEligibility`` master file.  The
        current master data contains no such mapping, so this returns
        ``None`` and callers fall back to the department-based rules in
        :meth:`get_eligible_teachers`.  Do NOT invent mappings here.
        """
        return None

    # ------------------------------------------------------------------
    # Room filters  (cascading by activity type + branch)
    # ------------------------------------------------------------------

    def get_rooms_for_activity(
        self,
        activity_type: ActivityType,
        branch: Optional[str] = None,
        active_only: bool = True,
    ) -> List[Room]:
        """
        Return rooms valid for a given activity type, applying cascading rules:

        - ``LECTURE``   --> rooms with room_type LECTURE
        - ``PRACTICAL`` --> rooms with room_type LAB **and** room.branch == branch
        - ``WORKSHOP``  --> rooms with room_type WORKSHOP (shared)
        - ``DRAWING``   --> rooms with room_type DRAWING_HALL (shared)

        Args:
            activity_type: The activity being scheduled.
            branch: Required for PRACTICAL (selects branch-specific labs).
            active_only: If True (default), only rooms marked active.
        """
        valid_room_types = ACTIVITY_ROOM_MAP.get(activity_type, [])

        result = []
        for r in self._rooms:
            if active_only and not r.active:
                continue
            if not isinstance(r.room_type, RoomType):
                continue
            if r.room_type not in valid_room_types:
                continue

            # For LAB rooms, filter by branch
            if r.room_type == RoomType.LAB and branch and r.branch != branch:
                continue

            result.append(r)

        return result

    def get_rooms_by_type(
        self,
        room_type: RoomType,
        branch: Optional[str] = None,
        active_only: bool = True,
    ) -> List[Room]:
        """
        Return rooms filtered by room_type directly.

        For LAB rooms, optionally filter by branch.
        """
        result = []
        for r in self._rooms:
            if active_only and not r.active:
                continue
            if not isinstance(r.room_type, RoomType):
                continue
            if r.room_type != room_type:
                continue
            if room_type == RoomType.LAB and branch and r.branch != branch:
                continue
            result.append(r)
        return result

    def get_room(self, room_id: str) -> Optional[Room]:
        """Look up a room by ID."""
        return self._room_by_id.get(room_id)

    def get_subject(self, subject_id: str) -> Optional[Subject]:
        """Look up a subject by ID."""
        return self._subject_by_id.get(subject_id)

    # ------------------------------------------------------------------
    # Activity type helpers
    # ------------------------------------------------------------------

    def get_valid_room_types_for_activity(
        self,
        activity_type: ActivityType,
    ) -> List[RoomType]:
        """Return the room types valid for a given activity type."""
        return list(ACTIVITY_ROOM_MAP.get(activity_type, []))

    def get_activity_types(self) -> List[ActivityType]:
        """Return all activity types that can be assigned."""
        return [
            ActivityType.LECTURE,
            ActivityType.PRACTICAL,
            ActivityType.WORKSHOP,
            ActivityType.DRAWING,
        ]
