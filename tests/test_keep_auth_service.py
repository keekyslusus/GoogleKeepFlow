import unittest
from unittest.mock import patch

from googlekeepflow.keep_auth_service import get_auth


class KeepAuthServiceTests(unittest.TestCase):
    def test_get_auth_uses_secure_metadata_email(self):
        with patch("googlekeepflow.keep_auth_service.load_auth", return_value=({"email": "User@Example.com"}, "token")):
            self.assertEqual(get_auth({}, "settings"), ("user@example.com", "token"))

    def test_get_auth_ignores_legacy_settings_email(self):
        settings = {"email": "old@example.com"}

        with patch("googlekeepflow.keep_auth_service.load_auth", return_value=({"email": "new@example.com"}, "token")):
            self.assertEqual(get_auth(settings, "settings"), ("new@example.com", "token"))

    def test_get_auth_does_not_use_settings_email_without_secure_auth(self):
        settings = {"email": "old@example.com"}

        with patch("googlekeepflow.keep_auth_service.load_auth", return_value=({}, None)):
            self.assertEqual(get_auth(settings, "settings"), ("", None))


if __name__ == "__main__":
    unittest.main()
