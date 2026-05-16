import sys
from pathlib import Path

package_dir = Path(__file__).parent.resolve()
plugindir = package_dir.parent
if str(plugindir) not in sys.path:
    sys.path.insert(0, str(plugindir))
lib_path = plugindir / "lib"
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

from googlekeepflow.worker_common import (
    find_note,
    load_keep,
    save_notes_cache,
    setup_worker_logger,
    short_error,
    show_notification,
)


logger = setup_worker_logger("archive_worker", plugindir)


def main():
    if len(sys.argv) != 6:
        logger.error("Invalid arguments count: %s", len(sys.argv))
        sys.exit(1)

    requested_email = sys.argv[1]
    note_id = sys.argv[2]
    archived = str(sys.argv[3]).lower() in ("1", "true", "yes", "on")
    show_notifications = str(sys.argv[4]).lower() in ("1", "true", "yes", "on")
    settings_dir = sys.argv[5]

    logger.info("Archive worker started")

    try:
        email, keep = load_keep(settings_dir, requested_email)
        note = find_note(keep, note_id)
        if note is None:
            logger.error("Note not found: %s", note_id)
            show_notification(
                "Note Not Found",
                "Could not find this Google Keep note",
                plugindir,
                logger,
                enabled=show_notifications,
            )
            return

        note.archived = archived
        keep.sync()
        save_notes_cache(settings_dir, email, keep, logger)

        title = "Note Archived" if archived else "Note Restored"
        logger.info("Note archive state changed: archived=%s", archived)
        logger.info("%s: id=%s", title, note_id)
    except Exception as exc:
        logger.error("Failed to update archive state: %s: %s", type(exc).__name__, exc)
        show_notification(
            "Failed to Update Note",
            short_error(exc),
            plugindir,
            logger,
            enabled=show_notifications,
        )


if __name__ == "__main__":
    main()
