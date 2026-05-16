import unittest
from unittest.mock import patch

from googlekeepflow.keep_setup_notifications import is_pythonnet_runtime_error
from googlekeepflow.keep_values import parse_bool
from googlekeepflow.worker_setup_webview import configure_pythonnet_runtime


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

    def test_configure_pythonnet_runtime_uses_netfx_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            configure_pythonnet_runtime()
            import os

            self.assertEqual(os.environ["PYTHONNET_RUNTIME"], "netfx")
            self.assertNotIn("PYTHONNET_CORECLR_RUNTIME_CONFIG", os.environ)

    def test_configure_pythonnet_runtime_keeps_explicit_runtime(self):
        with patch.dict("os.environ", {"PYTHONNET_RUNTIME": "coreclr"}, clear=True):
            configure_pythonnet_runtime()
            import os

            self.assertEqual(os.environ["PYTHONNET_RUNTIME"], "coreclr")

    def test_detects_pythonnet_runtime_failure(self):
        error = RuntimeError(
            "Failed to resolve Python.Runtime.Loader.Initialize from "
            "lib\\pythonnet\\runtime\\Python.Runtime.dll"
        )

        self.assertTrue(is_pythonnet_runtime_error(error))


if __name__ == "__main__":
    unittest.main()
