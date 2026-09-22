"""
====================================================================
Project: College Timetable Generation & Scheduling System
Author / Trademark: CRG
Copyright (c) 2026 CRG. All rights reserved.
====================================================================
Desktop Launcher for College Timetable System.

This script is the main entry point for the standalone Windows executable (.exe).
It:
  1. Sets up safe stdout/stderr file logging for windowed mode (console=False).
  2. Detects if an instance is already running (single-instance protection).
  3. Starts the Flask application via Waitress WSGI server in a background thread.
  4. Waits for the HTTP health check to succeed before launching the UI.
  5. Launches Microsoft Edge / Chrome in dedicated, isolated App Window mode
     with its own user data directory (no browser chrome, no premature delegation).
  6. Keeps the server alive while the app window is open, and cleans up when closed.
"""

import os
import sys
import time
import socket
import tempfile
import threading
import subprocess
import webbrowser
import urllib.request
from pathlib import Path
from typing import Optional, List

# Detect frozen (PyInstaller executable) vs normal development mode
IS_FROZEN = getattr(sys, "frozen", False)
if IS_FROZEN:
    APP_ROOT = Path(sys.executable).parent
    BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", str(APP_ROOT)))
    PROJECT_ROOT = BUNDLE_ROOT
else:
    PROJECT_ROOT = Path(__file__).resolve().parent
    APP_ROOT = PROJECT_ROOT
    BUNDLE_ROOT = PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Safe logging setup for windowed executables
LOG_DIR = APP_ROOT / "Data" / "logs"
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE = LOG_DIR / "desktop.log"
except Exception:
    LOG_FILE = Path(tempfile.gettempdir()) / "CollegeTimetable_desktop.log"


class SafeLogger:
    """Safe logger that writes to a file when running without a console."""

    def __init__(self, filepath: Path):
        self._filepath = filepath
        self._file = None
        try:
            self._file = open(filepath, "a", encoding="utf-8", buffering=1)
        except Exception:
            pass

    def write(self, msg: str):
        if self._file:
            try:
                self._file.write(msg)
                self._file.flush()
            except Exception:
                pass

    def flush(self):
        if self._file:
            try:
                self._file.flush()
            except Exception:
                pass


# Redirect stdout and stderr if running in windowed mode
if sys.stdout is None or not hasattr(sys.stdout, "write"):
    sys.stdout = SafeLogger(LOG_FILE)
elif hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

if sys.stderr is None or not hasattr(sys.stderr, "write"):
    sys.stderr = SafeLogger(LOG_FILE)
elif hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

from app.web.server import create_app


def find_free_port(start_port: int = 5000, max_tries: int = 50) -> int:
    """Find an open TCP port on localhost starting from start_port."""
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port


def is_server_ready(url: str, timeout: float = 0.5) -> bool:
    """Check if the web server is answering HTTP requests."""
    try:
        req = urllib.request.Request(f"{url}/api/dashboard/stats")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def wait_for_server(url: str, max_wait: float = 25.0) -> bool:
    """Poll the server until it responds or timeout expires."""
    start = time.time()
    while time.time() - start < max_wait:
        if is_server_ready(url):
            return True
        time.sleep(0.15)
    return False


def get_browser_command(url: str) -> Optional[List[str]]:
    """
    Find Microsoft Edge, Google Chrome, or Brave to run in standalone desktop app mode.
    Returns command line with an isolated --user-data-dir so it never delegates to
    existing browser processes or prematurely exits.
    """
    found_exe = None

    # 1. Query Windows Registry for official installed path
    try:
        import winreg

        browser_names = ["msedge.exe", "chrome.exe", "brave.exe"]
        for b_name in browser_names:
            for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(
                        root_key,
                        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{b_name}",
                    ) as key:
                        path, _ = winreg.QueryValueEx(key, "")
                        if path and os.path.exists(path):
                            found_exe = path
                            break
                except Exception:
                    pass
            if found_exe:
                break
    except Exception:
        pass

    # 2. Check standard directory locations if registry lookup didn't succeed
    if not found_exe:
        candidates = [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for c in candidates:
            if os.path.exists(c):
                found_exe = c
                break

    if found_exe:
        local_app_data = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or tempfile.gettempdir()
        profile_dir = Path(local_app_data) / "CollegeTimetable" / "browser_profile"
        try:
            profile_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        return [
            found_exe,
            f"--user-data-dir={profile_dir}",
            f"--app={url}",
            "--window-size=1366,850",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
        ]

    return None


def show_error_dialog(title: str, message: str):
    """Show a native Windows error dialog if available."""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10 | 0x0)
    except Exception:
        print(f"[{title}] {message}", file=sys.stderr)


def main():
    # Fast self-test flag for CI/verification
    if "--test-only" in sys.argv:
        print("Initializing app for self-test...", flush=True)
        app = create_app()
        print(f"Self-test SUCCESS: app initialized, routes: {len(app.url_map._rules)}", flush=True)
        sys.exit(0)

    # 1. Single Instance Check: if default port 5000 is already active and serving our app
    default_port = 5000
    default_url = f"http://127.0.0.1:{default_port}"
    if is_server_ready(default_url, timeout=0.8):
        print(f"Existing instance detected on {default_url}, opening window...", flush=True)
        cmd = get_browser_command(default_url)
        if cmd:
            subprocess.Popen(cmd)
        else:
            webbrowser.open(default_url)
        sys.exit(0)

    # 2. Pick a free port
    port = find_free_port(default_port)
    url = f"http://127.0.0.1:{port}"

    print(f"Starting College Timetable System by CRG at {url}...", flush=True)

    # 3. Create Flask app
    try:
        app = create_app()
    except Exception as e:
        err_msg = f"Failed to load application data:\n{e}"
        print(err_msg, file=sys.stderr)
        show_error_dialog("College Timetable System Error", err_msg)
        sys.exit(1)

    # 4. Start WSGI server in a background thread
    server_error = []

    def run_server():
        try:
            from waitress import serve

            serve(app, host="127.0.0.1", port=port, threads=6, _quiet=True)
        except ImportError:
            try:
                app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
            except Exception as e:
                server_error.append(str(e))
        except Exception as e:
            server_error.append(str(e))

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # 5. Wait for the server to become ready and answer HTTP requests
    ready = wait_for_server(url, max_wait=25.0)
    if not ready:
        err_details = server_error[0] if server_error else "Server did not respond within 25 seconds."
        err_msg = f"Could not start the internal web server.\n\nDetails: {err_details}"
        print(err_msg, file=sys.stderr)
        show_error_dialog("College Timetable System Error", err_msg)
        sys.exit(1)

    print(f"Server is ready at {url}. Launching application window...", flush=True)

    # 6. Launch desktop app window
    cmd = get_browser_command(url)
    if cmd:
        try:
            proc = subprocess.Popen(cmd)
            # Give the browser a moment to initialize
            time.sleep(2.0)
            if proc.poll() is None:
                # App window is active! Wait for the user to close it.
                proc.wait()
                print("Application window closed by user. Exiting cleanly.", flush=True)
                sys.exit(0)
            else:
                print(
                    f"Browser exited with code {proc.poll()}, falling back to default browser.",
                    flush=True,
                )
        except Exception as e:
            print(f"Could not launch app mode window: {e}", file=sys.stderr)

    # 7. Fallback to default browser if app window mode didn't stay open
    webbrowser.open(url)
    try:
        while True:
            time.sleep(1.0)
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)


if __name__ == "__main__":
    main()
