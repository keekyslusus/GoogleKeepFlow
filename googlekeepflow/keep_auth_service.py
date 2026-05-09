from pathlib import Path

from googlekeepflow.keep_auth_store import load_auth


def secure_settings_dir(plugin_dir, settings_path):
    try:
        return Path(settings_path).parent
    except TypeError:
        return Path(plugin_dir)


def get_auth(settings, settings_dir, logger=None):
    try:
        metadata, secure_token = load_auth(settings_dir, logger)
    except Exception as exc:
        if logger:
            logger.error(f"Failed to load secure auth: {type(exc).__name__}: {exc}")
        metadata, secure_token = {}, None

    email = str((metadata or {}).get("email", "")).strip().lower()
    return email, secure_token


