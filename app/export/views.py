"""
Timetable view builders.

Turn a list of :class:`~app.models.placement.Placement` objects into
render-agnostic :class:`GridView` models — one per entity for each of
the five required views:

========  ================  ==========================================
View      Entity            Audience
========  ================  ==========================================
class     branch-semester   HOD — all sections of a class side by side
section   section           Students — one section's weekly grid
group     section+group     Practical sub-groups (G1/G2) students
teacher   teacher           Faculty — personal engagements
room      room              Office/admin — room occupancy
========  ================  ==========================================

Grid cells know about:

* **practical blocks** — every slot of a multi-slot placement shares a
  ``block_id``; the start cell carries the entries and the span, so
  renderers can merge columns (XLSX/PDF) or repeat content (CSV);
* **parallel groups** — G1/G2 entries land in the same cell so the
  split is visible at a glance, and group views annotate the
  counterpart group running in parallel;
* **conflicts** — the caller passes a :class:`ConflictReport`; any
  conflicted (placement, slot) is flagged on the cell.

Views contain no formatting: CSV/XLSX/PDF renderers consume them.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from app.models.assignment import Assignment
from app.models.enums import ActivityType, Day
from app.models.placement import Placement
from app.models.slot import TimeSlot

from app.export.conflicts import ConflictReport, conflicted_slot_keys
from app.export.context import ExportContext
from app.export.grid import (
    COL_LUNCH,
    DAYS,
    GRID_COLUMNS,
    day_sort_key,
    column_index,
)

VIEW_CLASS = "class"
VIEW_SECTION = "section"
VIEW_GROUP = "group"
VIEW_TEACHER = "teacher"
VIEW_ROOM = "room"

#: All supported views in canonical order.
VIEW_KINDS: Tuple[str, ...] = (
    VIEW_CLASS, VIEW_SECTION, VIEW_GROUP, VIEW_TEACHER, VIEW_ROOM,
)

#: Human names for legends / UI.
VIEW_TITLES: Dict[str, str] = {
    VIEW_CLASS: "Class-wise Timetable",
    VIEW_SECTION: "Section-wise Timetable",
    VIEW_GROUP: "Group-wise Timetable",
    VIEW_TEACHER: "Teacher-wise Timetable",
    VIEW_ROOM: "Room-wise Timetable",
}

#: Activity type → display tag used inside cells (LECTURE is implicit).
ACTIVITY_TAGS: Dict[str, str] = {
    ActivityType.LECTURE.value: "",
    ActivityType.PRACTICAL.value: "Practical",
    ActivityType.WORKSHOP.value: "Workshop",
    ActivityType.DRAWING.value: "Drawing",
    ActivityType.PROJECT.value: "Project",
    ActivityType.TRAINING.value: "Training",
}


# ----------------------------------------------------------------------
# View model
# ----------------------------------------------------------------------

@dataclass
class CellEntry:
    """
    One activity inside a grid cell (a cell may hold several — e.g. the
    two parallel groups of a practical, or multiple sections in a
    class view).
    """
    lines: List[str]
    group: str = "ALL"
    activity: str = ActivityType.LECTURE.value
    section: str = ""
    subject_id: str = ""
    teacher_id: str = ""
    room_id: str = ""
    placement_id: str = ""
    conflict: bool = False
    #: Dimmed annotation (e.g. "Parallel G2: …") — not a booking.
    is_note: bool = False


@dataclass
class BlockInfo:
    """
    One placement's block footprint through a cell.

    A cell may host several blocks at once — e.g. in the class view,
    two sections running practicals across the same periods — so block
    metadata is tracked per placement, never per cell.
    """
    placement_id: str
    span: int
    is_start: bool


@dataclass
class GridCell:
    """Everything happening in one (day, column) for one entity."""
    entries: List[CellEntry] = field(default_factory=list)
    #: Block footprints of the placements covering this cell.
    blocks: List[BlockInfo] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.entries

    @property
    def conflict(self) -> bool:
        return any(e.conflict for e in self.entries)


@dataclass
class GridView:
    """One render-ready timetable grid for one entity."""
    view_kind: str
    entity_id: str
    title: str
    subtitle: str
    cells: Dict[Tuple[int, int], GridCell] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)   # warnings / footnotes
    weekly_periods: int = 0                          # booked periods total
    activities_present: List[str] = field(default_factory=list)

    def cell(self, day_index: int, col_index: int) -> GridCell:
        return self.cells.get((day_index, col_index), GridCell())


# ----------------------------------------------------------------------
# Public builders
# ----------------------------------------------------------------------

def build_views(
    placements: Sequence[Placement],
    ctx: ExportContext,
    report: ConflictReport,
    view_kind: str,
) -> List[GridView]:
    """Build all entity grids for one view kind, in display order."""
    builders: Dict[str, Callable[..., List[GridView]]] = {
        VIEW_CLASS: build_class_views,
        VIEW_SECTION: build_section_views,
        VIEW_GROUP: build_group_views,
        VIEW_TEACHER: build_teacher_views,
        VIEW_ROOM: build_room_views,
    }
    if view_kind not in builders:
        raise ValueError(f"Unknown view kind: {view_kind!r}")
    return builders[view_kind](placements, ctx, report)


def build_class_views(
    placements: Sequence[Placement],
    ctx: ExportContext,
    report: ConflictReport,
) -> List[GridView]:
    """
    One grid per class (branch-semester).  Cells stack every section's
    activities, each prefixed with its section label, so the HOD sees
    the complete picture for the class including parallel G1/G2 splits.
    """
    classes: Dict[Tuple[str, int], List[Placement]] = {}
    for p in placements:
        key = _class_key(p.assignment, ctx)
        classes.setdefault(key, []).append(p)

    views = []
    for (branch, semester) in sorted(classes, key=lambda k: (k[0], k[1])):
        items = classes[(branch, semester)]
        sections_in = sorted({_section_label(p.assignment) for p in items})

        def entry_fn(p: Placement, partner, conflicted: bool) -> List[CellEntry]:
            a = p.assignment
            sec = _section_label(a)
            # Compact display: class cells stack several sections, so
            # keep lines short enough to avoid wrapping.
            lines = [f"{sec} · {ctx.subject_display(a.subject_id, max_len=20)}"]
            lines.extend(_group_room_lines(p, partner, ctx))
            return [CellEntry(
                lines=lines, group=a.group,
                activity=_activity_value(a.activity_type),
                section=sec, subject_id=a.subject_id,
                teacher_id=a.teacher_id, room_id=p.room_id,
                placement_id=p.placement_id, conflict=conflicted,
            )]

        views.append(_build_grid(
            view_kind=VIEW_CLASS, entity_id=ExportContext.class_key(branch, semester),
            title=ExportContext.class_title(branch, semester),
            subtitle=_subtitle(ctx, sections=sections_in),
            items=_pair_parallel(items),
            ctx=ctx, report=report, entry_fn=entry_fn,
            weekly_periods=sum(len(p.slots) for p in items),
        ))
    return views


def build_section_views(
    placements: Sequence[Placement],
    ctx: ExportContext,
    report: ConflictReport,
) -> List[GridView]:
    """
    One grid per section — the student-facing view.  Parallel G1/G2
    practicals of the same subject are combined into a single cell
    entry with one labelled line per group::

        3.7 Data Structures Lab
        G1 · RJS — CC1 (Practical)
        G2 · SRP — CC2 (Practical)

    so the split is obvious at a glance and the cell still merges
    across the block's period columns.
    """
    sections: Dict[str, List[Placement]] = {}
    for p in placements:
        sections.setdefault(_section_key(p.assignment, ctx), []).append(p)

    conflict_keys = conflicted_slot_keys(report)

    views = []
    for sec_key in sorted(sections):
        items = sections[sec_key]
        label = _split_section_key(sec_key)[2]

        def entry_fn(p: Placement, partner, conflicted: bool) -> List[CellEntry]:
            a = p.assignment
            lines = [ctx.subject_display(a.subject_id)]
            lines.extend(_group_room_lines(p, partner, ctx))
            return [CellEntry(
                lines=lines, group=a.group,
                activity=_activity_value(a.activity_type),
                section=label, subject_id=a.subject_id,
                teacher_id=a.teacher_id, room_id=p.room_id,
                placement_id=p.placement_id, conflict=conflicted,
            )]

        views.append(_build_grid(
            view_kind=VIEW_SECTION, entity_id=sec_key,
            title=f"Section {sec_key}",
            subtitle=_subtitle(ctx, sections=[label]),
            items=_pair_parallel(items),
            ctx=ctx, report=report, entry_fn=entry_fn,
            weekly_periods=sum(len(p.slots) for p in items),
        ))
    return views


def build_group_views(
    placements: Sequence[Placement],
    ctx: ExportContext,
    report: ConflictReport,
) -> List[GridView]:
    """
    One grid per (section, group) — the exact weekly schedule a student
    of that group follows: every ``ALL`` activity plus the group's own
    practicals.  When the counterpart group (G1↔G2) runs in parallel,
    a dimmed annotation shows what it is doing and where, so the
    parallel assignment is visible without opening the other view.
    """
    by_section: Dict[str, List[Placement]] = {}
    for p in placements:
        by_section.setdefault(_section_key(p.assignment, ctx), []).append(p)

    views = []
    for sec_key in sorted(by_section):
        items = by_section[sec_key]
        groups = _groups_for_section(items, sec_key, ctx)
        for group in groups:
            own = [p for p in items
                   if p.assignment.group in ("ALL", group)]
            other = "G2" if group == "G1" else "G1"
            others = [p for p in items if p.assignment.group == other]
            other_by_slot: Dict[Tuple[str, int], Placement] = {}
            for p in others:
                for s in p.slots:
                    other_by_slot[(s.day.name, s.period)] = p

            def entry_fn(
                p: Placement, _extra,
                conflicted: bool, _group=group, _other=other,
                _other_by_slot=other_by_slot,
            ) -> List[CellEntry]:
                a = p.assignment
                room_part = _room_part(p, ctx)
                lines = [
                    ctx.subject_display(a.subject_id),
                    ctx.teacher_name(a.teacher_id) + room_part,
                ]
                entries = [CellEntry(
                    lines=lines, group=a.group,
                    activity=_activity_value(a.activity_type),
                    section=a.section, subject_id=a.subject_id,
                    teacher_id=a.teacher_id, room_id=p.room_id,
                    placement_id=p.placement_id, conflict=conflicted,
                )]

                # Parallel counterpart annotation (own-group practicals only)
                if a.group == _group:
                    for s in p.slots:
                        op = _other_by_slot.get((s.day.name, s.period))
                        if op is not None:
                            entries.append(CellEntry(
                                lines=[
                                    f"Parallel {_other}: "
                                    f"{ctx.subject_display(op.assignment.subject_id)}"
                                    f" · {ctx.room_name(op.room_id)}",
                                ],
                                group=_other,
                                activity=_activity_value(op.assignment.activity_type),
                                room_id=op.room_id,
                                placement_id=op.placement_id,
                                is_note=True,
                            ))
                            break
                return entries

            entity_id = f"{sec_key}-{group}"
            views.append(_build_grid(
                view_kind=VIEW_GROUP, entity_id=entity_id,
                title=f"Group {group} — Section {sec_key}",
                subtitle=_subtitle(ctx, sections=[_section_label(
                    next(iter(items)).assignment)]),
                items=[(p, None) for p in own],
                ctx=ctx, report=report, entry_fn=entry_fn,
                weekly_periods=sum(len(p.slots) for p in own),
            ))
    return views


def build_teacher_views(
    placements: Sequence[Placement],
    ctx: ExportContext,
    report: ConflictReport,
) -> List[GridView]:
    """One grid per teacher with every engagement across all sections."""
    by_teacher: Dict[str, List[Placement]] = {}
    for p in placements:
        by_teacher.setdefault(p.assignment.teacher_id, []).append(p)

    views = []
    for tid in sorted(by_teacher):
        items = by_teacher[tid]
        dept = ctx.teacher_department(tid)

        def entry_fn(p: Placement, extra, conflicted: bool) -> List[CellEntry]:
            a = p.assignment
            sec_group = _section_key(a, ctx) + (
                f" · {a.group}" if a.group != "ALL" else ""
            )
            lines = [
                ctx.subject_display(a.subject_id),
                sec_group,
                ctx.room_name(p.room_id) + _activity_suffix(a.activity_type),
            ]
            return [CellEntry(
                lines=lines, group=a.group,
                activity=_activity_value(a.activity_type),
                section=a.section, subject_id=a.subject_id,
                teacher_id=a.teacher_id, room_id=p.room_id,
                placement_id=p.placement_id, conflict=conflicted,
            )]

        load = sum(len(p.slots) for p in items)
        views.append(_build_grid(
            view_kind=VIEW_TEACHER, entity_id=tid,
            title=f"{ctx.teacher_name(tid)} ({tid})"
            + (f" — {dept}" if dept else ""),
            subtitle=f"Weekly load: {load} periods",
            items=[(p, None) for p in items],
            ctx=ctx, report=report, entry_fn=entry_fn,
            weekly_periods=load,
        ))
    return views


def build_room_views(
    placements: Sequence[Placement],
    ctx: ExportContext,
    report: ConflictReport,
) -> List[GridView]:
    """One grid per room showing its full weekly occupancy."""
    by_room: Dict[str, List[Placement]] = {}
    for p in placements:
        by_room.setdefault(p.room_id, []).append(p)

    views = []
    for rid in sorted(by_room, key=lambda r: ctx.room_name(r)):
        items = by_room[rid]
        rtype = ctx.room_type(rid) or ""
        rname = ctx.room_name(rid)
        owner = _room_owner(rid, ctx)

        def entry_fn(p: Placement, extra, conflicted: bool) -> List[CellEntry]:
            a = p.assignment
            sec_group = _section_key(a, ctx) + (
                f" · {a.group}" if a.group != "ALL" else ""
            )
            lines = [
                ctx.subject_display(a.subject_id),
                ctx.teacher_name(a.teacher_id),
                sec_group,
            ]
            return [CellEntry(
                lines=lines, group=a.group,
                activity=_activity_value(a.activity_type),
                section=a.section, subject_id=a.subject_id,
                teacher_id=a.teacher_id, room_id=p.room_id,
                placement_id=p.placement_id, conflict=conflicted,
            )]

        booked = sum(len(p.slots) for p in items)
        subtitle_bits = [t for t in (rtype, owner) if t]
        subtitle = (
            f"{' · '.join(subtitle_bits)} — Booked: {booked} periods"
            if subtitle_bits else f"Booked: {booked} periods"
        )
        views.append(_build_grid(
            view_kind=VIEW_ROOM, entity_id=rid,
            title=f"Room {rname} ({rid})",
            subtitle=subtitle,
            items=[(p, None) for p in items],
            ctx=ctx, report=report, entry_fn=entry_fn,
            weekly_periods=booked,
        ))
    return views


# ----------------------------------------------------------------------
# Grid assembly (shared by all builders)
# ----------------------------------------------------------------------

def _build_grid(
    view_kind: str,
    entity_id: str,
    title: str,
    subtitle: str,
    items: Sequence[Tuple[Placement, object]],
    ctx: ExportContext,
    report: ConflictReport,
    entry_fn: Callable[[Placement, object, bool], List[CellEntry]],
    weekly_periods: int = 0,
) -> GridView:
    """
    Assemble a :class:`GridView` from ``(placement, extra)`` items.

    Detects practical blocks (multi-slot placements on one day), marks
    continuation slots, and flags conflicted (placement, slot) pairs
    from the audit report.
    """
    conflict_keys = conflicted_slot_keys(report)
    view = GridView(
        view_kind=view_kind, entity_id=entity_id,
        title=title, subtitle=subtitle,
        weekly_periods=weekly_periods,
    )

    activities: List[str] = []
    out_of_grid = 0

    for placement, extra in _sorted_items(items):
        a = placement.assignment
        slots: List[TimeSlot] = list(placement.slots)

        # Slots outside the Mon–Fri grid are reported, never shown.
        known_days = [s for s in slots if day_sort_key(s.day) < len(DAYS)]
        out_of_grid += len(slots) - len(known_days)

        # Build the entries once per placement (identical across slots).
        conflicted = any(
            (placement.placement_id, s.day.name, s.period) in conflict_keys
            for s in known_days
        )
        entries = entry_fn(placement, extra, conflicted)
        for e in entries:
            if e.activity not in activities:
                activities.append(e.activity)

        # Group the placement's slots per day, then split into
        # consecutive runs — each run becomes one mergeable block.
        by_day: Dict[int, List[TimeSlot]] = {}
        for s in known_days:
            by_day.setdefault(day_sort_key(s.day), []).append(s)

        for day_idx, day_slots in sorted(by_day.items()):
            for run in _consecutive_runs(day_slots):
                block_size = len(run)
                for i, slot in enumerate(run):
                    col = column_index(slot.period)
                    if col is None:
                        out_of_grid += 1
                        continue
                    key = (day_idx, col)
                    cell = view.cells.get(key)
                    if cell is None:
                        cell = GridCell()
                        view.cells[key] = cell
                    # Entries live on every covered slot.  Renderers
                    # merge a block only when it shares its columns
                    # with no other placement; overlapping blocks
                    # simply repeat their content per column.
                    cell.entries.extend(entries)
                    if block_size > 1:
                        cell.blocks.append(BlockInfo(
                            placement_id=placement.placement_id,
                            span=block_size,
                            is_start=(i == 0),
                        ))

    if out_of_grid:
        view.notes.append(
            f"{out_of_grid} slot(s) fell outside the Mon–Fri / P1–P7 grid "
            f"and are not shown."
        )

    view.activities_present = activities
    return view


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------

_GROUP_ORDER = {"ALL": 0, "G1": 1, "G2": 2}


def _sorted_items(
    items: Sequence[Tuple[Placement, object]],
) -> List[Tuple[Placement, object]]:
    """Deterministic cell-stacking order: section, group (ALL first),
    then placement id."""
    def key(item: Tuple[Placement, object]):
        a = item[0].assignment
        return (
            a.section, _GROUP_ORDER.get(a.group, 9),
            item[0].placement_id,
        )
    return sorted(items, key=key)


def _consecutive_runs(slots: List[TimeSlot]) -> List[List[TimeSlot]]:
    """Split a day's slots into maximal consecutive period runs."""
    ordered = sorted(slots, key=lambda s: s.period)
    runs: List[List[TimeSlot]] = []
    current: List[TimeSlot] = []
    for s in ordered:
        if current and s.period == current[-1].period + 1:
            current.append(s)
        else:
            if current:
                runs.append(current)
            current = [s]
    if current:
        runs.append(current)
    return runs


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------

def _pair_parallel(
    items: List[Placement],
) -> List[Tuple[Placement, Optional[Placement]]]:
    """
    Combine G1/G2 placements of the same subject and section with
    *identical* slot sets into ``(g1_placement, g2_placement)`` units so
    renderers show one entry with a line per group.  Misaligned groups
    (a C6 conflict) stay separate and therefore fully visible.
    """
    index: Dict[Tuple[str, str, str, frozenset], Dict[str, Placement]] = {}
    for p in items:
        a = p.assignment
        if a.group not in ("G1", "G2"):
            continue
        key = (
            a.section, a.subject_id, _activity_value(a.activity_type),
            frozenset(p.slots),
        )
        index.setdefault(key, {})[a.group] = p

    consumed = set()
    result: List[Tuple[Placement, Optional[Placement]]] = []
    for p in items:
        if p.placement_id in consumed:
            continue
        a = p.assignment
        if a.group == "G1":
            key = (a.section, a.subject_id, _activity_value(a.activity_type),
                   frozenset(p.slots))
            partner = index.get(key, {}).get("G2")
            if partner is not None and partner.placement_id != p.placement_id:
                consumed.add(partner.placement_id)
                result.append((p, partner))
                continue
        result.append((p, None))
    return result


def _group_room_lines(
    p: Placement,
    partner: Optional[Placement],
    ctx: ExportContext,
) -> List[str]:
    """
    The ``G1 · teacher — room`` line(s) for a cell entry: one line for a
    whole-section activity, two labelled lines for a parallel pair.
    """
    def _line(placement: Placement, group: str) -> str:
        a = placement.assignment
        return (
            f"{group} · {ctx.teacher_name(a.teacher_id)}"
            f"{_room_part(placement, ctx)}"
        )

    a = p.assignment
    if a.group == "ALL":
        return [f"{ctx.teacher_name(a.teacher_id)}{_room_part(p, ctx)}"]

    lines = [_line(p, a.group)]
    if partner is not None:
        lines.append(_line(partner, partner.assignment.group))
    return lines


def _class_key(a: Assignment, ctx: ExportContext) -> Tuple[str, int]:
    branch = a.branch or ctx.branch
    semester = a.semester if a.semester else (ctx.semester or 0)
    return (branch, semester)


def _section_key(a: Assignment, ctx: ExportContext) -> str:
    branch = a.branch or ctx.branch or ""
    semester = a.semester if a.semester else (ctx.semester or "")
    return f"{branch}-{semester}-{a.section}"


def _split_section_key(key: str) -> Tuple[str, object, str]:
    """``CSE-3-A`` → (``CSE``, ``3``, ``A``); tolerates dashes in branch."""
    branch, sem, label = key.split("-", 2)
    try:
        return branch, int(sem), label
    except ValueError:
        return branch, sem, label


def _section_label(a: Assignment) -> str:
    return a.section


def _groups_for_section(
    items: List[Placement], sec_key: str, ctx: ExportContext,
) -> List[str]:
    """Groups to emit for a section: G1/G2 when either is used,
    nothing when the section has no grouping at all."""
    present = {p.assignment.group for p in items}
    declared = ctx.groups_of_section(_split_section_key(sec_key)[2])
    groups = [g for g in ("G1", "G2")
              if g in present or g in declared]
    # Only emit a group view when at least one group is actually used —
    # a section with ALL-only activities has no subgroup split.
    if not ({"G1", "G2"} & present):
        return []
    return groups


def _group_suffix(group: str) -> str:
    return f" · {group}" if group != "ALL" else ""


def _room_part(p: Placement, ctx: ExportContext) -> str:
    """`` — CC1`` plus an activity tag for non-lectures."""
    return f" — {ctx.room_name(p.room_id)}{_activity_suffix(p.assignment.activity_type)}"


def _activity_suffix(activity_type) -> str:
    val = _activity_value(activity_type)
    tag = ACTIVITY_TAGS.get(val, val)
    return f" ({tag})" if tag else ""


def _room_owner(room_id: str, ctx: ExportContext) -> str:
    room = ctx.rooms.get(room_id)
    return (room.branch or "Shared") if room else ""


def _activity_value(activity_type) -> str:
    return (
        activity_type.value
        if isinstance(activity_type, ActivityType)
        else str(activity_type)
    )


def _subtitle(ctx: ExportContext, sections: List[str]) -> str:
    bits = [ctx.session_id]
    if ctx.academic_year:
        bits.append(ctx.academic_year)
    if sections:
        bits.append("Sections: " + ", ".join(sections))
    return " · ".join(bits)
