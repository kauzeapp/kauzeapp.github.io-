import unittest

from backend.auth import (
    _business_logo_value,
    _normalized_business_state,
    _profile_image_value,
)


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

    def test_business_logo_accepts_upload_and_rejects_unsafe_url(self):
        value = "data:image/webp;base64,QUJDRA=="
        self.assertEqual(_business_logo_value(value), value)
        with self.assertRaises(ValueError):
            _business_logo_value("http://unsafe.example/logo.png")

    def test_business_state_keeps_authoritative_business_identity(self):
        state = _normalized_business_state(
            {
                "name": "Negocio ajeno",
                "type": "manicure",
                "logoUrl": "data:image/webp;base64,QUJDRA==",
                "businessStatus": "estado-inventado",
            },
            "barberia",
            "Barbería autorizada",
        )
        self.assertEqual(state["type"], "barberia")
        self.assertEqual(state["name"], "Negocio ajeno")
        self.assertEqual(state["businessStatus"], "CERRADO")

    def test_business_integrations_are_normalized(self):
        state = _normalized_business_state(
            {
                "name": "Barbería autorizada",
                "instagramUrl": "https://www.instagram.com/masterplan.soluciones",
                "instagramHandle": "masterplan.soluciones",
                "publicPhone": "+56 9 1234 5678",
            },
            "barberia",
            "Barbería autorizada",
        )
        self.assertEqual(state["type"], "barberia")
        self.assertEqual(state["instagramHandle"], "@masterplan.soluciones")
        self.assertEqual(state["publicPhone"], "+56 9 1234 5678")

    def test_business_integrations_reject_unsafe_values(self):
        with self.assertRaisesRegex(ValueError, "Instagram"):
            _normalized_business_state(
                {"name": "Barbería", "instagramUrl": "https://example.com/falso"},
                "barberia",
                "Barbería",
            )

    def test_business_location_is_normalized_and_coordinates_are_bounded(self):
        state = _normalized_business_state(
            {
                "name": "Barbería autorizada",
                "address": "  Av. Providencia 1234  ",
                "commune": "Providencia",
                "city": "Santiago",
                "latitude": "-33.4267",
                "longitude": "-70.6122",
            },
            "barberia",
            "Barbería autorizada",
        )
        self.assertEqual(state["address"], "Av. Providencia 1234")
        self.assertEqual(state["commune"], "Providencia")
        self.assertEqual(state["city"], "Santiago")
        self.assertEqual(state["latitude"], -33.4267)
        self.assertEqual(state["longitude"], -70.6122)

        with self.assertRaisesRegex(ValueError, "latitud"):
            _normalized_business_state(
                {"name": "Barbería", "latitude": 120},
                "barberia",
                "Barbería",
            )
        with self.assertRaisesRegex(ValueError, "WhatsApp"):
            _normalized_business_state(
                {"name": "Barbería", "publicPhone": "llámame"},
                "barberia",
                "Barbería",
            )


if __name__ == "__main__":
    unittest.main()
