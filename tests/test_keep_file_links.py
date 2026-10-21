import unittest
from datetime import datetime

from googlekeepflow.keep_file_links import (
    format_change_time,
    format_line_changes,
    line_change_counts,
    link_status_text,
)


NOW = datetime(2026, 10, 2, 15, 0)


def at(*args):
    return datetime(*args).timestamp()


class LineChangeTests(unittest.TestCase):
    def test_counts_added_removed_and_edited_lines(self):
        self.assertEqual(line_change_counts("a\nb\nc\n", "a\nB\nc\nd\n"), (2, 1))
        self.assertEqual(line_change_counts("a\n", "a\n"), (0, 0))
        self.assertEqual(line_change_counts("", "a\nb"), (2, 0))

    def test_format(self):
        self.assertEqual(format_line_changes(3, 1), "+3 −1 lines")
        self.assertEqual(format_line_changes(1, 0), "+1 line")
        self.assertEqual(format_line_changes(0, 2), "−2 lines")
        self.assertEqual(format_line_changes(0, 0), "")


class ChangeTimeTests(unittest.TestCase):
    def test_today_yesterday_and_older(self):
        self.assertEqual(format_change_time(at(2026, 10, 2, 12, 29), NOW), "12:29")
        self.assertEqual(format_change_time(at(2026, 10, 1, 23, 5), NOW), "yesterday 23:05")
        self.assertEqual(format_change_time(at(2026, 9, 28, 9, 7), NOW), "Sep 28 09:07")


class LinkStatusTextTests(unittest.TestCase):
    def test_shows_direction_time_and_lines(self):
        entry = {"status": "synced", "last_change": {"direction": "push", "at": at(2026, 10, 2, 12, 29), "added": 3, "removed": 1}}

        self.assertEqual(link_status_text(entry, NOW), "↑ Sent to Keep 12:29 · +3 −1 lines")

        entry["last_change"]["direction"] = "pull"
        self.assertEqual(link_status_text(entry, NOW), "↓ Updated from Keep 12:29 · +3 −1 lines")

    def test_falls_back_without_change_or_with_broken_record(self):
        self.assertEqual(link_status_text({"status": "synced"}, NOW), "Synced with Google Keep")
        self.assertEqual(link_status_text({"status": "synced", "last_change": {"direction": "push"}}, NOW), "Synced with Google Keep")

    def test_sync_error_wins_over_last_change(self):
        entry = {
            "status": "synced",
            "sync_error": "no connection to Google Keep",
            "last_change": {"direction": "push", "at": at(2026, 10, 2, 12, 29), "added": 1, "removed": 0},
        }

        self.assertEqual(link_status_text(entry, NOW), "Not synced: no connection to Google Keep")


if __name__ == "__main__":
    unittest.main()
