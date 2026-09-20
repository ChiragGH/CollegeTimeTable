"""
Desktop Launcher for College Timetable System.

This script is the main entry point for the standalone Windows executable (.exe).
It:
  1. Finds an available local port (default: 5000).
  2. Spawns a background thread to launch the default web browser once the server is ready.
  3. Serves the Flask application via Waitress (production WSGI server for Windows).
"""

import os
import sys
import time
import socket
import threading
import subprocess
import webbrowser
from pathlib import Path

# Add project root to sys.path if not frozen
if not getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(__file__).resolve().parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

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


def launch_app_window(url: str, delay: float = 1.0):
    """
    Launch the app in dedicated Desktop Window mode (no address bar, no tabs).
    Uses Microsoft Edge or Google Chrome in --app mode, which creates a native-looking
    desktop application window. When the window is closed, the app exits cleanly.
    """
    time.sleep(delay)

    edge_candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    chrome_candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]

    for browser_exe in edge_candidates + chrome_candidates:
        if os.path.exists(browser_exe):
            try:
                # Launch in standalone app window mode
                proc = subprocess.Popen([
                    browser_exe,
                    f"--app={url}",
                    "--window-size=1366,850",
                    "--app-launch-url-for-shortcuts-menu-item=true",
                ])
                # Wait until the user closes the app window, then terminate the server
                proc.wait()
                os._exit(0)
            except Exception:
                pass

    # Fallback to standard browser if neither Edge nor Chrome is found
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Could not open browser automatically: {e}", flush=True)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)

    # Fast self-test flag for CI/verification
    if "--test-only" in sys.argv:
        print("Initializing app for self-test...", flush=True)
        app = create_app()
        print(f"Self-test SUCCESS: app initialized, routes: {len(app.url_map._rules)}", flush=True)
        sys.exit(0)

    port = find_free_port(5000)
    url = f"http://127.0.0.1:{port}"

    print("\n" + "=" * 56, flush=True)
    print("       College Timetable System (Desktop Edition)", flush=True)
    print("=" * 56, flush=True)
    print(f"  * Starting server at: {url}", flush=True)
    print("  * Opening your web browser automatically...", flush=True)
    print("  * Keep this window open while using the application.", flush=True)
    print("  * To exit, close this window or press Ctrl+C.", flush=True)
    print("=" * 56 + "\n", flush=True)

    # Start desktop app window launcher thread
    threading.Thread(target=launch_app_window, args=(url,), daemon=True).start()

    # Create Flask app
    app = create_app()

    # Run using waitress (preferred for Windows .exe)
    try:
        from waitress import serve
        serve(app, host="127.0.0.1", port=port, threads=6, _quiet=True)
    except ImportError:
        # Fallback to werkzeug if waitress not present
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
