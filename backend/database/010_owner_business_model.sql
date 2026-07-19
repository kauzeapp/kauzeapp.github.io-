-- KAUZE · Modelo definitivo de identidad y operación multi-negocio.
--
-- Principios:
--   * Solo SuperAdmin y Dueño de Local son usuarios autenticados.
--   * Los profesionales son fichas internas del negocio, sin login obligatorio.
--   * Los clientes reservan sin cuenta y quedan registrados por negocio.
--   * La suscripción pertenece al negocio, no al usuario.
--
-- Esta migración es compatible con los datos existentes. Las columnas antiguas
-- de suscripción en usuarios se conservan temporalmente para permitir una
-- transición controlada del panel Admin.

BEGIN;

-- Respaldo lógico previo sin depender del plan Pro de Railway. Si cualquier
-- instrucción posterior falla, PostgreSQL revierte también esta migración y los
-- datos originales permanecen intactos. Si termina bien, estas copias quedan
-- disponibles para una restauración manual controlada.
CREATE SCHEMA IF NOT EXISTS kauze_backups;

CREATE TABLE IF NOT EXISTS kauze_backups.pre_owner_model_usuarios
  AS TABLE usuarios WITH DATA;
CREATE TABLE IF NOT EXISTS kauze_backups.pre_owner_model_usuario_roles
  AS TABLE usuario_roles WITH DATA;
CREATE TABLE IF NOT EXISTS kauze_backups.pre_owner_model_locales
  AS TABLE locales WITH DATA;
CREATE TABLE IF NOT EXISTS kauze_backups.pre_owner_model_profesionales
  AS TABLE profesionales WITH DATA;
CREATE TABLE IF NOT EXISTS kauze_backups.pre_owner_model_estados_panel_local
  AS TABLE estados_panel_local WITH DATA;

ALTER TABLE usuarios
  ADD COLUMN IF NOT EXISTS proveedor_auth TEXT NOT NULL DEFAULT 'password',
  ADD COLUMN IF NOT EXISTS email_verificado BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE usuarios
SET proveedor_auth = CASE
  WHEN proveedor_auth_id IS NOT NULL THEN 'google'
  ELSE 'password'
END
WHERE proveedor_auth IS NULL OR proveedor_auth = '';

ALTER TABLE usuarios
  DROP CONSTRAINT IF EXISTS usuarios_proveedor_auth_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS usuarios_proveedor_identidad_unico_idx
  ON usuarios (proveedor_auth, proveedor_auth_id)
  WHERE proveedor_auth_id IS NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'usuarios_proveedor_auth_valido'
  ) THEN
    ALTER TABLE usuarios
      ADD CONSTRAINT usuarios_proveedor_auth_valido
      CHECK (proveedor_auth IN ('password', 'google'));
  END IF;
END;
$$;

ALTER TABLE locales
  ADD COLUMN IF NOT EXISTS creado_por UUID,
  ADD COLUMN IF NOT EXISTS onboarding_estado TEXT NOT NULL DEFAULT 'completo';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'locales_creado_por_fk'
  ) THEN
    ALTER TABLE locales
      ADD CONSTRAINT locales_creado_por_fk
      FOREIGN KEY (creado_por)
      REFERENCES usuarios(id)
      ON DELETE SET NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'locales_onboarding_estado_valido'
  ) THEN
    ALTER TABLE locales
      ADD CONSTRAINT locales_onboarding_estado_valido
      CHECK (onboarding_estado IN ('pendiente', 'en_progreso', 'completo'));
  END IF;
END;
$$;

UPDATE locales l
SET creado_por = (
  SELECT ur.usuario_id
  FROM usuario_roles ur
  INNER JOIN roles r ON r.id = ur.rol_id
  WHERE ur.local_id = l.id
    AND r.slug = 'dueno'
  ORDER BY ur.creado_en
  LIMIT 1
)
WHERE l.creado_por IS NULL;

-- Un profesional deja de depender de una cuenta de usuario.
DROP TRIGGER IF EXISTS profesionales_rol_trigger ON profesionales;
DROP FUNCTION IF EXISTS validar_usuario_profesional();

ALTER TABLE profesionales
  ADD COLUMN IF NOT EXISTS nombre TEXT,
  ADD COLUMN IF NOT EXISTS foto_url TEXT,
  ADD COLUMN IF NOT EXISTS telefono_contacto TEXT,
  ADD COLUMN IF NOT EXISTS email_contacto TEXT,
  ADD COLUMN IF NOT EXISTS comision_tipo TEXT NOT NULL DEFAULT 'ninguna',
  ADD COLUMN IF NOT EXISTS comision_porcentaje NUMERIC(5, 2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS comision_monto_fijo INTEGER NOT NULL DEFAULT 0;

UPDATE profesionales p
SET nombre = COALESCE(
  NULLIF(TRIM(p.nombre), ''),
  NULLIF(TRIM(p.nombre_publico), ''),
  (
    SELECT NULLIF(TRIM(u.nombre_completo), '')
    FROM usuarios u
    WHERE u.id = p.usuario_id
  ),
  'Profesional'
)
WHERE p.nombre IS NULL OR TRIM(p.nombre) = '';

ALTER TABLE profesionales
  ALTER COLUMN nombre SET NOT NULL,
  ALTER COLUMN usuario_id DROP NOT NULL,
  DROP CONSTRAINT IF EXISTS profesionales_local_usuario_unico,
  DROP CONSTRAINT IF EXISTS profesionales_usuario_fk;

ALTER TABLE profesionales
  ADD CONSTRAINT profesionales_usuario_fk
  FOREIGN KEY (usuario_id)
  REFERENCES usuarios(id)
  ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS profesionales_local_usuario_legacy_unico_idx
  ON profesionales (local_id, usuario_id)
  WHERE usuario_id IS NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'profesionales_comision_tipo_valido'
  ) THEN
    ALTER TABLE profesionales
      ADD CONSTRAINT profesionales_comision_tipo_valido
      CHECK (comision_tipo IN ('ninguna', 'porcentaje', 'fijo'));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'profesionales_comision_valida'
  ) THEN
    ALTER TABLE profesionales
      ADD CONSTRAINT profesionales_comision_valida
      CHECK (
        (comision_tipo = 'ninguna' AND comision_porcentaje = 0 AND comision_monto_fijo = 0)
        OR (comision_tipo = 'porcentaje' AND comision_porcentaje > 0 AND comision_porcentaje <= 100 AND comision_monto_fijo = 0)
        OR (comision_tipo = 'fijo' AND comision_monto_fijo > 0 AND comision_porcentaje = 0)
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'profesionales_foto_tamano'
  ) THEN
    ALTER TABLE profesionales
      ADD CONSTRAINT profesionales_foto_tamano
      CHECK (foto_url IS NULL OR CHAR_LENGTH(foto_url) <= 750000);
  END IF;
END;
$$;

-- Registro operativo del cliente. No contiene usuario_id a propósito.
CREATE TABLE IF NOT EXISTS clientes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  local_id UUID NOT NULL,
  nombre TEXT NOT NULL,
  telefono_whatsapp TEXT,
  email TEXT,
  notas_privadas TEXT,
  estado TEXT NOT NULL DEFAULT 'activo',
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT clientes_local_fk
    FOREIGN KEY (local_id)
    REFERENCES locales(id)
    ON DELETE CASCADE,
  CONSTRAINT clientes_id_local_unico
    UNIQUE (id, local_id),
  CONSTRAINT clientes_contacto_requerido
    CHECK (telefono_whatsapp IS NOT NULL OR email IS NOT NULL),
  CONSTRAINT clientes_whatsapp_formato
    CHECK (
      telefono_whatsapp IS NULL
      OR telefono_whatsapp ~ '^\\+[1-9][0-9]{7,14}$'
    ),
  CONSTRAINT clientes_email_formato
    CHECK (email IS NULL OR POSITION('@' IN email) > 1),
  CONSTRAINT clientes_estado_valido
    CHECK (estado IN ('activo', 'inactivo', 'bloqueado'))
);

CREATE UNIQUE INDEX IF NOT EXISTS clientes_local_whatsapp_unico_idx
  ON clientes (local_id, telefono_whatsapp)
  WHERE telefono_whatsapp IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS clientes_local_email_unico_idx
  ON clientes (local_id, LOWER(email))
  WHERE email IS NOT NULL;

CREATE INDEX IF NOT EXISTS clientes_local_estado_idx
  ON clientes (local_id, estado);

-- Reserva normalizada y protegida por claves compuestas del mismo negocio.
CREATE TABLE IF NOT EXISTS reservas (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  local_id UUID NOT NULL,
  cliente_id UUID NOT NULL,
  servicio_id UUID NOT NULL,
  profesional_id UUID,
  inicio_en TIMESTAMPTZ NOT NULL,
  fin_en TIMESTAMPTZ NOT NULL,
  estado TEXT NOT NULL DEFAULT 'pendiente',
  origen TEXT NOT NULL DEFAULT 'web',
  notas_cliente TEXT,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT reservas_local_fk
    FOREIGN KEY (local_id)
    REFERENCES locales(id)
    ON DELETE CASCADE,
  CONSTRAINT reservas_cliente_fk
    FOREIGN KEY (cliente_id, local_id)
    REFERENCES clientes(id, local_id)
    ON DELETE RESTRICT,
  CONSTRAINT reservas_servicio_fk
    FOREIGN KEY (servicio_id, local_id)
    REFERENCES servicios(id, local_id)
    ON DELETE RESTRICT,
  CONSTRAINT reservas_profesional_fk
    FOREIGN KEY (profesional_id, local_id)
    REFERENCES profesionales(id, local_id)
    ON DELETE RESTRICT,
  CONSTRAINT reservas_periodo_valido
    CHECK (fin_en > inicio_en),
  CONSTRAINT reservas_estado_valido
    CHECK (estado IN ('pendiente', 'confirmada', 'atendida', 'cancelada', 'no_asistio')),
  CONSTRAINT reservas_origen_valido
    CHECK (origen IN ('web', 'panel', 'walk_in', 'importada'))
);

CREATE INDEX IF NOT EXISTS reservas_local_inicio_idx
  ON reservas (local_id, inicio_en);

CREATE INDEX IF NOT EXISTS reservas_profesional_inicio_idx
  ON reservas (profesional_id, inicio_en)
  WHERE profesional_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS reservas_cliente_inicio_idx
  ON reservas (cliente_id, inicio_en DESC);

-- La suscripción y la facturación pertenecen al negocio.
CREATE TABLE IF NOT EXISTS suscripciones_saas (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  local_id UUID NOT NULL UNIQUE,
  plan_tipo TEXT NOT NULL DEFAULT 'trial',
  estado TEXT NOT NULL DEFAULT 'trial',
  inicio_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  trial_fin_en TIMESTAMPTZ,
  periodo_fin_en TIMESTAMPTZ,
  proveedor_pago TEXT,
  cliente_pago_id TEXT,
  suscripcion_pago_id TEXT,
  estado_factura TEXT NOT NULL DEFAULT 'PENDIENTE',
  ultima_factura_folio TEXT,
  ultima_factura_emitida_en TIMESTAMPTZ,
  moneda CHAR(3) NOT NULL DEFAULT 'CLP',
  monto_periodo_clp INTEGER NOT NULL DEFAULT 0,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT suscripciones_local_fk
    FOREIGN KEY (local_id)
    REFERENCES locales(id)
    ON DELETE CASCADE,
  CONSTRAINT suscripciones_plan_valido
    CHECK (plan_tipo IN ('trial', 'mensual', 'trimestral', 'anual')),
  CONSTRAINT suscripciones_estado_valido
    CHECK (estado IN ('trial', 'activo', 'en_mora', 'cancelado', 'desactivado')),
  CONSTRAINT suscripciones_estado_factura_valido
    CHECK (estado_factura IN ('PENDIENTE', 'EMITIDA', 'EXENTA')),
  CONSTRAINT suscripciones_moneda_clp
    CHECK (moneda = 'CLP'),
  CONSTRAINT suscripciones_monto_valido
    CHECK (monto_periodo_clp >= 0)
);

INSERT INTO suscripciones_saas (
  local_id,
  plan_tipo,
  estado,
  inicio_en,
  trial_fin_en,
  periodo_fin_en
)
SELECT DISTINCT ON (l.id)
  l.id,
  COALESCE(u.plan_tipo, 'trial'),
  COALESCE(u.estado_suscripcion, 'trial'),
  COALESCE(u.creado_en, NOW()),
  CASE WHEN COALESCE(u.plan_tipo, 'trial') = 'trial' THEN u.fecha_vencimiento END,
  u.fecha_vencimiento
FROM locales l
INNER JOIN usuario_roles ur ON ur.local_id = l.id
INNER JOIN roles r ON r.id = ur.rol_id AND r.slug = 'dueno'
INNER JOIN usuarios u ON u.id = ur.usuario_id
WHERE u.plan_tipo IS NOT NULL
ORDER BY l.id, ur.creado_en
ON CONFLICT (local_id) DO NOTHING;

DROP TRIGGER IF EXISTS clientes_actualizado_en_trigger ON clientes;
CREATE TRIGGER clientes_actualizado_en_trigger
BEFORE UPDATE ON clientes
FOR EACH ROW
EXECUTE FUNCTION actualizar_marca_de_tiempo();

DROP TRIGGER IF EXISTS reservas_actualizado_en_trigger ON reservas;
CREATE TRIGGER reservas_actualizado_en_trigger
BEFORE UPDATE ON reservas
FOR EACH ROW
EXECUTE FUNCTION actualizar_marca_de_tiempo();

DROP TRIGGER IF EXISTS suscripciones_actualizado_en_trigger ON suscripciones_saas;
CREATE TRIGGER suscripciones_actualizado_en_trigger
BEFORE UPDATE ON suscripciones_saas
FOR EACH ROW
EXECUTE FUNCTION actualizar_marca_de_tiempo();

COMMENT ON COLUMN profesionales.usuario_id IS
  'Compatibilidad con profesionales antiguos. Las nuevas fichas internas deben dejar este campo en NULL.';

COMMENT ON TABLE clientes IS
  'Clientes operativos por negocio. Reservar no crea una cuenta autenticada.';

COMMENT ON TABLE suscripciones_saas IS
  'Plan y estado de cobro asociados al negocio, nunca a un trabajador o cliente.';

COMMENT ON SCHEMA kauze_backups IS
  'Copias lógicas previas a migraciones estructurales de Kauze. No exponer desde la aplicación.';

COMMIT;
