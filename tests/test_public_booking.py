import unittest
from datetime import date, timedelta

from backend.public_booking import _available_slots, _public_business


class PublicBookingTests(unittest.TestCase):
    def setUp(self):
        self.target_date = (date.today() + timedelta(days=1)).isoformat()
        self.state = {
            "type": "barberia",
            "demoMode": True,
            "businessStatus": "DISPONIBLE",
            "pageTitle": "Reserva en Cauce Norte",
            "services": {
                "barberia": [
                    {"id": "service-1", "name": "Fade", "duration": "60 min", "price": 18000}
                ]
            },
            "professionals": {
                "barberia": [
                    {"id": "professional-1", "name": "Camila Soto", "role": "Barbera"}
                ]
            },
            "appointments": {
                "barberia": [
                    {
                        "date": self.target_date,
                        "time": "10:00",
                        "professional": "Camila Soto",
                        "status": "Confirmada",
                    }
                ]
            },
        }

    def test_public_projection_contains_real_catalog(self):
        business = _public_business(
            {
                "slug": "barberia-cauce-norte-demo",
                "name": "Barbería Cauce Norte — DEMO",
                "description": "Demo funcional",
                "address": "Avenida Demo 123",
                "commune": "Providencia",
                "city": "Santiago",
                "category_slug": "barberia",
                "panel_state": self.state,
            }
        )
        self.assertEqual(business["services"][0]["name"], "Fade")
        self.assertEqual(business["professionals"][0]["name"], "Camila Soto")
        self.assertTrue(business["demoMode"])

    def test_occupied_slot_is_not_offered(self):
        available = _available_slots(
            self.state, "barberia", self.target_date, "Camila Soto"
        )
        self.assertNotIn("10:00", available)
        self.assertIn("10:30", available)

    def test_other_professional_keeps_the_slot(self):
        available = _available_slots(
            self.state, "barberia", self.target_date, "Otro Profesional"
        )
        self.assertIn("10:00", available)


if __name__ == "__main__":
    unittest.main()
