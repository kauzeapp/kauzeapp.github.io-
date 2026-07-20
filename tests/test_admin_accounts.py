import unittest
from unittest.mock import patch

from backend import admin_accounts


class AdminAccountsLocalTests(unittest.TestCase):
    def setUp(self):
        self.local_db = {"subscriptions": []}

    def _read(self):
        return self.local_db

    def _write(self, value):
        self.local_db = value

    def _create(self, email="preview@example.com"):
        return admin_accounts.create_admin_client(
            {
                "name": "Cliente Preview",
                "email": email,
                "phone": "+56911112222",
                "businessName": "Negocio Preview",
                "planTipo": "trial",
                "estadoSuscripcion": "trial",
                "categoriaSlug": "barberia",
            }
        )

    def test_create_and_stats_share_the_same_source(self):
        with (
            patch.object(admin_accounts, "is_configured", return_value=False),
            patch.object(admin_accounts, "read_local_db", side_effect=self._read),
            patch.object(admin_accounts, "write_local_db", side_effect=self._write),
        ):
            result = self._create()
            clients = admin_accounts.get_admin_clients()
            stats = admin_accounts.get_dashboard_stats()

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(clients), 1)
        self.assertEqual(stats["trial"], 1)
        self.assertEqual(stats["total"], 1)
        self.assertEqual(clients[0]["businessName"], "Negocio Preview")

    def test_duplicate_email_is_rejected(self):
        with (
            patch.object(admin_accounts, "is_configured", return_value=False),
            patch.object(admin_accounts, "read_local_db", side_effect=self._read),
            patch.object(admin_accounts, "write_local_db", side_effect=self._write),
        ):
            self._create()
            with self.assertRaisesRegex(ValueError, "correo ya esta registrado"):
                self._create()

    def test_update_and_reactivate_keep_cards_consistent(self):
        with (
            patch.object(admin_accounts, "is_configured", return_value=False),
            patch.object(admin_accounts, "read_local_db", side_effect=self._read),
            patch.object(admin_accounts, "write_local_db", side_effect=self._write),
        ):
            created = self._create()
            client_id = created["client"]["id"]
            admin_accounts.update_admin_client(
                client_id,
                {
                    "name": "Cliente Preview",
                    "email": "preview@example.com",
                    "phone": "+56911112222",
                    "businessName": "Negocio Preview",
                    "planTipo": "mensual",
                    "estadoSuscripcion": "en_mora",
                    "categoriaSlug": "barberia",
                    "subdominio": "negocio-preview.kauze.cl",
                },
            )
            self.assertEqual(admin_accounts.get_dashboard_stats()["en_mora"], 1)
            admin_accounts.activate_admin_client(client_id)
            stats = admin_accounts.get_dashboard_stats()

        self.assertEqual(stats["activo"], 1)
        self.assertEqual(stats["total"], 1)


if __name__ == "__main__":
    unittest.main()
