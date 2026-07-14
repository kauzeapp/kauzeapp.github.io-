-- KAUZE · Fase 1 / Objetivo 1.1 / Tarea 1
-- Esquema inicial PostgreSQL para categorías y locales.
-- Cada fila de `locales` representa el límite lógico de un negocio (tenant).

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS categorias (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  nombre TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  descripcion TEXT,
  icono TEXT,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT categorias_slug_formato
    CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$')
);

CREATE TABLE IF NOT EXISTS locales (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  categoria_id UUID NOT NULL,
  nombre TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  descripcion TEXT,
  direccion TEXT,
  comuna TEXT,
  ciudad TEXT,
  zona_horaria TEXT NOT NULL DEFAULT 'America/Santiago',
  telefono_whatsapp TEXT,
  email_contacto TEXT,
  email_calendar TEXT,
  logo_url TEXT,
  banner_url TEXT,
  tema_visual TEXT NOT NULL DEFAULT 'Kauze Base',
  estado TEXT NOT NULL DEFAULT 'activo',
  requiere_abono BOOLEAN NOT NULL DEFAULT FALSE,
  tipo_abono TEXT NOT NULL DEFAULT 'none',
  porcentaje_abono NUMERIC(5, 2) NOT NULL DEFAULT 0,
  monto_abono_fijo INTEGER NOT NULL DEFAULT 0,
  monto_abono_minimo INTEGER NOT NULL DEFAULT 0,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actualizado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT locales_categoria_fk
    FOREIGN KEY (categoria_id)
    REFERENCES categorias(id)
    ON UPDATE CASCADE
    ON DELETE RESTRICT,

  CONSTRAINT locales_slug_formato
    CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  CONSTRAINT locales_estado_valido
    CHECK (estado IN ('activo', 'inactivo', 'suspendido')),
  CONSTRAINT locales_tipo_abono_valido
    CHECK (tipo_abono IN ('none', 'porcentaje', 'fijo')),
  CONSTRAINT locales_porcentaje_abono_valido
    CHECK (porcentaje_abono BETWEEN 0 AND 100),
  CONSTRAINT locales_montos_abono_validos
    CHECK (monto_abono_fijo >= 0 AND monto_abono_minimo >= 0),
  CONSTRAINT locales_configuracion_abono_coherente
    CHECK (
      (requiere_abono = FALSE AND tipo_abono = 'none')
      OR
      (
        requiere_abono = TRUE
        AND (
          (tipo_abono = 'porcentaje' AND porcentaje_abono > 0)
          OR
          (tipo_abono = 'fijo' AND monto_abono_fijo > 0)
        )
      )
    )
);

CREATE INDEX IF NOT EXISTS locales_categoria_id_idx
  ON locales (categoria_id);

CREATE INDEX IF NOT EXISTS locales_estado_idx
  ON locales (estado);

CREATE INDEX IF NOT EXISTS locales_ubicacion_idx
  ON locales (ciudad, comuna);

CREATE OR REPLACE FUNCTION actualizar_marca_de_tiempo()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.actualizado_en = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS categorias_actualizado_en_trigger ON categorias;
CREATE TRIGGER categorias_actualizado_en_trigger
BEFORE UPDATE ON categorias
FOR EACH ROW
EXECUTE FUNCTION actualizar_marca_de_tiempo();

DROP TRIGGER IF EXISTS locales_actualizado_en_trigger ON locales;
CREATE TRIGGER locales_actualizado_en_trigger
BEFORE UPDATE ON locales
FOR EACH ROW
EXECUTE FUNCTION actualizar_marca_de_tiempo();

INSERT INTO categorias (nombre, slug, descripcion)
VALUES
  ('Barbería', 'barberia', 'Barberías y servicios de grooming masculino.'),
  ('Manicure', 'manicure', 'Manicure, pedicure y servicios de uñas.'),
  ('Pestañas', 'pestanas', 'Extensiones, lifting y cuidado de pestañas.'),
  ('Estética', 'estetica', 'Servicios de estética y bienestar.'),
  ('Peluquería', 'peluqueria', 'Peluquerías y servicios capilares.')
ON CONFLICT (slug) DO UPDATE
SET
  nombre = EXCLUDED.nombre,
  descripcion = EXCLUDED.descripcion,
  activo = TRUE,
  actualizado_en = NOW();

COMMIT;
