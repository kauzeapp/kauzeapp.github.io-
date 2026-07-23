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
        self.assertEqual(clients[0]["subdominioEstado"], "pendiente")
        self.assertIsNone(clients[0]["subdominioUrl"])

    def test_duplicate_email_is_rejected(self):
        with (
            patch.object(admin_accounts, "is_configured", return_value=False),
            patch.object(admin_accounts, "read_local_db", side_effect=self._read),
            patch.object(admin_accounts, "write_local_db", side_effect=self._write),
        ):
            self._create()
            with self.assertRaisesRegex(ValueError, "correo ya esta registrado"):
                self._create()

    def test_admin_can_activate_and_suspend_subdomain(self):
        with (
            patch.object(admin_accounts, "is_configured", return_value=False),
            patch.object(admin_accounts, "read_local_db", side_effect=self._read),
            patch.object(admin_accounts, "write_local_db", side_effect=self._write),
        ):
            client_id = self._create()["client"]["id"]
            activated = admin_accounts.set_admin_client_subdomain(
                client_id,
                {"subdominio": "masterplansoluciones", "action": "activar"},
            )
            self.assertEqual(activated["subdominioEstado"], "activo")
            self.assertEqual(activated["subdominioUrl"], "https://masterplansoluciones.kauze.cl")
            suspended = admin_accounts.set_admin_client_subdomain(
                client_id,
                {"subdominio": "masterplansoluciones", "action": "suspender"},
            )

        self.assertEqual(suspended["subdominioEstado"], "suspendido")
        self.assertIsNone(suspended["subdominioUrl"])

    def test_reserved_and_duplicate_subdomains_are_rejected(self):
        with (
            patch.object(admin_accounts, "is_configured", return_value=False),
            patch.object(admin_accounts, "read_local_db", side_effect=self._read),
            patch.object(admin_accounts, "write_local_db", side_effect=self._write),
        ):
            first_id = self._create("first@example.com")["client"]["id"]
            second_id = self._create("second@example.com")["client"]["id"]
            admin_accounts.set_admin_client_subdomain(
                first_id, {"subdominio": "masterplan", "action": "activar"}
            )
            with self.assertRaisesRegex(ValueError, "ya esta en uso"):
                admin_accounts.set_admin_client_subdomain(
                    second_id, {"subdominio": "masterplan", "action": "activar"}
                )
            with self.assertRaisesRegex(ValueError, "reservado"):
                admin_accounts.set_admin_client_subdomain(
                    second_id, {"subdominio": "admin", "action": "activar"}
                )

    def test_suspended_account_cannot_publish_subdomain(self):
        with (
            patch.object(admin_accounts, "is_configured", return_value=False),
            patch.object(admin_accounts, "read_local_db", side_effect=self._read),
            patch.object(admin_accounts, "write_local_db", side_effect=self._write),
        ):
            client_id = self._create()["client"]["id"]
            self.local_db["subscriptions"][0]["estadoSuscripcion"] = "desactivado"
            with self.assertRaisesRegex(ValueError, "plan activo"):
                admin_accounts.set_admin_client_subdomain(
                    client_id, {"subdominio": "negocio-suspendido", "action": "activar"}
                )

    def test_database_subdomain_activation_reads_state_inside_tenant_context(self):
        client_id = "11111111-1111-4111-8111-111111111111"
        local_id = "22222222-2222-4222-8222-222222222222"
        operations = []

        class Result:
            def __init__(self, one=None):
                self.one = one

            def fetchone(self):
                return self.one

        class Context:
            def __init__(self, value):
                self.value = value

            def __enter__(self):
                return self.value

            def __exit__(self, *_args):
                return False

        class FakeConnection:
            row_factory = None

            def transaction(self):
                return Context(self)

            def execute(self, statement, _params=None):
                normalized = " ".join(statement.split())
                operations.append(normalized)
                if "FROM usuarios u" in normalized:
                    return Result(
                        one={
                            "id": client_id,
                            "legacy_subscription_state": "trial",
                            "legacy_subscription_expiry": None,
                            "local_id": local_id,
                            "direccion": "Atahualpa 2812",
                            "comuna": "Recoleta",
                            "ciudad": "Región Metropolitana",
                        }
                    )
                if "FROM estados_panel_local e" in normalized:
                    return Result(
                        one={
                            "panel_state": {"publicBookingEnabled": True},
                            "subscription_state": "trial",
                            "subscription_expiry": None,
                        }
                    )
                return Result()

        fake = FakeConnection()

        def tenant_context(_conn, selected_local_id, selected_user_id):
            operations.append(f"TENANT:{selected_local_id}:{selected_user_id}")

        with (
            patch.object(admin_accounts, "is_configured", return_value=True),
            patch.object(admin_accounts, "connection", return_value=Context(fake)),
            patch.object(admin_accounts, "set_tenant_context", side_effect=tenant_context),
        ):
            result = admin_accounts.set_admin_client_subdomain(
                client_id,
                {"subdominio": "negocio-listo", "action": "activar"},
            )

        tenant_index = operations.index(f"TENANT:{local_id}:{client_id}")
        state_index = next(
            index
            for index, operation in enumerate(operations)
            if "FROM estados_panel_local e" in operation
        )
        self.assertLess(tenant_index, state_index)
        self.assertEqual(result["subdominioEstado"], "activo")

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

    def test_reset_access_rejects_primary_admin_account(self):
        client_id = "11111111-1111-4111-8111-111111111111"

        class Result:
            def fetchone(self):
                return {
                    "id": client_id,
                    "nombre_completo": "Equipo KAUZE",
                    "email": "admin@example.com",
                }

        class Context:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def transaction(self):
                return self

            def execute(self, _statement, _params=None):
                return Result()

        with (
            patch.object(admin_accounts, "is_configured", return_value=True),
            patch.object(admin_accounts, "email_delivery_configured", return_value=True),
            patch.object(admin_accounts, "connection", return_value=Context()),
            patch.dict(
                admin_accounts.os.environ,
                {"KAUZE_BOOTSTRAP_EMAIL": "admin@example.com"},
                clear=False,
            ),
        ):
            with self.assertRaisesRegex(
                ValueError, "cuenta administradora principal"
            ):
                admin_accounts.reset_admin_client_access(client_id)


if __name__ == "__main__":
    unittest.main()
