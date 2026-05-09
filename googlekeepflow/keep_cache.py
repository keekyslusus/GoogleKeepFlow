import json
import re
import time
from pathlib import Path

from googlekeepflow.keep_auth_store import protect_bytes, unprotect_bytes
from googlekeepflow.keep_labels import label_names_for_note, matches_terms
from googlekeepflow.keep_links import extract_links


CACHE_FILE_NAME = "cache_notes.bin"
CACHE_VERSION = 4
NOTE_BODY_DIR_NAME = "note_bodies"
NOTE_BODY_CACHE_VERSION = 1
SEARCH_TEXT_LIMIT = 4000
PREVIEW_LIMIT = 100
URL_SCHEME_PATTERN = re.compile(r"\bhttps?://", re.IGNORECASE)
_MEMORY_CACHE = {}
OPEN_IN_KEEP_TEXT = "Open in Google Keep"


def cache_path(settings_dir, create=False):
    base_dir = Path(settings_dir)
    if create:
        base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / CACHE_FILE_NAME


def safe_note_body_key(note_id):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(note_id or "").strip())[:120] or "note"


def note_body_cache_path(settings_dir, note_id, create=False):
    base_dir = Path(settings_dir) / NOTE_BODY_DIR_NAME
    if create:
        base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"{safe_note_body_key(note_id)}.bin"


def note_type_value(note):
    value = getattr(note, "type", "")
    return str(getattr(value, "value", value) or "")


def cache_file_key(path):
    return str(Path(path))


def cache_file_signature(path):
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def memory_cache_get(path, signature):
    entry = _MEMORY_CACHE.get(cache_file_key(path))
    if entry and entry.get("signature") == signature:
        return entry.get("data")
    return None


def memory_cache_set(path, signature, data):
    if signature is None or data is None:
        _MEMORY_CACHE.pop(cache_file_key(path), None)
        return
    _MEMORY_CACHE[cache_file_key(path)] = {
        "signature": signature,
        "data": data,
    }


def preview_lines(text):
    return [display_text(line.strip()) for line in str(text or "").splitlines() if line.strip()]


def truncate_preview(text, limit=PREVIEW_LIMIT):
    text = str(text or "").strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def display_text(text):
    return URL_SCHEME_PATTERN.sub("", str(text or ""))


def note_display_text(title, text):
    title = str(title or "")
    text = str(text or "")

    if title:
        clean_title = display_text(title.replace("\n", " ").strip())
        subtitle = truncate_preview(" | ".join(preview_lines(text)))
        return clean_title, subtitle or OPEN_IN_KEEP_TEXT

    lines = preview_lines(text)
    first_line = lines[0] if lines else ""
    clean_title = first_line[:50].strip()
    if len(first_line) > 50:
        clean_title += "..."

    if len(lines) <= 1:
        return clean_title, OPEN_IN_KEEP_TEXT

    subtitle = truncate_preview(" | ".join(lines[1:]))
    return clean_title, subtitle or OPEN_IN_KEEP_TEXT


def log_cache_event(logger, level, message, *args):
    if logger:
        getattr(logger, level)(message, *args)


def note_updated_value(note, logger=None):
    try:
        return note.timestamps.updated.timestamp()
    except Exception as exc:
        log_cache_event(logger, "debug", "Failed to read note updated timestamp: %s: %s", type(exc).__name__, exc)
        return 0


def cache_item_sort_key(item):
    try:
        updated = float(item.get("updated", 0))
    except (TypeError, ValueError):
        updated = 0
    return (not bool(item.get("pinned")), -updated)


def note_sort_key(note):
    return (not bool(getattr(note, "pinned", False)), -note_updated_value(note))


def label_name_map(labels):
    return {str(getattr(label, "id", "") or ""): str(getattr(label, "name", "") or "") for label in labels or []}


def note_to_cache_item(note, labels_by_id=None, logger=None):
    title, subtitle = note_display_text(getattr(note, "title", ""), getattr(note, "text", ""))
    text = str(getattr(note, "text", "") or "")
    note_title = str(getattr(note, "title", "") or "")
    label_names = label_names_for_note(note, labels_by_id)
    search_text = f"{note_title}\n{text}".strip()
    return {
        "id": str(getattr(note, "id", "") or ""),
        "type": str(getattr(getattr(note, "type", ""), "value", getattr(note, "type", "")) or ""),
        "title": title,
        "subtitle": subtitle,
        "labels": label_names,
        "links": extract_links(f"{note_title}\n{text}"),
        "archived": bool(getattr(note, "archived", False)),
        "pinned": bool(getattr(note, "pinned", False)),
        "search_text": f"{search_text}\n{' '.join(label_names)}".strip()[:SEARCH_TEXT_LIMIT],
        "updated": note_updated_value(note, logger),
    }


def serialize_notes(notes, labels=None, logger=None):
    items = []
    skipped = 0
    labels_by_id = label_name_map(labels)
    for note in notes:
        try:
            if getattr(note, "trashed", False):
                continue
            item = note_to_cache_item(note, labels_by_id, logger)
            if item["id"]:
                items.append(item)
            else:
                skipped += 1
        except Exception as exc:
            skipped += 1
            log_cache_event(logger, "debug", "Failed to serialize cache note: %s: %s", type(exc).__name__, exc)
            continue
    if skipped:
        log_cache_event(logger, "warning", "Skipped %s note(s) while serializing cache", skipped)
    return sorted(items, key=cache_item_sort_key)


def load_cache(settings_dir, logger=None):
    path = cache_path(settings_dir)
    signature = cache_file_signature(path)
    if signature is None:
        memory_cache_set(path, None, None)
        log_cache_event(logger, "debug", "Notes cache miss: %s does not exist", path)
        return None

    cached_data = memory_cache_get(path, signature)
    if cached_data is not None:
        log_cache_event(logger, "debug", "Notes cache memory hit: %s", path)
        return cached_data

    try:
        raw = unprotect_bytes(path.read_bytes()).decode("utf-8")
        data = json.loads(raw)
    except Exception as exc:
        memory_cache_set(path, None, None)
        log_cache_event(logger, "warning", "Failed to load notes cache %s: %s: %s", path, type(exc).__name__, exc)
        return None
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        memory_cache_set(path, None, None)
        log_cache_event(
            logger,
            "warning",
            "Ignoring notes cache %s: unsupported or invalid version %r",
            path,
            data.get("version") if isinstance(data, dict) else None,
        )
        return None
    memory_cache_set(path, signature, data)
    return data


def save_cache(settings_dir, email, notes, logger=None, labels=None):
    note_list = list(notes or [])
    data = {
        "version": CACHE_VERSION,
        "email": str(email or "").strip().lower(),
        "cached_at": time.time(),
        "notes": serialize_notes(note_list, labels, logger),
    }
    path = cache_path(settings_dir, create=True)
    tmp_path = path.with_suffix(".tmp")
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    tmp_path.write_bytes(protect_bytes(raw))
    tmp_path.replace(path)
    memory_cache_set(path, cache_file_signature(path), data)
    save_note_body_caches(settings_dir, email, note_list, logger)
    return data


def note_body_cache_item(email, note, logger=None):
    note_id = str(getattr(note, "id", "") or "")
    if not note_id or getattr(note, "trashed", False) or note_type_value(note) == "LIST":
        return None
    return {
        "version": NOTE_BODY_CACHE_VERSION,
        "email": str(email or "").strip().lower(),
        "id": note_id,
        "type": note_type_value(note),
        "title": str(getattr(note, "title", "") or ""),
        "text": str(getattr(note, "text", "") or ""),
        "updated": note_updated_value(note, logger),
        "cached_at": time.time(),
    }


def save_note_body_cache(settings_dir, email, note, logger=None):
    item = note_body_cache_item(email, note, logger)
    if not item:
        return None
    path = note_body_cache_path(settings_dir, item["id"], create=True)
    tmp_path = path.with_suffix(".tmp")
    raw = json.dumps(item, ensure_ascii=False).encode("utf-8")
    tmp_path.write_bytes(protect_bytes(raw))
    tmp_path.replace(path)
    return item


def save_note_body_caches(settings_dir, email, notes, logger=None):
    saved = 0
    for note in notes or []:
        try:
            if save_note_body_cache(settings_dir, email, note, logger):
                saved += 1
        except Exception as exc:
            log_cache_event(logger, "debug", "Failed to save note body cache: %s: %s", type(exc).__name__, exc)
    if saved:
        log_cache_event(logger, "debug", "Saved %s note body cache item(s)", saved)
    return saved


def load_note_body_cache(settings_dir, email, note_id, logger=None):
    path = note_body_cache_path(settings_dir, note_id)
    if not path.exists():
        return None
    try:
        raw = unprotect_bytes(path.read_bytes()).decode("utf-8")
        data = json.loads(raw)
    except Exception as exc:
        log_cache_event(logger, "warning", "Failed to load note body cache %s: %s: %s", path, type(exc).__name__, exc)
        return None
    if not isinstance(data, dict) or data.get("version") != NOTE_BODY_CACHE_VERSION:
        log_cache_event(logger, "warning", "Ignoring invalid note body cache %s", path)
        return None
    if str(data.get("email", "")).strip().lower() != str(email or "").strip().lower():
        return None
    if str(data.get("id", "") or "") != str(note_id or ""):
        return None
    if str(data.get("type", "") or "") == "LIST":
        return None
    return data


def matches_search_text(note, search_text):
    haystack = "\n".join(
        str(note.get(field, "") or "")
        for field in ("title", "subtitle", "search_text")
    )
    return matches_terms(haystack, search_text)


def cached_notes(settings_dir, email, archived, max_notes, search_text="", logger=None):
    data = load_cache(settings_dir, logger)
    if not data:
        return None
    return notes_from_cache_data(data, email, archived, max_notes, search_text, logger)


def notes_from_cache_data(data, email, archived, max_notes, search_text="", logger=None):
    if str(data.get("email", "")).strip().lower() != str(email or "").strip().lower():
        log_cache_event(logger, "debug", "Notes cache miss: cached email does not match active email")
        return None

    notes = data.get("notes", [])
    if not isinstance(notes, list):
        log_cache_event(logger, "warning", "Ignoring notes cache: notes payload is not a list")
        return None

    filtered = [
        note
        for note in notes
        if isinstance(note, dict) and bool(note.get("archived")) == bool(archived)
        and matches_search_text(note, search_text)
    ]
    return filtered[:max_notes]


def cache_data_age_seconds(data, logger=None):
    if not data:
        return None
    try:
        return max(0, int(time.time() - float(data.get("cached_at", 0))))
    except Exception as exc:
        log_cache_event(logger, "warning", "Failed to read notes cache age: %s: %s", type(exc).__name__, exc)
        return None


def cache_age_seconds(settings_dir, logger=None):
    data = load_cache(settings_dir, logger)
    return cache_data_age_seconds(data, logger)

