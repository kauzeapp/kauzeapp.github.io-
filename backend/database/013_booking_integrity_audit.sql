-- KAUZE · Integridad de agenda y trazabilidad de reservas.

BEGIN;

CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE reservas
  ADD COLUMN IF NOT EXISTS solicitud_id UUID,
  ADD COLUMN IF NOT EXISTS version BIGINT NOT NULL DEFAULT 1;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'reservas_id_local_unico'
  ) THEN
    ALTER TABLE reservas
      ADD CONSTRAINT reservas_id_local_unico UNIQUE (id, local_id);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'reservas_duracion_maxima'
  ) THEN
    ALTER TABLE reservas
      ADD CONSTRAINT reservas_duracion_maxima
      CHECK (fin_en <= inicio_en + INTERVAL '24 hours');
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'reservas_version_valida'
  ) THEN
    ALTER TABLE reservas
      ADD CONSTRAINT reservas_version_valida CHECK (version > 0);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'reservas_profesional_sin_traslape'
  ) THEN
    ALTER TABLE reservas
      ADD CONSTRAINT reservas_profesional_sin_traslape
      EXCLUDE USING gist (
        local_id WITH =,
        profesional_id WITH =,
        tstzrange(inicio_en, fin_en, '[)') WITH &&
      )
      WHERE (
        profesional_id IS NOT NULL
        AND estado IN ('pendiente', 'confirmada')
      );
  END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS reservas_solicitud_unica_idx
  ON reservas (local_id, solicitud_id)
  WHERE solicitud_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS eventos_reserva (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  local_id UUID NOT NULL,
  reserva_id UUID NOT NULL,
  tipo TEXT NOT NULL,
  actor_tipo TEXT NOT NULL DEFAULT 'sistema',
  actor_id UUID,
  datos JSONB NOT NULL DEFAULT '{}'::jsonb,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT eventos_reserva_reserva_fk
    FOREIGN KEY (reserva_id, local_id)
    REFERENCES reservas(id, local_id)
    ON DELETE CASCADE,
  CONSTRAINT eventos_reserva_actor_fk
    FOREIGN KEY (actor_id)
    REFERENCES usuarios(id)
    ON DELETE SET NULL,
  CONSTRAINT eventos_reserva_tipo_valido
    CHECK (tipo ~ '^[a-z][a-z0-9_]{2,49}$'),
  CONSTRAINT eventos_reserva_actor_tipo_valido
    CHECK (actor_tipo IN ('sistema', 'dueno', 'cliente', 'automatizacion')),
  CONSTRAINT eventos_reserva_datos_objeto
    CHECK (jsonb_typeof(datos) = 'object')
);

CREATE INDEX IF NOT EXISTS eventos_reserva_historial_idx
  ON eventos_reserva (local_id, reserva_id, creado_en DESC);

ALTER TABLE eventos_reserva ENABLE ROW LEVEL SECURITY;
ALTER TABLE eventos_reserva FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS eventos_reserva_lectura_local ON eventos_reserva;
CREATE POLICY eventos_reserva_lectura_local ON eventos_reserva
  FOR SELECT
  USING (local_id = kauze_local_actual());

DROP POLICY IF EXISTS eventos_reserva_insercion_local ON eventos_reserva;
CREATE POLICY eventos_reserva_insercion_local ON eventos_reserva
  FOR INSERT
  WITH CHECK (local_id = kauze_local_actual());

GRANT SELECT, INSERT ON TABLE eventos_reserva TO kauze_tenant_runtime;

COMMIT;
