import json
import tempfile
import unittest
from pathlib import Path

from googlekeepflow.keep_autostart import autostart_command, autostart_enabled, update_autostart


class FakeRunKey:
    def __init__(self, value=None):
        self.value = value
        self.writes = 0

    def read(self):
        return self.value

    def write(self, command):
        self.value = command
        self.writes += 1

    def delete(self):
        self.value = None


def update(run_key, enabled, command="cmd"):
    return update_autostart(enabled, command, read=run_key.read, write=run_key.write, delete=run_key.delete)


class AutostartSettingTests(unittest.TestCase):
    def test_reads_flow_plugin_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(autostart_enabled(tmp))

            (Path(tmp) / "Settings.json").write_text(json.dumps({"sync_files_on_startup": True}), encoding="utf-8")
            self.assertTrue(autostart_enabled(tmp))

            (Path(tmp) / "Settings.json").write_text("{broken", encoding="utf-8")
            self.assertFalse(autostart_enabled(tmp))

    def test_command_prefers_pythonw_and_quotes_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            python = Path(tmp) / "python.exe"
            pythonw = Path(tmp) / "pythonw.exe"
            python.write_bytes(b"")
            pythonw.write_bytes(b"")

            command = autostart_command(Path("C:/Plugins/Google Keep/worker.py"), Path("C:/Settings dir"), python)

            self.assertTrue(command.startswith(f'"{pythonw}"') or command.startswith(str(pythonw)))
            self.assertIn('"C:\\Plugins\\Google Keep\\worker.py"', command)
            self.assertIn('"C:\\Settings dir"', command)


class UpdateAutostartTests(unittest.TestCase):
    def test_adds_updates_and_removes_entry(self):
        run_key = FakeRunKey()

        self.assertEqual(update(run_key, True, "old"), "added")
        self.assertEqual(update(run_key, True, "old"), "")
        self.assertEqual(update(run_key, True, "new"), "updated")
        self.assertEqual((run_key.value, run_key.writes), ("new", 2))
        self.assertEqual(update(run_key, False), "removed")
        self.assertIsNone(run_key.value)
        self.assertEqual(update(run_key, False), "")


if __name__ == "__main__":
    unittest.main()
