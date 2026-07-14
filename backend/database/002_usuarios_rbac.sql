-- KAUZE · Fase 1 / Objetivo 1.1 / Tarea 2
-- Usuarios globales y control de acceso basado en roles (RBAC).
-- Requiere haber aplicado 001_categorias_locales.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS roles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  nombre TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  ambito TEXT NOT NULL,
  descripcion TEXT,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT roles_slug_formato
    CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  CONSTRAINT roles_ambito_valido
    CHECK (ambito IN ('global', 'local'))
);

CREATE TABLE IF NOT EXISTS usuarios (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  proveedor_auth_id TEXT UNIQUE,
  nombre_completo TEXT NOT NULL,
  email TEXT,
  telefono_whatsapp TEXT,
  estado TEXT NOT NULL DEFAULT 'activo',
  ultimo_acceso_en TIMESTAMPTZ,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT usuarios_contacto_requerido
    CHECK (email IS NOT NULL OR telefono_whatsapp IS NOT NULL),
  CONSTRAINT usuarios_email_formato
    CHECK (email IS NULL OR POSITION('@' IN email) > 1),
  CONSTRAINT usuarios_whatsapp_formato
    CHECK (
      telefono_whatsapp IS NULL
      OR telefono_whatsapp ~ '^\+[1-9][0-9]{7,14}$'
    ),
  CONSTRAINT usuarios_estado_valido
    CHECK (estado IN ('activo', 'inactivo', 'bloqueado'))
);

CREATE UNIQUE INDEX IF NOT EXISTS usuarios_email_unico_idx
  ON usuarios (LOWER(email))
  WHERE email IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS usuarios_whatsapp_unico_idx
  ON usuarios (telefono_whatsapp)
  WHERE telefono_whatsapp IS NOT NULL;

CREATE TABLE IF NOT EXISTS usuario_roles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario_id UUID NOT NULL,
  rol_id UUID NOT NULL,
  local_id UUID,
  otorgado_por UUID,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT usuario_roles_usuario_fk
    FOREIGN KEY (usuario_id)
    REFERENCES usuarios(id)
    ON DELETE CASCADE,
  CONSTRAINT usuario_roles_rol_fk
    FOREIGN KEY (rol_id)
    REFERENCES roles(id)
    ON DELETE RESTRICT,
  CONSTRAINT usuario_roles_local_fk
    FOREIGN KEY (local_id)
    REFERENCES locales(id)
    ON DELETE CASCADE,
  CONSTRAINT usuario_roles_otorgado_por_fk
    FOREIGN KEY (otorgado_por)
    REFERENCES usuarios(id)
    ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS usuario_roles_global_unico_idx
  ON usuario_roles (usuario_id, rol_id)
  WHERE local_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS usuario_roles_local_unico_idx
  ON usuario_roles (usuario_id, rol_id, local_id)
  WHERE local_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS usuario_roles_usuario_idx
  ON usuario_roles (usuario_id);

CREATE INDEX IF NOT EXISTS usuario_roles_local_idx
  ON usuario_roles (local_id)
  WHERE local_id IS NOT NULL;

CREATE OR REPLACE FUNCTION validar_ambito_usuario_rol()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  ambito_rol TEXT;
BEGIN
  SELECT ambito
  INTO ambito_rol
  FROM roles
  WHERE id = NEW.rol_id AND activo = TRUE;

  IF ambito_rol IS NULL THEN
    RAISE EXCEPTION 'El rol indicado no existe o está inactivo.';
  END IF;

  IF ambito_rol = 'global' AND NEW.local_id IS NOT NULL THEN
    RAISE EXCEPTION 'Un rol global no puede asociarse a un local.';
  END IF;

  IF ambito_rol = 'local' AND NEW.local_id IS NULL THEN
    RAISE EXCEPTION 'Un rol local debe asociarse a un local.';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS usuario_roles_ambito_trigger ON usuario_roles;
CREATE TRIGGER usuario_roles_ambito_trigger
BEFORE INSERT OR UPDATE OF rol_id, local_id ON usuario_roles
FOR EACH ROW
EXECUTE FUNCTION validar_ambito_usuario_rol();

DROP TRIGGER IF EXISTS roles_actualizado_en_trigger ON roles;
CREATE TRIGGER roles_actualizado_en_trigger
BEFORE UPDATE ON roles
FOR EACH ROW
EXECUTE FUNCTION actualizar_marca_de_tiempo();

DROP TRIGGER IF EXISTS usuarios_actualizado_en_trigger ON usuarios;
CREATE TRIGGER usuarios_actualizado_en_trigger
BEFORE UPDATE ON usuarios
FOR EACH ROW
EXECUTE FUNCTION actualizar_marca_de_tiempo();

INSERT INTO roles (nombre, slug, ambito, descripcion)
VALUES
  ('SuperAdmin', 'superadmin', 'global', 'Administración interna completa de Kauze.'),
  ('Dueño de local', 'dueno', 'local', 'Responsable principal de uno o más locales.'),
  ('Encargado', 'encargado', 'local', 'Administrador operativo de un local.'),
  ('Profesional', 'profesional', 'local', 'Barbero, estilista, técnica u otro profesional del local.'),
  ('Cliente final', 'cliente', 'global', 'Persona que reserva servicios en negocios Kauze.')
ON CONFLICT (slug) DO UPDATE
SET
  nombre = EXCLUDED.nombre,
  ambito = EXCLUDED.ambito,
  descripcion = EXCLUDED.descripcion,
  activo = TRUE,
  actualizado_en = NOW();

COMMIT;
