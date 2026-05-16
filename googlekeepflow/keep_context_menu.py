from flox import Flox
from urllib.parse import urlparse

from googlekeepflow.keep_links import open_url
from googlekeepflow.keep_urls import open_note_url


KEEP_LINKS = (
    ("Open Google Keep", "Open Google Keep page in browser", "https://keep.google.com/u/0/#home", "add_note"),
    ("Open reminders", "Open reminders page in browser", "https://keep.google.com/u/0/#reminders", "reminder"),
    ("Open archive", "Open archived notes page in browser", "https://keep.google.com/u/0/#archive", "archive"),
    ("Open trash", "Open trash page in browser", "https://keep.google.com/u/0/#trash", "trash"),
)


def link_host(url):
    host = urlparse(str(url or "")).netloc.strip()
    if host.startswith("www."):
        host = host[4:]
    return host or "link"


class GoogleKeepContextMenuPlugin(Flox):
    def __init__(self):
        super().__init__()
        self.icons = {
            "add_note": "icons/add_note.png",
            "archive": "icons/archive.png",
            "default": "keep.png",
            "edit_note": "icons/edit_note.png",
            "list": "icons/list.png",
            "open_website": "icons/open_website.png",
            "pin": "icons/pin.png",
            "reminder": "icons/reminder.png",
            "restore_archive": "icons/unarchive.png",
            "trash": "icons/trash.png",
            "unpin": "icons/unpin.png",
            "clipboard": "icons/clipboard.png",
        }

    def open_note(self, note_id):
        open_note_url(note_id)
        return "Opening note in browser..."

    def open_link(self, url):
        open_url(url)
        return "Opening link..."

    def add_keep_launcher_items(self):
        for title, subtitle, url, icon in KEEP_LINKS:
            self.add_item(
                title=title,
                subtitle=subtitle,
                icon=self.icons[icon],
                method=self.open_link,
                parameters=[url],
            )

    def context_menu(self, data):
        if not isinstance(data, dict):
            return

        if data.get("type") == "keep_launcher":
            self.add_keep_launcher_items()
            return

        if data.get("type") == "clipboard_image":
            self.add_item(
                title="Send image without text",
                subtitle="Send the current clipboard image to Google Keep",
                icon=self.icons["clipboard"],
                method="send_clipboard_image_now",
                parameters=[],
            )
            return

        if data.get("type") != "keep_note":
            return

        note_id = data.get("note_id")
        if note_id:
            self.add_item(
                title="Open note in Google Keep",
                subtitle="Open the full note in your browser",
                icon=self.icons["default"],
                method=self.open_note,
                parameters=[note_id],
            )

            if not bool(data.get("checklist")) and not bool(data.get("edit_mode")):
                self.add_item(
                    title="Edit note in text editor",
                    subtitle="Save the .txt file to sync changes back to Google Keep",
                    icon=self.icons["edit_note"],
                    method="edit_note_external",
                    parameters=[note_id],
                )

            archived = bool(data.get("archived"))
            self.add_item(
                title="Restore from archive" if archived else "Move to archive",
                subtitle="Return this note to active notes" if archived else "Move this note out of active notes",
                icon=self.icons["restore_archive"] if archived else self.icons["archive"],
                method="set_note_archived",
                parameters=[note_id, not archived],
            )

            pinned = bool(data.get("pinned"))
            self.add_item(
                title="Unpin note" if pinned else "Pin note",
                subtitle="Remove this note from pinned notes" if pinned else "Keep this note at the top",
                icon=self.icons["unpin"] if pinned else self.icons["pin"],
                method="set_note_pinned",
                parameters=[note_id, not pinned],
            )

        links = data.get("links") if isinstance(data.get("links"), list) else []
        for url in links:
            self.add_item(
                title=f"Open {link_host(url)}",
                subtitle=url,
                icon=self.icons["open_website"],
                method=self.open_link,
                parameters=[url],
            )

        if note_id:
            self.add_item(
                title="Move to trash",
                subtitle="Move this note to Google Keep trash",
                icon=self.icons["trash"],
                method="move_note_to_trash",
                parameters=[note_id],
            )
