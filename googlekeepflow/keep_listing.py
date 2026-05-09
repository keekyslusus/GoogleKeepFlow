from googlekeepflow.keep_cache import cache_data_age_seconds, load_cache, notes_from_cache_data, save_cache
from googlekeepflow.keep_notes import recent_notes_from_keep
from googlekeepflow.keep_query import parse_max_notes
from googlekeepflow.keep_worker_launcher import start_cache_refresh_worker


def list_notes(plugin, plugin_dir, email, master_token, archived=False, search_text="", edit_mode=False):
    max_notes = parse_max_notes(plugin.settings.get('max_notes_to_show', '20'))
    settings_dir = plugin.secure_settings_dir()

    try:
        cache_data = load_cache(settings_dir, plugin.logger)
        cached = notes_from_cache_data(cache_data, email, archived, max_notes, search_text=search_text, logger=plugin.logger) if cache_data else None
        if cached is not None:
            age_seconds = cache_data_age_seconds(cache_data, plugin.logger)
            plugin.logger.info("Using notes cache: age_seconds=%s", age_seconds)
            plugin.render_cached_notes(cached, archived, search_text=search_text, edit_mode=edit_mode)
            start_cache_refresh_worker(plugin_dir, email, settings_dir, plugin.logger)
            return

        keep = plugin.synced_keep_client(email, master_token, force=True)
        labels = keep.labels()
        labels_by_id = {label.id: label.name for label in labels}
        save_cache(settings_dir, email, keep.all(), plugin.logger, labels=labels)
        notes = recent_notes_from_keep(keep, max_notes=max_notes, archived=archived, search_text=search_text, labels_by_id=labels_by_id)
        plugin.render_live_notes(notes, archived, search_text=search_text, labels_by_id=labels_by_id, edit_mode=edit_mode)

    except Exception as e:
        plugin.logger.error(f"Failed to list notes: {type(e).__name__}: {e}")
        plugin.add_item(
            title="Failed to load notes",
            subtitle=str(e),
            icon=plugin.icons["list"],
        )
