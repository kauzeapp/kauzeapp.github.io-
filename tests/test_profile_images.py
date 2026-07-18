import unittest

from backend.auth import _profile_image_value


class ProfileImageValidationTests(unittest.TestCase):
    def test_accepts_supported_data_image(self):
        value = "data:image/webp;base64,QUJDRA=="
        self.assertEqual(_profile_image_value(value), value)

    def test_accepts_google_https_avatar(self):
        value = "https://lh3.googleusercontent.com/a/example"
        self.assertEqual(_profile_image_value(value), value)

    def test_empty_value_removes_image(self):
        self.assertIsNone(_profile_image_value(""))

    def test_rejects_unsafe_source(self):
        with self.assertRaises(ValueError):
            _profile_image_value("javascript:alert(1)")


if __name__ == "__main__":
    unittest.main()
