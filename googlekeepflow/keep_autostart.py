import json
import subprocess
import sys
from pathlib import Path

from googlekeepflow.keep_values import parse_bool


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "GoogleKeepFlow file sync"
AUTOSTART_SETTING = "sync_files_on_startup"
PLUGIN_SETTINGS_FILE_NAME = "Settings.json"


def autostart_enabled(settings_dir):
    try:
        settings = json.loads((Path(settings_dir) / PLUGIN_SETTINGS_FILE_NAME).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return isinstance(settings, dict) and parse_bool(settings.get(AUTOSTART_SETTING, False))


def windowless_python(executable=None):
    executable = Path(executable or sys.executable)
    pythonw = executable.with_name("pythonw.exe")
    return pythonw if pythonw.exists() else executable


def autostart_command(script_path, settings_dir, executable=None):
    return subprocess.list2cmdline([str(windowless_python(executable)), str(script_path), str(settings_dir)])


def read_run_value(name=RUN_VALUE_NAME):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value)
    except FileNotFoundError:
        return None


def write_run_value(command, name=RUN_VALUE_NAME):
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)


def delete_run_value(name=RUN_VALUE_NAME):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass


def update_autostart(enabled, command, read=read_run_value, write=write_run_value, delete=delete_run_value):
    """Keep the Run entry in line with the setting; returns "added", "updated", "removed" or ""."""
    if sys.platform != "win32" and read is read_run_value:
        return ""
    current = read()
    if not enabled:
        if current is None:
            return ""
        delete()
        return "removed"
    if current == command:
        return ""
    write(command)
    return "added" if current is None else "updated"
