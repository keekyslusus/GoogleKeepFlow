import unittest

from googlekeepflow.keep_actions import start_authenticated_worker_action


class FakePlugin:
    def __init__(self, email="user@example.com", token="token"):
        self.auth = (email, token)
        self.settings = {}
        self.query_changes = []
        self.settings_dir = object()

    def get_auth(self):
        return self.auth

    def secure_settings_dir(self):
        return self.settings_dir

    def current_keyword(self):
        return "keep"

    def change_query(self, query, requery):
        self.query_changes.append((query, requery))


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


if __name__ == "__main__":
    unittest.main()
