import json
import hashlib
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

package_dir = Path(__file__).parent.resolve()
plugindir = package_dir.parent
if str(plugindir) not in sys.path:
    sys.path.insert(0, str(plugindir))
lib_path = plugindir / "lib"
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

from googlekeepflow.keep_auth_store import unprotect_bytes
from googlekeepflow.keep_cache import load_note_body_cache
from googlekeepflow.worker_common import (
    find_note,
    load_keep,
    save_notes_cache,
    setup_worker_logger,
    short_error,
    show_notification,
)

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    FileSystemEventHandler = object
    Observer = None
    WATCHDOG_AVAILABLE = False


EDIT_DIR_NAME = "editing"
JOB_DIR_NAME = "jobs"
JOB_PATTERN = "external_edit_*.bin"
WATCH_LOCK_NAME = "external_edit_watch.lock"
WATCH_STATE_NAME = "external_edit_watch.state.json"
UPDATE_CHECK_SECONDS = 5
WATCHDOG_FALLBACK_SCAN_SECONDS = 30
LOCK_STALE_SECONDS = 8 * 60 * 60
IDLE_EXIT_SECONDS = 2 * 60 * 60
DEBOUNCE_SECONDS = 1.5
POLL_SECONDS = 0.75
WATCHED_CODE_PATHS = (
    "plugin.json",
    "googlekeepflow/worker_external_edit.py",
    "googlekeepflow/worker_common.py",
    "googlekeepflow/keep_cache.py",
)

logger = setup_worker_logger("external_edit_worker", plugindir)


class EditConflictError(RuntimeError):
    pass


EPOCH = datetime.fromtimestamp(0, timezone.utc)


class FileLock:
    def __init__(self, lock_file):
        self.lock_file = Path(lock_file)
        self.fd = None

    def acquire(self):
        try:
            if self.lock_file.exists() and time.time() - self.lock_file.stat().st_mtime > LOCK_STALE_SECONDS:
                self.lock_file.unlink()
        except OSError as exc:
            logger.debug("Failed to inspect stale edit lock %s: %s: %s", self.lock_file, type(exc).__name__, exc)

        try:
            self.fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.fd, str(os.getpid()).encode())
            return True
        except FileExistsError:
            return False

    def release(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError as exc:
                logger.warning("Failed to close edit lock descriptor: %s: %s", type(exc).__name__, exc)
            self.fd = None
        try:
            self.lock_file.unlink()
        except OSError as exc:
            logger.warning("Failed to delete edit lock %s: %s: %s", self.lock_file, type(exc).__name__, exc)


def safe_note_id(note_id):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(note_id or "").strip())[:120] or "note"


def note_type_value(note):
    value = getattr(note, "type", "")
    return str(getattr(value, "value", value) or "")


def timestamp_is_set(value):
    if value is None:
        return False
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value > EPOCH
    return bool(value)


def note_is_deleted_or_trashed(note):
    if bool(getattr(note, "trashed", False)):
        return True

    timestamps = getattr(note, "timestamps", None)
    return timestamp_is_set(getattr(timestamps, "trashed", None)) or timestamp_is_set(getattr(timestamps, "deleted", None))


def file_signature(path):
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def code_fingerprint(plugin_dir=plugindir):
    plugin_dir = Path(plugin_dir)
    fingerprint = {}
    for relative_path in WATCHED_CODE_PATHS:
        path = plugin_dir / relative_path
        try:
            stat = path.stat()
            fingerprint[relative_path] = {
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        except OSError:
            fingerprint[relative_path] = None
    return fingerprint


def write_watch_state(edit_dir, fingerprint, pid=None):
    state_path = Path(edit_dir) / WATCH_STATE_NAME
    state = {
        "pid": int(pid or os.getpid()),
        "started_at": int(time.time()),
        "fingerprint": fingerprint,
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state_path


def remove_watch_state(edit_dir):
    try:
        state_path = Path(edit_dir) / WATCH_STATE_NAME
        if state_path.exists():
            state_path.unlink()
    except OSError as exc:
        logger.debug("Failed to remove edit watch state: %s: %s", type(exc).__name__, exc)


def code_fingerprint_changed(start_fingerprint, plugin_dir=plugindir):
    return code_fingerprint(plugin_dir) != start_fingerprint


def read_text_file(path):
    return Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def write_text_file(path, text):
    Path(path).write_text(str(text or ""), encoding="utf-8", newline="\r\n")


def open_default_editor(path):
    path = Path(path)
    if sys.platform == "win32":
        os.startfile(str(path))
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def load_job(job_path):
    job_path = Path(job_path)
    raw = unprotect_bytes(job_path.read_bytes()).decode("utf-8")
    job = json.loads(raw)
    if not isinstance(job, dict):
        raise ValueError("Invalid external edit job")
    return job


def delete_job_file(job_path):
    job_path = Path(job_path)
    try:
        if job_path.exists():
            job_path.unlink()
            logger.debug("Deleted external edit job %s", job_path.name)
    except OSError as exc:
        logger.warning("Failed to delete external edit job %s: %s: %s", job_path.name, type(exc).__name__, exc)


def iter_jobs(job_dir):
    def job_mtime(path):
        try:
            return path.stat().st_mtime
        except OSError:
            return 0

    for job_path in sorted(Path(job_dir).glob(JOB_PATTERN), key=job_mtime):
        try:
            yield job_path, load_job(job_path)
        except Exception as exc:
            logger.error("Failed to load external edit job %s; leaving file for retry: %s: %s", job_path.name, type(exc).__name__, exc)


def cleanup_edit_file(path):
    try:
        if Path(path).exists():
            Path(path).unlink()
    except OSError as exc:
        logger.debug("Failed to delete external edit file %s: %s: %s", path, type(exc).__name__, exc)


def cleanup_active_edit_files(active, keep_files=False):
    if keep_files:
        return
    for state in active.values():
        cleanup_edit_file(state["path"])


def backup_edit_file(path, suffix):
    path = Path(path)
    if not path.exists():
        return None

    backup_path = path.with_suffix(suffix)
    if backup_path.exists():
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = path.with_name(f"{path.stem}.{timestamp}{suffix}")

    try:
        path.replace(backup_path)
        return backup_path
    except OSError as exc:
        logger.warning("Failed to backup external edit file %s: %s: %s", path, type(exc).__name__, exc)
        return None


def sidecar_path(path, suffix):
    path = Path(path)
    target = path.with_suffix(suffix)
    if target.exists():
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        target = path.with_name(f"{path.stem}.{timestamp}{suffix}")
    return target


def write_sidecar_text(path, suffix, text):
    target = sidecar_path(path, suffix)
    write_text_file(target, text)
    return target


def file_launch_url(path):
    if not path:
        return ""
    try:
        return Path(path).resolve().as_uri()
    except (OSError, ValueError):
        return ""


def show_job_notification(job, title, message, launch_path=None):
    show_notification(
        title,
        message,
        plugindir,
        logger,
        launch_url=file_launch_url(launch_path),
        enabled=bool(job.get("show_notifications", True)),
    )


def sync_note_text(settings_dir, job, new_text, last_synced_text):
    email, keep = load_keep(settings_dir, job.get("email", ""))
    note_id = str(job.get("note_id", "") or "")
    note = find_note(keep, note_id)
    if note is None:
        raise ValueError("Note not found")
    if note_is_deleted_or_trashed(note):
        raise EditConflictError("Note was moved to trash in Google Keep while editing; external edit was not synced")
    if note_type_value(note) == "LIST":
        raise ValueError("Checklist notes are not supported for external editing")

    remote_text = str(getattr(note, "text", "") or "")
    if remote_text != last_synced_text and remote_text != new_text:
        raise EditConflictError("Note changed in Google Keep while editing; external edit was not synced")

    note.text = str(new_text or "")
    keep.sync()
    save_notes_cache(settings_dir, email, keep, logger)
    job["email"] = email


def add_active_edit(active, note_key, job, edit_file, last_synced_text):
    active[note_key] = {
        "job": job,
        "path": edit_file,
        "last_signature": file_signature(edit_file),
        "last_synced_text": last_synced_text,
        "pending_signature": None,
        "pending_since": None,
        "remote_conflict": False,
    }
    return active[note_key]


def mark_remote_conflict(state, message, remote_text=None):
    state["remote_conflict"] = True
    if remote_text is not None:
        try:
            remote_path = write_sidecar_text(state["path"], ".remote.txt", remote_text)
            state["remote_path"] = remote_path
            message = f"{message} Click to open the remote copy."
        except OSError as exc:
            logger.warning("Failed to save remote conflict copy: %s: %s", type(exc).__name__, exc)
    show_job_notification(state["job"], "Note changed in Google Keep", message, launch_path=state.get("remote_path"))


def verify_cached_edit_remote(settings_dir, state):
    note_id = str(state["job"].get("note_id", "") or "")
    email, keep = load_keep(settings_dir, state["job"].get("email", ""))
    note = find_note(keep, note_id)
    if note is None:
        mark_remote_conflict(state, "The note was not found in Google Keep. Your cached copy stays open.")
        return
    if note_is_deleted_or_trashed(note):
        mark_remote_conflict(state, "The note was moved to trash in Google Keep. Your cached copy stays open.")
        return
    if note_type_value(note) == "LIST":
        mark_remote_conflict(state, "The note is now a checklist in Google Keep. Your cached copy stays open.")
        return

    remote_text = str(getattr(note, "text", "") or "")
    if remote_text != state["last_synced_text"]:
        mark_remote_conflict(
            state,
            "Your editor has the cached version.",
            remote_text=remote_text,
        )
        return

    state["job"]["email"] = email
    save_notes_cache(settings_dir, email, keep, logger)


def open_edit_job(settings_dir, edit_dir, active, job):
    note_id = str(job.get("note_id", "") or "")
    if not note_id:
        raise ValueError("Missing note id")

    note_key = safe_note_id(note_id)
    if note_key in active:
        open_default_editor(active[note_key]["path"])
        show_job_notification(job, "Note already open", "This note is already open in an external editor.")
        return

    edit_file = edit_dir / f"{note_key}.txt"
    cached = load_note_body_cache(settings_dir, job.get("email", ""), note_id, logger)
    if cached is not None:
        last_synced_text = str(cached.get("text", "") or "")
        write_text_file(edit_file, last_synced_text)
        cached_job = {**job, "email": str(cached.get("email", "") or job.get("email", "")), "note_id": note_id}
        state = add_active_edit(active, note_key, cached_job, edit_file, last_synced_text)
        logger.info("Opening cached external edit file for note: id=%s", note_id)
        open_default_editor(edit_file)
        show_job_notification(job, "Editing Google Keep note", "Saves sync back to Google Keep.")
        try:
            verify_cached_edit_remote(settings_dir, state)
        except Exception as exc:
            logger.warning("Failed to verify cached external edit: id=%s %s: %s", note_id, type(exc).__name__, exc)
        return

    email, keep = load_keep(settings_dir, job.get("email", ""))
    note = find_note(keep, note_id)
    if note is None:
        raise ValueError("Note not found")
    if note_is_deleted_or_trashed(note):
        raise ValueError("Note is in trash and cannot be edited externally")
    if note_type_value(note) == "LIST":
        raise ValueError("Checklist notes are not supported for external editing")

    last_synced_text = str(getattr(note, "text", "") or "")
    write_text_file(edit_file, last_synced_text)
    add_active_edit(active, note_key, {**job, "email": email, "note_id": note_id}, edit_file, last_synced_text)
    logger.info("Opening external edit file for note: id=%s", note_id)
    open_default_editor(edit_file)
    show_job_notification(job, "Editing Google Keep Note", "Save the text file to sync changes back to Google Keep.")


def process_active_edits(settings_dir, active):
    now = time.time()
    for note_key in list(active.keys()):
        state = active[note_key]
        path = state["path"]
        signature = file_signature(path)
        note_id = state["job"].get("note_id", "")
        if signature is None:
            logger.info("External edit file deleted: id=%s", note_id)
            active.pop(note_key, None)
            continue

        if signature != state["last_signature"] and signature != state["pending_signature"]:
            state["pending_signature"] = signature
            state["pending_since"] = now
            continue

        if state["pending_signature"] is None or now - state["pending_since"] < DEBOUNCE_SECONDS:
            continue

        edited_text = read_text_file(path)
        state["last_signature"] = file_signature(path)
        state["pending_signature"] = None
        state["pending_since"] = None
        if edited_text == state["last_synced_text"]:
            continue

        if state.get("remote_conflict"):
            backup_path = backup_edit_file(path, ".conflict.txt")
            message = "The note changed in Google Keep. Your version was not synced."
            if backup_path:
                message = f"{message} Click to open your saved copy."
            show_job_notification(state["job"], "External Edit Not Synced", message, launch_path=backup_path)
            active.pop(note_key, None)
            continue

        try:
            sync_note_text(settings_dir, state["job"], edited_text, state["last_synced_text"])
            state["last_synced_text"] = edited_text
            logger.info("External edit synced: id=%s chars=%s", note_id, len(edited_text))
            show_job_notification(state["job"], "Google Keep note synced", "Your saved text was sent to Google Keep.")
        except Exception as exc:
            logger.error("External edit failed: id=%s %s: %s", note_id, type(exc).__name__, exc)
            suffix = ".conflict.txt" if isinstance(exc, EditConflictError) else ".failed.txt"
            backup_path = backup_edit_file(path, suffix)
            if backup_path:
                logger.info("External edit backup saved: id=%s file=%s", note_id, backup_path.name)
            message = short_error(exc)
            if backup_path:
                message = f"{message} Click to open your saved copy."
            show_job_notification(state["job"], "External edit failed", message, launch_path=backup_path)
            active.pop(note_key, None)


class ExternalEditEventHandler(FileSystemEventHandler):
    def __init__(self, wake_event):
        self.wake_event = wake_event

    def on_any_event(self, event):
        if getattr(event, "is_directory", False):
            return

        for raw_path in (getattr(event, "src_path", ""), getattr(event, "dest_path", "")):
            if not raw_path:
                continue
            name = Path(raw_path).name
            if name in (WATCH_LOCK_NAME, WATCH_STATE_NAME):
                continue
            self.wake_event.set()
            return


def start_filesystem_watcher(edit_dir, logger):
    if not WATCHDOG_AVAILABLE:
        logger.warning("watchdog not installed, external edit watcher using polling")
        return None, None

    wake_event = threading.Event()
    observer = Observer()
    try:
        observer.schedule(ExternalEditEventHandler(wake_event), str(edit_dir), recursive=True)
        observer.start()
        logger.info("External edit filesystem watcher started")
        return observer, wake_event
    except Exception as exc:
        logger.warning("Failed to start watchdog observer, using polling: %s: %s", type(exc).__name__, exc)
        try:
            observer.stop()
        except Exception:
            pass
        return None, None


def stop_filesystem_watcher(observer, logger):
    if observer is None:
        return
    observer.stop()
    observer.join(timeout=5)
    logger.info("External edit filesystem watcher stopped")


def seconds_until_next_pending_edit(active, now):
    waits = []
    for state in active.values():
        pending_since = state.get("pending_since")
        if state.get("pending_signature") is not None and pending_since is not None:
            waits.append(max(0, pending_since + DEBOUNCE_SECONDS - now))
    return min(waits) if waits else None


def has_due_pending_edit(active, now):
    pending_wait = seconds_until_next_pending_edit(active, now)
    return pending_wait is not None and pending_wait <= 0


def wait_for_external_edit_work(wake_event, active, last_update_check, last_activity, last_fallback_scan):
    if wake_event is None:
        time.sleep(POLL_SECONDS)
        return last_fallback_scan

    now = time.time()
    wait_times = [
        max(0, UPDATE_CHECK_SECONDS - (now - last_update_check)),
        max(0, WATCHDOG_FALLBACK_SCAN_SECONDS - (now - last_fallback_scan)),
    ]
    pending_wait = seconds_until_next_pending_edit(active, now)
    if pending_wait is not None:
        wait_times.append(pending_wait)
    if not active:
        wait_times.append(max(0, IDLE_EXIT_SECONDS - (now - last_activity)))

    wake_event.clear()
    wake_event.wait(min(wait_times))
    return last_fallback_scan


def main():
    if len(sys.argv) != 2:
        logger.error("Invalid arguments count: %s", len(sys.argv))
        sys.exit(1)

    settings_dir = Path(sys.argv[1])
    edit_dir = settings_dir / EDIT_DIR_NAME
    job_dir = edit_dir / JOB_DIR_NAME
    edit_dir.mkdir(parents=True, exist_ok=True)
    job_dir.mkdir(parents=True, exist_ok=True)

    lock = FileLock(edit_dir / WATCH_LOCK_NAME)
    if not lock.acquire():
        logger.info("External edit watcher already running")
        return

    active = {}
    last_activity = time.time()
    last_update_check = 0
    update_exit = False
    start_fingerprint = code_fingerprint()
    observer, wake_event = start_filesystem_watcher(edit_dir, logger)
    last_fallback_scan = 0
    write_watch_state(edit_dir, start_fingerprint)
    logger.info("External edit watcher started")
    try:
        while True:
            now = time.time()
            force_scan = wake_event is None or now - last_fallback_scan >= WATCHDOG_FALLBACK_SCAN_SECONDS
            pending_due = has_due_pending_edit(active, now)
            if now - last_update_check >= UPDATE_CHECK_SECONDS:
                last_update_check = now
                if code_fingerprint_changed(start_fingerprint):
                    update_exit = True
                    logger.info("External edit watcher exiting because plugin files changed")
                    show_notification(
                        "GoogleKeepFlow Updated",
                        "Reopen note editing to continue syncing. Edit files were left untouched.",
                        plugindir,
                        logger,
                    )
                    return

            opened_jobs = 0
            if force_scan or pending_due or wake_event.is_set():
                last_fallback_scan = now
                for job_path, job in iter_jobs(job_dir):
                    try:
                        open_edit_job(settings_dir, edit_dir, active, job)
                        delete_job_file(job_path)
                        opened_jobs += 1
                    except Exception as exc:
                        logger.error("Failed to open external edit: %s: %s", type(exc).__name__, exc)
                        show_job_notification(job, "External edit failed", short_error(exc))
                        delete_job_file(job_path)

                process_active_edits(settings_dir, active)

            if opened_jobs or active:
                last_activity = time.time()
            elif time.time() - last_activity > IDLE_EXIT_SECONDS:
                logger.info("External edit watcher idle timeout")
                return

            last_fallback_scan = wait_for_external_edit_work(
                wake_event,
                active,
                last_update_check,
                last_activity,
                last_fallback_scan,
            )
    finally:
        stop_filesystem_watcher(observer, logger)
        remove_watch_state(edit_dir)
        if update_exit:
            logger.info("External edit watcher left active edit files in place after update")
        else:
            cleanup_active_edit_files(active)
        lock.release()


if __name__ == "__main__":
    main()
