import unittest

from googlekeepflow.worker_setup_webview import parse_bool


class WorkerSetupWebviewTests(unittest.TestCase):
    def test_parse_bool_accepts_debug_enabled_values(self):
        self.assertTrue(parse_bool(True))
        self.assertTrue(parse_bool("1"))
        self.assertTrue(parse_bool("true"))
        self.assertTrue(parse_bool("yes"))
        self.assertTrue(parse_bool("on"))

    def test_parse_bool_rejects_debug_disabled_values(self):
        self.assertFalse(parse_bool(False))
        self.assertFalse(parse_bool("0"))
        self.assertFalse(parse_bool("false"))
        self.assertFalse(parse_bool(""))


if __name__ == "__main__":
    unittest.main()
