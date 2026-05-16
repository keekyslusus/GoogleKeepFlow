import sys
import json
import time
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler

plugindir = Path(__file__).parent.resolve()
if str(plugindir) not in sys.path:
    sys.path.insert(0, str(plugindir))
lib_path = plugindir / 'lib'
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

LIGHTWEIGHT_METHODS = {
    "context_menu",
    "open_link",
    "open_note",
}


def get_request_method():
    if len(sys.argv) <= 1:
        return ""
    try:
        request = json.loads(sys.argv[1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return ""
    return str(request.get("method", ""))


if __name__ == "__main__" and get_request_method() in LIGHTWEIGHT_METHODS:
    from googlekeepflow.keep_context_menu import GoogleKeepContextMenuPlugin

    GoogleKeepContextMenuPlugin().run()
    raise SystemExit(0)

from flox import Flox
import googlekeepflow.keep_actions as keep_actions
import googlekeepflow.keep_listing as keep_listing
from googlekeepflow.keep_clipboard import has_clipboard_image, has_pending_clipboard_image, load_pending_clipboard_image, save_clipboard_preview
from googlekeepflow.keep_auth_service import get_auth, secure_settings_dir
from googlekeepflow.keep_commands import handle_query
from googlekeepflow.keep_notes import create_keep_client, sync_keep_client
from googlekeepflow.keep_results import add_empty_notes_result, add_to_keep_subtitle, note_icon, note_preview_and_labels, render_cached_notes, render_live_notes
from googlekeepflow.keep_setup_launcher import start_setup_helper
from googlekeepflow.keep_urls import open_note_url
from googlekeepflow.keep_values import parse_bool


KEEP_SYNC_TTL_SECONDS = 15


class GoogleKeepPlugin(Flox):
    def __init__(self):
        super().__init__()
        self.keep = None
        self.keep_email = ""
        self.keep_token = ""
        self.keep_last_sync_at = 0

        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)

        log_handler = RotatingFileHandler(
            plugindir / "plugin.log",
            maxBytes=1*1024*1024,
            backupCount=1,
            encoding='utf-8'
        )
        log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        self.logger.addHandler(log_handler)
        self.logger.setLevel(logging.INFO)
        self.icons = {
            "add_archive": "icons/add_archive.png",
            "add_note": "icons/add_note.png",
            "archive": "icons/archive.png",
            "checklist": "icons/checklist.png",
            "contain_audio": "icons/contain_audio.png",
            "contain_drawing": "icons/contain_drawing.png",
            "contain_image": "icons/contain_image.png",
            "default": "keep.png",
            "edit_note": "icons/edit_note.png",
            "list": "icons/list.png",
            "open_website": "icons/open_website.png",
            "pin": "icons/pin.png",
            "reminder": "icons/reminder.png",
            "restore_archive": "icons/unarchive.png",
            "setup": "icons/setup.png",
            "trash": "icons/trash.png",
            "unpin": "icons/unpin.png",
            "clipboard" : "icons/clipboard.png",
            "warning" : "icons/warn.png",
        }

    def get_auth(self):
        return get_auth(self.settings, self.secure_settings_dir(), self.logger)

    def secure_settings_dir(self):
        return secure_settings_dir(plugindir, self.settings_path)

    def keep_client(self, email, master_token):
        if self.keep is None or self.keep_email != email or self.keep_token != master_token:
            self.keep = create_keep_client(email, master_token, self.logger)
            self.keep_email = email
            self.keep_token = master_token
            self.keep_last_sync_at = 0
        return self.keep

    def synced_keep_client(self, email, master_token, force=False):
        keep = self.keep_client(email, master_token)
        should_sync = force or time.time() - self.keep_last_sync_at > KEEP_SYNC_TTL_SECONDS
        if should_sync:
            sync_keep_client(keep, self.logger)
            self.keep_last_sync_at = time.time()
        return keep

    def query(self, query_text):
        handle_query(self, query_text)

    def add_note_result(self, text, pinned=False, archived=False, list_note=False, reminder_at_iso="", reminder_title_due="", reminder_subtitle_due=""):
        action = f"reminder {reminder_title_due}" if reminder_at_iso and reminder_title_due else "reminder" if reminder_at_iso else "checklist" if list_note else "pinned note" if pinned else "archived note" if archived else "note"
        preview, labels = note_preview_and_labels(text, list_note)
        if list_note:
            icon = self.icons["checklist"]
        elif reminder_at_iso:
            icon = self.icons["reminder"]
        elif archived:
            icon = self.icons["add_archive"]
        elif pinned:
            icon = self.icons["pin"]
        else:
            icon = self.icons["add_note"]
        self.add_item(
            title=f"Add {action}: {preview}",
            subtitle=add_to_keep_subtitle(labels, prefix=f"Reminder {reminder_subtitle_due}" if reminder_at_iso and reminder_subtitle_due else ""),
            icon=icon,
            method=self.add_note,
            parameters=[text, pinned, archived, list_note, reminder_at_iso]
        )

    def current_keyword(self):
        try:
            plugin_settings = self.app_settings.get("PluginSettings", {}).get("Plugins", {}).get(self.id, {})
        except (AttributeError, TypeError) as exc:
            self.logger.debug("Failed to read plugin keyword from app settings: %s: %s", type(exc).__name__, exc)
            plugin_settings = {}

        for setting_name in ("UserKeywords", "ActionKeywords"):
            keywords = plugin_settings.get(setting_name)
            if isinstance(keywords, list):
                for keyword in keywords:
                    normalized = str(keyword or "").strip()
                    if normalized:
                        return normalized
            else:
                normalized = str(keywords or "").strip()
                if normalized:
                    return normalized

        return str(getattr(self, "user_keyword", "") or getattr(self, "action_keyword", "") or "keep").strip()

    def list_notes(self, email, master_token, archived=False, search_text="", edit_mode=False):
        keep_listing.list_notes(self, plugindir, email, master_token, archived, search_text, edit_mode)

    def add_empty_notes_result(self, archived=False, search_text=""):
        add_empty_notes_result(self, self.icons, archived, search_text)

    def render_cached_notes(self, notes, archived=False, search_text="", edit_mode=False):
        render_cached_notes(self, self.icons, notes, archived, search_text, edit_mode)

    def note_icon(self, archived=False, pinned=False, checklist=False):
        return note_icon(self.icons, archived, pinned, checklist)

    def render_live_notes(self, notes, archived=False, search_text="", labels_by_id=None, edit_mode=False):
        render_live_notes(self, self.icons, notes, archived, search_text, labels_by_id, edit_mode)

    def add_note(self, text, pinned=False, archived=False, list_note=False, reminder_at_iso=""):
        return keep_actions.add_note(self, plugindir, text, pinned, archived, list_note, reminder_at_iso)

    def has_clipboard_image(self):
        return has_clipboard_image()

    def clipboard_image_icon(self):
        try:
            return save_clipboard_preview(self.secure_settings_dir())
        except Exception as exc:
            self.logger.debug("Failed to create clipboard image preview: %s: %s", type(exc).__name__, exc)
            return self.icons["clipboard"]

    def pending_clipboard_image_icon(self):
        try:
            payload = load_pending_clipboard_image(self.secure_settings_dir())
            return str(payload.get("preview_icon", "") or "") or self.icons["clipboard"]
        except Exception as exc:
            self.logger.debug("Failed to read pending clipboard image preview: %s: %s", type(exc).__name__, exc)
            return self.icons["clipboard"]

    def has_pending_clipboard_image(self):
        try:
            return has_pending_clipboard_image(self.secure_settings_dir())
        except Exception as exc:
            self.logger.debug("Failed to read pending clipboard image: %s: %s", type(exc).__name__, exc)
            return False

    def add_clipboard_image(self):
        return keep_actions.add_clipboard_image(self, plugindir)

    def send_clipboard_image_now(self):
        return keep_actions.send_clipboard_image_now(self, plugindir)

    def begin_clipboard_image_note(self):
        return keep_actions.begin_clipboard_image_note(self, plugindir)

    def add_pending_image_note(self, text=""):
        return keep_actions.add_pending_image_note(self, plugindir, text)

    def open_note(self, note_id):
        self.logger.info(f"Opening note: {note_id}")
        open_note_url(note_id)
        return "Opening note in browser..."

    def set_note_archived(self, note_id, archived):
        return keep_actions.set_note_archived(self, plugindir, note_id, archived)

    def set_note_pinned(self, note_id, pinned):
        return keep_actions.set_note_pinned(self, plugindir, note_id, pinned)

    def move_note_to_trash(self, note_id):
        return keep_actions.move_note_to_trash(self, plugindir, note_id)

    def edit_note_external(self, note_id):
        return keep_actions.edit_note_external(self, plugindir, note_id)

    def open_webview_setup(self, email=''):
        try:
            debug_webview = parse_bool(self.settings.get("debug_webview", False))
            start_setup_helper(plugindir, email, self.secure_settings_dir(), self.logger, debug_webview=debug_webview)
            return "Opening GoogleKeepFlow setup..."
        except Exception as e:
            self.logger.error(f"Failed to start setup: {type(e).__name__}: {e}")
            return f"Failed: {str(e)}"

if __name__ == "__main__":
    GoogleKeepPlugin().run()
