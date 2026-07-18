-- Negocio ficticio para probar el acceso directo desde Instagram y el aislamiento multiempresa.
-- La migración es aditiva: no reemplaza ni modifica las reservas de otros negocios.

BEGIN;

CREATE OR REPLACE FUNCTION provisionar_masterplan_demo()
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
  v_categoria_id UUID;
  v_rol_dueno_id UUID;
  v_dueno_id UUID;
  v_local_id UUID;
BEGIN
  SELECT id
  INTO v_categoria_id
  FROM categorias
  WHERE slug = 'barberia' AND activo = TRUE;

  SELECT id
  INTO v_rol_dueno_id
  FROM roles
  WHERE slug = 'dueno' AND activo = TRUE;

  SELECT ur.usuario_id
  INTO v_dueno_id
  FROM usuario_roles ur
  INNER JOIN roles r ON r.id = ur.rol_id AND r.slug = 'dueno'
  INNER JOIN locales l ON l.id = ur.local_id
  INNER JOIN usuarios u ON u.id = ur.usuario_id AND u.estado = 'activo'
  ORDER BY (l.slug = 'barberia-cauce-norte-demo') DESC, ur.creado_en
  LIMIT 1;

  IF v_categoria_id IS NULL OR v_rol_dueno_id IS NULL OR v_dueno_id IS NULL THEN
    RAISE NOTICE 'Masterplan DEMO omitido: todavía no existe un dueño activo para asociarlo.';
    RETURN FALSE;
  END IF;

  INSERT INTO locales (
    categoria_id,
    nombre,
    slug,
    descripcion,
    direccion,
    comuna,
    ciudad,
    telefono_whatsapp,
    email_contacto,
    tema_visual,
    estado,
    requiere_abono,
    tipo_abono,
    porcentaje_abono,
    monto_abono_fijo,
    monto_abono_minimo
  )
  VALUES (
    v_categoria_id,
    'Masterplan Barbería — DEMO',
    'masterplan',
    'Perfil ficticio conectado a Instagram para probar reservas directas en Kauze.',
    'Avenida Demo 456',
    'Providencia',
    'Santiago',
    NULL,
    'demo.masterplan@kauze.cl',
    'Kauze Base',
    'activo',
    FALSE,
    'none',
    0,
    0,
    0
  )
  ON CONFLICT (slug) DO UPDATE
  SET nombre = EXCLUDED.nombre,
      descripcion = EXCLUDED.descripcion,
      direccion = EXCLUDED.direccion,
      comuna = EXCLUDED.comuna,
      ciudad = EXCLUDED.ciudad,
      telefono_whatsapp = NULL,
      email_contacto = EXCLUDED.email_contacto,
      tema_visual = EXCLUDED.tema_visual,
      estado = 'activo',
      actualizado_en = NOW()
  RETURNING id INTO v_local_id;

  INSERT INTO usuario_roles (usuario_id, rol_id, local_id, otorgado_por)
  VALUES (v_dueno_id, v_rol_dueno_id, v_local_id, v_dueno_id)
  ON CONFLICT (usuario_id, rol_id, local_id) WHERE local_id IS NOT NULL
  DO NOTHING;

  INSERT INTO estados_panel_local (local_id, estado, actualizado_por)
  VALUES (
    v_local_id,
    jsonb_build_object(
      'name', 'Masterplan Barbería — DEMO',
      'type', 'barberia',
      'demoMode', TRUE,
      'publicBookingEnabled', TRUE,
      'publicRating', '5.0',
      'publicReviews', 1,
      'clientRatingMode', 'none',
      'instagramUrl', 'https://www.instagram.com/masterplan.soluciones?igsh=MXVsNnF3NXI5M2hkMA==',
      'instagramHandle', '@masterplan.soluciones',
      'publicPhone', '',
      'publicSubdomain', 'masterplan',
      'externalMessagingEnabled', FALSE,
      'ownerWhatsapp', '',
      'ownerCalendarEmail', '',
      'depositEnabled', FALSE,
      'depositMode', 'none',
      'depositPercent', 0,
      'depositFixedAmount', 0,
      'depositMinimum', 0,
      'activeTheme', 'Kauze Base',
      'pageTitle', 'Reserva tu hora en Masterplan Barbería',
      'pageSubtitle', 'Elige servicio, profesional y horario. Para ver trabajos y ejemplos, visita su Instagram.',
      'pageCta', 'Reservar ahora',
      'bannerStyle', 'soft',
      'bannerImage', '',
      'businessStatus', 'DISPONIBLE',
      'notificationPreferences', jsonb_build_object(
        'frequency', 'daily',
        'delivery', 'panel_only',
        'externalDeliveryEnabled', FALSE
      ),
      'professionals', jsonb_build_object(
        'barberia', jsonb_build_array(
          jsonb_build_object(
            'id', 'masterplan-pro-1',
            'name', 'Benjamín Soto',
            'role', 'Barbero senior',
            'note', 'Perfil ficticio para pruebas internas.',
            'commission', 45,
            'days', jsonb_build_array('Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'),
            'shifts', jsonb_build_array('10:00 - 20:00'),
            'services', jsonb_build_array('Corte clásico', 'Fade', 'Perfilado de barba')
          ),
          jsonb_build_object(
            'id', 'masterplan-pro-2',
            'name', 'Martina Rojas',
            'role', 'Especialista en fade',
            'note', 'Perfil ficticio para pruebas internas.',
            'commission', 45,
            'days', jsonb_build_array('Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'),
            'shifts', jsonb_build_array('10:00 - 20:00'),
            'services', jsonb_build_array('Corte clásico', 'Fade', 'Perfilado de barba')
          )
        )
      ),
      'services', jsonb_build_object(
        'barberia', jsonb_build_array(
          jsonb_build_object('id', 'masterplan-ser-1', 'name', 'Corte clásico', 'duration', '45 min', 'price', 12000, 'professional', 'Todos'),
          jsonb_build_object('id', 'masterplan-ser-2', 'name', 'Fade', 'duration', '60 min', 'price', 16000, 'professional', 'Todos'),
          jsonb_build_object('id', 'masterplan-ser-3', 'name', 'Perfilado de barba', 'duration', '30 min', 'price', 10000, 'professional', 'Todos')
        )
      ),
      'clients', jsonb_build_object('barberia', jsonb_build_array()),
      'appointments', jsonb_build_object('barberia', jsonb_build_array()),
      'campaigns', jsonb_build_object('barberia', jsonb_build_array()),
      'virtualQueue', jsonb_build_array()
    ),
    v_dueno_id
  )
  ON CONFLICT (local_id) DO NOTHING;
  RETURN TRUE;
END;
$$;

SELECT provisionar_masterplan_demo();

COMMIT;
