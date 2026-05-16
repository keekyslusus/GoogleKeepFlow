import unittest
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from googlekeepflow.worker_sync import FileLock, job_email_for_queue, load_queue, queue_image_item, queue_pending_jobs, save_queue


class WorkerSyncMultiAccountTests(unittest.TestCase):
    def test_job_email_for_queue_preserves_existing_email(self):
        job = {"email": "Other@Example.com"}

        self.assertEqual(job_email_for_queue(job, "active@example.com"), "other@example.com")

    def test_job_email_for_queue_uses_active_email_when_missing(self):
        job = {"text": "hello"}

        self.assertEqual(job_email_for_queue(job, "Active@Example.com"), "active@example.com")

    def test_queue_pending_jobs_does_not_rewrite_other_account_jobs(self):
        jobs = [
            (Path("one.bin"), {"email": "other@example.com", "text": "old"}),
            (Path("two.bin"), {"email": "", "text": "new"}),
        ]
        queued = []
        deleted = []

        with patch("googlekeepflow.worker_sync.add_job_to_queue", lambda queue_file, job: queued.append(job)):
            with patch("googlekeepflow.worker_sync.delete_job_file", lambda path: deleted.append(path)):
                count = queue_pending_jobs(Path("queue.bin"), jobs, "active@example.com")

        self.assertEqual(count, 2)
        self.assertEqual([job["email"] for job in queued], ["other@example.com", "active@example.com"])
        self.assertEqual(deleted, [Path("one.bin"), Path("two.bin")])

    def test_queue_pending_jobs_keeps_job_when_queue_save_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_path = Path(tmp) / "one.bin"
            queue_path = Path(tmp) / "queue.bin"
            job_path.write_text("pending", encoding="utf-8")
            jobs = [(job_path, {"email": "", "text": "new"})]

            with patch("googlekeepflow.worker_sync.protect_bytes", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    queue_pending_jobs(queue_path, jobs, "active@example.com")

            self.assertTrue(job_path.exists())

    def test_save_queue_keeps_existing_queue_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.bin"
            original_queue = [{"email": "active@example.com", "text": "old"}]
            new_queue = [{"email": "active@example.com", "text": "new"}]
            save_queue(queue_path, original_queue)

            with patch("pathlib.Path.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    save_queue(queue_path, new_queue)

            self.assertEqual(load_queue(queue_path), original_queue)

    def test_queue_image_item_preserves_image_payload(self):
        item = {
            "email": "User@Example.com",
            "type": "image",
            "text": "caption",
            "labels": ["photos"],
            "mime_type": "image/png",
            "png_base64": "abc",
            "byte_size": 3,
            "width": 10,
            "height": 20,
            "timestamp": 123,
        }

        queued = queue_image_item(item)

        self.assertEqual(queued["email"], "user@example.com")
        self.assertEqual(queued["type"], "image")
        self.assertEqual(queued["text"], "caption")
        self.assertEqual(queued["labels"], ["photos"])
        self.assertEqual(queued["png_base64"], "abc")
        self.assertEqual(queued["width"], 10)
        self.assertEqual(queued["height"], 20)

    def test_file_lock_keeps_fresh_lock_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "worker.lock"
            lock_path.write_text("other", encoding="utf-8")

            lock = FileLock(lock_path, stale_seconds=600)

            self.assertFalse(lock.acquire(timeout=0))
            self.assertTrue(lock_path.exists())

    def test_file_lock_replaces_stale_lock_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "worker.lock"
            lock_path.write_text("old", encoding="utf-8")
            old_time = time.time() - 700
            os.utime(lock_path, (old_time, old_time))
            lock = FileLock(lock_path, stale_seconds=600)

            self.assertTrue(lock.acquire(timeout=0))

            lock.release()
            self.assertFalse(lock_path.exists())

    def test_file_lock_heartbeat_refreshes_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "worker.lock"
            lock = FileLock(lock_path)
            self.assertTrue(lock.acquire(timeout=0))
            old_time = time.time() - 700
            os.utime(lock_path, (old_time, old_time))

            lock.heartbeat()

            self.assertGreater(lock_path.stat().st_mtime, old_time)
            lock.release()


if __name__ == "__main__":
    unittest.main()
