-- KAUZE · Rol efectivo de aplicación para datos privados de cada negocio.
--
-- Railway mantiene la cuenta propietaria para migraciones. Cada operación del
-- panel usa este rol NOLOGIN y NOBYPASSRLS mediante SET LOCAL ROLE, por lo que
-- las políticas RLS también se respetan cuando DATABASE_URL pertenece al dueño
-- de las tablas o a un superusuario administrado por el proveedor.

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kauze_tenant_runtime') THEN
    CREATE ROLE kauze_tenant_runtime NOLOGIN NOINHERIT NOBYPASSRLS;
  END IF;
END
$$;

ALTER ROLE kauze_tenant_runtime NOLOGIN NOINHERIT NOBYPASSRLS;
GRANT kauze_tenant_runtime TO CURRENT_USER;
GRANT USAGE ON SCHEMA public TO kauze_tenant_runtime;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
  profesionales,
  servicios,
  profesional_servicios,
  disponibilidad_semanal,
  bloqueos_agenda,
  clientes,
  reservas,
  suscripciones_saas,
  estados_panel_local
TO kauze_tenant_runtime;

ALTER TABLE estados_panel_local ENABLE ROW LEVEL SECURITY;
ALTER TABLE estados_panel_local FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS estados_panel_aislamiento_local ON estados_panel_local;
CREATE POLICY estados_panel_aislamiento_local ON estados_panel_local
  USING (local_id = kauze_local_actual())
  WITH CHECK (local_id = kauze_local_actual());

COMMIT;
