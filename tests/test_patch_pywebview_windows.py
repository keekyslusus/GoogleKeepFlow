import unittest

from scripts.patch_pywebview_windows import patch_winforms_text


class PatchPywebviewWindowsTests(unittest.TestCase):
    def test_patch_replaces_open_folder_dialog_without_systemevents_reference(self):
        source = """clr.AddReference('System.Reflection')

class OpenFolderDialog:
    broken = True


_main_window_created = Event()
"""

        patched = patch_winforms_text(source)

        self.assertIn("dialog = WinForms.FolderBrowserDialog()", patched)
        self.assertIn("_main_window_created = Event()", patched)
        self.assertNotIn("Microsoft.Win32.SystemEvents", patched)


if __name__ == "__main__":
    unittest.main()
