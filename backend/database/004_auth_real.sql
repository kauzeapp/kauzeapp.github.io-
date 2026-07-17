-- KAUZE · Autenticación real y estado aislado por negocio.
-- Requiere 001_categorias_locales.sql y 002_usuarios_rbac.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS credenciales_password (
  usuario_id UUID PRIMARY KEY,
  password_hash TEXT NOT NULL,
  intentos_fallidos SMALLINT NOT NULL DEFAULT 0,
  bloqueado_hasta TIMESTAMPTZ,
  password_actualizada_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT credenciales_password_usuario_fk
    FOREIGN KEY (usuario_id)
    REFERENCES usuarios(id)
    ON DELETE CASCADE,
  CONSTRAINT credenciales_intentos_validos
    CHECK (intentos_fallidos BETWEEN 0 AND 50)
);

CREATE TABLE IF NOT EXISTS sesiones_auth (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario_id UUID NOT NULL,
  local_id UUID NOT NULL,
  rol_id UUID NOT NULL,
  token_hash CHAR(64) NOT NULL UNIQUE,
  user_agent_hash CHAR(64),
  expira_en TIMESTAMPTZ NOT NULL,
  ultimo_uso_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  revocada_en TIMESTAMPTZ,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT sesiones_usuario_fk
    FOREIGN KEY (usuario_id)
    REFERENCES usuarios(id)
    ON DELETE CASCADE,
  CONSTRAINT sesiones_local_fk
    FOREIGN KEY (local_id)
    REFERENCES locales(id)
    ON DELETE CASCADE,
  CONSTRAINT sesiones_rol_fk
    FOREIGN KEY (rol_id)
    REFERENCES roles(id)
    ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS sesiones_auth_usuario_idx
  ON sesiones_auth (usuario_id, expira_en);

CREATE INDEX IF NOT EXISTS sesiones_auth_local_idx
  ON sesiones_auth (local_id, expira_en);

CREATE TABLE IF NOT EXISTS tokens_restablecimiento_password (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario_id UUID NOT NULL,
  token_hash CHAR(64) NOT NULL UNIQUE,
  expira_en TIMESTAMPTZ NOT NULL,
  usado_en TIMESTAMPTZ,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT tokens_restablecimiento_usuario_fk
    FOREIGN KEY (usuario_id)
    REFERENCES usuarios(id)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS tokens_restablecimiento_usuario_idx
  ON tokens_restablecimiento_password (usuario_id, expira_en);

CREATE TABLE IF NOT EXISTS estados_panel_local (
  local_id UUID PRIMARY KEY,
  estado JSONB NOT NULL DEFAULT '{}'::jsonb,
  version BIGINT NOT NULL DEFAULT 1,
  actualizado_por UUID,
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT estados_panel_local_fk
    FOREIGN KEY (local_id)
    REFERENCES locales(id)
    ON DELETE CASCADE,
  CONSTRAINT estados_panel_usuario_fk
    FOREIGN KEY (actualizado_por)
    REFERENCES usuarios(id)
    ON DELETE SET NULL,
  CONSTRAINT estados_panel_version_valida
    CHECK (version > 0),
  CONSTRAINT estados_panel_objeto_valido
    CHECK (jsonb_typeof(estado) = 'object')
);

COMMIT;
