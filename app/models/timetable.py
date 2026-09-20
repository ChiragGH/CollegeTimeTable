"""
Timetable domain model and persistent entities.

Represents an independent, persistent timetable instance for a specific
academic context (academic_year, branch, semester, section).
Every timetable instance has its own unique persistent identifier, status,
version history, and collection of TimetablePlacements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.assignment import Assignment
from app.models.enums import ActivityType, Day, RoomType
from app.models.placement import Placement
from app.models.slot import TimeSlot


@dataclass
class TimetablePlacement:
    """
    A scheduled session/placement belonging to a specific Timetable.

    Attributes:
        placement_id:       Unique identifier, e.g. "P_CSE_SEM1_A_1".
        timetable_id:       Parent timetable ID this placement belongs to.
        assignment_id:      Source teaching assignment ID.
        subject_id:         FK to Subjects master data.
        teacher_id:         FK to Teachers master data.
        room_id:            FK to Rooms master data.
        section:            Section label, e.g. "A".
        group:              "ALL", "G1", or "G2".
        activity_type:      LECTURE, PRACTICAL, WORKSHOP, DRAWING, etc.
        slots:              List of occupied TimeSlots.
        block_size:         Number of consecutive periods (e.g. 2 for practicals).
        subject_short_name: Cached human-friendly short name (e.g. "OS", "DE").
        subject_name:       Cached full subject title.
        teacher_name:       Cached teacher full name.
        room_name:          Cached room title/code.
        is_linked_parallel: True if this is a G1/G2 parallel practical session.
        linked_placement_id: Pointer to the partner parallel placement (if any).
    """
    placement_id: str
    timetable_id: str
    assignment_id: str
    subject_id: str
    teacher_id: str
    room_id: str
    section: str
    group: str
    activity_type: ActivityType
    slots: List[TimeSlot]
    block_size: int = 1
    subject_short_name: str = ""
    subject_name: str = ""
    teacher_name: str = ""
    room_name: str = ""
    is_linked_parallel: bool = False
    linked_placement_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert placement to JSON-serializable dictionary."""
        return {
            "placement_id": self.placement_id,
            "timetable_id": self.timetable_id,
            "assignment_id": self.assignment_id,
            "subject_id": self.subject_id,
            "short_name": self.subject_short_name or self.subject_id,
            "subject_short_name": self.subject_short_name or self.subject_id,
            "subject_name": self.subject_name or self.subject_id,
            "teacher_id": self.teacher_id,
            "teacher_name": self.teacher_name or self.teacher_id,
            "room_id": self.room_id,
            "room_name": self.room_name or self.room_id,
            "section": self.section,
            "group": self.group,
            "activity_type": (
                self.activity_type.value
                if isinstance(self.activity_type, ActivityType)
                else str(self.activity_type)
            ),
            "block_size": self.block_size,
            "slots": [
                {"day": s.day.name, "period": s.period}
                for s in self.slots
            ],
            "is_linked_parallel": self.is_linked_parallel,
            "linked_placement_id": self.linked_placement_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TimetablePlacement:
        """Hydrate placement from JSON dictionary."""
        raw_act = data.get("activity_type", "LECTURE")
        try:
            act_type = ActivityType(raw_act)
        except ValueError:
            act_type = ActivityType.LECTURE

        slots: List[TimeSlot] = []
        for s in data.get("slots", []):
            day_name = s.get("day", "MON")
            period = int(s.get("period", 1))
            try:
                day_enum = Day[day_name]
            except KeyError:
                day_enum = Day.MON
            slots.append(TimeSlot(day=day_enum, period=period))

        return cls(
            placement_id=data.get("placement_id", ""),
            timetable_id=data.get("timetable_id", ""),
            assignment_id=data.get("assignment_id", ""),
            subject_id=data.get("subject_id", ""),
            teacher_id=data.get("teacher_id", ""),
            room_id=data.get("room_id", ""),
            section=data.get("section", "A"),
            group=data.get("group", "ALL"),
            activity_type=act_type,
            slots=slots,
            block_size=int(data.get("block_size", max(len(slots), 1))),
            subject_short_name=data.get("subject_short_name") or data.get("short_name", ""),
            subject_name=data.get("subject_name", ""),
            teacher_name=data.get("teacher_name", ""),
            room_name=data.get("room_name", ""),
            is_linked_parallel=bool(data.get("is_linked_parallel", False)),
            linked_placement_id=data.get("linked_placement_id"),
        )


@dataclass
class TimetableHistoryEntry:
    """Audit log entry for a timetable lifecycle or manual edit event."""
    version: int
    timestamp: str
    action: str  # "CREATED", "MANUAL_EDIT", "REGENERATED", "OVERRIDE", "REMOVED"
    description: str
    changes: List[Dict[str, Any]] = field(default_factory=list)
    snapshot: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "version": self.version,
            "timestamp": self.timestamp,
            "action": self.action,
            "description": self.description,
            "changes": self.changes,
        }
        if self.snapshot is not None:
            d["snapshot"] = self.snapshot
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TimetableHistoryEntry:
        return cls(
            version=int(data.get("version", 1)),
            timestamp=data.get("timestamp", ""),
            action=data.get("action", "EDIT"),
            description=data.get("description", ""),
            changes=data.get("changes", []),
            snapshot=data.get("snapshot"),
        )


@dataclass
class Timetable:
    """
    Persistent timetable entity.

    Represents a concrete generated and editable timetable instance
    associated with an academic year, branch, semester, and section.
    """
    timetable_id: str
    academic_year: str
    branch: str
    semester: int
    section: str
    status: str = "VALID"  # "VALID", "CONFLICTING", "INCOMPLETE", "DRAFT"
    placements: List[TimetablePlacement] = field(default_factory=list)
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    generation_seed: Optional[int] = None
    session_id: Optional[str] = None
    history: List[TimetableHistoryEntry] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Human-friendly timetable name, e.g. 'CSE — Semester 1 — Section A'."""
        return f"{self.branch} — Semester {self.semester} — Section {self.section}"

    @property
    def full_context_code(self) -> str:
        """Unique standard context code, e.g. 'CSE-SEM1-A-2026-27'."""
        return f"{self.branch}-SEM{self.semester}-{self.section}-{self.academic_year}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert timetable entity to JSON-serializable dictionary."""
        return {
            "timetable_id": self.timetable_id,
            "display_name": self.display_name,
            "context_code": self.full_context_code,
            "academic_year": self.academic_year,
            "branch": self.branch,
            "semester": self.semester,
            "section": self.section,
            "status": self.status,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "generation_seed": self.generation_seed,
            "session_id": self.session_id,
            "placements_count": len(self.placements),
            "placements": [p.to_dict() for p in self.placements],
            "history": [h.to_dict() for h in self.history],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Timetable:
        """Hydrate Timetable entity from JSON dictionary."""
        placements = [
            TimetablePlacement.from_dict(p)
            for p in data.get("placements", [])
        ]
        history = [
            TimetableHistoryEntry.from_dict(h)
            for h in data.get("history", [])
        ]
        return cls(
            timetable_id=data.get("timetable_id", ""),
            academic_year=data.get("academic_year", ""),
            branch=data.get("branch", ""),
            semester=int(data.get("semester", 1)),
            section=data.get("section", "A"),
            status=data.get("status", "DRAFT"),
            placements=placements,
            version=int(data.get("version", 1)),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            generation_seed=data.get("generation_seed"),
            session_id=data.get("session_id"),
            history=history,
            metadata=data.get("metadata", {}),
        )

    def find_placement(self, placement_id: str) -> Optional[TimetablePlacement]:
        """Find placement by id."""
        for p in self.placements:
            if p.placement_id == placement_id:
                return p
        return None

    def get_slot_occupants(self, day_name: str, period: int) -> List[TimetablePlacement]:
        """Return all placements occupying a specific (day, period) slot."""
        occupants = []
        for p in self.placements:
            for s in p.slots:
                if s.day.name == day_name and s.period == period:
                    occupants.append(p)
                    break
        return occupants

    def to_engine_placements(self) -> List[Placement]:
        """
        Convert TimetablePlacements to domain Placement instances.

        Used for existing export engines and conflict auditors.
        """
        engine_placements: List[Placement] = []
        for tp in self.placements:
            assignment = Assignment(
                assignment_id=tp.assignment_id or tp.placement_id,
                session_id=self.session_id or self.timetable_id,
                teacher_id=tp.teacher_id,
                subject_id=tp.subject_id,
                branch=self.branch,
                semester=self.semester,
                section=tp.section,
                group=tp.group,
                activity_type=tp.activity_type,
                weekly_periods=len(tp.slots),
                room_id=tp.room_id,
                block_size=tp.block_size,
                sessions_per_week=1,
            )
            engine_placements.append(Placement(
                placement_id=tp.placement_id,
                assignment=assignment,
                slots=list(tp.slots),
                room_id=tp.room_id,
            ))
        return engine_placements
