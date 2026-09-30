import atexit
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import gkeepapi
import gpsoauth


USAGE_LOG_NAME = "api_usage.log"
KEEP_REQUEST_TIMEOUT_SECONDS = 30
HTTP_TOO_MANY_REQUESTS = 429
KEEP_API_NAMES = ("_keep_api", "_reminders_api", "_media_api")


class KeepRateLimitedError(RuntimeError):
    """Google answered 429; gkeepapi on its own would retry that forever."""


class ApiUsage:
    """Counts Google requests of this process and appends them to api_usage.log in the settings folder."""

    def __init__(self):
        self.path = None
        self.source = ""
        self.counts = Counter()
        self.started = time.time()

    def enable(self, settings_dir, source):
        if self.path is None:
            atexit.register(self.flush)
        self.path = Path(settings_dir) / USAGE_LOG_NAME
        self.source = source

    def add(self, key, amount=1):
        self.counts[key] += amount

    def flush(self, now=None):
        now = time.time() if now is None else now
        counts = {key: value for key, value in self.counts.items() if value}
        if self.path is not None and counts:
            record = {
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "source": self.source,
                "seconds": round(now - self.started),
                **counts,
            }
            try:
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record) + "\n")
            except OSError:
                pass
        self.counts = Counter()
        self.started = now


api_usage = ApiUsage()


def enable_api_usage_log(settings_dir, source):
    api_usage.enable(settings_dir, source)


def response_is_rate_limited(response):
    status_code = getattr(response, "status_code", 200)
    if status_code == HTTP_TOO_MANY_REQUESTS:
        return True
    if status_code < 400:
        return False
    try:
        return int(response.json().get("error", {}).get("code", 0)) == HTTP_TOO_MANY_REQUESTS
    except Exception:
        return False


def harden_keep_client(keep, on_response=None):
    """Add a timeout to every Keep request and turn 429 into an exception."""
    for api_name in KEEP_API_NAMES:
        session = getattr(getattr(keep, api_name, None), "_session", None)
        if session is None or getattr(session, "_keepflow_hardened", False):
            continue
        send = session.request

        def request(*args, _send=send, **kwargs):
            if kwargs.get("timeout") is None:
                kwargs["timeout"] = KEEP_REQUEST_TIMEOUT_SECONDS
            api_usage.add("requests")
            try:
                response = _send(*args, **kwargs)
            except Exception:
                api_usage.add("request_errors")
                raise
            if on_response:
                on_response(response)
            if response_is_rate_limited(response):
                api_usage.add("rate_limited")
                raise KeepRateLimitedError("Google Keep is limiting requests")
            return response

        session.request = request
        session._keepflow_hardened = True
    return keep


def harden_google_auth(adapter_class=None):
    # gpsoauth posts without a timeout, so a stalled sign-in would hang the process.
    adapter_class = adapter_class or gpsoauth.AuthHTTPAdapter
    if getattr(adapter_class, "_keepflow_timeout", False):
        return
    send = adapter_class.send

    def send_with_timeout(self, request, *args, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = KEEP_REQUEST_TIMEOUT_SECONDS
        api_usage.add("auth_requests")
        return send(self, request, *args, **kwargs)

    adapter_class.send = send_with_timeout
    adapter_class._keepflow_timeout = True


def new_keep_client(on_response=None):
    harden_google_auth()
    return harden_keep_client(gkeepapi.Keep(), on_response)
