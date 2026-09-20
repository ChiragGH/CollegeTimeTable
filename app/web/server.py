"""
Flask web server for the College Timetable system.

Serves the SPA frontend and provides JSON API endpoints that wrap
the existing Python backend modules.  No scheduling logic is
duplicated here -- all intelligence lives in the ``app.engine``
and ``app.setup`` packages.
"""

import sys
import os
import json
import traceback
import shutil
from pathlib import Path
from dataclasses import asdict
from typing import Any, Dict, List, Optional
from flask import Flask, jsonify, request, send_from_directory, render_template, send_file

# Detect frozen (PyInstaller executable) vs normal development mode
IS_FROZEN = getattr(sys, "frozen", False)
if IS_FROZEN:
    APP_ROOT = Path(sys.executable).parent
    BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", str(APP_ROOT)))
    PROJECT_ROOT = BUNDLE_ROOT
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    APP_ROOT = PROJECT_ROOT
    BUNDLE_ROOT = PROJECT_ROOT

DATA_ROOT = APP_ROOT / "Data"

# If running as bundled exe and Data/ does not exist next to .exe, copy seed Data
if IS_FROZEN:
    try:
        seed_data = BUNDLE_ROOT / "Data"
        if seed_data.exists() and not (DATA_ROOT / "master").exists():
            DATA_ROOT.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(seed_data), str(DATA_ROOT), dirs_exist_ok=True)
    except Exception as _e:
        print(f"Warning: Could not seed Data directory: {_e}")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.data.loader import DataLoader
from app.data.validators import DataValidator
from app.models.enums import ActivityType, RoomType
from app.models.branch import normalize_branch
from app.models.assignment import Assignment
from app.models.section import Section
from app.models.session import TimetableSetup
from app.setup.filters import SetupFilters, ACTIVITY_ROOM_MAP
from app.setup.assignment_manager import AssignmentManager
from app.setup.session_manager import SessionManager
from app.engine.scheduler import TimetableScheduler, ScheduleResult
from app.engine.slot_allocator import SchedulerConfig
from app.engine.scoring import ScoringWeights
from app.engine.validation import validate_timetable
from app.models.timetable import Timetable, TimetablePlacement, TimetableHistoryEntry
from app.engine.timetable_manager import TimetableManager
from app.engine.global_validation import GlobalConflictDetector, GlobalConflict
from app.export import (
    ExportContext,
    TimetableExporter,
    VIEW_KINDS,
    VIEW_TITLES,
    placements_from_result_data,
)


# ====================================================================
# Application State (in-memory for development)
# ====================================================================

class AppState:
    """In-memory application state holding loaded master data and sessions."""

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = str(DATA_ROOT / "master")
        self.data_dir = data_dir
        self.loader = DataLoader(data_dir)
        self.teachers = []
        self.rooms = []
        self.subjects = []
        self.workloads = []
        self.filters = None
        self.assignment_manager: Optional[AssignmentManager] = None
        self.sessions: Dict[str, dict] = {}  # session_id → session data
        self.timetables_dir = str(DATA_ROOT / "timetables")
        self.timetable_manager = TimetableManager(self.timetables_dir)
        self._load_master_data()

    def _load_master_data(self):
        try:
            self.teachers = self.loader.load_teachers()
            self.rooms = self.loader.load_rooms()
            self.subjects = self.loader.load_subjects()
            self.workloads = self.loader.load_workloads()
            self.filters = SetupFilters(
                self.teachers, self.rooms, self.subjects, self.workloads
            )
            self.assignment_manager = AssignmentManager(self.filters)
        except Exception as e:
            print(f"Warning: Could not load master data: {e}")

    def get_room_dict(self) -> Dict[str, Any]:
        return {r.room_id: r for r in self.rooms}


# ====================================================================
# Flask App Factory
# ====================================================================

def create_app(data_dir: str = None) -> Flask:
    """Create and configure the Flask application."""
    templates_path = BUNDLE_ROOT / "app" / "web" / "templates" if IS_FROZEN else (Path(__file__).parent / "templates")
    static_path = BUNDLE_ROOT / "app" / "web" / "static" if IS_FROZEN else (Path(__file__).parent / "static")
    app = Flask(
        __name__,
        template_folder=str(templates_path),
        static_folder=str(static_path),
    )
    app.config["SECRET_KEY"] = "college-timetable-dev-key"

    state = AppState(data_dir)
    app.state = state

    # ------------------------------------------------------------------
    # SPA Entry Point
    # ------------------------------------------------------------------

    @app.route("/")
    def index():
        return render_template("index.html")

    # ------------------------------------------------------------------
    # Dashboard API
    # ------------------------------------------------------------------

    @app.route("/api/dashboard/stats")
    def dashboard_stats():
        active_teachers = sum(1 for t in state.teachers if t.active)
        active_rooms = sum(1 for r in state.rooms if r.active)
        branches = list(set(s.branch for s in state.subjects))
        all_timetables = state.timetable_manager.list_timetables()
        return jsonify({
            "teachers": {"total": len(state.teachers), "active": active_teachers},
            "rooms": {"total": len(state.rooms), "active": active_rooms},
            "subjects": {"total": len(state.subjects)},
            "workloads": {"total": len(state.workloads)},
            "branches": sorted(branches),
            "sessions": len(state.sessions),
            "timetables": len(all_timetables),
        })

    # ------------------------------------------------------------------
    # Master Data API
    # ------------------------------------------------------------------

    @app.route("/api/master/teachers")
    def api_teachers():
        return jsonify([
            {"teacher_id": t.teacher_id, "teacher_name": t.teacher_name,
             "department": t.department, "designation": getattr(t, "designation", "") or "",
             "active": t.active}
            for t in state.teachers
        ])

    @app.route("/api/master/rooms")
    def api_rooms():
        return jsonify([
            {"room_id": r.room_id, "room_name": r.room_name,
             "room_type": r.room_type.value if isinstance(r.room_type, RoomType) else str(r.room_type),
             "branch": r.branch, "is_shared": r.is_shared, "active": r.active}
            for r in state.rooms
        ])

    @app.route("/api/master/subjects")
    def api_subjects():
        return jsonify([
            {"subject_id": s.subject_id, "subject_code": s.subject_code,
             "subject_name": s.subject_name,
             "short_name": getattr(s, "short_name", "") or s.subject_code,
             "branch": s.branch, "semester": s.semester,
             "active": getattr(s, "active", True)}
            for s in state.subjects
        ])

    @app.route("/api/master/workloads")
    def api_workloads():
        return jsonify([
            {"workload_id": w.workload_id, "subject_id": w.subject_id,
             "branch": w.branch, "semester": w.semester,
             "lecture_periods_per_week": w.lecture_periods_per_week,
             "practical_periods_per_week": w.practical_periods_per_week,
             "total_periods_per_week": w.total_periods_per_week}
            for w in state.workloads
        ])

    @app.route("/api/master/branches")
    def api_master_branches():
        if state.filters:
            return jsonify([
                {"branch_id": b.branch_id, "branch_name": b.branch_name, "short_name": b.short_name}
                for b in state.filters.get_branch_objects()
            ])
        return jsonify([])

    @app.route("/api/master/validate")
    def api_validate():
        validator = DataValidator()
        result = validator.validate_all(
            state.teachers, state.rooms, state.subjects, state.workloads
        )
        return jsonify({
            "valid": result.is_valid,
            "errors": [{"code": e.code, "message": e.message, "entity": e.entity_id,
                        "field": e.field} for e in result.errors if getattr(e.severity, "value", str(e.severity)) == "ERROR"],
            "warnings": [{"code": w.code, "message": w.message, "entity": w.entity_id,
                          "field": w.field} for w in result.warnings],
        })

    # ------------------------------------------------------------------
    # Cascading Filter API
    # ------------------------------------------------------------------

    @app.route("/api/filters/branches")
    def api_branches():
        if state.filters:
            return jsonify(state.filters.get_branches())
        return jsonify([])

    @app.route("/api/filters/semesters")
    def api_semesters():
        branch = request.args.get("branch", "")
        if state.filters and branch:
            return jsonify(state.filters.get_semesters_for_branch(branch))
        return jsonify([])

    @app.route("/api/filters/subjects")
    def api_filter_subjects():
        branch = request.args.get("branch", "")
        semester = request.args.get("semester", "0")
        if state.filters and branch and semester:
            subjects = state.filters.get_subjects(branch, int(semester))
            return jsonify([
                {"subject_id": s.subject_id, "subject_code": s.subject_code,
                 "subject_name": s.subject_name,
                 "short_name": getattr(s, "short_name", "") or s.subject_code}
                for s in subjects
            ])
        return jsonify([])

    @app.route("/api/filters/rooms")
    def api_filter_rooms():
        activity = request.args.get("activity", "")
        branch = request.args.get("branch", "")
        if state.filters and activity:
            try:
                at = ActivityType(activity)
                rooms = state.filters.get_rooms_for_activity(at, branch=branch or None)
                return jsonify([
                    {"room_id": r.room_id, "room_name": r.room_name,
                     "room_type": r.room_type.value if isinstance(r.room_type, RoomType) else str(r.room_type)}
                    for r in rooms
                ])
            except ValueError:
                pass
        return jsonify([])

    @app.route("/api/filters/teachers")
    def api_filter_teachers():
        """
        Teacher options for the assignment form.

        With ``branch`` (plus optional ``semester`` / ``subject_id`` / ``activity_type``),
        returns only teachers eligible for that timetable context, per
        :meth:`SetupFilters.get_eligible_teachers` -- the filtering rule
        lives in the domain layer, not the frontend.  Without ``branch``
        the legacy behaviour (all active teachers, optional ``department``
        filter) is preserved.
        """
        branch = request.args.get("branch", "")
        if branch and state.filters:
            sem_arg = request.args.get("semester", "")
            semester = int(sem_arg) if sem_arg and sem_arg.isdigit() else None
            subject_id = request.args.get("subject_id", "") or None
            activity = request.args.get("activity_type", "") or None
            activity_type = None
            if activity:
                try:
                    activity_type = ActivityType(activity)
                except ValueError:
                    return jsonify({"error": f"Invalid activity_type: {activity}"}), 400
            teachers = state.filters.get_eligible_teachers(
                branch, semester=semester, subject_id=subject_id, activity_type=activity_type
            )
            return jsonify([
                {"teacher_id": t.teacher_id, "teacher_name": t.teacher_name,
                 "department": t.department}
                for t in teachers
            ])

        dept = request.args.get("department", "")
        teachers = [t for t in state.teachers if t.active]
        if dept:
            teachers = [t for t in teachers if t.department == dept]
        return jsonify([
            {"teacher_id": t.teacher_id, "teacher_name": t.teacher_name,
             "department": t.department}
            for t in teachers
        ])

    # ------------------------------------------------------------------
    # Session Management API
    # ------------------------------------------------------------------

    @app.route("/api/session/create", methods=["POST"])
    def api_create_session():
        data = request.get_json()
        session_id = data.get("session_id", "")
        branch = normalize_branch(data.get("branch", ""))
        semester = data.get("semester", 0)
        academic_year = data.get("academic_year", "2026-27")

        if not session_id or not branch or not semester:
            return jsonify({"error": "Missing required fields"}), 400

        state.sessions[session_id] = {
            "session_id": session_id,
            "branch": branch,
            "semester": int(semester),
            "academic_year": academic_year,
            "sections": [],
            "assignments": [],
            "result": None,
        }
        return jsonify({"ok": True, "session_id": session_id})

    @app.route("/api/session/list")
    def api_list_sessions():
        return jsonify([
            {"session_id": s["session_id"], "branch": s["branch"],
             "semester": s["semester"], "academic_year": s["academic_year"],
             "sections_count": len(s["sections"]),
             "assignments_count": len(s["assignments"]),
             "has_result": s["result"] is not None}
            for s in state.sessions.values()
        ])

    @app.route("/api/session/<session_id>")
    def api_get_session(session_id):
        s = state.sessions.get(session_id)
        if not s:
            return jsonify({"error": "Session not found"}), 404
        # Strip the live ScheduleResult -- only its serialized JSON twin
        # ("result") is safe to send to the client.
        return jsonify({k: v for k, v in s.items() if k != "result_obj"})

    @app.route("/api/session/<session_id>/sections", methods=["POST"])
    def api_update_sections(session_id):
        s = state.sessions.get(session_id)
        if not s:
            return jsonify({"error": "Session not found"}), 404
        data = request.get_json()
        s["sections"] = data.get("sections", [])
        return jsonify({"ok": True, "sections": s["sections"]})

    # ------------------------------------------------------------------
    # Teaching Assignment API
    # ------------------------------------------------------------------

    def _session_to_setup(s: dict) -> TimetableSetup:
        """
        Materialize a stored session dict as a :class:`TimetableSetup`
        so the domain layer (AssignmentManager) can operate on it.
        """
        sections: List[Section] = []
        for raw in s.get("sections", []):
            if isinstance(raw, str):
                sections.append(
                    Section(branch=s["branch"], semester=s["semester"],
                            label=raw)
                )
            elif isinstance(raw, dict):
                sections.append(
                    Section(branch=raw.get("branch", s["branch"]),
                            semester=raw.get("semester", s["semester"]),
                            label=raw.get("label", ""),
                            groups=raw.get("groups", ["G1", "G2"]))
                )
        assignments = []
        for a in s.get("assignments", []):
            payload = {
                "session_id": s["session_id"],
                "branch": s["branch"],
                "semester": s["semester"],
                "group": "ALL",
                "block_size": 1,
                "sessions_per_week": 0,
                "weekly_periods": 0,
            }
            payload.update(a)
            assignments.append(SessionManager.dict_to_assignment(payload))
        return TimetableSetup(
            session_id=s["session_id"],
            academic_year=s.get("academic_year", ""),
            branch=s["branch"],
            semester=s["semester"],
            sections=sections,
            assignments=assignments,
        )

    @app.route("/api/session/<session_id>/assignments", methods=["POST"])
    def api_add_assignment(session_id):
        s = state.sessions.get(session_id)
        if not s:
            return jsonify({"error": "Session not found"}), 404
        if not state.assignment_manager:
            return jsonify({"error": "Master data not loaded"}), 500

        data = request.get_json() or {}
        payload = data.get("assignment", {}) or {}

        try:
            activity_type = ActivityType(payload.get("activity_type", ""))
        except ValueError:
            return jsonify({
                "error": f"Invalid activity_type: "
                         f"{payload.get('activity_type')!r}"
            }), 400

        block_size = payload.get("block_size")
        if block_size is not None:
            try:
                block_size = int(block_size)
            except (TypeError, ValueError):
                return jsonify({"error": f"Invalid block_size: {block_size!r}"}), 400

        # Validate against master data; weekly_periods are derived from the
        # master workload inside prepare_assignment and cannot be overridden.
        setup = _session_to_setup(s)
        assignment, errors = state.assignment_manager.prepare_assignment(
            setup=setup,
            teacher_id=str(payload.get("teacher_id", "") or ""),
            subject_id=str(payload.get("subject_id", "") or ""),
            section=str(payload.get("section", "") or ""),
            group=str(payload.get("group", "") or ""),
            activity_type=activity_type,
            block_size=block_size,
            room_id=payload.get("room_id") or None,
        )
        if errors:
            return jsonify({"error": "; ".join(errors), "errors": errors}), 400

        a_dict = SessionManager.assignment_to_dict(assignment)
        s["assignments"].append(a_dict)
        return jsonify({"ok": True, "assignment": a_dict,
                        "total": len(s["assignments"])})

    @app.route("/api/session/<session_id>/assignments/auto", methods=["POST"])
    def api_auto_add_assignment(session_id):
        """
        Auto Add Test Assignment (development/testing utility).

        Creates ONE valid assignment for the session's branch/semester/
        sections using master data only.  Repeated calls walk through the
        remaining valid subject/activity combinations instead of
        duplicating the same assignment.

        With ``{"dry_run": true}`` nothing is saved; the response carries
        the proposed assignment fields (used by the frontend Auto Fill).
        """
        s = state.sessions.get(session_id)
        if not s:
            return jsonify({"error": "Session not found"}), 404
        if not state.assignment_manager:
            return jsonify({"error": "Master data not loaded"}), 500

        data = request.get_json(silent=True) or {}
        setup = _session_to_setup(s)

        if data.get("dry_run"):
            candidate, message = state.assignment_manager.auto_pick_assignment(setup)
            if candidate is None:
                return jsonify({"ok": True, "proposed": None, "message": message})
            candidate = dict(candidate)
            candidate["activity_type"] = candidate["activity_type"].value
            return jsonify({"ok": True, "proposed": candidate, "message": message})

        mode = data.get("mode", "package")
        if mode == "single":
            assignment, message = state.assignment_manager.auto_create_assignment(setup)
            if assignment is None:
                return jsonify({"ok": True, "created": False, "message": message})
            a_dict = SessionManager.assignment_to_dict(assignment)
            s["assignments"].append(a_dict)
            return jsonify({
                "ok": True, "created": True, "message": message,
                "assignment": a_dict, "assignments": [a_dict], "total": len(s["assignments"])
            })

        created_assignments, message = state.assignment_manager.auto_create_package(
            setup,
            subject_id=data.get("subject_id"),
            section=data.get("section"),
        )
        if not created_assignments:
            return jsonify({"ok": True, "created": False, "message": message})

        created_dicts = [SessionManager.assignment_to_dict(a) for a in created_assignments]
        s["assignments"].extend(created_dicts)
        return jsonify({
            "ok": True,
            "created": True,
            "message": message,
            "assignment": created_dicts[0] if created_dicts else None,
            "assignments": created_dicts,
            "total": len(s["assignments"]),
        })

    @app.route("/api/session/<session_id>/assignments/<assignment_id>", methods=["DELETE"])
    def api_delete_assignment(session_id, assignment_id):
        s = state.sessions.get(session_id)
        if not s:
            return jsonify({"error": "Session not found"}), 404
        s["assignments"] = [a for a in s["assignments"] if a.get("assignment_id") != assignment_id]
        return jsonify({"ok": True})

    @app.route("/api/session/<session_id>/workload-summary")
    def api_workload_summary(session_id):
        """
        Per-subject workload status (required / assigned / remaining) for
        one section and group of the session, straight from master data.
        """
        s = state.sessions.get(session_id)
        if not s:
            return jsonify({"error": "Session not found"}), 404
        if not state.assignment_manager:
            return jsonify({"error": "Master data not loaded"}), 500

        sections = s.get("sections", [])
        section = request.args.get("section", "")
        if not section and sections:
            first = sections[0]
            section = first if isinstance(first, str) else first.get("label", "")
        section = section or "A"
        group = request.args.get("group", "ALL")
        setup = _session_to_setup(s)
        return jsonify(
            state.assignment_manager.get_workload_status(setup, section, group)
        )

    # ------------------------------------------------------------------
    # Generation API
    # ------------------------------------------------------------------

    @app.route("/api/session/<session_id>/generate", methods=["POST"])
    def api_generate(session_id):
        s = state.sessions.get(session_id)
        if not s:
            return jsonify({"error": "Session not found"}), 404

        try:
            req_data = request.get_json(silent=True) or {}
            mode = req_data.get("mode", "auto")  # "check", "new_version", "replace_existing", "auto"
            seed = req_data.get("seed")
            target_id = req_data.get("target_timetable_id")

            # Check if timetables exist for this context when mode is "check"
            sections_list = s.get("sections", [])
            existing_for_context = []
            for raw_sec in sections_list:
                sec_lbl = raw_sec if isinstance(raw_sec, str) else raw_sec.get("label", "A")
                existing = state.timetable_manager.find_existing(
                    academic_year=s.get("academic_year", "2026-27"),
                    branch=s["branch"],
                    semester=s["semester"],
                    section=sec_lbl,
                )
                existing_for_context.extend(existing)

            if mode == "check":
                return jsonify({
                    "has_existing": len(existing_for_context) > 0,
                    "existing": [
                        {
                            "timetable_id": e.timetable_id,
                            "display_name": e.display_name,
                            "version": e.version,
                            "status": e.status,
                            "updated_at": e.updated_at,
                        }
                        for e in existing_for_context
                    ],
                })

            # Convert JSON assignments to Assignment objects
            assignments = []
            for a_data in s["assignments"]:
                assignments.append(Assignment(
                    assignment_id=a_data["assignment_id"],
                    session_id=session_id,
                    teacher_id=a_data["teacher_id"],
                    subject_id=a_data["subject_id"],
                    branch=s["branch"],
                    semester=s["semester"],
                    section=a_data["section"],
                    group=a_data.get("group", "ALL"),
                    activity_type=ActivityType(a_data["activity_type"]),
                    weekly_periods=int(a_data["weekly_periods"]),
                    room_id=a_data.get("room_id"),
                    room_type=RoomType(a_data["room_type"]) if a_data.get("room_type") else None,
                    block_size=int(a_data.get("block_size", 1)),
                    sessions_per_week=int(a_data.get("sessions_per_week", 0)),
                ))

            # Run the scheduler
            room_dict = state.get_room_dict()
            scheduler = TimetableScheduler(rooms=room_dict, seed=seed)
            result = scheduler.schedule(assignments, seed=seed)

            # Build rich placements with human-readable subject display information
            placements_json = []
            for p in result.placements:
                subj = state.filters.get_subject(p.assignment.subject_id) if state.filters else None
                short_name = (
                    getattr(subj, "short_name", "")
                    or (subj.subject_code if subj else "")
                    or p.assignment.subject_id
                )
                code = subj.subject_code if subj else ""
                name = subj.subject_name if subj else p.assignment.subject_id
                teacher = state.filters.get_teacher(p.assignment.teacher_id) if state.filters else None
                teacher_name = getattr(teacher, "teacher_name", "") or p.assignment.teacher_id
                placements_json.append({
                    "placement_id": p.placement_id,
                    "assignment_id": p.assignment.assignment_id,
                    "teacher_id": p.assignment.teacher_id,
                    "teacher_name": teacher_name,
                    "subject_id": p.assignment.subject_id,
                    "short_name": short_name,
                    "subject_short_name": short_name,
                    "subject_code": code,
                    "subject_name": name,
                    "section": p.assignment.section,
                    "group": p.assignment.group,
                    "activity_type": p.assignment.activity_type.value,
                    "room_id": p.room_id,
                    "room_name": room_dict[p.room_id].room_name if p.room_id in room_dict else p.room_id,
                    "slots": [{"day": sl.day.name, "period": sl.period} for sl in p.slots],
                })

            # Independent validation
            setup = _session_to_setup(s)
            validation = validate_timetable(
                assignments=assignments,
                placements=result.placements,
                sections=setup.sections,
                unscheduled=[u.to_dict() for u in result.unscheduled],
            )

            # Create / update persistent Timetable entities
            created_tts = state.timetable_manager.create_from_schedule_result(
                session_id=session_id,
                academic_year=s.get("academic_year", "2026-27"),
                branch=s["branch"],
                semester=s["semester"],
                schedule_result=result,
                filters=state.filters,
                room_dict=room_dict,
                mode="replace_existing" if mode == "replace_existing" else "new_version",
                target_timetable_id=target_id,
                seed=seed,
            )

            result_data = {
                "is_complete": result.is_complete,
                "valid": validation.is_valid,
                "validation": validation.to_dict(),
                "score": round(result.score, 1),
                "score_report": result.score_report.to_dict() if result.score_report else None,
                "placements": placements_json,
                "unscheduled": [u.to_dict() for u in result.unscheduled],
                "stats": result.stats,
                "timetables": [tt.to_dict() for tt in created_tts],
                "timetable_id": created_tts[0].timetable_id if created_tts else None,
            }

            s["result"] = result_data
            s["result_obj"] = result
            return jsonify(result_data)

        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route("/api/session/<session_id>/timetable")
    def api_timetable(session_id):
        s = state.sessions.get(session_id)
        if not s:
            return jsonify({"error": "Session not found"}), 404
        if not s["result"]:
            return jsonify({"error": "No timetable generated yet"}), 404
        return jsonify(s["result"])

    # ------------------------------------------------------------------
    # Persistent Timetable Management API
    # ------------------------------------------------------------------

    @app.route("/api/timetables")
    def api_list_timetables():
        """List all saved persistent timetables with optional filters."""
        sem_str = request.args.get("semester", "")
        semester = int(sem_str) if sem_str.isdigit() else None
        timetables = state.timetable_manager.list_timetables(
            academic_year=request.args.get("academic_year") or None,
            branch=request.args.get("branch") or None,
            semester=semester,
            section=request.args.get("section") or None,
            status=request.args.get("status") or None,
        )
        return jsonify([tt.to_dict() for tt in timetables])

    @app.route("/api/timetable/<timetable_id>")
    def api_get_timetable(timetable_id):
        """Retrieve a specific persistent timetable with all its placements."""
        tt = state.timetable_manager.get_timetable(timetable_id)
        if not tt:
            return jsonify({"error": "Timetable not found"}), 404
        return jsonify(tt.to_dict())

    @app.route("/api/timetable/<timetable_id>", methods=["DELETE"])
    def api_delete_timetable(timetable_id):
        """Delete a timetable independently without affecting other timetables."""
        success = state.timetable_manager.delete_timetable(timetable_id)
        if not success:
            return jsonify({"error": "Timetable not found"}), 404
        return jsonify({"ok": True, "deleted": timetable_id})

    @app.route("/api/timetable/<timetable_id>/duplicate", methods=["POST"])
    def api_duplicate_timetable(timetable_id):
        """Duplicate / clone an existing timetable."""
        clone = state.timetable_manager.duplicate_timetable(timetable_id)
        if not clone:
            return jsonify({"error": "Could not duplicate timetable"}), 404
        return jsonify({"ok": True, "timetable": clone.to_dict()})

    @app.route("/api/timetable/<timetable_id>/undo", methods=["POST"])
    def api_undo_timetable(timetable_id):
        """Undo the most recent manual edit on a timetable."""
        tt = state.timetable_manager.undo_last_edit(timetable_id)
        if not tt:
            return jsonify({"error": "Timetable not found"}), 404
        return jsonify({"ok": True, "timetable": tt.to_dict()})

    @app.route("/api/timetable/<timetable_id>/regenerate", methods=["POST"])
    def api_regenerate_timetable(timetable_id):
        """Regenerate a specific timetable with confirmation."""
        tt = state.timetable_manager.get_timetable(timetable_id)
        if not tt:
            return jsonify({"error": "Timetable not found"}), 404

        req_data = request.get_json(silent=True) or {}
        seed = req_data.get("seed")

        assignments = []
        if tt.session_id and tt.session_id in state.sessions:
            s = state.sessions[tt.session_id]
            for a_data in s.get("assignments", []):
                if a_data.get("section") == tt.section:
                    assignments.append(Assignment(
                        assignment_id=a_data["assignment_id"],
                        session_id=tt.session_id,
                        teacher_id=a_data["teacher_id"],
                        subject_id=a_data["subject_id"],
                        branch=tt.branch,
                        semester=tt.semester,
                        section=tt.section,
                        group=a_data.get("group", "ALL"),
                        activity_type=ActivityType(a_data["activity_type"]),
                        weekly_periods=int(a_data["weekly_periods"]),
                        room_id=a_data.get("room_id"),
                        room_type=RoomType(a_data["room_type"]) if a_data.get("room_type") else None,
                        block_size=int(a_data.get("block_size", 1)),
                        sessions_per_week=int(a_data.get("sessions_per_week", 0)),
                    ))
        else:
            for p in tt.placements:
                assignments.append(Assignment(
                    assignment_id=p.assignment_id or p.placement_id,
                    session_id=tt.timetable_id,
                    teacher_id=p.teacher_id,
                    subject_id=p.subject_id,
                    branch=tt.branch,
                    semester=tt.semester,
                    section=tt.section,
                    group=p.group,
                    activity_type=p.activity_type,
                    weekly_periods=len(p.slots),
                    room_id=p.room_id,
                    block_size=p.block_size,
                    sessions_per_week=1,
                ))

        if not assignments:
            return jsonify({"error": "No assignments available to regenerate this timetable."}), 400

        room_dict = state.get_room_dict()
        scheduler = TimetableScheduler(rooms=room_dict, seed=seed)
        result = scheduler.schedule(assignments, seed=seed)

        state.timetable_manager.create_from_schedule_result(
            session_id=tt.session_id or tt.timetable_id,
            academic_year=tt.academic_year,
            branch=tt.branch,
            semester=tt.semester,
            schedule_result=result,
            filters=state.filters,
            room_dict=room_dict,
            mode="replace_existing",
            target_timetable_id=timetable_id,
            seed=seed,
        )
        updated = state.timetable_manager.get_timetable(timetable_id)
        return jsonify({"ok": True, "timetable": updated.to_dict() if updated else None})

    # ------------------------------------------------------------------
    # Timetable Manual Editing API
    # ------------------------------------------------------------------

    @app.route("/api/timetable/<timetable_id>/check-conflict", methods=["POST"])
    def api_timetable_check_conflict(timetable_id):
        """Live pre-validation for the cell editor."""
        tt = state.timetable_manager.get_timetable(timetable_id)
        if not tt:
            return jsonify({"error": "Timetable not found"}), 404

        candidate = request.get_json() or {}
        all_active = list(state.timetable_manager._cache.values())
        conflicts = GlobalConflictDetector.check_candidate_edit(
            target_timetable=tt,
            candidate_data=candidate,
            all_timetables=all_active,
            exclude_placement_id=candidate.get("placement_id"),
        )
        return jsonify({
            "has_conflict": len(conflicts) > 0,
            "conflicts": [c.to_dict() for c in conflicts],
        })

    @app.route("/api/timetable/<timetable_id>/placement/save", methods=["POST"])
    def api_timetable_save_placement(timetable_id):
        """Save a cell placement modification atomically with conflict validation."""
        tt = state.timetable_manager.get_timetable(timetable_id)
        if not tt:
            return jsonify({"error": "Timetable not found"}), 404

        data = request.get_json() or {}
        placement_data = data.get("placement", {})
        force_override = bool(data.get("force_override", False))
        move_partner = bool(data.get("move_partner", True))

        updated_tt, conflicts = state.timetable_manager.apply_placement_edit(
            timetable_id=timetable_id,
            placement_id=placement_data.get("placement_id", ""),
            new_data=placement_data,
            filters=state.filters,
            room_dict=state.get_room_dict(),
            force_override=force_override,
            move_partner=move_partner,
        )

        if conflicts and not force_override:
            return jsonify({
                "ok": False,
                "has_conflict": True,
                "conflicts": [c.to_dict() for c in conflicts],
                "message": f"Conflict detected: {conflicts[0].description}"
            }), 409

        return jsonify({
            "ok": True,
            "timetable": updated_tt.to_dict() if updated_tt else None,
            "has_conflict": len(conflicts) > 0,
            "conflicts": [c.to_dict() for c in conflicts],
        })

    @app.route("/api/timetable/<timetable_id>/placement/<placement_id>", methods=["DELETE"])
    def api_timetable_delete_placement(timetable_id, placement_id):
        """Remove a placement from a timetable, making the cell free."""
        tt = state.timetable_manager.remove_placement(timetable_id, placement_id)
        if not tt:
            return jsonify({"error": "Timetable not found"}), 404
        return jsonify({"ok": True, "timetable": tt.to_dict()})

    # ------------------------------------------------------------------
    # Global Conflict Validation API
    # ------------------------------------------------------------------

    @app.route("/api/validation/global")
    def api_global_validation():
        """College-wide conflict audit across ALL active timetables."""
        academic_year = request.args.get("academic_year", "")
        all_timetables = state.timetable_manager.list_timetables(
            academic_year=academic_year or None
        )
        report = GlobalConflictDetector.audit_timetables(
            all_timetables, academic_year=academic_year or None
        )
        return jsonify(report.to_dict())

    @app.route("/api/timetable/<timetable_id>/validate")
    def api_timetable_validate(timetable_id):
        """Run validation for a specific timetable against all active college timetables."""
        tt = state.timetable_manager.get_timetable(timetable_id)
        if not tt:
            return jsonify({"error": "Timetable not found"}), 404

        all_timetables = state.timetable_manager.list_timetables(
            academic_year=tt.academic_year
        )
        report = GlobalConflictDetector.audit_timetables(
            all_timetables, academic_year=tt.academic_year
        )
        my_conflicts = [
            c for c in report.conflicts
            if (c.timetable_a and c.timetable_a.get("timetable_id") == timetable_id)
            or (c.timetable_b and c.timetable_b.get("timetable_id") == timetable_id)
        ]
        return jsonify({
            "timetable_id": timetable_id,
            "display_name": tt.display_name,
            "academic_year": tt.academic_year,
            "status": "VALID" if not my_conflicts else "CONFLICTING",
            "is_valid": len(my_conflicts) == 0,
            "total_conflicts": len(my_conflicts),
            "conflicts": [c.to_dict() for c in my_conflicts],
        })

    # ------------------------------------------------------------------
    # Timetable-Specific Export API
    # ------------------------------------------------------------------

    def _timetable_export_context(tt: Timetable) -> ExportContext:
        sections = [
            Section(branch=tt.branch, semester=tt.semester, label=tt.section, groups=["G1", "G2"])
        ]
        return ExportContext(
            session_id=tt.session_id or tt.timetable_id,
            academic_year=tt.academic_year,
            branch=tt.branch,
            semester=tt.semester,
            sections=sections,
            teachers={t.teacher_id: t for t in state.teachers},
            rooms={r.room_id: r for r in state.rooms},
            subjects={su.subject_id: su for su in state.subjects},
            college_name="College Timetable System",
        )

    def _get_timetable_exporter(tt: Timetable) -> TimetableExporter:
        ctx = _timetable_export_context(tt)
        placements = tt.to_engine_placements()
        return TimetableExporter(placements, ctx)

    def _timetable_exports_dir(tt: Timetable) -> Path:
        return DATA_ROOT / "timetables" / tt.timetable_id / "exports"

    @app.route("/api/timetable/<timetable_id>/export/info")
    def api_timetable_export_info(timetable_id):
        tt = state.timetable_manager.get_timetable(timetable_id)
        if not tt:
            return jsonify({"error": "Timetable not found"}), 404

        exporter = _get_timetable_exporter(tt)
        report = exporter.conflicts()

        # Also check global cross-timetable conflicts
        all_active = state.timetable_manager.list_timetables(academic_year=tt.academic_year)
        global_report = GlobalConflictDetector.audit_timetables(all_active, academic_year=tt.academic_year)
        global_conflicts = [
            c for c in global_report.conflicts
            if (c.timetable_a and c.timetable_a.get("timetable_id") == timetable_id)
            or (c.timetable_b and c.timetable_b.get("timetable_id") == timetable_id)
        ]

        return jsonify({
            "timetable_id": timetable_id,
            "display_name": tt.display_name,
            "academic_year": tt.academic_year,
            "status": tt.status,
            "is_clean": report.is_clean and len(global_conflicts) == 0,
            "conflict_counts": report.count_by_type(),
            "conflict_total": len(report.conflicts) + len(global_conflicts),
            "global_conflicts": [c.to_dict() for c in global_conflicts],
            "views": [
                {
                    "kind": kind,
                    "title": VIEW_TITLES[kind],
                    "entities": [
                        {"id": v.entity_id, "title": v.title,
                         "weekly_periods": v.weekly_periods,
                         "conflicts": len(report.conflicts_for(kind, v.entity_id))}
                        for v in exporter.views(kind)
                    ],
                }
                for kind in VIEW_KINDS
            ],
        })

    @app.route("/api/timetable/<timetable_id>/export/<view_kind>/<fmt>")
    def api_timetable_export_download(timetable_id, view_kind, fmt):
        fmt = fmt.lower()
        if fmt not in ("csv", "xlsx", "pdf"):
            return jsonify({"error": f"Unsupported format: {fmt}"}), 400

        tt = state.timetable_manager.get_timetable(timetable_id)
        if not tt:
            return jsonify({"error": "Timetable not found"}), 404

        exporter = _get_timetable_exporter(tt)
        entity = request.args.get("entity") or None
        try:
            out_dir = _timetable_exports_dir(tt)
            if view_kind == "college":
                path = exporter.export_college_timetable(fmt, section=entity or tt.section, out_dir=out_dir)
            else:
                path = exporter.export_view(view_kind, fmt, entity=entity, out_dir=out_dir)
            return send_file(path, as_attachment=True, download_name=path.name)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route("/api/timetable/<timetable_id>/export/college/<fmt>")
    def api_timetable_export_college_download(timetable_id, fmt):
        fmt = fmt.lower()
        if fmt not in ("csv", "xlsx", "pdf"):
            return jsonify({"error": f"Unsupported format: {fmt}"}), 400

        tt = state.timetable_manager.get_timetable(timetable_id)
        if not tt:
            return jsonify({"error": "Timetable not found"}), 404

        exporter = _get_timetable_exporter(tt)
        try:
            out_dir = _timetable_exports_dir(tt)
            path = exporter.export_college_timetable(fmt=fmt, section=tt.section, out_dir=out_dir)
            return send_file(path, as_attachment=True, download_name=path.name)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route("/api/timetable/<timetable_id>/export/save", methods=["POST"])
    def api_timetable_export_save(timetable_id):
        tt = state.timetable_manager.get_timetable(timetable_id)
        if not tt:
            return jsonify({"error": "Timetable not found"}), 404

        exporter = _get_timetable_exporter(tt)
        out_dir = _timetable_exports_dir(tt)
        result = exporter.export_all(out_dir=out_dir)
        return jsonify({
            "ok": True,
            "directory": str(out_dir),
            "files": [f.name for f in result.files],
            "is_clean": result.is_clean,
            "conflict_total": len(result.report.conflicts),
        })

    # ------------------------------------------------------------------
    # Export API
    # ------------------------------------------------------------------

    def _export_context(session_id: str) -> ExportContext:
        """Build the export reference context from app master data."""
        s = state.sessions[session_id]
        sections = []
        for raw in s.get("sections", []):
            if isinstance(raw, str):
                sections.append(
                    Section(branch=s["branch"], semester=s["semester"],
                            label=raw)
                )
            elif isinstance(raw, dict):
                sections.append(
                    Section(branch=raw.get("branch", s["branch"]),
                            semester=raw.get("semester", s["semester"]),
                            label=raw.get("label", ""),
                            groups=raw.get("groups", ["G1", "G2"]))
                )
        return ExportContext(
            session_id=session_id,
            academic_year=s.get("academic_year", ""),
            branch=s["branch"],
            semester=s["semester"],
            sections=sections,
            teachers={t.teacher_id: t for t in state.teachers},
            rooms={r.room_id: r for r in state.rooms},
            subjects={su.subject_id: su for su in state.subjects},
            college_name="College Timetable System",
        )

    def _get_exporter(session_id: str) -> Optional[TimetableExporter]:
        """
        Build the exporter for a session, preferring the live
        ScheduleResult and falling back to the serialized JSON (works
        after a server restart).
        """
        s = state.sessions.get(session_id)
        if not s or not s.get("result"):
            return None

        ctx = _export_context(session_id)
        result_obj = s.get("result_obj")
        if result_obj is not None:
            placements = result_obj.placements
            unscheduled = [u.to_dict() for u in result_obj.unscheduled]
        else:
            placements = placements_from_result_data(s["result"], ctx)
            unscheduled = s["result"].get("unscheduled", [])

        return TimetableExporter(placements, ctx, unscheduled)

    def _exports_dir(session_id: str) -> Path:
        return DATA_ROOT / "sessions" / session_id / "exports"

    @app.route("/api/session/<session_id>/export/info")
    def api_export_info(session_id):
        exporter = _get_exporter(session_id)
        if exporter is None:
            return jsonify({"error": "No timetable generated yet"}), 404

        report = exporter.conflicts()
        return jsonify({
            "session_id": session_id,
            "is_clean": report.is_clean,
            "conflict_counts": report.count_by_type(),
            "conflict_total": len(report.conflicts),
            "unscheduled_count": len(report.unscheduled),
            "views": [
                {
                    "kind": kind,
                    "title": VIEW_TITLES[kind],
                    "entities": [
                        {"id": v.entity_id, "title": v.title,
                         "weekly_periods": v.weekly_periods,
                         "conflicts": len(report.conflicts_for(kind, v.entity_id))}
                        for v in exporter.views(kind)
                    ],
                }
                for kind in VIEW_KINDS
            ],
        })

    @app.route("/api/session/<session_id>/export/<view_kind>/<fmt>")
    def api_export_download(session_id, view_kind, fmt):
        fmt = fmt.lower()
        if fmt not in ("csv", "xlsx", "pdf"):
            return jsonify({"error": f"Unsupported format: {fmt}"}), 400

        exporter = _get_exporter(session_id)
        if exporter is None:
            return jsonify({"error": "No timetable generated yet"}), 404

        entity = request.args.get("entity") or None
        try:
            if view_kind == "college":
                path = exporter.export_college_timetable(
                    fmt, section=entity,
                    out_dir=_exports_dir(session_id),
                )
            else:
                path = exporter.export_view(
                    view_kind, fmt, entity=entity,
                    out_dir=_exports_dir(session_id),
                )
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

        return send_file(path, as_attachment=True, download_name=path.name)

    @app.route("/api/session/<session_id>/export/college/<fmt>")
    def api_export_college_download(session_id, fmt):
        fmt = fmt.lower()
        if fmt not in ("csv", "xlsx", "pdf"):
            return jsonify({"error": f"Unsupported format: {fmt}"}), 400

        exporter = _get_exporter(session_id)
        if exporter is None:
            return jsonify({"error": "No timetable generated yet"}), 404

        section = request.args.get("section") or None
        try:
            path = exporter.export_college_timetable(
                fmt=fmt, section=section,
                out_dir=_exports_dir(session_id),
            )
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

        return send_file(path, as_attachment=True, download_name=path.name)

    @app.route("/api/session/<session_id>/export/aux/<kind>")
    def api_export_aux(session_id, kind):
        exporter = _get_exporter(session_id)
        if exporter is None:
            return jsonify({"error": "No timetable generated yet"}), 404
        try:
            path = exporter.export_aux(kind, out_dir=_exports_dir(session_id))
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.route("/api/session/<session_id>/export/save", methods=["POST"])
    def api_export_save(session_id):
        exporter = _get_exporter(session_id)
        if exporter is None:
            return jsonify({"error": "No timetable generated yet"}), 404

        out_dir = _exports_dir(session_id)
        result = exporter.export_all(out_dir=out_dir)
        return jsonify({
            "ok": True,
            "directory": str(out_dir),
            "files": [f.name for f in result.files],
            "is_clean": result.is_clean,
            "conflict_total": len(result.report.conflicts),
        })

    # ------------------------------------------------------------------
    # Workload helper
    # ------------------------------------------------------------------

    @app.route("/api/filters/workload")
    def api_workload():
        """
        Workload for a subject; with ``activity_type``, also returns the
        activity's periods/week (derived from the master workload column)
        and a valid default block configuration.
        """
        subject_id = request.args.get("subject_id", "")
        if state.filters and subject_id:
            wl = state.filters.get_workload_for_subject(subject_id)
            if wl:
                resp = {
                    "workload_id": wl.workload_id,
                    "lecture_periods_per_week": wl.lecture_periods_per_week,
                    "practical_periods_per_week": wl.practical_periods_per_week,
                    "total_periods_per_week": wl.total_periods_per_week,
                }
                activity = request.args.get("activity_type", "")
                if activity and state.assignment_manager:
                    try:
                        at = ActivityType(activity)
                    except ValueError:
                        return jsonify(
                            {"error": f"Invalid activity_type: {activity}"}), 400
                    mgr = state.assignment_manager
                    periods = mgr.get_workload_for_activity(subject_id, at)
                    block_size, sessions = mgr.compute_block_config(at, periods)
                    resp.update({
                        "activity_type": at.value,
                        "activity_periods": periods,
                        "block_size": block_size,
                        "sessions_per_week": sessions,
                    })
                return jsonify(resp)
        return jsonify(None)

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not found"}), 404
        return render_template("index.html")

    return app


# ====================================================================
# Entry point
# ====================================================================

if __name__ == "__main__":
    app = create_app()
    print("\n  College Timetable System")
    print("  http://localhost:5000\n")
    app.run(debug=True, port=5000)
