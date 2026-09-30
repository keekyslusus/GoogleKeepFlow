import sys
import types
import unittest

sys.modules.setdefault("flox", types.SimpleNamespace(Flox=object))

from googlekeepflow.keep_context_menu import GoogleKeepContextMenuPlugin


class FakeContextPlugin:
    def __init__(self):
        self.items = []
        self.icons = {
            "clipboard": "icons/clipboard.png",
            "default": "keep.png",
            "edit_note": "icons/edit_note.png",
            "link": "icons/link.png",
            "warning": "icons/warn.png",
        }

    def open_note(self, note_id):
        pass

    def open_path(self, path):
        pass

    def add_linked_file_items(self, data):
        GoogleKeepContextMenuPlugin.add_linked_file_items(self, data)

    def add_link_target_items(self, data):
        GoogleKeepContextMenuPlugin.add_link_target_items(self, data)

    def add_item(self, **kwargs):
        self.items.append(kwargs)


class KeepContextMenuTests(unittest.TestCase):
    def test_clipboard_image_context_adds_send_without_text_action(self):
        plugin = FakeContextPlugin()

        GoogleKeepContextMenuPlugin.context_menu(plugin, {"type": "clipboard_image"})

        self.assertEqual(len(plugin.items), 1)
        self.assertEqual(plugin.items[0]["title"], "Send image without text")
        self.assertEqual(plugin.items[0]["icon"], "icons/clipboard.png")
        self.assertEqual(plugin.items[0]["method"], "send_clipboard_image_now")
        self.assertEqual(plugin.items[0]["parameters"], [])

    def test_linked_file_conflict_offers_both_versions(self):
        plugin = FakeContextPlugin()

        GoogleKeepContextMenuPlugin.context_menu(plugin, {
            "type": "linked_file",
            "note_id": "note-1",
            "path": "C:/work/roadmap.md",
            "status": "conflict",
        })

        titles = [item["title"] for item in plugin.items]
        self.assertEqual(titles[:2], ["Use local file version", "Use Google Keep version"])
        self.assertEqual(plugin.items[0]["parameters"], ["note-1", "push"])
        self.assertEqual(plugin.items[1]["parameters"], ["note-1", "pull"])
        self.assertEqual(plugin.items[-1]["method"], "unlink_file")

    def test_synced_linked_file_has_no_resolve_items(self):
        plugin = FakeContextPlugin()

        GoogleKeepContextMenuPlugin.context_menu(plugin, {
            "type": "linked_file",
            "note_id": "note-1",
            "path": "C:/work/roadmap.md",
            "status": "synced",
        })

        self.assertNotIn("resolve_linked_file", [item.get("method") for item in plugin.items])

    def test_link_target_note_offers_both_directions(self):
        plugin = FakeContextPlugin()

        GoogleKeepContextMenuPlugin.context_menu(plugin, {
            "type": "keep_note",
            "note_id": "note-1",
            "link_path": "C:/work/roadmap.md",
        })

        self.assertEqual(plugin.items[0]["parameters"], ["C:/work/roadmap.md", "note-1", "push"])
        self.assertEqual(plugin.items[1]["parameters"], ["C:/work/roadmap.md", "note-1", "pull"])
        self.assertNotIn("move_note_to_trash", [item.get("method") for item in plugin.items])


if __name__ == "__main__":
    unittest.main()
