import tempfile
import unittest
from pathlib import Path

from googlekeepflow.keep_commands import handle_query


class FakePlugin:
    def __init__(self, email="user@example.com", token="token"):
        self.auth = (email, token)
        self.icons = {
            "add_note": "add_note.png",
            "archive": "archive.png",
            "checklist": "checklist.png",
            "default": "keep.png",
            "edit_note": "edit_note.png",
            "link": "link.png",
            "list": "list.png",
            "pin": "pin.png",
            "reminder": "reminder.png",
            "setup": "setup.png",
            "clipboard": "clipboard.png",
            "warning": "warn.png",
        }
        self.settings = {}
        self.items = []
        self.note_results = []
        self.list_calls = []
        self.open_webview_setup = object()
        self.add_clipboard_image = object()
        self.begin_clipboard_image_note = object()
        self.add_pending_image_note = object()
        self.clipboard_image = False
        self.clipboard_icon = "preview.png"
        self.pending_clipboard_image = False
        self.link_file = object()
        self.link_path = None
        self.clipboard_file = None
        self.links = []
        self.link_list_paths = []

    def get_auth(self):
        return self.auth

    def current_keyword(self):
        return "keep"

    def add_item(self, **kwargs):
        self.items.append(kwargs)

    def add_note_result(self, text, **kwargs):
        self.note_results.append((text, kwargs))

    def list_notes(self, email, master_token, archived=False, search_text="", edit_mode=False, link_path="", linked_files=None):
        self.list_calls.append((email, master_token, archived, search_text, edit_mode))
        self.link_list_paths.append(link_path)
        self.list_linked_files = linked_files

    def link_source(self, command_text):
        return self.link_path, command_text

    def clipboard_link_file(self):
        return self.clipboard_file

    def linked_files(self):
        return self.links

    def linked_file_paths(self):
        return {entry["note_id"]: entry["path"] for entry in self.links}

    def linked_file_entry(self, path):
        return next((entry for entry in self.links if Path(entry["path"]) == Path(path)), None)

    def has_clipboard_image(self):
        return self.clipboard_image

    def clipboard_image_icon(self):
        return self.clipboard_icon

    def has_pending_clipboard_image(self):
        return self.pending_clipboard_image


class KeepCommandsTests(unittest.TestCase):
    def test_unknown_query_falls_back_to_add_note_result(self):
        plugin = FakePlugin()

        handle_query(plugin, "buy milk")

        self.assertEqual(plugin.note_results, [("buy milk", {})])
        self.assertEqual(plugin.items, [])
        self.assertEqual(plugin.list_calls, [])

    def test_setup_required_when_auth_missing(self):
        plugin = FakePlugin(email="", token="")

        handle_query(plugin, "buy milk")

        self.assertEqual(plugin.items[0]["title"], "Setup GoogleKeepFlow")
        self.assertEqual(plugin.note_results, [])

    def test_archive_command_adds_archived_note_result_and_lists_archive(self):
        plugin = FakePlugin()

        handle_query(plugin, "archive old idea")

        self.assertEqual(plugin.note_results, [("old idea", {"archived": True})])
        self.assertEqual(plugin.list_calls, [("user@example.com", "token", True, "old idea", False)])

    def test_edit_command_lists_notes_in_edit_mode(self):
        plugin = FakePlugin()

        handle_query(plugin, "edit project plan")

        self.assertEqual(plugin.list_calls, [("user@example.com", "token", False, "project plan", True)])
        self.assertEqual(plugin.note_results, [])

    def test_reminder_command_is_blocked_when_feature_disabled(self):
        plugin = FakePlugin()

        handle_query(plugin, "remind in 10m check oven")

        self.assertEqual(plugin.items[0]["title"], "Reminders are experimental")
        self.assertEqual(plugin.note_results, [])

    def test_empty_query_adds_clipboard_image_result_when_image_available(self):
        plugin = FakePlugin()
        plugin.clipboard_image = True

        handle_query(plugin, "")

        self.assertEqual(plugin.items[1]["title"], "Send clipboard image to Google Keep")
        self.assertEqual(plugin.items[1]["icon"], "preview.png")
        self.assertEqual(plugin.items[1]["method"], plugin.begin_clipboard_image_note)
        self.assertEqual(plugin.items[1]["context"], {"type": "clipboard_image"})

    def test_help_includes_clipboard_image_query_shortcut(self):
        plugin = FakePlugin()

        handle_query(plugin, "?")

        image_item = next(item for item in plugin.items if item["title"] == "keep [image]")
        self.assertEqual(image_item["subtitle"], "Copy an image to the clipboard, then send it to Google Keep")
        self.assertEqual(image_item["icon"], "clipboard.png")
        self.assertEqual(image_item["method"], "change_query")
        self.assertEqual(image_item["parameters"], ["keep [image] ", True])
        self.assertTrue(image_item["dont_hide"])

    def test_image_marker_adds_pending_image_note_result(self):
        plugin = FakePlugin()
        plugin.pending_clipboard_image = True

        handle_query(plugin, "[image] caption #photos")

        self.assertEqual(plugin.items[0]["title"], "Add image note: caption")
        self.assertEqual(plugin.items[0]["subtitle"], "Send [image] with this text to Google Keep with label #photos")
        self.assertEqual(plugin.items[0]["method"], plugin.add_pending_image_note)
        self.assertEqual(plugin.items[0]["parameters"], ["caption #photos"])

    def test_image_marker_subtitle_includes_multiple_labels(self):
        plugin = FakePlugin()
        plugin.pending_clipboard_image = True

        handle_query(plugin, "[image] caption #bro #test")

        self.assertEqual(plugin.items[0]["title"], "Add image note: caption")
        self.assertEqual(plugin.items[0]["subtitle"], "Send [image] with this text to Google Keep with labels #bro #test")

    def test_image_marker_without_pending_image_is_disabled(self):
        plugin = FakePlugin()

        handle_query(plugin, "[image] caption")

        self.assertEqual(plugin.items[0]["title"], "No image attached")
        self.assertEqual(plugin.items[0]["icon"], "warn.png")
        self.assertNotIn("method", plugin.items[0])
        self.assertEqual(plugin.note_results, [])


class KeepLinkCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file_path = Path(self.tmp.name) / "roadmap.md"
        self.file_path.write_text("# plan", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_link_without_copied_file_explains_how_to_copy(self):
        plugin = FakePlugin()

        handle_query(plugin, "link")

        self.assertEqual(plugin.items[0]["title"], "Copy a .txt or .md file first")
        self.assertNotIn("method", plugin.items[0])
        self.assertEqual(plugin.list_calls, [])

    def test_link_rejects_unsupported_file_type(self):
        plugin = FakePlugin()
        other = Path(self.tmp.name) / "photo.png"
        other.write_bytes(b"png")
        plugin.link_path = other

        handle_query(plugin, "link")

        self.assertEqual(plugin.items[0]["title"], "photo.png can't be synced")
        self.assertEqual(plugin.list_calls, [])

    def test_link_offers_new_note_and_lists_notes_in_link_mode(self):
        plugin = FakePlugin()
        plugin.link_path = self.file_path

        handle_query(plugin, "link project")

        self.assertEqual(plugin.items[0]["title"], "Sync roadmap.md with a new note")
        self.assertEqual(plugin.items[0]["method"], plugin.link_file)
        self.assertEqual(plugin.items[0]["parameters"], [str(self.file_path)])
        self.assertEqual(plugin.list_calls, [("user@example.com", "token", False, "project", False)])
        self.assertEqual(plugin.link_list_paths, [str(self.file_path)])

    def test_link_hides_notes_already_synced_with_other_files(self):
        plugin = FakePlugin()
        plugin.link_path = self.file_path
        plugin.links = [{"note_id": "note-7", "path": str(Path(self.tmp.name) / "other.md"), "status": "synced"}]

        handle_query(plugin, "link")

        self.assertEqual(plugin.list_linked_files, {"note-7": str(Path(self.tmp.name) / "other.md")})

    def test_edit_passes_linked_files_to_label_synced_notes(self):
        plugin = FakePlugin()
        plugin.links = [{"note_id": "note-7", "path": str(self.file_path), "status": "synced"}]

        handle_query(plugin, "edit")

        self.assertEqual(plugin.list_calls, [("user@example.com", "token", False, "", True)])
        self.assertEqual(plugin.list_linked_files, {"note-7": str(self.file_path)})

    def test_link_for_already_synced_file_shows_its_status(self):
        plugin = FakePlugin()
        plugin.link_path = self.file_path
        plugin.links = [{"note_id": "note-1", "path": str(self.file_path), "status": "synced"}]

        handle_query(plugin, "link")

        self.assertEqual(len(plugin.items), 1)
        self.assertEqual(plugin.items[0]["title"], "roadmap.md")
        self.assertEqual(plugin.items[0]["context"]["type"], "linked_file")
        self.assertEqual(plugin.list_calls, [])

    def test_links_lists_synced_files_with_status_icons(self):
        plugin = FakePlugin()
        plugin.links = [
            {"note_id": "note-1", "path": str(self.file_path), "status": "synced"},
            {"note_id": "note-2", "path": str(Path(self.tmp.name) / "todo.txt"), "status": "conflict"},
        ]

        handle_query(plugin, "links")

        self.assertEqual([item["title"] for item in plugin.items], ["roadmap.md", "todo.txt"])
        self.assertEqual(plugin.items[0]["icon"], "link.png")
        self.assertEqual(plugin.items[1]["icon"], "warn.png")
        self.assertEqual(plugin.items[0]["method"], "open_path")
        self.assertEqual(plugin.items[1]["context"]["status"], "conflict")

    def test_links_flags_files_that_are_not_syncing(self):
        plugin = FakePlugin()
        plugin.links = [{"note_id": "note-1", "path": str(self.file_path), "status": "synced", "sync_error": "no connection to Google Keep"}]

        handle_query(plugin, "links")

        self.assertEqual(plugin.items[0]["icon"], "warn.png")
        self.assertTrue(plugin.items[0]["subtitle"].startswith("Not synced: no connection to Google Keep"))

    def test_links_without_entries_points_to_link_command(self):
        plugin = FakePlugin()

        handle_query(plugin, "links")

        self.assertEqual(plugin.items[0]["title"], "No synced files")
        self.assertEqual(plugin.items[0]["parameters"], ["keep link ", True])

    def test_empty_query_suggests_copied_text_file(self):
        plugin = FakePlugin()
        plugin.clipboard_file = self.file_path

        handle_query(plugin, "")

        self.assertEqual(plugin.items[1]["title"], "Sync copied file roadmap.md with Google Keep")
        self.assertEqual(plugin.items[1]["parameters"], ["keep link ", True])


if __name__ == "__main__":
    unittest.main()
