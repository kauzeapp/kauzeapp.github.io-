-- KAUZE · Fase 1 / Objetivo 1.1 / Tarea 3
-- Servicios, perfiles operativos de profesionales y reglas de agenda.
-- Requiere 001_categorias_locales.sql y 002_usuarios_rbac.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS profesionales (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  local_id UUID NOT NULL,
  usuario_id UUID NOT NULL,
  nombre_publico TEXT,
  especialidad TEXT,
  biografia TEXT,
  color_agenda TEXT,
  acepta_reservas BOOLEAN NOT NULL DEFAULT TRUE,
  estado TEXT NOT NULL DEFAULT 'activo',
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT profesionales_local_fk
    FOREIGN KEY (local_id)
    REFERENCES locales(id)
    ON DELETE CASCADE,
  CONSTRAINT profesionales_usuario_fk
    FOREIGN KEY (usuario_id)
    REFERENCES usuarios(id)
    ON DELETE CASCADE,
  CONSTRAINT profesionales_local_usuario_unico
    UNIQUE (local_id, usuario_id),
  CONSTRAINT profesionales_id_local_unico
    UNIQUE (id, local_id),
  CONSTRAINT profesionales_estado_valido
    CHECK (estado IN ('activo', 'inactivo', 'suspendido')),
  CONSTRAINT profesionales_color_agenda_formato
    CHECK (color_agenda IS NULL OR color_agenda ~ '^#[0-9A-Fa-f]{6}$')
);

CREATE TABLE IF NOT EXISTS servicios (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  local_id UUID NOT NULL,
  nombre TEXT NOT NULL,
  slug TEXT NOT NULL,
  descripcion TEXT,
  duracion_minutos SMALLINT NOT NULL,
  precio_clp INTEGER NOT NULL,
  moneda CHAR(3) NOT NULL DEFAULT 'CLP',
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT servicios_local_fk
    FOREIGN KEY (local_id)
    REFERENCES locales(id)
    ON DELETE CASCADE,
  CONSTRAINT servicios_local_slug_unico
    UNIQUE (local_id, slug),
  CONSTRAINT servicios_id_local_unico
    UNIQUE (id, local_id),
  CONSTRAINT servicios_slug_formato
    CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  CONSTRAINT servicios_duracion_valida
    CHECK (duracion_minutos BETWEEN 5 AND 1440),
  CONSTRAINT servicios_precio_valido
    CHECK (precio_clp >= 0),
  CONSTRAINT servicios_moneda_clp
    CHECK (moneda = 'CLP')
);

CREATE TABLE IF NOT EXISTS profesional_servicios (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  local_id UUID NOT NULL,
  profesional_id UUID NOT NULL,
  servicio_id UUID NOT NULL,
  duracion_personalizada_minutos SMALLINT,
  precio_personalizado_clp INTEGER,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT profesional_servicios_profesional_fk
    FOREIGN KEY (profesional_id, local_id)
    REFERENCES profesionales(id, local_id)
    ON DELETE CASCADE,
  CONSTRAINT profesional_servicios_servicio_fk
    FOREIGN KEY (servicio_id, local_id)
    REFERENCES servicios(id, local_id)
    ON DELETE CASCADE,
  CONSTRAINT profesional_servicios_asignacion_unica
    UNIQUE (profesional_id, servicio_id),
  CONSTRAINT profesional_servicios_duracion_valida
    CHECK (
      duracion_personalizada_minutos IS NULL
      OR duracion_personalizada_minutos BETWEEN 5 AND 1440
    ),
  CONSTRAINT profesional_servicios_precio_valido
    CHECK (precio_personalizado_clp IS NULL OR precio_personalizado_clp >= 0)
);

CREATE TABLE IF NOT EXISTS disponibilidad_semanal (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  local_id UUID NOT NULL,
  profesional_id UUID NOT NULL,
  dia_semana SMALLINT NOT NULL,
  hora_inicio TIME NOT NULL,
  hora_fin TIME NOT NULL,
  vigente_desde DATE NOT NULL DEFAULT CURRENT_DATE,
  vigente_hasta DATE,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT disponibilidad_profesional_fk
    FOREIGN KEY (profesional_id, local_id)
    REFERENCES profesionales(id, local_id)
    ON DELETE CASCADE,
  CONSTRAINT disponibilidad_dia_valido
    CHECK (dia_semana BETWEEN 1 AND 7),
  CONSTRAINT disponibilidad_horas_validas
    CHECK (hora_fin > hora_inicio),
  CONSTRAINT disponibilidad_vigencia_valida
    CHECK (vigente_hasta IS NULL OR vigente_hasta >= vigente_desde),
  CONSTRAINT disponibilidad_bloque_unico
    UNIQUE (
      profesional_id,
      dia_semana,
      hora_inicio,
      hora_fin,
      vigente_desde
    )
);

CREATE TABLE IF NOT EXISTS bloqueos_agenda (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  local_id UUID NOT NULL,
  profesional_id UUID,
  tipo TEXT NOT NULL DEFAULT 'manual',
  motivo TEXT,
  inicio_en TIMESTAMPTZ NOT NULL,
  fin_en TIMESTAMPTZ NOT NULL,
  creado_por UUID,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT bloqueos_local_fk
    FOREIGN KEY (local_id)
    REFERENCES locales(id)
    ON DELETE CASCADE,
  CONSTRAINT bloqueos_profesional_fk
    FOREIGN KEY (profesional_id, local_id)
    REFERENCES profesionales(id, local_id)
    ON DELETE CASCADE,
  CONSTRAINT bloqueos_creado_por_fk
    FOREIGN KEY (creado_por)
    REFERENCES usuarios(id)
    ON DELETE SET NULL,
  CONSTRAINT bloqueos_tipo_valido
    CHECK (tipo IN ('manual', 'descanso', 'vacaciones', 'capacitacion', 'feriado')),
  CONSTRAINT bloqueos_periodo_valido
    CHECK (fin_en > inicio_en)
);

CREATE INDEX IF NOT EXISTS profesionales_local_idx
  ON profesionales (local_id, estado);

CREATE INDEX IF NOT EXISTS servicios_local_activo_idx
  ON servicios (local_id, activo);

CREATE INDEX IF NOT EXISTS profesional_servicios_servicio_idx
  ON profesional_servicios (servicio_id, activo);

CREATE INDEX IF NOT EXISTS disponibilidad_profesional_dia_idx
  ON disponibilidad_semanal (profesional_id, dia_semana, activo);

CREATE INDEX IF NOT EXISTS bloqueos_profesional_periodo_idx
  ON bloqueos_agenda (profesional_id, inicio_en, fin_en);

CREATE INDEX IF NOT EXISTS bloqueos_local_periodo_idx
  ON bloqueos_agenda (local_id, inicio_en, fin_en);

CREATE OR REPLACE FUNCTION validar_usuario_profesional()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM usuario_roles ur
    INNER JOIN roles r ON r.id = ur.rol_id
    WHERE ur.usuario_id = NEW.usuario_id
      AND ur.local_id = NEW.local_id
      AND r.slug = 'profesional'
      AND r.activo = TRUE
  ) THEN
    RAISE EXCEPTION
      'El usuario debe tener el rol profesional en el local indicado.';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS profesionales_rol_trigger ON profesionales;
CREATE TRIGGER profesionales_rol_trigger
BEFORE INSERT OR UPDATE OF usuario_id, local_id ON profesionales
FOR EACH ROW
EXECUTE FUNCTION validar_usuario_profesional();

DROP TRIGGER IF EXISTS profesionales_actualizado_en_trigger ON profesionales;
CREATE TRIGGER profesionales_actualizado_en_trigger
BEFORE UPDATE ON profesionales
FOR EACH ROW
EXECUTE FUNCTION actualizar_marca_de_tiempo();

DROP TRIGGER IF EXISTS servicios_actualizado_en_trigger ON servicios;
CREATE TRIGGER servicios_actualizado_en_trigger
BEFORE UPDATE ON servicios
FOR EACH ROW
EXECUTE FUNCTION actualizar_marca_de_tiempo();

DROP TRIGGER IF EXISTS profesional_servicios_actualizado_en_trigger
  ON profesional_servicios;
CREATE TRIGGER profesional_servicios_actualizado_en_trigger
BEFORE UPDATE ON profesional_servicios
FOR EACH ROW
EXECUTE FUNCTION actualizar_marca_de_tiempo();

DROP TRIGGER IF EXISTS disponibilidad_actualizado_en_trigger
  ON disponibilidad_semanal;
CREATE TRIGGER disponibilidad_actualizado_en_trigger
BEFORE UPDATE ON disponibilidad_semanal
FOR EACH ROW
EXECUTE FUNCTION actualizar_marca_de_tiempo();

DROP TRIGGER IF EXISTS bloqueos_actualizado_en_trigger ON bloqueos_agenda;
CREATE TRIGGER bloqueos_actualizado_en_trigger
BEFORE UPDATE ON bloqueos_agenda
FOR EACH ROW
EXECUTE FUNCTION actualizar_marca_de_tiempo();

COMMENT ON COLUMN disponibilidad_semanal.dia_semana IS
  'Día ISO-8601: 1=lunes, 7=domingo.';

COMMENT ON COLUMN bloqueos_agenda.profesional_id IS
  'NULL bloquea al local completo; un UUID bloquea solo a ese profesional.';

COMMIT;
