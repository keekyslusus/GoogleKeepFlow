from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINFORMS_FILE = ROOT / "lib" / "webview" / "platforms" / "winforms.py"


def patch_winforms_text(text):
    start = text.index("class OpenFolderDialog:")
    end = text.index("_main_window_created = Event()", start)
    replacement = """class OpenFolderDialog:
    @classmethod
    def show(cls, parent=None, initialDirectory=None, allow_multiple=False, title=None):
        dialog = WinForms.FolderBrowserDialog()
        if initialDirectory:
            dialog.InitialDirectory = initialDirectory
        if title:
            dialog.Description = title
        result = dialog.ShowDialog(parent) if parent else dialog.ShowDialog()
        if result == WinForms.DialogResult.OK:
            return (dialog.SelectedPath,)
        return None


"""
    return text[:start] + replacement + text[end:]


def main():
    text = WINFORMS_FILE.read_text(encoding="utf-8")
    text = patch_winforms_text(text)
    WINFORMS_FILE.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
