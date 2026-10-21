import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from gkeepapi.exception import LoginException

from googlekeepflow.file_identity import file_identity, is_recycle_bin_path
from googlekeepflow.keep_file_links import (
    replace_with_retry,
    link_status_text,
    DIRECTION_PULL,
    DIRECTION_PUSH,
    STATUS_CONFLICT,
    STATUS_FILE_MISSING,
    STATUS_NOTE_MISSING,
    STATUS_SYNCED,
    backups_dir,
    decode_file_bytes,
    encode_file_text,
    find_link_by_path,
    load_registry,
    path_from_text,
    registry_path,
    resolve_link_source,
    save_registry,
)
from googlekeepflow.keep_http import KeepRateLimitedError
from googlekeepflow.worker_linked_files import (
    RATE_LIMIT_BACKOFF_MIN_SECONDS,
    STALE_SYNC_NOTIFY_SECONDS,
    ACTION_ADOPT,
    ACTION_CONFLICT,
    ACTION_NONE,
    ACTION_PULL,
    ACTION_PUSH,
    LinkedFilesWorker,
    reconcile_action,
)


class FakeNote:
    def __init__(self, note_id, text="", title=""):
        self.id = note_id
        self.text = text
        self.title = title
        self.type = "NOTE"
        self.sort = 5
        self.pinned = False
        self.archived = False
        self.trashed = False
        self.timestamps = None


class FakeKeep:
    def __init__(self, notes=None):
        self.notes = list(notes or [])
        self.sync_count = 0

    def all(self):
        return self.notes

    def sync(self):
        self.sync_count += 1

    def createNote(self, title=None, text=None):
        note = FakeNote(f"new-{len(self.notes)}", text or "", title or "")
        note.sort = -123
        self.notes.append(note)
        return note


class ReconcileActionTests(unittest.TestCase):
    def test_decisions(self):
        self.assertEqual(reconcile_action("a", "a", "a"), ACTION_NONE)
        self.assertEqual(reconcile_action("a", "b", "a"), ACTION_PUSH)
        self.assertEqual(reconcile_action("a", "a", "b"), ACTION_PULL)
        self.assertEqual(reconcile_action("a", "b", "b"), ACTION_ADOPT)
        self.assertEqual(reconcile_action("a", "b", "c"), ACTION_CONFLICT)


class FileFormatTests(unittest.TestCase):
    def test_round_trip_keeps_crlf_and_bom(self):
        data = b"\xef\xbb\xbfone\r\ntwo\r\n"
        text, file_format = decode_file_bytes(data)

        self.assertEqual(text, "one\ntwo\n")
        self.assertEqual(encode_file_text(text, file_format), data)

    def test_round_trip_keeps_lf(self):
        text, file_format = decode_file_bytes(b"one\ntwo")

        self.assertEqual(encode_file_text("x\ny", file_format), b"x\ny")

    def test_file_without_newlines_defaults_to_crlf(self):
        _, file_format = decode_file_bytes(b"one")

        self.assertEqual(encode_file_text("x\ny", file_format), b"x\r\ny")


class LinkSourceTests(unittest.TestCase):
    def test_quoted_path_from_explorer_copy_as_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "road map.md"
            path.write_text("x", encoding="utf-8")

            self.assertEqual(path_from_text(f'"{path}"'), path)

    def test_typed_path_wins_over_clipboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text("x", encoding="utf-8")

            self.assertEqual(resolve_link_source(str(path), lambda: Path("other.md")), (path, ""))

    def test_clipboard_file_keeps_query_as_search_text(self):
        clipboard_path = Path("C:/copied/roadmap.md")

        self.assertEqual(resolve_link_source("project", lambda: clipboard_path), (clipboard_path, "project"))


class RegistryTests(unittest.TestCase):
    def test_round_trip_and_empty_registry_removes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = load_registry(tmp)
            registry["links"]["note-1"] = {"note_id": "note-1", "path": str(Path(tmp) / "a.md")}
            save_registry(tmp, registry)

            loaded = load_registry(tmp)
            self.assertEqual(find_link_by_path(loaded, Path(tmp) / "a.md")["note_id"], "note-1")

            loaded["links"].clear()
            save_registry(tmp, loaded)
            self.assertFalse(registry_path(tmp).exists())


class LinkedFilesWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_dir = Path(self.tmp.name) / "settings"
        self.file_path = Path(self.tmp.name) / "roadmap.md"
        self.keep = FakeKeep()
        patches = [
            patch("googlekeepflow.worker_linked_files.load_keep", side_effect=lambda settings_dir, email, on_response=None: ("user@example.com", self.keep)),
            patch("googlekeepflow.worker_linked_files.save_notes_cache"),
            patch("googlekeepflow.worker_linked_files.show_notification"),
            patch("googlekeepflow.worker_linked_files.MISSING_RECHECK_SECONDS", 0),
            patch("googlekeepflow.worker_linked_files.RELOCATE_GRACE_SECONDS", 0),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.worker = LinkedFilesWorker(self.settings_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def link(self, file_text="plan", remote_text="plan", status=STATUS_SYNCED, note_id="note-1", path=None):
        path = path or self.file_path
        path.write_bytes(file_text.encode("utf-8"))
        note = FakeNote(note_id, remote_text)
        self.keep.notes.append(note)
        self.worker.links[note_id] = {
            "note_id": note_id,
            "email": "user@example.com",
            "path": str(path),
            "file_id": file_identity(path),
            "format": {"bom": False, "newline": "\n"},
            "last_synced_text": "plan",
            "status": status,
            "message": "",
        }
        return note

    def notifications(self):
        from googlekeepflow import worker_linked_files
        return [call.args[0] for call in worker_linked_files.show_notification.call_args_list]

    def test_local_change_is_pushed(self):
        note = self.link(file_text="plan\nv2")

        self.worker.reconcile(["note-1"])

        self.assertEqual(note.text, "plan\nv2")
        self.assertEqual(self.worker.links["note-1"]["last_synced_text"], "plan\nv2")
        self.assertTrue(registry_path(self.settings_dir).exists())

    def test_remote_change_is_pulled_with_file_newlines(self):
        self.link(file_text="plan\n", remote_text="plan\nfrom phone")
        self.worker.links["note-1"]["last_synced_text"] = "plan\n"

        self.worker.reconcile(["note-1"])

        self.assertEqual(self.file_path.read_bytes(), b"plan\nfrom phone")
        self.assertEqual(self.worker.links["note-1"]["last_synced_text"], "plan\nfrom phone")

    def test_both_changed_pauses_with_conflict_and_backs_up_remote(self):
        note = self.link(file_text="local", remote_text="remote")

        self.worker.reconcile(["note-1"])

        self.assertEqual(self.worker.links["note-1"]["status"], STATUS_CONFLICT)
        self.assertEqual(note.text, "remote")
        self.assertEqual(self.file_path.read_text(encoding="utf-8"), "local")
        backups = list(backups_dir(self.settings_dir).iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "remote")

        # Still paused while the versions differ.
        self.worker.reconcile(["note-1"])
        self.assertEqual(note.text, "remote")
        self.assertEqual(len(list(backups_dir(self.settings_dir).iterdir())), 1)

    def test_conflict_clears_when_versions_match_again(self):
        self.link(file_text="merged", remote_text="merged", status=STATUS_CONFLICT)

        self.worker.reconcile(["note-1"])

        self.assertEqual(self.worker.links["note-1"]["status"], STATUS_SYNCED)
        self.assertEqual(self.worker.links["note-1"]["last_synced_text"], "merged")

    def test_missing_file_and_note_pause_sync(self):
        note = self.link()
        self.file_path.unlink()

        self.worker.reconcile(["note-1"])
        self.assertEqual(self.worker.links["note-1"]["status"], STATUS_FILE_MISSING)

        self.file_path.write_text("plan", encoding="utf-8")
        note.trashed = True
        self.worker.reconcile(["note-1"])
        self.assertEqual(self.worker.links["note-1"]["status"], STATUS_NOTE_MISSING)

        note.trashed = False
        self.worker.reconcile(["note-1"])
        self.assertEqual(self.worker.links["note-1"]["status"], STATUS_SYNCED)

    def test_link_job_creates_note_titled_after_file_at_the_top(self):
        self.file_path.write_text("roadmap text", encoding="utf-8")
        self.keep.notes.append(FakeNote("old", "older note"))
        pinned = FakeNote("pinned", "pinned note")
        pinned.pinned = True
        pinned.sort = 10 ** 9
        self.keep.notes.append(pinned)

        self.worker.handle_job({"action": "link", "path": str(self.file_path), "email": "user@example.com"})

        note = self.keep.notes[-1]
        self.assertEqual((note.title, note.text), ("roadmap.md", "roadmap text"))
        self.assertGreater(note.sort, 5)
        self.assertLess(note.sort, pinned.sort)
        self.assertEqual(self.worker.links[note.id]["last_synced_text"], "roadmap text")

    def test_link_job_rejects_already_linked_file(self):
        self.link()

        with self.assertRaises(ValueError):
            self.worker.handle_job({"action": "link", "path": str(self.file_path), "email": "user@example.com"})

    def test_link_to_existing_note_with_pull_backs_up_file(self):
        self.file_path.write_text("old file", encoding="utf-8")
        self.keep.notes.append(FakeNote("note-9", "note text"))

        self.worker.handle_job({
            "action": "link",
            "path": str(self.file_path),
            "note_id": "note-9",
            "direction": DIRECTION_PULL,
            "email": "user@example.com",
        })

        self.assertEqual(self.file_path.read_text(encoding="utf-8"), "note text")
        backups = list(backups_dir(self.settings_dir).iterdir())
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "old file")

    def test_resolve_conflict_with_local_version(self):
        note = self.link(file_text="local", remote_text="remote", status=STATUS_CONFLICT)

        self.worker.handle_job({"action": "resolve", "note_id": "note-1", "direction": DIRECTION_PUSH})

        self.assertEqual(note.text, "local")
        self.assertEqual(self.worker.links["note-1"]["status"], STATUS_SYNCED)
        self.assertEqual(self.worker.links["note-1"]["last_synced_text"], "local")

    def test_unlink_keeps_file(self):
        self.link()

        self.worker.handle_job({"action": "unlink", "note_id": "note-1"})

        self.assertEqual(self.worker.links, {})
        self.assertTrue(self.file_path.exists())

    def test_watched_path_matches_linked_file_and_jobs(self):
        self.link()
        self.worker.reschedule_watches()

        self.assertTrue(self.worker.is_watched_path(str(self.file_path)))
        self.assertTrue(self.worker.is_watched_path(str(self.worker.job_dir / "link_job_1.bin")))
        self.assertFalse(self.worker.is_watched_path(str(self.file_path.with_name("other.md"))))


    def test_missing_file_waits_for_grace_before_pausing(self):
        self.link()
        self.file_path.unlink()

        with patch("googlekeepflow.worker_linked_files.RELOCATE_GRACE_SECONDS", 60):
            self.worker.reconcile(["note-1"])

        self.assertEqual(self.worker.links["note-1"]["status"], STATUS_SYNCED)

    @unittest.skipUnless(sys.platform == "win32", "file ids are resolved through the Windows API")
    def test_renamed_and_moved_file_keeps_syncing(self):
        self.link()
        renamed = self.file_path.with_name("renamed.md")
        self.file_path.rename(renamed)

        self.worker.scan_local(time.time())

        self.assertEqual(os.path.normcase(self.worker.links["note-1"]["path"]), os.path.normcase(str(renamed)))
        self.assertIn("Synced file moved", self.notifications())

        subdir = Path(self.tmp.name) / "docs" / "deep"
        subdir.mkdir(parents=True)
        moved = subdir / "renamed.md"
        renamed.rename(moved)
        with open(moved, "ab") as handle:
            handle.write(b"\nafter move")

        self.worker.reconcile(["note-1"])

        self.assertEqual(os.path.normcase(self.worker.links["note-1"]["path"]), os.path.normcase(str(moved)))
        self.assertEqual(self.keep.notes[0].text, "plan\nafter move")

    def test_deleted_file_is_not_relocated(self):
        self.link()
        self.file_path.unlink()

        self.worker.reconcile(["note-1"])

        self.assertEqual(self.worker.links["note-1"]["status"], STATUS_FILE_MISSING)

    def test_file_id_refreshes_after_safe_write_replace(self):
        self.link()
        old_id = self.worker.links["note-1"]["file_id"]
        self.worker.scan_local(time.time())
        tmp_path = self.file_path.with_name("roadmap.md.tmp")
        tmp_path.write_text("plan v2", encoding="utf-8")
        os.replace(tmp_path, self.file_path)

        self.worker.scan_local(time.time())

        new_id = self.worker.links["note-1"]["file_id"]
        self.assertEqual(new_id, file_identity(self.file_path))
        if sys.platform == "win32":
            self.assertNotEqual(new_id, old_id)

    def test_read_only_file_pauses_pull_without_crashing(self):
        self.link(file_text="plan", remote_text="from phone")
        os.chmod(self.file_path, stat.S_IREAD)

        self.worker.reconcile(["note-1"])

        self.assertEqual(self.worker.links["note-1"]["status"], "error")
        self.assertIn("read-only", self.worker.links["note-1"]["message"])

        os.chmod(self.file_path, stat.S_IWRITE | stat.S_IREAD)
        self.worker.reconcile(["note-1"])
        self.assertEqual(self.file_path.read_text(encoding="utf-8"), "from phone")
        self.assertEqual(self.worker.links["note-1"]["status"], STATUS_SYNCED)

    def test_failure_in_one_link_does_not_block_others(self):
        self.link(file_text="plan v2")
        other_path = Path(self.tmp.name) / "other.md"
        other_note = self.link(file_text="other v2", note_id="note-2", path=other_path)
        original = self.worker.reconcile_entry

        def flaky(keep, entry, pushed):
            if entry["note_id"] == "note-1":
                raise RuntimeError("boom")
            return original(keep, entry, pushed)

        with patch.object(self.worker, "reconcile_entry", flaky):
            self.worker.reconcile(["note-1", "note-2"])

        self.assertEqual(other_note.text, "other v2")

    def test_offline_marks_links_not_synced_until_connection_returns(self):
        self.link(file_text="plan v2")
        self.worker.clients["user@example.com"] = ("user@example.com", self.keep)

        with patch.object(self.keep, "sync", side_effect=ConnectionError("down")):
            self.worker.reconcile(["note-1"])

        entry = self.worker.links["note-1"]
        self.assertEqual(entry["sync_error"], "no connection to Google Keep")
        self.assertEqual(link_status_text(entry), "Not synced: no connection to Google Keep")
        self.assertNotIn("File sync can't reach your account", self.notifications())

        self.worker.reconcile(["note-1"])

        self.assertNotIn("sync_error", self.worker.links["note-1"])
        self.assertEqual(self.keep.notes[0].text, "plan v2")

    def test_auth_errors_notify_once(self):
        self.link()

        with patch("googlekeepflow.worker_linked_files.load_keep", side_effect=ValueError("Stored auth email does not match worker email")):
            self.worker.reconcile(["note-1"])
            self.worker.reconcile(["note-1"])

        self.assertEqual(self.worker.links["note-1"]["sync_error"], "signed in to a different Google account than user@example.com")
        self.assertEqual(self.notifications().count("File sync can't reach your account"), 1)

        with patch("googlekeepflow.worker_linked_files.load_keep", side_effect=LoginException("expired")):
            self.worker.clients.clear()
            self.worker.reconcile(["note-1"])
        self.assertEqual(self.worker.links["note-1"]["sync_error"], "Google sign-in expired")

    def test_pushes_are_throttled(self):
        now = time.time()
        self.worker.pending["note-1"] = now - 10
        self.worker.last_push["note-1"] = now - 1

        self.assertEqual(self.worker.due_pending(now), [])
        self.assertEqual(self.worker.due_pending(now + 4), ["note-1"])

    def test_emptied_file_backs_up_note_before_clearing_it(self):
        note = self.link(file_text="")

        self.worker.reconcile(["note-1"])

        self.assertEqual(note.text, "")
        backups = list(backups_dir(self.settings_dir).iterdir())
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "plan")
        self.assertIn("Synced file is empty", self.notifications())

    def test_run_survives_a_failing_pass(self):
        calls = []

        def step():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return False

        with patch.object(self.worker, "step", step), patch("googlekeepflow.worker_linked_files.LOOP_ERROR_BACKOFF_SECONDS", 0):
            self.worker.run()

        self.assertEqual(len(calls), 2)

    def test_restored_file_announces_resume(self):
        self.link()
        self.file_path.unlink()
        self.worker.reconcile(["note-1"])

        self.file_path.write_text("plan", encoding="utf-8")
        self.worker.reconcile(["note-1"])

        self.assertEqual(self.worker.links["note-1"]["status"], STATUS_SYNCED)
        self.assertEqual(self.notifications(), ["File sync paused", "File sync resumed"])

        self.worker.reconcile(["note-1"])
        self.assertEqual(self.notifications().count("File sync resumed"), 1)

    def test_restored_note_and_writable_file_announce_resume(self):
        note = self.link(file_text="plan", remote_text="from phone")
        note.trashed = True
        self.worker.reconcile(["note-1"])
        note.trashed = False
        self.worker.reconcile(["note-1"])

        self.assertEqual(self.notifications(), ["File sync paused", "File sync resumed"])
        from googlekeepflow import worker_linked_files
        self.assertIn("The file was updated", worker_linked_files.show_notification.call_args.args[1])
        self.assertEqual(self.file_path.read_text(encoding="utf-8"), "from phone")

    def test_manual_conflict_resolution_notifies_once(self):
        self.link(file_text="local", remote_text="remote", status=STATUS_CONFLICT)

        self.worker.handle_job({"action": "resolve", "note_id": "note-1", "direction": DIRECTION_PUSH})

        self.assertEqual(self.notifications(), ["File sync resumed"])

    @unittest.skipUnless(sys.platform == "win32", "file ids are resolved through the Windows API")
    def test_file_found_after_pause_reports_move_only(self):
        self.link()
        self.worker.links["note-1"]["status"] = STATUS_FILE_MISSING
        moved = self.file_path.with_name("moved.md")
        self.file_path.rename(moved)

        self.worker.reconcile(["note-1"])

        self.assertEqual(self.worker.links["note-1"]["status"], STATUS_SYNCED)
        self.assertEqual(self.notifications(), ["Synced file moved"])

    def test_rate_limit_backs_off_and_notifies_once(self):
        self.link(file_text="plan v2")

        with patch("googlekeepflow.worker_linked_files.load_keep", side_effect=KeepRateLimitedError("Google Keep is limiting requests")):
            self.worker.reconcile(["note-1"])
            first_backoff = self.worker.backoff_seconds
            self.worker.reconcile(["note-1"])

        self.assertEqual(first_backoff, RATE_LIMIT_BACKOFF_MIN_SECONDS)
        self.assertEqual(self.worker.backoff_seconds, RATE_LIMIT_BACKOFF_MIN_SECONDS * 2)
        self.assertFalse(self.worker.remote_allowed(time.time()))
        self.assertEqual(self.notifications().count("Google Keep is limiting requests"), 1)
        self.assertEqual(
            link_status_text(self.worker.links["note-1"]),
            "Not synced: Google Keep is limiting requests, sync slowed down",
        )

        self.worker.reconcile(["note-1"])

        self.assertEqual(self.worker.backoff_seconds, 0)
        self.assertTrue(self.worker.remote_allowed(time.time()))
        self.assertEqual(self.keep.notes[0].text, "plan v2")

    def test_backoff_is_capped(self):
        for _ in range(10):
            self.worker.start_backoff()

        self.assertEqual(self.worker.backoff_seconds, 30 * 60)

    def test_network_error_keeps_client_but_failed_push_drops_it(self):
        self.link()
        self.worker.clients["user@example.com"] = ("user@example.com", self.keep)

        with patch.object(self.keep, "sync", side_effect=ConnectionError("down")):
            self.worker.reconcile(["note-1"])
        self.assertIn("user@example.com", self.worker.clients)

        self.file_path.write_text("plan v2", encoding="utf-8")
        calls = []

        def fail_on_push():
            calls.append(1)
            if len(calls) == 2:
                raise ConnectionError("down")

        with patch.object(self.keep, "sync", side_effect=fail_on_push):
            self.worker.reconcile(["note-1"])
        self.assertNotIn("user@example.com", self.worker.clients)
        self.assertEqual(self.worker.links["note-1"]["last_synced_text"], "plan")

    def test_stale_sync_notifies_once_and_resets_after_success(self):
        self.link()
        with patch("googlekeepflow.worker_linked_files.load_keep", side_effect=ConnectionError("down")):
            self.worker.reconcile(["note-1"])

        now = time.time()
        self.worker.check_stale_sync(now)
        self.assertNotIn("Files are not syncing", self.notifications())

        later = self.worker.failing_since + STALE_SYNC_NOTIFY_SECONDS + 1
        self.worker.check_stale_sync(later)
        self.worker.check_stale_sync(later + 600)
        self.assertEqual(self.notifications().count("Files are not syncing"), 1)

        self.worker.reconcile(["note-1"])
        self.assertIsNone(self.worker.failing_since)
        self.assertFalse(self.worker.stale_notified)

    def test_periodic_stats_are_logged_and_reset(self):
        self.link(file_text="plan v2")
        self.worker.reconcile(["note-1"])

        with self.assertLogs("linked_files_worker", level="INFO") as logs:
            self.worker.log_stats(self.worker.stats_started + 600)

        line = next(message for message in logs.output if "Linked files stats" in message)
        self.assertIn("pushes=1", line)
        self.assertIn("logins=1", line)
        self.assertEqual(self.worker.stats["pushes"], 0)

    def test_push_and_pull_record_last_change(self):
        note = self.link(file_text="plan\nnew line\n")
        self.worker.links["note-1"]["last_synced_text"] = "plan\n"
        note.text = "plan\n"

        self.worker.reconcile(["note-1"])

        change = self.worker.links["note-1"]["last_change"]
        self.assertEqual((change["direction"], change["added"], change["removed"]), ("push", 1, 0))

        note.text = "plan\nfrom phone\n"
        self.worker.reconcile(["note-1"])

        change = self.worker.links["note-1"]["last_change"]
        self.assertEqual((change["direction"], change["added"], change["removed"]), ("pull", 1, 1))

    def test_unchanged_sync_keeps_previous_change(self):
        self.link()
        self.worker.links["note-1"]["last_change"] = {"direction": "push", "at": 1, "added": 2, "removed": 0}

        self.worker.reconcile(["note-1"])

        self.assertEqual(self.worker.links["note-1"]["last_change"]["at"], 1)

    def test_resolved_conflict_records_change(self):
        self.link(file_text="local\n", remote_text="remote\n", status=STATUS_CONFLICT)

        self.worker.handle_job({"action": "resolve", "note_id": "note-1", "direction": DIRECTION_PULL})

        change = self.worker.links["note-1"]["last_change"]
        self.assertEqual((change["direction"], change["added"], change["removed"]), ("pull", 1, 1))


class HelperTests(unittest.TestCase):
    def test_recycle_bin_paths(self):
        self.assertTrue(is_recycle_bin_path("C:\\$Recycle.Bin\\S-1-5-21\\$R7NU4TS.md"))
        self.assertFalse(is_recycle_bin_path("C:\\work\\roadmap.md"))

    def test_replace_retries_while_target_is_busy(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "a.tmp"
            target = Path(tmp) / "a.bin"
            source.write_text("new", encoding="utf-8")
            real_replace = Path.replace
            attempts = []

            def busy_then_free(self, other):
                attempts.append(1)
                if len(attempts) < 3:
                    raise PermissionError("busy")
                return real_replace(self, other)

            with patch.object(Path, "replace", busy_then_free):
                replace_with_retry(source, target, delay=0)

            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertEqual(len(attempts), 3)


if __name__ == "__main__":
    unittest.main()
