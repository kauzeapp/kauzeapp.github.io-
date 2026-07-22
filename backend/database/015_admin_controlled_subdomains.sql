-- KAUZE · Activación administrativa de subdominios públicos.

BEGIN;

ALTER TABLE locales
  ADD COLUMN IF NOT EXISTS subdominio_estado TEXT NOT NULL DEFAULT 'pendiente',
  ADD COLUMN IF NOT EXISTS subdominio_activado_en TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS subdominio_activado_por UUID;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'locales_subdominio_estado_valido'
  ) THEN
    ALTER TABLE locales
      ADD CONSTRAINT locales_subdominio_estado_valido
      CHECK (subdominio_estado IN ('pendiente', 'activo', 'suspendido'));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'locales_subdominio_activado_por_fk'
  ) THEN
    ALTER TABLE locales
      ADD CONSTRAINT locales_subdominio_activado_por_fk
      FOREIGN KEY (subdominio_activado_por)
      REFERENCES usuarios(id)
      ON DELETE SET NULL;
  END IF;
END
$$;

-- Todo negocio, nuevo o existente, debe ser aprobado expresamente desde Admin.
UPDATE locales
SET subdominio_estado = 'pendiente',
    subdominio_activado_en = NULL,
    subdominio_activado_por = NULL;

CREATE INDEX IF NOT EXISTS locales_subdominio_estado_idx
  ON locales (subdominio_estado, slug);

COMMIT;
