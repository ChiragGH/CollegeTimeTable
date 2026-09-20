"""
Timetable validation engine.

Answers one question about a generated timetable: **is it a valid,
complete deliverable?**  A timetable is VALID only when

* it contains **zero hard-constraint clashes** (teacher / room /
  section-group double bookings and G1/G2 parallel misalignment), and
* the **full required workload** is placed — every assignment gets all
  of its weekly periods, and every configured section actually carries
  its workload (an ``A``-full / ``B``-empty split is INVALID).

The engine NEVER fabricates filler to hide a gap.  When the solver
could not place the complete workload it reports the structured status
``NO_VALID_TIMETABLE`` together with the exact reasons, so the user can
fix the setup rather than ship a silently-broken grid.

This module is a thin, read-only layer over
:func:`app.export.conflicts.audit_placements`; it adds workload- and
section-coverage completeness on top of the independent clash audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.models.assignment import Assignment
from app.models.placement import Placement
from app.models.section import Section
from app.export.conflicts import ConflictReport, audit_placements


# Validation status values.
VALID = "VALID"
INVALID = "INVALID"
NO_VALID_TIMETABLE = "NO_VALID_TIMETABLE"


@dataclass
class ValidationIssue:
    """One concrete reason a timetable is not a valid deliverable."""

    category: str          # CLASH | WORKLOAD_INCOMPLETE | SECTION_EMPTY | SECTION_INCOMPLETE
    entity: str            # section label / assignment id / teacher / room
    message: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "entity": self.entity,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass
class ValidationReport:
    """Verdict for one generated timetable."""

    status: str                                    # VALID | INVALID | NO_VALID_TIMETABLE
    issues: List[ValidationIssue] = field(default_factory=list)
    conflict_report: Optional[ConflictReport] = None

    @property
    def is_valid(self) -> bool:
        return self.status == VALID

    @property
    def headline(self) -> str:
        if self.status == VALID:
            return "VALID — complete workload, zero clashes"
        if self.status == NO_VALID_TIMETABLE:
            return "NO VALID TIMETABLE FOUND"
        return "INVALID — see reported issues"

    def issues_by_category(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for i in self.issues:
            counts[i.category] = counts.get(i.category, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "is_valid": self.is_valid,
            "headline": self.headline,
            "issue_count": len(self.issues),
            "counts": self.issues_by_category(),
            "issues": [i.to_dict() for i in self.issues],
            "conflicts": (
                self.conflict_report.to_dict() if self.conflict_report else None
            ),
        }


def _placed_periods_by_assignment(
    placements: Sequence[Placement],
) -> Dict[str, int]:
    """Total placed periods per assignment_id (sum of slot counts)."""
    placed: Dict[str, int] = {}
    for p in placements:
        aid = p.assignment.assignment_id
        placed[aid] = placed.get(aid, 0) + len(p.slots)
    return placed


def _check_workload(
    assignments: Sequence[Assignment],
    placements: Sequence[Placement],
) -> List[ValidationIssue]:
    """Every assignment must have all of its weekly periods placed.

    G1/G2 practicals are validated per assignment, so a G1 weekly=4 and
    a G2 weekly=4 are each checked against their own 4 periods — the
    shared academic periods are never counted twice.
    """
    placed = _placed_periods_by_assignment(placements)
    issues: List[ValidationIssue] = []
    for a in assignments:
        required = a.weekly_periods
        got = placed.get(a.assignment_id, 0)
        if got < required:
            grp = "" if a.group == "ALL" else f"/{a.group}"
            issues.append(ValidationIssue(
                category="WORKLOAD_INCOMPLETE",
                entity=a.assignment_id,
                message=(
                    f"{a.subject_id} (section {a.section}{grp}) has "
                    f"{got}/{required} weekly periods placed"
                ),
                detail={
                    "assignment_id": a.assignment_id,
                    "subject_id": a.subject_id,
                    "section": a.section,
                    "group": a.group,
                    "required": required,
                    "placed": got,
                    "missing": required - got,
                },
            ))
    return issues


def _check_section_coverage(
    assignments: Sequence[Assignment],
    sections: Sequence[Section],
    placements: Sequence[Placement],
) -> List[ValidationIssue]:
    """Every configured section must carry its required workload.

    A section that is configured but has **no assignments** at all, or
    whose assignments are entirely unplaced, is INVALID (the ``A``-full
    / ``B``-empty split the spec forbids).
    """
    issues: List[ValidationIssue] = []

    # section label → assignments requested for it
    requested: Dict[str, List[Assignment]] = {}
    for a in assignments:
        requested.setdefault(a.section, []).append(a)

    # section label → placed periods
    placed_by_section: Dict[str, int] = {}
    for p in placements:
        sec = p.assignment.section
        placed_by_section[sec] = placed_by_section.get(sec, 0) + len(p.slots)

    for section in sections:
        label = section.label
        sec_assignments = requested.get(label, [])
        if not sec_assignments:
            issues.append(ValidationIssue(
                category="SECTION_EMPTY",
                entity=label,
                message=(
                    f"Section {label} is configured but has no workload "
                    f"assigned — every section must carry its required load"
                ),
                detail={"section": label, "assignments": 0},
            ))
            continue
        required = sum(a.weekly_periods for a in sec_assignments)
        got = placed_by_section.get(label, 0)
        if got == 0 and required > 0:
            issues.append(ValidationIssue(
                category="SECTION_EMPTY",
                entity=label,
                message=(
                    f"Section {label} has {len(sec_assignments)} assignment(s) "
                    f"but none were placed — the section timetable is empty"
                ),
                detail={"section": label, "required": required, "placed": 0},
            ))
    return issues


def validate_timetable(
    assignments: Sequence[Assignment],
    placements: Sequence[Placement],
    sections: Sequence[Section] = (),
    unscheduled: Sequence[dict] = (),
) -> ValidationReport:
    """Validate a generated timetable against the hard requirements.

    Args:
        assignments: The required academic workload (what *should* be
                     scheduled).
        placements:  The placements the scheduler produced.
        sections:    Configured sections; used for coverage completeness.
                     When empty, only assignment-level workload is checked.
        unscheduled: Optional ``UnscheduledSession.to_dict()`` list, passed
                     through to the conflict report so nothing is hidden.

    Returns:
        A :class:`ValidationReport`.  Status is:

        * ``INVALID`` when any hard-constraint clash exists, or a
          configured section carries no workload;
        * ``NO_VALID_TIMETABLE`` when the workload is incomplete
          (sessions could not be placed) but the placed part is clash-free;
        * ``VALID`` only when the full workload is placed with zero clashes.
    """
    conflict_report = audit_placements(placements, unscheduled=unscheduled)

    issues: List[ValidationIssue] = []

    # 1. Hard-constraint clashes (from the independent audit).
    for c in conflict_report.conflicts:
        issues.append(ValidationIssue(
            category="CLASH",
            entity=c.entity_id,
            message=c.description,
            detail=c.to_dict(),
        ))

    # 2. Workload completeness (per assignment).
    workload_issues = _check_workload(assignments, placements)
    issues.extend(workload_issues)

    # 3. Section coverage completeness.
    empty_section_issues = _check_section_coverage(
        assignments, sections, placements,
    )
    issues.extend(empty_section_issues)

    # Decide the overall status.  Clashes and empty configured sections
    # mean the produced grid is INVALID; an incomplete-but-clean workload
    # means the solver found NO complete valid timetable.
    if conflict_report.conflicts or empty_section_issues:
        status = INVALID
    elif workload_issues:
        status = NO_VALID_TIMETABLE
    else:
        status = VALID

    return ValidationReport(
        status=status,
        issues=issues,
        conflict_report=conflict_report,
    )
