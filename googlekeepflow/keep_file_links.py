import codecs
import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import unquote

from googlekeepflow.keep_auth_store import protect_bytes, unprotect_bytes


LINKS_DIR_NAME = "linked_files"
REGISTRY_FILE_NAME = "links.bin"
JOB_DIR_NAME = "jobs"
JOB_PATTERN = "link_job_*.bin"
BACKUP_DIR_NAME = "backups"
WATCH_LOCK_NAME = "linked_files_watch.lock"
START_STAMP_NAME = "linked_files_start.stamp"
REGISTRY_VERSION = 1
LINKABLE_EXTENSIONS = (".txt", ".md", ".markdown", ".text")
LOCK_HEARTBEAT_SECONDS = 30
LOCK_STALE_SECONDS = 3 * 60
START_THROTTLE_SECONDS = 20
MAX_NOTE_CHARS = 20000
CF_HDROP = 15
CLIPBOARD_OPEN_ATTEMPTS = 3
CLIPBOARD_OPEN_RETRY_SECONDS = 0.05
MAX_CLIPBOARD_FILES = 32
REPLACE_ATTEMPTS = 10
REPLACE_RETRY_SECONDS = 0.05

STATUS_SYNCED = "synced"
STATUS_CONFLICT = "conflict"
STATUS_FILE_MISSING = "file_missing"
STATUS_NOTE_MISSING = "note_missing"
STATUS_ERROR = "error"

DIRECTION_PUSH = "push"
DIRECTION_PULL = "pull"

ACTION_LINK = "link"
ACTION_UNLINK = "unlink"
ACTION_RESOLVE = "resolve"


def links_dir(settings_dir, create=False):
    path = Path(settings_dir) / LINKS_DIR_NAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def jobs_dir(settings_dir, create=False):
    path = links_dir(settings_dir) / JOB_DIR_NAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir(settings_dir, create=False):
    path = links_dir(settings_dir) / BACKUP_DIR_NAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def registry_path(settings_dir):
    return links_dir(settings_dir) / REGISTRY_FILE_NAME


def empty_registry():
    return {"version": REGISTRY_VERSION, "show_notifications": True, "links": {}}


def load_registry(settings_dir, logger=None):
    path = registry_path(settings_dir)
    if not path.exists():
        return empty_registry()
    try:
        data = json.loads(unprotect_bytes(path.read_bytes()).decode("utf-8"))
    except Exception as exc:
        if logger:
            logger.warning("Failed to load linked files registry: %s: %s", type(exc).__name__, exc)
        return empty_registry()
    if not isinstance(data, dict) or data.get("version") != REGISTRY_VERSION or not isinstance(data.get("links"), dict):
        if logger:
            logger.warning("Ignoring invalid linked files registry")
        return empty_registry()
    return data


def save_registry(settings_dir, registry):
    path = registry_path(settings_dir)
    if not registry.get("links"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    raw = json.dumps(registry, ensure_ascii=False).encode("utf-8")
    tmp_path.write_bytes(protect_bytes(raw))
    replace_with_retry(tmp_path, path)


def replace_with_retry(source, target, attempts=REPLACE_ATTEMPTS, delay=REPLACE_RETRY_SECONDS):
    # Windows refuses to replace a file while another process has it open for reading.
    for attempt in range(attempts):
        try:
            Path(source).replace(target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def normalize_link_path(path):
    return str(Path(os.path.abspath(os.path.expanduser(str(path)))))


def path_key(path):
    # realpath folds symlinks, subst drives and 8.3 names so one file cannot be linked twice.
    normalized = normalize_link_path(path)
    try:
        normalized = os.path.realpath(normalized)
    except (OSError, ValueError):
        pass
    return os.path.normcase(normalized)


def watch_key(path):
    return os.path.normcase(os.path.abspath(str(path)))


def find_link_by_path(registry, path):
    key = path_key(path)
    for entry in registry.get("links", {}).values():
        if path_key(entry.get("path", "")) == key:
            return entry
    return None


def linked_file_for_note(registry, note_id):
    entry = registry.get("links", {}).get(str(note_id or ""))
    if not entry:
        return None
    path = Path(entry.get("path", ""))
    return path if path.is_file() else None


def open_file(path):
    if sys.platform == "win32":
        os.startfile(str(path))
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sorted_links(registry):
    return sorted(registry.get("links", {}).values(), key=lambda entry: Path(entry.get("path", "")).name.lower())


def is_linkable_file(path):
    try:
        path = Path(path)
        return path.suffix.lower() in LINKABLE_EXTENSIONS and path.is_file()
    except (OSError, ValueError):
        return False


def path_from_text(text):
    value = str(text or "").strip().strip('"').strip("'").strip()
    if value.lower().startswith("file:///"):
        value = unquote(value[len("file:///"):])
    if not value or ("\\" not in value and "/" not in value):
        return None
    try:
        path = Path(os.path.expandvars(os.path.expanduser(value)))
        if path.is_absolute() and path.is_file():
            return path
    except (OSError, ValueError):
        return None
    return None


def clipboard_file_paths():
    if sys.platform != "win32":
        return []

    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = ctypes.c_void_p
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT

    if not user32.IsClipboardFormatAvailable(CF_HDROP):
        return []

    for attempt in range(CLIPBOARD_OPEN_ATTEMPTS):
        if user32.OpenClipboard(None):
            break
        if attempt < CLIPBOARD_OPEN_ATTEMPTS - 1:
            time.sleep(CLIPBOARD_OPEN_RETRY_SECONDS)
    else:
        return []

    try:
        handle = user32.GetClipboardData(CF_HDROP)
        if not handle:
            return []
        count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
        paths = []
        for index in range(min(count, MAX_CLIPBOARD_FILES)):
            length = shell32.DragQueryFileW(handle, index, None, 0)
            buffer = ctypes.create_unicode_buffer(length + 1)
            shell32.DragQueryFileW(handle, index, buffer, length + 1)
            if buffer.value:
                paths.append(buffer.value)
        return paths
    finally:
        user32.CloseClipboard()


def clipboard_link_file(read_paths=clipboard_file_paths):
    try:
        paths = read_paths()
    except Exception:
        return None
    for candidate in paths or []:
        if is_linkable_file(candidate):
            return Path(candidate)
    return None


def resolve_link_source(command_text, read_clipboard_file=clipboard_link_file):
    """Return (path, search_text): a typed path wins, otherwise a file copied in Explorer."""
    typed_path = path_from_text(command_text)
    if typed_path is not None:
        return typed_path, ""
    return read_clipboard_file(), str(command_text or "").strip()


def normalize_text(text):
    return str(text or "").replace("\r\n", "\n")


def decode_file_bytes(data):
    bom = data.startswith(codecs.BOM_UTF8)
    text = data.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n" if "\n" in text else ""
    return normalize_text(text), {"bom": bom, "newline": newline}


def encode_file_text(text, file_format=None):
    file_format = file_format or {}
    newline = file_format.get("newline") or "\r\n"
    body = normalize_text(text)
    if newline != "\n":
        body = body.replace("\n", newline)
    data = body.encode("utf-8")
    if file_format.get("bom"):
        data = codecs.BOM_UTF8 + data
    return data


def queue_link_job(settings_dir, job):
    job_dir = jobs_dir(settings_dir, create=True)
    job_file = job_dir / f"link_job_{uuid.uuid4().hex}.bin"
    data = {**job, "timestamp": time.time()}
    job_file.write_bytes(protect_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8")))
    return job_file


def has_pending_jobs(settings_dir):
    try:
        return any(jobs_dir(settings_dir).glob(JOB_PATTERN))
    except OSError:
        return False


def file_age_seconds(path):
    try:
        return time.time() - Path(path).stat().st_mtime
    except OSError:
        return None


def worker_is_running(settings_dir):
    age = file_age_seconds(links_dir(settings_dir) / WATCH_LOCK_NAME)
    return age is not None and age < LOCK_STALE_SECONDS


def worker_start_recent(settings_dir):
    age = file_age_seconds(links_dir(settings_dir) / START_STAMP_NAME)
    return age is not None and age < START_THROTTLE_SECONDS


def mark_worker_start(settings_dir):
    stamp = links_dir(settings_dir, create=True) / START_STAMP_NAME
    stamp.write_text(str(int(time.time())), encoding="utf-8")


def worker_needed(settings_dir):
    if not registry_path(settings_dir).exists() and not has_pending_jobs(settings_dir):
        return False
    return not worker_is_running(settings_dir) and not worker_start_recent(settings_dir)


def link_needs_attention(entry):
    return entry.get("status", STATUS_SYNCED) != STATUS_SYNCED or bool(entry.get("sync_error"))


def link_status_text(entry):
    status = entry.get("status", STATUS_SYNCED)
    message = str(entry.get("message", "") or "")
    if status == STATUS_SYNCED:
        sync_error = str(entry.get("sync_error", "") or "")
        return f"Not synced: {sync_error}" if sync_error else "Synced with Google Keep"
    if status == STATUS_CONFLICT:
        return "Conflict: changed in both places, open the context menu to choose a version"
    if status == STATUS_FILE_MISSING:
        return "File not found, syncing is paused"
    if status == STATUS_NOTE_MISSING:
        return message or "Note not found in Google Keep, syncing is paused"
    return f"Sync error: {message}" if message else "Sync error"
