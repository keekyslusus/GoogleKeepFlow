import subprocess
import sys
from pathlib import Path

from googlekeepflow.keep_values import parse_bool


SW_SHOWNORMAL = 1


def start_setup_helper(plugin_dir, email="", settings_dir=None, logger=None, debug_webview=False):
    plugin_dir = Path(plugin_dir)
    setup_script = plugin_dir / "googlekeepflow" / "worker_setup_webview.py"
    settings_dir = Path(settings_dir) if settings_dir else plugin_dir
    if not setup_script.exists():
        raise FileNotFoundError(f"Setup helper script not found: {setup_script}")

    if logger:
        logger.info(f"Starting setup helper: {setup_script}")

    startupinfo = None
    creationflags = 0
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = SW_SHOWNORMAL
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    command = [sys.executable, str(setup_script), email or "", str(settings_dir), "1" if parse_bool(debug_webview) else "0"]
    try:
        process = subprocess.Popen(
            command,
            cwd=str(plugin_dir),
            startupinfo=startupinfo,
            creationflags=creationflags,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        if logger:
            logger.exception("Setup helper failed to start: %s", setup_script)
        raise

    if logger:
        logger.info("Setup helper started: pid=%s script=%s", process.pid, setup_script.name)
    return process
