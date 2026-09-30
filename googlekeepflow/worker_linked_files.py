import json
import os
import sys
import threading
import time
from collections import Counter
from pathlib import Path

package_dir = Path(__file__).parent.resolve()
plugindir = package_dir.parent
if str(plugindir) not in sys.path:
    sys.path.insert(0, str(plugindir))
lib_path = plugindir / "lib"
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

from googlekeepflow.keep_auth_store import unprotect_bytes
from gkeepapi.exception import LoginException, SyncException
from googlekeepflow.file_identity import file_identity, find_path_by_identity, is_recycle_bin_path
from googlekeepflow.keep_http import KeepRateLimitedError, api_usage, enable_api_usage_log
from googlekeepflow.keep_autostart import autostart_command, autostart_enabled, update_autostart
from googlekeepflow.keep_file_links import (
    ACTION_LINK,
    ACTION_RESOLVE,
    ACTION_UNLINK,
    DIRECTION_PULL,
    DIRECTION_PUSH,
    JOB_PATTERN,
    LOCK_HEARTBEAT_SECONDS,
    LOCK_STALE_SECONDS,
    MAX_NOTE_CHARS,
    STATUS_CONFLICT,
    STATUS_ERROR,
    STATUS_FILE_MISSING,
    STATUS_NOTE_MISSING,
    STATUS_SYNCED,
    WATCH_LOCK_NAME,
    backups_dir,
    decode_file_bytes,
    encode_file_text,
    file_age_seconds,
    find_link_by_path,
    has_pending_jobs,
    is_linkable_file,
    jobs_dir,
    links_dir,
    load_registry,
    normalize_link_path,
    normalize_text,
    path_key,
    save_registry,
    watch_key,
)
from googlekeepflow.worker_common import (
    find_note,
    load_keep,
    next_top_sort_value,
    save_notes_cache,
    setup_worker_logger,
    short_error,
    show_notification,
)
from googlekeepflow.worker_external_edit import (
    code_fingerprint,
    code_fingerprint_changed,
    file_launch_url,
    file_signature,
    note_is_deleted_or_trashed,
    note_type_value,
)

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    FileSystemEventHandler = object
    Observer = None
    WATCHDOG_AVAILABLE = False


DEBOUNCE_SECONDS = 1.5
REMOTE_POLL_SECONDS = 60
LOCAL_SCAN_SECONDS = 10
UPDATE_CHECK_SECONDS = 15
POLL_SECONDS = 1
MISSING_RECHECK_SECONDS = 0.5
RELOCATE_GRACE_SECONDS = 3
MIN_PUSH_INTERVAL_SECONDS = 5
LOOP_ERROR_BACKOFF_SECONDS = 5
RATE_LIMIT_BACKOFF_MIN_SECONDS = 2 * 60
RATE_LIMIT_BACKOFF_MAX_SECONDS = 30 * 60
STALE_SYNC_NOTIFY_SECONDS = 30 * 60
STATS_LOG_SECONDS = 60 * 60
BACKUP_KEEP_SECONDS = 30 * 24 * 60 * 60
WATCHED_CODE_PATHS = (
    "plugin.json",
    "googlekeepflow/worker_linked_files.py",
    "googlekeepflow/keep_file_links.py",
    "googlekeepflow/keep_autostart.py",
    "googlekeepflow/file_identity.py",
    "googlekeepflow/keep_http.py",
    "googlekeepflow/worker_external_edit.py",
    "googlekeepflow/worker_common.py",
    "googlekeepflow/keep_cache.py",
)

ACTION_NONE = "none"
ACTION_ADOPT = "adopt"
ACTION_PUSH = "push"
ACTION_PULL = "pull"
ACTION_CONFLICT = "conflict"

PAUSED_STATUSES = (STATUS_CONFLICT, STATUS_ERROR, STATUS_FILE_MISSING, STATUS_NOTE_MISSING)

logger = setup_worker_logger("linked_files_worker", plugindir)


class HeartbeatLock:
    def __init__(self, lock_file, stale_seconds=LOCK_STALE_SECONDS):
        self.lock_file = Path(lock_file)
        self.stale_seconds = stale_seconds
        self.fd = None

    def acquire(self):
        age = file_age_seconds(self.lock_file)
        if age is not None and age > self.stale_seconds:
            try:
                self.lock_file.unlink()
                logger.warning("Removed stale linked files lock")
            except OSError as exc:
                logger.debug("Failed to remove stale linked files lock: %s: %s", type(exc).__name__, exc)
        try:
            self.fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.fd, str(os.getpid()).encode())
            return True
        except FileExistsError:
            return False

    def heartbeat(self):
        if self.fd is None:
            return
        try:
            os.utime(self.lock_file, None)
        except OSError as exc:
            logger.debug("Failed to update linked files lock heartbeat: %s: %s", type(exc).__name__, exc)

    def release(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError as exc:
                logger.warning("Failed to close linked files lock: %s: %s", type(exc).__name__, exc)
            self.fd = None
        try:
            self.lock_file.unlink()
        except OSError as exc:
            logger.warning("Failed to delete linked files lock: %s: %s", type(exc).__name__, exc)


def reconcile_action(last_synced_text, local_text, remote_text):
    """Three-way decision against the last text both sides agreed on."""
    local_changed = local_text != last_synced_text
    remote_changed = remote_text != last_synced_text
    if not local_changed and not remote_changed:
        return ACTION_NONE
    if local_text == remote_text:
        return ACTION_ADOPT
    if local_changed and not remote_changed:
        return ACTION_PUSH
    if remote_changed and not local_changed:
        return ACTION_PULL
    return ACTION_CONFLICT


def too_long_message(text):
    return f"File is too long for Google Keep ({len(text)}/{MAX_NOTE_CHARS} characters)"


def is_auth_error(exc):
    # load_worker_auth raises ValueError for a missing or different signed-in account.
    return isinstance(exc, (LoginException, ValueError))


def sync_error_message(exc, email=""):
    text = str(exc)
    if "does not match" in text:
        return f"signed in to a different Google account than {email}" if email else "signed in to a different Google account"
    if "setup required" in text:
        return "not signed in to Google Keep"
    if isinstance(exc, KeepRateLimitedError):
        return "Google Keep is limiting requests, sync slowed down"
    if isinstance(exc, LoginException):
        return "Google sign-in expired"
    if type(exc).__module__.startswith(("requests", "urllib3")) or isinstance(exc, (ConnectionError, TimeoutError)):
        return "no connection to Google Keep"
    return short_error(exc)


def load_job(job_path):
    job = json.loads(unprotect_bytes(Path(job_path).read_bytes()).decode("utf-8"))
    if not isinstance(job, dict):
        raise ValueError("Invalid linked file job")
    return job


def iter_job_paths(job_dir):
    def job_mtime(path):
        try:
            return path.stat().st_mtime
        except OSError:
            return 0

    return sorted(Path(job_dir).glob(JOB_PATTERN), key=job_mtime)


def delete_file(path):
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Failed to delete %s: %s: %s", Path(path).name, type(exc).__name__, exc)


def usable_note(note):
    if note is None or note_is_deleted_or_trashed(note):
        raise ValueError("Note not found in Google Keep")
    if note_type_value(note) == "LIST":
        raise ValueError("Checklist notes cannot be synced with a file")
    return note


class LinkedFilesEventHandler(FileSystemEventHandler):
    def __init__(self, worker):
        self.worker = worker

    def on_any_event(self, event):
        if getattr(event, "is_directory", False):
            return
        for raw_path in (getattr(event, "src_path", ""), getattr(event, "dest_path", "")):
            if raw_path and self.worker.is_watched_path(raw_path):
                self.worker.wake_event.set()
                return


class LinkedFilesWorker:
    def __init__(self, settings_dir, lock=None):
        self.settings_dir = Path(settings_dir)
        self.lock = lock
        self.job_dir = jobs_dir(settings_dir, create=True)
        self.job_dir_key = os.path.normcase(str(self.job_dir))
        self.registry = load_registry(settings_dir, logger)
        self.clients = {}
        self.signatures = {}
        self.pending = {}
        self.missing_since = {}
        self.last_push = {}
        self.remote_error = ""
        self.dirty = False
        self.backoff_seconds = 0
        self.backoff_until = 0
        self.failing_since = None
        self.failure_reason = ""
        self.stale_notified = False
        self.stats = Counter()
        self.stats_started = time.time()
        self.wake_event = threading.Event()
        self.observer = None
        self.watched_dirs = set()
        self.watched_keys = frozenset()

    @property
    def links(self):
        return self.registry.setdefault("links", {})

    def notify(self, title, message, launch_path=None):
        show_notification(
            title,
            message,
            plugindir,
            logger,
            launch_url=file_launch_url(launch_path),
            enabled=bool(self.registry.get("show_notifications", True)),
        )

    def save(self):
        try:
            save_registry(self.settings_dir, self.registry)
            self.dirty = False
        except OSError as exc:
            # Kept in memory and retried by the main loop.
            self.dirty = True
            logger.warning("Failed to save linked files registry: %s: %s", type(exc).__name__, exc)

    def count_response(self, response):
        self.stats["requests"] += 1

    def synced_keep(self, email):
        key = str(email or "").strip().lower()
        client = self.clients.get(key)
        if client is None:
            self.stats["logins"] += 1
            actual_email, keep = load_keep(self.settings_dir, key, on_response=self.count_response)
            self.clients[key] = (actual_email, keep)
            return actual_email, keep
        actual_email, keep = client
        self.sync_keep(key, keep)
        return actual_email, keep

    def sync_keep(self, email, keep, local_changes=False):
        self.stats["syncs"] += 1
        try:
            keep.sync()
        except Exception as exc:
            # A client holding unsent edits must go, or its text would be taken for the server's.
            # Otherwise it is kept: signing in again costs a login plus a full download.
            if local_changes or isinstance(exc, (LoginException, SyncException)):
                self.clients.pop(str(email or "").strip().lower(), None)
            raise

    def save_cache(self, email, keep):
        save_notes_cache(self.settings_dir, email, keep, logger)

    def write_backup(self, path, text, kind, file_format):
        path = Path(path)
        backup_dir = backups_dir(self.settings_dir, create=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{path.stem}.{timestamp}.{kind}{path.suffix}"
        backup_path.write_bytes(encode_file_text(text, file_format))
        logger.info("Linked file backup saved: %s", backup_path.name)
        return backup_path

    def prune_backups(self):
        backup_dir = backups_dir(self.settings_dir)
        if not backup_dir.exists():
            return
        for path in backup_dir.iterdir():
            age = file_age_seconds(path)
            if age is not None and age > BACKUP_KEEP_SECONDS:
                delete_file(path)

    def read_local(self, entry):
        path = Path(entry["path"])
        signature = file_signature(path)
        if signature is None:
            # Editors that save through a temp file briefly remove the target.
            time.sleep(MISSING_RECHECK_SECONDS)
            signature = file_signature(path)
            if signature is None:
                raise FileNotFoundError(str(path))
        text, file_format = decode_file_bytes(path.read_bytes())
        return text, file_format, signature

    def write_local(self, entry, text, expected_signature=None):
        path = Path(entry["path"])
        if expected_signature is not None and file_signature(path) != expected_signature:
            return False
        path.write_bytes(encode_file_text(text, entry.get("format")))
        self.signatures[entry["note_id"]] = file_signature(path)
        self.pending.pop(entry["note_id"], None)
        return True

    def set_status(self, entry, status, message="", notify_title="", launch_path=None):
        previous_status = entry.get("status", STATUS_SYNCED)
        if previous_status == status and entry.get("message", "") == message:
            return False
        entry["status"] = status
        entry["message"] = message
        logger.info("Linked file status: id=%s status=%s", entry.get("note_id", ""), status)
        if notify_title:
            self.notify(notify_title, f"{Path(entry['path']).name}: {message}" if message else Path(entry["path"]).name, launch_path)
        elif status == STATUS_SYNCED:
            self.announce_resume(entry, previous_status)
        return True

    def mark_synced(self, entry, text, announce=True):
        previous_status = entry.get("status", STATUS_SYNCED)
        entry["last_synced_text"] = text
        entry["synced_at"] = time.time()
        entry["status"] = STATUS_SYNCED
        entry["message"] = ""
        if announce:
            self.announce_resume(entry, previous_status)

    def announce_resume(self, entry, previous_status, suffix=""):
        if previous_status not in PAUSED_STATUSES:
            return
        name = Path(entry["path"]).name
        messages = {
            STATUS_FILE_MISSING: f"{name} is back. Syncing with Google Keep resumed.",
            STATUS_NOTE_MISSING: f"The note for {name} is back in Google Keep. Syncing resumed.",
            STATUS_CONFLICT: f"{name} matches the Google Keep note again. Syncing resumed.",
        }
        logger.info("Linked file sync resumed: id=%s previous=%s", entry.get("note_id", ""), previous_status)
        message = messages.get(previous_status, f"{name} is syncing with Google Keep again.")
        self.notify("File sync resumed", f"{message}{suffix}")

    def report_remote_error(self, exc, entries=(), email=""):
        message = short_error(exc)
        if message != self.remote_error:
            logger.warning("Linked files sync with Google Keep failed: %s: %s", type(exc).__name__, exc)
        self.remote_error = message
        self.stats["errors"] += 1

        sync_error = sync_error_message(exc, email)
        if self.failing_since is None:
            self.failing_since = time.time()
        self.failure_reason = sync_error
        if isinstance(exc, KeepRateLimitedError):
            self.stats["rate_limited"] += 1
            first_limit = self.backoff_seconds == 0
            seconds = self.start_backoff()
            logger.warning("Google Keep rate limit, next attempt in %s s", seconds)
            if first_limit:
                self.notify(
                    "Google Keep is limiting requests",
                    f"File sync slowed down and will retry in {max(1, round(seconds / 60))} min.",
                )
        changed = False
        for entry in entries:
            if entry.get("sync_error") != sync_error:
                entry["sync_error"] = sync_error
                changed = True
        if changed:
            self.dirty = True
            if is_auth_error(exc):
                self.notify("File sync can't reach your account", f"Files are not syncing: {sync_error}. Run keep setup to sign in.")

    def clear_sync_error(self, entries):
        for entry in entries:
            if entry.pop("sync_error", None):
                self.dirty = True
        if self.backoff_seconds:
            logger.info("Google Keep accepts requests again, normal sync interval restored")
        self.backoff_seconds = 0
        self.backoff_until = 0
        self.failing_since = None
        self.stale_notified = False

    def start_backoff(self):
        self.backoff_seconds = min(
            max(self.backoff_seconds * 2, RATE_LIMIT_BACKOFF_MIN_SECONDS),
            RATE_LIMIT_BACKOFF_MAX_SECONDS,
        )
        self.backoff_until = time.time() + self.backoff_seconds
        return self.backoff_seconds

    def remote_allowed(self, now):
        return now >= self.backoff_until

    def check_stale_sync(self, now):
        # Safety net for failures that have no notification of their own.
        if self.failing_since is None or self.stale_notified or not self.links:
            return
        if now - self.failing_since < STALE_SYNC_NOTIFY_SECONDS:
            return
        self.stale_notified = True
        minutes = int((now - self.failing_since) // 60)
        logger.warning("Linked files not synced for %s min: %s", minutes, self.failure_reason)
        self.notify("Files are not syncing", f"Nothing synced with Google Keep for {minutes} min: {self.failure_reason}.")

    def log_stats(self, now, force=False):
        if not force and now - self.stats_started < STATS_LOG_SECONDS:
            return
        minutes = max(1, round((now - self.stats_started) / 60))
        stats = self.stats
        logger.info(
            "Linked files stats: minutes=%s links=%s requests=%s syncs=%s pushes=%s pulls=%s errors=%s rate_limited=%s logins=%s backoff=%s",
            minutes,
            len(self.links),
            stats["requests"],
            stats["syncs"],
            stats["pushes"],
            stats["pulls"],
            stats["errors"],
            stats["rate_limited"],
            stats["logins"],
            self.backoff_seconds,
        )
        for key in ("syncs", "pushes", "pulls", "errors", "logins"):
            api_usage.add(key, stats[key])
        api_usage.flush(now)
        self.stats = Counter()
        self.stats_started = now

    def reconcile(self, note_ids):
        by_email = {}
        for note_id in note_ids:
            entry = self.links.get(note_id)
            if entry:
                by_email.setdefault(str(entry.get("email", "")).strip().lower(), []).append(entry)

        changed = False
        for email, entries in by_email.items():
            try:
                actual_email, keep = self.synced_keep(email)
            except Exception as exc:
                self.report_remote_error(exc, entries, email)
                continue

            pushed = []
            pulled = False
            for entry in entries:
                try:
                    result = self.reconcile_entry(keep, entry, pushed)
                except Exception:
                    logger.exception("Failed to sync linked file: id=%s", entry.get("note_id", ""))
                    result = False
                changed = changed or bool(result)
                pulled = pulled or result == ACTION_PULL

            if pushed:
                try:
                    self.sync_keep(email, keep, local_changes=True)
                except Exception as exc:
                    self.report_remote_error(exc, entries, email)
                    continue
                for entry, text, empty_backup in pushed:
                    self.mark_synced(entry, text)
                    self.last_push[entry["note_id"]] = time.time()
                    self.stats["pushes"] += 1
                    logger.info("Linked file pushed: id=%s chars=%s", entry["note_id"], len(text))
                    if empty_backup:
                        self.notify(
                            "Synced file is empty",
                            f"{Path(entry['path']).name} is empty, so the note was cleared too. Click to open the previous note text.",
                            launch_path=empty_backup,
                        )
                changed = True
            self.remote_error = ""
            self.clear_sync_error(entries)
            if pushed or pulled:
                self.save_cache(actual_email, keep)

        if changed or self.dirty:
            self.save()

    def reconcile_entry(self, keep, entry, pushed):
        note = find_note(keep, entry["note_id"])
        if note is None or note_is_deleted_or_trashed(note):
            return self.set_status(
                entry,
                STATUS_NOTE_MISSING,
                "Note was deleted or moved to trash in Google Keep, syncing is paused",
                notify_title="File sync paused",
            )
        if note_type_value(note) == "LIST":
            return self.set_status(entry, STATUS_ERROR, "Note became a checklist, syncing is paused", notify_title="File sync paused")

        try:
            local_text, file_format, signature = self.read_local(entry)
        except FileNotFoundError:
            if not self.missing_grace_passed(entry["note_id"]):
                # scan_local looks for a rename or move once the file has been gone for a moment.
                return False
            if not self.relocate(entry):
                return self.set_status(entry, STATUS_FILE_MISSING, "File not found, syncing is paused", notify_title="File sync paused")
            return self.reconcile_entry(keep, entry, pushed)
        except UnicodeDecodeError:
            return self.set_status(entry, STATUS_ERROR, "File is not UTF-8 text", notify_title="File sync paused")
        except OSError as exc:
            logger.warning("Failed to read linked file: id=%s %s: %s", entry["note_id"], type(exc).__name__, exc)
            return False
        entry["format"] = file_format

        remote_text = normalize_text(getattr(note, "text", ""))
        if entry.get("status") == STATUS_CONFLICT:
            if local_text != remote_text:
                return False
            self.mark_synced(entry, local_text)
            return ACTION_ADOPT

        action = reconcile_action(entry.get("last_synced_text", ""), local_text, remote_text)
        if action == ACTION_NONE:
            return self.set_status(entry, STATUS_SYNCED)

        if action == ACTION_ADOPT:
            self.mark_synced(entry, local_text)
            return action

        if action == ACTION_PUSH:
            if len(local_text) > MAX_NOTE_CHARS:
                return self.set_status(
                    entry,
                    STATUS_ERROR,
                    f"File is longer than the Google Keep limit of {MAX_NOTE_CHARS} characters",
                    notify_title="File sync paused",
                )
            empty_backup = None
            if not local_text.strip() and remote_text.strip():
                empty_backup = self.write_backup(entry["path"], remote_text, "keep", file_format)
            note.text = local_text
            pushed.append((entry, local_text, empty_backup))
            return action

        if action == ACTION_PULL:
            try:
                written = self.write_local(entry, remote_text, signature)
            except OSError as exc:
                logger.warning("Failed to write linked file: id=%s %s: %s", entry["note_id"], type(exc).__name__, exc)
                return self.set_status(
                    entry,
                    STATUS_ERROR,
                    "Can't write changes from Google Keep, the file is read-only or locked by another program",
                    notify_title="File sync paused",
                )
            if not written:
                return False
            previous_status = entry.get("status", STATUS_SYNCED)
            self.mark_synced(entry, remote_text, announce=False)
            self.stats["pulls"] += 1
            logger.info("Linked file pulled: id=%s chars=%s", entry["note_id"], len(remote_text))
            if previous_status in PAUSED_STATUSES:
                self.announce_resume(entry, previous_status, " The file was updated with changes from Google Keep.")
            else:
                self.notify("Updated from Google Keep", f"{Path(entry['path']).name} was updated with changes from Google Keep.")
            return action

        backup_path = self.write_backup(entry["path"], remote_text, "keep", file_format)
        return self.set_status(
            entry,
            STATUS_CONFLICT,
            "Changed both locally and in Google Keep. Choose a version in keep links. Click to open the Google Keep version.",
            notify_title="File sync conflict",
            launch_path=backup_path,
        )

    def process_jobs(self):
        processed = False
        for job_path in iter_job_paths(self.job_dir):
            processed = True
            try:
                job = load_job(job_path)
            except Exception as exc:
                logger.error("Failed to load linked file job %s: %s: %s", job_path.name, type(exc).__name__, exc)
                delete_file(job_path)
                continue
            try:
                self.handle_job(job)
            except Exception as exc:
                logger.error("Linked file job failed: action=%s %s: %s", job.get("action", ""), type(exc).__name__, exc)
                self.notify("File sync failed", short_error(exc, limit=120))
            finally:
                delete_file(job_path)
        if processed:
            self.save()
            self.reschedule_watches()

    def handle_job(self, job):
        if "show_notifications" in job:
            self.registry["show_notifications"] = bool(job.get("show_notifications"))
        action = job.get("action")
        if action == ACTION_LINK:
            self.link_file(job)
        elif action == ACTION_UNLINK:
            self.unlink_file(str(job.get("note_id", "") or ""))
        elif action == ACTION_RESOLVE:
            self.resolve_conflict(str(job.get("note_id", "") or ""), job.get("direction", DIRECTION_PUSH))
        else:
            raise ValueError(f"Unknown linked file action: {action}")

    def link_file(self, job):
        path = Path(normalize_link_path(job.get("path", "")))
        if not is_linkable_file(path):
            raise ValueError(f"{path.name} is not an existing .txt or .md file")
        if find_link_by_path(self.registry, path):
            raise ValueError(f"{path.name} is already synced with Google Keep")
        try:
            local_text, file_format = decode_file_bytes(path.read_bytes())
        except UnicodeDecodeError:
            raise ValueError(f"{path.name} is not UTF-8 text")

        note_id = str(job.get("note_id", "") or "")
        direction = job.get("direction", DIRECTION_PUSH)
        if note_id in self.links:
            raise ValueError(f"This note is already synced with {Path(self.links[note_id]['path']).name}")
        if direction != DIRECTION_PULL and len(local_text) > MAX_NOTE_CHARS:
            raise ValueError(too_long_message(local_text))

        email, keep = self.synced_keep(job.get("email", ""))
        backup_path = None
        if note_id:
            note = usable_note(find_note(keep, note_id))
            remote_text = normalize_text(getattr(note, "text", ""))
            if direction == DIRECTION_PULL:
                if local_text.strip() and local_text != remote_text:
                    backup_path = self.write_backup(path, local_text, "local", file_format)
                if local_text != remote_text:
                    path.write_bytes(encode_file_text(remote_text, file_format))
                synced_text = remote_text
            else:
                if remote_text.strip() and remote_text != local_text:
                    backup_path = self.write_backup(path, remote_text, "keep", file_format)
                if remote_text != local_text:
                    note.text = local_text
                    self.sync_keep(email, keep, local_changes=True)
                synced_text = local_text
        else:
            sort_value = next_top_sort_value(keep, logger)
            note = keep.createNote(title=path.name, text=local_text)
            note.sort = sort_value
            self.sync_keep(email, keep, local_changes=True)
            note_id = str(note.id)
            synced_text = local_text

        entry = {
            "note_id": note_id,
            "email": email,
            "path": str(path),
            "file_id": file_identity(path),
            "format": file_format,
            "last_synced_text": synced_text,
            "status": STATUS_SYNCED,
            "message": "",
            "linked_at": time.time(),
            "synced_at": time.time(),
        }
        self.links[note_id] = entry
        self.signatures[note_id] = file_signature(path)
        self.save()
        self.save_cache(email, keep)
        logger.info("Linked file added: id=%s direction=%s", note_id, direction)

        message = f"{path.name} and Google Keep will stay in sync."
        if backup_path:
            message = f"{message} The replaced text was backed up, click to open it."
        self.notify("File sync enabled", message, launch_path=backup_path)

    def unlink_file(self, note_id):
        entry = self.links.pop(note_id, None)
        self.signatures.pop(note_id, None)
        self.pending.pop(note_id, None)
        if entry is None:
            return
        logger.info("Linked file removed: id=%s", note_id)
        self.notify("File sync stopped", f"{Path(entry['path']).name} is no longer synced. The file and the note were kept.")

    def resolve_conflict(self, note_id, direction):
        entry = self.links.get(note_id)
        if entry is None:
            raise ValueError("This file is no longer synced")
        name = Path(entry["path"]).name
        try:
            local_text, file_format, _ = self.read_local(entry)
        except FileNotFoundError:
            raise ValueError(f"{name} was not found")
        except UnicodeDecodeError:
            raise ValueError(f"{name} is not UTF-8 text")
        entry["format"] = file_format

        email, keep = self.synced_keep(entry.get("email", ""))
        note = usable_note(find_note(keep, note_id))
        remote_text = normalize_text(getattr(note, "text", ""))
        backup_path = None
        if direction == DIRECTION_PULL:
            if local_text != remote_text:
                backup_path = self.write_backup(entry["path"], local_text, "local", file_format)
                self.write_local(entry, remote_text)
            synced_text = remote_text
        else:
            if len(local_text) > MAX_NOTE_CHARS:
                raise ValueError(too_long_message(local_text))
            if local_text != remote_text:
                backup_path = self.write_backup(entry["path"], remote_text, "keep", file_format)
                note.text = local_text
                self.sync_keep(email, keep, local_changes=True)
            synced_text = local_text

        self.mark_synced(entry, synced_text, announce=False)
        self.signatures[note_id] = file_signature(entry["path"])
        self.save()
        self.save_cache(email, keep)
        logger.info("Linked file conflict resolved: id=%s direction=%s", note_id, direction)

        version = "Google Keep" if direction == DIRECTION_PULL else "local file"
        message = f"{name} now uses the {version} version."
        if backup_path:
            message = f"{message} The other version was backed up, click to open it."
        self.notify("File sync resumed", message, launch_path=backup_path)

    def scan_local(self, now):
        for note_id, entry in list(self.links.items()):
            signature = file_signature(entry.get("path", ""))
            if signature is None:
                since = self.missing_since.setdefault(note_id, now)
                if now - since < RELOCATE_GRACE_SECONDS:
                    # Editors that save through a temp file make the target vanish for a moment.
                    continue
                if self.relocate(entry):
                    signature = file_signature(entry["path"])
            else:
                self.missing_since.pop(note_id, None)
                if signature != self.signatures.get(note_id) or not entry.get("file_id"):
                    self.refresh_file_identity(entry)

            if note_id not in self.signatures:
                self.signatures[note_id] = signature
                if signature is None:
                    self.pending[note_id] = now
            elif signature != self.signatures[note_id]:
                self.signatures[note_id] = signature
                self.pending[note_id] = now

    def refresh_file_identity(self, entry):
        # Safe-write editors replace the file on every save, which gives it a new id.
        identity = file_identity(entry["path"])
        if identity and identity != entry.get("file_id"):
            entry["file_id"] = identity
            self.dirty = True

    def missing_grace_passed(self, note_id, now=None):
        now = time.time() if now is None else now
        since = self.missing_since.setdefault(note_id, now)
        return now - since >= RELOCATE_GRACE_SECONDS

    def relocate(self, entry):
        """Follow a rename or move on the same drive using the file id."""
        note_id = entry["note_id"]
        old_path = entry["path"]
        found = find_path_by_identity(old_path, entry.get("file_id"))
        if not found or is_recycle_bin_path(found) or path_key(found) == path_key(old_path):
            return False
        other = find_link_by_path(self.registry, found)
        if other is not None and other is not entry:
            return False

        entry["path"] = normalize_link_path(found)
        if entry.get("status") == STATUS_FILE_MISSING:
            entry["status"] = STATUS_SYNCED
            entry["message"] = ""
        self.missing_since.pop(note_id, None)
        self.signatures[note_id] = file_signature(entry["path"])
        self.pending[note_id] = time.time() - DEBOUNCE_SECONDS
        self.dirty = True
        self.reschedule_watches()
        logger.info("Linked file moved: id=%s", note_id)
        self.notify("Synced file moved", f"{Path(old_path).name} is now {entry['path']}. It keeps syncing with Google Keep.")
        return True

    def pending_due_at(self, note_id, since):
        return max(since + DEBOUNCE_SECONDS, self.last_push.get(note_id, 0) + MIN_PUSH_INTERVAL_SECONDS)

    def due_pending(self, now):
        return [note_id for note_id, since in self.pending.items() if now >= self.pending_due_at(note_id, since)]

    def is_watched_path(self, raw_path):
        key = watch_key(raw_path)
        return key in self.watched_keys or os.path.dirname(key) == self.job_dir_key

    def reschedule_watches(self):
        self.watched_keys = frozenset(watch_key(entry.get("path", "")) for entry in self.links.values())
        if self.observer is None:
            return
        dirs = {str(self.job_dir)}
        for entry in self.links.values():
            parent = Path(entry.get("path", "")).parent
            if parent.is_dir():
                dirs.add(str(parent))
        if dirs == self.watched_dirs:
            return
        self.observer.unschedule_all()
        handler = LinkedFilesEventHandler(self)
        for directory in dirs:
            try:
                self.observer.schedule(handler, directory, recursive=False)
            except Exception as exc:
                logger.warning("Failed to watch %s: %s: %s", directory, type(exc).__name__, exc)
        self.watched_dirs = dirs

    def start_watcher(self):
        if not WATCHDOG_AVAILABLE:
            logger.warning("watchdog not installed, linked files watcher using polling")
            return
        try:
            self.observer = Observer()
            self.observer.start()
        except Exception as exc:
            logger.warning("Failed to start linked files watcher, using polling: %s: %s", type(exc).__name__, exc)
            self.observer = None

    def stop_watcher(self):
        if self.observer is None:
            return
        try:
            self.observer.stop()
            self.observer.join(timeout=5)
        except Exception as exc:
            logger.debug("Failed to stop linked files watcher: %s: %s", type(exc).__name__, exc)
        self.observer = None

    def sync_autostart(self, has_links=True):
        # Rewritten on every check so the entry follows Flow/plugin updates that move the paths.
        enabled = has_links and autostart_enabled(self.settings_dir)
        command = autostart_command(Path(__file__).resolve(), self.settings_dir.resolve())
        try:
            change = update_autostart(enabled, command)
        except OSError as exc:
            logger.warning("Failed to update linked files autostart entry: %s: %s", type(exc).__name__, exc)
            return
        if change:
            logger.info("Linked files autostart entry %s", change)

    def wait_for_work(self, timeout):
        timeout = max(0, timeout)
        if self.observer is None:
            time.sleep(min(timeout, POLL_SECONDS))
            return
        self.wake_event.wait(timeout)
        self.wake_event.clear()

    def run(self):
        self.prune_backups()
        self.start_watcher()
        self.reschedule_watches()
        self.sync_autostart(bool(self.links))
        self.start_fingerprint = code_fingerprint(plugindir, WATCHED_CODE_PATHS)
        self.last_poll = 0
        self.last_heartbeat = time.time()
        self.last_update_check = time.time()
        logger.info("Linked files watcher started: links=%s", len(self.links))
        try:
            while True:
                try:
                    if not self.step():
                        return
                except Exception:
                    # One bad pass must not stop syncing for every file.
                    logger.exception("Linked files watcher pass failed")
                    time.sleep(LOOP_ERROR_BACKOFF_SECONDS)
                    continue
                self.wait_for_work(self.next_wait_seconds())
        finally:
            self.log_stats(time.time(), force=True)
            self.stop_watcher()

    def step(self):
        now = time.time()
        if self.lock is not None and now - self.last_heartbeat >= LOCK_HEARTBEAT_SECONDS:
            self.lock.heartbeat()
            self.last_heartbeat = now
        if now - self.last_update_check >= UPDATE_CHECK_SECONDS:
            self.last_update_check = now
            if code_fingerprint_changed(self.start_fingerprint, plugindir, WATCHED_CODE_PATHS):
                logger.info("Linked files watcher exiting because plugin files changed")
                return False

        self.process_jobs()
        if not self.links and not has_pending_jobs(self.settings_dir):
            logger.info("Linked files watcher exiting: no linked files")
            self.sync_autostart(has_links=False)
            return False

        self.scan_local(now)
        if not self.remote_allowed(now):
            # Rate limited: local changes stay pending until the backoff ends.
            pass
        elif now - self.last_poll >= REMOTE_POLL_SECONDS:
            self.last_poll = now
            self.pending.clear()
            self.reschedule_watches()
            self.sync_autostart()
            self.reconcile(list(self.links))
        else:
            due = self.due_pending(now)
            if due:
                for note_id in due:
                    self.pending.pop(note_id, None)
                self.reconcile(due)
        if self.dirty:
            self.save()
        self.check_stale_sync(time.time())
        self.log_stats(time.time())
        return True

    def next_wait_seconds(self):
        now = time.time()
        waits = [
            LOCAL_SCAN_SECONDS,
            LOCK_HEARTBEAT_SECONDS - (now - self.last_heartbeat),
            UPDATE_CHECK_SECONDS - (now - self.last_update_check),
            REMOTE_POLL_SECONDS - (now - self.last_poll),
        ]
        remote_wait = max(0, self.backoff_until - now)
        waits.extend(max(remote_wait, self.pending_due_at(note_id, since) - now) for note_id, since in self.pending.items())
        waits[3] = max(waits[3], remote_wait)
        waits.append(self.stats_started + STATS_LOG_SECONDS - now)
        if self.failing_since is not None and not self.stale_notified:
            waits.append(self.failing_since + STALE_SYNC_NOTIFY_SECONDS - now)
        grace_deadlines = (since + RELOCATE_GRACE_SECONDS - now for since in self.missing_since.values())
        waits.extend(deadline for deadline in grace_deadlines if deadline > 0)
        return min(waits)

def main():
    if len(sys.argv) != 2:
        logger.error("Invalid arguments count: %s", len(sys.argv))
        sys.exit(1)

    settings_dir = Path(sys.argv[1])
    enable_api_usage_log(settings_dir, "linked_files")
    lock = HeartbeatLock(links_dir(settings_dir, create=True) / WATCH_LOCK_NAME)
    if not lock.acquire():
        logger.info("Linked files watcher already running")
        return
    try:
        LinkedFilesWorker(settings_dir, lock).run()
    except Exception:
        logger.exception("Linked files watcher crashed")
    finally:
        lock.release()


if __name__ == "__main__":
    main()
