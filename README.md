# College Timetable Generation & Scheduling System

[![Author](https://img.shields.io/badge/Author-CRG-blue.svg)](https://github.com/ChiragGH)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Web-orange.svg)]()
[![Trademark](https://img.shields.io/badge/Trademark-CRG-red.svg)]()

An intelligent, full-featured College Timetable Generation and Management System built with Python and modern web technologies. Designed and developed by **CRG**.

It handles complex academic scheduling constraints, multi-branch section allocations, teacher workloads, room capacities, and provides automated clash detection with one-click exports to formatted PDF and Excel.

---

## Key Features

- **Automated Scheduling Engine**: High-performance constraint-satisfaction slot allocator with customizable scoring weights and conflict detection.
- **Modern Desktop UI**: Runs in a dedicated, sleek desktop application window (no terminal, no address bar, no browser tabs).
- **Flexible Master Data**: Excel-based master data inputs (`rooms.xlsx`, `teachers.xlsx`, `subjects.xlsx`, `workloads.xlsx`).
- **Comprehensive Export Options**: Export complete section, faculty, and master timetables to formatted Excel (`.xlsx`) and presentation-ready PDF (`.pdf`).
- **Cross-Timetable Clash Detection**: Detect room, teacher, or section double-booking across different semesters and branches in real-time.
- **Standalone Windows Desktop App**: Portable `.exe` with zero Python or environment setup needed.

---

## Desktop Application (No Python Required)

You can download and run the standalone Windows version directly:

1. Go to [Releases](https://github.com/ChiragGH/CollegeTimeTable/releases).
2. Download the latest `CollegeTimetable_Portable.zip` (or `CollegeTimetable_CRG_Setup.exe`).
3. Extract and double-click **`CollegeTimetable.exe`** to start using the system immediately.

---

## Developer Quickstart

If you want to develop or run directly from the source code:

### 1. Clone the repository
```bash
git clone https://github.com/ChiragGH/CollegeTimeTable.git
cd CollegeTimeTable
```

### 2. Set up virtual environment & install dependencies
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run the development server
```bash
python -m app.web.server
```
Visit `http://127.0.0.1:5000` in your web browser.

### 4. Build Standalone Windows Executable (.exe)
```bash
python build_executable.py
```
The compiled application will be generated in `dist/CollegeTimetable/`.

---

## Project Structure

```
CollegeTimeTable/
├── app/
│   ├── data/             # Excel master data loaders and validators
│   ├── engine/           # Scheduling engine, slot allocator, conflict detector
│   ├── export/           # Excel & PDF export services
│   ├── models/           # Core domain models (Teacher, Room, Subject, Slot)
│   ├── setup/            # Workload filters and assignment managers
│   └── web/              # Flask web server, REST API, SPA static assets & templates
├── Data/
│   ├── master/           # Master Excel templates (rooms, teachers, subjects, workloads)
│   └── timetables/       # Saved timetable instances and persistent JSONs
├── docs/                 # Documentation and architecture diagrams
├── tests/                # Comprehensive test suite
├── run_desktop.py        # Desktop launcher (native app window, auto-exit)
├── CollegeTimetable.spec # PyInstaller packaging specification
├── build_executable.py   # 1-click executable builder
├── installer.iss         # Inno Setup Windows installer script
├── requirements.txt      # Python dependencies
└── README.md             # Project documentation
```

---

## Trademark & Copyright

**College Timetable System** is designed, developed, and maintained by **CRG**.

Copyright (c) 2026 **CRG**. All Rights Reserved.
Licensed under the [MIT License](LICENSE).