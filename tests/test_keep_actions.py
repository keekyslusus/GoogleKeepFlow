import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from googlekeepflow.keep_actions import edit_note_external, send_clipboard_image_now, start_authenticated_worker_action
from googlekeepflow.keep_file_links import load_registry, save_registry


class FakePlugin:
    def __init__(self, email="user@example.com", token="token"):
        self.auth = (email, token)
        self.settings = {}
        self.query_changes = []
        self.settings_dir = object()
        self.logger = object()

    def get_auth(self):
        return self.auth

    def secure_settings_dir(self):
        return self.settings_dir

    def current_keyword(self):
        return "keep"

    def change_query(self, query, requery):
        self.query_changes.append((query, requery))


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, *args):
        self.messages.append(("info", args))

    def error(self, *args):
        self.messages.append(("error", args))


class KeepActionsTests(unittest.TestCase):
    def test_successful_worker_action_resets_launcher_query(self):
        plugin = FakePlugin()
        calls = []

        result = start_authenticated_worker_action(
            plugin,
            "test worker",
            lambda email, token, notifications, settings_dir: calls.append((email, token, notifications, settings_dir)),
            "Done",
        )

        self.assertEqual(result, "Done")
        self.assertEqual(calls, [("user@example.com", "token", True, plugin.settings_dir)])
        self.assertEqual(plugin.query_changes, [("keep", True)])

    def test_worker_action_parses_disabled_notifications(self):
        plugin = FakePlugin()
        plugin.settings["show_notifications"] = "False"
        calls = []

        result = start_authenticated_worker_action(
            plugin,
            "test worker",
            lambda email, token, notifications, settings_dir: calls.append(notifications),
            "Done",
        )

        self.assertEqual(result, "Done")
        self.assertEqual(calls, [False])

    def test_unauthenticated_worker_action_does_not_reset_launcher_query(self):
        plugin = FakePlugin(email="", token="")

        result = start_authenticated_worker_action(
            plugin,
            "test worker",
            lambda email, token, notifications, settings_dir: None,
            "Done",
        )

        self.assertEqual(result, "GoogleKeepFlow setup required")
        self.assertEqual(plugin.query_changes, [])

    def test_send_clipboard_image_now_reads_clipboard_and_starts_worker(self):
        plugin = FakePlugin()
        plugin.logger = FakeLogger()
        image_payload = {"mime_type": "image/png", "png_base64": "abc"}
        calls = []

        with patch("googlekeepflow.keep_actions.read_clipboard_png", return_value=image_payload):
            with patch("googlekeepflow.keep_actions.start_image_worker", lambda *args: calls.append(args)):
                result = send_clipboard_image_now(plugin, "plugin-dir")

        self.assertEqual(result, "Image queued for Google Keep sync...")
        self.assertEqual(calls[0], ("plugin-dir", "user@example.com", image_payload, "", True, plugin.logger, plugin.settings_dir))
        self.assertEqual(plugin.query_changes, [("keep", True)])


class EditSyncedNoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plugin = FakePlugin()
        self.plugin.settings_dir = Path(self.tmp.name)
        self.plugin.logger = FakeLogger()
        self.file_path = Path(self.tmp.name) / "release_roadmap.md"
        registry = load_registry(self.plugin.settings_dir)
        registry["links"]["note-1"] = {"note_id": "note-1", "path": str(self.file_path)}
        save_registry(self.plugin.settings_dir, registry)

    def tearDown(self):
        self.tmp.cleanup()

    def test_synced_note_opens_its_file_instead_of_temp_copy(self):
        self.file_path.write_text("plan", encoding="utf-8")
        opened = []

        with patch("googlekeepflow.keep_actions.open_file", opened.append):
            with patch("googlekeepflow.keep_actions.start_external_edit_worker") as start_worker:
                result = edit_note_external(self.plugin, "plugin-dir", "note-1")

        self.assertEqual(result, "Opening synced file...")
        self.assertEqual(opened, [self.file_path])
        start_worker.assert_not_called()
        self.assertEqual(self.plugin.query_changes, [("keep", True)])

    def test_missing_synced_file_falls_back_to_temp_copy(self):
        with patch("googlekeepflow.keep_actions.open_file") as open_file:
            with patch("googlekeepflow.keep_actions.start_external_edit_worker") as start_worker:
                result = edit_note_external(self.plugin, "plugin-dir", "note-1")

        self.assertEqual(result, "Opening note in your text editor...")
        open_file.assert_not_called()
        start_worker.assert_called_once()

    def test_unsynced_note_uses_temp_copy(self):
        with patch("googlekeepflow.keep_actions.start_external_edit_worker") as start_worker:
            result = edit_note_external(self.plugin, "plugin-dir", "note-2")

        self.assertEqual(result, "Opening note in your text editor...")
        start_worker.assert_called_once()


if __name__ == "__main__":
    unittest.main()
