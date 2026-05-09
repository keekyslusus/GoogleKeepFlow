import unittest
from pathlib import Path
from unittest.mock import patch

from googlekeepflow.worker_sync import job_email_for_queue, queue_pending_jobs


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


if __name__ == "__main__":
    unittest.main()
