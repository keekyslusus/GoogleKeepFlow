import tempfile
import unittest
from pathlib import Path

from googlekeepflow.keep_cache import load_note_body_cache, save_cache


class TypeValue:
    def __init__(self, value):
        self.value = value


class Timestamps:
    def __init__(self, updated):
        self.updated = updated


class Updated:
    def timestamp(self):
        return 123.0


class Note:
    def __init__(self, note_id="note-1", text="Body text", note_type="NOTE"):
        self.id = note_id
        self.title = "Title"
        self.text = text
        self.type = TypeValue(note_type)
        self.archived = False
        self.pinned = False
        self.trashed = False
        self.timestamps = Timestamps(Updated())
        self.labels = []


class KeepCacheBodyTests(unittest.TestCase):
    def test_save_cache_writes_plain_note_body_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_cache(tmp, "user@example.com", [Note()])

            body = load_note_body_cache(tmp, "user@example.com", "note-1")

        self.assertIsNotNone(body)
        self.assertEqual(body["text"], "Body text")
        self.assertEqual(body["updated"], 123.0)

    def test_save_cache_skips_checklist_body_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_cache(tmp, "user@example.com", [Note(note_type="LIST")])

            body = load_note_body_cache(tmp, "user@example.com", "note-1")

        self.assertIsNone(body)

    def test_body_cache_is_stored_outside_metadata_cache_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_cache(tmp, "user@example.com", [Note()])

            body_files = list((Path(tmp) / "note_bodies").glob("*.bin"))

        self.assertEqual(len(body_files), 1)


if __name__ == "__main__":
    unittest.main()
