import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from googlekeepflow.keep_setup_launcher import start_setup_helper


class KeepSetupLauncherTests(unittest.TestCase):
    def test_start_setup_helper_passes_debug_flag_to_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = Path(tmp)
            package_dir = plugin_dir / "googlekeepflow"
            package_dir.mkdir()
            setup_script = package_dir / "worker_setup_webview.py"
            setup_script.write_text("", encoding="utf-8")

            with patch("googlekeepflow.keep_setup_launcher.subprocess.Popen") as popen:
                popen.return_value.pid = 123

                start_setup_helper(
                    plugin_dir,
                    email="user@example.com",
                    settings_dir=plugin_dir / "settings",
                    debug_webview=True,
                )

            command = popen.call_args.args[0]
            self.assertEqual(command, [
                sys.executable,
                str(setup_script),
                "user@example.com",
                str(plugin_dir / "settings"),
                "1",
            ])

    def test_start_setup_helper_disables_debug_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = Path(tmp)
            package_dir = plugin_dir / "googlekeepflow"
            package_dir.mkdir()
            setup_script = package_dir / "worker_setup_webview.py"
            setup_script.write_text("", encoding="utf-8")

            with patch("googlekeepflow.keep_setup_launcher.subprocess.Popen") as popen:
                popen.return_value.pid = 123

                start_setup_helper(plugin_dir)

            self.assertEqual(popen.call_args.args[0][-1], "0")


if __name__ == "__main__":
    unittest.main()
