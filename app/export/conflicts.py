"""
Timetable conflict audit.

An **independent** re-check of the hard constraints (C1--C3, C6 from
SCHEDULING_RULES.md) run over the final placements.  The export layer
treats this as its "no hidden conflicts" guarantee:

* every conflict found is flagged **inline** on the offending grid
  cells in all views, and
* every export carries a full conflict report (CSV block / XLSX sheet /
  PDF page).

Detected conflict types:

* ``TEACHER``  — one teacher, two activities, same day+period   (C1)
* ``ROOM``     — one room, two activities, same day+period      (C2)
* ``SECTION``  — a section/group is double-booked               (C3)
* ``PARALLEL`` — G1/G2 practicals of the same subject-section
                 that were *both* scheduled but are not aligned (C6)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Set, Tuple

from app.models.placement import Placement
from app.models.slot import TimeSlot
from app.engine.state import ScheduleState


@dataclass
class Conflict:
    """One concrete constraint violation between placements."""

    conflict_type: str          # TEACHER | ROOM | SECTION | PARALLEL
    entity_id: str              # teacher_id / room_id / section / section
    day: str                    # Day name, e.g. ``MON``; PARALLEL uses ``*``
    period: int                 # 0 when spanning (PARALLEL)
    placement_a: str
    placement_b: str            # '' for PARALLEL (may involve many)
    description: str

    @property
    def severity(self) -> str:
        return "ERROR"

    def to_dict(self) -> dict:
        return {
            "type": self.conflict_type,
            "entity_id": self.entity_id,
            "day": self.day,
            "period": self.period,
            "placement_a": self.placement_a,
            "placement_b": self.placement_b,
            "description": self.description,
        }


@dataclass
class ConflictReport:
    """Result of the full audit, plus lookup indexes for renderers."""

    conflicts: List[Conflict] = field(default_factory=list)
    unscheduled: List[dict] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.conflicts

    def count_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for c in self.conflicts:
            counts[c.conflict_type] = counts.get(c.conflict_type, 0) + 1
        return counts

    def conflicts_for(self, entity_kind: str, entity_id: str) -> List[Conflict]:
        """
        Conflicts relevant to one view entity.

        ``entity_kind`` is one of ``teacher``, ``room``, ``section``.
        Section-kind conflicts (SECTION/PARALLEL) attach to every
        section touched by the conflict.
        """
        result = []
        for c in self.conflicts:
            if entity_kind == "teacher" and c.conflict_type == "TEACHER":
                if c.entity_id == entity_id:
                    result.append(c)
            elif entity_kind == "room" and c.conflict_type == "ROOM":
                if c.entity_id == entity_id:
                    result.append(c)
            elif entity_kind == "section" and c.conflict_type in (
                "SECTION", "PARALLEL",
            ):
                if entity_id in c.entity_id.split("|"):
                    result.append(c)
        return result

    def to_dict(self) -> dict:
        return {
            "is_clean": self.is_clean,
            "total": len(self.conflicts),
            "counts": self.count_by_type(),
            "conflicts": [c.to_dict() for c in self.conflicts],
            "unscheduled": self.unscheduled,
        }


def audit_placements(
    placements: Sequence[Placement],
    unscheduled: Sequence[dict] = (),
) -> ConflictReport:
    """
    Run the full conflict audit over final placements.

    Args:
        placements:  All placed sessions.
        unscheduled: Optional list of ``UnscheduledSession.to_dict()``
                     results — reported verbatim so nothing is hidden.

    Returns:
        A :class:`ConflictReport` with per-slot conflict indexes for
        the renderers.
    """
    conflicts: List[Conflict] = []
    conflicts.extend(_find_double_bookings(placements))
    conflicts.extend(_find_parallel_misalignment(placements))
    return ConflictReport(conflicts=conflicts, unscheduled=list(unscheduled))


# ----------------------------------------------------------------------
# C1 / C2 / C3 — same-slot double bookings
# ----------------------------------------------------------------------

def _find_double_bookings(
    placements: Sequence[Placement],
) -> List[Conflict]:
    conflicts: List[Conflict] = []

    # (day, period) → list of placements occupying it
    by_slot: Dict[Tuple[str, int], List[Placement]] = {}
    for p in placements:
        for s in p.slots:
            by_slot.setdefault((s.day.name, s.period), []).append(p)

    for (day, period), occupants in sorted(by_slot.items()):
        if len(occupants) < 2:
            continue

        # Teacher clashes (C1)
        seen: Dict[str, Placement] = {}
        for p in occupants:
            tid = p.assignment.teacher_id
            if tid in seen:
                conflicts.append(Conflict(
                    conflict_type="TEACHER",
                    entity_id=tid,
                    day=day,
                    period=period,
                    placement_a=seen[tid].placement_id,
                    placement_b=p.placement_id,
                    description=(
                        f"Teacher {tid} is double-booked at {day} P{period}: "
                        f"{_label(seen[tid])} vs {_label(p)}"
                    ),
                ))
            else:
                seen[tid] = p

        # Room clashes (C2)
        seen = {}
        for p in occupants:
            rid = p.room_id
            if rid in seen:
                conflicts.append(Conflict(
                    conflict_type="ROOM",
                    entity_id=rid,
                    day=day,
                    period=period,
                    placement_a=seen[rid].placement_id,
                    placement_b=p.placement_id,
                    description=(
                        f"Room {rid} is double-booked at {day} P{period}: "
                        f"{_label(seen[rid])} vs {_label(p)}"
                    ),
                ))
            else:
                seen[rid] = p

        # Section/group clashes (C3) — pairs, so both directions reported once
        reported: Set[Tuple[str, str]] = set()
        for i, a in enumerate(occupants):
            for b in occupants[i + 1:]:
                if _sections_clash(a, b):
                    key = tuple(sorted((a.placement_id, b.placement_id)))
                    if key in reported:
                        continue
                    reported.add(key)
                    conflicts.append(Conflict(
                        conflict_type="SECTION",
                        entity_id=_section_entity(a),
                        day=day,
                        period=period,
                        placement_a=a.placement_id,
                        placement_b=b.placement_id,
                        description=(
                            f"Section conflict at {day} P{period}: "
                            f"{_label(a)} overlaps {_label(b)}"
                        ),
                    ))

    return conflicts


def _sections_clash(a: Placement, b: Placement) -> bool:
    """True if the two placements claim the same students (C3 rules)."""
    aa, ba = a.assignment, b.assignment
    if aa.section != ba.section:
        return False
    return ba.group in ScheduleState._get_conflicting_groups(aa.group)


def _section_entity(p: Placement) -> str:
    """Entity id for section-kind conflicts (both sections if they differ)."""
    return p.assignment.section


def _label(p: Placement) -> str:
    a = p.assignment
    return (
        f"{a.subject_id} sec {a.section}"
        + (f"/{a.group}" if a.group != "ALL" else "")
        + f" ({a.teacher_id}, room {p.room_id})"
    )


# ----------------------------------------------------------------------
# C6 — G1/G2 parallel alignment
# ----------------------------------------------------------------------

def _find_parallel_misalignment(
    placements: Sequence[Placement],
) -> List[Conflict]:
    """
    If both G1 and G2 placements exist for the same (subject, section,
    activity), their slot ranges must match one-to-one (C6).  A group
    with no counterpart assignment is legitimate and never flagged.
    """
    # (subject_id, section, activity) → group → sorted range list
    buckets: Dict[Tuple[str, str, str], Dict[str, List[Tuple[str, int, int]]]] = {}

    for p in placements:
        a = p.assignment
        if a.group not in ("G1", "G2"):
            continue
        periods = sorted(s.period for s in p.slots)
        if not periods:
            continue
        day = p.slots[0].day.name
        rng = (day, periods[0], periods[-1])
        key = (a.subject_id, a.section, _activity_value(a))
        buckets.setdefault(key, {}).setdefault(a.group, []).append(rng)

    conflicts: List[Conflict] = []
    for (subject_id, section, activity), groups in buckets.items():
        g1 = sorted(groups.get("G1", []))
        g2 = sorted(groups.get("G2", []))
        if not g1 or not g2:
            continue  # single-group practicals are fine
        if g1 != g2:
            sections = f"{section}"
            conflicts.append(Conflict(
                conflict_type="PARALLEL",
                entity_id=sections,
                day="*",
                period=0,
                placement_a="",
                placement_b="",
                description=(
                    f"G1/G2 parallel misalignment for {subject_id} "
                    f"(section {section}, {activity}): "
                    f"G1={_ranges(g1)} vs G2={_ranges(g2)}"
                ),
            ))
    return conflicts


def _activity_value(assignment) -> str:
    at = assignment.activity_type
    return at.value if hasattr(at, "value") else str(at)


def _ranges(ranges: List[Tuple[str, int, int]]) -> str:
    return ", ".join(f"{d} P{a}-P{b}" for d, a, b in ranges)


# ----------------------------------------------------------------------
# Conflict → grid-cell marking helpers
# ----------------------------------------------------------------------

def conflicted_slot_keys(report: ConflictReport) -> Set[Tuple[str, str, int]]:
    """
    Set of ``(placement_id, day_name, period)`` triples that belong to a
    conflicted placement.  Renderers use this to flag grid cells.
    """
    keys: Set[Tuple[str, str, int]] = set()
    for c in report.conflicts:
        for pid in (c.placement_a, c.placement_b):
            if pid:
                keys.add((pid, c.day, c.period))
    return keys
