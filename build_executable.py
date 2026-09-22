"""
====================================================================
Project: College Timetable Generation & Scheduling System
Author / Trademark: CRG
Copyright (c) 2026 CRG. All rights reserved.
====================================================================
Build Script for College Timetable Standalone Windows Application.

Usage:
    python build_executable.py

This script:
  1. Detects virtual environment Python (.venv) and terminates running instances.
  2. Runs PyInstaller using CollegeTimetable.spec.
  3. Ensures the distribution folder (dist/CollegeTimetable) contains:
     - CollegeTimetable.exe (windowed desktop app)
     - Data/ (master Excel files, timetables, sessions)
     - README_HOW_TO_RUN.txt
  4. Creates a clean portable zip archive: dist/CollegeTimetable_Portable.zip
"""

import sys
import shutil
import zipfile
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist" / "CollegeTimetable"
SPEC_FILE = PROJECT_ROOT / "CollegeTimetable.spec"
DATA_SRC = PROJECT_ROOT / "Data"
ZIP_OUTPUT = PROJECT_ROOT / "dist" / "CollegeTimetable_Portable.zip"

README_TEXT = """========================================================================
       COLLEGE TIMETABLE GENERATION & SCHEDULING SYSTEM
                   Developed by CRG
         Copyright (c) 2026 CRG. All Rights Reserved.
========================================================================

HOW TO RUN:
1. Double-click "CollegeTimetable.exe".
2. The application will start and open its dedicated desktop window
   (no terminal or command prompt will appear).
3. Use the system as usual (generate timetables, edit placements, export PDF/Excel).
4. To exit: Simply close the application window.

DATA & EXCEL FILES:
- The "Data/master" folder contains all master Excel files:
  - rooms.xlsx
  - subjects.xlsx
  - teachers.xlsx
  - workloads.xlsx
- You can update or replace these Excel files anytime. When you start
  the application, the new data is loaded automatically!
- Saved timetables and exports are stored in "Data/timetables/".
- Application logs are recorded in "Data/logs/desktop.log".

REQUIREMENTS:
- Windows 10 or 11 (64-bit).
- No Python or technical dependencies required.
========================================================================
"""


def main():
    print("=" * 65)
    print("  Building College Timetable Standalone Windows Executable")
    print("                 Author / Trademark: CRG")
    print("=" * 65)

    # Detect python executable (prefer .venv if present)
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable
    print(f"  * Using Python: {python_exe}")

    # Terminate any running CollegeTimetable.exe to prevent file locks
    try:
        subprocess.run(["taskkill", "/F", "/IM", "CollegeTimetable.exe"], capture_output=True)
    except Exception:
        pass

    # Delete old ZIP if exists
    if ZIP_OUTPUT.exists():
        try:
            ZIP_OUTPUT.unlink()
            print(f"  * Removed old {ZIP_OUTPUT.name}")
        except Exception:
            pass

    # 1. Run PyInstaller
    print("\n[1/4] Running PyInstaller...")
    cmd = [
        python_exe,
        "-m",
        "PyInstaller",
        "--clean",
        "-y",
        str(SPEC_FILE),
    ]
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if res.returncode != 0:
        print("\n[ERROR] PyInstaller build failed! Please inspect output above.")
        sys.exit(res.returncode)

    print("\n[2/4] Verifying distribution files...")
    if not DIST_DIR.exists():
        print(f"[ERROR] Distribution folder {DIST_DIR} not found!")
        sys.exit(1)

    # 2. Ensure Data folder is present in dist
    dist_data = DIST_DIR / "Data"
    print(f"\n[3/4] Ensuring Data directory exists in {dist_data}...")
    if DATA_SRC.exists():
        shutil.copytree(str(DATA_SRC), str(dist_data), dirs_exist_ok=True)
        print("      -> Data folder copied successfully.")

    # Write README
    readme_path = DIST_DIR / "README_HOW_TO_RUN.txt"
    readme_path.write_text(README_TEXT, encoding="utf-8")
    print("      -> README_HOW_TO_RUN.txt created.")

    # 3. Create ZIP archive
    print("\n[4/4] Creating portable ZIP archive...")
    try:
        with zipfile.ZipFile(ZIP_OUTPUT, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in DIST_DIR.rglob("*"):
                arcname = file_path.relative_to(DIST_DIR.parent)
                zf.write(file_path, arcname)
        print(f"      -> ZIP created: {ZIP_OUTPUT} ({ZIP_OUTPUT.stat().st_size / (1024*1024):.1f} MB)")
    except Exception as e:
        print(f"      -> Warning: Could not create zip: {e}")

    print("\n" + "=" * 65)
    print("  BUILD COMPLETE!")
    print("=" * 65)
    print(f"  Executable Folder : {DIST_DIR}")
    print(f"  Main Executable   : {DIST_DIR / 'CollegeTimetable.exe'}")
    print(f"  Portable ZIP      : {ZIP_OUTPUT}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
