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
        }

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


if __name__ == "__main__":
    unittest.main()
