"""
Timetable scheduling engine.

Provides schedule state tracking, conflict detection, session expansion,
slot allocation, soft-constraint scoring, and the main scheduler.
"""

from app.engine.state import ScheduleState
from app.engine.conflicts import (
    ConflictType,
    Conflict,
    ConflictReport,
    check_teacher_overlap,
    check_room_overlap,
    check_section_overlap,
    check_group_overlap,
    check_room_type_validity,
    check_room_branch_validity,
    check_consecutive_slots,
    check_g1_g2_sync,
    is_valid_assignment,
)
from app.engine.expander import ScheduleRequest, expand_assignments, pair_g1_g2
from app.engine.slot_allocator import SlotAllocator, SchedulerConfig
from app.engine.scoring import (
    TimetableScorer,
    ScoreReport,
    ScoringWeights,
    SoftPenalty,
    DayTracker,
)
from app.engine.scheduler import (
    TimetableScheduler,
    ScheduleResult,
    UnscheduledSession,
)

__all__ = [
    # State
    "ScheduleState",
    # Conflict detection
    "ConflictType",
    "Conflict",
    "ConflictReport",
    "check_teacher_overlap",
    "check_room_overlap",
    "check_section_overlap",
    "check_group_overlap",
    "check_room_type_validity",
    "check_room_branch_validity",
    "check_consecutive_slots",
    "check_g1_g2_sync",
    "is_valid_assignment",
    # Expander
    "ScheduleRequest",
    "expand_assignments",
    "pair_g1_g2",
    # Slot allocator
    "SlotAllocator",
    "SchedulerConfig",
    # Scoring
    "TimetableScorer",
    "ScoreReport",
    "ScoringWeights",
    "SoftPenalty",
    "DayTracker",
    # Scheduler
    "TimetableScheduler",
    "ScheduleResult",
    "UnscheduledSession",
]
