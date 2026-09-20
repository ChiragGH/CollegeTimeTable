"""
Timetable scheduling engine.

Constraint-based scheduler that places teaching assignments into the
weekly time grid using **seeded random valid placement**.  Its only
jobs are to schedule the full required workload and to guarantee zero
hard-constraint clashes — it performs NO soft-constraint optimisation
and applies NO placement preference (no morning/afternoon bias, no
lecture-vs-practical priority, no gap/spacing/load tuning, no room
preference unless one is explicitly required).

Strategy:
    1. Expand assignments into individual session requests
    2. Pair G1/G2 practicals for simultaneous placement
    3. Order by difficulty (larger blocks first) purely for solver
       correctness — most-constrained-first — never for preference,
       then shuffle within equal-difficulty buckets using the seed
    4. For each request, enumerate ALL valid candidates (slots + room)
       and pick one at RANDOM among them (never a scored "best")
    5. Use seeded randomized restart to reach a complete workload:
       retry with derived seeds and keep the first complete, zero-clash
       timetable (else the most-complete attempt)
    6. Report any unscheduled sessions with detailed reasons

Reproducible per seed (default 12345); different seeds yield different
valid timetables.  A post-hoc :class:`ScoreReport` is still produced
for reporting only — it is NEVER consulted for any placement decision.
"""

import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.models.room import Room
from app.models.assignment import Assignment
from app.models.slot import TimeSlot
from app.models.placement import Placement
from app.models.enums import Day
from app.engine.state import ScheduleState
from app.engine.expander import (
    ScheduleRequest,
    expand_assignments,
    pair_g1_g2,
    sort_by_difficulty,
)
from app.engine.slot_allocator import SlotAllocator, SchedulerConfig
from app.engine.scoring import (
    TimetableScorer,
    ScoreReport,
    ScoringWeights,
)


def _shuffle_equal_blocks(items: List[Any], rng: random.Random) -> List[Any]:
    """Group items by block size and shuffle within each equal-size bucket."""
    by_size = defaultdict(list)
    for it in items:
        req = it[0] if isinstance(it, tuple) else it
        by_size[req.block_size].append(it)
    result = []
    for size in sorted(by_size.keys(), reverse=True):
        bucket = list(by_size[size])
        rng.shuffle(bucket)
        result.extend(bucket)
    return result


# ====================================================================
# Result types
# ====================================================================

@dataclass
class UnscheduledSession:
    """
    A session that could not be placed in the timetable.

    Provides structured information about what failed and why,
    so the user can take corrective action.
    """
    request_id: str
    assignment_id: str
    subject_id: str
    teacher_id: str
    section: str
    group: str
    activity_type: str
    session_index: int
    block_size: int
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "assignment_id": self.assignment_id,
            "subject_id": self.subject_id,
            "teacher_id": self.teacher_id,
            "section": self.section,
            "group": self.group,
            "activity_type": self.activity_type,
            "session_index": self.session_index,
            "block_size": self.block_size,
            "reasons": self.reasons,
        }


@dataclass
class ScheduleResult:
    """
    Output of the scheduling engine.

    Attributes:
        placements:    Successfully placed sessions.
        unscheduled:   Sessions that could not be placed, with reasons.
        score_report:  Soft-constraint quality evaluation.
        stats:         Summary statistics.
    """
    placements: List[Placement] = field(default_factory=list)
    unscheduled: List[UnscheduledSession] = field(default_factory=list)
    score_report: Optional[ScoreReport] = None
    stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        """True if every session was successfully placed."""
        return len(self.unscheduled) == 0

    @property
    def score(self) -> float:
        """Quality score 0--100 (100 = perfect)."""
        return self.score_report.total_score if self.score_report else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_complete": self.is_complete,
            "placed_count": len(self.placements),
            "unscheduled_count": len(self.unscheduled),
            "score": round(self.score, 1),
            "score_report": self.score_report.to_dict() if self.score_report else None,
            "unscheduled": [u.to_dict() for u in self.unscheduled],
            "stats": self.stats,
        }


# ====================================================================
# Scheduler
# ====================================================================

DEFAULT_SEED = 12345


class TimetableScheduler:
    """
    Seeded random-valid-placement timetable scheduler.

    For each session request the scheduler enumerates ALL valid
    placements (those that violate no hard constraint) and picks one at
    **random** — never a scored "best".  A seeded randomized restart
    then retries with derived seeds until the full workload is placed
    with zero clashes, keeping the most-complete attempt if a perfect
    one is not found.

    The result carries a post-hoc :class:`ScoreReport` for reporting
    only; it is never used to choose a placement.

    Usage::

        rooms_dict = {r.room_id: r for r in rooms}
        scheduler = TimetableScheduler(rooms=rooms_dict)
        result = scheduler.schedule(assignments)          # seed 12345
        other = scheduler.schedule(assignments, seed=99)  # different timetable

    Args:
        rooms:        Dict of room_id → Room.
        config:       Optional SchedulerConfig for grid/behaviour settings.
        weights:      Optional ScoringWeights (report only, not placement).
        seed:         Base random seed; defaults to ``DEFAULT_SEED`` when
                      neither this nor the ``schedule`` argument is set.
        max_attempts: Seeded randomized-restart budget for reaching a
                      complete, zero-clash timetable.
    """

    def __init__(
        self,
        rooms: Dict[str, Room],
        config: Optional[SchedulerConfig] = None,
        weights: Optional[ScoringWeights] = None,
        seed: Optional[int] = None,
        max_attempts: int = 40,
    ):
        self.rooms = rooms
        self.config = config or SchedulerConfig()
        self.allocator = SlotAllocator(rooms, self.config)
        self.scorer = TimetableScorer(weights)
        self.seed = seed
        self.max_attempts = max(1, max_attempts)
        self._placement_counter = 0

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def schedule(
        self,
        assignments: List[Assignment],
        seed: Optional[int] = None,
    ) -> ScheduleResult:
        """
        Schedule all assignments with seeded random valid placement.

        Runs up to ``max_attempts`` seeded attempts; the first complete,
        zero-clash attempt wins, otherwise the most-complete is returned
        with structured reasons for every unscheduled session.  Ordering
        is most-constrained-first for solver correctness only — it
        carries no morning/afternoon or activity-type preference.

        Args:
            assignments: Teaching assignments from the setup.
            seed:        Optional base seed; falls back to ``DEFAULT_SEED``.
        """
        effective_seed = seed if seed is not None else self.seed
        if effective_seed is None:
            effective_seed = DEFAULT_SEED

        all_requests = expand_assignments(assignments)
        total_sessions = len(all_requests)
        pairs, singles = pair_g1_g2(all_requests)
        pairs, singles = sort_by_difficulty(pairs, singles)

        best_result: Optional[ScheduleResult] = None
        attempts_used = 0
        for attempt in range(self.max_attempts):
            attempts_used = attempt + 1
            rng = random.Random(effective_seed + attempt)
            result = self._attempt_schedule(pairs, singles, rng)
            if result.is_complete:
                best_result = result
                break
            if (best_result is None
                    or len(result.placements) > len(best_result.placements)):
                best_result = result

        # Post-hoc quality report (NOT used for any placement decision).
        best_result.score_report = self.scorer.score_timetable(
            best_result.placements
        )
        best_result.stats = self._compute_stats(total_sessions, best_result)
        best_result.stats["seed"] = effective_seed
        best_result.stats["attempts_used"] = attempts_used
        return best_result

    # ------------------------------------------------------------------
    # One placement attempt
    # ------------------------------------------------------------------

    def _attempt_schedule(
        self,
        pairs,
        singles,
        rng: random.Random,
    ) -> ScheduleResult:
        """Run one full placement attempt with the given RNG."""
        state = ScheduleState()
        self._placement_counter = 0
        result = ScheduleResult()

        # Shuffle within equal-difficulty buckets; order carries no
        # preference, it only lets different seeds explore differently.
        for g1_req, g2_req in _shuffle_equal_blocks(pairs, rng):
            self._schedule_pair(g1_req, g2_req, state, result, rng)
        for req in _shuffle_equal_blocks(singles, rng):
            self._schedule_single(req, state, result, rng)

        return result

    # ------------------------------------------------------------------
    # Single session placement (random valid)
    # ------------------------------------------------------------------

    def _schedule_single(
        self,
        request: ScheduleRequest,
        state: ScheduleState,
        result: ScheduleResult,
        rng: random.Random,
    ) -> bool:
        """Place a single session at a RANDOM valid candidate."""
        valid = self.allocator.find_valid_placements(request, state, rng=rng)
        if valid:
            slots, room_id = rng.choice(valid)
            placement = self._create_placement(request, slots, room_id)
            state.add_placement(placement)
            result.placements.append(placement)
            return True
        reasons = self.allocator.get_failure_reasons(request, state)
        result.unscheduled.append(self._create_unscheduled(request, reasons))
        return False

    # ------------------------------------------------------------------
    # Paired G1/G2 placement (random valid)
    # ------------------------------------------------------------------

    def _schedule_pair(
        self,
        g1_request: ScheduleRequest,
        g2_request: ScheduleRequest,
        state: ScheduleState,
        result: ScheduleResult,
        rng: random.Random,
    ) -> bool:
        """
        Place a G1/G2 pair at a RANDOM valid candidate.

        Both groups take the same slots in different rooms; the pair is
        placed together so their parallel alignment (C6) always holds.
        """
        valid = self.allocator.find_valid_paired_placements(
            g1_request, g2_request, state, rng=rng,
        )
        if valid:
            slots, g1_room, g2_room = rng.choice(valid)
            g1_placement = self._create_placement(g1_request, slots, g1_room)
            g2_placement = self._create_placement(g2_request, slots, g2_room)
            state.add_placement(g1_placement)
            state.add_placement(g2_placement)
            result.placements.append(g1_placement)
            result.placements.append(g2_placement)
            return True
        reasons = self.allocator.get_paired_failure_reasons(
            g1_request, g2_request, state,
        )
        result.unscheduled.append(self._create_unscheduled(g1_request, reasons))
        result.unscheduled.append(self._create_unscheduled(g2_request, reasons))
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_placement(
        self,
        request: ScheduleRequest,
        slots: List[TimeSlot],
        room_id: str,
    ) -> Placement:
        """Create a Placement object for a successfully scheduled session."""
        self._placement_counter += 1
        return Placement(
            placement_id=f"P{self._placement_counter:04d}",
            assignment=request.assignment,
            slots=slots,
            room_id=room_id,
        )

    @staticmethod
    def _create_unscheduled(
        request: ScheduleRequest,
        reasons: List[str],
    ) -> UnscheduledSession:
        """Create an UnscheduledSession with diagnostic info."""
        a = request.assignment
        return UnscheduledSession(
            request_id=request.request_id,
            assignment_id=a.assignment_id,
            subject_id=a.subject_id,
            teacher_id=a.teacher_id,
            section=a.section,
            group=a.group,
            activity_type=a.activity_type.value,
            session_index=request.session_index,
            block_size=request.block_size,
            reasons=reasons,
        )

    def _compute_stats(
        self,
        total_sessions: int,
        result: ScheduleResult,
    ) -> Dict[str, Any]:
        """Compute summary statistics for the schedule result."""
        placed = len(result.placements)
        unscheduled = len(result.unscheduled)

        # Teacher utilisation
        teacher_periods: Dict[str, int] = {}
        for p in result.placements:
            tid = p.assignment.teacher_id
            teacher_periods[tid] = teacher_periods.get(tid, 0) + len(p.slots)

        # Room utilisation
        room_periods: Dict[str, int] = {}
        for p in result.placements:
            room_periods[p.room_id] = room_periods.get(p.room_id, 0) + len(p.slots)

        total_slots = (
            len(self.config.days) * self.config.periods_per_day
        )

        return {
            "total_sessions": total_sessions,
            "placed": placed,
            "unscheduled": unscheduled,
            "completion_rate": (
                round(placed / total_sessions * 100, 1)
                if total_sessions > 0 else 100.0
            ),
            "total_weekly_slots": total_slots,
            "teacher_count": len(teacher_periods),
            "room_count": len(room_periods),
            "avg_teacher_periods": (
                round(sum(teacher_periods.values()) / len(teacher_periods), 1)
                if teacher_periods else 0
            ),
        }
