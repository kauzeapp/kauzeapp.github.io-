-- KAUZE · Fotografías de perfil personales.
-- El logo del negocio continúa separado en locales.logo_url / estado del panel.

BEGIN;

ALTER TABLE usuarios
  ADD COLUMN IF NOT EXISTS foto_perfil_url TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'usuarios_foto_perfil_tamano'
  ) THEN
    ALTER TABLE usuarios
      ADD CONSTRAINT usuarios_foto_perfil_tamano
      CHECK (
        foto_perfil_url IS NULL
        OR CHAR_LENGTH(foto_perfil_url) <= 750000
      );
  END IF;
END;
$$;

COMMIT;
