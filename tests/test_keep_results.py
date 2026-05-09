import unittest

from googlekeepflow.keep_results import add_to_keep_subtitle, note_preview_and_labels, render_cached_notes


class FakePlugin:
    def __init__(self):
        self.items = []
        self.open_note = object()
        self.edit_note_external = object()

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


if __name__ == "__main__":
    unittest.main()
