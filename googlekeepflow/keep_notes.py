import gkeepapi

from googlekeepflow.keep_cache import media_counts_for_note, note_display_text, note_sort_key
from googlekeepflow.keep_labels import label_names_for_note, matches_terms


def create_keep_client(email, master_token, logger=None):
    if logger:
        logger.info("Authenticating Google Keep client...")
    keep = gkeepapi.Keep()
    keep.authenticate(email, master_token, sync=False)
    return keep


def sync_keep_client(keep, logger=None):
    if logger:
        logger.info("Syncing Google Keep client...")
    keep.sync()
    if logger:
        logger.info("Loaded notes successfully")


def recent_notes(email, master_token, max_notes=10, logger=None, archived=False):
    if logger:
        logger.info("Listing archived notes..." if archived else "Listing notes...")

    keep = create_keep_client(email, master_token, logger)
    sync_keep_client(keep, logger)
    return recent_notes_from_keep(keep, max_notes=max_notes, archived=archived)


def note_matches_search(note, search_text="", labels_by_id=None):
    labels = " ".join(label_names_for_note(note, labels_by_id))
    media = " ".join(key for key, count in media_counts_for_note(note).items() if count)
    haystack = f"{getattr(note, 'title', '')}\n{getattr(note, 'text', '')}\n{media}\n{labels}"
    return matches_terms(haystack, search_text)


def recent_notes_from_keep(keep, max_notes=10, archived=False, search_text="", labels_by_id=None):
    notes = [
        note
        for note in keep.all()
        if not note.trashed and bool(note.archived) == bool(archived)
        and note_matches_search(note, search_text, labels_by_id)
    ]
    return sorted(notes, key=note_sort_key)[:max_notes]


def note_result_text(note):
    return note_display_text(note.title, note.text, media_counts_for_note(note))

