-- KAUZE · Base de aislamiento PostgreSQL por negocio (tenant).
--
-- El backend fija app.local_id dentro de cada transacción autenticada. Estas
-- políticas impiden que una conexión de aplicación no propietaria de las tablas
-- lea o modifique filas pertenecientes a otro negocio.

BEGIN;

CREATE OR REPLACE FUNCTION kauze_local_actual()
RETURNS UUID
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('app.local_id', TRUE), '')::UUID
$$;

ALTER TABLE profesionales ENABLE ROW LEVEL SECURITY;
ALTER TABLE profesionales FORCE ROW LEVEL SECURITY;
ALTER TABLE servicios ENABLE ROW LEVEL SECURITY;
ALTER TABLE servicios FORCE ROW LEVEL SECURITY;
ALTER TABLE profesional_servicios ENABLE ROW LEVEL SECURITY;
ALTER TABLE profesional_servicios FORCE ROW LEVEL SECURITY;
ALTER TABLE disponibilidad_semanal ENABLE ROW LEVEL SECURITY;
ALTER TABLE disponibilidad_semanal FORCE ROW LEVEL SECURITY;
ALTER TABLE bloqueos_agenda ENABLE ROW LEVEL SECURITY;
ALTER TABLE bloqueos_agenda FORCE ROW LEVEL SECURITY;
ALTER TABLE clientes ENABLE ROW LEVEL SECURITY;
ALTER TABLE clientes FORCE ROW LEVEL SECURITY;
ALTER TABLE reservas ENABLE ROW LEVEL SECURITY;
ALTER TABLE reservas FORCE ROW LEVEL SECURITY;
ALTER TABLE suscripciones_saas ENABLE ROW LEVEL SECURITY;
ALTER TABLE suscripciones_saas FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS profesionales_aislamiento_local ON profesionales;
CREATE POLICY profesionales_aislamiento_local ON profesionales
  USING (local_id = kauze_local_actual())
  WITH CHECK (local_id = kauze_local_actual());

DROP POLICY IF EXISTS servicios_aislamiento_local ON servicios;
CREATE POLICY servicios_aislamiento_local ON servicios
  USING (local_id = kauze_local_actual())
  WITH CHECK (local_id = kauze_local_actual());

DROP POLICY IF EXISTS profesional_servicios_aislamiento_local ON profesional_servicios;
CREATE POLICY profesional_servicios_aislamiento_local ON profesional_servicios
  USING (local_id = kauze_local_actual())
  WITH CHECK (local_id = kauze_local_actual());

DROP POLICY IF EXISTS disponibilidad_aislamiento_local ON disponibilidad_semanal;
CREATE POLICY disponibilidad_aislamiento_local ON disponibilidad_semanal
  USING (local_id = kauze_local_actual())
  WITH CHECK (local_id = kauze_local_actual());

DROP POLICY IF EXISTS bloqueos_aislamiento_local ON bloqueos_agenda;
CREATE POLICY bloqueos_aislamiento_local ON bloqueos_agenda
  USING (local_id = kauze_local_actual())
  WITH CHECK (local_id = kauze_local_actual());

DROP POLICY IF EXISTS clientes_aislamiento_local ON clientes;
CREATE POLICY clientes_aislamiento_local ON clientes
  USING (local_id = kauze_local_actual())
  WITH CHECK (local_id = kauze_local_actual());

DROP POLICY IF EXISTS reservas_aislamiento_local ON reservas;
CREATE POLICY reservas_aislamiento_local ON reservas
  USING (local_id = kauze_local_actual())
  WITH CHECK (local_id = kauze_local_actual());

DROP POLICY IF EXISTS suscripciones_aislamiento_local ON suscripciones_saas;
CREATE POLICY suscripciones_aislamiento_local ON suscripciones_saas
  USING (local_id = kauze_local_actual())
  WITH CHECK (local_id = kauze_local_actual());

COMMIT;
