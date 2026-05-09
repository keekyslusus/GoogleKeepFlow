import unittest

from googlekeepflow.keep_commands import handle_query


class FakePlugin:
    def __init__(self, email="user@example.com", token="token"):
        self.auth = (email, token)
        self.icons = {
            "add_note": "add_note.png",
            "checklist": "checklist.png",
            "default": "keep.png",
            "edit_note": "edit_note.png",
            "pin": "pin.png",
            "reminder": "reminder.png",
            "setup": "setup.png",
        }
        self.settings = {}
        self.items = []
        self.note_results = []
        self.list_calls = []
        self.open_webview_setup = object()

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


if __name__ == "__main__":
    unittest.main()
