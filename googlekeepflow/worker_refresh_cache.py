import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time
from pathlib import Path

package_dir = Path(__file__).parent.resolve()
plugindir = package_dir.parent
if str(plugindir) not in sys.path:
    sys.path.insert(0, str(plugindir))
lib_path = plugindir / "lib"
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

from googlekeepflow.keep_cache import save_cache
from googlekeepflow.keep_notes import create_keep_client, sync_keep_client
from googlekeepflow.worker_auth import load_worker_auth


log_handler = RotatingFileHandler(
    plugindir / "log_worker.log",
    maxBytes=1 * 1024 * 1024,
    backupCount=1,
    encoding="utf-8",
)
log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger = logging.getLogger("refresh_cache_worker")
logger.addHandler(log_handler)
logger.setLevel(logging.INFO)


class FileLock:
    def __init__(self, lock_file):
        self.lock_file = Path(lock_file)
        self.fd = None

    def acquire(self):
        try:
            if self.lock_file.exists() and time.time() - self.lock_file.stat().st_mtime > 60:
                self.lock_file.unlink()
        except OSError as exc:
            logger.debug("Failed to inspect stale cache lock %s: %s: %s", self.lock_file, type(exc).__name__, exc)

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
                logger.warning("Failed to close cache lock descriptor: %s: %s", type(exc).__name__, exc)
            self.fd = None
        try:
            self.lock_file.unlink()
        except OSError as exc:
            logger.warning("Failed to delete cache lock %s: %s: %s", self.lock_file, type(exc).__name__, exc)


def main():
    if len(sys.argv) != 3:
        logger.error("Invalid arguments count: %s", len(sys.argv))
        sys.exit(1)

    requested_email = sys.argv[1]
    settings_dir = Path(sys.argv[2])
    settings_dir.mkdir(parents=True, exist_ok=True)

    lock = FileLock(settings_dir / "cache_notes.lock")
    if not lock.acquire():
        logger.info("Cache refresh already running")
        return

    try:
        email, master_token = load_worker_auth(settings_dir, requested_email)
        logger.info("Refreshing notes cache")
        keep = create_keep_client(email, master_token, logger)
        sync_keep_client(keep, logger)
        save_cache(settings_dir, email, keep.all(), logger, labels=keep.labels())
        logger.info("Notes cache refreshed")
    except Exception as exc:
        logger.error("Failed to refresh notes cache: %s: %s", type(exc).__name__, exc)
    finally:
        lock.release()


if __name__ == "__main__":
    main()



