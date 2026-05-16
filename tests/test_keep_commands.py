import unittest

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

    def get_auth(self):
        return self.auth

    def current_keyword(self):
        return "keep"

    def add_item(self, **kwargs):
        self.items.append(kwargs)

    def add_note_result(self, text, **kwargs):
        self.note_results.append((text, kwargs))

    def list_notes(self, email, master_token, archived=False, search_text="", edit_mode=False):
        self.list_calls.append((email, master_token, archived, search_text, edit_mode))

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


if __name__ == "__main__":
    unittest.main()
