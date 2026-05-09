from pathlib import Path

from googlekeepflow.keep_auth_store import load_auth


def load_worker_auth(settings_dir, expected_email=""):
    metadata, master_token = load_auth(Path(settings_dir))
    email = str((metadata or {}).get("email", "") or "").strip().lower()
    expected_email = str(expected_email or "").strip().lower()
    if expected_email and email and email != expected_email:
        raise ValueError("Stored auth email does not match worker email")
    if not email:
        email = expected_email
    if not email or not master_token:
        raise ValueError("GoogleKeepFlow setup required")
    return email, master_token



