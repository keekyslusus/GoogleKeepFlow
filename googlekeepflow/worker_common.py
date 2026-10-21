import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from googlekeepflow.keep_cache import save_cache
from googlekeepflow.keep_http import new_keep_client
from googlekeepflow.worker_auth import load_worker_auth


try:
    from winotify import Notification

    NOTIFICATIONS_ENABLED = True
except ImportError:
    Notification = None
    NOTIFICATIONS_ENABLED = False


SORT_STEP = 1048576


_LOG_HANDLERS = {}


def worker_log_handler(plugin_dir):
    # One handler per log file per process, so loggers of imported workers share rollover.
    log_path = str(Path(plugin_dir) / "log_worker.log")
    handler = _LOG_HANDLERS.get(log_path)
    if handler is None:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=1 * 1024 * 1024,
            backupCount=1,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        _LOG_HANDLERS[log_path] = handler
    return handler


def setup_worker_logger(name, plugin_dir):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    logger.addHandler(worker_log_handler(plugin_dir))
    if not NOTIFICATIONS_ENABLED:
        logger.warning("winotify not installed, notifications disabled")
    return logger


def show_notification(title, message, plugin_dir, logger, launch_url="", enabled=True):
    if not NOTIFICATIONS_ENABLED or not enabled:
        return

    try:
        icon_path = Path(plugin_dir) / "keep.png"
        toast = Notification(
            app_id="GoogleKeepFlow",
            title=title,
            msg=message,
            icon=str(icon_path) if icon_path.exists() else None,
            launch=launch_url or "",
        )
        toast.show()
        logger.info("Notification shown: %s", title)
    except Exception as exc:
        logger.error("Failed to show notification: %s", exc)


def note_preview(note):
    title = str(getattr(note, "title", "") or "").strip()
    text = str(getattr(note, "text", "") or "").strip()
    preview = title or text or "Google Keep note"
    preview = preview.replace("\n", " ")
    return preview[:80] + ("..." if len(preview) > 80 else "")


def next_top_sort_value(keep, logger=None):
    # gkeepapi gives new notes a random sort value; Keep orders unpinned notes by it, highest first.
    sorts = []
    for note in keep.all():
        try:
            if getattr(note, "trashed", False) or getattr(note, "archived", False) or getattr(note, "pinned", False):
                continue
            sorts.append(int(note.sort))
        except (TypeError, ValueError, AttributeError) as exc:
            if logger:
                logger.debug("Failed to read note sort value: %s: %s", type(exc).__name__, exc)

    if not sorts:
        return SORT_STEP
    return max(sorts) + SORT_STEP


def find_note(keep, note_id):
    for note in keep.all():
        if str(getattr(note, "id", "")) == str(note_id):
            return note
    return None


def load_keep(settings_dir, requested_email, on_response=None):
    email, master_token = load_worker_auth(settings_dir, requested_email)
    keep = new_keep_client(on_response)
    keep.authenticate(email, master_token, sync=True)
    return email, keep


def save_notes_cache(settings_dir, email, keep, logger):
    if settings_dir:
        try:
            save_cache(settings_dir, email, keep.all(), logger, labels=keep.labels())
            logger.info("Notes cache updated")
        except Exception as exc:
            logger.warning("Failed to update notes cache: %s: %s", type(exc).__name__, exc)


def short_error(exc, limit=80):
    message = str(exc)
    return message[:limit] + ("..." if len(message) > limit else "")
