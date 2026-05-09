from googlekeepflow.keep_help import add_help_results, change_query_action, is_help_query, plugin_query
from googlekeepflow.keep_query import (
    ADD_COMMANDS,
    ARCHIVE_COMMANDS,
    EDIT_COMMANDS,
    LIST_COMMANDS,
    PIN_COMMANDS,
    REMINDER_COMMANDS,
    TODO_COMMANDS,
    setup_email_from_query,
    split_command_query,
)
from googlekeepflow.keep_reminder_parser import parse_reminder_details


def parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def handle_query(plugin, query_text):
    email, master_token = plugin.get_auth()

    if is_help_query(query_text):
        add_help_results(plugin, plugin.current_keyword(), plugin.icons)
        return

    if add_setup_query_result(plugin, query_text, email):
        return

    if not email or not master_token:
        add_setup_required_result(plugin, email)
        return

    if not query_text.strip():
        add_launcher_result(plugin)
        return

    command, command_text = split_command_query(query_text)
    if dispatch_command(plugin, command, command_text, email, master_token):
        return

    plugin.add_note_result(query_text)


def add_setup_query_result(plugin, query_text, email):
    setup_email = setup_email_from_query(query_text, email)
    if setup_email is None:
        return False
    plugin.add_item(
        title="Open GoogleKeepFlow setup",
        subtitle="Sign in with Google and configure this plugin",
        icon=plugin.icons["setup"],
        method=plugin.open_webview_setup,
        parameters=[setup_email],
    )
    return True


def add_setup_required_result(plugin, email):
    plugin.add_item(
        title="Setup GoogleKeepFlow",
        subtitle="Sign in with Google to start using Keep",
        icon=plugin.icons["setup"],
        method=plugin.open_webview_setup,
        parameters=[email],
    )


def add_launcher_result(plugin):
    list_query = plugin_query(plugin.current_keyword(), "list")
    help_query = plugin_query(plugin.current_keyword(), "?")
    list_action = change_query_action(plugin, list_query)
    plugin.add_item(
        title="GoogleKeepFlow",
        subtitle=f"Type a note, use {list_query}, or open commands with {help_query}",
        icon=plugin.icons["default"],
        method=list_action["method"],
        parameters=list_action["parameters"],
        dont_hide=list_action["dont_hide"],
        auto_complete_text=list_query,
        context={
            "type": "keep_launcher",
        },
    )


def dispatch_command(plugin, command, command_text, email, master_token):
    if command in LIST_COMMANDS:
        return handle_list_command(plugin, email, master_token, command_text)

    if command in EDIT_COMMANDS:
        return handle_edit_command(plugin, email, master_token, command_text)

    if command in ARCHIVE_COMMANDS:
        return handle_archive_command(plugin, email, master_token, command_text)

    if command in PIN_COMMANDS:
        return handle_pin_command(plugin, command_text)

    if command in TODO_COMMANDS:
        return handle_todo_command(plugin, command_text)

    if command in REMINDER_COMMANDS:
        return handle_reminder_command(plugin, command_text)

    if command in ADD_COMMANDS:
        return handle_add_command(plugin, command_text)

    return False


def handle_list_command(plugin, email, master_token, command_text):
    plugin.list_notes(email, master_token, archived=False, search_text=command_text)
    return True


def handle_edit_command(plugin, email, master_token, command_text):
    plugin.list_notes(email, master_token, archived=False, search_text=command_text, edit_mode=True)
    return True


def handle_archive_command(plugin, email, master_token, command_text):
    if command_text:
        plugin.add_note_result(command_text, archived=True)
    plugin.list_notes(email, master_token, archived=True, search_text=command_text)
    return True


def handle_pin_command(plugin, command_text):
    if command_text:
        plugin.add_note_result(command_text, pinned=True)
    else:
        plugin.add_item(
            title="Add pinned note",
            subtitle=f"Example: {plugin_query(plugin.current_keyword(), 'pin important idea #work')}",
            icon=plugin.icons["pin"],
        )
    return True


def handle_todo_command(plugin, command_text):
    if command_text:
        plugin.add_note_result(command_text, list_note=True)
    else:
        plugin.add_item(
            title="Add checklist",
            subtitle=f"Example: {plugin_query(plugin.current_keyword(), 'todo milk; eggs; bread #shopping')}",
            icon=plugin.icons["checklist"],
        )
    return True


def handle_reminder_command(plugin, command_text):
    if not parse_bool(plugin.settings.get("experimental_reminders", False)):
        plugin.add_item(
            title="Reminders are experimental",
            subtitle="Enable 'Experimental: Reminder feature' in plugin settings",
            icon=plugin.icons["reminder"],
        )
        return True

    reminder = parse_reminder_details(command_text)
    if reminder.due_at and reminder.note_text:
        plugin.add_note_result(
            reminder.note_text,
            reminder_at_iso=reminder.due_at.isoformat(),
            reminder_title_due=reminder.title_due_text,
            reminder_subtitle_due=reminder.subtitle_due_text,
        )
    else:
        plugin.add_item(
            title="Add reminder",
            subtitle=reminder.error,
            icon=plugin.icons["reminder"],
        )
    return True


def handle_add_command(plugin, command_text):
    if command_text:
        plugin.add_note_result(command_text)
    else:
        plugin.add_item(
            title="Add note",
            subtitle=f"Example: {plugin_query(plugin.current_keyword(), 'add buy milk #shopping')}",
            icon=plugin.icons["add_note"],
        )
    return True
