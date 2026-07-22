import unittest
from datetime import date, timedelta
from unittest.mock import patch

from backend.public_booking import PublicBookingError, _available_slots, _public_business, resolve_public_subdomain


class PublicBookingTests(unittest.TestCase):
    def setUp(self):
        self.target_date = (date.today() + timedelta(days=1)).isoformat()
        self.state = {
            "type": "barberia",
            "demoMode": True,
            "businessStatus": "DISPONIBLE",
            "pageTitle": "Reserva en Cauce Norte",
            "instagramUrl": "https://www.instagram.com/masterplan.soluciones",
            "instagramHandle": "@masterplan.soluciones",
            "logoUrl": "/cliente/assets/masterplan-logo.jpg",
            "publicSubdomain": "masterplan",
            "latitude": -33.4267,
            "longitude": -70.6122,
            "services": {
                "barberia": [
                    {"id": "service-1", "name": "Fade", "duration": "60 min", "price": 18000}
                ]
            },
            "professionals": {
                "barberia": [
                    {
                        "id": "professional-1",
                        "name": "Camila Soto",
                        "role": "Barbera",
                        "profileImage": "data:image/webp;base64,QUJDRA==",
                    }
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
                "phone": None,
                "category_slug": "barberia",
                "subdomain_state": "activo",
                "panel_state": self.state,
            }
        )
        self.assertEqual(business["services"][0]["name"], "Fade")
        self.assertEqual(business["professionals"][0]["name"], "Camila Soto")
        self.assertEqual(
            business["professionals"][0]["profileImage"],
            "data:image/webp;base64,QUJDRA==",
        )
        self.assertTrue(business["demoMode"])
        self.assertEqual(business["route"], "barberia-cauce-norte-demo.kauze.cl")
        self.assertEqual(business["instagramHandle"], "@masterplan.soluciones")
        self.assertEqual(business["logoUrl"], "/cliente/assets/masterplan-logo.jpg")
        self.assertEqual(business["lat"], -33.4267)
        self.assertEqual(business["lng"], -70.6122)
        self.assertEqual(
            business["instagramUrl"],
            "https://www.instagram.com/masterplan.soluciones",
        )

    def test_public_projection_rejects_unsafe_social_url(self):
        self.state["instagramUrl"] = "javascript:alert(1)"
        self.state["logoUrl"] = "javascript:alert(1)"
        self.state["publicSubdomain"] = '"><script>'
        business = _public_business(
            {
                "slug": "masterplan",
                "name": "Masterplan Barbería — DEMO",
                "description": "Demo funcional",
                "address": "Avenida Demo 456",
                "commune": "Providencia",
                "city": "Santiago",
                "phone": None,
                "category_slug": "barberia",
                "subdomain_state": "activo",
                "panel_state": self.state,
            }
        )
        self.assertEqual(business["instagramUrl"], "")
        self.assertEqual(business["logoUrl"], "")
        self.assertEqual(business["route"], "masterplan.kauze.cl")

    def test_closed_business_keeps_online_booking_message(self):
        self.state["businessStatus"] = "CERRADO"
        business = _public_business(
            {
                "slug": "barberia-cauce-norte-demo",
                "name": "Barbería Cauce Norte",
                "description": "Demo funcional",
                "address": "Avenida Demo 123",
                "commune": "Providencia",
                "city": "Santiago",
                "phone": None,
                "category_slug": "barberia",
                "subdomain_state": "activo",
                "panel_state": self.state,
            }
        )
        self.assertIn("Cerrado ahora", business["statusLabel"])
        self.assertIn("reservas online", business["statusLabel"])

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

    def test_pending_subdomain_uses_stable_direct_route(self):
        business = _public_business(
            {
                "slug": "masterplan",
                "name": "Masterplan",
                "category_slug": "barberia",
                "subdomain_state": "pendiente",
                "panel_state": self.state,
            }
        )
        self.assertEqual(business["route"], "kauze.cl/cliente/?negocio=masterplan")
        self.assertIsNone(business["subdomainUrl"])

    def test_resolver_only_returns_admin_approved_subdomain(self):
        class Result:
            def fetchone(self):
                return {"slug": "masterplan"}

        class FakeConnection:
            row_factory = None

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, statement, params):
                self.statement = " ".join(statement.split())
                self.params = params
                return Result()

        fake = FakeConnection()
        with patch("backend.public_booking.connection", return_value=fake):
            result = resolve_public_subdomain("masterplan")

        self.assertEqual(result["destination"], "https://kauze.cl/cliente/?negocio=masterplan")
        self.assertIn("l.subdominio_estado = 'activo'", fake.statement)
        self.assertIn("s.estado IN ('trial', 'activo')", fake.statement)

    def test_resolver_rejects_invalid_subdomain(self):
        with self.assertRaises(PublicBookingError):
            resolve_public_subdomain("admin.kauze.cl/path")


if __name__ == "__main__":
    unittest.main()
