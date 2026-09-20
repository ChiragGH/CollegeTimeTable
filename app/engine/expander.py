"""
Assignment-to-session expander.

Converts :class:`Assignment` objects (which describe weekly workload)
into individual :class:`ScheduleRequest` objects (each representing one
session to be placed in the timetable).

Also handles G1/G2 pairing so that parallel practical groups are
scheduled together.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.models.assignment import Assignment
from app.models.enums import ActivityType


@dataclass
class ScheduleRequest:
    """
    One session to be placed in the timetable.

    A single Assignment with ``sessions_per_week=3`` expands into three
    ScheduleRequests, one for each session of the week.

    Attributes:
        request_id:    Unique ID, e.g. ``SR0001``.
        assignment:    The parent Assignment.
        block_size:    Number of consecutive slots this session occupies.
        session_index: 1-based index (which session of the week: 1, 2, 3...).
    """
    request_id: str
    assignment: Assignment
    block_size: int
    session_index: int


def expand_assignments(assignments: List[Assignment]) -> List[ScheduleRequest]:
    """
    Expand assignments into individual session requests.

    Each Assignment specifies a weekly workload (e.g., 3 lectures/week).
    This function creates one ScheduleRequest per session.

    Args:
        assignments: List of teaching assignments.

    Returns:
        List of ScheduleRequests, one per session to schedule.

    Example::

        # Assignment with sessions_per_week=3, block_size=1
        # → 3 ScheduleRequests, each for 1 slot

        # Assignment with sessions_per_week=1, block_size=2
        # → 1 ScheduleRequest for 2 consecutive slots
    """
    requests: List[ScheduleRequest] = []
    counter = 0

    for a in assignments:
        if a.sessions_per_week <= 0:
            continue

        for i in range(1, a.sessions_per_week + 1):
            counter += 1
            requests.append(ScheduleRequest(
                request_id=f"SR{counter:04d}",
                assignment=a,
                block_size=a.block_size,
                session_index=i,
            ))

    return requests


def pair_g1_g2(
    requests: List[ScheduleRequest],
) -> Tuple[
    List[Tuple[ScheduleRequest, ScheduleRequest]],
    List[ScheduleRequest],
]:
    """
    Pair G1/G2 requests that must be placed simultaneously.

    For each subject-section combination, if both G1 and G2 have
    matching sessions (same activity type and session index), they
    are paired.  Unpaired requests are returned separately.

    Returns:
        A tuple of (paired_requests, unpaired_requests).
    """
    # Build index: (subject_id, section, activity_type, session_index) → group → request
    index: Dict[
        Tuple[str, str, ActivityType, int],
        Dict[str, ScheduleRequest],
    ] = {}

    for req in requests:
        a = req.assignment
        # Only non-ALL, non-lecture groups can be paired
        if a.group == "ALL" or a.activity_type == ActivityType.LECTURE:
            continue

        key = (a.subject_id, a.section, a.activity_type, req.session_index)
        if key not in index:
            index[key] = {}
        index[key][a.group] = req

    # Extract pairs
    pairs: List[Tuple[ScheduleRequest, ScheduleRequest]] = []
    paired_ids = set()

    for key, groups in index.items():
        if "G1" in groups and "G2" in groups:
            pairs.append((groups["G1"], groups["G2"]))
            paired_ids.add(groups["G1"].request_id)
            paired_ids.add(groups["G2"].request_id)

    # Everything not paired is a single request
    unpaired = [r for r in requests if r.request_id not in paired_ids]

    return pairs, unpaired


def sort_by_difficulty(
    pairs: List[Tuple[ScheduleRequest, ScheduleRequest]],
    singles: List[ScheduleRequest],
) -> Tuple[
    List[Tuple[ScheduleRequest, ScheduleRequest]],
    List[ScheduleRequest],
]:
    """
    Sort requests by scheduling difficulty (most constrained first).

    Priority order:
    1. Paired G1/G2 practicals (need 2 rooms simultaneously)
    2. Large blocks (block_size > 1) — harder to fit
    3. Practicals/workshops/drawing (specific room types)
    4. Lectures (most flexible — many rooms available)

    Within each category, larger blocks come first.
    """
    # Sort pairs by block size descending
    pairs_sorted = sorted(pairs, key=lambda p: -p[0].block_size)

    # Sort singles: larger blocks first (since they require contiguous slots),
    # without artificial activity-type discrimination.
    def _single_priority(req: ScheduleRequest) -> int:
        return -req.block_size

    singles_sorted = sorted(singles, key=_single_priority)

    return pairs_sorted, singles_sorted
