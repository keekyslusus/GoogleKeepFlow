import unittest

from googlekeepflow.keep_query import parse_max_notes


class KeepQueryTests(unittest.TestCase):
    def test_parse_max_notes_uses_default_for_invalid_values(self):
        self.assertEqual(parse_max_notes("nope"), 20)
        self.assertEqual(parse_max_notes(None), 20)

    def test_parse_max_notes_clamps_low_values(self):
        self.assertEqual(parse_max_notes("-10"), 1)
        self.assertEqual(parse_max_notes("0"), 1)

    def test_parse_max_notes_clamps_high_values(self):
        self.assertEqual(parse_max_notes("1001"), 1000)
        self.assertEqual(parse_max_notes("999999"), 1000)

    def test_parse_max_notes_accepts_values_in_range(self):
        self.assertEqual(parse_max_notes("42"), 42)
        self.assertEqual(parse_max_notes(1000), 1000)


if __name__ == "__main__":
    unittest.main()
