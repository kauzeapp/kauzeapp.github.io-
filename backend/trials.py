import os
import re
import secrets
import threading
import time

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.auth import _sha256
from backend.db import connection, is_configured, is_configured
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
        raise TrialRegistrationError(f"{field} no es válido.", f"invalid_{field}")
    return result


def _email(value):
    result = str(value or "").strip().lower()
    if len(result) > 320 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", result):
        raise TrialRegistrationError("El correo no es válido.", "invalid_email")
    return result


def _phone(value):
    result = re.sub(r"[\s()-]", "", str(value or "").strip())
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", result):
        raise TrialRegistrationError(
            "Usa un teléfono con código de país, por ejemplo +56912345678.",
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
        raise RuntimeError("El servicio de correo de Kauze todavía no está configurado.")

    content = (
        f"Hola {owner_name},\n\n"
        f"Tu negocio {business_name} ya fue preparado en Kauze.\n"
        f"Crea tu contraseña desde este enlace durante las próximas {INITIAL_ACCESS_HOURS} horas:\n\n"
        f"{access_url}\n\n"
        f"Después podrás ingresar al panel y configurar logo, servicios, trabajadores y agenda. "
        f"Tu prueba gratuita dura {TRIAL_DAYS} días.\n\n"
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
        raise TrialRegistrationError("La solicitud no es válida.")

    plan = str(data.get("planTipo") or "trial").strip().lower()
    if plan != "trial":
        raise TrialRegistrationError(
            "Los planes pagados estarán disponibles próximamente.",
            "paid_plans_unavailable",
            409,
        )

    owner_name = _clean(data.get("name"), "nombre")
    email = _email(data.get("email"))
    phone = _phone(data.get("phone"))
    business_name = _clean(data.get("businessName"), "negocio", 3)
    category_slug = str(data.get("categoriaSlug") or "barberia").strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", category_slug):
        raise TrialRegistrationError("El rubro no es válido.", "invalid_category")

    _rate_limit(client_key, email)

    if not is_configured():
        # Modo Pruebas Locales (Puente de Simulaciones)
        from backend.simulations import log_simulation
        from backend.subscriptions import read_local_db, write_local_db
        import uuid
        from datetime import datetime, timedelta, timezone
        
        # 1. Simular validación de email
        log_simulation("Validación de Email", email, f"Comprobando disponibilidad para el correo '{email}'.")
        
        db = read_local_db()
        exists = any(s.get("email") == email for s in db["subscriptions"])
        if exists:
            raise TrialRegistrationError(
                "Este correo ya está registrado. Ingresa al panel o recupera tu contraseña.",
                "email_registered",
                409
            )
            
        # 2. Generar slug único y token
        from backend.subscriptions import clean_subdomain
        base_slug = clean_subdomain(business_name)
        slug = base_slug
        counter = 1
        while any(s.get("subdominio") == f"{slug}.kauze.cl" for s in db["subscriptions"]):
            slug = f"{base_slug}-{counter}"
            counter += 1
            
        subdomain = f"{slug}.kauze.cl"
        client_id = str(uuid.uuid4())
        raw_token = secrets.token_urlsafe(48)
        
        # 3. Crear registro en base de datos local JSON
        expiry = datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)
        new_sub = {
            "id": client_id,
            "name": owner_name,
            "email": email,
            "phone": phone,
            "planTipo": "trial",
            "estadoSuscripcion": "trial",
            "fechaVencimiento": expiry.isoformat() + "Z",
            "subdominio": subdomain,
            "requiereAprobacion": False,
            "businessName": business_name,
            "categoriaSlug": category_slug,
            "creadoEn": datetime.now(timezone.utc).isoformat() + "Z",
            "tokenAccesoTemporal": raw_token
        }
        db["subscriptions"].append(new_sub)
        write_local_db(db)
        
        # 4. Logear simulaciones en el puente de pruebas
        log_simulation("Base de Datos Local (JSON)", email, f"Creado registro de prueba '{business_name}' en 'subscriptions_db.json'.")
        log_simulation("Ruteo de Subdominio", subdomain, f"Subdominio simulado creado. Apunta a 'http://localhost:8000/app/index.html?negocio={slug}'.")
        
        # Simular envío de email de bienvenida
        access_url = f"http://localhost:8000/app/index.html?token={raw_token}"
        log_simulation("Envío de Correo (Bienvenida)", email, f"Simulación de envío SMTP/Resend exitosa. Enlace de acceso: {access_url}")
        
        return {
            "status": "success",
            "message": "Tu negocio fue creado. Revisa el Muro de Simulaciones en el Panel Admin para activar el acceso.",
            "subdomain": subdomain,
            "simulated": True
        }

    if not is_configured():
        # Modo Pruebas Locales (Puente de Simulaciones)
        from backend.simulations import log_simulation
        from backend.subscriptions import read_local_db, write_local_db
        import uuid
        from datetime import datetime, timedelta, timezone
        
        # 1. Simular validación de email
        log_simulation("Validación de Email", email, f"Comprobando disponibilidad para el correo '{email}'.")
        
        db = read_local_db()
        exists = any(s.get("email") == email for s in db["subscriptions"])
        if exists:
            raise TrialRegistrationError(
                "Este correo ya está registrado. Ingresa al panel o recupera tu contraseña.",
                "email_registered",
                409
            )
            
        # 2. Generar slug único y token
        from backend.subscriptions import clean_subdomain
        base_slug = clean_subdomain(business_name)
        slug = base_slug
        counter = 1
        while any(s.get("subdominio") == f"{slug}.kauze.cl" for s in db["subscriptions"]):
            slug = f"{base_slug}-{counter}"
            counter += 1
            
        subdomain = f"{slug}.kauze.cl"
        client_id = str(uuid.uuid4())
        raw_token = secrets.token_urlsafe(48)
        
        # 3. Crear registro en base de datos local JSON
        expiry = datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)
        new_sub = {
            "id": client_id,
            "name": owner_name,
            "email": email,
            "phone": phone,
            "planTipo": "trial",
            "estadoSuscripcion": "trial",
            "fechaVencimiento": expiry.isoformat() + "Z",
            "subdominio": subdomain,
            "requiereAprobacion": False,
            "businessName": business_name,
            "categoriaSlug": category_slug,
            "creadoEn": datetime.now(timezone.utc).isoformat() + "Z",
            "tokenAccesoTemporal": raw_token
        }
        db["subscriptions"].append(new_sub)
        write_local_db(db)
        
        # 4. Logear simulaciones en el puente de pruebas
        log_simulation("Base de Datos Local (JSON)", email, f"Creado registro de prueba '{business_name}' en 'subscriptions_db.json'.")
        log_simulation("Ruteo de Subdominio", subdomain, f"Subdominio simulado creado. Apunta a 'http://localhost:8000/app/index.html?negocio={slug}'.")
        
        # Simular envío de email de bienvenida
        access_url = f"http://localhost:8000/app/index.html?token={raw_token}"
        log_simulation("Envío de Correo (Bienvenida)", email, f"Simulación de envío SMTP/Resend exitosa. Enlace de acceso: {access_url}")
        
        return {
            "status": "success",
            "message": "Tu negocio fue creado. Revisa el Muro de Simulaciones en el Panel Admin para activar el acceso.",
            "subdomain": subdomain,
            "simulated": True
        }
    if not email_delivery_configured():
        raise TrialRegistrationError(
            "El envío de correos aún no está disponible. Intenta más tarde.",
            "email_unavailable",
            503,
        )

    # ── Paso 1: guardar todo en PostgreSQL (transacción independiente del email) ──
    raw_token = secrets.token_urlsafe(48)
    saved_owner_id = None
    saved_slug = None
    saved_local_id = None

    with connection() as conn:
        with conn.transaction():
            conn.row_factory = dict_row
            _ensure_owner_contact_available(conn, email, phone)

            category = conn.execute(
                "SELECT id FROM categorias WHERE slug = %s AND activo = TRUE",
                (category_slug,),
            ).fetchone()
            if not category:
                raise TrialRegistrationError("El rubro no está disponible.", "category_unavailable")

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
                raise RuntimeError("El rol dueño no está configurado.")
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

            # Guardar IDs para usar después de la transacción
            saved_owner_id = owner["id"]
            saved_slug = slug
            saved_local_id = local["id"]

    # ── Paso 2: loguear en simulaciones (fuera de la transacción) ──
    try:
        from backend.simulations import log_simulation
        log_simulation("Base de Datos (Producción)", email, f"Creado negocio '{business_name}' en PostgreSQL. ID: {saved_owner_id}")
        log_simulation("Ruteo de Subdominio (Producción)", f"{saved_slug}.kauze.cl", f"Subdominio registrado exitosamente.")
    except Exception:
        pass

    # ── Paso 3: enviar email de bienvenida (fuera de la transacción) ──
    # Si el email falla, el usuario YA está guardado en la BD y puede recuperar acceso.
    public_url = os.environ.get("KAUZE_PUBLIC_URL", "https://kauze.cl").rstrip("/")
    access_url = f"{public_url}/app/?reset_token={raw_token}&welcome=1"
    email_provider = "none"
    try:
        delivery = _send_initial_access_email(
            email,
            owner_name,
            business_name,
            access_url,
            f"trial-access/{saved_owner_id}",
        )
        email_provider = delivery.get("provider", "resend")
        try:
            from backend.simulations import log_simulation
            log_simulation("Envío de Correo (Producción)", email, f"Email de bienvenida enviado vía {email_provider}. Enlace: {access_url}")
        except Exception:
            pass
    except Exception as email_exc:
        # Email falló pero el usuario YA está guardado → no revertir nada
        print(f"[trials] Email falló para {email}: {type(email_exc).__name__}: {email_exc}")
        try:
            from backend.simulations import log_simulation
            log_simulation("Email Fallido (Producción)", email, f"El negocio fue creado pero el email falló: {email_exc}. El usuario puede recuperar acceso desde la landing.")
        except Exception:
            pass

    return {
        "status": "success",
        "message": "Tu negocio fue creado. Revisa tu correo para activar el acceso.",
        "businessName": business_name,
        "businessSlug": saved_slug,
        "trialDays": TRIAL_DAYS,
        "emailAccepted": True,
        "emailProvider": email_provider,
    }

