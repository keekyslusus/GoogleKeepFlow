from googlekeepflow.keep_clipboard import IMAGE_MARKER


HELP_QUERY_ALIASES = {"?"}
HELP_BASE_SCORE = 1_000_000


def is_help_query(query_text):
    return str(query_text or "").strip().lower() in HELP_QUERY_ALIASES


def plugin_query(keyword, command):
    return f"{str(keyword or 'keep').strip()} {command}".strip()


def change_query_action(plugin, query):
    return {
        "method": "change_query",
        "parameters": [str(query or ""), True],
        "dont_hide": True,
    }


def add_help_results(plugin, keyword, icons):
    list_query = plugin_query(keyword, "list")
    list_search_query = plugin_query(keyword, "list ")
    edit_query = plugin_query(keyword, "edit ")
    archive_query = plugin_query(keyword, "archive")
    archive_search_query = plugin_query(keyword, "archive ")
    add_query = plugin_query(keyword, "add ")
    pin_query = plugin_query(keyword, "pin ")
    todo_query = plugin_query(keyword, "todo ")
    remind_query = plugin_query(keyword, "remind in 10m ")
    image_query = plugin_query(keyword, IMAGE_MARKER)
    image_input_query = f"{image_query} "
    setup_query = plugin_query(keyword, "setup")

    list_action = change_query_action(plugin, list_query)
    plugin.add_item(
        title=list_query,
        subtitle="Show recent Google Keep notes",
        icon=icons["list"],
        method=list_action["method"],
        parameters=list_action["parameters"],
        dont_hide=list_action["dont_hide"],
        score=HELP_BASE_SCORE,
        auto_complete_text=list_query,
    )

    list_search_action = change_query_action(plugin, list_search_query)
    plugin.add_item(
        title=f"{list_query} [search]",
        subtitle="Search active Google Keep notes",
        icon=icons["list"],
        method=list_search_action["method"],
        parameters=list_search_action["parameters"],
        dont_hide=list_search_action["dont_hide"],
        score=HELP_BASE_SCORE - 1,
        auto_complete_text=list_search_query,
    )

    edit_action = change_query_action(plugin, edit_query)
    plugin.add_item(
        title=f"{plugin_query(keyword, 'edit')} [search]",
        subtitle="Search notes and open the selected note in your text editor",
        icon=icons["edit_note"],
        method=edit_action["method"],
        parameters=edit_action["parameters"],
        dont_hide=edit_action["dont_hide"],
        score=HELP_BASE_SCORE - 2,
        auto_complete_text=edit_query,
    )

    archive_action = change_query_action(plugin, archive_query)
    plugin.add_item(
        title=archive_query,
        subtitle="Show archived Google Keep notes",
        icon=icons["archive"],
        method=archive_action["method"],
        parameters=archive_action["parameters"],
        dont_hide=archive_action["dont_hide"],
        score=HELP_BASE_SCORE - 3,
        auto_complete_text=archive_query,
    )

    archive_search_action = change_query_action(plugin, archive_search_query)
    plugin.add_item(
        title=f"{archive_query} [search]",
        subtitle="Search archived notes; first result can add an archived note",
        icon=icons["archive"],
        method=archive_search_action["method"],
        parameters=archive_search_action["parameters"],
        dont_hide=archive_search_action["dont_hide"],
        score=HELP_BASE_SCORE - 4,
        auto_complete_text=archive_search_query,
    )

    add_action = change_query_action(plugin, add_query)
    plugin.add_item(
        title=f"{plugin_query(keyword, 'add')} [text]",
        subtitle="Create a note explicitly; hashtags become labels",
        icon=icons["add_note"],
        method=add_action["method"],
        parameters=add_action["parameters"],
        dont_hide=add_action["dont_hide"],
        score=HELP_BASE_SCORE - 5,
        auto_complete_text=add_query,
    )

    pin_action = change_query_action(plugin, pin_query)
    plugin.add_item(
        title=f"{plugin_query(keyword, 'pin')} [text]",
        subtitle="Create a pinned note",
        icon=icons["pin"],
        method=pin_action["method"],
        parameters=pin_action["parameters"],
        dont_hide=pin_action["dont_hide"],
        score=HELP_BASE_SCORE - 6,
        auto_complete_text=pin_query,
    )

    todo_action = change_query_action(plugin, todo_query)
    plugin.add_item(
        title=f"{plugin_query(keyword, 'todo')} [item; item]",
        subtitle="Create a checklist; separate items with ;",
        icon=icons["checklist"],
        method=todo_action["method"],
        parameters=todo_action["parameters"],
        dont_hide=todo_action["dont_hide"],
        score=HELP_BASE_SCORE - 7,
        auto_complete_text=todo_query,
    )

    remind_action = change_query_action(plugin, remind_query)
    plugin.add_item(
        title=f"{plugin_query(keyword, 'remind')} in 10m [text]",
        subtitle="Experimental: create a note with a Google Keep reminder",
        icon=icons["reminder"],
        method=remind_action["method"],
        parameters=remind_action["parameters"],
        dont_hide=remind_action["dont_hide"],
        score=HELP_BASE_SCORE - 8,
        auto_complete_text=remind_query,
    )

    image_action = change_query_action(plugin, image_input_query)
    plugin.add_item(
        title=image_query,
        subtitle="Copy an image to the clipboard, then send it to Google Keep",
        icon=icons["clipboard"],
        method=image_action["method"],
        parameters=image_action["parameters"],
        dont_hide=image_action["dont_hide"],
        score=HELP_BASE_SCORE - 9,
        auto_complete_text=image_input_query,
    )

    setup_action = change_query_action(plugin, setup_query)
    plugin.add_item(
        title=setup_query,
        subtitle="Sign in with Google and configure GoogleKeepFlow",
        icon=icons["setup"],
        method=setup_action["method"],
        parameters=setup_action["parameters"],
        dont_hide=setup_action["dont_hide"],
        score=HELP_BASE_SCORE - 10,
        auto_complete_text=setup_query,
    )

