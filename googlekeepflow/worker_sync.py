import sys
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import json
import time
import os
from datetime import datetime

package_dir = Path(__file__).parent.resolve()
plugindir = package_dir.parent
if str(plugindir) not in sys.path:
    sys.path.insert(0, str(plugindir))
lib_path = plugindir / 'lib'
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

import gkeepapi
from gkeepapi import node as keep_node
from googlekeepflow.keep_auth_store import load_auth, protect_bytes, unprotect_bytes
from googlekeepflow.keep_cache import save_cache
from googlekeepflow.keep_reminders import ReminderError, create_keep_reminder
from googlekeepflow.worker_auth import load_worker_auth

USER_WANTS_NOTIFICATIONS = True
SORT_STEP = 1048576
NOTE_JOB_PATTERN = "google_keep_note_job_*.bin"
LOCK_STALE_SECONDS = 10 * 60

log_handler = RotatingFileHandler(
    plugindir / "log_worker.log",
    maxBytes=1*1024*1024,
    backupCount=1,
    encoding='utf-8'
)
log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger = logging.getLogger('sync_worker')
logger.addHandler(log_handler)
logger.setLevel(logging.INFO)

try:
    from winotify import Notification
    NOTIFICATIONS_ENABLED = True
except ImportError:
    NOTIFICATIONS_ENABLED = False
    logger.warning("winotify not installed, notifications disabled")


class FileLock:
    def __init__(self, lock_file, stale_seconds=LOCK_STALE_SECONDS):
        self.lock_file = Path(lock_file)
        self.stale_seconds = stale_seconds
        self.fd = None

    def acquire(self, timeout=0):
        # OS-level exclusive lock with stale lock detection.
        start = time.time()
        while True:
            try:
                self.fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode())
                return True
            except FileExistsError:
                try:
                    if time.time() - self.lock_file.stat().st_mtime > self.stale_seconds:
                        logger.warning("Removing stale lock file")
                        self.lock_file.unlink()
                        continue
                except OSError as exc:
                    logger.debug("Failed to inspect stale lock file %s: %s: %s", self.lock_file, type(exc).__name__, exc)
                
                if timeout == 0 or (time.time() - start) >= timeout:
                    return False
                time.sleep(0.1)

    def heartbeat(self):
        if self.fd is None:
            return
        try:
            os.utime(self.lock_file, None)
        except OSError as exc:
            logger.debug("Failed to update lock heartbeat %s: %s: %s", self.lock_file, type(exc).__name__, exc)

    def release(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError as e:
                logger.error(f"Failed to close lock file descriptor: {e}")
            self.fd = None
        try:
            self.lock_file.unlink()
        except OSError as e:
            logger.error(f"Failed to delete lock file: {e}")


def load_queue(queue_file):
    try:
        queue_file = Path(queue_file)
        if queue_file.exists():
            raw = unprotect_bytes(queue_file.read_bytes()).decode("utf-8")
            return json.loads(raw)
    except Exception as e:
        logger.error(f"Failed to load queue: {e}")
    return []


def save_queue(queue_file, queue):
    try:
        queue_file = Path(queue_file)
        queue_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = queue_file.with_suffix(".tmp")
        raw = json.dumps(queue, ensure_ascii=False).encode("utf-8")
        tmp_file.write_bytes(protect_bytes(raw))
        tmp_file.replace(queue_file)
    except Exception as e:
        logger.error(f"Failed to save queue: {e}")
        raise


def load_job(job_file):
    job_path = Path(job_file)
    data = job_path.read_bytes()
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError:
        raw = unprotect_bytes(data).decode("utf-8")
    job = json.loads(raw)
    if not isinstance(job, dict):
        raise ValueError("Invalid note job")
    return job


def delete_job_file(job_file):
    job_path = Path(job_file)
    try:
        if job_path.exists():
            job_path.unlink()
            logger.debug("Deleted note job file %s", job_path.name)
    except OSError as exc:
        logger.warning("Failed to delete note job file %s: %s: %s", job_path, type(exc).__name__, exc)


def load_pending_jobs(settings_dir, current_job_file):
    settings_dir = Path(settings_dir)
    current_job_file = Path(current_job_file)
    def job_mtime(path):
        try:
            return path.stat().st_mtime
        except OSError:
            return 0

    job_paths = sorted(settings_dir.glob(NOTE_JOB_PATTERN), key=job_mtime)
    if current_job_file not in job_paths:
        job_paths.append(current_job_file)

    jobs = []
    for job_path in job_paths:
        if not job_path.exists():
            continue
        try:
            jobs.append((job_path, load_job(job_path)))
        except Exception as exc:
            logger.error("Failed to load note job %s; leaving file for retry: %s: %s", job_path.name, type(exc).__name__, exc)
    return jobs


def normalize_labels(labels):
    normalized = []
    seen = set()
    for label in labels or []:
        label = str(label or "").strip()
        label_key = label.lower()
        if label and label_key not in seen:
            normalized.append(label)
            seen.add(label_key)
    return normalized


def normalize_email(value):
    return str(value or "").strip().lower()


def job_email_for_queue(job, active_email):
    return normalize_email(job.get("email", "")) or normalize_email(active_email)


def queue_pending_jobs(queue_file, jobs, active_email):
    queued = 0
    for job_path, job in jobs:
        queued_job = {**job, "email": job_email_for_queue(job, active_email)}
        add_job_to_queue(queue_file, queued_job)
        delete_job_file(job_path)
        queued += 1
    return queued


def add_job_to_queue(queue_file, job):
    queue = load_queue(queue_file)
    if job.get("type") == "image":
        queue.append(queue_image_item(job))
    else:
        queue.append(queue_text_item(job))
    save_queue(queue_file, queue)
    logger.info(f"Added to queue, total items: {len(queue)}")


def queue_text_item(item, email=None):
    return {
        'email': normalize_email(email if email is not None else item.get("email", "")),
        'type': "list" if item.get("type") == "list" else "note",
        'text': str(item.get("text", "") or ""),
        'items': [str(entry or "").strip() for entry in item.get("items", []) if str(entry or "").strip()],
        'labels': normalize_labels(item.get("labels", [])),
        'pinned': bool(item.get("pinned", False)),
        'archived': bool(item.get("archived", False)),
        'reminder_at': str(item.get("reminder_at", "") or "").strip(),
        'timestamp': item.get("timestamp", time.time())
    }


def queue_image_item(item, email=None):
    return {
        'email': normalize_email(email if email is not None else item.get("email", "")),
        'type': "image",
        'text': str(item.get("text", "") or ""),
        'labels': normalize_labels(item.get("labels", [])),
        'mime_type': str(item.get("mime_type", "image/png") or "image/png"),
        'png_base64': str(item.get("png_base64", "") or ""),
        'byte_size': int(item.get("byte_size", 0) or 0),
        'width': int(item.get("width", 0) or 0),
        'height': int(item.get("height", 0) or 0),
        'timestamp': item.get("timestamp", time.time())
    }


def next_top_sort_value(keep):
    sorts = []
    for note in keep.all():
        try:
            if getattr(note, "trashed", False) or getattr(note, "archived", False) or getattr(note, "pinned", False):
                continue
            sorts.append(int(note.sort))
        except (TypeError, ValueError, AttributeError) as exc:
            logger.debug("Failed to read note sort value: %s: %s", type(exc).__name__, exc)

    if not sorts:
        return SORT_STEP
    return max(sorts) + SORT_STEP


def parse_reminder_at(value):
    value = str(value or "").strip()
    if not value:
        return None
    return datetime.fromisoformat(value)


def show_notification(title, message, launch_url=""):
    if not NOTIFICATIONS_ENABLED:
        return

    if not USER_WANTS_NOTIFICATIONS:
        logger.info(f"Notifications disabled by user, skipping: {title}")
        return

    try:
        icon_path = plugindir / "keep.png"
        toast = Notification(
            app_id="GoogleKeepFlow",
            title=title,
            msg=message,
            icon=str(icon_path) if icon_path.exists() else None,
            launch=launch_url or ""
        )
        toast.show()
        logger.info(f"Notification shown: {title}")
    except Exception as e:
        logger.error(f"Failed to show notification: {e}")


def success_notification_text(items):
    if len(items) > 1:
        return "Notes created", f"{len(items)} notes were added to Google Keep"

    item = items[0]
    if item.get("type") == "image":
        note_text = str(item.get("text", "") or "")
        preview = note_text[:80] + ("..." if len(note_text) > 80 else "")
        return "Image note created", preview or "Clipboard image was added to Google Keep"
    note_text = str(item.get("text", "") or "")
    preview = note_text[:80] + ("..." if len(note_text) > 80 else "")
    if item.get("type") == "list":
        return "Checklist created", preview or "Checklist was added to Google Keep"
    if item.get("reminder_at"):
        return "Reminder note created", preview or "Note with reminder was added to Google Keep"
    if item.get("pinned"):
        return "Pinned note created", preview or "Pinned note was added to Google Keep"
    if item.get("archived"):
        return "Archived note created", preview or "Archived note was added to Google Keep"
    return "Note created", preview or "Note was added to Google Keep"


def normalize_queue_item(item, email=None):
    if item.get("type") == "image":
        return queue_image_item(item, email=email)
    return queue_text_item(item, email=email)


def upload_keep_image(keep, note, blob, image_item):
    png_base64 = str(image_item.get("png_base64", "") or "")
    if not png_base64:
        raise ValueError("Image payload is empty")

    note_server_id = str(getattr(note, "server_id", "") or "")
    blob_server_id = str(getattr(blob, "server_id", "") or "")
    if not note_server_id or not blob_server_id:
        raise ValueError("Missing server ids for image upload")

    boundary = f"----googlekeepflow{int(time.time() * 1000)}"
    mime_type = str(image_item.get("mime_type", "image/png") or "image/png")
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        "{}\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="media"; filename=""\r\n'
        f"Content-Type: {mime_type}\r\n"
        "Content-Transfer-Encoding: base64\r\n\r\n"
        f"{png_base64}\r\n"
        f"--{boundary}--\r\n"
    ).encode("ascii")
    url = (
        "https://notes-pa.clients6.google.com/upload/notes/v1/media/"
        f"{blob_server_id}?noteId={note_server_id}"
    )
    auth = keep._keep_api.getAuth()
    headers = {
        "Authorization": "OAuth " + auth.getAuthToken(),
        "Content-Type": f"multipart/related; boundary={boundary}",
    }
    response = keep._keep_api._session.request("POST", url, data=body, headers=headers)
    if response.status_code >= 400:
        raise ValueError(f"Image upload failed: HTTP {response.status_code} {response.text[:120]}")
    try:
        return response.json()
    except ValueError:
        return {}


def create_image_note(keep, image_item, sort_value):
    note = keep_node.Note()
    keep.add(note)
    note.sort = sort_value
    text = str(image_item.get("text", "") or "")
    if text:
        note.text = text

    blob = keep_node.Blob(parent_id=note.id)
    image = keep_node.NodeImage()
    image._mimetype = str(image_item.get("mime_type", "image/png") or "image/png")
    image._width = int(image_item.get("width", 0) or 0)
    image._height = int(image_item.get("height", 0) or 0)
    image._byte_size = int(image_item.get("byte_size", 0) or 0)
    image._extraction_status = "unknown"
    blob.blob = image
    blob.sort = 0
    note.append(blob, True)
    for label_name in normalize_labels(image_item.get("labels", [])):
        label = keep.findLabel(label_name, create=True)
        if label is not None:
            note.labels.add(label)

    keep.sync()
    upload_keep_image(keep, note, blob, image_item)
    image._byte_size = int(image_item.get("byte_size", 0) or 0)
    image._width = int(image_item.get("width", 0) or 0)
    image._height = int(image_item.get("height", 0) or 0)
    image._extraction_status = "unknown"
    blob.touch(True)
    keep.sync()
    return note


def pulse(heartbeat):
    if callable(heartbeat):
        heartbeat()


def process_queue(queue_file, active_email, active_master_token, settings_dir=None, device_id=None, heartbeat=None):
    queue = load_queue(queue_file)
    if not queue:
        logger.info("Queue is empty")
        return

    items = []
    items_to_keep = []
    for item in queue:
        item_email = str(item.get('email', '')).strip().lower()
        if item_email == active_email.strip().lower():
            items.append(normalize_queue_item(item, email=item_email))
        else:
            # Keep other accounts queued, but never persist credentials.
            items_to_keep.append(normalize_queue_item(item, email=item_email))

    if not items:
        save_queue(queue_file, items_to_keep)
        logger.info("No queued notes for active account")
        return

    logger.info(f"Processing {len(items)} notes for active account")

    try:
        pulse(heartbeat)
        keep = gkeepapi.Keep()
        keep.authenticate(active_email, active_master_token, sync=True, device_id=device_id)
        pulse(heartbeat)
        next_sort = next_top_sort_value(keep)
        created_notes = []

        for item in items:
            pulse(heartbeat)
            item_type = str(item.get("type", "note") or "note")
            if item_type == "image":
                note = create_image_note(keep, item, next_sort)
                pulse(heartbeat)
                next_sort -= 1
                created_notes.append((item, note, str(item.get("text", "") or "")))
                logger.info(
                    "Prepared image note for sync: bytes=%s width=%s height=%s labels=%s",
                    item.get("byte_size", 0),
                    item.get("width", 0),
                    item.get("height", 0),
                    len(normalize_labels(item.get("labels", []))),
                )
                continue

            text = str(item.get("text", "") or "")
            item_type = "list" if item_type == "list" else "note"
            checklist_items = [str(entry or "").strip() for entry in item.get("items", []) if str(entry or "").strip()]
            labels = normalize_labels(item.get("labels", []))
            if item_type == "list":
                note = keep.createList(title='', items=[(entry, False) for entry in checklist_items])
            else:
                note = keep.createNote(title='', text=text)
            note.sort = next_sort
            next_sort -= 1
            note.pinned = bool(item.get("pinned", False))
            note.archived = bool(item.get("archived", False))
            for label_name in labels:
                label = keep.findLabel(label_name, create=True)
                if label is not None:
                    note.labels.add(label)
            created_notes.append((item, note, text))
            logger.info("Prepared note for sync: type=%s labels=%s", item_type, len(labels))

        pulse(heartbeat)
        keep.sync()
        pulse(heartbeat)
        logger.info(f"Synced {len(items)} notes successfully")
        reminder_failures = 0
        for item, note, note_text in created_notes:
            pulse(heartbeat)
            try:
                if item.get("type") == "image":
                    continue
                reminder_at = parse_reminder_at(item.get("reminder_at"))
                if not reminder_at:
                    continue
                task_id = create_keep_reminder(
                    active_email,
                    active_master_token,
                    keep,
                    note,
                    note_text,
                    reminder_at,
                    logger=logger,
                    device_id=device_id,
                )
                logger.info("Reminder set for note %s with task %s at %s", note.id, task_id, reminder_at.isoformat())
            except (ReminderError, ValueError) as exc:
                reminder_failures += 1
                logger.error("Failed to set reminder for note %s: %s: %s", note.id, type(exc).__name__, exc)
                show_notification("Failed to Set Reminder", f"Note was created, but reminder failed: {str(exc)[:80]}")

        if settings_dir:
            try:
                pulse(heartbeat)
                save_cache(settings_dir, active_email, keep.all(), logger, labels=keep.labels())
                pulse(heartbeat)
                logger.info("Notes cache updated")
            except Exception as exc:
                logger.warning("Failed to update notes cache: %s: %s", type(exc).__name__, exc)

        if not reminder_failures:
            title, message = success_notification_text(items)
            show_notification(title, message)

        if len(items) == 1:
            note = created_notes[0][1] if created_notes else None
            logger.info("Note created: id=%s", getattr(note, "id", ""))
        else:
            note_ids = [str(getattr(note, "id", "") or "") for _, note, _ in created_notes]
            logger.info("Notes created: count=%s ids=%s", len(items), ",".join(note_ids))

    except Exception as e:
        logger.error(f"Failed to process notes: {type(e).__name__}: {e}")

        error_msg = str(e)
        if len(error_msg) > 80:
            error_msg = error_msg[:80] + "..."
        show_notification(
            "Failed to Create Note",
            f"Error: {error_msg}"
        )

        for item in items:
            items_to_keep.append(normalize_queue_item(item, email=active_email.strip().lower()))
        logger.info("Failed notes kept in queue for retry")

    save_queue(queue_file, items_to_keep)
    logger.info(f"Queue updated: {len(items_to_keep)} items remaining")


def main():
    global USER_WANTS_NOTIFICATIONS

    if len(sys.argv) != 4:
        logger.error(f"Invalid arguments count: {len(sys.argv)}")
        sys.exit(1)

    job_file = sys.argv[1]
    show_notifications_str = sys.argv[2]
    settings_dir = Path(sys.argv[3])
    settings_dir.mkdir(parents=True, exist_ok=True)
    queue_file = settings_dir / "cache_note_queue.bin"
    lock_file = settings_dir / "worker.lock"

    USER_WANTS_NOTIFICATIONS = str(show_notifications_str).lower() in ('true', '1', 'yes', 'on')
    logger.info(f"Worker started (notifications: {USER_WANTS_NOTIFICATIONS})")

    # Acquire lock before queue operations to prevent race conditions.
    lock = FileLock(lock_file)
    if not lock.acquire(timeout=60):
        logger.warning("Could not acquire lock after 60 seconds, leaving note job for retry")
        return

    try:
        jobs = load_pending_jobs(settings_dir, job_file)
        if not jobs:
            logger.info("No pending note jobs")
            return

        metadata, _ = load_auth(settings_dir, logger)
        email, master_token = load_worker_auth(settings_dir)
        queue_pending_jobs(queue_file, jobs, email)
        lock.heartbeat()

        time.sleep(0.3)

        process_queue(queue_file, email, master_token, settings_dir, device_id=metadata.get("android_id"), heartbeat=lock.heartbeat)

    finally:
        lock.release()
        logger.info("Worker finished")


if __name__ == "__main__":
    main()



