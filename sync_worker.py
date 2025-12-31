#!/usr/bin/env python
import sys
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import json
import time
import os

plugindir = Path(__file__).parent.resolve()
if str(plugindir) not in sys.path:
    sys.path.insert(0, str(plugindir))
lib_path = plugindir / 'lib'
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

import gkeepapi

QUEUE_FILE = plugindir / "note_queue.json"
LOCK_FILE = plugindir / "worker.lock"
USER_WANTS_NOTIFICATIONS = True

log_handler = RotatingFileHandler(
    plugindir / "worker.log",
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
    def __init__(self, lock_file):
        self.lock_file = Path(lock_file)
        self.fd = None
    
    def acquire(self, timeout=0):
        # OS-level exclusive lock with stale lock detection (60sec timeout)
        start = time.time()
        while True:
            try:
                self.fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode())
                return True
            except FileExistsError:
                try:
                    if time.time() - self.lock_file.stat().st_mtime > 60:
                        logger.warning("Removing stale lock file")
                        self.lock_file.unlink()
                        continue
                except:
                    pass
                
                if timeout == 0 or (time.time() - start) >= timeout:
                    return False
                time.sleep(0.1)
    
    def release(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception as e:
                logger.error(f"Failed to close lock file descriptor: {e}")
            self.fd = None
        try:
            self.lock_file.unlink()
        except Exception as e:
            logger.error(f"Failed to delete lock file: {e}")


def load_queue():
    try:
        if QUEUE_FILE.exists():
            with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load queue: {e}")
    return []


def save_queue(queue):
    try:
        with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(queue, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save queue: {e}")


def add_to_queue(email, master_token, text):
    queue = load_queue()
    queue.append({
        'email': email,
        'master_token': master_token,
        'text': text,
        'timestamp': time.time()
    })
    save_queue(queue)
    logger.info(f"Added to queue, total items: {len(queue)}")


def show_notification(title, message):
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
            icon=str(icon_path) if icon_path.exists() else None
        )
        toast.show()
        logger.info(f"Notification shown: {title}")
    except Exception as e:
        logger.error(f"Failed to show notification: {e}")


def process_queue():
    queue = load_queue()
    if not queue:
        logger.info("Queue is empty")
        return

    # group items by account but keep track of original items
    by_account = {}
    for item in queue:
        key = (item['email'], item['master_token'])
        if key not in by_account:
            by_account[key] = {'texts': [], 'items': []}
        by_account[key]['texts'].append(item['text'])
        by_account[key]['items'].append(item)

    # track items to keep in queue (failed ones)
    items_to_keep = []

    for (email, master_token), data in by_account.items():
        texts = data['texts']
        items = data['items']
        logger.info(f"Processing {len(texts)} notes for {email[:20]}...")

        try:
            keep = gkeepapi.Keep()
            keep.authenticate(email, master_token, sync=False)

            for text in texts:
                keep.createNote(title='', text=text)
                logger.info(f"Created note: {text[:30]}...")

            keep.sync()
            logger.info(f"Synced {len(texts)} notes successfully")

            if len(texts) == 1:
                note_preview = texts[0][:50]
                if len(texts[0]) > 50:
                    note_preview += "..."
                show_notification(
                    "Note Created",
                    f"Successfully added: {note_preview}"
                )
            else:
                show_notification(
                    "Notes Created",
                    f"Successfully added {len(texts)} notes to Google Keep"
                )

        except Exception as e:
            logger.error(f"Failed to process notes: {type(e).__name__}: {e}")

            error_msg = str(e)
            if len(error_msg) > 80:
                error_msg = error_msg[:80] + "..."
            show_notification(
                "Failed to Create Note",
                f"Error: {error_msg}"
            )

            # keep failed items in queue for retry
            items_to_keep.extend(items)
            logger.info(f"Failed notes kept in queue for retry")

    save_queue(items_to_keep)
    logger.info(f"Queue updated: {len(items_to_keep)} items remaining")


def main():
    global USER_WANTS_NOTIFICATIONS

    if len(sys.argv) != 5:
        logger.error(f"Invalid arguments count: {len(sys.argv)}")
        sys.exit(1)

    email = sys.argv[1]
    master_token = sys.argv[2]
    text = sys.argv[3]
    show_notifications_str = sys.argv[4]

    USER_WANTS_NOTIFICATIONS = str(show_notifications_str).lower() in ('true', '1', 'yes', 'on')
    logger.info(f"Worker started for note: {text[:50]}... (notifications: {USER_WANTS_NOTIFICATIONS})")

    # acquire lock before queue operations to prevent race conditions
    lock = FileLock(LOCK_FILE)
    if not lock.acquire(timeout=5):
        logger.warning("Could not acquire lock after 5 seconds, another worker is busy")
        add_to_queue(email, master_token, text)
        return

    try:
        add_to_queue(email, master_token, text)

        time.sleep(0.3)

        process_queue()

    finally:
        lock.release()
        logger.info("Worker finished")


if __name__ == "__main__":
    main()