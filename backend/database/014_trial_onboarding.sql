-- KAUZE · Acceso inicial verificable para negocios en trial.

BEGIN;

ALTER TABLE tokens_restablecimiento_password
  ADD COLUMN IF NOT EXISTS proposito TEXT NOT NULL DEFAULT 'recuperacion';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'tokens_password_proposito_valido'
  ) THEN
    ALTER TABLE tokens_restablecimiento_password
      ADD CONSTRAINT tokens_password_proposito_valido
      CHECK (proposito IN ('recuperacion', 'acceso_inicial'));
  END IF;
END
$$;

INSERT INTO categorias (nombre, slug, descripcion)
VALUES
  ('Tatuajes', 'tatuajes', 'Estudios de tatuajes y arte corporal.'),
  ('Talleres', 'talleres', 'Talleres mecánicos y servicios automotrices.')
ON CONFLICT (slug) DO UPDATE
SET nombre = EXCLUDED.nombre,
    descripcion = EXCLUDED.descripcion,
    activo = TRUE,
    actualizado_en = NOW();

COMMIT;
