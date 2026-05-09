import re


LABEL_PATTERN = re.compile(r"(?<![\w/\\])#([\w][\w-]{0,49})", re.UNICODE)
ESCAPED_HASH_MARKER = "\0GOOGLEKEEPFLOW_HASH\0"


def parse_note_labels(text):
    text = str(text or "")
    protected_text = text.replace(r"\#", ESCAPED_HASH_MARKER)
    labels = []
    seen = set()

    def replace_label(match):
        label = match.group(1).strip()
        label_key = label.lower()
        if label_key and label_key not in seen:
            labels.append(label)
            seen.add(label_key)
        return " "

    note_text = LABEL_PATTERN.sub(replace_label, protected_text)
    note_text = note_text.replace(ESCAPED_HASH_MARKER, "#")
    note_text = re.sub(r"[ \t]{2,}", " ", note_text)
    note_text = re.sub(r" *\n *", "\n", note_text).strip()
    return note_text, labels


def label_names_for_note(note, labels_by_id=None):
    labels_by_id = labels_by_id or {}
    note_labels = getattr(note, "labels", None)
    if note_labels is None:
        return []

    names = []
    for label_id in getattr(note_labels, "_labels", {}) or {}:
        name = labels_by_id.get(label_id)
        if name:
            names.append(name)
    return names


def label_suffix(labels, max_labels=3):
    labels = [str(label or "").strip() for label in labels or [] if str(label or "").strip()]
    if not labels:
        return ""

    shown = labels[:max_labels]
    suffix = " ".join(f"#{label}" for label in shown)
    if len(labels) > max_labels:
        suffix += f" +{len(labels) - max_labels}"
    return suffix


def append_label_suffix(subtitle, labels):
    suffix = label_suffix(labels)
    if not suffix:
        return subtitle
    return f"{subtitle} | {suffix}" if subtitle else suffix


def search_terms(search_text):
    terms = []
    for term in str(search_text or "").strip().lower().split():
        if term.startswith("#") and len(term) > 1:
            term = term[1:]
        if term:
            terms.append(term)
    return terms


def matches_terms(haystack, search_text):
    terms = search_terms(search_text)
    if not terms:
        return True
    haystack = str(haystack or "").lower()
    return all(term in haystack for term in terms)
