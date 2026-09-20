# College Timetable Generation System — Project Specification

> **Version:** 1.0-DRAFT  
> **Date:** 2026-08-30  
> **Status:** Architecture & Specification Phase — implementation not yet started.

---

## 1. Purpose

Build a **Python-based timetable scheduling application** that generates conflict-free weekly class timetables for a polytechnic college.  
The system ingests master data from normalised Excel files, applies constraint-based scheduling, validates the result, and exports ready-to-use timetables.

---

## 2. Scope

### 2.1 In Scope (Phase 1)

| Area | Details |
|---|---|
| **Master Data Management** | Import / validate Teachers, Rooms, Subjects, Workloads from `data/master/*.xlsx`. |
| **Timetable Setup** | Select branch + semester → create/select section(s) → optionally define G1/G2 groups → assign teachers to subjects for the current term. |
| **Schedule Generation** | Constraint-satisfaction engine that places lectures, practicals/labs, and workshop sessions into a weekly grid while honouring all hard constraints. |
| **Conflict Detection** | Real-time detection of teacher, room, and section/group clashes. |
| **Validation** | Pre-export validation pass that certifies workload fulfilment and constraint compliance. |
| **Export** | Export finalised timetable to Excel (per-section view, per-teacher view). |

### 2.2 Out of Scope (deferred to roadmap)

- Web/GUI front-end.
- Multi-week or calendar-aware scheduling.
- Automatic teacher-subject assignment optimisation.
- Student-facing portals or mobile apps.
- Attendance / substitution management.

---

## 3. College Profile

### 3.1 Branches

| # | Branch Code | Full Name |
|---|---|---|
| 1 | CSE | Computer Science & Engineering |
| 2 | ECE | Electronics & Communication Engineering |
| 3 | EE | Electrical Engineering |
| 4 | ME | Mechanical Engineering |
| 5 | CE | Civil Engineering |
| 6 | AS | Applied Science (service department) |
| 7 | WS | Workshop (service department) |

### 3.2 Semesters

Each branch offers semesters **1 through 6**.  
Subject offerings and workloads differ per branch-semester combination.

### 3.3 Weekly Grid

| Property | Value |
|---|---|
| Working days | Monday – Friday |
| Periods per day | 7 (excluding lunch) |
| Period duration | 60 minutes |
| Total slots/week | 35 |

**Daily slot structure:**

| Slot # | Time |
|---|---|
| 1 | 09:00 – 10:00 |
| 2 | 10:00 – 11:00 |
| 3 | 11:00 – 12:00 |
| 4 | 12:00 – 13:00 |
| — | 13:00 – 14:00 (Lunch Break) |
| 5 | 14:00 – 15:00 |
| 6 | 15:00 – 16:00 |
| 7 | 16:00 – 17:00 |

---

## 4. Activity Types

| Type Code | Description | Typical Room | Group Split |
|---|---|---|---|
| `LECTURE` | Theory class for entire section | L1–L13 (shared lecture halls) | Full section |
| `PRACTICAL` | Lab/practical for a group | Branch-specific labs | G1 or G2 (configurable) |
| `WORKSHOP` | Workshop practical | Workshop rooms (shared) | G1 or G2 (configurable) |
| `DRAWING` | Drawing/drafting class | DH1–DH2 | Full section or group (configurable) |

---

## 5. Sections and Groups

- A **section** (e.g., CSE-3-A) represents a cohort of students in a branch-semester.
- Sections may be split into **groups** (G1, G2) for practicals.
- When a section is split, G1 and G2 practicals may run **in parallel** in different labs with different teachers — this is a single scheduling unit that occupies one time-slot from the section's perspective but uses two rooms and two teachers.
- Sections and groups are created/selected during timetable setup, **not** stored as permanent master data.

---

## 6. Teacher-Subject Assignment Model

- Teacher ↔ Subject mappings are **transient** — they change every semester.
- They are configured during **timetable setup**, not baked into master data.
- A single teacher may be assigned to multiple subjects (even across branches in the same semester).
- The setup entity is `TeacherSubjectAssignment(teacher_id, subject_id, section_id, group, activity_type)`.

---

## 7. Key Constraints (summary)

Detailed rules are in `SCHEDULING_RULES.md`. High-level constraints:

| # | Constraint | Type |
|---|---|---|
| C1 | No teacher can be in two places at the same time-slot. | Hard |
| C2 | No room can host two activities at the same time-slot. | Hard |
| C3 | No section (or group) can have two activities at the same time-slot. | Hard |
| C4 | Weekly workload (L + P periods) for each subject must be met. | Hard |
| C5 | Practical/workshop sessions must occupy **consecutive** slots (block size configurable). | Hard |
| C6 | Parallel G1/G2 practicals must share the same time-slot range. | Hard |
| C7 | Lab rooms are branch-specific; lectures use shared rooms. | Hard |
| C8 | Drawing halls (DH1/DH2) are shared resources — conflict-checked like any room. | Hard |

---

## 8. Configurable Parameters

Items explicitly **not** hard-coded, because the college has not yet confirmed fixed values or they may change term-to-term:

| Parameter | Default | Notes |
|---|---|---|
| `practical_block_size` | 2 | Number of consecutive periods a practical occupies. **Unresolved** — confirm with college whether some practicals span 3 periods. |
| `workshop_block_size` | 3 | Number of consecutive periods a workshop occupies. **Unresolved** — confirm exact policy. |
| `drawing_block_size` | 3 | Consecutive periods for drawing hall sessions. **Unresolved**. |
| `max_lectures_per_day` | 5 | Soft limit on theory periods per day for a section. |
| `max_periods_per_day_teacher` | 6 | Soft limit on total periods for a teacher per day. |
| `allow_lunch_span` | `false` | Whether a practical block can span the lunch break. |
| `sca_scheduled` | `false` | SCA rows are excluded from normalised data. Remaining free periods (35 minus workload total) are left unscheduled. |
| `moocs_scheduled` | `false` | Whether MOOCs/Open-Elective slots appear on the timetable. **Unresolved**. |

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **Slot** | A (day, period) pair — e.g., (Monday, Slot 3). 35 slots per week. |
| **Activity** | An instance of teaching: one subject, one activity-type, assigned to a teacher + room + section/group. |
| **Placement** | An Activity assigned to a specific Slot (or block of slots). |
| **Hard constraint** | Must never be violated — violation invalidates the timetable. |
| **Soft constraint** | Desirable but can be relaxed if necessary (e.g., teacher daily load limits). |
| **Block** | A set of consecutive slots on the same day (for practicals/workshops). |
| **VF** | "Visiting Faculty" — placeholder IDs (VF1–VF5) present in multiple departments, indicating unfilled positions. |
| **SCA** | Student Centred Activities — self-study or seminar periods. |
| **MOOCs+** | Online elective courses — may not need room scheduling. |

---

## 10. Assumptions

1. All existing Excel source data in `Data/` is authoritative and already normalised. `College_Data.xlsx` has been retired.
2. "VF" (Visiting Faculty) entries are placeholder slots — the system must support them but flag that real teacher names are pending.
3. Subject sharing (which department provides the teacher) is **not** encoded in the data files. It is resolved implicitly when the teacher's department differs from the subject's branch during `TeacherSubjectAssignment` at setup time.
4. **SCA is excluded** from the subject/workload files. Semester totals are less than 35; the gap represents unscheduled free periods.
5. The system is single-user / desktop for Phase 1.
6. Python 3.10+ is the target runtime.

---

## 11. Deliverables by Phase

| Phase | Deliverable |
|---|---|
| **Phase 0 (current)** | Architecture docs, data schemas, scheduling-rule spec. |
| **Phase 1** | Core scheduling engine (CLI-driven), Excel import/export. |
| **Phase 2** | Streamlit or web UI, multi-section batch generation. |
| **Phase 3** | Advanced optimisation (soft constraints, teacher preferences, room utilisation dashboards). |
