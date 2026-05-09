import ctypes
import json
import time
from ctypes import wintypes
from pathlib import Path


DPAPI_ENTROPY = b"GoogleKeepFlow-MasterToken-v1"
TOKEN_FILE_NAME = "google_keep_master_token.bin"
META_FILE_NAME = "google_keep_auth.meta.json"


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _build_data_blob(data):
    if not data:
        return DATA_BLOB(0, None), None
    buffer = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect_bytes(raw_bytes):
    if not raw_bytes:
        return b""

    blob_in, buffer_in = _build_data_blob(raw_bytes)
    blob_entropy, buffer_entropy = _build_data_blob(DPAPI_ENTROPY)
    blob_out = DATA_BLOB()

    result = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None,
        ctypes.byref(blob_entropy),
        None,
        None,
        0,
        ctypes.byref(blob_out),
    )
    if not result:
        raise ctypes.WinError()

    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def unprotect_bytes(protected_bytes):
    if not protected_bytes:
        return b""

    blob_in, buffer_in = _build_data_blob(protected_bytes)
    blob_entropy, buffer_entropy = _build_data_blob(DPAPI_ENTROPY)
    blob_out = DATA_BLOB()

    result = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        ctypes.byref(blob_entropy),
        None,
        None,
        0,
        ctypes.byref(blob_out),
    )
    if not result:
        raise ctypes.WinError()

    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def auth_paths(settings_dir):
    base_dir = Path(settings_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / TOKEN_FILE_NAME, base_dir / META_FILE_NAME


def save_auth(settings_dir, email, master_token, android_id=None):
    email = (email or "").strip().lower()
    master_token = (master_token or "").strip()
    if not email:
        raise ValueError("Email is required")
    if not master_token.startswith("aas_et/"):
        raise ValueError("Invalid Google Keep master token")

    token_file, meta_file = auth_paths(settings_dir)
    token_file.write_bytes(protect_bytes(master_token.encode("utf-8")))
    metadata = {
        "email": email,
        "android_id": android_id,
        "token_last4": master_token[-4:],
        "saved_at": int(time.time()),
    }
    meta_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def load_auth(settings_dir, logger=None):
    token_file, meta_file = auth_paths(settings_dir)
    if not token_file.exists():
        return {}, None

    metadata = {}
    if meta_file.exists():
        try:
            loaded = json.loads(meta_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                metadata = loaded
        except (OSError, json.JSONDecodeError) as exc:
            if logger:
                logger.warning("Failed to load auth metadata %s: %s: %s", meta_file, type(exc).__name__, exc)
            metadata = {}

    raw_token = unprotect_bytes(token_file.read_bytes()).decode("utf-8", errors="ignore").strip()
    if not raw_token:
        return metadata, None
    return metadata, raw_token


def remove_auth(settings_dir, logger=None):
    token_file, meta_file = auth_paths(settings_dir)
    for path in (token_file, meta_file):
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            if logger:
                logger.warning("Failed to remove auth file %s: %s: %s", path, type(exc).__name__, exc)

