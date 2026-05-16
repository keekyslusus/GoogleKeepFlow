import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from googlekeepflow.keep_clipboard import (
    CF_HDROP,
    CF_DIB,
    first_image_file_path,
    grab_clipboard_with_retry,
    has_clipboard_image_format,
    has_clipboard_image_file_list,
    load_pending_clipboard_image,
    pending_image_path,
    read_clipboard_png,
    read_clipboard_png_bytes,
    save_pending_clipboard_image,
)
from googlekeepflow.worker_sync import load_job


class ImagePayloadStorageTests(unittest.TestCase):
    def test_pending_clipboard_image_is_stored_as_plain_json(self):
        payload = {
            "mime_type": "image/png",
            "png_base64": "abc",
            "byte_size": 3,
            "width": 10,
            "height": 20,
        }

        with tempfile.TemporaryDirectory() as tmp:
            save_pending_clipboard_image(tmp, payload)

            raw = pending_image_path(tmp).read_text(encoding="utf-8")

            self.assertEqual(json.loads(raw), payload)
            self.assertEqual(load_pending_clipboard_image(tmp), payload)

    def test_image_job_can_be_loaded_from_plain_json(self):
        job = {
            "email": "user@example.com",
            "type": "image",
            "png_base64": "abc",
        }

        with tempfile.TemporaryDirectory() as tmp:
            job_path = Path(tmp) / "google_keep_note_job_test.bin"
            job_path.write_text(json.dumps(job), encoding="utf-8")

            self.assertEqual(load_job(job_path), job)

    def test_read_clipboard_png_uses_pillow_bytes(self):
        with patch("sys.platform", "win32"):
            with patch("googlekeepflow.keep_clipboard.export_clipboard_png_pillow", return_value=(b"png", 10, 20)):
                payload = read_clipboard_png()

        self.assertEqual(payload["mime_type"], "image/png")
        self.assertEqual(payload["png_base64"], "cG5n")
        self.assertEqual(payload["byte_size"], 3)
        self.assertEqual(payload["width"], 10)
        self.assertEqual(payload["height"], 20)

    def test_read_clipboard_png_bytes_uses_pillow_directly(self):
        with patch("googlekeepflow.keep_clipboard.export_clipboard_png_pillow", return_value=(b"png", 10, 20)) as fast_path:
            data, width, height = read_clipboard_png_bytes()

        self.assertEqual((data, width, height), (b"png", 10, 20))
        self.assertEqual(fast_path.call_count, 1)

    def test_has_clipboard_image_format_accepts_raw_image_formats(self):
        class FakeUser32:
            @staticmethod
            def IsClipboardFormatAvailable(fmt):
                return fmt == CF_DIB

        self.assertTrue(has_clipboard_image_format(FakeUser32()))

    def test_has_clipboard_image_format_ignores_file_drop_without_inspection(self):
        class FakeUser32:
            @staticmethod
            def IsClipboardFormatAvailable(fmt):
                return fmt == CF_HDROP

        self.assertFalse(has_clipboard_image_format(FakeUser32()))

    def test_has_clipboard_image_file_list_accepts_copied_image_file(self):
        class FakeImageGrab:
            clipboard = []

            @classmethod
            def grabclipboard(cls):
                return cls.clipboard

        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "photo.png"
            image_path.write_bytes(b"fake")
            FakeImageGrab.clipboard = [image_path]

            self.assertTrue(has_clipboard_image_file_list(FakeImageGrab))

    def test_first_image_file_path_uses_first_supported_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            text_path = Path(tmp) / "notes.txt"
            image_path = Path(tmp) / "photo.PNG"
            text_path.write_text("not image", encoding="utf-8")
            image_path.write_bytes(b"fake")

            self.assertEqual(first_image_file_path([text_path, image_path]), image_path)

    def test_grab_clipboard_with_retry_retries_empty_clipboard(self):
        class FakeImageGrab:
            calls = 0

            @classmethod
            def grabclipboard(cls):
                cls.calls += 1
                return "image" if cls.calls == 2 else None

        with patch("googlekeepflow.keep_clipboard.time.sleep") as sleep:
            grabbed = grab_clipboard_with_retry(FakeImageGrab)

        self.assertEqual(grabbed, "image")
        self.assertEqual(FakeImageGrab.calls, 2)
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
