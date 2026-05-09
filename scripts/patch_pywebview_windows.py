from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINFORMS_FILE = ROOT / "lib" / "webview" / "platforms" / "winforms.py"


def replace_once(text, old, new):
    if old not in text:
        raise RuntimeError(f"Patch marker not found: {old!r}")
    return text.replace(old, new, 1)


def main():
    text = WINFORMS_FILE.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "clr.AddReference('System.Reflection')",
        "clr.AddReference('System.Reflection')\nclr.AddReference('Microsoft.Win32.SystemEvents')",
    )

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
    text = text[:start] + replacement + text[end:]
    WINFORMS_FILE.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
