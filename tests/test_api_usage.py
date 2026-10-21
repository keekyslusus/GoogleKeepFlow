import json
import sys
import tempfile
import unittest
from pathlib import Path

from googlekeepflow.keep_http import USAGE_LOG_NAME, ApiUsage, api_usage, harden_google_auth, harden_keep_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from api_usage_summary import format_report, load_records, summarize  # noqa: E402


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def json(self):
        return {}


class FakeApi:
    def __init__(self, request):
        self._session = type("Session", (), {"request": staticmethod(request)})()


class ApiUsageTests(unittest.TestCase):
    def test_flush_appends_one_json_line_and_resets(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = ApiUsage()
            usage.enable(tmp, "keep_list_refresh")
            usage.add("requests", 3)
            usage.add("runs")

            usage.flush()
            usage.flush()

            lines = (Path(tmp) / USAGE_LOG_NAME).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual((record["source"], record["requests"], record["runs"]), ("keep_list_refresh", 3, 1))

    def test_disabled_usage_writes_nothing(self):
        usage = ApiUsage()
        usage.add("requests")

        usage.flush()

        self.assertEqual(usage.counts, {})

    def test_hardened_client_counts_requests_errors_and_rate_limits(self):
        responses = [FakeResponse(), FakeResponse(429)]

        def request(**kwargs):
            if not responses:
                raise ConnectionError("down")
            return responses.pop(0)

        keep = type("Keep", (), {})()
        keep._keep_api = FakeApi(request)
        harden_keep_client(keep)
        before = dict(api_usage.counts)
        session = keep._keep_api._session

        session.request(url="u")
        for _ in range(2):
            try:
                session.request(url="u")
            except Exception:
                pass

        def delta(key):
            return api_usage.counts[key] - before.get(key, 0)

        self.assertEqual((delta("requests"), delta("rate_limited"), delta("request_errors")), (3, 1, 1))

    def test_sign_in_requests_are_counted(self):
        class Adapter:
            def send(self, request, **kwargs):
                return None

        harden_google_auth(Adapter)
        before = api_usage.counts["auth_requests"]

        Adapter().send("request")

        self.assertEqual(api_usage.counts["auth_requests"] - before, 1)


class SummaryTests(unittest.TestCase):
    def test_groups_by_day_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / USAGE_LOG_NAME
            path.write_text("\n".join([
                json.dumps({"time": "2026-10-02T10:05:00+03:00", "source": "keep_list_refresh", "requests": 4, "auth_requests": 2, "runs": 1}),
                json.dumps({"time": "2026-10-02T10:40:00+03:00", "source": "keep_list_refresh", "requests": 3, "auth_requests": 2, "runs": 1}),
                json.dumps({"time": "2026-10-02T11:00:00+03:00", "source": "linked_files", "requests": 60, "pushes": 2}),
                "not json",
            ]), encoding="utf-8")

            by_day, by_hour = summarize(load_records(path))
            report = format_report(by_day, by_hour)

        refresh = by_day[("2026-10-02", "keep_list_refresh")]
        self.assertEqual((refresh["entries"], refresh["requests"], refresh["auth_requests"]), (2, 7, 4))
        self.assertEqual(by_hour["2026-10-02T11"], 60)
        self.assertIn("linked_files", report)
        self.assertIn("2026-10-02 11:00", report)


if __name__ == "__main__":
    unittest.main()
