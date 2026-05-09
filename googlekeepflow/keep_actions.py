from googlekeepflow.keep_worker_launcher import (
    start_archive_worker,
    start_external_edit_worker,
    start_note_worker,
    start_pin_worker,
    start_trash_worker,
)


def parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def reset_launcher_query(plugin):
    change_query = getattr(plugin, "change_query", None)
    if not callable(change_query):
        return

    try:
        current_keyword = getattr(plugin, "current_keyword", None)
        home_query = current_keyword() if callable(current_keyword) else "keep"
        change_query(str(home_query or "keep").strip() or "keep", True)
    except Exception as exc:
        logger = getattr(plugin, "logger", None)
        if logger:
            logger.debug("Failed to reset launcher query: %s: %s", type(exc).__name__, exc)


def start_authenticated_worker_action(plugin, worker_label, worker_action, success_message):
    email, master_token = plugin.get_auth()
    if not email or not master_token:
        return "GoogleKeepFlow setup required"

    show_notifications = parse_bool(plugin.settings.get('show_notifications', True))
    try:
        worker_action(email, master_token, show_notifications, plugin.secure_settings_dir())
        reset_launcher_query(plugin)
        return success_message
    except Exception as e:
        plugin.logger.error(f"Failed to start {worker_label}: {type(e).__name__}: {e}")
        return f"Failed: {str(e)}"


def add_note(plugin, plugin_dir, text, pinned=False, archived=False, list_note=False, reminder_at_iso=""):
    pinned = parse_bool(pinned)
    archived = parse_bool(archived)
    list_note = parse_bool(list_note)
    plugin.logger.info("Adding note...")

    def start(email, master_token, show_notifications, settings_dir):
        start_note_worker(
            plugin_dir,
            email,
            text,
            pinned,
            archived,
            list_note,
            reminder_at_iso,
            show_notifications,
            plugin.logger,
            settings_dir,
        )

    return start_authenticated_worker_action(
        plugin,
        "sync worker",
        start,
        "Note queued for Google Keep sync...",
    )


def set_note_archived(plugin, plugin_dir, note_id, archived):
    archived = parse_bool(archived)

    def start(email, master_token, show_notifications, settings_dir):
        start_archive_worker(
            plugin_dir,
            email,
            str(note_id),
            archived,
            show_notifications,
            plugin.logger,
            settings_dir,
        )

    return start_authenticated_worker_action(
        plugin,
        "archive worker",
        start,
        "Moving note to archive..." if archived else "Restoring note from archive...",
    )


def set_note_pinned(plugin, plugin_dir, note_id, pinned):
    pinned = parse_bool(pinned)

    def start(email, master_token, show_notifications, settings_dir):
        start_pin_worker(
            plugin_dir,
            email,
            str(note_id),
            pinned,
            show_notifications,
            plugin.logger,
            settings_dir,
        )

    return start_authenticated_worker_action(
        plugin,
        "pin worker",
        start,
        "Pinning note..." if pinned else "Unpinning note...",
    )


def move_note_to_trash(plugin, plugin_dir, note_id):
    def start(email, master_token, show_notifications, settings_dir):
        start_trash_worker(
            plugin_dir,
            email,
            str(note_id),
            show_notifications,
            plugin.logger,
            settings_dir,
        )

    return start_authenticated_worker_action(
        plugin,
        "trash worker",
        start,
        "Moving note to trash...",
    )


def edit_note_external(plugin, plugin_dir, note_id):
    def start(email, master_token, show_notifications, settings_dir):
        start_external_edit_worker(
            plugin_dir,
            email,
            str(note_id),
            show_notifications,
            plugin.logger,
            settings_dir,
        )

    return start_authenticated_worker_action(
        plugin,
        "external edit worker",
        start,
        "Opening note in your text editor...",
    )
