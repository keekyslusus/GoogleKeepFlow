import subprocess
import sys
import json
import time
import uuid
from pathlib import Path

from googlekeepflow.keep_auth_store import protect_bytes
from googlekeepflow.keep_labels import parse_note_labels


def parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def start_worker(plugin_dir, script_name, args, logger=None, label="Worker"):
    plugin_dir = Path(plugin_dir)
    worker_script = plugin_dir / "googlekeepflow" / script_name
    if not worker_script.exists():
        raise FileNotFoundError(f"{label} script not found: {worker_script}")

    startupinfo = None
    creationflags = 0
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    command = [sys.executable, str(worker_script), *[str(arg) for arg in args]]
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
            logger.exception("%s failed to start: %s", label, worker_script)
        raise

    if logger:
        logger.info("%s started: pid=%s script=%s", label, process.pid, worker_script.name)
    return process


def split_checklist_items(text):
    items = [item.strip() for item in str(text or "").split(";")]
    return [item for item in items if item]


def start_note_worker(plugin_dir, email, text, pinned=False, archived=False, list_note=False, reminder_at_iso="", show_notifications=True, logger=None, settings_dir=""):
    plugin_dir = Path(plugin_dir)
    settings_dir = Path(settings_dir)
    settings_dir.mkdir(parents=True, exist_ok=True)
    job_file = settings_dir / f"google_keep_note_job_{uuid.uuid4().hex}.bin"
    note_text, labels = parse_note_labels(text)
    if not note_text and str(text or "").strip():
        note_text = str(text or "").strip()
    job_data = {
        "email": str(email or "").strip().lower(),
        "type": "list" if list_note else "note",
        "text": note_text,
        "items": split_checklist_items(note_text) if list_note else [],
        "labels": labels,
        "pinned": parse_bool(pinned),
        "archived": parse_bool(archived),
        "reminder_at": str(reminder_at_iso or "").strip(),
        "timestamp": time.time(),
    }
    job_file.write_bytes(protect_bytes(json.dumps(job_data, ensure_ascii=False).encode("utf-8")))
    start_worker(
        plugin_dir,
        "worker_sync.py",
        [job_file, show_notifications, settings_dir or ""],
        logger,
        "Sync worker",
    )


def start_archive_worker(plugin_dir, email, note_id, archived, show_notifications=True, logger=None, settings_dir=""):
    start_worker(
        plugin_dir,
        "worker_archive.py",
        [email, note_id, "1" if archived else "0", show_notifications, settings_dir or ""],
        logger,
        "Archive worker",
    )


def start_trash_worker(plugin_dir, email, note_id, show_notifications=True, logger=None, settings_dir=""):
    start_worker(
        plugin_dir,
        "worker_trash.py",
        [email, note_id, show_notifications, settings_dir or ""],
        logger,
        "Trash worker",
    )


def start_pin_worker(plugin_dir, email, note_id, pinned, show_notifications=True, logger=None, settings_dir=""):
    start_worker(
        plugin_dir,
        "worker_pin.py",
        [email, note_id, "1" if pinned else "0", show_notifications, settings_dir or ""],
        logger,
        "Pin worker",
    )


def start_external_edit_worker(plugin_dir, email, note_id, show_notifications=True, logger=None, settings_dir=""):
    settings_dir = Path(settings_dir)
    edit_jobs_dir = settings_dir / "editing" / "jobs"
    edit_jobs_dir.mkdir(parents=True, exist_ok=True)
    job_file = edit_jobs_dir / f"external_edit_{uuid.uuid4().hex}.bin"
    job_data = {
        "email": str(email or "").strip().lower(),
        "note_id": str(note_id or ""),
        "show_notifications": parse_bool(show_notifications),
        "timestamp": time.time(),
    }
    job_file.write_bytes(protect_bytes(json.dumps(job_data, ensure_ascii=False).encode("utf-8")))
    start_worker(
        plugin_dir,
        "worker_external_edit.py",
        [settings_dir or ""],
        logger,
        "External edit watcher",
    )


def start_cache_refresh_worker(plugin_dir, email, settings_dir, logger=None):
    start_worker(
        plugin_dir,
        "worker_refresh_cache.py",
        [email, settings_dir],
        logger,
        "Cache refresh worker",
    )

