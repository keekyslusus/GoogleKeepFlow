from googlekeepflow.keep_labels import append_label_suffix, label_names_for_note, label_suffix, parse_note_labels
from googlekeepflow.keep_links import extract_links
from googlekeepflow.keep_notes import note_result_text


ADD_TO_KEEP_TEXT = "Add to Google Keep"
EDIT_IN_TEXT_EDITOR_TEXT = "Edit in text editor"


def checklist_preview(text):
    items = [item.strip() for item in str(text or "").split(";") if item.strip()]
    if not items:
        return str(text or "").strip()
    return " ".join(f"\u25a1 {item}" for item in items)


def note_preview_and_labels(text, list_note=False):
    note_text, labels = parse_note_labels(text)
    if not note_text and str(text or "").strip():
        note_text = str(text or "").strip()
    preview = checklist_preview(note_text) if list_note else note_text
    return preview, labels


def keep_action_subtitle(action, labels=None, prefix=""):
    labels = labels or []
    suffix = label_suffix(labels)
    if suffix:
        label_word = "label" if len(labels) == 1 else "labels"
        action = f"{action} with {label_word} {suffix}"
    if prefix:
        return f"{prefix} \u2022 {action}"
    return action


def add_to_keep_subtitle(labels=None, prefix=""):
    return keep_action_subtitle(ADD_TO_KEEP_TEXT, labels, prefix)


def first_media_type(media=None):
    media = media or {}
    for media_type in ("image", "audio", "drawing"):
        if int(media.get(media_type, 0) or 0) > 0:
            return media_type
    return ""


def media_icon(icons, media=None):
    media_type = first_media_type(media)
    if not media_type:
        return ""
    return icons.get(f"contain_{media_type}", "")


def note_icon(icons, archived=False, pinned=False, checklist=False, media=None):
    if checklist:
        return icons["checklist"]
    icon = media_icon(icons, media)
    if icon:
        return icon
    if archived:
        return icons["archive"]
    if pinned:
        return icons["pin"]
    return icons["list"]


def note_result_action(plugin, note_id, edit_mode=False):
    if edit_mode:
        return plugin.edit_note_external, [note_id]
    return plugin.open_note, [note_id]


def note_result_icon(icons, archived=False, pinned=False, checklist=False, edit_mode=False, media=None):
    if edit_mode and not pinned and not checklist:
        return icons["edit_note"]
    return note_icon(icons, archived, pinned, checklist, media)


def note_result_subtitle(subtitle, labels=None, edit_mode=False):
    subtitle = str(subtitle or "")
    if edit_mode and subtitle == "Open in Google Keep":
        subtitle = EDIT_IN_TEXT_EDITOR_TEXT
    return append_label_suffix(subtitle, labels or [])


def add_empty_notes_result(plugin, icons, archived=False, search_text=""):
    icon = icons.get("warning", icons["archive"] if archived else icons["list"])
    if str(search_text or "").strip():
        plugin.add_item(
            title="No archived notes found" if archived else "No notes found",
            subtitle=f"No matches for: {search_text}",
            icon=icon,
        )
        return

    plugin.add_item(
        title="No archived notes found" if archived else "No notes found",
        subtitle="Archived notes will appear here" if archived else "Create your first note!",
        icon=icon,
    )


def render_cached_notes(plugin, icons, notes, archived=False, search_text="", edit_mode=False):
    if not notes:
        add_empty_notes_result(plugin, icons, archived, search_text)
        return

    for note in notes:
        pinned = bool(note.get("pinned"))
        is_checklist = note.get("type") == "LIST"
        media = note.get("media") if isinstance(note.get("media"), dict) else {}
        labels = note.get("labels", []) if isinstance(note.get("labels"), list) else []
        method, parameters = note_result_action(plugin, note.get("id", ""), edit_mode)
        plugin.add_item(
            title=note.get("title", ""),
            subtitle=note_result_subtitle(note.get("subtitle", ""), labels, edit_mode),
            icon=note_result_icon(icons, archived, pinned, is_checklist, edit_mode, media),
            method=method,
            parameters=parameters,
            context={
                "type": "keep_note",
                "note_id": note.get("id", ""),
                "archived": bool(note.get("archived")),
                "pinned": pinned,
                "checklist": is_checklist,
                "edit_mode": bool(edit_mode),
                "links": note.get("links", []) if isinstance(note.get("links"), list) else [],
                "media": media,
            },
        )


def render_live_notes(plugin, icons, notes, archived=False, search_text="", labels_by_id=None, edit_mode=False):
    if not notes:
        add_empty_notes_result(plugin, icons, archived, search_text)
        return

    for note in notes:
        title, subtitle = note_result_text(note)
        labels = label_names_for_note(note, labels_by_id)
        links = extract_links(f"{note.title}\n{note.text}")
        pinned = bool(note.pinned)
        is_checklist = str(getattr(getattr(note, "type", ""), "value", getattr(note, "type", ""))) == "LIST"
        media = {
            "image": len(getattr(note, "images", []) or []),
            "audio": len(getattr(note, "audio", []) or []),
            "drawing": len(getattr(note, "drawings", []) or []),
        }
        method, parameters = note_result_action(plugin, note.id, edit_mode)
        plugin.add_item(
            title=title,
            subtitle=note_result_subtitle(subtitle, labels, edit_mode),
            icon=note_result_icon(icons, archived, pinned, is_checklist, edit_mode, media),
            method=method,
            parameters=parameters,
            context={
                "type": "keep_note",
                "note_id": note.id,
                "archived": bool(note.archived),
                "pinned": pinned,
                "checklist": is_checklist,
                "edit_mode": bool(edit_mode),
                "links": links,
                "media": media,
            },
        )
