import unittest

from googlekeepflow.keep_results import add_to_keep_subtitle, keep_action_subtitle, note_preview_and_labels, render_cached_notes


class FakePlugin:
    def __init__(self):
        self.items = []
        self.open_note = object()
        self.edit_note_external = object()
        self.link_file = object()

    def add_item(self, **kwargs):
        self.items.append(kwargs)


class KeepResultsTests(unittest.TestCase):
    def test_note_preview_extracts_labels_without_losing_text(self):
        preview, labels = note_preview_and_labels("buy milk #shopping #Home")

        self.assertEqual(preview, "buy milk")
        self.assertEqual(labels, ["shopping", "Home"])

    def test_checklist_preview_formats_semicolon_items(self):
        preview, labels = note_preview_and_labels("milk; eggs; bread #shopping", list_note=True)

        self.assertEqual(preview, "\u25a1 milk \u25a1 eggs \u25a1 bread")
        self.assertEqual(labels, ["shopping"])

    def test_add_to_keep_subtitle_includes_prefix_and_labels(self):
        subtitle = add_to_keep_subtitle(["work", "ideas"], prefix="Reminder today 09:00")

        self.assertEqual(subtitle, "Reminder today 09:00 \u2022 Add to Google Keep with labels #work #ideas")

    def test_keep_action_subtitle_reuses_label_suffix(self):
        subtitle = keep_action_subtitle("Send [image] with this text to Google Keep", ["bro"])

        self.assertEqual(subtitle, "Send [image] with this text to Google Keep with label #bro")

    def test_edit_mode_results_open_external_editor_with_edit_icon(self):
        plugin = FakePlugin()
        icons = {
            "archive": "archive.png",
            "checklist": "checklist.png",
            "edit_note": "edit_note.png",
            "list": "list.png",
            "pin": "pin.png",
        }
        notes = [{
            "id": "note-1",
            "title": "Project plan",
            "subtitle": "Draft",
            "archived": False,
            "pinned": False,
            "type": "NOTE",
        }]

        render_cached_notes(plugin, icons, notes, edit_mode=True)

        self.assertEqual(plugin.items[0]["method"], plugin.edit_note_external)
        self.assertEqual(plugin.items[0]["parameters"], ["note-1"])
        self.assertEqual(plugin.items[0]["icon"], "edit_note.png")
        self.assertEqual(plugin.items[0]["subtitle"], "Draft")
        self.assertTrue(plugin.items[0]["context"]["edit_mode"])

    def test_edit_mode_replaces_open_in_keep_subtitle(self):
        plugin = FakePlugin()
        icons = {
            "archive": "archive.png",
            "checklist": "checklist.png",
            "edit_note": "edit_note.png",
            "list": "list.png",
            "pin": "pin.png",
        }
        notes = [{
            "id": "note-1",
            "title": "Short note",
            "subtitle": "Open in Google Keep",
            "archived": False,
            "pinned": False,
            "type": "NOTE",
        }]

        render_cached_notes(plugin, icons, notes, edit_mode=True)

        self.assertEqual(plugin.items[0]["subtitle"], "Edit in text editor")

    def test_edit_mode_keeps_pin_icon_for_pinned_notes(self):
        plugin = FakePlugin()
        icons = {
            "archive": "archive.png",
            "checklist": "checklist.png",
            "edit_note": "edit_note.png",
            "list": "list.png",
            "pin": "pin.png",
        }
        notes = [{
            "id": "note-1",
            "title": "Pinned",
            "subtitle": "",
            "archived": False,
            "pinned": True,
            "type": "NOTE",
        }]

        render_cached_notes(plugin, icons, notes, edit_mode=True)

        self.assertEqual(plugin.items[0]["icon"], "pin.png")

    def test_link_mode_keeps_note_icons_and_skips_checklists(self):
        plugin = FakePlugin()
        icons = {
            "archive": "archive.png",
            "checklist": "checklist.png",
            "contain_image": "contain_image.png",
            "edit_note": "edit_note.png",
            "list": "list.png",
            "pin": "pin.png",
        }
        notes = [
            {"id": "plain", "title": "Plain", "pinned": False, "type": "NOTE"},
            {"id": "pinned", "title": "Pinned", "pinned": True, "type": "NOTE"},
            {"id": "image", "title": "Photo", "pinned": False, "type": "NOTE", "media": {"image": 1}},
            {"id": "todo", "title": "Todo", "pinned": False, "type": "LIST"},
        ]

        render_cached_notes(plugin, icons, notes, link_path="C:/work/roadmap.md", linked_files={"pinned": "C:/work/other.md"})

        self.assertEqual([item["icon"] for item in plugin.items], ["list.png", "contain_image.png"])
        self.assertEqual(plugin.items[0]["method"], plugin.link_file)
        self.assertEqual(plugin.items[0]["parameters"], ["C:/work/roadmap.md", "plain"])
        self.assertEqual(plugin.items[0]["subtitle"], "Sync with roadmap.md: file text replaces this note")


    def test_edit_mode_labels_synced_notes_with_their_file(self):
        plugin = FakePlugin()
        icons = {"archive": "archive.png", "checklist": "checklist.png", "edit_note": "edit_note.png", "list": "list.png", "pin": "pin.png"}
        notes = [
            {"id": "synced", "title": "Roadmap", "subtitle": "Open in Google Keep", "pinned": False, "type": "NOTE"},
            {"id": "plain", "title": "Plain", "subtitle": "Open in Google Keep", "pinned": False, "type": "NOTE"},
        ]

        render_cached_notes(plugin, icons, notes, edit_mode=True, linked_files={"synced": "C:/work/release_roadmap.md"})

        self.assertEqual(plugin.items[0]["subtitle"], "Open synced file release_roadmap.md")
        self.assertEqual(plugin.items[1]["subtitle"], "Edit in text editor")
        self.assertEqual(plugin.items[0]["method"], plugin.edit_note_external)


if __name__ == "__main__":
    unittest.main()
