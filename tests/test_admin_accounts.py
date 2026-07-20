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

    def test_delete_removes_account_and_updates_cards(self):
        with (
            patch.object(admin_accounts, "is_configured", return_value=False),
            patch.object(admin_accounts, "read_local_db", side_effect=self._read),
            patch.object(admin_accounts, "write_local_db", side_effect=self._write),
        ):
            created = self._create()
            client_id = created["client"]["id"]
            result = admin_accounts.delete_admin_client(client_id)
            clients = admin_accounts.get_admin_clients()
            stats = admin_accounts.get_dashboard_stats()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deletedClientId"], client_id)
        self.assertEqual(clients, [])
        self.assertEqual(stats["total"], 0)

    def test_delete_rejects_unknown_account(self):
        with (
            patch.object(admin_accounts, "is_configured", return_value=False),
            patch.object(admin_accounts, "read_local_db", side_effect=self._read),
            patch.object(admin_accounts, "write_local_db", side_effect=self._write),
        ):
            with self.assertRaisesRegex(ValueError, "Cliente no encontrado"):
                admin_accounts.delete_admin_client("missing")

    def test_database_delete_accepts_dictionary_rows(self):
        client_id = "11111111-1111-4111-8111-111111111111"
        local_id = "22222222-2222-4222-8222-222222222222"

        class Result:
            def __init__(self, one=None, all_rows=None):
                self.one = one
                self.all_rows = all_rows or []

            def fetchone(self):
                return self.one

            def fetchall(self):
                return self.all_rows

        class Context:
            def __init__(self, value):
                self.value = value

            def __enter__(self):
                return self.value

            def __exit__(self, *_args):
                return False

        class FakeConnection:
            row_factory = None

            def __init__(self):
                self.statements = []

            def transaction(self):
                return Context(self)

            def execute(self, statement, _params=None):
                normalized = " ".join(statement.split())
                self.statements.append(normalized)
                if "FROM usuarios u WHERE u.id" in normalized:
                    return Result(one={"id": client_id, "email": "owner@example.com", "is_superadmin": False})
                if "SELECT DISTINCT l.id" in normalized:
                    return Result(all_rows=[{"id": local_id}])
                if normalized.startswith("DELETE FROM usuarios"):
                    return Result(one={"id": client_id})
                return Result()

        fake = FakeConnection()
        with (
            patch.object(admin_accounts, "is_configured", return_value=True),
            patch.object(admin_accounts, "connection", return_value=Context(fake)),
            patch.object(admin_accounts, "set_tenant_context"),
        ):
            result = admin_accounts.delete_admin_client(client_id)

        self.assertEqual(result["deletedBusinesses"], 1)
        self.assertTrue(any(sql.startswith("DELETE FROM locales") for sql in fake.statements))
        self.assertTrue(any(sql.startswith("DELETE FROM usuarios") for sql in fake.statements))


if __name__ == "__main__":
    unittest.main()
