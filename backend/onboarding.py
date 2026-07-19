import re
import secrets
import unicodedata

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.db import connection
from backend.tenant import set_tenant_context


TRIAL_DAYS = 14
GOOGLE_PICTURE_MAX_LENGTH = 1_000


def business_slug(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) < 3:
        raise ValueError("El nombre del negocio es demasiado corto.")
    return slug[:50].rstrip("-")


def normalize_google_identity(identity):
    """Valida claims que ya fueron verificados criptográficamente por OAuth."""
    if not isinstance(identity, dict):
        raise ValueError("La identidad de Google no es válida.")

    subject = str(identity.get("sub") or "").strip()
    email = str(identity.get("email") or "").strip().lower()
    name = str(identity.get("name") or "").strip()
    picture = str(identity.get("picture") or "").strip()
    email_verified = identity.get("email_verified") is True

    if not subject or len(subject) > 255:
        raise ValueError("Google no entregó un identificador válido.")
    if not email_verified or "@" not in email or len(email) > 320:
        raise ValueError("Google debe entregar un correo verificado.")
    if not name:
        name = email.split("@", 1)[0]
    if len(name) > 160:
        name = name[:160].strip()
    if picture and (
        not picture.startswith("https://")
        or len(picture) > GOOGLE_PICTURE_MAX_LENGTH
    ):
        picture = ""

    return {
        "subject": subject,
        "email": email,
        "name": name,
        "picture": picture or None,
    }


def _available_slug(conn, requested_name):
    base = business_slug(requested_name)
    candidate = base
    for _ in range(20):
        exists = conn.execute(
            "SELECT 1 FROM locales WHERE slug = %s",
            (candidate,),
        ).fetchone()
        if not exists:
            return candidate
        candidate = f"{base[:43].rstrip('-')}-{secrets.token_hex(2)}"
    raise RuntimeError("No fue posible generar una dirección única para el negocio.")


def complete_google_owner_onboarding(identity, business):
    """Crea el dueño y su primer negocio después de validar el callback OAuth.

    Esta función no verifica tokens de Google. Solo debe recibir claims producidos
    por el futuro verificador OAuth del servidor.
    """
    google = normalize_google_identity(identity)
    if not isinstance(business, dict):
        raise ValueError("Los datos del negocio no son válidos.")

    business_name = str(business.get("name") or "").strip()
    category_slug = str(business.get("categorySlug") or "").strip().lower()
    if len(business_name) < 3 or len(business_name) > 160:
        raise ValueError("El nombre del negocio debe tener entre 3 y 160 caracteres.")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", category_slug):
        raise ValueError("La categoría del negocio no es válida.")

    with connection() as conn:
        with conn.transaction():
            conn.row_factory = dict_row
            category = conn.execute(
                "SELECT id, slug FROM categorias WHERE slug = %s AND activo = TRUE",
                (category_slug,),
            ).fetchone()
            if not category:
                raise ValueError("La categoría seleccionada no está disponible.")

            existing_owner = conn.execute(
                """
                SELECT id, proveedor_auth, proveedor_auth_id
                FROM usuarios
                WHERE LOWER(email) = %s
                LIMIT 1
                FOR UPDATE
                """,
                (google["email"],),
            ).fetchone()
            if existing_owner:
                linked_subject = existing_owner["proveedor_auth_id"]
                if linked_subject and linked_subject != google["subject"]:
                    raise ValueError("Este correo ya está vinculado a otra identidad.")
                owner = conn.execute(
                    """
                    UPDATE usuarios
                    SET proveedor_auth = 'google',
                        proveedor_auth_id = %s,
                        nombre_completo = %s,
                        email_verificado = TRUE,
                        foto_perfil_url = COALESCE(%s, foto_perfil_url),
                        estado = 'activo',
                        actualizado_en = NOW()
                    WHERE id = %s
                    RETURNING id, nombre_completo, email, foto_perfil_url
                    """,
                    (
                        google["subject"],
                        google["name"],
                        google["picture"],
                        existing_owner["id"],
                    ),
                ).fetchone()
                conn.execute(
                    "DELETE FROM credenciales_password WHERE usuario_id = %s",
                    (owner["id"],),
                )
            else:
                owner = conn.execute(
                    """
                    INSERT INTO usuarios (
                      proveedor_auth,
                      proveedor_auth_id,
                      nombre_completo,
                      email,
                      email_verificado,
                      foto_perfil_url,
                      estado
                    )
                    VALUES ('google', %s, %s, %s, TRUE, %s, 'activo')
                    ON CONFLICT (proveedor_auth, proveedor_auth_id)
                      WHERE proveedor_auth_id IS NOT NULL
                    DO UPDATE SET
                      nombre_completo = EXCLUDED.nombre_completo,
                      email = EXCLUDED.email,
                      email_verificado = TRUE,
                      foto_perfil_url = COALESCE(EXCLUDED.foto_perfil_url, usuarios.foto_perfil_url),
                      estado = 'activo',
                      actualizado_en = NOW()
                    RETURNING id, nombre_completo, email, foto_perfil_url
                    """,
                    (
                        google["subject"],
                        google["name"],
                        google["email"],
                        google["picture"],
                    ),
                ).fetchone()

            existing = conn.execute(
                """
                SELECT l.id, l.nombre, l.slug, c.slug AS categoria_slug
                FROM usuario_roles ur
                INNER JOIN roles r ON r.id = ur.rol_id AND r.slug = 'dueno'
                INNER JOIN locales l ON l.id = ur.local_id
                INNER JOIN categorias c ON c.id = l.categoria_id
                WHERE ur.usuario_id = %s
                ORDER BY ur.creado_en
                LIMIT 1
                """,
                (owner["id"],),
            ).fetchone()
            if existing:
                return {
                    "created": False,
                    "userId": str(owner["id"]),
                    "businessId": str(existing["id"]),
                    "businessName": existing["nombre"],
                    "businessSlug": existing["slug"],
                    "categorySlug": existing["categoria_slug"],
                }

            slug = _available_slug(conn, business_name)
            local = conn.execute(
                """
                INSERT INTO locales (
                  categoria_id,
                  nombre,
                  slug,
                  creado_por,
                  onboarding_estado,
                  estado
                )
                VALUES (%s, %s, %s, %s, 'en_progreso', 'activo')
                RETURNING id, nombre, slug
                """,
                (category["id"], business_name, slug, owner["id"]),
            ).fetchone()

            owner_role = conn.execute(
                "SELECT id FROM roles WHERE slug = 'dueno' AND activo = TRUE"
            ).fetchone()
            if not owner_role:
                raise RuntimeError("El rol Dueño no está disponible.")

            conn.execute(
                """
                INSERT INTO usuario_roles (usuario_id, rol_id, local_id, otorgado_por)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (usuario_id, rol_id, local_id) WHERE local_id IS NOT NULL
                DO NOTHING
                """,
                (owner["id"], owner_role["id"], local["id"], owner["id"]),
            )
            set_tenant_context(conn, local["id"], owner["id"])
            conn.execute(
                """
                INSERT INTO suscripciones_saas (
                  local_id,
                  plan_tipo,
                  estado,
                  trial_fin_en,
                  periodo_fin_en
                )
                VALUES (%s, 'trial', 'trial', NOW() + (%s * INTERVAL '1 day'), NOW() + (%s * INTERVAL '1 day'))
                ON CONFLICT (local_id) DO NOTHING
                """,
                (local["id"], TRIAL_DAYS, TRIAL_DAYS),
            )
            conn.execute(
                """
                INSERT INTO estados_panel_local (local_id, estado, actualizado_por)
                VALUES (%s, %s, %s)
                ON CONFLICT (local_id) DO NOTHING
                """,
                (
                    local["id"],
                    Jsonb(
                        {
                            "name": business_name,
                            "type": category_slug,
                            "logoUrl": "",
                            "professionals": {},
                            "services": {},
                            "clients": {},
                            "appointments": {},
                        }
                    ),
                    owner["id"],
                ),
            )

            return {
                "created": True,
                "userId": str(owner["id"]),
                "businessId": str(local["id"]),
                "businessName": local["nombre"],
                "businessSlug": local["slug"],
                "categorySlug": category_slug,
                "onboardingStatus": "en_progreso",
                "trialDays": TRIAL_DAYS,
            }
