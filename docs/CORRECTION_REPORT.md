# College Timetable System — Correction Report

**Date:** 2026-09-05
**Scope:** Major correction (not a rebuild) of the existing scheduling engine, validation, exports, and viewer.
**Result:** Full suite green — **479 tests passing**. Central mandate implemented and empirically verified.

---

## 1. Executive Summary

The default scheduler was converted from a deterministic *best-first greedy with
soft-constraint scoring* engine into a **seeded random valid-placement** engine whose
only two jobs are:

1. **Schedule the full required academic workload**, and
2. **Guarantee zero hard-constraint clashes**.

All placement preference (morning/afternoon bias, lecture-vs-practical priority,
spacing, load balancing, gap minimisation, room preference) was removed from the
placement path. Scoring survives **only** as a post-hoc report and is never consulted
for any placement decision. A new **validation engine** now reports
`VALID` / `INVALID` / `NO_VALID_TIMETABLE` with structured reasons, and free periods
are rendered genuinely blank — the fabricated "SCA (Free)" filler is gone end-to-end.

---

## 2. The Central Mandate

> **RANDOM VALID PLACEMENT + ZERO CLASHES + COMPLETE WORKLOAD.**

Philosophy implemented literally: for each required session, enumerate **all** valid
candidates (slots + room that violate no hard constraint), shuffle with a configurable
seed (`DEFAULT_SEED = 12345`), pick one at **random**, assign, and continue. Reproducible
per seed; different seeds yield different valid timetables.

---

## 3. Scheduler: From Greedy-Scored to Seeded Random-Valid

`app/engine/scheduler.py`:

- `TimetableScheduler.schedule(assignments, seed=None)` — seed falls back to `DEFAULT_SEED`.
- Seeded **randomized restart**: up to `max_attempts` (default 40) attempts with
  `random.Random(effective_seed + attempt)`; the first complete zero-clash attempt wins,
  otherwise the most-complete attempt is kept with structured unscheduled reasons.
- Selection is `rng.choice(valid)` for both single sessions (`_schedule_single`) and
  G1/G2 pairs (`_schedule_pair`). **No scored "best" is ever chosen.**
- `stats["seed"]` and `stats["attempts_used"]` are emitted for reproducibility/telemetry.

---

## 4. Removal of Priority/Scoring from the Placement Path

- `TimetableScorer.score_timetable(...)` is invoked **once**, after placement, purely to
  populate a `ScoreReport` for the report page. It touches no placement decision.
- Ordering uses `sort_by_difficulty` (most-constrained-first) **only for solver
  correctness**, and within equal-difficulty buckets items are **shuffled by the seed**
  (`_shuffle_equal_blocks`) — carrying no preference.

---

## 5. Hard Constraints Enforced

Placement admits a candidate only if it violates **none** of:

- **Teacher clash** — a teacher is never in two places in the same slot.
- **Room clash** — a room holds at most one activity per slot.
- **Section/group clash** — a section (or a specific group within it) is never
  double-booked; `ALL` blocks the whole section, `G1`/`G2` block only their group.
- **Recess free** — no class spans the P4→P5 lunch break (`LUNCH_AFTER_PERIOD = 4`).
- **Activity/room compatibility** — lectures need lecture rooms, practicals need labs.
- **Branch-specific lab & shared-workshop rules** — enforced in room-type validity.
- **Practical block continuity** — multi-period practicals occupy consecutive periods
  on one day and never straddle lunch.
- **G1/G2 synchronisation** — parallel practicals share the same slots.
- **Teacher eligibility** and **valid slot boundaries** (MON–FRI, P1–P7).

---

## 6. Seeded Reproducibility & Randomized Restart

- Same seed → **identical** timetable (verified at scheduler and API level).
- Different seeds → **different valid** timetables (cross-seed divergence test).
- Restart loop re-seeds per attempt (`effective_seed + attempt`) so a stuck attempt
  explores a genuinely different candidate order rather than repeating itself.

---

## 7. G1/G2 Parallel Practicals & No-Double-Count

A practical with weekly workload *N* means **G1 gets N periods and G2 gets the same
N academic periods** — one block of wall-clock time, two rooms/teachers. It is **not**
counted as 2N. Protected by `test_g1_g2_no_double_count_at_scheduler_level` (weekly=4,
block=2, sessions=2 → G1 sum = 4, G2 sum = 4, equal block count, mirrored rooms differ,
4 distinct academic slots) and mirrored at the validation layer.

---

## 8. Slot-Order Randomization

Candidate enumeration produces the full valid set; order is then shuffled by the
seeded RNG before `rng.choice`. Equal-difficulty ordering buckets are shuffled via
`_shuffle_equal_blocks`, so difficulty ordering never leaks a placement preference.

---

## 9. SCA Filler Removal — Free Periods Are Blank

The old engine fabricated "SCA (Free)" cells to paper over empty slots. This is gone
end-to-end:

- The scheduler places **only** the real academic workload.
- `_make_cell_from_placements` returns a blank cell (`subject=""`, `classroom=""`,
  `teacher=""`, `activity_type="FREE"`) for empty slots.
- CSV / XLSX / PDF human-readable exporters render `FREE` cells as **blank** — the
  literal strings "SCA", "Free", "FREE" never appear.
- The inflated `sca_periods` stat is no longer emitted.
- SCA remains a valid `ActivityType` **only** for real activities carrying workload
  (and is exempt from physical-room checks).

Two source comments still mention "SCA (Free)" — intentionally, documenting the
removed anti-pattern. Guarded by `test_16_free_periods_render_blank_no_sca_filler`
and `test_api_generate_leaves_unfilled_slots_blank`.

---

## 10. Validation Engine (new — `app/engine/validation.py`)

A read-only engine layered over the independent conflict audit. It **never** fabricates
placements. `validate_timetable(assignments, placements, sections, unscheduled)` returns
a `ValidationReport`:

- `status` ∈ {`VALID`, `INVALID`, `NO_VALID_TIMETABLE`}
- `issues: List[ValidationIssue]` with `category` ∈
  {`CLASH`, `WORKLOAD_INCOMPLETE`, `SECTION_EMPTY`, `SECTION_INCOMPLETE`}
- `conflict_report`, plus `.is_valid`, `.headline`, `.issues_by_category()`, `.to_dict()`

Status logic:

- clashes **or** empty configured section → `INVALID`
- else incomplete workload → `NO_VALID_TIMETABLE`
- else → `VALID`

---

## 11. Section-Coverage Completeness

Every configured section must carry its required workload. An **A-full / B-empty**
split is explicitly **INVALID**: a configured section with no assignments (or with
assignments but zero placements) raises a `SECTION_EMPTY` issue on that entity.
Verified by `test_api_generate_flags_empty_section_as_invalid` (sections A+B, workload
on A only → `INVALID` + `SECTION_EMPTY` entity `"B"`).

---

## 12. Workload Completeness & "NO VALID TIMETABLE FOUND"

When the workload cannot be fully placed without a clash, the engine keeps the
most-complete clash-free attempt and reports `NO_VALID_TIMETABLE` with per-assignment
`WORKLOAD_INCOMPLETE` issues and structured `unscheduled` reasons — it never fake-fills
to hide the shortfall. The frontend surfaces this as **"NO VALID TIMETABLE FOUND"**.

---

## 13. Independent Post-Hoc Conflict Audit

`app/export/conflicts.audit_placements` re-derives conflicts from the final placement
list, independently of the scheduler: C1 teacher, C2 room, C3 section/group, C6 G1/G2
parallel alignment. The validation engine consumes this audit, so a VALID verdict is
corroborated by a second, independent pass rather than the scheduler grading its own work.

---

## 14. Auto-Add — Even Distribution

Auto Add inserts a **complete package** (lecture + G1/G2 practicals) and distributes
across sections by round-robin / least-loaded, **workload-remaining aware** — it does
**not** always dump onto Section A. Self-diagnosis on real master data produced a clean
**A = 14 / B = 14** split from 28 auto-added assignments.

---

## 15. Human-Readable vs Raw/Debug Export

- **Human-readable** (`college_timetable.py` → CSV/XLSX/PDF):
  `DAY | TIME | PERIOD | SUBJECT | CLASSROOM/LAB | TEACHER NAME`, free cells blank,
  a RECESS row per day.
- **Raw/debug** (`TimetableExporter.export_aux("flat")`): retains internal IDs, kept
  separate for debugging. Covered by the existing flat-export test.

---

## 16. 12-Hour Time Format Consistency

The grid is the single source of truth: `PERIOD_TIMES` P1 9:00–10:00 … P4 12:00–1:00,
recess 1:00–2:00, P5 2:00–3:00 … P7 4:00–5:00 (no AM/PM). Stale 24-hour strings were
corrected in the `grid.py` module docstring and in `pdf_exporter.py` (now derived
dynamically from grid constants rather than hardcoded). Guarded by `Test12HourTimeFormat`.

---

## 17. Viewer / Frontend (seed + verdict surfacing)

`app/web/static/js/app.js`:

- **Generate page**: a seed `<input>` (default `12345`) plus **Generate** and
  **🎲 New Variation** (randomises the seed) buttons.
- `runGeneration(newVariation)` posts `{ seed }`, then renders a **verdict badge**
  (`VALID` / `NO_VALID_TIMETABLE` / `INVALID`) and *"Seed: X — same seed reproduces
  this exact timetable."*
- **Report page**: a verdict card with the headline, the note *"Empty periods are
  intentionally left blank (no SCA filler)"*, and, when present, an issues table
  (`category | entity | message`).
- All interpolated text is escaped via a new `htmlEsc` helper (XSS-safe). Verified with
  `node --check`.

---

## 18. Dead-Code Cleanup (confirmed-dead only)

- `scheduler.py`: removed unused `Tuple` from the `typing` import.
- `server.py`: removed imports `Day`, `TimeSlot`, `Placement` (grep-confirmed unused
  after SCA removal — `Placement` survived only in a comment) and a redundant
  function-local `Assignment` import (module-level import now used at construction).

No sample data was deleted, and no `subject_id` / `teacher_id` / `room_id` was changed.

---

## 19. Test Suite

**479 passing** (up from 460). Notable additions:

- `tests/test_scheduler.py` → `TestSchedulerSeededRandomValid` (5): reproducibility,
  default-seed == 12345, cross-seed divergence, every sampled seed complete & clash-free,
  G1/G2 no-double-count. Plus `_timetable_signature` order-independent fingerprint.
- `tests/test_validation_engine.py` (11): VALID, NO_VALID_TIMETABLE (no filler invented),
  clash → INVALID (teacher & room), section coverage (empty B, assignments-but-no-
  placements, clash-precedence), and `to_dict` serialization.
- `tests/test_scheduler_hierarchy_and_sca.py`: `TestSectionCoverageAPI` (empty-section
  INVALID, seed reproducibility) + validation assertions on the blank-slots test.
- `tests/test_college_export_and_package.py`: `test_16_free_periods_render_blank_no_sca_filler`.

---

## 20. End-to-End Self-Diagnosis

Ran the real application against the real master data (throwaway harness, since removed):

- Auto-Add produced **28 assignments**, distributed **A = 14 / B = 14**.
- Seeds **{12345, 777, 2026}** each returned `is_complete = True`, `status = VALID`,
  **58/58 placements**, `conflicts.is_clean = True`, **0 conflicts, 0 issues**.
- Same seed reproduced an identical timetable; different seeds diverged — exactly the
  mandated behaviour.

---

## 21. Files Changed

| File | Change |
|------|--------|
| `app/engine/scheduler.py` | Seeded random-valid placement confirmed; removed dead `Tuple` import |
| `app/engine/validation.py` | **New** validation engine (VALID/INVALID/NO_VALID_TIMETABLE) |
| `app/web/server.py` | Wired validation into `/generate`; removed dead imports |
| `app/web/static/js/app.js` | Seed input, New Variation, verdict surfacing, `htmlEsc` |
| `app/export/grid.py` | Docstring → 12-hour format |
| `app/export/pdf_exporter.py` | Time strings derived dynamically from grid constants |
| `tests/test_scheduler.py` | `TestSchedulerSeededRandomValid` + signature helper |
| `tests/test_validation_engine.py` | **New** — 11 validation tests |
| `tests/test_scheduler_hierarchy_and_sca.py` | `TestSectionCoverageAPI` + validation asserts |
| `tests/test_college_export_and_package.py` | Blank-free-period / no-SCA-filler test |

---

## 22. Non-Goals & Notes

- **Scoring was isolated, not deleted.** `TimetableScorer` still exists and runs once
  post-placement for the report only; removing it would lose useful reporting for no gain.
- **Difficulty ordering was kept** strictly for solver efficiency (most-constrained-first);
  it is preference-neutral because equal buckets are seed-shuffled.
- The two residual "SCA (Free)" **comments** are intentional documentation of the removed
  anti-pattern, not live behaviour.
- No sample data, IDs, or schema were altered; all changes are behavioural/display plus
  additive tests and this report.





