import unittest
from pathlib import Path

from backend.trials import TrialRegistrationError, _phone, register_trial


ROOT = Path(__file__).resolve().parents[1]
LANDING = (ROOT / "index.html").read_text(encoding="utf-8")
TRIAL_SQL = (ROOT / "backend" / "database" / "014_trial_onboarding.sql").read_text(
    encoding="utf-8"
)


class TrialRegistrationTests(unittest.TestCase):
    def test_paid_plans_are_rejected_by_backend(self):
        with self.assertRaises(TrialRegistrationError) as error:
            register_trial({"planTipo": "mensual"})
        self.assertEqual(error.exception.code, "paid_plans_unavailable")
        self.assertEqual(error.exception.status, 409)

    def test_phone_is_normalized_to_e164(self):
        self.assertEqual(_phone("+56 9 1234 5678"), "+56912345678")
        with self.assertRaises(TrialRegistrationError):
            _phone("912345678")

    def test_landing_exposes_only_trial_as_selectable(self):
        self.assertGreaterEqual(LANDING.count('aria-disabled="true"'), 3)
        self.assertIn("Crear mi prueba gratis", LANDING)
        self.assertNotIn("123456789", LANDING)
        self.assertNotIn("pagos@kauze.cl", LANDING)

    def test_initial_access_token_and_categories_are_migrated(self):
        self.assertIn("acceso_inicial", TRIAL_SQL)
        self.assertIn("'tatuajes'", TRIAL_SQL)
        self.assertIn("'talleres'", TRIAL_SQL)


if __name__ == "__main__":
    unittest.main()
