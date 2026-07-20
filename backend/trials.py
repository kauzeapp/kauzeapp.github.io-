import os
import re
import secrets
import threading
import time

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.auth import _sha256
from backend.db import connection
from backend.email_delivery import email_delivery_configured, send_email
from backend.onboarding import business_slug
from backend.tenant import set_tenant_context


TRIAL_DAYS = 7
INITIAL_ACCESS_HOURS = 24
RATE_WINDOW_SECONDS = 30 * 60
RATE_MAX_REQUESTS = 3
_rate_lock = threading.Lock()
_rate_events = {}


class TrialRegistrationError(ValueError):
    def __init__(self, message, code="invalid_trial", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def _clean(value, field, minimum=2, maximum=160):
    result = " ".join(str(value or "").strip().split())
    if len(result) < minimum or len(result) > maximum or "<" in result or ">" in result:
        raise TrialRegistrationError(f"{field} no es valido.", f"invalid_{field}")
    return result


def _email(value):
    result = str(value or "").strip().lower()
    if len(result) > 320 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", result):
        raise TrialRegistrationError("El correo no es valido.", "invalid_email")
    return result


def _phone(value):
    result = re.sub(r"[\s()-]", "", str(value or "").strip())
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", result):
        raise TrialRegistrationError(
            "Usa un telefono con codigo de pais, por ejemplo +56912345678.",
            "invalid_phone",
        )
    return result


def _rate_limit(client_key, email):
    now = time.monotonic()
    key = f"{str(client_key or 'unknown')[:100]}:{email[:120]}"
    with _rate_lock:
        recent = [event for event in _rate_events.get(key, []) if now - event < RATE_WINDOW_SECONDS]
        if len(recent) >= RATE_MAX_REQUESTS:
            raise TrialRegistrationError(
                "Demasiados intentos. Espera unos minutos.", "rate_limited", 429
            )
        recent.append(now)
        _rate_events[key] = recent


def _available_slug(conn, name):
    base = business_slug(name)
    candidate = base
    for _ in range(12):
        exists = conn.execute("SELECT 1 FROM locales WHERE slug = %s", (candidate,)).fetchone()
        if not exists:
            return candidate
        candidate = f"{base[:43].rstrip('-')}-{secrets.token_hex(3)}"
    raise TrialRegistrationError("No fue posible crear el enlace del negocio.", "slug_unavailable", 409)


def _ensure_owner_contact_available(conn, email, phone):
    if conn.execute(
        "SELECT 1 FROM usuarios WHERE LOWER(email) = %s", (email,)
    ).fetchone():
        raise TrialRegistrationError(
            "Este correo ya está registrado. Ingresa al panel o recupera tu contraseña.",
            "email_registered",
            409,
        )
    if conn.execute(
        "SELECT 1 FROM usuarios WHERE telefono_whatsapp = %s", (phone,)
    ).fetchone():
        raise TrialRegistrationError(
            "Este teléfono ya está registrado. Ingresa al panel, recupera tu contraseña o utiliza otro número.",
            "phone_registered",
            409,
        )


def _send_initial_access_email(
    recipient, owner_name, business_name, access_url, idempotency_key
):
    if not email_delivery_configured():
        raise RuntimeError("El servicio de correo de Kauze todavia no esta configurado.")
    content = (
        f"Hola {owner_name},\n\n"
        f"Tu negocio {business_name} ya fue preparado en Kauze.\n"
        f"Crea tu contrasena desde este enlace durante las proximas {INITIAL_ACCESS_HOURS} horas:\n\n"
        f"{access_url}\n\n"
        f"Despues podras ingresar al panel y configurar logo, servicios, trabajadores y agenda. "
        f"Tu prueba gratuita dura {TRIAL_DAYS} dias.\n\n"
        "Si no solicitaste esta cuenta, puedes ignorar este mensaje.\n\n"
        "Equipo Kauze"
    )
    return send_email(
        recipient,
        "Activa tu prueba gratis de Kauze",
        content,
        idempotency_key=idempotency_key,
    )


def register_trial(data, client_key="unknown"):
    if not isinstance(data, dict) or data.get("website"):
        raise TrialRegistrationError("La solicitud no es valida.")
    plan = str(data.get("planTipo") or "trial").strip().lower()
    if plan != "trial":
        raise TrialRegistrationError(
            "Los planes pagados estaran disponibles proximamente.",
            "paid_plans_unavailable",
            409,
        )
    owner_name = _clean(data.get("name"), "nombre")
    email = _email(data.get("email"))
    phone = _phone(data.get("phone"))
    business_name = _clean(data.get("businessName"), "negocio", 3)
    category_slug = str(data.get("categoriaSlug") or "barberia").strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", category_slug):
        raise TrialRegistrationError("El rubro no es valido.", "invalid_category")

    _rate_limit(client_key, email)
    if not email_delivery_configured():
        raise TrialRegistrationError(
            "El envio de correos aun no esta disponible. Intenta mas tarde.",
            "email_unavailable",
            503,
        )

    raw_token = secrets.token_urlsafe(48)
    with connection() as conn:
        with conn.transaction():
            conn.row_factory = dict_row
            _ensure_owner_contact_available(conn, email, phone)
            category = conn.execute(
                "SELECT id FROM categorias WHERE slug = %s AND activo = TRUE",
                (category_slug,),
            ).fetchone()
            if not category:
                raise TrialRegistrationError("El rubro no esta disponible.", "category_unavailable")

            slug = _available_slug(conn, business_name)
            owner = conn.execute(
                """
                INSERT INTO usuarios (
                  proveedor_auth, nombre_completo, email, telefono_whatsapp,
                  email_verificado, estado, plan_tipo, estado_suscripcion,
                  fecha_vencimiento, subdominio, requiere_aprobacion,
                  nombre_barberia, categoria_slug
                )
                VALUES (
                  'password', %s, %s, %s, FALSE, 'activo', 'trial', 'trial',
                  NOW() + (%s * INTERVAL '1 day'), %s, FALSE, %s, %s
                )
                RETURNING id
                """,
                (
                    owner_name,
                    email,
                    phone,
                    TRIAL_DAYS,
                    f"{slug}.kauze.cl",
                    business_name,
                    category_slug,
                ),
            ).fetchone()
            local = conn.execute(
                """
                INSERT INTO locales (
                  categoria_id, nombre, slug, email_contacto, telefono_whatsapp,
                  creado_por, onboarding_estado, estado
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'en_progreso', 'activo')
                RETURNING id
                """,
                (category["id"], business_name, slug, email, phone, owner["id"]),
            ).fetchone()
            role = conn.execute(
                "SELECT id FROM roles WHERE slug = 'dueno' AND activo = TRUE"
            ).fetchone()
            if not role:
                raise RuntimeError("El rol dueno no esta configurado.")
            conn.execute(
                """
                INSERT INTO usuario_roles (usuario_id, rol_id, local_id, otorgado_por)
                VALUES (%s, %s, %s, %s)
                """,
                (owner["id"], role["id"], local["id"], owner["id"]),
            )
            set_tenant_context(conn, local["id"], owner["id"])
            conn.execute(
                """
                INSERT INTO suscripciones_saas (
                  local_id, plan_tipo, estado, trial_fin_en, periodo_fin_en
                )
                VALUES (
                  %s, 'trial', 'trial',
                  NOW() + (%s * INTERVAL '1 day'),
                  NOW() + (%s * INTERVAL '1 day')
                )
                """,
                (local["id"], TRIAL_DAYS, TRIAL_DAYS),
            )
            conn.execute(
                """
                INSERT INTO estados_panel_local (local_id, estado, actualizado_por)
                VALUES (%s, %s, %s)
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
                            "publicBookingEnabled": False,
                            "businessStatus": "DISPONIBLE",
                            "onboarding": {"welcomeDismissed": False, "tourCompleted": False},
                        }
                    ),
                    owner["id"],
                ),
            )
            conn.execute(
                """
                INSERT INTO tokens_restablecimiento_password (
                  usuario_id, token_hash, expira_en, proposito
                )
                VALUES (
                  %s, %s, NOW() + (%s * INTERVAL '1 hour'), 'acceso_inicial'
                )
                """,
                (owner["id"], _sha256(raw_token), INITIAL_ACCESS_HOURS),
            )
            public_url = os.environ.get("KAUZE_PUBLIC_URL", "https://kauze.cl").rstrip("/")
            access_url = f"{public_url}/app/?reset_token={raw_token}&welcome=1"
            delivery = _send_initial_access_email(
                email,
                owner_name,
                business_name,
                access_url,
                f"trial-access/{owner['id']}",
            )

    return {
        "status": "success",
        "message": "Tu negocio fue creado. Revisa tu correo para activar el acceso.",
        "businessName": business_name,
        "businessSlug": slug,
        "trialDays": TRIAL_DAYS,
        "emailAccepted": True,
        "emailProvider": delivery["provider"],
    }
