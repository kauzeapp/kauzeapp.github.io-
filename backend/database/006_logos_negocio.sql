-- Logos configurables por negocio.
-- La imagen inicial de Masterplan se mantiene dentro de kauze.cl y puede
-- reemplazarse posteriormente desde Ajustes del panel.

BEGIN;

UPDATE locales
SET logo_url = '/cliente/assets/masterplan-logo.jpg'
WHERE slug = 'masterplan'
  AND COALESCE(logo_url, '') = '';

UPDATE estados_panel_local e
SET estado = jsonb_set(
      COALESCE(e.estado, '{}'::jsonb),
      '{logoUrl}',
      to_jsonb('/cliente/assets/masterplan-logo.jpg'::text),
      TRUE
    ),
    actualizado_en = NOW(),
    version = e.version + 1
FROM locales l
WHERE l.id = e.local_id
  AND l.slug = 'masterplan'
  AND COALESCE(e.estado->>'logoUrl', '') = '';

COMMIT;
