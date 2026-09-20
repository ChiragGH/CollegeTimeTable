"""
Assignment manager for timetable setup.

Creates and validates teaching assignments (teacher-subject-section
mappings).  Implements validation rules V-A1 through V-A6 from
DATA_SCHEMA.md §6.2.

Important: teacher-subject mappings are **transient** -- they belong
to the current timetable setup, NOT permanent master data.
"""

from typing import Dict, List, Optional, Tuple

from app.models.teacher import Teacher
from app.models.room import Room
from app.models.section import Section
from app.models.subject import Subject
from app.models.workload import Workload
from app.models.assignment import Assignment
from app.models.session import TimetableSetup
from app.models.enums import ActivityType, RoomType
from app.models.branch import normalize_branch
from app.data.validators import ValidationError, ValidationResult, Severity
from app.setup.filters import SetupFilters, ACTIVITY_ROOM_MAP


# Default block sizes (from PROJECT_SPEC.md §8)
DEFAULT_BLOCK_SIZES = {
    ActivityType.LECTURE:   1,
    ActivityType.PRACTICAL: 2,
    ActivityType.WORKSHOP:  3,
    ActivityType.DRAWING:   3,
}

# Workload master-data source per activity type.  Workloads.xlsx carries
# one lecture column and one practical column per subject; WORKSHOP /
# DRAWING / PROJECT / TRAINING have no workload source in the current
# data model, so assignments of those types cannot be substantiated
# (they resolve to 0 periods/week and are rejected at creation time).
WORKLOAD_FIELD_BY_ACTIVITY = {
    ActivityType.LECTURE:   "lecture_periods_per_week",
    ActivityType.PRACTICAL: "practical_periods_per_week",
}

# Activity candidates in the order auto-assignment considers them.
AUTO_ACTIVITY_ORDER = (ActivityType.LECTURE, ActivityType.PRACTICAL)

VALID_GROUPS = frozenset({"G1", "G2", "ALL"})


class AssignmentManager:
    """
    Creates and validates teaching assignments for a timetable setup.

    Provides:

    - Assignment creation with auto-computed block_size and sessions_per_week
    - Cascading room filtering via :class:`SetupFilters`
    - Full validation against DATA_SCHEMA.md §6.2 rules

    Args:
        filters: A :class:`SetupFilters` instance loaded with master data.
    """

    def __init__(self, filters: SetupFilters):
        self.filters = filters

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_assignment(
        self,
        setup: TimetableSetup,
        teacher_id: str,
        subject_id: str,
        section: str,
        group: str,
        activity_type: ActivityType,
        weekly_periods: int,
        room_id: Optional[str] = None,
        room_type: Optional[RoomType] = None,
        block_size: Optional[int] = None,
    ) -> Assignment:
        """
        Create a new assignment and add it to the setup.

        Args:
            setup:           The parent timetable setup.
            teacher_id:      FK to Teachers.xlsx, e.g. ``T001``.
            subject_id:      FK to Subjects.xlsx, e.g. ``SUB042``.
            section:         Section label, e.g. ``A``.
            group:           ``G1``, ``G2``, or ``ALL``.
            activity_type:   LECTURE, PRACTICAL, WORKSHOP, or DRAWING.
            weekly_periods:  Total periods per week for this assignment.
            room_id:         Optional preferred room ID.
            room_type:       Optional preferred room type for filtering.
            block_size:      Consecutive periods per session.
                             Defaults to activity-type-specific value.

        Returns:
            The newly created :class:`Assignment`.

        Raises:
            ValueError: If ``block_size`` does not divide ``weekly_periods``
                        (an inconsistent block config must never be stored).
        """
        # Derive the assignment ID from the IDs already present in the
        # setup so re-adding after a delete can never collide.
        existing_ids = {a.assignment_id for a in setup.assignments}
        n = 1
        while f"A{n:03d}" in existing_ids:
            n += 1
        assignment_id = f"A{n:03d}"

        # Default block_size from activity type
        if block_size is None:
            block_size = DEFAULT_BLOCK_SIZES.get(activity_type, 1)

        # Compute sessions_per_week -- must divide exactly, otherwise the
        # scheduled slots would silently disagree with weekly_periods.
        if block_size <= 0:
            raise ValueError(f"block_size must be >= 1, got {block_size}.")
        if weekly_periods > 0 and weekly_periods % block_size != 0:
            raise ValueError(
                f"block_size {block_size} does not divide weekly_periods "
                f"{weekly_periods}; use a compatible block size."
            )
        sessions_per_week = weekly_periods // block_size if weekly_periods > 0 else 0

        # Infer room_type from activity_type if not specified
        if room_type is None:
            valid_types = ACTIVITY_ROOM_MAP.get(activity_type, [])
            if valid_types:
                room_type = valid_types[0]

        assignment = Assignment(
            assignment_id=assignment_id,
            session_id=setup.session_id,
            teacher_id=teacher_id,
            subject_id=subject_id,
            branch=setup.branch,
            semester=setup.semester,
            section=section,
            group=group,
            activity_type=activity_type,
            weekly_periods=weekly_periods,
            room_id=room_id,
            room_type=room_type,
            block_size=block_size,
            sessions_per_week=sessions_per_week,
        )

        setup.assignments.append(assignment)
        return assignment

    def remove_assignment(
        self,
        setup: TimetableSetup,
        assignment_id: str,
    ) -> bool:
        """
        Remove an assignment from the setup by its ID.

        Returns True if removed, False if not found.
        """
        for i, a in enumerate(setup.assignments):
            if a.assignment_id == assignment_id:
                setup.assignments.pop(i)
                return True
        return False

    # ------------------------------------------------------------------
    # Convenience: auto-create assignments from workload
    # ------------------------------------------------------------------

    def create_assignments_from_workload(
        self,
        setup: TimetableSetup,
        subject_id: str,
        section: str,
        teacher_id_lecture: Optional[str] = None,
        teacher_id_practical: Optional[str] = None,
        group: str = "ALL",
        practical_group: Optional[str] = None,
    ) -> List[Assignment]:
        """
        Auto-create assignments from a subject's workload.

        If the workload has lecture periods > 0, creates a LECTURE assignment.
        If it has practical periods > 0, creates a PRACTICAL assignment.

        Args:
            setup:                The parent setup.
            subject_id:           Subject to assign.
            section:              Section label.
            teacher_id_lecture:   Teacher for the lecture component (if any).
            teacher_id_practical: Teacher for the practical component (if any).
            group:                Group for lectures (usually ``ALL``).
            practical_group:      Group for practicals (e.g. ``G1``).

        Returns:
            List of created assignments.
        """
        workload = self.filters.get_workload_for_subject(subject_id)
        if workload is None:
            return []

        created = []

        # Lecture component
        if workload.lecture_periods_per_week > 0 and teacher_id_lecture:
            a = self.create_assignment(
                setup=setup,
                teacher_id=teacher_id_lecture,
                subject_id=subject_id,
                section=section,
                group="ALL",
                activity_type=ActivityType.LECTURE,
                weekly_periods=workload.lecture_periods_per_week,
            )
            created.append(a)

        # Practical component
        if workload.practical_periods_per_week > 0 and teacher_id_practical:
            block_size, _ = self.compute_block_config(
                ActivityType.PRACTICAL, workload.practical_periods_per_week
            )
            a = self.create_assignment(
                setup=setup,
                teacher_id=teacher_id_practical,
                subject_id=subject_id,
                section=section,
                group=practical_group or "G1",
                activity_type=ActivityType.PRACTICAL,
                weekly_periods=workload.practical_periods_per_week,
                block_size=block_size,
            )
            created.append(a)

        return created

    # ------------------------------------------------------------------
    # Workload-derived fields (master workload is the source of truth)
    # ------------------------------------------------------------------

    def get_workload_for_activity(
        self,
        subject_id: str,
        activity_type: ActivityType,
    ) -> int:
        """
        Return the master workload periods per week for one activity type.

        Reads the authoritative workload column for the activity
        (:data:`WORKLOAD_FIELD_BY_ACTIVITY`).  Returns 0 when the subject
        has no workload row or the activity has no workload source in the
        current data model (WORKSHOP / DRAWING / ...).
        """
        field = WORKLOAD_FIELD_BY_ACTIVITY.get(activity_type)
        if field is None:
            return 0
        workload = self.filters.get_workload_for_subject(subject_id)
        if workload is None:
            return 0
        value = getattr(workload, field, None)
        return value if isinstance(value, int) and value > 0 else 0

    def compute_block_config(
        self,
        activity_type: ActivityType,
        weekly_periods: int,
    ) -> Tuple[int, int]:
        """
        Compute a valid (block_size, sessions_per_week) pair for a workload.

        Starts from the activity's default block size; if it does not
        divide the weekly periods, falls back to block size 1 (single
        periods) so a valid configuration is always produced.  Returns
        ``(0, 0)`` when ``weekly_periods`` is not positive.

        Future mixed block patterns (e.g. 2+1) can hook in here without
        changing callers.
        """
        if weekly_periods <= 0:
            return (0, 0)
        block_size = DEFAULT_BLOCK_SIZES.get(activity_type, 1)
        if weekly_periods % block_size != 0:
            block_size = 1
        return (block_size, weekly_periods // block_size)

    def get_assigned_periods(
        self,
        setup: TimetableSetup,
        subject_id: str,
        activity_type: ActivityType,
        section: str,
        group: str,
    ) -> int:
        """
        Sum weekly periods already assigned for one
        (subject, activity, section, group) slot in a setup.

        Capacity is tracked per group: parallel G1/G2 practicals each
        consume the subject's full practical workload (the scheduler
        places them in parallel via ``pair_g1_g2``), while lectures use
        ``group='ALL'``.
        """
        return sum(
            a.weekly_periods
            for a in setup.assignments
            if a.subject_id == subject_id
            and a.activity_type == activity_type
            and a.section == section
            and a.group == group
        )

    def get_remaining_periods(
        self,
        setup: TimetableSetup,
        subject_id: str,
        activity_type: ActivityType,
        section: str,
        group: str,
    ) -> int:
        """Master workload minus already-assigned periods for one slot."""
        required = self.get_workload_for_activity(subject_id, activity_type)
        assigned = self.get_assigned_periods(
            setup, subject_id, activity_type, section, group
        )
        return required - assigned

    # ------------------------------------------------------------------
    # Section distribution helpers (used by Auto Add)
    # ------------------------------------------------------------------

    def _section_load(self, setup: TimetableSetup) -> Dict[str, int]:
        """Total weekly periods already assigned per section label.

        Auto Add uses this to spread packages across sections (least
        loaded first) instead of always filling Section A — an
        ``A=full / B=empty`` split is an invalid timetable.
        """
        load: Dict[str, int] = {}
        for a in setup.assignments:
            load[a.section] = load.get(a.section, 0) + a.weekly_periods
        return load

    def _sections_least_loaded_first(
        self, setup: TimetableSetup
    ) -> List[Section]:
        """Configured sections ordered by current load (ascending), with
        configured order as the deterministic tie-break — a round-robin
        in effect across repeated auto-adds."""
        load = self._section_load(setup)
        return [
            s for _, s in sorted(
                enumerate(setup.sections),
                key=lambda it: (load.get(it[1].label, 0), it[0]),
            )
        ]

    def _subject_has_remaining(
        self,
        setup: TimetableSetup,
        subj: Subject,
        sec: Section,
    ) -> bool:
        """True if ``subj`` still owes lecture or practical workload in
        section ``sec`` (practicals are tracked per group)."""
        lec = self.get_workload_for_activity(subj.subject_id, ActivityType.LECTURE)
        prac = self.get_workload_for_activity(subj.subject_id, ActivityType.PRACTICAL)
        if lec <= 0 and prac <= 0:
            return False
        groups = sec.groups or ["G1", "G2"]
        lec_assigned = self.get_assigned_periods(
            setup, subj.subject_id, ActivityType.LECTURE, sec.label, "ALL"
        )
        check_group = "G1" if "G1" in groups else "ALL"
        prac_assigned = self.get_assigned_periods(
            setup, subj.subject_id, ActivityType.PRACTICAL, sec.label, check_group
        )
        return lec_assigned < lec or prac_assigned < prac

    # ------------------------------------------------------------------
    # Validated assignment creation (workload-driven, used by the web API)
    # ------------------------------------------------------------------

    def prepare_assignment(
        self,
        setup: TimetableSetup,
        teacher_id: str,
        subject_id: str,
        section: str,
        group: str,
        activity_type: ActivityType,
        block_size: Optional[int] = None,
        room_id: Optional[str] = None,
        room_type: Optional[RoomType] = None,
    ) -> Tuple[Optional[Assignment], List[str]]:
        """
        Validate one assignment request against master data and derive the
        workload-driven fields.

        ``weekly_periods`` is intentionally NOT a parameter: it is always
        derived from the master workload for the selected subject +
        activity, so it cannot be overridden from the outside.

        Checks performed:

        - teacher exists, is active, and is eligible for the branch
        - subject exists and belongs to the setup's branch + semester
        - the activity has a non-zero master workload for the subject
        - group rules (lectures must be ``ALL``)
        - block size divides the weekly periods
        - capacity: the assignment must not exceed the master workload for
          its (subject, activity, section, group) slot
        - preferred room (if given) exists, is active, and fits the activity

        Returns:
            ``(Assignment, [])`` on success, ``(None, [messages...])`` on
            validation failure.  Never raises for validation problems.
        """
        errors: List[str] = []

        # --- Subject: exists and matches the session context ---
        subject = self.filters.get_subject(subject_id)
        if subject is None:
            errors.append(f"Subject '{subject_id}' not found in Subjects.xlsx.")
        else:
            if normalize_branch(subject.branch) != normalize_branch(setup.branch) or subject.semester != setup.semester:
                errors.append(
                    f"Subject '{subject_id}' belongs to {subject.branch} semester "
                    f"{subject.semester}, but this session is "
                    f"{setup.branch} semester {setup.semester}."
                )
            if not subject.active:
                errors.append(f"Subject '{subject_id}' is not active.")

        # --- Teacher: exists, active, eligible for this branch context ---
        teacher = self.filters.get_teacher(teacher_id)
        if teacher is None:
            errors.append(f"Teacher '{teacher_id}' not found in Teachers.xlsx.")
        elif not teacher.active:
            errors.append(f"Teacher '{teacher_id}' ({teacher.teacher_name}) is not active.")
        else:
            eligible = self.filters.get_eligible_teachers(
                setup.branch, semester=setup.semester, subject_id=subject_id, activity_type=activity_type
            )
            if teacher not in eligible:
                errors.append(
                    f"Teacher '{teacher_id}' ({teacher.teacher_name}, {teacher.department}) "
                    f"is not eligible for a {setup.branch} timetable."
                )

        # --- Section exists in the setup ---
        section_obj = next(
            (s for s in setup.sections if s.label == section), None
        )
        if section_obj is None:
            labels = [s.label for s in setup.sections] or ["(none configured)"]
            errors.append(
                f"Section '{section}' is not configured in this session. "
                f"Available sections: {labels}."
            )

        # --- Group rules ---
        if group not in VALID_GROUPS:
            errors.append(
                f"Invalid group '{group}'. Must be one of: {sorted(VALID_GROUPS)}."
            )
        elif activity_type == ActivityType.LECTURE and group != "ALL":
            errors.append(
                f"Lecture assignments must use group 'ALL', got '{group}'."
            )
        elif (
            activity_type != ActivityType.LECTURE
            and group != "ALL"
            and section_obj is not None
            and group not in section_obj.groups
        ):
            errors.append(
                f"Group '{group}' is not configured for section '{section}' "
                f"(configured groups: {section_obj.groups})."
            )

        # --- Workload: master data is the source of truth ---
        weekly_periods = self.get_workload_for_activity(subject_id, activity_type)
        if weekly_periods <= 0:
            if self.filters.has_workload_row(subject_id):
                errors.append(
                    f"No {activity_type.value.lower()} workload exists for subject "
                    f"'{subject_id}' in the master data; the assignment cannot "
                    f"be created."
                )
            else:
                errors.append(
                    f"No workload exists for subject '{subject_id}' in the "
                    f"master data; the assignment cannot be created."
                )
            return None, errors

        # --- Capacity: never exceed the master workload for this slot ---
        assigned = self.get_assigned_periods(
            setup, subject_id, activity_type, section, group
        )
        if assigned + weekly_periods > weekly_periods:
            errors.append(
                f"Assignment would exceed the subject's configured workload: "
                f"{assigned} of {weekly_periods} {activity_type.value.lower()} "
                f"periods/week already assigned for section '{section}' "
                f"group '{group}'."
            )
            return None, errors

        # --- Block configuration ---
        if block_size is not None and block_size <= 0:
            errors.append(f"Block size must be >= 1, got {block_size}.")
            return None, errors
        if block_size is not None and weekly_periods % block_size != 0:
            errors.append(
                f"Block size {block_size} x sessions per week does not equal "
                f"weekly periods ({weekly_periods}); choose a block size that "
                f"divides {weekly_periods}."
            )
            return None, errors

        # --- Preferred room: optional, but must fit if given ---
        if room_id:
            room = self.filters.get_room(room_id)
            if room is None:
                errors.append(f"Room '{room_id}' not found in Rooms.xlsx.")
            elif not room.active:
                errors.append(f"Room '{room_id}' ({room.room_name}) is not active.")
            elif isinstance(room.room_type, RoomType):
                valid_types = ACTIVITY_ROOM_MAP.get(activity_type, [])
                if valid_types and room.room_type not in valid_types:
                    errors.append(
                        f"Room '{room_id}' has type {room.room_type.value}, but "
                        f"{activity_type.value} requires "
                        f"{[rt.value for rt in valid_types]}."
                    )

        if errors:
            return None, errors

        if block_size is None:
            block_size = DEFAULT_BLOCK_SIZES.get(activity_type, 1)

        assignment = self.create_assignment(
            setup=setup,
            teacher_id=teacher_id,
            subject_id=subject_id,
            section=section,
            group=group,
            activity_type=activity_type,
            weekly_periods=weekly_periods,
            room_id=room_id,
            room_type=room_type,
            block_size=block_size,
        )
        return assignment, []

    # ------------------------------------------------------------------
    # Auto Add Test Assignment (development/testing utility)
    # ------------------------------------------------------------------

    def auto_create_assignment(
        self,
        setup: TimetableSetup,
    ) -> Tuple[Optional[Assignment], str]:
        """
        Create ONE valid teaching assignment from the setup context.

        Development/testing utility: picks the next valid candidate via
        :meth:`auto_pick_assignment` and creates it immediately.
        Repeated calls walk through the remaining valid combinations
        instead of duplicating the same assignment.

        Returns:
            ``(assignment, description)`` when one was created, or
            ``(None, reason)`` when nothing could be created.
        """
        candidate, description = self.auto_pick_assignment(setup)
        if candidate is None:
            return None, description

        assignment, errors = self.prepare_assignment(setup=setup, **candidate)
        if assignment is None:
            return None, "; ".join(errors)
        return assignment, description

    def auto_create_package(
        self,
        setup: TimetableSetup,
        subject_id: Optional[str] = None,
        section: Optional[str] = None,
    ) -> Tuple[List[Assignment], str]:
        """
        Create a COMPLETE test assignment package for one subject.

        One click creates the full workload package:
        - Lecture assignment (if lecture workload > 0)
        - G1 and G2 parallel practical assignments (if practical workload > 0)
          using distinct eligible teachers when available
        - Preserves master workload values without double-counting

        Returns:
            ``(assignments, message)``
        """
        subjects = sorted(
            self.filters.get_subjects(setup.branch, setup.semester),
            key=lambda s: s.subject_id,
        )
        if not subjects:
            return [], f"No subjects found for {setup.branch} semester {setup.semester}."

        # Choose the section(s) to consider.  An explicit section is
        # honoured as-is; otherwise packages are distributed across
        # sections least-loaded-first (never always Section A).
        if section:
            explicit = next(
                (s for s in setup.sections if s.label == section), None
            )
            if explicit is None:
                labels = [s.label for s in setup.sections] or ["(none configured)"]
                return [], (
                    f"Section '{section}' is not configured in this session. "
                    f"Available sections: {labels}."
                )
            candidate_sections = [explicit]
        elif setup.sections:
            candidate_sections = self._sections_least_loaded_first(setup)
        else:
            candidate_sections = [
                Section(branch=setup.branch, semester=setup.semester, label="A")
            ]

        teacher_load: Dict[str, int] = {}
        for a in setup.assignments:
            teacher_load[a.teacher_id] = teacher_load.get(a.teacher_id, 0) + a.weekly_periods

        # Find the first (section, subject) pair with remaining workload,
        # walking sections in least-loaded order so coverage spreads.
        sec = candidate_sections[0]
        target_subj = None
        if subject_id:
            lookup = self.filters.get_subject(subject_id)
            if not lookup:
                return [], f"Subject '{subject_id}' not found."
            for cand in candidate_sections:
                if self._subject_has_remaining(setup, lookup, cand):
                    sec, target_subj = cand, lookup
                    break
            if target_subj is None:
                # Requested subject fully assigned everywhere considered.
                sec = candidate_sections[0]
        else:
            for cand in candidate_sections:
                for subj in subjects:
                    if self._subject_has_remaining(setup, subj, cand):
                        sec, target_subj = cand, subj
                        break
                if target_subj is not None:
                    break

        if target_subj is None:
            scope = (
                f"section '{section}'" if section
                else f"any configured section ({', '.join(s.label for s in candidate_sections)})"
            )
            return [], (
                f"All subjects for {setup.branch} semester {setup.semester} "
                f"are already assigned in {scope}."
            )

        lec_periods = self.get_workload_for_activity(target_subj.subject_id, ActivityType.LECTURE)
        prac_periods = self.get_workload_for_activity(target_subj.subject_id, ActivityType.PRACTICAL)
        created: List[Assignment] = []

        # 1. Lecture Assignment
        if lec_periods > 0:
            assigned = self.get_assigned_periods(setup, target_subj.subject_id, ActivityType.LECTURE, sec.label, "ALL")
            if assigned < lec_periods:
                eligible_lec = self.filters.get_eligible_teachers(
                    setup.branch, semester=setup.semester, subject_id=target_subj.subject_id, activity_type=ActivityType.LECTURE
                )
                if not eligible_lec:
                    return [], f"No eligible teachers for {target_subj.subject_name} lecture."
                t_lec = min(eligible_lec, key=lambda t: (teacher_load.get(t.teacher_id, 0), t.teacher_id))
                block_size, _ = self.compute_block_config(ActivityType.LECTURE, lec_periods)
                a_lec = self.create_assignment(
                    setup=setup,
                    teacher_id=t_lec.teacher_id,
                    subject_id=target_subj.subject_id,
                    section=sec.label,
                    group="ALL",
                    activity_type=ActivityType.LECTURE,
                    weekly_periods=lec_periods,
                    block_size=block_size,
                )
                created.append(a_lec)
                teacher_load[t_lec.teacher_id] = teacher_load.get(t_lec.teacher_id, 0) + lec_periods

        # 2. Practical Assignment(s)
        if prac_periods > 0:
            block_size, _ = self.compute_block_config(ActivityType.PRACTICAL, prac_periods)
            eligible_prac = self.filters.get_eligible_teachers(
                setup.branch, semester=setup.semester, subject_id=target_subj.subject_id, activity_type=ActivityType.PRACTICAL
            )
            if not eligible_prac:
                return [], f"No eligible teachers for {target_subj.subject_name} practical."

            groups = sec.groups or ["G1", "G2"]
            if "G1" in groups and "G2" in groups:
                eligible_sorted = sorted(eligible_prac, key=lambda t: (teacher_load.get(t.teacher_id, 0), t.teacher_id))
                t_g1 = eligible_sorted[0]
                t_g2 = eligible_sorted[1] if len(eligible_sorted) > 1 else eligible_sorted[0]

                if self.get_assigned_periods(setup, target_subj.subject_id, ActivityType.PRACTICAL, sec.label, "G1") < prac_periods:
                    a_g1 = self.create_assignment(
                        setup=setup,
                        teacher_id=t_g1.teacher_id,
                        subject_id=target_subj.subject_id,
                        section=sec.label,
                        group="G1",
                        activity_type=ActivityType.PRACTICAL,
                        weekly_periods=prac_periods,
                        block_size=block_size,
                    )
                    created.append(a_g1)
                    teacher_load[t_g1.teacher_id] = teacher_load.get(t_g1.teacher_id, 0) + prac_periods

                if self.get_assigned_periods(setup, target_subj.subject_id, ActivityType.PRACTICAL, sec.label, "G2") < prac_periods:
                    a_g2 = self.create_assignment(
                        setup=setup,
                        teacher_id=t_g2.teacher_id,
                        subject_id=target_subj.subject_id,
                        section=sec.label,
                        group="G2",
                        activity_type=ActivityType.PRACTICAL,
                        weekly_periods=prac_periods,
                        block_size=block_size,
                    )
                    created.append(a_g2)
                    teacher_load[t_g2.teacher_id] = teacher_load.get(t_g2.teacher_id, 0) + prac_periods
            else:
                if self.get_assigned_periods(setup, target_subj.subject_id, ActivityType.PRACTICAL, sec.label, "ALL") < prac_periods:
                    t_prac = min(eligible_prac, key=lambda t: (teacher_load.get(t.teacher_id, 0), t.teacher_id))
                    a_prac = self.create_assignment(
                        setup=setup,
                        teacher_id=t_prac.teacher_id,
                        subject_id=target_subj.subject_id,
                        section=sec.label,
                        group="ALL",
                        activity_type=ActivityType.PRACTICAL,
                        weekly_periods=prac_periods,
                        block_size=block_size,
                    )
                    created.append(a_prac)
                    teacher_load[t_prac.teacher_id] = teacher_load.get(t_prac.teacher_id, 0) + prac_periods

        if not created:
            return [], f"Subject '{target_subj.subject_name}' is already assigned in section '{sec.label}'."

        groups_str = "G1 + G2" if ("G1" in (sec.groups or []) and "G2" in (sec.groups or []) and prac_periods > 0) else "ALL"
        msg = (
            f"Test package added:\n"
            f"{target_subj.subject_name}\n"
            f"Lecture: {lec_periods} periods/week\n"
            f"Practical: {prac_periods} periods/week\n"
            f"Groups: {groups_str}\n"
            f"Assignments created: {len(created)}"
        )
        return created, msg

    def auto_pick_assignment(
        self,
        setup: TimetableSetup,
    ) -> Tuple[Optional[Dict[str, object]], str]:
        """
        Find the next valid auto-assignment candidate WITHOUT creating it.

        Candidates are considered in this order:

        1. sections least-loaded first (spreading coverage across all
           configured sections; default section ``A`` when the session
           has none yet)
        2. subjects for the branch + semester, ordered by subject_id
        3. activities: LECTURE before PRACTICAL (activities without a
           master workload source are skipped, never invented)
        4. groups: ALL for lectures, then the section's groups (G1, G2)
           for practicals

        The teacher is the least-loaded (total weekly periods) eligible
        teacher, tie-broken by teacher ID for determinism.

        Returns:
            ``(candidate_dict, description)`` where the candidate dict can
            be passed straight to :meth:`prepare_assignment`
            (``**candidate``), or ``(None, reason)`` when no valid
            candidate remains.  Used by auto-add and the frontend
            "Auto Fill" preview.
        """
        # Walk sections least-loaded-first so repeated auto-adds spread
        # coverage across all sections rather than filling Section A.
        if setup.sections:
            sections = self._sections_least_loaded_first(setup)
        else:
            sections = [
                Section(branch=setup.branch, semester=setup.semester, label="A")
            ]

        subjects = sorted(
            self.filters.get_subjects(setup.branch, setup.semester),
            key=lambda s: s.subject_id,
        )
        if not subjects:
            return None, (
                f"No subjects found for {setup.branch} semester "
                f"{setup.semester} in the master data."
            )

        # Teacher load (weekly periods) for least-loaded selection.
        teacher_load: Dict[str, int] = {}
        for a in setup.assignments:
            teacher_load[a.teacher_id] = (
                teacher_load.get(a.teacher_id, 0) + a.weekly_periods
            )

        for sec in sections:
            for subj in subjects:
                for activity in AUTO_ACTIVITY_ORDER:
                    weekly_periods = self.get_workload_for_activity(
                        subj.subject_id, activity
                    )
                    if weekly_periods <= 0:
                        continue  # no workload for this activity -- skip, never invent
                    groups = (
                        ["ALL"]
                        if activity == ActivityType.LECTURE
                        else (sec.groups or ["G1", "G2"])
                    )
                    for group in groups:
                        assigned = self.get_assigned_periods(
                            setup, subj.subject_id, activity, sec.label, group
                        )
                        if assigned >= weekly_periods:
                            continue  # fully assigned -- move to the next candidate

                        eligible = self.filters.get_eligible_teachers(
                            setup.branch,
                            semester=setup.semester,
                            subject_id=subj.subject_id,
                            activity_type=activity,
                        )
                        if not eligible:
                            continue  # no eligible teacher -- try the next candidate

                        teacher = min(
                            eligible,
                            key=lambda t: (
                                teacher_load.get(t.teacher_id, 0), t.teacher_id
                            ),
                        )
                        block_size, _ = self.compute_block_config(
                            activity, weekly_periods
                        )
                        activity_label = (
                            "Lecture" if activity == ActivityType.LECTURE
                            else activity.value.title()
                        )
                        description = (
                            f"{setup.branch}-SEM{setup.semester}-{sec.label}"
                            f"{'/' + group if group != 'ALL' else ''}: "
                            f"{subj.subject_code} {subj.subject_name} — "
                            f"{activity_label}, {weekly_periods} periods/week, "
                            f"teacher {teacher.teacher_name}"
                        )
                        candidate: Dict[str, object] = {
                            "teacher_id": teacher.teacher_id,
                            "subject_id": subj.subject_id,
                            "section": sec.label,
                            "group": group,
                            "activity_type": activity,
                            "block_size": block_size,
                        }
                        return candidate, description

        return None, (
            f"All subject/activity combinations for {setup.branch} semester "
            f"{setup.semester} are already assigned. No further auto "
            f"assignments can be created."
        )

    # ------------------------------------------------------------------
    # Workload status (per subject, for the UI remaining-workload view)
    # ------------------------------------------------------------------

    def get_workload_status(
        self,
        setup: TimetableSetup,
        section: str,
        group: str,
    ) -> List[Dict[str, object]]:
        """
        Per-subject workload status for one section/group of a setup.

        Returns a list ordered by subject_id::

            [
                {
                    "subject_id": "SUB016",
                    "subject_code": "3.3",
                    "subject_name": "Digital Electronics",
                    "lecture":   {"required": 3, "assigned": 0, "remaining": 3},
                    "practical": {"required": 4, "assigned": 0, "remaining": 4},
                },
                ...
            ]

        ``assigned`` counts the periods already assigned for exactly this
        section (and group, for practicals; lectures use ``ALL``).
        """
        status: List[Dict[str, object]] = []
        for subj in sorted(
            self.filters.get_subjects(setup.branch, setup.semester),
            key=lambda s: s.subject_id,
        ):
            lecture_assigned = self.get_assigned_periods(
                setup, subj.subject_id, ActivityType.LECTURE, section, "ALL"
            )
            practical_assigned = self.get_assigned_periods(
                setup, subj.subject_id, ActivityType.PRACTICAL, section, group
            )
            practical_required = self.get_workload_for_activity(
                subj.subject_id, ActivityType.PRACTICAL
            )
            status.append({
                "subject_id": subj.subject_id,
                "subject_code": subj.subject_code,
                "subject_name": subj.subject_name,
                "short_name": getattr(subj, "short_name", "") or subj.subject_code,
                "lecture": {
                    "required": self.get_workload_for_activity(
                        subj.subject_id, ActivityType.LECTURE
                    ),
                    "assigned": lecture_assigned,
                    "remaining": self.get_workload_for_activity(
                        subj.subject_id, ActivityType.LECTURE
                    ) - lecture_assigned,
                },
                "practical": {
                    "required": practical_required,
                    "assigned": practical_assigned,
                    "remaining": practical_required - practical_assigned,
                },
            })
        return status

    # ------------------------------------------------------------------
    # Validation  (DATA_SCHEMA.md §6.2: V-A1 through V-A6)
    # ------------------------------------------------------------------

    def validate_assignments(
        self,
        setup: TimetableSetup,
    ) -> ValidationResult:
        """
        Validate all assignments in a setup against rules V-A1 through V-A6.

        Returns:
            A :class:`ValidationResult` with all findings.
        """
        result = ValidationResult()
        assignments = setup.assignments

        # Build lookup for duplicate checking (V-A5)
        seen_combos: Dict[Tuple[str, str, str], str] = {}

        # Pre-compute per-slot totals for the workload capacity rule (V-A10)
        slot_totals: Dict[Tuple[str, ActivityType, str, str], int] = {}
        for a in assignments:
            key = (a.subject_id, a.activity_type, a.section, a.group)
            slot_totals[key] = slot_totals.get(key, 0) + a.weekly_periods
        flagged_slots = set()

        for a in assignments:
            # V-A1: teacher_id must exist and be active
            teacher = self.filters.get_teacher(a.teacher_id)
            if teacher is None:
                result.add(ValidationError(
                    rule_id="V-A1",
                    severity=Severity.ERROR,
                    entity_type="Assignment",
                    entity_id=a.assignment_id,
                    field="teacher_id",
                    message=f"Teacher '{a.teacher_id}' not found in Teachers.xlsx.",
                ))
            elif not teacher.active:
                result.add(ValidationError(
                    rule_id="V-A1",
                    severity=Severity.ERROR,
                    entity_type="Assignment",
                    entity_id=a.assignment_id,
                    field="teacher_id",
                    message=f"Teacher '{a.teacher_id}' ({teacher.teacher_name}) is not active.",
                ))

            # V-A2: subject_id must exist
            subject = self.filters.get_subject(a.subject_id)
            if subject is None:
                result.add(ValidationError(
                    rule_id="V-A2",
                    severity=Severity.ERROR,
                    entity_type="Assignment",
                    entity_id=a.assignment_id,
                    field="subject_id",
                    message=f"Subject '{a.subject_id}' not found in Subjects.xlsx.",
                ))

            # V-A3: room_id must exist and be active (if specified)
            if a.room_id:
                room = self.filters.get_room(a.room_id)
                if room is None:
                    result.add(ValidationError(
                        rule_id="V-A3",
                        severity=Severity.ERROR,
                        entity_type="Assignment",
                        entity_id=a.assignment_id,
                        field="room_id",
                        message=f"Room '{a.room_id}' not found in Rooms.xlsx.",
                    ))
                elif not room.active:
                    result.add(ValidationError(
                        rule_id="V-A3",
                        severity=Severity.ERROR,
                        entity_type="Assignment",
                        entity_id=a.assignment_id,
                        field="room_id",
                        message=f"Room '{a.room_id}' ({room.room_name}) is not active.",
                    ))
                elif isinstance(room.room_type, RoomType):
                    # Check room type compatibility with activity type
                    valid_types = ACTIVITY_ROOM_MAP.get(a.activity_type, [])
                    if room.room_type not in valid_types:
                        result.add(ValidationError(
                            rule_id="V-A3",
                            severity=Severity.ERROR,
                            entity_type="Assignment",
                            entity_id=a.assignment_id,
                            field="room_id",
                            message=(
                                f"Room '{a.room_id}' has type {room.room_type.value} "
                                f"but activity {a.activity_type.value} requires "
                                f"{[rt.value for rt in valid_types]}."
                            ),
                        ))

            # V-A4: block_size * sessions_per_week must match workload
            if a.activity_type in (ActivityType.PRACTICAL, ActivityType.WORKSHOP, ActivityType.DRAWING):
                workload = self.filters.get_workload_for_subject(a.subject_id)
                if workload is not None:
                    expected = workload.practical_periods_per_week
                    actual = a.block_size * a.sessions_per_week
                    if expected > 0 and actual != expected:
                        result.add(ValidationError(
                            rule_id="V-A4",
                            severity=Severity.WARNING,
                            entity_type="Assignment",
                            entity_id=a.assignment_id,
                            field="block_size",
                            message=(
                                f"block_size({a.block_size}) x sessions_per_week({a.sessions_per_week}) "
                                f"= {actual}, but workload practical periods = {expected}."
                            ),
                        ))

            # V-A5: No duplicate subject-section-group combination
            combo_key = (a.subject_id, a.section, a.group)
            if combo_key in seen_combos:
                result.add(ValidationError(
                    rule_id="V-A5",
                    severity=Severity.ERROR,
                    entity_type="Assignment",
                    entity_id=a.assignment_id,
                    field="subject_id",
                    message=(
                        f"Duplicate assignment: subject '{a.subject_id}' / "
                        f"section '{a.section}' / group '{a.group}' "
                        f"already assigned in {seen_combos[combo_key]}."
                    ),
                ))
            else:
                seen_combos[combo_key] = a.assignment_id

            # V-A6: Lectures must have group = ALL
            if a.activity_type == ActivityType.LECTURE and a.group != "ALL":
                result.add(ValidationError(
                    rule_id="V-A6",
                    severity=Severity.WARNING,
                    entity_type="Assignment",
                    entity_id=a.assignment_id,
                    field="group",
                    message=(
                        f"Lecture activity should have group='ALL', "
                        f"but got '{a.group}'."
                    ),
                ))

            # V-A7: teacher must be eligible for the assignment's branch context
            teacher = self.filters.get_teacher(a.teacher_id)
            if teacher is not None and teacher.active:
                eligible = self.filters.get_eligible_teachers(
                    a.branch, semester=a.semester, subject_id=a.subject_id,
                    activity_type=a.activity_type,
                )
                if teacher not in eligible:
                    result.add(ValidationError(
                        rule_id="V-A7",
                        severity=Severity.ERROR,
                        entity_type="Assignment",
                        entity_id=a.assignment_id,
                        field="teacher_id",
                        message=(
                            f"Teacher '{a.teacher_id}' ({teacher.teacher_name}, "
                            f"{teacher.department}) is not eligible for a "
                            f"{a.branch} timetable."
                        ),
                    ))

            # V-A8: block_size * sessions_per_week must equal weekly_periods
            actual = a.block_size * a.sessions_per_week
            if a.weekly_periods > 0 and actual != a.weekly_periods:
                result.add(ValidationError(
                    rule_id="V-A8",
                    severity=Severity.ERROR,
                    entity_type="Assignment",
                    entity_id=a.assignment_id,
                    field="block_size",
                    message=(
                        f"block_size({a.block_size}) x sessions_per_week"
                        f"({a.sessions_per_week}) = {actual}, but "
                        f"weekly_periods = {a.weekly_periods}."
                    ),
                ))

            # V-A9: weekly_periods must match the master workload for the
            # activity (master workload is the source of truth)
            required = self.get_workload_for_activity(a.subject_id, a.activity_type)
            if required <= 0:
                has_row = self.filters.has_workload_row(a.subject_id)
                detail = (
                    f"No {a.activity_type.value.lower()} workload exists for "
                    f"subject '{a.subject_id}' in the master data."
                    if has_row else
                    f"No workload exists for subject '{a.subject_id}' in the "
                    f"master data."
                )
                result.add(ValidationError(
                    rule_id="V-A9",
                    severity=Severity.ERROR,
                    entity_type="Assignment",
                    entity_id=a.assignment_id,
                    field="activity_type",
                    message=detail,
                ))
            elif a.weekly_periods != required:
                result.add(ValidationError(
                    rule_id="V-A9",
                    severity=Severity.ERROR,
                    entity_type="Assignment",
                    entity_id=a.assignment_id,
                    field="weekly_periods",
                    message=(
                        f"weekly_periods({a.weekly_periods}) does not match the "
                        f"master {a.activity_type.value.lower()} workload "
                        f"({required}) for subject '{a.subject_id}'."
                    ),
                ))

            # V-A10: total assigned periods per (subject, activity, section,
            # group) slot must not exceed the master workload
            if required > 0:
                slot_key = (a.subject_id, a.activity_type, a.section, a.group)
                if (
                    slot_totals[slot_key] > required
                    and slot_key not in flagged_slots
                ):
                    flagged_slots.add(slot_key)
                    result.add(ValidationError(
                        rule_id="V-A10",
                        severity=Severity.ERROR,
                        entity_type="Assignment",
                        entity_id=a.assignment_id,
                        field="weekly_periods",
                        message=(
                            f"Assignments for subject '{a.subject_id}' / "
                            f"{a.activity_type.value} / section '{a.section}' / "
                            f"group '{a.group}' total {slot_totals[slot_key]} "
                            f"periods/week, exceeding the master workload of "
                            f"{required}."
                        ),
                    ))

            # Additional: valid group value
            if a.group not in VALID_GROUPS:
                result.add(ValidationError(
                    rule_id="V-A0",
                    severity=Severity.ERROR,
                    entity_type="Assignment",
                    entity_id=a.assignment_id,
                    field="group",
                    message=(
                        f"Invalid group '{a.group}'. "
                        f"Must be one of: {sorted(VALID_GROUPS)}."
                    ),
                ))

            # Additional: weekly_periods must be positive
            if a.weekly_periods <= 0:
                result.add(ValidationError(
                    rule_id="V-A0",
                    severity=Severity.ERROR,
                    entity_type="Assignment",
                    entity_id=a.assignment_id,
                    field="weekly_periods",
                    message=f"Weekly periods must be > 0, got {a.weekly_periods}.",
                ))

            # Additional: section must exist in setup
            section_labels = {s.label for s in setup.sections}
            if a.section not in section_labels:
                result.add(ValidationError(
                    rule_id="V-A0",
                    severity=Severity.ERROR,
                    entity_type="Assignment",
                    entity_id=a.assignment_id,
                    field="section",
                    message=(
                        f"Section '{a.section}' not found in session. "
                        f"Available: {sorted(section_labels)}."
                    ),
                ))

        return result

    # ------------------------------------------------------------------
    # Summary helpers
    # ------------------------------------------------------------------

    def get_workload_summary(
        self,
        setup: TimetableSetup,
    ) -> Dict[str, Dict[str, int]]:
        """
        Summarize assigned vs required periods per subject.

        Returns a dict keyed by subject_id with::

            {
                "SUB042": {
                    "subject_name": "Data Structures",
                    "lecture_required": 4,
                    "practical_required": 2,
                    "lecture_assigned": 4,
                    "practical_assigned": 2,
                }
            }
        """
        summary: Dict[str, Dict[str, int]] = {}

        # Get all subjects for this branch-semester
        subjects = self.filters.get_subjects(setup.branch, setup.semester)

        for subj in subjects:
            wl = self.filters.get_workload_for_subject(subj.subject_id)
            entry: Dict[str, int] = {
                "subject_name": subj.subject_name,
                "lecture_required": wl.lecture_periods_per_week if wl else 0,
                "practical_required": wl.practical_periods_per_week if wl else 0,
                "lecture_assigned": 0,
                "practical_assigned": 0,
            }
            summary[subj.subject_id] = entry

        # Tally assignments
        for a in setup.assignments:
            if a.subject_id in summary:
                if a.activity_type == ActivityType.LECTURE:
                    summary[a.subject_id]["lecture_assigned"] += a.weekly_periods
                else:
                    summary[a.subject_id]["practical_assigned"] += a.weekly_periods

        return summary
