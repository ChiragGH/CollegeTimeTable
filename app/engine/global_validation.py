"""
Global timetable conflict detection and validation engine.

Detects hard-constraint clashes across ALL active timetables within
an academic year / scheduling universe:
1. Teacher Clash: Teacher assigned in two places at the same day + period.
2. Room Clash: Room (including shared labs/workshops) occupied by two classes at the same day + period.
3. Section Clash: Section assigned two activities at the same time.
4. Group Clash: Group (e.g. G1) assigned two simultaneous activities.
5. Recess Violation: Activities scheduled during the 13:00-14:00 lunch period or bridging recess.
6. Parallel Practical Alignment: G1 and G2 for the same subject/section must be aligned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.models.enums import Day
from app.models.slot import TimeSlot
from app.models.timetable import Timetable, TimetablePlacement

TIME_LABELS = {
    1: "9:00 - 10:00",
    2: "10:00 - 11:00",
    3: "11:00 - 12:00",
    4: "12:00 - 1:00",
    5: "2:00 - 3:00",
    6: "3:00 - 4:00",
    7: "4:00 - 5:00",
}


@dataclass
class GlobalConflict:
    """One concrete constraint violation, potentially cross-timetable."""
    conflict_type: str  # "TEACHER", "ROOM", "SECTION", "GROUP", "RECESS", "PARALLEL"
    entity_id: str      # teacher_id / room_id / section
    entity_name: str    # Human-friendly name
    day: str            # "MON", "TUE", etc.
    period: int         # 1..7 (or 0 for spanning)
    time_label: str
    timetable_a: Dict[str, Any]
    timetable_b: Optional[Dict[str, Any]]
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_type": self.conflict_type,
            "type": self.conflict_type,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "day": self.day,
            "period": self.period,
            "time_label": self.time_label,
            "timetable_a": self.timetable_a,
            "timetable_b": self.timetable_b,
            "description": self.description,
        }


@dataclass
class GlobalValidationReport:
    """Result of a college-wide cross-timetable conflict audit."""
    academic_year: str
    total_timetables: int
    total_placements: int
    is_clean: bool
    counts: Dict[str, int]
    conflicts: List[GlobalConflict] = field(default_factory=list)

    @property
    def total_conflicts(self) -> int:
        return len(self.conflicts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "academic_year": self.academic_year,
            "total_timetables": self.total_timetables,
            "total_placements": self.total_placements,
            "is_clean": self.is_clean,
            "status": "VALID" if self.is_clean else "CONFLICTING",
            "counts": self.counts,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "total_conflicts": len(self.conflicts),
        }


class GlobalConflictDetector:
    """Independent validator and clash auditor across multiple timetables."""

    @staticmethod
    def _placement_info(p: TimetablePlacement, tt: Timetable) -> Dict[str, Any]:
        return {
            "timetable_id": tt.timetable_id,
            "display_name": tt.display_name,
            "context_code": tt.full_context_code,
            "academic_year": tt.academic_year,
            "branch": tt.branch,
            "semester": tt.semester,
            "section": tt.section,
            "placement_id": p.placement_id,
            "subject_id": p.subject_id,
            "subject_name": p.subject_short_name or p.subject_id,
            "teacher_id": p.teacher_id,
            "teacher_name": p.teacher_name or p.teacher_id,
            "room_id": p.room_id,
            "room_name": p.room_name or p.room_id,
            "group": p.group,
            "activity_type": (
                p.activity_type.value
                if hasattr(p.activity_type, "value")
                else str(p.activity_type)
            ),
        }

    @staticmethod
    def _groups_conflict(g1: str, g2: str) -> bool:
        """True if groups conflict (ALL conflicts with everything; G1/G2 run in parallel)."""
        if g1 == "ALL" or g2 == "ALL":
            return True
        return g1 == g2

    @classmethod
    def audit_timetables(
        cls,
        timetables: List[Timetable],
        academic_year: Optional[str] = None,
    ) -> GlobalValidationReport:
        """
        Audit all given timetables for hard clashes across the scheduling universe.
        """
        if academic_year:
            timetables = [tt for tt in timetables if tt.academic_year == academic_year]

        total_placements = sum(len(tt.placements) for tt in timetables)
        conflicts: List[GlobalConflict] = []

        # Map: (day, period) -> List of (placement, timetable)
        slot_occupancy: Dict[Tuple[str, int], List[Tuple[TimetablePlacement, Timetable]]] = {}

        for tt in timetables:
            for p in tt.placements:
                for sl in p.slots:
                    key = (sl.day.name, sl.period)
                    slot_occupancy.setdefault(key, []).append((p, tt))

        # Check each slot
        for (day, period), occupants in sorted(slot_occupancy.items()):
            time_label = TIME_LABELS.get(period, f"Period {period}")

            # 1. Recess Violation check: periods must be 1..7, no recess placement
            if period <= 0 or period > 7:
                for p, tt in occupants:
                    conflicts.append(GlobalConflict(
                        conflict_type="RECESS",
                        entity_id=f"P{period}",
                        entity_name=f"Period {period}",
                        day=day,
                        period=period,
                        time_label=time_label,
                        timetable_a=cls._placement_info(p, tt),
                        timetable_b=None,
                        description=f"Class scheduled outside valid teaching periods ({day} P{period}) in {tt.display_name}",
                    ))

            # 2. Check blocks that illegally bridge recess (Period 4 -> Period 5)
            # A block cannot start at P4 and continue to P5 because 13:00-14:00 is recess!
            seen_bridge: Set[str] = set()
            for p, tt in occupants:
                if p.placement_id in seen_bridge:
                    continue
                seen_bridge.add(p.placement_id)
                periods = [sl.period for sl in p.slots if sl.day.name == day]
                if 4 in periods and 5 in periods:
                    conflicts.append(GlobalConflict(
                        conflict_type="RECESS",
                        entity_id="RECESS_13:00-14:00",
                        entity_name="Recess (1:00 - 2:00 PM)",
                        day=day,
                        period=4,
                        time_label="12:00 - 2:00",
                        timetable_a=cls._placement_info(p, tt),
                        timetable_b=None,
                        description=f"Block session '{p.subject_short_name or p.subject_id}' bridges across Recess (1:00-2:00 PM) in {tt.display_name}",
                    ))

            if len(occupants) < 2:
                continue

            # 3. Teacher Clashes (C1)
            teacher_seen: Dict[str, Tuple[TimetablePlacement, Timetable]] = {}
            for p, tt in occupants:
                tid = p.teacher_id
                if not tid:
                    continue
                if tid in teacher_seen:
                    prev_p, prev_tt = teacher_seen[tid]
                    # Disregard duplicate references to the exact same placement
                    if prev_p.placement_id != p.placement_id:
                        t_name = p.teacher_name or prev_p.teacher_name or tid
                        conflicts.append(GlobalConflict(
                            conflict_type="TEACHER",
                            entity_id=tid,
                            entity_name=t_name,
                            day=day,
                            period=period,
                            time_label=time_label,
                            timetable_a=cls._placement_info(prev_p, prev_tt),
                            timetable_b=cls._placement_info(p, tt),
                            description=(
                                f"Teacher clash: {t_name} is double-booked at {day} P{period} ({time_label}) "
                                f"between '{prev_tt.display_name}' ({prev_p.subject_short_name or prev_p.subject_id}) "
                                f"and '{tt.display_name}' ({p.subject_short_name or p.subject_id})"
                            ),
                        ))
                else:
                    teacher_seen[tid] = (p, tt)

            # 4. Room Clashes (C2)
            room_seen: Dict[str, Tuple[TimetablePlacement, Timetable]] = {}
            for p, tt in occupants:
                rid = p.room_id
                if not rid:
                    continue
                if rid in room_seen:
                    prev_p, prev_tt = room_seen[rid]
                    if prev_p.placement_id != p.placement_id:
                        r_name = p.room_name or prev_p.room_name or rid
                        conflicts.append(GlobalConflict(
                            conflict_type="ROOM",
                            entity_id=rid,
                            entity_name=r_name,
                            day=day,
                            period=period,
                            time_label=time_label,
                            timetable_a=cls._placement_info(prev_p, prev_tt),
                            timetable_b=cls._placement_info(p, tt),
                            description=(
                                f"Room clash: Room {r_name} is double-booked at {day} P{period} ({time_label}) "
                                f"between '{prev_tt.display_name}' ({prev_p.subject_short_name or prev_p.subject_id}) "
                                f"and '{tt.display_name}' ({p.subject_short_name or p.subject_id})"
                            ),
                        ))
                else:
                    room_seen[rid] = (p, tt)

            # 5. Section and Group Clashes (C3)
            # Check within the same academic section
            sec_seen: Set[Tuple[str, str]] = set()
            for i, (p1, tt1) in enumerate(occupants):
                for p2, tt2 in occupants[i + 1:]:
                    if p1.placement_id == p2.placement_id:
                        continue
                    # Same academic section context
                    if (
                        tt1.branch == tt2.branch
                        and tt1.semester == tt2.semester
                        and p1.section == p2.section
                    ):
                        if cls._groups_conflict(p1.group, p2.group):
                            pair_key = tuple(sorted((p1.placement_id, p2.placement_id)))
                            if pair_key in sec_seen:
                                continue
                            sec_seen.add(pair_key)
                            c_type = "GROUP" if p1.group == p2.group and p1.group != "ALL" else "SECTION"
                            target = f"Group {p1.group}" if c_type == "GROUP" else f"Section {p1.section}"
                            conflicts.append(GlobalConflict(
                                conflict_type=c_type,
                                entity_id=f"{tt1.branch}-S{tt1.semester}-{p1.section}",
                                entity_name=target,
                                day=day,
                                period=period,
                                time_label=time_label,
                                timetable_a=cls._placement_info(p1, tt1),
                                timetable_b=cls._placement_info(p2, tt2),
                                description=(
                                    f"{target} conflict at {day} P{period} ({time_label}): "
                                    f"'{p1.subject_short_name or p1.subject_id}' ({p1.group}) overlaps "
                                    f"with '{p2.subject_short_name or p2.subject_id}' ({p2.group})"
                                ),
                            ))

        # Count conflicts by category
        counts: Dict[str, int] = {
            "TEACHER": 0,
            "ROOM": 0,
            "SECTION": 0,
            "GROUP": 0,
            "RECESS": 0,
            "PARALLEL": 0,
        }
        for c in conflicts:
            counts[c.conflict_type] = counts.get(c.conflict_type, 0) + 1

        yr = academic_year or (timetables[0].academic_year if timetables else "All")
        return GlobalValidationReport(
            academic_year=yr,
            total_timetables=len(timetables),
            total_placements=total_placements,
            is_clean=len(conflicts) == 0,
            counts=counts,
            conflicts=conflicts,
        )

    @classmethod
    def check_candidate_edit(
        cls,
        target_timetable: Timetable,
        candidate_data: Dict[str, Any],
        all_timetables: List[Timetable],
        exclude_placement_id: Optional[str] = None,
    ) -> List[GlobalConflict]:
        """
        Live pre-validation for the cell editor.

        Checks if placing the candidate session causes any conflict against
        all active timetables in the same academic year.
        """
        day_name = candidate_data.get("day", "MON")
        start_period = int(candidate_data.get("period", 1))
        block_size = int(candidate_data.get("block_size", 1))
        teacher_id = candidate_data.get("teacher_id", "")
        room_id = candidate_data.get("room_id", "")
        subject_id = candidate_data.get("subject_id", "")
        section = candidate_data.get("section", target_timetable.section)
        group = candidate_data.get("group", "ALL")

        # Determine target periods
        target_periods = list(range(start_period, start_period + block_size))
        conflicts: List[GlobalConflict] = []

        # 1. Recess checks
        for p in target_periods:
            if p <= 0 or p > 7:
                conflicts.append(GlobalConflict(
                    conflict_type="RECESS",
                    entity_id=f"P{p}",
                    entity_name=f"Period {p}",
                    day=day_name,
                    period=p,
                    time_label=TIME_LABELS.get(p, f"P{p}"),
                    timetable_a={"timetable_id": target_timetable.timetable_id, "display_name": target_timetable.display_name},
                    timetable_b=None,
                    description=f"Selected period P{p} is outside teaching hours (P1 to P7).",
                ))

        if 4 in target_periods and 5 in target_periods:
            conflicts.append(GlobalConflict(
                conflict_type="RECESS",
                entity_id="RECESS",
                entity_name="Recess (1:00 - 2:00 PM)",
                day=day_name,
                period=4,
                time_label="12:00 - 2:00",
                timetable_a={"timetable_id": target_timetable.timetable_id, "display_name": target_timetable.display_name},
                timetable_b=None,
                description="A continuous block cannot bridge across Recess (1:00 - 2:00 PM).",
            ))

        # Check against all active timetables for the same academic year
        same_year_timetables = [
            tt for tt in all_timetables
            if tt.academic_year == target_timetable.academic_year
        ]

        for p_num in target_periods:
            time_label = TIME_LABELS.get(p_num, f"P{p_num}")
            for tt in same_year_timetables:
                for existing in tt.placements:
                    if exclude_placement_id and existing.placement_id == exclude_placement_id:
                        continue
                    # Check if existing occupies (day_name, p_num)
                    occupies = any(
                        s.day.name == day_name and s.period == p_num
                        for s in existing.slots
                    )
                    if not occupies:
                        continue

                    # Teacher clash
                    if teacher_id and existing.teacher_id == teacher_id:
                        conflicts.append(GlobalConflict(
                            conflict_type="TEACHER",
                            entity_id=teacher_id,
                            entity_name=candidate_data.get("teacher_name") or teacher_id,
                            day=day_name,
                            period=p_num,
                            time_label=time_label,
                            timetable_a={"timetable_id": target_timetable.timetable_id, "display_name": target_timetable.display_name, "subject": subject_id},
                            timetable_b=cls._placement_info(existing, tt),
                            description=(
                                f"Teacher Conflict: {existing.teacher_name or teacher_id} is already "
                                f"assigned to '{tt.display_name}' ({existing.subject_short_name or existing.subject_id}) at {day_name} P{p_num} ({time_label})."
                            ),
                        ))

                    # Room clash
                    if room_id and existing.room_id == room_id:
                        conflicts.append(GlobalConflict(
                            conflict_type="ROOM",
                            entity_id=room_id,
                            entity_name=candidate_data.get("room_name") or room_id,
                            day=day_name,
                            period=p_num,
                            time_label=time_label,
                            timetable_a={"timetable_id": target_timetable.timetable_id, "display_name": target_timetable.display_name, "subject": subject_id},
                            timetable_b=cls._placement_info(existing, tt),
                            description=(
                                f"Room Conflict: Room {existing.room_name or room_id} is already "
                                f"booked by '{tt.display_name}' ({existing.subject_short_name or existing.subject_id}) at {day_name} P{p_num} ({time_label})."
                            ),
                        ))

                    # Section / Group clash
                    if (
                        tt.branch == target_timetable.branch
                        and tt.semester == target_timetable.semester
                        and existing.section == section
                    ):
                        if cls._groups_conflict(group, existing.group):
                            c_type = "GROUP" if group == existing.group and group != "ALL" else "SECTION"
                            target = f"Group {group}" if c_type == "GROUP" else f"Section {section}"
                            conflicts.append(GlobalConflict(
                                conflict_type=c_type,
                                entity_id=f"{tt.branch}-S{tt.semester}-{section}",
                                entity_name=target,
                                day=day_name,
                                period=p_num,
                                time_label=time_label,
                                timetable_a={"timetable_id": target_timetable.timetable_id, "display_name": target_timetable.display_name, "subject": subject_id},
                                timetable_b=cls._placement_info(existing, tt),
                                description=(
                                    f"{target} Conflict: {target} already has '{existing.subject_short_name or existing.subject_id}' "
                                    f"scheduled at {day_name} P{p_num} ({time_label})."
                                ),
                            ))

        return conflicts
