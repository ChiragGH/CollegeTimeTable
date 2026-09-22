# -*- mode: python ; coding: utf-8 -*-
# ====================================================================
# Project: College Timetable Generation & Scheduling System
# Author / Trademark: CRG
# Copyright (c) 2026 CRG. All rights reserved.
# ====================================================================

from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None
project_root = Path.cwd()

# Core static, template, and seed data assets
datas = [
    (str(project_root / "app" / "web" / "templates"), "app/web/templates"),
    (str(project_root / "app" / "web" / "static"), "app/web/static"),
    (str(project_root / "Data"), "Data"),
]

binaries = []

hidden_imports = [
    "waitress",
    "waitress.adjustments",
    "waitress.channel",
    "waitress.receiver",
    "waitress.server",
    "waitress.task",
    "waitress.utilities",
    "flask",
    "jinja2",
    "markupsafe",
    "werkzeug",
    "openpyxl",
    "openpyxl.styles",
    "reportlab",
    "reportlab.lib",
    "reportlab.lib.colors",
    "reportlab.lib.pagesizes",
    "reportlab.lib.styles",
    "reportlab.lib.units",
    "reportlab.platypus",
    "reportlab.pdfgen",
    "reportlab.pdfgen.canvas",
    "pymupdf",
    "fitz",
    "app",
    "app.data",
    "app.data.loader",
    "app.data.validators",
    "app.models",
    "app.models.branch",
    "app.models.enums",
    "app.models.assignment",
    "app.models.section",
    "app.models.session",
    "app.models.slot",
    "app.models.teacher",
    "app.models.room",
    "app.models.subject",
    "app.models.timetable",
    "app.setup",
    "app.setup.assignment_manager",
    "app.setup.filters",
    "app.setup.session_manager",
    "app.engine",
    "app.engine.scheduler",
    "app.engine.slot_allocator",
    "app.engine.scoring",
    "app.engine.validation",
    "app.engine.timetable_manager",
    "app.engine.global_validation",
    "app.export",
    "app.export.service",
    "app.export.excel_export",
    "app.export.pdf_export",
    "app.export.summary_export",
    "app.export.batch_export",
    "app.web",
    "app.web.server",
]

# Ensure complete collection of critical dependencies
for package in ["waitress", "openpyxl", "reportlab", "pymupdf"]:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hidden_imports += pkg_hidden
    except Exception as e:
        print(f"Warning: collect_all({package}) failed: {e}")

a = Analysis(
    ["run_desktop.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tests", "_pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CollegeTimetable",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CollegeTimetable",
)
