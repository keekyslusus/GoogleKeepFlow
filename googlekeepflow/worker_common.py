import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import gkeepapi

from googlekeepflow.keep_cache import save_cache
from googlekeepflow.worker_auth import load_worker_auth


try:
    from winotify import Notification

    NOTIFICATIONS_ENABLED = True
except ImportError:
    Notification = None
    NOTIFICATIONS_ENABLED = False


def setup_worker_logger(name, plugin_dir):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    log_handler = RotatingFileHandler(
        Path(plugin_dir) / "log_worker.log",
        maxBytes=1 * 1024 * 1024,
        backupCount=1,
        encoding="utf-8",
    )
    log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(log_handler)
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


def find_note(keep, note_id):
    for note in keep.all():
        if str(getattr(note, "id", "")) == str(note_id):
            return note
    return None


def load_keep(settings_dir, requested_email):
    email, master_token = load_worker_auth(settings_dir, requested_email)
    keep = gkeepapi.Keep()
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
