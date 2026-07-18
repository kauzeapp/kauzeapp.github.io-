-- KAUZE · Suscripciones MVP / Fase 1
-- Agregar campo categoria_slug a usuarios para registrar el rubro del negocio.

BEGIN;

ALTER TABLE usuarios 
  ADD COLUMN IF NOT EXISTS categoria_slug TEXT;

COMMIT;
