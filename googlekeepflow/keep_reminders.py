from datetime import datetime, timezone
from uuid import getnode as get_mac
import json
import random
import string

import gpsoauth
import requests

try:
    from tzlocal import get_localzone_name
except ImportError:
    get_localzone_name = None


# Public client identifiers copied from Google Keep Web/Android traffic.
# They are not user secrets, the user's encrypted master token supplies account access.
KEEP_WEB_API_KEY = "AIzaSyDE7NHMUZfMoJVu-YNkK-7AXFSuL1Q9gKE"
GOOGLE_TASKS_OAUTH_SCOPE = "oauth2:https://www.googleapis.com/auth/tasks"
KEEP_ANDROID_APP = "com.google.android.keep"
KEEP_ANDROID_CLIENT_SIG = "38918a453d07199354f8b19af05ec6562ced5788"
CLIENT_HOSTS = ["clients6.google.com", "clients1.google.com", "clients2.google.com", "clients3.google.com", "clients4.google.com", "clients5.google.com"]
TASKS_PATH = "/$rpc/google.internal.tasks.v1.TasksApiService/Sync"
NOTES_PATH = "/notes/v1/changes"
WEB_CLIENT_VERSION = {"major": "3", "minor": "3", "build": "0", "revision": "387"}
WEB_CAPABILITIES = ("EC", "TR", "SH", "LB", "RB", "DR", "AN", "PI", "EX", "IN", "SNB", "CO", "MI", "NC", "CL", "IN")


class ReminderError(RuntimeError):
    pass


def _random_id(length=16):
    alphabet = string.ascii_letters + string.digits + "_-"
    return "".join(random.choice(alphabet) for _ in range(length))


def _timestamp_tuple(dt=None):
    dt = dt or datetime.now(timezone.utc)
    return [int(dt.timestamp()), dt.microsecond * 1000]


def _time_list(dt):
    return [dt.hour if dt.hour else None, dt.minute]


def _web_timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _web_request_header():
    milliseconds = int(datetime.now(timezone.utc).timestamp() * 1000)
    return {
        "requestId": f"request.{_random_id(12).lower()}.{milliseconds}",
        "clientVersion": WEB_CLIENT_VERSION,
        "clientPlatform": "WEB",
        "capabilities": [{"type": capability} for capability in WEB_CAPABILITIES],
        "clientSessionId": f"s--{milliseconds}--{random.randint(1000000000, 9999999999)}",
        "clientLocale": "ru",
    }


def _offset_timezone_name(dt):
    offset = dt.utcoffset()
    if offset is None:
        return "UTC"

    total_minutes = int(offset.total_seconds() // 60)
    if total_minutes == 0:
        return "UTC"

    hours, minutes = divmod(abs(total_minutes), 60)
    sign = "-" if total_minutes > 0 else "+"
    if minutes:
        return f"Etc/GMT{sign}{hours}:{minutes:02d}"
    return f"Etc/GMT{sign}{hours}"


def timezone_name_for_reminder(dt, timezone_name=None):
    timezone_name = str(timezone_name or "").strip()
    if timezone_name:
        return timezone_name

    tzinfo = dt.tzinfo
    key = getattr(tzinfo, "key", "")
    if key:
        return key

    if get_localzone_name is not None:
        try:
            localzone_name = str(get_localzone_name() or "").strip()
            if localzone_name:
                return localzone_name
        except Exception:
            pass

    return _offset_timezone_name(dt)


def _request_with_host_fallback(session, subdomain, path, headers, logger=None, **kwargs):
    last_error = None
    for host in CLIENT_HOSTS:
        url = f"https://{subdomain}.{host}{path}"
        try:
            response = session.post(url, headers=headers, timeout=30, **kwargs)
        except requests.RequestException as exc:
            last_error = exc
            if logger:
                logger.warning("Reminder request failed for %s: %s: %s", host, type(exc).__name__, exc)
            continue

        if response.status_code in (401, 403):
            raise ReminderError(f"{subdomain} auth failed: HTTP {response.status_code}: {response.text[:200]}")
        if response.status_code < 500 and response.status_code != 404:
            if logger:
                logger.info("Reminder request used %s.%s", subdomain, host)
            return response

        last_error = ReminderError(f"{subdomain} host {host} returned HTTP {response.status_code}: {response.text[:200]}")
        if logger:
            logger.warning("%s", last_error)

    raise ReminderError(str(last_error) if last_error else f"No {subdomain} hosts available")


def _tasks_payload(task_id, server_id, text, due_at, timezone_name):
    now = _timestamp_tuple()
    date = [due_at.year, due_at.month, due_at.day]
    due_unix = int(due_at.timestamp())
    empty_note_link = [None, None, None, None, None, None, None, None, []]
    note_link = [None, None, None, None, None, None, None, None, [server_id]]
    due = [[None, [1]], [[None, date, _time_list(due_at), timezone_name, None, [due_unix]]]]
    operations = [
        [
            _random_id(), 3, task_id, [1], None, None,
            [[None, [2, 4, 8, 6, 13]], [None, text + " ", None, date, None, None, None, empty_note_link]],
            None, None, now, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, 1,
        ],
        [
            _random_id(), 3, task_id, [1, 1], None, None, None, None, None, now, None, due,
            None, None, None, None, None, None, None, None, None, None, None, None, None, 1, 1, [1],
        ],
        [
            _random_id(), 4, "~default", [1], None, None, None, None, [task_id, None, None, None, None, None, 1], now,
            None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, 1, 2,
            [None, str(random.randint(200, 999))],
        ],
        [
            _random_id(), 3, task_id, [1, 2], None, None, None, None, None, now, [None, "~default"], None,
            None, None, None, None, None, None, None, None, None, None, None, None, None, 1, 3, [1, 1],
        ],
        [
            _random_id(), 3, task_id, [1, 3], None, None,
            [[None, [8, 6, 13]], [None, None, None, None, None, None, None, note_link]],
            None, None, now, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None,
            1, 4, [1, 2],
        ],
        [
            _random_id(), 3, task_id, [1, 4], None, None, None, None, None, now, None, None,
            None, None, None, None, None, None, None, None, [], None, None, None, None, 1, 6, [1, 3],
        ],
    ]
    return [[None, [_timestamp_tuple(), None, [[operations, []]]]]]


def _keep_tasks_payload(target_version, note, task_id):
    timestamps = note.timestamps.save(True)
    timestamps.setdefault("deleted", "1970-01-01T00:00:00.000Z")
    timestamps.setdefault("trashed", "1970-01-01T00:00:00.000Z")
    node = {
        "id": note.id,
        "kind": "notes#node",
        "parentId": "root",
        "timestamps": timestamps,
        "type": note.type.value,
        "trashState": 0,
        "serverId": note.server_id,
        "deletionState": 0,
        "sortValue": note.sort,
        "baseVersion": "0",
        "title": getattr(note, "title", "") or "",
        "isArchived": bool(getattr(note, "archived", False)),
        "isPinned": bool(getattr(note, "pinned", False)),
        "tasks": [{"taskId": task_id, "deleted": False}],
        "clientChanges": {"clientRevision": "2", "commandBundles": []},
    }
    return {
        "targetVersion": target_version,
        "clientTimestamp": _web_timestamp(),
        "nodes": [node],
        "requestHeader": _web_request_header(),
    }


def _tasks_token(email, master_token, device_id):
    result = gpsoauth.perform_oauth(
        email,
        master_token,
        device_id,
        service=GOOGLE_TASKS_OAUTH_SCOPE,
        app=KEEP_ANDROID_APP,
        client_sig=KEEP_ANDROID_CLIENT_SIG,
    )
    token = result.get("Auth")
    if not token:
        raise ReminderError(f"Failed to get Google Tasks token: {result.get('Error') or 'unknown error'}")
    return token


def create_keep_reminder(email, master_token, keep, note, text, due_at, logger=None, device_id=None, timezone_name=None):
    if not getattr(note, "server_id", None):
        raise ReminderError("Cannot set reminder before note server_id is available")

    due_at = due_at.astimezone()
    resolved_timezone_name = timezone_name_for_reminder(due_at, timezone_name)
    device_id = str(device_id or f"{get_mac():x}")
    session = requests.Session()
    task_id = _random_id()
    task_token = _tasks_token(email, master_token, device_id)
    task_headers = {
        "Authorization": "OAuth " + task_token,
        "Content-Type": "application/json+protobuf",
        "x-goog-api-key": KEEP_WEB_API_KEY,
        "x-goog-authuser": "0",
        "x-user-agent": "grpc-web-javascript/0.1",
        "Origin": "https://keep.google.com",
        "Referer": "https://keep.google.com/",
    }
    task_response = _request_with_host_fallback(
        session,
        "tasks-pa",
        TASKS_PATH,
        task_headers,
        logger,
        data=json.dumps(_tasks_payload(task_id, note.server_id, text, due_at, resolved_timezone_name), separators=(",", ":")),
    )
    if task_response.status_code != 200:
        raise ReminderError(f"Google Tasks reminder failed: HTTP {task_response.status_code}: {task_response.text[:200]}")

    keep_token = keep._keep_api.getAuth().getAuthToken()
    note_headers = {
        "Authorization": "OAuth " + keep_token,
        "Content-Type": "application/json",
        "x-goog-api-key": KEEP_WEB_API_KEY,
        "x-goog-authuser": "0",
        "Origin": "https://keep.google.com",
        "Referer": "https://keep.google.com/",
    }
    note_response = _request_with_host_fallback(
        session,
        "notes-pa",
        f"{NOTES_PATH}?alt=json&key={KEEP_WEB_API_KEY}",
        note_headers,
        logger,
        json=_keep_tasks_payload(keep._keep_version, note, task_id),
    )
    if note_response.status_code != 200 or "SUCCESS" not in note_response.text:
        raise ReminderError(f"Keep reminder link failed: HTTP {note_response.status_code}: {note_response.text[:200]}")

    if logger:
        logger.info("Reminder timezone used: %s", resolved_timezone_name)
    return task_id
