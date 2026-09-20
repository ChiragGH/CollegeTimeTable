"""
Integration tests for the Flask Web API endpoints supporting:
- Multi-timetable workspace listing, filtering, and stats
- Duplicate context detection and prompt handling
- Manual cell editing, live validation debouncing endpoint
- College-wide global validation
- Export deliverables (official college format, per-timetable isolation)
"""

import pytest
import json
import tempfile
import shutil

from app.web.server import create_app
from app.models.timetable import Timetable, TimetablePlacement
from app.models.enums import ActivityType, Day
from app.models.slot import TimeSlot


@pytest.fixture
def app():
    _app = create_app()
    _app.config["TESTING"] = True
    return _app


@pytest.fixture
def client(app):
    return app.test_client()


def make_placement(pid: str, tid: str, aid: str, sub: str, teacher: str, room: str,
                   day: Day = Day.MON, period: int = 1, block_size: int = 1) -> TimetablePlacement:
    return TimetablePlacement(
        placement_id=pid,
        timetable_id=tid,
        assignment_id=aid,
        subject_id=sub,
        teacher_id=teacher,
        room_id=room,
        section="A",
        group="ALL",
        activity_type=ActivityType.LECTURE,
        slots=[TimeSlot(day=day, period=p) for p in range(period, period + block_size)],
        block_size=block_size,
        subject_short_name=sub,
        subject_name=sub,
        teacher_name=teacher,
        room_name=room,
    )


class TestTimetableWorkspaceAPI:
    def test_list_and_stats(self, client):
        # Stats returns timetables count
        res = client.get("/api/dashboard/stats")
        assert res.status_code == 200
        data = res.get_json()
        assert "timetables" in data

        # List timetables
        res = client.get("/api/timetables?academic_year=2026-27")
        assert res.status_code == 200
        timetables = res.get_json()
        assert isinstance(timetables, list)

    def test_global_validation_report_api(self, client):
        res = client.get("/api/validation/global?academic_year=2026-27")
        assert res.status_code == 200
        data = res.get_json()
        assert "is_clean" in data
        assert "conflicts" in data
        assert "academic_year" in data


class TestTimetableEditingAndLifecycleAPI:
    @pytest.fixture
    def test_timetable(self, app):
        # Create a test timetable directly in the app state
        tt = Timetable(
            timetable_id="TT_API_TEST",
            academic_year="2026-27",
            branch="CSE",
            semester=4,
            section="A",
            placements=[
                make_placement("P_API_1", "TT_API_TEST", "A1", "CS401", "T001", "R101",
                               day=Day.MON, period=1, block_size=1)
            ]
        )
        app.state.timetable_manager.save_timetable(tt)
        yield tt
        app.state.timetable_manager.delete_timetable(tt.timetable_id)

    def test_get_timetable(self, client, test_timetable):
        res = client.get(f"/api/timetable/{test_timetable.timetable_id}")
        assert res.status_code == 200
        data = res.get_json()
        assert data["timetable_id"] == test_timetable.timetable_id
        assert len(data["placements"]) == 1

    def test_check_conflict_candidate_api(self, client, test_timetable):
        # Candidate on MON P1 with same teacher T001 is a self-exclusion if placement_id matches
        res = client.post(f"/api/timetable/{test_timetable.timetable_id}/check-conflict", json={
            "placement_id": "P_API_1",
            "subject_id": "CS401",
            "teacher_id": "T001",
            "room_id": "R102",
            "day": "MON",
            "period": 1,
            "block_size": 1,
            "group": "ALL",
            "activity_type": "LECTURE",
        })
        assert res.status_code == 200
        data = res.get_json()
        assert data["has_conflict"] is False

        # Candidate with recess spanning
        res_rec = client.post(f"/api/timetable/{test_timetable.timetable_id}/check-conflict", json={
            "placement_id": "P_NEW",
            "subject_id": "CS401P",
            "teacher_id": "T001",
            "room_id": "R101",
            "day": "MON",
            "period": 4,
            "block_size": 2,
            "group": "G1",
            "activity_type": "PRACTICAL",
        })
        assert res_rec.status_code == 200
        data_rec = res_rec.get_json()
        assert data_rec["has_conflict"] is True
        assert any(c["type"] == "RECESS" for c in data_rec["conflicts"])

    def test_save_placement_edit_api(self, client, test_timetable):
        # Valid edit to TUE P2
        res = client.post(f"/api/timetable/{test_timetable.timetable_id}/placement/save", json={
            "placement": {
                "placement_id": "P_API_1",
                "subject_id": "CS402",
                "teacher_id": "T002",
                "room_id": "R102",
                "day": "TUE",
                "period": 2,
                "block_size": 1,
                "group": "ALL",
                "activity_type": "LECTURE",
            },
            "force_override": False,
            "move_partner": True,
        })
        assert res.status_code == 200
        data = res.get_json()
        assert data["ok"] is True

        # Verify placement changed in timetable
        res_tt = client.get(f"/api/timetable/{test_timetable.timetable_id}")
        tt_data = res_tt.get_json()
        p = tt_data["placements"][0]
        assert p["subject_id"] == "CS402"
        assert p["slots"][0]["day"] == "TUE"
        assert p["slots"][0]["period"] == 2

    def test_undo_and_delete_placement_api(self, client, test_timetable):
        # 1. Edit placement
        client.post(f"/api/timetable/{test_timetable.timetable_id}/placement/save", json={
            "placement": {
                "placement_id": "P_API_1",
                "subject_id": "CS401",
                "teacher_id": "T001",
                "room_id": "R101",
                "day": "WED",
                "period": 3,
                "block_size": 1,
                "group": "ALL",
                "activity_type": "LECTURE",
            },
            "force_override": False,
        })

        # 2. Undo edit
        res_undo = client.post(f"/api/timetable/{test_timetable.timetable_id}/undo", json={})
        assert res_undo.status_code == 200

        res_check = client.get(f"/api/timetable/{test_timetable.timetable_id}")
        assert res_check.get_json()["placements"][0]["slots"][0]["day"] == "MON"

        # 3. Delete placement
        res_del = client.delete(f"/api/timetable/{test_timetable.timetable_id}/placement/P_API_1")
        assert res_del.status_code == 200
        assert len(res_del.get_json()["timetable"]["placements"]) == 0

    def test_duplicate_and_delete_timetable_api(self, client, test_timetable):
        # Clone timetable
        res_dup = client.post(f"/api/timetable/{test_timetable.timetable_id}/duplicate", json={})
        assert res_dup.status_code == 200
        cloned_data = res_dup.get_json()
        cloned_id = cloned_data["timetable"]["timetable_id"]
        assert cloned_id != test_timetable.timetable_id

        # Delete cloned timetable
        res_del = client.delete(f"/api/timetable/{cloned_id}")
        assert res_del.status_code == 200
        assert res_del.get_json()["deleted"] == cloned_id

    def test_export_deliverables_api(self, client, test_timetable):
        # Export info
        res_info = client.get(f"/api/timetable/{test_timetable.timetable_id}/export/info")
        assert res_info.status_code == 200
        info = res_info.get_json()
        assert "views" in info
        assert "is_clean" in info

        # College official format download (PDF/XLSX/CSV)
        res_csv = client.get(f"/api/timetable/{test_timetable.timetable_id}/export/college/csv")
        assert res_csv.status_code == 200
        assert len(res_csv.data) > 0

        res_xlsx = client.get(f"/api/timetable/{test_timetable.timetable_id}/export/college/xlsx")
        assert res_xlsx.status_code == 200
        assert len(res_xlsx.data) > 0
