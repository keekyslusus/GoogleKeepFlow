import unittest
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from googlekeepflow.worker_external_edit import (
    DEBOUNCE_SECONDS,
    cleanup_active_edit_files,
    code_fingerprint,
    code_fingerprint_changed,
    file_launch_url,
    file_signature,
    mark_remote_conflict,
    note_is_deleted_or_trashed,
    process_active_edits,
    remove_watch_state,
    write_watch_state,
)


class Timestamps:
    def __init__(self, trashed=None, deleted=None):
        self.trashed = trashed
        self.deleted = deleted


class Note:
    def __init__(self, trashed=False, timestamps=None):
        self.trashed = trashed
        self.timestamps = timestamps


class ExternalEditTrashStateTests(unittest.TestCase):
    def test_detects_note_trashed_property(self):
        self.assertTrue(note_is_deleted_or_trashed(Note(trashed=True)))

    def test_detects_trashed_timestamp(self):
        note = Note(timestamps=Timestamps(trashed=datetime(2026, 1, 1, tzinfo=timezone.utc)))

        self.assertTrue(note_is_deleted_or_trashed(note))

    def test_detects_deleted_timestamp(self):
        note = Note(timestamps=Timestamps(deleted=datetime(2026, 1, 1, tzinfo=timezone.utc)))

        self.assertTrue(note_is_deleted_or_trashed(note))

    def test_epoch_timestamp_is_not_deleted_or_trashed(self):
        epoch = datetime.fromtimestamp(0, timezone.utc)
        note = Note(timestamps=Timestamps(trashed=epoch, deleted=epoch))

        self.assertFalse(note_is_deleted_or_trashed(note))


class ExternalEditConflictTests(unittest.TestCase):
    def test_file_launch_url_uses_file_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.conflict.txt"
            path.write_text("local edit", encoding="utf-8")

            self.assertTrue(file_launch_url(path).startswith("file:///"))

    def test_remote_conflict_toast_launches_remote_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            edit_file = Path(tmp) / "note.txt"
            edit_file.write_text("cached", encoding="utf-8")
            state = {
                "job": {"show_notifications": True},
                "path": edit_file,
            }

            with patch("googlekeepflow.worker_external_edit.show_notification") as notify:
                mark_remote_conflict(state, "Remote changed.", remote_text="remote")

            remote_path = Path(tmp) / "note.remote.txt"
            self.assertEqual(remote_path.read_text(encoding="utf-8-sig"), "remote")
            self.assertEqual(notify.call_args.kwargs["launch_url"], file_launch_url(remote_path))
            self.assertIn("Click to open the remote copy.", notify.call_args.args[1])
            self.assertNotIn(remote_path.name, notify.call_args.args[1])

    def test_remote_conflict_saves_local_edit_as_conflict_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            edit_file = Path(tmp) / "note.txt"
            edit_file.write_text("cached", encoding="utf-8")
            initial_signature = file_signature(edit_file)
            edit_file.write_text("local edit", encoding="utf-8")
            changed_signature = file_signature(edit_file)
            active = {
                "note": {
                    "job": {"show_notifications": True, "note_id": "note-1"},
                    "path": edit_file,
                    "last_signature": initial_signature,
                    "last_synced_text": "cached",
                    "pending_signature": changed_signature,
                    "pending_since": time.time() - DEBOUNCE_SECONDS - 1,
                    "remote_conflict": True,
                }
            }

            with patch("googlekeepflow.worker_external_edit.show_notification") as notify:
                process_active_edits(tmp, active)

            conflict_file = Path(tmp) / "note.conflict.txt"
            self.assertFalse(edit_file.exists())
            self.assertEqual(conflict_file.read_text(encoding="utf-8-sig"), "local edit")
            self.assertEqual(notify.call_args.kwargs["launch_url"], file_launch_url(conflict_file))
            self.assertIn("Click to open your saved copy.", notify.call_args.args[1])
            self.assertNotIn(conflict_file.name, notify.call_args.args[1])
            self.assertEqual(active, {})


class ExternalEditWatcherUpdateTests(unittest.TestCase):
    def test_code_fingerprint_detects_watched_file_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "googlekeepflow").mkdir()
            (root / "plugin.json").write_text("{}", encoding="utf-8")
            (root / "googlekeepflow" / "worker_external_edit.py").write_text("one", encoding="utf-8")
            (root / "googlekeepflow" / "worker_common.py").write_text("one", encoding="utf-8")
            (root / "googlekeepflow" / "keep_cache.py").write_text("one", encoding="utf-8")
            fingerprint = code_fingerprint(root)

            (root / "googlekeepflow" / "worker_external_edit.py").write_text("two", encoding="utf-8")

            self.assertTrue(code_fingerprint_changed(fingerprint, root))

    def test_watch_state_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            edit_dir = Path(tmp)
            fingerprint = {"plugin.json": {"mtime_ns": 1, "size": 2}}

            state_path = write_watch_state(edit_dir, fingerprint, pid=123)

            self.assertTrue(state_path.exists())
            self.assertIn('"pid": 123', state_path.read_text(encoding="utf-8"))
            remove_watch_state(edit_dir)
            self.assertFalse(state_path.exists())

    def test_update_cleanup_policy_leaves_active_edit_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            edit_file = Path(tmp) / "note.txt"
            edit_file.write_text("draft", encoding="utf-8")
            active = {"note": {"path": edit_file}}

            cleanup_active_edit_files(active, keep_files=True)

            self.assertTrue(edit_file.exists())


if __name__ == "__main__":
    unittest.main()
