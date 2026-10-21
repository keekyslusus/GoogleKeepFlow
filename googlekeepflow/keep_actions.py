from googlekeepflow.keep_worker_launcher import (
    start_archive_worker,
    start_external_edit_worker,
    start_image_worker,
    start_note_worker,
    start_pin_worker,
    start_trash_worker,
    queue_linked_file_job,
)
from googlekeepflow.keep_file_links import (
    ACTION_LINK,
    ACTION_RESOLVE,
    ACTION_UNLINK,
    DIRECTION_PULL,
    DIRECTION_PUSH,
    linked_file_for_note,
    load_registry,
    open_file,
)
from googlekeepflow.keep_clipboard import (
    IMAGE_MARKER,
    clear_pending_clipboard_image,
    load_pending_clipboard_image,
    read_clipboard_png,
    save_pending_clipboard_image,
)
from googlekeepflow.keep_values import parse_bool


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


def add_clipboard_image(plugin, plugin_dir):
    return add_pending_image_note(plugin, plugin_dir, "")


def send_clipboard_image_now(plugin, plugin_dir):
    plugin.logger.info("Sending clipboard image note...")
    email, master_token = plugin.get_auth()
    if not email or not master_token:
        return "GoogleKeepFlow setup required"

    try:
        image_payload = read_clipboard_png()
    except Exception as exc:
        plugin.logger.error("Failed to read clipboard image: %s: %s", type(exc).__name__, exc)
        return f"Failed: {str(exc)}"

    show_notifications = parse_bool(plugin.settings.get('show_notifications', True))
    try:
        start_image_worker(
            plugin_dir,
            email,
            image_payload,
            "",
            show_notifications,
            plugin.logger,
            plugin.secure_settings_dir(),
        )
        reset_launcher_query(plugin)
        return "Image queued for Google Keep sync..."
    except Exception as exc:
        plugin.logger.error("Failed to start image sync worker: %s: %s", type(exc).__name__, exc)
        return f"Failed: {str(exc)}"


def begin_clipboard_image_note(plugin, plugin_dir):
    plugin.logger.info("Preparing clipboard image note...")
    email, master_token = plugin.get_auth()
    if not email or not master_token:
        return "GoogleKeepFlow setup required"

    try:
        image_payload = read_clipboard_png()
    except Exception as exc:
        plugin.logger.error("Failed to read clipboard image: %s: %s", type(exc).__name__, exc)
        return f"Failed: {str(exc)}"

    try:
        image_payload["preview_icon"] = getattr(plugin, "clipboard_image_icon", lambda: "")() or ""
        save_pending_clipboard_image(plugin.secure_settings_dir(), image_payload)
        change_query = getattr(plugin, "change_query", None)
        if callable(change_query):
            change_query(f"{plugin.current_keyword()} {IMAGE_MARKER} ", True)
        return "Clipboard image attached. Type note text..."
    except Exception as exc:
        plugin.logger.error("Failed to prepare clipboard image note: %s: %s", type(exc).__name__, exc)
        return f"Failed: {str(exc)}"


def add_pending_image_note(plugin, plugin_dir, text):
    plugin.logger.info("Adding pending clipboard image note...")
    try:
        image_payload = load_pending_clipboard_image(plugin.secure_settings_dir())
    except Exception as exc:
        plugin.logger.error("Failed to load pending clipboard image: %s: %s", type(exc).__name__, exc)
        return f"Failed: {str(exc)}"
    if not image_payload:
        return "No pending clipboard image"

    def start(email, master_token, show_notifications, settings_dir):
        start_image_worker(
            plugin_dir,
            email,
            image_payload,
            text,
            show_notifications,
            plugin.logger,
            settings_dir,
        )
        clear_pending_clipboard_image(settings_dir)

    return start_authenticated_worker_action(
        plugin,
        "image sync worker",
        start,
        "Image queued for Google Keep sync...",
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
    # A synced note is edited through its own file; a second temp copy would only race it.
    linked_path = linked_file_for_note(load_registry(plugin.secure_settings_dir(), plugin.logger), note_id)
    if linked_path is not None:
        try:
            open_file(linked_path)
        except OSError as exc:
            plugin.logger.error("Failed to open synced file: %s: %s", type(exc).__name__, exc)
            return f"Failed: {str(exc)}"
        reset_launcher_query(plugin)
        return "Opening synced file..."

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


def queue_linked_file_action(plugin, plugin_dir, job, success_message):
    def start(email, master_token, show_notifications, settings_dir):
        queue_linked_file_job(
            plugin_dir,
            settings_dir,
            {**job, "email": email, "show_notifications": show_notifications},
            plugin.logger,
        )

    return start_authenticated_worker_action(
        plugin,
        "linked files watcher",
        start,
        success_message,
    )


def link_direction(direction):
    return DIRECTION_PULL if str(direction or "").strip().lower() == DIRECTION_PULL else DIRECTION_PUSH


def link_file(plugin, plugin_dir, path, note_id="", direction=DIRECTION_PUSH):
    job = {
        "action": ACTION_LINK,
        "path": str(path or ""),
        "note_id": str(note_id or ""),
        "direction": link_direction(direction),
    }
    return queue_linked_file_action(plugin, plugin_dir, job, "Linking file to Google Keep...")


def unlink_file(plugin, plugin_dir, note_id):
    job = {"action": ACTION_UNLINK, "note_id": str(note_id or "")}
    return queue_linked_file_action(plugin, plugin_dir, job, "Stopping file sync...")


def resolve_linked_file(plugin, plugin_dir, note_id, direction):
    job = {"action": ACTION_RESOLVE, "note_id": str(note_id or ""), "direction": link_direction(direction)}
    return queue_linked_file_action(plugin, plugin_dir, job, "Resolving file sync conflict...")
