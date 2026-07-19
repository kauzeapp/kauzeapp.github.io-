import unittest
from unittest.mock import Mock, patch
from pathlib import Path
from urllib.error import URLError

from backend.trials import (
    TrialRegistrationError,
    _ensure_owner_contact_available,
    _phone,
    register_trial,
)
from backend.email_delivery import _send_with_resend, email_provider


ROOT = Path(__file__).resolve().parents[1]
LANDING = (ROOT / "index.html").read_text(encoding="utf-8")
TRIAL_SQL = (ROOT / "backend" / "database" / "014_trial_onboarding.sql").read_text(
    encoding="utf-8"
)


class TrialRegistrationTests(unittest.TestCase):
    class _LookupConnection:
        def __init__(self, email_exists=False, phone_exists=False):
            self.email_exists = email_exists
            self.phone_exists = phone_exists
            self._result = None

        def execute(self, query, _params):
            self._result = self.email_exists if "LOWER(email)" in query else self.phone_exists
            return self

        def fetchone(self):
            return (1,) if self._result else None

    def test_paid_plans_are_rejected_by_backend(self):
        with self.assertRaises(TrialRegistrationError) as error:
            register_trial({"planTipo": "mensual"})
        self.assertEqual(error.exception.code, "paid_plans_unavailable")
        self.assertEqual(error.exception.status, 409)

    def test_phone_is_normalized_to_e164(self):
        self.assertEqual(_phone("+56 9 1234 5678"), "+56912345678")
        with self.assertRaises(TrialRegistrationError):
            _phone("912345678")

    def test_registered_phone_returns_a_clear_conflict(self):
        connection = self._LookupConnection(phone_exists=True)

        with self.assertRaises(TrialRegistrationError) as error:
            _ensure_owner_contact_available(
                connection, "nuevo@kauze.cl", "+56900000001"
            )

        self.assertEqual(error.exception.code, "phone_registered")
        self.assertEqual(error.exception.status, 409)
        self.assertIn("teléfono ya está registrado", str(error.exception))

    def test_registered_email_keeps_its_clear_conflict(self):
        connection = self._LookupConnection(email_exists=True)

        with self.assertRaises(TrialRegistrationError) as error:
            _ensure_owner_contact_available(
                connection, "registrado@kauze.cl", "+56900000001"
            )

        self.assertEqual(error.exception.code, "email_registered")
        self.assertEqual(error.exception.status, 409)

    def test_landing_exposes_only_trial_as_selectable(self):
        self.assertGreaterEqual(LANDING.count('aria-disabled="true"'), 3)
        self.assertIn("Crear mi prueba gratis", LANDING)
        self.assertNotIn("123456789", LANDING)
        self.assertNotIn("pagos@kauze.cl", LANDING)

    def test_initial_access_token_and_categories_are_migrated(self):
        self.assertIn("acceso_inicial", TRIAL_SQL)
        self.assertIn("'tatuajes'", TRIAL_SQL)
        self.assertIn("'talleres'", TRIAL_SQL)

    def test_resend_is_preferred_over_smtp(self):
        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "test-key",
                "KAUZE_EMAIL_FROM": "Kauze <acceso@kauze.cl>",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_USER": "user",
                "SMTP_PASSWORD": "secret",
                "SMTP_FROM": "legacy@kauze.cl",
            },
            clear=True,
        ):
            self.assertEqual(email_provider(), "resend")

    def test_resend_confirms_acceptance_and_uses_idempotency_key(self):
        response = Mock()
        response.status = 200
        response.read.return_value = b'{"id":"email-accepted-1"}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "test-key",
                "KAUZE_EMAIL_FROM": "Kauze <acceso@kauze.cl>",
            },
            clear=True,
        ), patch("backend.email_delivery.urlopen", return_value=response) as request:
            receipt = _send_with_resend(
                "persona@example.com",
                "Bienvenida",
                "Contenido",
                "trial-access/user-1",
            )

        self.assertEqual(
            receipt, {"provider": "resend", "id": "email-accepted-1"}
        )
        self.assertEqual(
            request.call_args.args[0].get_header("Idempotency-key"),
            "trial-access/user-1",
        )

    def test_resend_retries_temporary_failures_without_duplicates(self):
        response = Mock()
        response.status = 200
        response.read.return_value = b'{"id":"email-after-retry"}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "test-key",
                "KAUZE_EMAIL_FROM": "Kauze <acceso@kauze.cl>",
            },
            clear=True,
        ), patch(
            "backend.email_delivery.urlopen",
            side_effect=[URLError("temporary"), response],
        ) as request, patch("backend.email_delivery.time.sleep"):
            receipt = _send_with_resend(
                "persona@example.com",
                "Bienvenida",
                "Contenido",
                "trial-access/user-2",
            )

        self.assertEqual(receipt["id"], "email-after-retry")
        self.assertEqual(request.call_count, 2)

    def test_resend_rejects_success_without_email_id(self):
        response = Mock()
        response.status = 200
        response.read.return_value = b'{}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        with patch.dict(
            "os.environ",
            {
                "RESEND_API_KEY": "test-key",
                "KAUZE_EMAIL_FROM": "Kauze <acceso@kauze.cl>",
            },
            clear=True,
        ), patch("backend.email_delivery.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "no confirmo"):
                _send_with_resend(
                    "persona@example.com",
                    "Bienvenida",
                    "Contenido",
                    "trial-access/user-3",
                )


if __name__ == "__main__":
    unittest.main()
