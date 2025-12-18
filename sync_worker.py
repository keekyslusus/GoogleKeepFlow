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


class FileLock:
    def __init__(self, lock_file):
        self.lock_file = Path(lock_file)
        self.fd = None
    
    def acquire(self, timeout=0):
        # Attempts to acquire an exclusive lock using OS-level file creation
        # prevents race conditions between multiple worker instances
        # checks for and removes stale locks if the previous owner crashed
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
            except:
                pass
            self.fd = None
        try:
            self.lock_file.unlink()
        except:
            pass


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


def process_queue():
    queue = load_queue()
    if not queue:
        logger.info("Queue is empty")
        return
    
    by_account = {}
    for item in queue:
        key = (item['email'], item['master_token'])
        if key not in by_account:
            by_account[key] = []
        by_account[key].append(item['text'])
    
    save_queue([])
    
    for (email, master_token), texts in by_account.items():
        logger.info(f"Processing {len(texts)} notes for {email[:20]}...")
        
        try:
            keep = gkeepapi.Keep()
            keep.authenticate(email, master_token, sync=False)
            
            for text in texts:
                keep.createNote(title='', text=text)
                logger.info(f"Created note: {text[:30]}...")
            
            keep.sync()
            logger.info(f"Synced {len(texts)} notes successfully")
            
        except Exception as e:
            logger.error(f"Failed to process notes: {type(e).__name__}: {e}")
            # if sync fails, return notes to the queue to be retried by the next worker execution
            failed_queue = load_queue()
            for text in texts:
                failed_queue.append({
                    'email': email,
                    'master_token': master_token,
                    'text': text,
                    'timestamp': time.time()
                })
            save_queue(failed_queue)
            logger.info("Failed notes returned to queue")


def main():
    if len(sys.argv) != 4:
        logger.error(f"Invalid arguments count: {len(sys.argv)}")
        sys.exit(1)
    
    email = sys.argv[1]
    master_token = sys.argv[2]
    text = sys.argv[3]
    
    logger.info(f"Worker started for note: {text[:50]}...")
    
    add_to_queue(email, master_token, text)
    
    lock = FileLock(LOCK_FILE)
    if not lock.acquire(timeout=0):
        logger.info("Another worker is running, exiting")
        return
    
    try:
        time.sleep(0.3)
        
        process_queue()
        
    finally:
        lock.release()
        logger.info("Worker finished")


if __name__ == "__main__":
    main()