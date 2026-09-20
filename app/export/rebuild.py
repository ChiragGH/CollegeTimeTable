"""
Rebuild :class:`~app.models.placement.Placement` objects from the
serialized timetable JSON stored by the web app
(``/api/session/<sid>/generate`` result).

This lets the export API serve downloads even after a server restart,
when only the JSON result (not the live ``ScheduleResult``) survives.
"""

from typing import Dict, List

from app.models.assignment import Assignment
from app.models.enums import ActivityType, Day
from app.models.placement import Placement
from app.models.slot import TimeSlot

from app.export.context import ExportContext


def placements_from_result_data(
    result_data: dict,
    ctx: ExportContext,
) -> List[Placement]:
    """
    Convert a serialized result (as stored in ``session['result']``)
    back into Placement objects suitable for the exporters.

    Missing master fields (branch, semester) fall back to the session
    context; ``block_size`` is inferred from the slot count.
    """
    placements: List[Placement] = []

    for p in result_data.get("placements", []):
        slots = [
            TimeSlot(day=Day[s["day"]], period=int(s["period"]))
            for s in p.get("slots", [])
        ]
        if not slots:
            continue

        assignment = Assignment(
            assignment_id=p.get("assignment_id", ""),
            session_id=ctx.session_id,
            teacher_id=p.get("teacher_id", ""),
            subject_id=p.get("subject_id", ""),
            branch=ctx.branch,
            semester=ctx.semester or 0,
            section=p.get("section", ""),
            group=p.get("group", "ALL"),
            activity_type=_parse_activity(p.get("activity_type")),
            weekly_periods=len(slots),
            room_id=p.get("room_id"),
            block_size=len(slots),
            sessions_per_week=0,
        )
        placements.append(Placement(
            placement_id=p.get("placement_id", ""),
            assignment=assignment,
            slots=slots,
            room_id=p.get("room_id", ""),
        ))

    return placements


def _parse_activity(value) -> ActivityType:
    try:
        return ActivityType(value)
    except (ValueError, TypeError):
        return ActivityType.LECTURE
