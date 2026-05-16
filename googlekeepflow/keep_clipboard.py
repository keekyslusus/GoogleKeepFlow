import base64
import hashlib
import json
import sys
import ctypes
import time
from io import BytesIO
from pathlib import Path

from googlekeepflow.keep_auth_store import unprotect_bytes


CF_BITMAP = 2
CF_DIB = 8
CF_HDROP = 15
CF_DIBV5 = 17
IMAGE_MARKER = "[image]"
PENDING_IMAGE_FILE = "pending_clipboard_image.bin"
CLIPBOARD_IMAGE_EXTENSIONS = {".bmp", ".gif", ".jfif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
CLIPBOARD_READ_ATTEMPTS = 3
CLIPBOARD_READ_RETRY_SECONDS = 0.05
RAW_CLIPBOARD_IMAGE_FORMATS = (CF_DIBV5, CF_DIB, CF_BITMAP)


def has_clipboard_image():
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        if has_clipboard_image_format(user32):
            return True
        if user32.IsClipboardFormatAvailable(CF_HDROP):
            return has_clipboard_image_file_list()
        return False
    except Exception:
        return False


def has_clipboard_image_format(user32):
    return any(user32.IsClipboardFormatAvailable(fmt) for fmt in RAW_CLIPBOARD_IMAGE_FORMATS)


def has_clipboard_image_file_list(image_grab=None):
    if image_grab is None:
        from PIL import ImageGrab
        image_grab = ImageGrab

    grabbed = grab_clipboard_with_retry(image_grab)
    return isinstance(grabbed, list) and first_image_file_path(grabbed) is not None


def read_clipboard_png():
    """Return clipboard image as a PNG payload dict.

    Pillow reads the clipboard in-process and returns PNG bytes without
    launching a helper process.
    """
    if sys.platform != "win32":
        raise ValueError("Clipboard images are only supported on Windows")

    data, width, height = read_clipboard_png_bytes()
    return {
        "mime_type": "image/png",
        "png_base64": base64.b64encode(data).decode("ascii"),
        "byte_size": len(data),
        "width": width,
        "height": height,
    }


def read_clipboard_png_bytes(thumbnail_size=0):
    return export_clipboard_png_pillow(thumbnail_size=thumbnail_size)


def save_clipboard_preview(settings_dir, size=128):
    if sys.platform != "win32":
        return ""

    settings_dir = Path(settings_dir)
    settings_dir.mkdir(parents=True, exist_ok=True)
    data, _, _ = read_clipboard_png_bytes(thumbnail_size=size)
    digest = hashlib.sha256(data).hexdigest()[:16]
    preview_path = settings_dir / f"clipboard_image_preview_{digest}.png"
    if not preview_path.exists():
        preview_path.write_bytes(data)
    cleanup_old_previews(settings_dir, preview_path)
    return str(preview_path)


def pending_image_path(settings_dir):
    return Path(settings_dir) / PENDING_IMAGE_FILE


def save_pending_clipboard_image(settings_dir, image_payload):
    path = pending_image_path(settings_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(image_payload, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)


def load_pending_clipboard_image(settings_dir):
    path = pending_image_path(settings_dir)
    if not path.exists():
        return {}
    data = path.read_bytes()
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError:
        raw = unprotect_bytes(data).decode("utf-8")
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def has_pending_clipboard_image(settings_dir):
    payload = load_pending_clipboard_image(settings_dir)
    return bool(payload.get("png_base64"))


def clear_pending_clipboard_image(settings_dir):
    try:
        pending_image_path(settings_dir).unlink()
    except OSError:
        pass


def is_image_note_query(query_text):
    return str(query_text or "").strip().lower().startswith(IMAGE_MARKER)


def image_note_text(query_text):
    text = str(query_text or "").strip()
    if text.lower().startswith(IMAGE_MARKER):
        return text[len(IMAGE_MARKER):].strip()
    return text


def cleanup_old_previews(settings_dir, keep_path):
    keep_path = Path(keep_path)
    for path in Path(settings_dir).glob("clipboard_image_preview_*.png"):
        if path == keep_path:
            continue
        try:
            path.unlink()
        except OSError:
            pass


def export_clipboard_png(path, thumbnail_size=0):
    data, width, height = read_clipboard_png_bytes(thumbnail_size=thumbnail_size)
    Path(path).write_bytes(data)
    return data, width, height


def export_clipboard_png_pillow(thumbnail_size=0):
    from PIL import Image, ImageGrab

    grabbed = grab_clipboard_with_retry(ImageGrab)
    if isinstance(grabbed, list):
        return export_image_file_list_png(grabbed, thumbnail_size=thumbnail_size)
    if not isinstance(grabbed, Image.Image):
        raise ValueError("Clipboard does not contain an image")

    return encode_pillow_image_png(grabbed, thumbnail_size=thumbnail_size)


def grab_clipboard_with_retry(image_grab):
    last_error = None
    for attempt in range(CLIPBOARD_READ_ATTEMPTS):
        try:
            grabbed = image_grab.grabclipboard()
            if grabbed is not None:
                return grabbed
        except OSError as exc:
            last_error = exc

        if attempt < CLIPBOARD_READ_ATTEMPTS - 1:
            time.sleep(CLIPBOARD_READ_RETRY_SECONDS)

    if last_error:
        raise last_error
    return None


def export_image_file_list_png(paths, thumbnail_size=0):
    from PIL import Image

    image_path = first_image_file_path(paths)
    if not image_path:
        raise ValueError("Clipboard does not contain an image")

    with Image.open(image_path) as image:
        return encode_pillow_image_png(image, thumbnail_size=thumbnail_size)


def first_image_file_path(paths):
    for candidate in paths or []:
        path = Path(str(candidate or ""))
        if path.is_file() and path.suffix.lower() in CLIPBOARD_IMAGE_EXTENSIONS:
            return path
    return None


def encode_pillow_image_png(grabbed, thumbnail_size=0):
    width, height = grabbed.size
    image = normalize_pillow_image(grabbed)
    try:
        size = max(0, int(thumbnail_size or 0))
        if size > 0:
            thumbnail = thumbnail_pillow_image(image, size)
            if image is not grabbed:
                image.close()
            image = thumbnail

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        data = buffer.getvalue()
        if not data:
            raise ValueError("Clipboard image export was empty")
        return data, width, height
    finally:
        if image is not grabbed:
            image.close()
        grabbed.close()


def normalize_pillow_image(image):
    if image.mode in ("RGB", "RGBA"):
        return image
    return image.convert("RGBA")


def thumbnail_pillow_image(image, size):
    from PIL import Image

    resampling = getattr(Image, "Resampling", Image).LANCZOS
    thumbnail = image.copy()
    thumbnail.thumbnail((size, size), resampling)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = int((size - thumbnail.width) / 2)
    y = int((size - thumbnail.height) / 2)
    mask = thumbnail.getchannel("A") if thumbnail.mode == "RGBA" else None
    canvas.paste(thumbnail, (x, y), mask)
    thumbnail.close()
    return canvas
