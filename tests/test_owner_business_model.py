import unittest
from pathlib import Path

from backend.onboarding import business_slug, normalize_google_identity
from backend.tenant import _uuid_text


ROOT = Path(__file__).resolve().parents[1]
MODEL_SQL = (ROOT / "backend" / "database" / "010_owner_business_model.sql").read_text(
    encoding="utf-8"
)
RLS_SQL = (ROOT / "backend" / "database" / "011_tenant_rls_foundation.sql").read_text(
    encoding="utf-8"
)
AUTH_SOURCE = (ROOT / "backend" / "auth.py").read_text(encoding="utf-8")
MIGRATE_SOURCE = (ROOT / "backend" / "migrate.py").read_text(encoding="utf-8")
TENANT_SOURCE = (ROOT / "backend" / "tenant.py").read_text(encoding="utf-8")
RUNTIME_ROLE_SQL = (
    ROOT / "backend" / "database" / "012_tenant_runtime_role.sql"
).read_text(encoding="utf-8")
BOOKING_INTEGRITY_SQL = (
    ROOT / "backend" / "database" / "013_booking_integrity_audit.sql"
).read_text(encoding="utf-8")


class OwnerBusinessModelTests(unittest.TestCase):
    def test_professionals_no_longer_require_user_accounts(self):
        self.assertIn("ALTER COLUMN usuario_id DROP NOT NULL", MODEL_SQL)
        self.assertIn("DROP TRIGGER IF EXISTS profesionales_rol_trigger", MODEL_SQL)
        self.assertIn("WHERE usuario_id IS NOT NULL", MODEL_SQL)

    def test_business_login_is_restricted_to_owner(self):
        self.assertNotIn("r.slug IN ('dueno', 'encargado', 'profesional')", AUTH_SOURCE)
        self.assertGreaterEqual(AUTH_SOURCE.count("r.slug = 'dueno'"), 2)

    def test_clients_are_operational_records_without_user_id(self):
        clients_block = MODEL_SQL.split("CREATE TABLE IF NOT EXISTS clientes", 1)[1]
        clients_block = clients_block.split("CREATE TABLE IF NOT EXISTS reservas", 1)[0]
        self.assertNotIn("usuario_id", clients_block)
        self.assertIn("local_id UUID NOT NULL", clients_block)

    def test_reservations_cannot_mix_businesses(self):
        self.assertIn("FOREIGN KEY (cliente_id, local_id)", MODEL_SQL)
        self.assertIn("FOREIGN KEY (servicio_id, local_id)", MODEL_SQL)
        self.assertIn("FOREIGN KEY (profesional_id, local_id)", MODEL_SQL)

    def test_subscription_belongs_to_business(self):
        subscriptions_block = MODEL_SQL.split(
            "CREATE TABLE IF NOT EXISTS suscripciones_saas", 1
        )[1]
        self.assertIn("local_id UUID NOT NULL UNIQUE", subscriptions_block)
        self.assertIn("estado_factura TEXT NOT NULL DEFAULT 'PENDIENTE'", subscriptions_block)
        self.assertIn("('PENDIENTE', 'EMITIDA', 'EXENTA')", subscriptions_block)

    def test_rls_covers_every_new_operational_table(self):
        for table in ("profesionales", "servicios", "clientes", "reservas", "suscripciones_saas"):
            self.assertIn(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY", RLS_SQL)
            self.assertIn(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY", RLS_SQL)
            self.assertIn(f"local_id = kauze_local_actual()", RLS_SQL)

    def test_migration_creates_internal_backups_first(self):
        backup_position = MODEL_SQL.index("CREATE SCHEMA IF NOT EXISTS kauze_backups")
        first_alter_position = MODEL_SQL.index("ALTER TABLE usuarios")
        self.assertLess(backup_position, first_alter_position)
        for table in (
            "usuarios",
            "usuario_roles",
            "locales",
            "profesionales",
            "estados_panel_local",
        ):
            self.assertIn(f"pre_owner_model_{table}", MODEL_SQL)

    def test_deploy_runs_a_negative_cross_tenant_test(self):
        self.assertIn("def verify_tenant_row_isolation", MIGRATE_SOURCE)
        self.assertIn("el negocio B pudo leer", MIGRATE_SOURCE)
        self.assertIn("el negocio B pudo escribir", MIGRATE_SOURCE)
        self.assertIn("verify_tenant_row_isolation(conn)", MIGRATE_SOURCE)

    def test_business_connections_drop_to_limited_role(self):
        self.assertIn("SET LOCAL ROLE", TENANT_SOURCE)
        self.assertIn("kauze_tenant_runtime", TENANT_SOURCE)
        self.assertIn("NOLOGIN NOINHERIT NOBYPASSRLS", RUNTIME_ROLE_SQL)
        self.assertIn(
            "ALTER TABLE estados_panel_local FORCE ROW LEVEL SECURITY",
            RUNTIME_ROLE_SQL,
        )

    def test_database_prevents_double_booking_and_duplicate_requests(self):
        self.assertIn("reservas_profesional_sin_traslape", BOOKING_INTEGRITY_SQL)
        self.assertIn("tstzrange(inicio_en, fin_en, '[)') WITH &&", BOOKING_INTEGRITY_SQL)
        self.assertIn("reservas_solicitud_unica_idx", BOOKING_INTEGRITY_SQL)

    def test_booking_history_is_tenant_protected_and_append_only(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS eventos_reserva", BOOKING_INTEGRITY_SQL)
        self.assertIn("ALTER TABLE eventos_reserva FORCE ROW LEVEL SECURITY", BOOKING_INTEGRITY_SQL)
        self.assertIn("GRANT SELECT, INSERT ON TABLE eventos_reserva", BOOKING_INTEGRITY_SQL)
        self.assertNotIn("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE eventos_reserva", BOOKING_INTEGRITY_SQL)

    def test_tenant_id_must_be_a_real_uuid(self):
        expected = "550e8400-e29b-41d4-a716-446655440000"
        self.assertEqual(_uuid_text(expected, "local_id"), expected)
        with self.assertRaises(ValueError):
            _uuid_text("negocio-ajeno", "local_id")

    def test_google_owner_requires_verified_email(self):
        identity = normalize_google_identity(
            {
                "sub": "google-owner-123",
                "email": "Dueno@Example.com",
                "email_verified": True,
                "name": "Dueño Demo",
                "picture": "https://lh3.googleusercontent.com/a/demo",
            }
        )
        self.assertEqual(identity["email"], "dueno@example.com")
        with self.assertRaises(ValueError):
            normalize_google_identity(
                {
                    "sub": "google-owner-123",
                    "email": "dueno@example.com",
                    "email_verified": False,
                }
            )

    def test_business_slug_is_safe_and_readable(self):
        self.assertEqual(business_slug("Barbería Don Juan"), "barberia-don-juan")


if __name__ == "__main__":
    unittest.main()
