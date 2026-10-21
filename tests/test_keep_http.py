import unittest

import gkeepapi

from googlekeepflow.keep_http import (
    KEEP_REQUEST_TIMEOUT_SECONDS,
    KeepRateLimitedError,
    harden_google_auth,
    harden_keep_client,
    new_keep_client,
    response_is_rate_limited,
)


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self.body = body or {}

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeApi:
    def __init__(self, response):
        self._session = FakeSession(response)


class FakeKeep:
    def __init__(self, response):
        self._keep_api = FakeApi(response)
        self._reminders_api = FakeApi(response)
        self._media_api = FakeApi(response)


class HardenKeepClientTests(unittest.TestCase):
    def test_requests_get_a_timeout_and_are_counted(self):
        keep = FakeKeep(FakeResponse())
        seen = []
        harden_keep_client(keep, seen.append)
        session = keep._keep_api._session

        session.request(method="POST", url="https://example.com")

        self.assertEqual(session.calls[0]["timeout"], KEEP_REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(len(seen), 1)

    def test_explicit_timeout_is_kept(self):
        keep = FakeKeep(FakeResponse())
        harden_keep_client(keep)
        session = keep._keep_api._session

        session.request(method="POST", url="https://example.com", timeout=5)

        self.assertEqual(session.calls[0]["timeout"], 5)

    def test_rate_limit_raises_instead_of_retrying_forever(self):
        keep = FakeKeep(FakeResponse(429))
        harden_keep_client(keep)

        with self.assertRaises(KeepRateLimitedError):
            keep._keep_api._session.request(method="POST", url="https://example.com")

    def test_hardening_twice_wraps_once(self):
        keep = FakeKeep(FakeResponse())
        harden_keep_client(keep)
        first = keep._keep_api._session.request
        harden_keep_client(keep)

        self.assertIs(keep._keep_api._session.request, first)

    def test_real_gkeepapi_client_sessions_are_hardened(self):
        keep = new_keep_client()

        for api_name in ("_keep_api", "_reminders_api", "_media_api"):
            self.assertTrue(getattr(getattr(keep, api_name)._session, "_keepflow_hardened", False), api_name)


class RateLimitDetectionTests(unittest.TestCase):
    def test_detects_status_and_error_body(self):
        self.assertTrue(response_is_rate_limited(FakeResponse(429)))
        self.assertTrue(response_is_rate_limited(FakeResponse(403, {"error": {"code": 429}})))
        self.assertFalse(response_is_rate_limited(FakeResponse(401, {"error": {"code": 401}})))
        self.assertFalse(response_is_rate_limited(FakeResponse(200)))


class HardenGoogleAuthTests(unittest.TestCase):
    def test_auth_requests_get_a_timeout(self):
        calls = []

        class Adapter:
            def send(self, request, **kwargs):
                calls.append(kwargs)

        harden_google_auth(Adapter)
        harden_google_auth(Adapter)
        Adapter().send("request", timeout=None)
        Adapter().send("request", timeout=3)

        self.assertEqual([call["timeout"] for call in calls], [KEEP_REQUEST_TIMEOUT_SECONDS, 3])


if __name__ == "__main__":
    unittest.main()
