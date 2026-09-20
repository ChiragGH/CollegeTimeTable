"""
Timetable quality scoring system.

Evaluates a complete timetable against soft constraints and provides
both a full-timetable score (for reporting) and a fast candidate-level
score (for the scheduler to pick the *best* valid slot).

Soft constraints (ARCHITECTURE.md §3.5, S1--S3 extended):

    S1  Subject distribution   -- Spread each subject across different days
    S2  Consecutive classes    -- Avoid excessive back-to-back for a section
    S3  Teacher daily load     -- Avoid overloading a teacher on one day
    S4  Section gaps           -- Avoid free periods between scheduled ones
    S5  Practical organisation -- Prefer clean block starts (slot 1, 3, 5)
    S6  Room preference        -- Prefer the configured/preferred room

Hard constraints are NEVER relaxed.  The scorer only evaluates quality
*within* the space of valid timetables.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.models.enums import ActivityType, Day
from app.models.placement import Placement
from app.models.slot import TimeSlot
from app.engine.state import ScheduleState


# ====================================================================
# Configuration
# ====================================================================

@dataclass
class ScoringWeights:
    """
    Weights for each soft constraint.  Higher weight = more influence.
    All weights are positive; the scorer subtracts weighted penalties
    from a perfect score of 100.
    """
    subject_distribution: float = 20.0
    consecutive_classes: float = 15.0
    teacher_daily_load: float = 15.0
    section_gaps: float = 20.0
    practical_organisation: float = 10.0
    room_preference: float = 20.0

    # Thresholds
    max_teacher_periods_per_day: int = 6
    max_consecutive_per_section: int = 4


# ====================================================================
# Day tracker — incremental per-day statistics
# ====================================================================

class DayTracker:
    """
    Maintains per-day usage statistics for O(1) candidate scoring.

    Updated incrementally as placements are added/removed.
    """

    def __init__(self):
        # teacher_id → day → period count
        self.teacher_day_count: Dict[str, Dict[Day, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        # section → day → sorted set of period numbers
        self.section_day_periods: Dict[str, Dict[Day, Set[int]]] = defaultdict(
            lambda: defaultdict(set)
        )
        # (subject_id, section) → set of days with a session
        self.subject_section_days: Dict[Tuple[str, str], Set[Day]] = defaultdict(set)

    def add_placement(self, p: Placement) -> None:
        a = p.assignment
        day = p.slots[0].day
        period_count = len(p.slots)

        self.teacher_day_count[a.teacher_id][day] += period_count
        for s in p.slots:
            self.section_day_periods[a.section][s.day].add(s.period)
        self.subject_section_days[(a.subject_id, a.section)].add(day)

    def remove_placement(self, p: Placement) -> None:
        a = p.assignment
        day = p.slots[0].day
        period_count = len(p.slots)

        self.teacher_day_count[a.teacher_id][day] = max(
            0, self.teacher_day_count[a.teacher_id][day] - period_count
        )
        for s in p.slots:
            self.section_day_periods[a.section][s.day].discard(s.period)
        # Note: can't reliably remove from subject_section_days without
        # re-scanning placements, so we leave it (conservative).

    def teacher_periods_on_day(self, teacher_id: str, day: Day) -> int:
        return self.teacher_day_count[teacher_id][day]

    def section_periods_on_day(self, section: str, day: Day) -> Set[int]:
        return self.section_day_periods[section][day]

    def subject_days(self, subject_id: str, section: str) -> Set[Day]:
        return self.subject_section_days[(subject_id, section)]


# ====================================================================
# Penalty data structures
# ====================================================================

@dataclass
class SoftPenalty:
    """One soft-constraint evaluation result."""
    name: str
    description: str
    weight: float
    raw_penalty: float          # 0.0 = perfect, higher = worse
    weighted_penalty: float     # raw_penalty * weight (normalised)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "raw_penalty": round(self.raw_penalty, 3),
            "weighted_penalty": round(self.weighted_penalty, 3),
        }


@dataclass
class ScoreReport:
    """
    Complete quality evaluation of a timetable.

    Attributes:
        total_score:         0--100, higher is better.
        penalties:           Breakdown per soft constraint.
        hard_violation_count: Must be 0 for a valid timetable.
    """
    total_score: float
    penalties: List[SoftPenalty] = field(default_factory=list)
    hard_violation_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_score": round(self.total_score, 1),
            "hard_violation_count": self.hard_violation_count,
            "penalties": [p.to_dict() for p in self.penalties],
        }


# ====================================================================
# Full-timetable scorer
# ====================================================================

class TimetableScorer:
    """
    Evaluates timetable quality via soft constraints.

    Two modes of operation:

    1. **Full scoring** -- :meth:`score_timetable` evaluates a complete
       schedule and returns a :class:`ScoreReport` with per-penalty
       breakdown.  Used for final reporting.

    2. **Candidate scoring** -- :meth:`score_candidate` quickly evaluates
       a proposed placement against the current state.  Used by the
       scheduler to pick the *best* valid slot.
    """

    def __init__(self, weights: Optional[ScoringWeights] = None):
        self.weights = weights or ScoringWeights()

    # ------------------------------------------------------------------
    # Full timetable scoring
    # ------------------------------------------------------------------

    def score_timetable(
        self,
        placements: List[Placement],
    ) -> ScoreReport:
        """
        Score a complete timetable.

        Returns a :class:`ScoreReport` with total score (0--100)
        and per-penalty breakdown.
        """
        if not placements:
            return ScoreReport(total_score=100.0)

        penalties = [
            self._score_subject_distribution(placements),
            self._score_consecutive_classes(placements),
            self._score_teacher_daily_load(placements),
            self._score_section_gaps(placements),
            self._score_practical_organisation(placements),
            self._score_room_preference(placements),
        ]

        total_weighted = sum(p.weighted_penalty for p in penalties)
        total_score = max(0.0, 100.0 - total_weighted)

        return ScoreReport(
            total_score=total_score,
            penalties=penalties,
            hard_violation_count=0,
        )

    # ------------------------------------------------------------------
    # Candidate scoring (incremental, fast)
    # ------------------------------------------------------------------

    def score_candidate(
        self,
        candidate_slots: List[TimeSlot],
        candidate_room: str,
        request_assignment,
        tracker: DayTracker,
    ) -> float:
        """
        Score a single candidate placement incrementally.

        Returns a penalty value (lower = better, 0 = ideal).
        Used by the scheduler to rank valid candidates.
        """
        a = request_assignment
        day = candidate_slots[0].day
        n_periods = len(candidate_slots)
        penalty = 0.0

        # S1: Subject distribution -- penalise if subject already on this day
        existing_days = tracker.subject_days(a.subject_id, a.section)
        if day in existing_days:
            penalty += 10.0  # Same subject on same day = bad

        # S2: Consecutive classes -- penalise dense section days (lunch breaks the run)
        section_periods = tracker.section_periods_on_day(a.section, day)
        proposed_periods = {s.period for s in candidate_slots}
        combined = section_periods | proposed_periods
        longest_run = _longest_consecutive_run(combined, respect_lunch=True)
        if longest_run > self.weights.max_consecutive_per_section:
            penalty += (longest_run - self.weights.max_consecutive_per_section) * 5.0

        # S3: Teacher daily load -- penalise overloaded days
        teacher_today = tracker.teacher_periods_on_day(a.teacher_id, day)
        new_total = teacher_today + n_periods
        if new_total > self.weights.max_teacher_periods_per_day:
            penalty += (new_total - self.weights.max_teacher_periods_per_day) * 4.0

        # S4: Gaps -- penalise if this creates gaps in section schedule
        if combined:
            gaps = _count_gaps(combined)
            penalty += gaps * 3.0

        # S5: Fair organisation for practicals and lectures (no practical monopoly)
        if a.activity_type in (
            ActivityType.PRACTICAL, ActivityType.WORKSHOP, ActivityType.DRAWING,
        ):
            start_period = candidate_slots[0].period
            # Clean block starts at 1, 3, 5 (periods 1-2, 3-4, 5-6)
            if start_period in (1, 3, 5):
                penalty -= 2.0  # Bonus
            elif start_period in (2, 6):
                penalty += 1.0  # Mild penalty
        elif a.activity_type == ActivityType.LECTURE:
            start_period = candidate_slots[0].period
            # Lectures are welcome and balanced across morning and afternoon
            if start_period in (1, 2, 3, 4):
                penalty -= 1.5  # Bonus for morning lectures
            elif start_period in (5, 6, 7):
                penalty -= 0.5  # Afternoon lecture bonus

        # S6: Room preference -- bonus for preferred room
        if a.room_id:
            if candidate_room == a.room_id:
                penalty -= 3.0  # Bonus for preferred room
            else:
                penalty += 2.0  # Penalty for non-preferred

        # Prefer earlier days (mild tie-breaker for determinism)
        day_order = {Day.MON: 0, Day.TUE: 1, Day.WED: 2, Day.THU: 3, Day.FRI: 4}
        penalty += day_order.get(day, 0) * 0.1

        return penalty

    # ------------------------------------------------------------------
    # Individual full-timetable penalty functions
    # ------------------------------------------------------------------

    def _score_subject_distribution(
        self,
        placements: List[Placement],
    ) -> SoftPenalty:
        """
        S1: Penalise subjects with multiple sessions on the same day.

        Ideal: each session of a subject is on a different day.
        """
        # (subject_id, section) → day → count
        subject_day_count: Dict[Tuple[str, str], Dict[Day, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        subject_session_count: Dict[Tuple[str, str], int] = defaultdict(int)

        for p in placements:
            a = p.assignment
            key = (a.subject_id, a.section)
            day = p.slots[0].day
            subject_day_count[key][day] += 1
            subject_session_count[key] += 1

        raw = 0.0
        for key, day_counts in subject_day_count.items():
            total_sessions = subject_session_count[key]
            if total_sessions <= 1:
                continue
            # Penalty = number of "duplicate day" sessions
            for day, count in day_counts.items():
                if count > 1:
                    raw += count - 1

        # Normalise: divide by total number of placements
        normalised = raw / max(len(placements), 1)

        return SoftPenalty(
            name="subject_distribution",
            description="Spread subjects across different days",
            weight=self.weights.subject_distribution,
            raw_penalty=normalised,
            weighted_penalty=normalised * self.weights.subject_distribution,
        )

    def _score_consecutive_classes(
        self,
        placements: List[Placement],
    ) -> SoftPenalty:
        """
        S2: Penalise excessive consecutive periods for a section.

        Threshold: max_consecutive_per_section (default 4).
        """
        # section → day → set of periods
        section_day_periods: Dict[str, Dict[Day, Set[int]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for p in placements:
            for s in p.slots:
                section_day_periods[p.assignment.section][s.day].add(s.period)

        raw = 0.0
        threshold = self.weights.max_consecutive_per_section

        for section, day_periods in section_day_periods.items():
            for day, periods in day_periods.items():
                longest = _longest_consecutive_run(periods, respect_lunch=True)
                if longest > threshold:
                    raw += longest - threshold

        total_section_days = sum(
            len(dp) for dp in section_day_periods.values()
        )
        normalised = raw / max(total_section_days, 1)

        return SoftPenalty(
            name="consecutive_classes",
            description=f"Avoid more than {threshold} consecutive periods per section",
            weight=self.weights.consecutive_classes,
            raw_penalty=normalised,
            weighted_penalty=normalised * self.weights.consecutive_classes,
        )

    def _score_teacher_daily_load(
        self,
        placements: List[Placement],
    ) -> SoftPenalty:
        """
        S3: Penalise teachers with too many periods on a single day.

        Threshold: max_teacher_periods_per_day (default 6).
        """
        # teacher → day → period count
        teacher_day_count: Dict[str, Dict[Day, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        for p in placements:
            for s in p.slots:
                teacher_day_count[p.assignment.teacher_id][s.day] += 1

        raw = 0.0
        threshold = self.weights.max_teacher_periods_per_day

        for teacher, day_counts in teacher_day_count.items():
            for day, count in day_counts.items():
                if count > threshold:
                    raw += count - threshold

        total_teacher_days = sum(
            len(dc) for dc in teacher_day_count.values()
        )
        normalised = raw / max(total_teacher_days, 1)

        return SoftPenalty(
            name="teacher_daily_load",
            description=f"Avoid more than {threshold} periods per teacher per day",
            weight=self.weights.teacher_daily_load,
            raw_penalty=normalised,
            weighted_penalty=normalised * self.weights.teacher_daily_load,
        )

    def _score_section_gaps(
        self,
        placements: List[Placement],
    ) -> SoftPenalty:
        """
        S4: Penalise gaps (free periods between scheduled ones) per section-day.

        A gap is an unscheduled period between two scheduled periods
        on the same day.
        """
        section_day_periods: Dict[str, Dict[Day, Set[int]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for p in placements:
            for s in p.slots:
                section_day_periods[p.assignment.section][s.day].add(s.period)

        raw = 0.0
        for section, day_periods in section_day_periods.items():
            for day, periods in day_periods.items():
                raw += _count_gaps(periods)

        total_section_days = sum(
            len(dp) for dp in section_day_periods.values()
        )
        normalised = raw / max(total_section_days, 1)

        return SoftPenalty(
            name="section_gaps",
            description="Minimise free-period gaps within a section's daily schedule",
            weight=self.weights.section_gaps,
            raw_penalty=normalised,
            weighted_penalty=normalised * self.weights.section_gaps,
        )

    def _score_practical_organisation(
        self,
        placements: List[Placement],
    ) -> SoftPenalty:
        """
        S5: Prefer practical blocks at clean starting positions.

        Clean starts: period 1, 3, 5 (aligns with 2-period blocks).
        Penalise starts at period 2, 6 (misaligned).
        """
        practical_count = 0
        raw = 0.0

        for p in placements:
            if p.assignment.activity_type not in (
                ActivityType.PRACTICAL, ActivityType.WORKSHOP, ActivityType.DRAWING,
            ):
                continue

            practical_count += 1
            start = p.slots[0].period
            if start in (1, 3, 5):
                pass  # Ideal position, no penalty
            elif start in (2, 6):
                raw += 0.5  # Misaligned
            else:
                raw += 1.0

        normalised = raw / max(practical_count, 1)

        return SoftPenalty(
            name="practical_organisation",
            description="Prefer clean block starts (periods 1, 3, 5) for practicals",
            weight=self.weights.practical_organisation,
            raw_penalty=normalised,
            weighted_penalty=normalised * self.weights.practical_organisation,
        )

    def _score_room_preference(
        self,
        placements: List[Placement],
    ) -> SoftPenalty:
        """
        S6: Penalise when a preferred room was specified but not assigned.
        """
        with_pref = 0
        matched = 0

        for p in placements:
            if p.assignment.room_id:
                with_pref += 1
                if p.room_id == p.assignment.room_id:
                    matched += 1

        if with_pref == 0:
            normalised = 0.0
        else:
            normalised = (with_pref - matched) / with_pref

        return SoftPenalty(
            name="room_preference",
            description="Honour preferred room assignments",
            weight=self.weights.room_preference,
            raw_penalty=normalised,
            weighted_penalty=normalised * self.weights.room_preference,
        )


# ====================================================================
# Helper functions
# ====================================================================

def _longest_consecutive_run(periods: Set[int], respect_lunch: bool = False) -> int:
    """
    Find the longest run of consecutive integers in a set.

    If respect_lunch is True, a run is broken across the lunch break (between 4 and 5).
    Example: {1, 2, 3, 5, 6} → longest run is 3 (periods 1, 2, 3).
    """
    if not periods:
        return 0

    sorted_p = sorted(periods)
    longest = 1
    current = 1

    for i in range(1, len(sorted_p)):
        if sorted_p[i] == sorted_p[i - 1] + 1:
            if respect_lunch and sorted_p[i - 1] == 4 and sorted_p[i] == 5:
                current = 1
            else:
                current += 1
            longest = max(longest, current)
        else:
            current = 1

    return longest


def _count_gaps(periods: Set[int]) -> int:
    """
    Count gaps (missing periods) between min and max of the set.

    Gaps across the lunch break (between period 4 and 5) are NOT
    counted as gaps since lunch is a natural break.

    Example: {1, 2, 4} → 1 gap (period 3 missing)
    Example: {3, 4, 5, 6} → 0 gaps (4→5 lunch gap not counted)
    """
    if len(periods) <= 1:
        return 0

    sorted_p = sorted(periods)
    gaps = 0

    for i in range(len(sorted_p) - 1):
        curr = sorted_p[i]
        nxt = sorted_p[i + 1]
        if nxt - curr > 1:
            # Don't count the lunch break as a gap
            if curr == 4 and nxt == 5:
                continue
            gaps += nxt - curr - 1

    return gaps
