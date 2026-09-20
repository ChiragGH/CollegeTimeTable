"""
Timetable Manager for multi-timetable persistence, lifecycle, and editing.

Handles saving, loading, listing, editing, versioning, and deleting
persistent Timetable records stored under ``Data/timetables/<timetable_id>.json``.
"""

from __future__ import annotations

import sys
import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.engine.global_validation import GlobalConflictDetector, GlobalConflict
from app.models.enums import ActivityType, Day, RoomType
from app.models.slot import TimeSlot
from app.models.timetable import Timetable, TimetablePlacement, TimetableHistoryEntry


class TimetableManager:
    """
    Central manager for persistent Timetable instances.
    """

    def __init__(self, timetables_dir: Optional[str] = None):
        if timetables_dir is None:
            if getattr(sys, "frozen", False):
                base_dir = Path(sys.executable).parent
            else:
                base_dir = Path(__file__).resolve().parent.parent.parent
            timetables_dir = str(base_dir / "Data" / "timetables")
        self.timetables_dir = Path(timetables_dir)
        self.timetables_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Timetable] = {}
        self.load_all()

    def load_all(self) -> None:
        """Scan timetables directory and load all JSON files into cache."""
        self._cache.clear()
        if not self.timetables_dir.exists():
            return
        for file_path in self.timetables_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    tt = Timetable.from_dict(data)
                    self._cache[tt.timetable_id] = tt
            except Exception as e:
                print(f"Warning: Could not load timetable file {file_path}: {e}")

    def list_timetables(
        self,
        academic_year: Optional[str] = None,
        branch: Optional[str] = None,
        semester: Optional[int] = None,
        section: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Timetable]:
        """Query timetables matching optional filters."""
        results = list(self._cache.values())
        if academic_year:
            results = [tt for tt in results if tt.academic_year == academic_year]
        if branch:
            results = [tt for tt in results if tt.branch.upper() == branch.upper()]
        if semester is not None and semester > 0:
            results = [tt for tt in results if tt.semester == semester]
        if section:
            results = [tt for tt in results if tt.section.upper() == section.upper()]
        if status:
            results = [tt for tt in results if tt.status.upper() == status.upper()]

        # Sort by academic_year, branch, semester, section, version
        results.sort(
            key=lambda t: (t.academic_year, t.branch, t.semester, t.section, t.version)
        )
        return results

    def get_timetable(self, timetable_id: str) -> Optional[Timetable]:
        """Retrieve a timetable by its unique identifier."""
        return self._cache.get(timetable_id)

    def save_timetable(self, timetable: Timetable) -> None:
        """Persist timetable to disk and update cache."""
        timetable.updated_at = datetime.now().isoformat(timespec="seconds")
        file_path = self.timetables_dir / f"{timetable.timetable_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(timetable.to_dict(), f, indent=2, ensure_ascii=False)
        self._cache[timetable.timetable_id] = timetable

    def delete_timetable(self, timetable_id: str) -> bool:
        """Delete timetable from disk and cache. Does NOT affect other timetables."""
        if timetable_id in self._cache:
            del self._cache[timetable_id]
            file_path = self.timetables_dir / f"{timetable_id}.json"
            if file_path.exists():
                file_path.unlink()
            return True
        return False

    def duplicate_timetable(self, timetable_id: str) -> Optional[Timetable]:
        """Create a duplicate / clone of an existing timetable."""
        original = self.get_timetable(timetable_id)
        if not original:
            return None

        new_version = original.version + 1
        new_id = f"{original.branch}-SEM{original.semester}-{original.section}-{original.academic_year}-v{new_version}"
        now = datetime.now().isoformat(timespec="seconds")

        new_placements = [
            copy.deepcopy(p) for p in original.placements
        ]
        for p in new_placements:
            p.timetable_id = new_id

        clone = Timetable(
            timetable_id=new_id,
            academic_year=original.academic_year,
            branch=original.branch,
            semester=original.semester,
            section=original.section,
            status=original.status,
            placements=new_placements,
            version=new_version,
            created_at=now,
            updated_at=now,
            generation_seed=original.generation_seed,
            session_id=original.session_id,
            history=[
                TimetableHistoryEntry(
                    version=new_version,
                    timestamp=now,
                    action="DUPLICATED",
                    description=f"Duplicated from {original.timetable_id}",
                )
            ],
            metadata=copy.deepcopy(original.metadata),
        )
        self.save_timetable(clone)
        return clone

    def find_existing(
        self,
        academic_year: str,
        branch: str,
        semester: int,
        section: str,
    ) -> List[Timetable]:
        """Find existing timetables matching the exact academic context."""
        return [
            tt for tt in self._cache.values()
            if tt.academic_year == academic_year
            and tt.branch.upper() == branch.upper()
            and tt.semester == semester
            and tt.section.upper() == section.upper()
        ]

    def create_from_schedule_result(
        self,
        session_id: str,
        academic_year: str,
        branch: str,
        semester: int,
        schedule_result: Any,
        filters: Any = None,
        room_dict: Optional[Dict[str, Any]] = None,
        mode: str = "new_version",
        target_timetable_id: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> List[Timetable]:
        """
        Convert a ScheduleResult into persistent Timetable entities.

        Splits placements per section so each section gets its own deliverable timetable.
        Respects duplicate generation choice:
        - "new_version": creates a new timetable instance with incremented version.
        - "replace_existing": replaces placements of target_timetable_id or active context.
        """
        now = datetime.now().isoformat(timespec="seconds")
        room_dict = room_dict or {}
        # Group placements by section
        placements_by_sec: Dict[str, List[TimetablePlacement]] = {}

        # 1. Convert engine placements to TimetablePlacements
        for p in schedule_result.placements:
            sec = p.assignment.section
            subj = filters.get_subject(p.assignment.subject_id) if filters else None
            short_name = (
                getattr(subj, "short_name", "")
                or (subj.subject_code if subj else "")
                or p.assignment.subject_id
            )
            name = subj.subject_name if subj else p.assignment.subject_id
            teacher = filters.get_teacher(p.assignment.teacher_id) if filters else None
            teacher_name = getattr(teacher, "teacher_name", "") or p.assignment.teacher_id
            room_name = room_dict[p.room_id].room_name if p.room_id in room_dict else p.room_id

            tp = TimetablePlacement(
                placement_id=p.placement_id,
                timetable_id="",  # Bound below
                assignment_id=p.assignment.assignment_id,
                subject_id=p.assignment.subject_id,
                teacher_id=p.assignment.teacher_id,
                room_id=p.room_id,
                section=sec,
                group=p.assignment.group,
                activity_type=p.assignment.activity_type,
                slots=list(p.slots),
                block_size=len(p.slots),
                subject_short_name=short_name,
                subject_name=name,
                teacher_name=teacher_name,
                room_name=room_name,
                is_linked_parallel=False,
                linked_placement_id=None,
            )
            placements_by_sec.setdefault(sec, []).append(tp)

        # 2. Detect parallel practical linkages (G1 and G2 same slots & subject)
        for sec, p_list in placements_by_sec.items():
            g1_map = {
                (p.subject_id, tuple(s.period for s in p.slots), tuple(s.day.name for s in p.slots)): p
                for p in p_list if p.group == "G1"
            }
            for p in p_list:
                if p.group == "G2":
                    key = (p.subject_id, tuple(s.period for s in p.slots), tuple(s.day.name for s in p.slots))
                    if key in g1_map:
                        g1_p = g1_map[key]
                        p.is_linked_parallel = True
                        p.linked_placement_id = g1_p.placement_id
                        g1_p.is_linked_parallel = True
                        g1_p.linked_placement_id = p.placement_id

        # 3. Create or update persistent Timetable record for each section
        created_timetables: List[Timetable] = []

        # In case a section has no placed assignments yet, ensure all session sections are handled
        session_sections = list(placements_by_sec.keys()) or ["A"]

        for sec in session_sections:
            sec_placements = placements_by_sec.get(sec, [])
            existing_list = self.find_existing(academic_year, branch, semester, sec)

            target_tt: Optional[Timetable] = None
            if mode == "replace_existing":
                if target_timetable_id and target_timetable_id in self._cache:
                    target_tt = self._cache[target_timetable_id]
                elif existing_list:
                    target_tt = existing_list[-1]

            if target_tt:
                # Regenerate / Replace existing
                version = target_tt.version + 1
                tt_id = target_tt.timetable_id
                target_tt.version = version
                target_tt.updated_at = now
                target_tt.generation_seed = seed
                target_tt.session_id = session_id
                # Bind placements to this timetable
                for p in sec_placements:
                    p.timetable_id = tt_id
                target_tt.placements = sec_placements
                target_tt.status = "VALID" if schedule_result.is_complete else "INCOMPLETE"
                target_tt.history.append(
                    TimetableHistoryEntry(
                        version=version,
                        timestamp=now,
                        action="REGENERATED",
                        description=f"Regenerated with seed {seed}",
                    )
                )
                self.save_timetable(target_tt)
                created_timetables.append(target_tt)
            else:
                # Generate New Version
                version = len(existing_list) + 1
                # Format: CSE-SEM1-A-2026-27 or with version suffix if duplicates exist
                base_id = f"{branch}-SEM{semester}-{sec}-{academic_year}"
                tt_id = base_id if version == 1 else f"{base_id}-v{version}"
                for p in sec_placements:
                    p.timetable_id = tt_id

                tt = Timetable(
                    timetable_id=tt_id,
                    academic_year=academic_year,
                    branch=branch,
                    semester=semester,
                    section=sec,
                    status="VALID" if schedule_result.is_complete else "INCOMPLETE",
                    placements=sec_placements,
                    version=version,
                    created_at=now,
                    updated_at=now,
                    generation_seed=seed,
                    session_id=session_id,
                    history=[
                        TimetableHistoryEntry(
                            version=version,
                            timestamp=now,
                            action="CREATED",
                            description=f"Initial generation with seed {seed}",
                        )
                    ],
                )
                self.save_timetable(tt)
                created_timetables.append(tt)

        # Audit global conflicts across all active timetables and update statuses
        all_active = list(self._cache.values())
        report = GlobalConflictDetector.audit_timetables(all_active, academic_year=academic_year)
        conflicted_tt_ids = set()
        for c in report.conflicts:
            if c.timetable_a and "timetable_id" in c.timetable_a:
                conflicted_tt_ids.add(c.timetable_a["timetable_id"])
            if c.timetable_b and "timetable_id" in c.timetable_b:
                conflicted_tt_ids.add(c.timetable_b["timetable_id"])

        for tt in created_timetables:
            if tt.timetable_id in conflicted_tt_ids:
                tt.status = "CONFLICTING"
                self.save_timetable(tt)

        return created_timetables

    def apply_placement_edit(
        self,
        timetable_id: str,
        placement_id: str,
        new_data: Dict[str, Any],
        filters: Any = None,
        room_dict: Optional[Dict[str, Any]] = None,
        force_override: bool = False,
        move_partner: bool = True,
    ) -> Tuple[Optional[Timetable], List[GlobalConflict]]:
        """
        Apply a manual cell edit atomically.

        Handles:
        - Consecutive practical block movement.
        - Synchronized G1/G2 movement.
        - Recess checking (13:00-14:00 blocked).
        - Global conflict checking.
        - Version history tracking.
        """
        tt = self.get_timetable(timetable_id)
        if not tt:
            return None, []

        p = tt.find_placement(placement_id)
        is_new_placement = p is None

        # Build proposed candidate slots
        day_name = new_data.get("day", "MON")
        try:
            day_enum = Day[day_name]
        except KeyError:
            day_enum = Day.MON

        start_period = int(new_data.get("period", 1))
        block_size = int(new_data.get("block_size", p.block_size if p else 1))

        # Check recess and valid periods
        proposed_periods = list(range(start_period, start_period + block_size))
        if 4 in proposed_periods and 5 in proposed_periods:
            raise ValueError("A continuous block cannot bridge across Recess (1:00 - 2:00 PM).")
        if any(pr <= 0 or pr > 7 for pr in proposed_periods):
            raise ValueError(f"Periods must be between 1 and 7 (got {proposed_periods}).")

        candidate_slots = [TimeSlot(day=day_enum, period=pr) for pr in proposed_periods]

        # Check global conflicts
        all_active = list(self._cache.values())
        candidate_data = dict(new_data)
        candidate_data["period"] = start_period
        candidate_data["block_size"] = block_size
        candidate_data["day"] = day_name

        conflicts = GlobalConflictDetector.check_candidate_edit(
            target_timetable=tt,
            candidate_data=candidate_data,
            all_timetables=all_active,
            exclude_placement_id=placement_id if not is_new_placement else None,
        )

        if conflicts and not force_override:
            return tt, conflicts

        # Capture snapshot of current placements prior to edit
        prior_snapshot = [pl.to_dict() for pl in tt.placements]

        # Prepare snapshot for history/undo
        now = datetime.now().isoformat(timespec="seconds")
        old_version = tt.version
        new_version = old_version + 1

        changes = []
        subject_id = new_data.get("subject_id", p.subject_id if p else "")
        teacher_id = new_data.get("teacher_id", p.teacher_id if p else "")
        room_id = new_data.get("room_id", p.room_id if p else "")
        group = new_data.get("group", p.group if p else "ALL")
        raw_act = new_data.get("activity_type", p.activity_type.value if p else "LECTURE")
        try:
            activity_type = ActivityType(raw_act)
        except ValueError:
            activity_type = ActivityType.LECTURE

        subj = filters.get_subject(subject_id) if filters else None
        short_name = (
            getattr(subj, "short_name", "")
            or (subj.subject_code if subj else "")
            or subject_id
        )
        subj_name = subj.subject_name if subj else subject_id
        teacher = filters.get_teacher(teacher_id) if filters else None
        teacher_name = getattr(teacher, "teacher_name", "") or teacher_id
        room_dict = room_dict or {}
        room_name = room_dict[room_id].room_name if room_id in room_dict else room_id

        if is_new_placement:
            p_id = placement_id or f"P_{tt.timetable_id}_{len(tt.placements) + 1}"
            p = TimetablePlacement(
                placement_id=p_id,
                timetable_id=tt.timetable_id,
                assignment_id=f"A_{p_id}",
                subject_id=subject_id,
                teacher_id=teacher_id,
                room_id=room_id,
                section=tt.section,
                group=group,
                activity_type=activity_type,
                slots=candidate_slots,
                block_size=block_size,
                subject_short_name=short_name,
                subject_name=subj_name,
                teacher_name=teacher_name,
                room_name=room_name,
            )
            tt.placements.append(p)
            changes.append({"action": "ADDED", "details": p.to_dict()})
            desc = f"Added {short_name} at {day_name} P{start_period}"
        else:
            old_slots_str = ", ".join(f"{s.day.name} P{s.period}" for s in p.slots)
            new_slots_str = ", ".join(f"{s.day.name} P{s.period}" for s in candidate_slots)
            if old_slots_str != new_slots_str:
                changes.append({"field": "slots", "from": old_slots_str, "to": new_slots_str})
            if p.teacher_id != teacher_id:
                changes.append({"field": "teacher", "from": p.teacher_name or p.teacher_id, "to": teacher_name})
            if p.room_id != room_id:
                changes.append({"field": "room", "from": p.room_name or p.room_id, "to": room_name})
            if p.subject_id != subject_id:
                changes.append({"field": "subject", "from": p.subject_short_name or p.subject_id, "to": short_name})

            p.subject_id = subject_id
            p.subject_short_name = short_name
            p.subject_name = subj_name
            p.teacher_id = teacher_id
            p.teacher_name = teacher_name
            p.room_id = room_id
            p.room_name = room_name
            p.group = group
            p.activity_type = activity_type
            p.slots = candidate_slots
            p.block_size = block_size
            desc = f"Edited placement: {'; '.join(f'{c.get('field', '')}: {c.get('to', '')}' for c in changes)}" if changes else "Updated placement"

        # Check G1/G2 linked partner
        partner = None
        if p.is_linked_parallel and p.linked_placement_id and move_partner:
            partner = tt.find_placement(p.linked_placement_id)
            if partner:
                partner.slots = list(candidate_slots)
                partner.block_size = block_size
                changes.append({
                    "action": "PARTNER_SYNCHRONIZED",
                    "partner_id": partner.placement_id,
                    "slots": new_slots_str if not is_new_placement else "",
                })

        tt.version = new_version
        tt.updated_at = now
        tt.status = "CONFLICTING" if conflicts else "VALID"
        tt.history.append(
            TimetableHistoryEntry(
                version=new_version,
                timestamp=now,
                action="MANUAL_EDIT" if not conflicts else "OVERRIDE",
                description=desc,
                changes=changes,
                snapshot=prior_snapshot,
            )
        )

        self.save_timetable(tt)
        return tt, conflicts

    def remove_placement(self, timetable_id: str, placement_id: str) -> Optional[Timetable]:
        """Remove a placement from a timetable (freeing the cell)."""
        tt = self.get_timetable(timetable_id)
        if not tt:
            return None

        p = tt.find_placement(placement_id)
        if not p:
            return tt

        prior_snapshot = [pl.to_dict() for pl in tt.placements]
        now = datetime.now().isoformat(timespec="seconds")
        new_version = tt.version + 1
        desc = f"Removed {p.subject_short_name or p.subject_id} ({', '.join(f'{s.day.name} P{s.period}' for s in p.slots)})"

        tt.placements = [pl for pl in tt.placements if pl.placement_id != placement_id]
        tt.version = new_version
        tt.updated_at = now
        tt.status = "INCOMPLETE"
        tt.history.append(
            TimetableHistoryEntry(
                version=new_version,
                timestamp=now,
                action="REMOVED",
                description=desc,
                snapshot=prior_snapshot,
            )
        )
        self.save_timetable(tt)
        return tt

    def undo_last_edit(self, timetable_id: str) -> Optional[Timetable]:
        """Undo the most recent manual edit if history exists."""
        tt = self.get_timetable(timetable_id)
        if not tt or not tt.history:
            return tt

        # Pop the latest history entry
        last_entry = tt.history.pop()
        if last_entry.snapshot is not None:
            tt.placements = [TimetablePlacement.from_dict(p_data) for p_data in last_entry.snapshot]

        tt.version = max(1, tt.version - 1)
        tt.updated_at = datetime.now().isoformat(timespec="seconds")
        self.save_timetable(tt)
        return tt
