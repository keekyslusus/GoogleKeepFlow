SETUP_COMMANDS = ("setup", "login", "auth")
ADD_COMMANDS = ("add", "new")
LIST_COMMANDS = ("list",)
EDIT_COMMANDS = ("edit",)
ARCHIVE_COMMANDS = ("archive",)
PIN_COMMANDS = ("pin", "pinned")
TODO_COMMANDS = ("todo", "checklist")
REMINDER_COMMANDS = ("remind", "reminder")


def setup_email_from_query(query_text, default_email=""):
    stripped = query_text.strip()
    first_word = stripped.lower().split(" ", 1)[0] if stripped else ""
    if first_word not in SETUP_COMMANDS:
        return None
    return stripped.split(" ", 1)[1].strip() if " " in stripped else default_email


MIN_MAX_NOTES = 1
MAX_MAX_NOTES = 1000


def parse_max_notes(value, default=20):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(MAX_MAX_NOTES, max(MIN_MAX_NOTES, parsed))


def split_command_query(query_text):
    stripped = str(query_text or "").strip()
    if not stripped:
        return "", ""
    command, _, rest = stripped.partition(" ")
    return command.lower(), rest.strip()

