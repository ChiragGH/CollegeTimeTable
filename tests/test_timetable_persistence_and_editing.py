"""
Tests for Timetable persistence, multi-timetable coexistence, workspace filtering,
and interactive manual cell editing.
"""

import pytest
import shutil
import tempfile
from typing import List

from app.models.enums import ActivityType, Day
from app.models.assignment import Assignment
from app.models.slot import TimeSlot
from app.models.placement import Placement
from app.models.timetable import Timetable, TimetablePlacement, TimetableHistoryEntry
from app.engine.timetable_manager import TimetableManager
from app.engine.scheduler import ScheduleResult


@pytest.fixture
def temp_tt_dir():
    d = tempfile.mkdtemp(prefix="tt_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def manager(temp_tt_dir):
    return TimetableManager(timetables_dir=temp_tt_dir)


def make_assignment(aid="A001", tid="T001", sid="SUB001", branch="CSE", sem=4, sec="A", grp="ALL",
                    act=ActivityType.LECTURE, periods=3, block=1, sessions=3):
    return Assignment(
        assignment_id=aid,
        session_id="sess1",
        teacher_id=tid,
        subject_id=sid,
        branch=branch,
        semester=sem,
        section=sec,
        group=grp,
        activity_type=act,
        weekly_periods=periods,
        block_size=block,
        sessions_per_week=sessions,
    )


def make_placement(pid: str, tid: str, aid: str, sub: str, teacher: str, room: str,
                   sec: str = "A", grp: str = "ALL", act: ActivityType = ActivityType.LECTURE,
                   day: Day = Day.MON, periods: List[int] = None, block_size: int = 1,
                   is_linked_parallel: bool = False, linked_placement_id: str = None) -> TimetablePlacement:
    if periods is None:
        periods = [1]
    slots = [TimeSlot(day=day, period=p) for p in periods]
    return TimetablePlacement(
        placement_id=pid,
        timetable_id=tid,
        assignment_id=aid,
        subject_id=sub,
        teacher_id=teacher,
        room_id=room,
        section=sec,
        group=grp,
        activity_type=act,
        slots=slots,
        block_size=block_size,
        is_linked_parallel=is_linked_parallel,
        linked_placement_id=linked_placement_id,
    )


class TestTimetableModel:
    def test_placement_to_and_from_dict(self):
        p = make_placement("PL001", "TT001", "A001", "CS401", "T001", "R101", day=Day.MON, periods=[1])
        d = p.to_dict()
        assert d["placement_id"] == "PL001"
        assert d["slots"] == [{"day": "MON", "period": 1}]

        p2 = TimetablePlacement.from_dict(d)
        assert p2.placement_id == p.placement_id
        assert p2.subject_id == p.subject_id
        assert p2.slots[0].day == Day.MON
        assert p2.slots[0].period == 1

    def test_timetable_serialization_and_bridge(self):
        tt = Timetable(
            timetable_id="TT_CSE_4_A",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("P1", "TT_CSE_4_A", "A1", "CS401", "T1", "R1", day=Day.MON, periods=[1])
            ]
        )
        data = tt.to_dict()
        assert data["timetable_id"] == "TT_CSE_4_A"
        assert len(data["placements"]) == 1

        tt_restored = Timetable.from_dict(data)
        assert tt_restored.timetable_id == tt.timetable_id
        assert len(tt_restored.placements) == 1

        # Test engine placements bridge
        eng_placements = tt.to_engine_placements()
        assert len(eng_placements) == 1
        assert eng_placements[0].placement_id == "P1"
        assert eng_placements[0].assignment.teacher_id == "T1"
        assert eng_placements[0].slots[0].period == 1


class TestMultiTimetableCoexistence:
    def test_coexistence_and_isolation(self, manager):
        """Verify generating multiple timetables across sections and branches
        coexist simultaneously with unique IDs without overwriting."""
        a_sec_a = make_assignment(aid="A1", sec="A", branch="CSE", sem=4)
        a_sec_b = make_assignment(aid="A2", sec="B", branch="CSE", sem=4)
        a_ece_a = make_assignment(aid="A3", sec="A", branch="ECE", sem=4)

        p1 = Placement("PL1", a_sec_a, [TimeSlot(Day.MON, 1)], "R101")
        p2 = Placement("PL2", a_sec_b, [TimeSlot(Day.MON, 1)], "R102")
        p3 = Placement("PL3", a_ece_a, [TimeSlot(Day.MON, 1)], "R103")

        res_cse = ScheduleResult(
            placements=[p1, p2],
            unscheduled=[],
        )
        res_ece = ScheduleResult(
            placements=[p3],
            unscheduled=[],
        )

        tt_cse = manager.create_from_schedule_result(
            session_id="sess_cse",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            schedule_result=res_cse,
        )
        assert len(tt_cse) == 2
        id_cse_a = tt_cse[0].timetable_id
        id_cse_b = tt_cse[1].timetable_id
        assert id_cse_a != id_cse_b

        tt_ece = manager.create_from_schedule_result(
            session_id="sess_ece",
            academic_year="2026-27",
            branch="ECE",
            semester=4,
            schedule_result=res_ece,
        )
        assert len(tt_ece) == 1
        id_ece_a = tt_ece[0].timetable_id

        # Verify all 3 exist in manager
        all_tt = manager.list_timetables()
        assert len(all_tt) == 3
        ids = {t.timetable_id for t in all_tt}
        assert id_cse_a in ids
        assert id_cse_b in ids
        assert id_ece_a in ids

        # Filter by branch
        cse_only = manager.list_timetables(branch="CSE")
        assert len(cse_only) == 2
        assert all(t.branch == "CSE" for t in cse_only)

        ece_only = manager.list_timetables(branch="ECE")
        assert len(ece_only) == 1
        assert ece_only[0].branch == "ECE"

    def test_duplicate_prompt_and_versioning(self, manager):
        """When a timetable for the same context already exists:
        - find_existing finds it
        - replace mode overwrites in place
        - new_version mode creates version 2 with distinct identity"""
        a1 = make_assignment(sec="A", branch="CSE", sem=4)
        p1 = Placement("PL1", a1, [TimeSlot(Day.MON, 1)], "R101")
        res1 = ScheduleResult(placements=[p1], unscheduled=[])

        # Initial creation
        created1 = manager.create_from_schedule_result(
            session_id="sess1",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            schedule_result=res1,
        )
        orig_id = created1[0].timetable_id
        assert created1[0].version == 1

        # Check existing
        existing = manager.find_existing("2026-27", "CSE", 4, "A")
        assert len(existing) > 0
        assert existing[0].timetable_id == orig_id

        # Mode: new_version
        created_v2 = manager.create_from_schedule_result(
            session_id="sess1",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            schedule_result=res1,
            mode="new_version",
        )
        v2_tt = created_v2[0]
        assert v2_tt.version == 2
        assert v2_tt.timetable_id != orig_id

        # Both versions exist
        all_tt = manager.list_timetables(branch="CSE", semester=4, section="A")
        assert len(all_tt) == 2

    def test_clone_and_delete(self, manager):
        a1 = make_assignment()
        p1 = Placement("PL1", a1, [TimeSlot(Day.MON, 1)], "R101")
        res1 = ScheduleResult(placements=[p1], unscheduled=[])
        created = manager.create_from_schedule_result(
            session_id="sess1",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            schedule_result=res1,
        )[0]

        # Duplicate
        cloned = manager.duplicate_timetable(created.timetable_id)
        assert cloned is not None
        assert cloned.timetable_id != created.timetable_id
        assert cloned.version > created.version
        assert len(cloned.placements) == len(created.placements)

        # Delete original
        assert manager.delete_timetable(created.timetable_id) is True
        assert manager.get_timetable(created.timetable_id) is None
        assert manager.get_timetable(cloned.timetable_id) is not None


class TestManualCellEditing:
    def test_basic_cell_edit(self, manager):
        """Edit subject, teacher, room, day, period for an existing placement."""
        tt = Timetable(
            timetable_id="TT_EDIT_1",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("PL_1", "TT_EDIT_1", "A1", "CS401", "T001", "R101", day=Day.MON, periods=[1])
            ]
        )
        manager.save_timetable(tt)

        # Edit placement to TUE Period 2, new teacher and room
        updated_tt, conflicts = manager.apply_placement_edit(
            timetable_id="TT_EDIT_1",
            placement_id="PL_1",
            new_data={
                "subject_id": "CS402",
                "teacher_id": "T002",
                "room_id": "R102",
                "activity_type": "LECTURE",
                "group": "ALL",
                "day": "TUE",
                "period": 2,
            }
        )

        assert len(conflicts) == 0
        p = updated_tt.find_placement("PL_1")
        assert p.subject_id == "CS402"
        assert p.teacher_id == "T002"
        assert p.room_id == "R102"
        assert p.slots[0].day == Day.TUE
        assert p.slots[0].period == 2
        assert updated_tt.version == 2
        assert len(updated_tt.history) == 1
        assert "v2" in updated_tt.history[0].description or updated_tt.history[0].version == 2

    def test_recess_prohibition_on_edit(self, manager):
        """Attempting to place a block crossing recess raises ValueError."""
        tt = Timetable(
            timetable_id="TT_RECESS_TEST",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("PL_REC", "TT_RECESS_TEST", "A1", "CS401", "T001", "R101", day=Day.MON, periods=[1])
            ]
        )
        manager.save_timetable(tt)

        # Period 4 with block_size=2 covers periods [4, 5] which bridges across Recess
        with pytest.raises(ValueError, match="Recess"):
            manager.apply_placement_edit(
                timetable_id="TT_RECESS_TEST",
                placement_id="PL_REC",
                new_data={
                    "subject_id": "CS401",
                    "teacher_id": "T001",
                    "room_id": "R101",
                    "activity_type": "LECTURE",
                    "group": "ALL",
                    "day": "MON",
                    "period": 4,
                    "block_size": 2,
                }
            )

    def test_practical_block_movement_as_unit(self, manager):
        """Moving a 2-period practical from Period 1 to Period 2
        moves both period 1 and 2 to periods 2 and 3 as a single unit."""
        tt = Timetable(
            timetable_id="TT_PRACTICAL_BLOCK",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("PL_PRACTICAL_1", "TT_PRACTICAL_BLOCK", "A_PRAC", "CS401P", "T001", "LAB1",
                               grp="G1", act=ActivityType.PRACTICAL, day=Day.MON, periods=[1, 2], block_size=2)
            ]
        )
        manager.save_timetable(tt)

        # Move to WED Period 2
        updated_tt, conflicts = manager.apply_placement_edit(
            timetable_id="TT_PRACTICAL_BLOCK",
            placement_id="PL_PRACTICAL_1",
            new_data={
                "subject_id": "CS401P",
                "teacher_id": "T001",
                "room_id": "LAB1",
                "activity_type": "PRACTICAL",
                "group": "G1",
                "day": "WED",
                "period": 2,
                "block_size": 2,
            }
        )

        p = updated_tt.find_placement("PL_PRACTICAL_1")
        assert p.slots[0].day == Day.WED
        assert [s.period for s in p.slots] == [2, 3]
        assert p.block_size == 2

    def test_parallel_practical_synchronization(self, manager):
        """G1 and G2 practicals linked as parallel sessions move together to target slot."""
        tt = Timetable(
            timetable_id="TT_PARALLEL_SYNC",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("PL_G1", "TT_PARALLEL_SYNC", "A_G1", "CS401P", "T001", "LAB1",
                               grp="G1", act=ActivityType.PRACTICAL, day=Day.MON, periods=[1, 2], block_size=2,
                               is_linked_parallel=True, linked_placement_id="PL_G2"),
                make_placement("PL_G2", "TT_PARALLEL_SYNC", "A_G2", "CS402P", "T002", "LAB2",
                               grp="G2", act=ActivityType.PRACTICAL, day=Day.MON, periods=[1, 2], block_size=2,
                               is_linked_parallel=True, linked_placement_id="PL_G1"),
            ]
        )
        manager.save_timetable(tt)

        # Move PL_G1 to THU Period 6 with move_partner=True
        updated_tt, conflicts = manager.apply_placement_edit(
            timetable_id="TT_PARALLEL_SYNC",
            placement_id="PL_G1",
            new_data={
                "subject_id": "CS401P",
                "teacher_id": "T001",
                "room_id": "LAB1",
                "activity_type": "PRACTICAL",
                "group": "G1",
                "day": "THU",
                "period": 6,
                "block_size": 2,
            },
            move_partner=True
        )

        p_g1 = updated_tt.find_placement("PL_G1")
        p_g2 = updated_tt.find_placement("PL_G2")

        # Both G1 and G2 must be on THU [6, 7]
        assert p_g1.slots[0].day == Day.THU
        assert [s.period for s in p_g1.slots] == [6, 7]
        assert p_g2.slots[0].day == Day.THU
        assert [s.period for s in p_g2.slots] == [6, 7]

    def test_cell_deletion_leaves_period_free(self, manager):
        """Deleting a placement removes it, leaving the period free without fake SCA."""
        tt = Timetable(
            timetable_id="TT_DEL_TEST",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("PL_TO_DEL", "TT_DEL_TEST", "A1", "CS401", "T001", "R101", day=Day.MON, periods=[1])
            ]
        )
        manager.save_timetable(tt)

        updated_tt = manager.remove_placement("TT_DEL_TEST", "PL_TO_DEL")
        assert len(updated_tt.placements) == 0
        assert updated_tt.find_placement("PL_TO_DEL") is None
        assert updated_tt.status == "INCOMPLETE"

    def test_undo_last_edit(self, manager):
        """Undo reverts the timetable to the version prior to the edit."""
        tt = Timetable(
            timetable_id="TT_UNDO_TEST",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("PL_U", "TT_UNDO_TEST", "A1", "CS401", "T001", "R101", day=Day.MON, periods=[1])
            ]
        )
        manager.save_timetable(tt)

        # Edit to TUE P2
        manager.apply_placement_edit(
            timetable_id="TT_UNDO_TEST",
            placement_id="PL_U",
            new_data={
                "subject_id": "CS401",
                "teacher_id": "T001",
                "room_id": "R101",
                "activity_type": "LECTURE",
                "group": "ALL",
                "day": "TUE",
                "period": 2,
            }
        )

        assert manager.get_timetable("TT_UNDO_TEST").placements[0].slots[0].day == Day.TUE

        # Undo
        reverted = manager.undo_last_edit("TT_UNDO_TEST")
        assert reverted.placements[0].slots[0].day == Day.MON
        assert reverted.placements[0].slots[0].period == 1
