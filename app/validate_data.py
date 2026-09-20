"""
Command-line data validation tool.

Run with::

    python -m app.validate_data

Loads all master data from ``Data/master/``, runs the full validation suite,
prints a human-readable report, and exits with a non-zero status when
errors are found.
"""

import io
import sys
from pathlib import Path

# Ensure the project root is on sys.path when executed directly as a script
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.data.loader import DataLoader, DataLoadError
from app.data.validators import DataValidator, Severity


def _setup_utf8_stdout():
    """Force UTF-8 output on Windows consoles that default to cp1252."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )


def main() -> int:
    """
    Entry point for ``python -m app.validate_data``.

    Returns:
        0 if all data is valid, 1 if validation errors exist.
    """
    _setup_utf8_stdout()

    # Resolve the project root Data/master directory
    project_root = Path(__file__).resolve().parent.parent
    data_dir = project_root / "Data" / "master"

    print("=" * 70)
    print("  College Timetable -- Master Data Validation Report")
    print("=" * 70)
    print(f"\n  Data directory: {data_dir}\n")

    # ---- Load data ----
    loader = DataLoader(data_dir=str(data_dir))

    try:
        print("  Loading Teachers.xlsx ...", end=" ")
        teachers = loader.load_teachers()
        print(f"OK ({len(teachers)} rows)")

        print("  Loading Rooms.xlsx ...", end=" ")
        rooms = loader.load_rooms()
        print(f"OK ({len(rooms)} rows)")

        print("  Loading Subjects.xlsx ...", end=" ")
        subjects = loader.load_subjects()
        print(f"OK ({len(subjects)} rows)")

        print("  Loading Workloads.xlsx ...", end=" ")
        workloads = loader.load_workloads()
        print(f"OK ({len(workloads)} rows)")

    except DataLoadError as exc:
        print(f"\n\n  FATAL: Could not load data -- {exc}")
        return 1

    # ---- Validate ----
    print("\n" + "-" * 70)
    print("  Running validation checks...")
    print("-" * 70 + "\n")

    validator = DataValidator()
    result = validator.validate_all(teachers, rooms, subjects, workloads)

    # ---- Report ----
    if result.errors:
        # Group by severity
        errors = [e for e in result.errors if e.severity == Severity.ERROR]
        warnings = [e for e in result.errors if e.severity == Severity.WARNING]

        if errors:
            print(f"  ERRORS ({len(errors)}):\n")
            for err in errors:
                print(f"    {err}")
            print()

        if warnings:
            print(f"  WARNINGS ({len(warnings)}):\n")
            for warn in warnings:
                print(f"    {warn}")
            print()
    else:
        print("  No issues found.\n")

    # ---- Summary ----
    print("-" * 70)
    print(f"  Summary: {result.error_count} error(s), {result.warning_count} warning(s)")

    if result.is_valid:
        print("  Status:  [VALID] Master data is ready for scheduling.")
    else:
        print("  Status:  [INVALID] Fix errors before proceeding.")

    print("=" * 70)

    return 0 if result.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
