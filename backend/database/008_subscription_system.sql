-- KAUZE · Suscripciones MVP / Fase 1
-- Extensión de la tabla usuarios para manejar el flujo de planes y suscripciones de barberos/dueños.

BEGIN;

ALTER TABLE usuarios 
  ADD COLUMN IF NOT EXISTS plan_tipo TEXT CONSTRAINT check_plan_tipo CHECK (plan_tipo IN ('trial', 'mensual', 'trimestral', 'anual')),
  ADD COLUMN IF NOT EXISTS estado_suscripcion TEXT CONSTRAINT check_estado_suscripcion CHECK (estado_suscripcion IN ('trial', 'activo', 'en_mora', 'desactivado')),
  ADD COLUMN IF NOT EXISTS fecha_vencimiento TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS subdominio TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS requiere_aprobacion BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS nombre_barberia TEXT;

COMMIT;
