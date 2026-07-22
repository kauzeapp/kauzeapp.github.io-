import hashlib
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.auth import _sha256
from backend.db import connection, is_configured
from backend.email_delivery import email_delivery_configured, kauze_email_html, send_email
from backend.onboarding import business_slug
from backend.subscriptions import read_local_db, safe_parse_datetime, write_local_db
from backend.tenant import set_tenant_context


TRIAL_DAYS = 7
INITIAL_ACCESS_HOURS = 24
VALID_PLANS = {"trial", "mensual", "trimestral", "anual"}
VALID_STATES = {"trial", "activo", "en_mora", "desactivado"}
VALID_SUBDOMAIN_STATES = {"pendiente", "activo", "suspendido"}
RESERVED_SUBDOMAINS = {
    "admin", "api", "app", "ayuda", "cdn", "cliente", "correo", "mail",
    "soporte", "static", "status", "www",
}


def _clean(value, label, minimum=2, maximum=160):
    result = " ".join(str(value or "").strip().split())
    if len(result) < minimum or len(result) > maximum or "<" in result or ">" in result:
        raise ValueError(f"{label} no es valido.")
    return result


def _email(value):
    result = str(value or "").strip().lower()
    if len(result) > 320 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", result):
        raise ValueError("El correo no es valido.")
    return result


def _phone(value):
    result = re.sub(r"[\s()-]", "", str(value or "").strip())
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", result):
        raise ValueError("Usa un telefono con codigo de pais, por ejemplo +56912345678.")
    return result


def _subdomain_slug(value):
    candidate = str(value or "").strip().lower()
    candidate = re.sub(r"^https?://", "", candidate).split("/", 1)[0]
    if candidate.endswith(".kauze.cl"):
        candidate = candidate[:-9]
    if (
        len(candidate) < 3
        or len(candidate) > 50
        or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", candidate)
    ):
        raise ValueError("El subdominio debe usar entre 3 y 50 caracteres, letras, numeros o guiones.")
    if candidate in RESERVED_SUBDOMAINS:
        raise ValueError("Ese subdominio esta reservado por Kauze.")
    return candidate


def _expiry(plan, now=None):
    now = now or datetime.now(timezone.utc)
    days = {"trial": TRIAL_DAYS, "mensual": 30, "trimestral": 90, "anual": 365}[plan]
    return now + timedelta(days=days)


def _display_state(state, expiry):
    normalized = str(state or "trial").strip().lower()
    if normalized == "cancelado":
        return "desactivado"
    if (
        normalized in ("trial", "activo")
        and expiry is not None
        and expiry < datetime.now(timezone.utc)
    ):
        return "en_mora"
    return normalized if normalized in VALID_STATES else "trial"


def _client_from_row(row):
    expiry = row["fecha_vencimiento"]
    state = _display_state(row["estado_suscripcion"], expiry)
    slug = row["local_slug"] or ""
    subdomain_state = row.get("subdominio_estado") or "pendiente"
    activated_at = row.get("subdominio_activado_en")
    return {
        "id": str(row["usuario_id"]),
        "localId": str(row["local_id"]),
        "name": row["nombre_completo"],
        "email": row["email"],
        "phone": row["telefono_whatsapp"] or "",
        "planTipo": row["plan_tipo"] or "trial",
        "estadoSuscripcion": state,
        "fechaVencimiento": expiry.isoformat() if expiry else None,
        "subdominio": f"{slug}.kauze.cl" if slug else None,
        "subdominioEstado": subdomain_state,
        "subdominioUrl": f"https://{slug}.kauze.cl" if slug and subdomain_state == "activo" else None,
        "subdominioActivadoEn": activated_at.isoformat() if activated_at else None,
        "requiereAprobacion": bool(row["requiere_aprobacion"]),
        "businessName": row["local_nombre"] or row["nombre_completo"],
        "categoriaSlug": row["categoria_slug"] or "barberia",
        "creadoEn": row["creado_en"].isoformat() if row["creado_en"] else None,
    }


def get_admin_clients(status_filter=None, search_query=None):
    if not is_configured():
        clients = []
        for item in read_local_db().get("subscriptions", []):
            expiry = safe_parse_datetime(
                item.get("fecha_vencimiento") or item.get("fechaVencimiento")
            )
            state = _display_state(
                item.get("estado_suscripcion") or item.get("estadoSuscripcion"), expiry
            )
            client = {
                "id": item.get("id"),
                "name": item.get("nombre_completo") or item.get("name") or "",
                "email": item.get("email") or "",
                "phone": item.get("telefono") or item.get("phone") or "",
                "planTipo": item.get("plan_tipo") or item.get("planTipo") or "trial",
                "estadoSuscripcion": state,
                "fechaVencimiento": expiry.isoformat() if expiry else None,
                "subdominio": item.get("subdominio"),
                "subdominioEstado": item.get("subdominio_estado") or item.get("subdominioEstado") or "pendiente",
                "subdominioUrl": (
                    f"https://{item.get('subdominio')}"
                    if item.get("subdominio")
                    and (item.get("subdominio_estado") or item.get("subdominioEstado")) == "activo"
                    else None
                ),
                "subdominioActivadoEn": item.get("subdominio_activado_en") or item.get("subdominioActivadoEn"),
                "requiereAprobacion": bool(
                    item.get("requiere_aprobacion") or item.get("requiereAprobacion")
                ),
                "businessName": item.get("nombre_barberia") or item.get("businessName") or "",
                "categoriaSlug": item.get("categoria_slug") or item.get("categoriaSlug") or "barberia",
                "creadoEn": item.get("creado_en") or item.get("creadoEn"),
            }
            clients.append(client)
    else:
        with connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                """
                SELECT
                  u.id AS usuario_id,
                  u.nombre_completo,
                  u.email,
                  u.telefono_whatsapp,
                  u.creado_en,
                  COALESCE(u.requiere_aprobacion, FALSE) AS requiere_aprobacion,
                  l.id AS local_id,
                  l.nombre AS local_nombre,
                  l.slug AS local_slug,
                  l.subdominio_estado,
                  l.subdominio_activado_en,
                  c.slug AS categoria_slug,
                  COALESCE(s.plan_tipo, u.plan_tipo, 'trial') AS plan_tipo,
                  COALESCE(s.estado, u.estado_suscripcion, 'trial') AS estado_suscripcion,
                  COALESCE(s.periodo_fin_en, s.trial_fin_en, u.fecha_vencimiento) AS fecha_vencimiento
                FROM usuarios u
                INNER JOIN usuario_roles ur ON ur.usuario_id = u.id
                INNER JOIN roles r ON r.id = ur.rol_id AND r.slug = 'dueno'
                INNER JOIN locales l ON l.id = ur.local_id
                INNER JOIN categorias c ON c.id = l.categoria_id
                LEFT JOIN suscripciones_saas s ON s.local_id = l.id
                WHERE u.email IS NOT NULL
                  AND u.estado <> 'inactivo'
                  AND l.estado = 'activo'
                ORDER BY u.creado_en DESC, l.nombre
                """
            ).fetchall()
        clients = [_client_from_row(row) for row in rows]

    normalized_filter = str(status_filter or "todos").strip().lower()
    normalized_search = str(search_query or "").strip().lower()
    if normalized_filter != "todos":
        clients = [c for c in clients if c["estadoSuscripcion"] == normalized_filter]
    if normalized_search:
        clients = [
            c
            for c in clients
            if normalized_search
            in " ".join((c["name"], c["email"], c["businessName"])).lower()
        ]
    return clients


def get_dashboard_stats():
    stats = {"trial": 0, "activo": 0, "en_mora": 0, "desactivado": 0}
    for client in get_admin_clients():
        state = client["estadoSuscripcion"]
        if state in stats:
            stats[state] += 1
    stats["total"] = sum(stats.values())
    stats["updatedAt"] = datetime.now(timezone.utc).isoformat()
    return stats


def delete_admin_client(client_id):
    """Elimina una cuenta de negocio y todos sus datos en una sola transaccion."""
    raw_client_id = str(client_id or "").strip()
    if not raw_client_id:
        raise ValueError("Cliente no encontrado.")

    if not is_configured():
        db = read_local_db()
        subscriptions = db.get("subscriptions", [])
        target = next(
            (item for item in subscriptions if str(item.get("id")) == raw_client_id),
            None,
        )
        if not target:
            raise ValueError("Cliente no encontrado.")
        bootstrap_email = os.environ.get("KAUZE_BOOTSTRAP_EMAIL", "").strip().lower()
        if bootstrap_email and str(target.get("email") or "").strip().lower() == bootstrap_email:
            raise ValueError("La cuenta administradora principal no se puede eliminar.")
        db["subscriptions"] = [
            item for item in subscriptions if str(item.get("id")) != raw_client_id
        ]
        write_local_db(db)
        return {
            "status": "success",
            "message": "Cuenta y negocio eliminados correctamente.",
            "deletedClientId": raw_client_id,
            "deletedBusinesses": 1,
        }

    try:
        normalized_client_id = str(uuid.UUID(raw_client_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Cliente no encontrado.") from exc

    with connection() as conn:
        with conn.transaction():
            conn.row_factory = dict_row
            target = conn.execute(
                """
                SELECT
                  u.id,
                  u.email,
                  EXISTS (
                    SELECT 1
                    FROM usuario_roles ur_admin
                    INNER JOIN roles r_admin
                      ON r_admin.id = ur_admin.rol_id
                     AND r_admin.slug = 'superadmin'
                    WHERE ur_admin.usuario_id = u.id
                      AND ur_admin.local_id IS NULL
                  ) AS is_superadmin
                FROM usuarios u
                WHERE u.id = %s
                """,
                (normalized_client_id,),
            ).fetchone()
            if not target:
                raise ValueError("Cliente no encontrado.")

            bootstrap_email = os.environ.get("KAUZE_BOOTSTRAP_EMAIL", "").strip().lower()
            if target["is_superadmin"] or (
                bootstrap_email
                and str(target["email"] or "").strip().lower() == bootstrap_email
            ):
                raise ValueError("La cuenta administradora principal no se puede eliminar.")

            owned_businesses = conn.execute(
                """
                SELECT DISTINCT l.id
                FROM usuario_roles ur
                INNER JOIN roles r ON r.id = ur.rol_id AND r.slug = 'dueno'
                INNER JOIN locales l ON l.id = ur.local_id
                WHERE ur.usuario_id = %s
                """,
                (normalized_client_id,),
            ).fetchall()

            for business in owned_businesses:
                local_id = business["id"]
                set_tenant_context(conn, local_id, normalized_client_id)

                # El orden evita restricciones cruzadas entre reservas, clientes,
                # servicios y profesionales. Todo ocurre dentro de la transaccion.
                conn.execute("DELETE FROM reservas WHERE local_id = %s", (local_id,))
                conn.execute("DELETE FROM bloqueos_agenda WHERE local_id = %s", (local_id,))
                conn.execute("DELETE FROM disponibilidad_semanal WHERE local_id = %s", (local_id,))
                conn.execute("DELETE FROM profesional_servicios WHERE local_id = %s", (local_id,))
                conn.execute("DELETE FROM clientes WHERE local_id = %s", (local_id,))
                conn.execute("DELETE FROM servicios WHERE local_id = %s", (local_id,))
                conn.execute("DELETE FROM profesionales WHERE local_id = %s", (local_id,))
                conn.execute("DELETE FROM estados_panel_local WHERE local_id = %s", (local_id,))
                conn.execute("DELETE FROM suscripciones_saas WHERE local_id = %s", (local_id,))
                conn.execute("DELETE FROM sesiones_auth WHERE local_id = %s", (local_id,))
                conn.execute("DELETE FROM usuario_roles WHERE local_id = %s", (local_id,))
                conn.execute("DELETE FROM locales WHERE id = %s", (local_id,))

            deleted = conn.execute(
                "DELETE FROM usuarios WHERE id = %s RETURNING id",
                (normalized_client_id,),
            ).fetchone()
            if not deleted:
                raise ValueError("Cliente no encontrado.")

    return {
        "status": "success",
        "message": "Cuenta, negocios y datos asociados eliminados correctamente.",
        "deletedClientId": normalized_client_id,
        "deletedBusinesses": len(owned_businesses),
    }


def _send_access_email(recipient, owner_name, business_name, access_url, key):
    if not email_delivery_configured():
        raise RuntimeError("El servicio de correo de Kauze no esta configurado.")
    content = (
        f"Hola {owner_name},\n\n"
        f"Tu negocio {business_name} ya fue creado en Kauze.\n"
        f"Crea tu contrasena desde este enlace durante las proximas {INITIAL_ACCESS_HOURS} horas:\n\n"
        f"{access_url}\n\n"
        "Al ingresar podras configurar el logo, los servicios, los trabajadores y la agenda.\n\n"
        "Equipo Kauze"
    )
    html = kauze_email_html(
        "Tu cuenta KAUZE está lista",
        f"Hola {owner_name}",
        [
            f"Creamos el acceso para {business_name}.",
            f"Define tu contraseña durante las próximas {INITIAL_ACCESS_HOURS} horas y entra a configurar el negocio.",
        ],
        access_url,
        "Activar mi cuenta",
        [("Negocio", business_name), ("Acceso", "Panel privado KAUZE")],
    )
    return send_email(
        recipient,
        "Activa tu cuenta de Kauze",
        content,
        idempotency_key=key,
        html=html,
    )


def _send_reset_email(recipient, owner_name, access_url, key):
    if not email_delivery_configured():
        raise RuntimeError("El servicio de correo de Kauze no esta configurado.")
    content = (
        f"Hola {owner_name},\n\n"
        "Solicitaste renovar el acceso a tu cuenta de Kauze.\n"
        f"Crea una nueva contrasena desde este enlace durante las proximas {INITIAL_ACCESS_HOURS} horas:\n\n"
        f"{access_url}\n\n"
        "Si no solicitaste este cambio, contacta al equipo Kauze.\n\n"
        "Equipo Kauze"
    )
    html = kauze_email_html(
        "Renueva tu acceso",
        f"Hola {owner_name}",
        [f"Crea una nueva contraseña durante las próximas {INITIAL_ACCESS_HOURS} horas."],
        access_url,
        "Crear nueva contraseña",
    )
    return send_email(
        recipient,
        "Renueva tu acceso a Kauze",
        content,
        idempotency_key=key,
        html=html,
    )


def create_admin_client(data):
    if not isinstance(data, dict):
        raise ValueError("La solicitud no es valida.")
    name = _clean(data.get("name"), "El nombre")
    email = _email(data.get("email"))
    phone = _phone(data.get("phone"))
    business_name = _clean(data.get("businessName"), "El nombre del negocio", 3)
    plan = str(data.get("planTipo") or "trial").strip().lower()
    state = str(data.get("estadoSuscripcion") or ("trial" if plan == "trial" else "activo")).strip().lower()
    category_slug = str(data.get("categoriaSlug") or "barberia").strip().lower()
    if plan not in VALID_PLANS:
        raise ValueError("El plan seleccionado no es valido.")
    if state not in VALID_STATES:
        raise ValueError("El estado seleccionado no es valido.")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", category_slug):
        raise ValueError("El rubro seleccionado no es valido.")

    now = datetime.now(timezone.utc)
    expiry = _expiry(plan, now)
    raw_token = secrets.token_urlsafe(48)

    if not is_configured():
        db = read_local_db()
        if any(str(item.get("email") or "").lower() == email for item in db.get("subscriptions", [])):
            raise ValueError("El correo ya esta registrado.")
        slug = business_slug(business_name)
        occupied = {str(item.get("subdominio") or "").split(".", 1)[0] for item in db.get("subscriptions", [])}
        while slug in occupied:
            slug = f"{business_slug(business_name)[:42]}-{secrets.token_hex(2)}"
        item_id = secrets.token_hex(16)
        db.setdefault("subscriptions", []).append(
            {
                "id": item_id,
                "name": name,
                "email": email,
                "phone": phone,
                "businessName": business_name,
                "planTipo": plan,
                "estadoSuscripcion": state,
                "fechaVencimiento": expiry.isoformat(),
                "subdominio": f"{slug}.kauze.cl",
                "subdominioEstado": "pendiente",
                "subdominioActivadoEn": None,
                "requiereAprobacion": False,
                "categoriaSlug": category_slug,
                "creadoEn": now.isoformat(),
            }
        )
        write_local_db(db)
        return {
            "status": "success",
            "client": {
                "id": item_id,
                "email": email,
                "subdominio": f"{slug}.kauze.cl",
                "subdominioEstado": "pendiente",
            },
            "emailAccepted": False,
            "simulated": True,
        }

    if not email_delivery_configured():
        raise RuntimeError("El servicio de correo no esta disponible.")

    with connection() as conn:
        with conn.transaction():
            conn.row_factory = dict_row
            if conn.execute("SELECT 1 FROM usuarios WHERE LOWER(email) = %s", (email,)).fetchone():
                raise ValueError("El correo ya esta registrado.")
            if conn.execute("SELECT 1 FROM usuarios WHERE telefono_whatsapp = %s", (phone,)).fetchone():
                raise ValueError("El telefono ya esta registrado.")
            category = conn.execute(
                "SELECT id FROM categorias WHERE slug = %s AND activo = TRUE",
                (category_slug,),
            ).fetchone()
            if not category:
                raise ValueError("El rubro seleccionado no esta disponible.")

            base_slug = business_slug(business_name)
            slug = base_slug
            while conn.execute("SELECT 1 FROM locales WHERE slug = %s", (slug,)).fetchone():
                slug = f"{base_slug[:42].rstrip('-')}-{secrets.token_hex(2)}"

            owner = conn.execute(
                """
                INSERT INTO usuarios (
                  proveedor_auth, nombre_completo, email, telefono_whatsapp,
                  email_verificado, estado, plan_tipo, estado_suscripcion,
                  fecha_vencimiento, subdominio, requiere_aprobacion,
                  nombre_barberia, categoria_slug
                ) VALUES (
                  'password', %s, %s, %s, FALSE, 'activo', %s, %s,
                  %s, %s, FALSE, %s, %s
                )
                RETURNING id
                """,
                (
                    name,
                    email,
                    phone,
                    plan,
                    state,
                    expiry,
                    f"{slug}.kauze.cl",
                    business_name,
                    category_slug,
                ),
            ).fetchone()
            local = conn.execute(
                """
                INSERT INTO locales (
                  categoria_id, nombre, slug, email_contacto, telefono_whatsapp,
                  creado_por, onboarding_estado, estado, subdominio_estado
                ) VALUES (%s, %s, %s, %s, %s, %s, 'en_progreso', 'activo', 'pendiente')
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
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    local["id"],
                    plan,
                    state,
                    expiry if plan == "trial" else None,
                    expiry,
                ),
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
                            "instagramUrl": "",
                            "instagramHandle": "",
                            "publicPhone": "",
                            "address": "",
                            "commune": "",
                            "city": "",
                            "latitude": None,
                            "longitude": None,
                            "professionals": {},
                            "services": {},
                            "clients": {},
                            "appointments": {},
                            "publicBookingEnabled": False,
                            "businessStatus": "CERRADO",
                            "operatingDay": {"date": "", "openedAt": ""},
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
                ) VALUES (%s, %s, NOW() + (%s * INTERVAL '1 hour'), 'acceso_inicial')
                """,
                (owner["id"], _sha256(raw_token), INITIAL_ACCESS_HOURS),
            )

            public_url = os.environ.get("KAUZE_PUBLIC_URL", "https://kauze.cl").rstrip("/")
            access_url = f"{public_url}/app/?reset_token={raw_token}&welcome=1"
            delivery = _send_access_email(
                email,
                name,
                business_name,
                access_url,
                "admin-access/" + hashlib.sha256(email.encode("utf-8")).hexdigest(),
            )

    return {
        "status": "success",
        "client": {
            "id": str(owner["id"]),
            "name": name,
            "email": email,
            "businessName": business_name,
            "subdominio": f"{slug}.kauze.cl",
            "subdominioEstado": "pendiente",
            "expiry": expiry.isoformat(),
        },
        "emailAccepted": True,
        "emailProvider": delivery["provider"],
    }


def update_admin_client(client_id, data):
    if not isinstance(data, dict):
        raise ValueError("La solicitud no es valida.")
    name = _clean(data.get("name"), "El nombre")
    email = _email(data.get("email"))
    phone = _phone(data.get("phone"))
    business_name = _clean(data.get("businessName"), "El nombre del negocio", 3)
    plan = str(data.get("planTipo") or "trial").strip().lower()
    state = str(data.get("estadoSuscripcion") or "trial").strip().lower()
    category_slug = str(data.get("categoriaSlug") or "barberia").strip().lower()
    if plan not in VALID_PLANS or state not in VALID_STATES:
        raise ValueError("El plan o estado seleccionado no es valido.")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", category_slug):
        raise ValueError("El rubro seleccionado no es valido.")

    requested_subdomain = _subdomain_slug(data.get("subdominio")) if data.get("subdominio") else ""
    expiry = safe_parse_datetime(data.get("fechaVencimiento")) or _expiry(plan)

    if not is_configured():
        db = read_local_db()
        item = next((row for row in db.get("subscriptions", []) if str(row.get("id")) == str(client_id)), None)
        if not item:
            raise ValueError("Cliente no encontrado.")
        if any(
            str(row.get("id")) != str(client_id)
            and str(row.get("email") or "").strip().lower() == email
            for row in db.get("subscriptions", [])
        ):
            raise ValueError("El correo ya esta registrado.")
        slug = requested_subdomain or str(item.get("subdominio") or "").split(".", 1)[0] or business_slug(business_name)
        if any(
            str(row.get("id")) != str(client_id)
            and str(row.get("subdominio") or "").split(".", 1)[0] == slug
            for row in db.get("subscriptions", [])
        ):
            raise ValueError("El subdominio ya esta en uso.")
        slug_changed = slug != str(item.get("subdominio") or "").split(".", 1)[0]
        item.update(
            {
                "name": name,
                "email": email,
                "phone": phone,
                "businessName": business_name,
                "planTipo": plan,
                "estadoSuscripcion": state,
                "fechaVencimiento": expiry.isoformat(),
                "subdominio": f"{slug}.kauze.cl",
                "subdominioEstado": "pendiente" if slug_changed else item.get("subdominioEstado", "pendiente"),
                "subdominioActivadoEn": None if slug_changed else item.get("subdominioActivadoEn"),
                "categoriaSlug": category_slug,
            }
        )
        write_local_db(db)
        return {"status": "success", "message": "Cliente actualizado."}

    with connection() as conn:
        with conn.transaction():
            conn.row_factory = dict_row
            owner = conn.execute(
                """
                SELECT u.id, l.id AS local_id, l.slug
                FROM usuarios u
                INNER JOIN usuario_roles ur ON ur.usuario_id = u.id
                INNER JOIN roles r ON r.id = ur.rol_id AND r.slug = 'dueno'
                INNER JOIN locales l ON l.id = ur.local_id
                WHERE u.id = %s
                ORDER BY ur.creado_en
                LIMIT 1
                """,
                (client_id,),
            ).fetchone()
            if not owner:
                raise ValueError("Cliente no encontrado.")
            if conn.execute(
                "SELECT 1 FROM usuarios WHERE LOWER(email) = %s AND id <> %s",
                (email, client_id),
            ).fetchone():
                raise ValueError("El correo ya esta registrado.")
            if conn.execute(
                "SELECT 1 FROM usuarios WHERE telefono_whatsapp = %s AND id <> %s",
                (phone, client_id),
            ).fetchone():
                raise ValueError("El telefono ya esta registrado.")
            category = conn.execute(
                "SELECT id FROM categorias WHERE slug = %s AND activo = TRUE",
                (category_slug,),
            ).fetchone()
            if not category:
                raise ValueError("El rubro seleccionado no esta disponible.")
            slug = requested_subdomain or owner["slug"]
            slug_changed = slug != owner["slug"]
            if conn.execute(
                "SELECT 1 FROM locales WHERE slug = %s AND id <> %s",
                (slug, owner["local_id"]),
            ).fetchone():
                raise ValueError("El subdominio ya esta en uso.")

            conn.execute(
                """
                UPDATE usuarios
                SET nombre_completo = %s, email = %s, telefono_whatsapp = %s,
                    plan_tipo = %s, estado_suscripcion = %s,
                    fecha_vencimiento = %s, subdominio = %s,
                    nombre_barberia = %s, categoria_slug = %s
                WHERE id = %s
                """,
                (name, email, phone, plan, state, expiry, f"{slug}.kauze.cl", business_name, category_slug, client_id),
            )
            conn.execute(
                """
                UPDATE locales
                SET nombre = %s, slug = %s, categoria_id = %s,
                    email_contacto = %s, telefono_whatsapp = %s,
                    subdominio_estado = CASE WHEN %s THEN 'pendiente' ELSE subdominio_estado END,
                    subdominio_activado_en = CASE WHEN %s THEN NULL ELSE subdominio_activado_en END,
                    subdominio_activado_por = CASE WHEN %s THEN NULL ELSE subdominio_activado_por END
                WHERE id = %s
                """,
                (
                    business_name,
                    slug,
                    category["id"],
                    email,
                    phone,
                    slug_changed,
                    slug_changed,
                    slug_changed,
                    owner["local_id"],
                ),
            )
            conn.execute(
                """
                INSERT INTO suscripciones_saas (
                  local_id, plan_tipo, estado, trial_fin_en, periodo_fin_en
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (local_id) DO UPDATE
                SET plan_tipo = EXCLUDED.plan_tipo,
                    estado = EXCLUDED.estado,
                    trial_fin_en = EXCLUDED.trial_fin_en,
                    periodo_fin_en = EXCLUDED.periodo_fin_en
                """,
                (owner["local_id"], plan, state, expiry if plan == "trial" else None, expiry),
            )
    return {"status": "success", "message": "Cliente actualizado."}


def set_admin_client_subdomain(client_id, data, actor_id=None):
    if not isinstance(data, dict):
        raise ValueError("La solicitud no es valida.")
    slug = _subdomain_slug(data.get("subdominio"))
    action = str(data.get("action") or "activar").strip().lower()
    if action not in ("activar", "suspender"):
        raise ValueError("La accion del subdominio no es valida.")
    target_state = "activo" if action == "activar" else "suspendido"

    if not is_configured():
        db = read_local_db()
        item = next(
            (row for row in db.get("subscriptions", []) if str(row.get("id")) == str(client_id)),
            None,
        )
        if not item:
            raise ValueError("Cliente no encontrado.")
        if any(
            str(row.get("id")) != str(client_id)
            and str(row.get("subdominio") or "").split(".", 1)[0] == slug
            for row in db.get("subscriptions", [])
        ):
            raise ValueError("El subdominio ya esta en uso.")
        subscription_state = _display_state(
            item.get("estado_suscripcion") or item.get("estadoSuscripcion"),
            safe_parse_datetime(item.get("fecha_vencimiento") or item.get("fechaVencimiento")),
        )
        if target_state == "activo" and subscription_state not in ("trial", "activo"):
            raise ValueError(
                "La cuenta debe estar en trial o con un plan activo antes de publicar su subdominio."
            )
        item["subdominio"] = f"{slug}.kauze.cl"
        item["subdominioEstado"] = target_state
        if target_state == "activo":
            item["subdominioActivadoEn"] = datetime.now(timezone.utc).isoformat()
        write_local_db(db)
        return {
            "status": "success",
            "message": "Subdominio activado correctamente." if target_state == "activo" else "Subdominio suspendido.",
            "subdominio": f"{slug}.kauze.cl",
            "subdominioEstado": target_state,
            "subdominioUrl": f"https://{slug}.kauze.cl" if target_state == "activo" else None,
        }

    try:
        normalized_client_id = str(uuid.UUID(str(client_id)))
        normalized_actor_id = str(uuid.UUID(str(actor_id))) if actor_id else None
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Cliente no encontrado.") from exc

    with connection() as conn:
        with conn.transaction():
            conn.row_factory = dict_row
            owner = conn.execute(
                """
                SELECT
                  u.id,
                  l.id AS local_id,
                  l.direccion,
                  l.comuna,
                  l.ciudad,
                  e.estado AS panel_state,
                  COALESCE(s.estado, u.estado_suscripcion, 'trial') AS subscription_state,
                  COALESCE(s.periodo_fin_en, s.trial_fin_en, u.fecha_vencimiento) AS subscription_expiry
                FROM usuarios u
                INNER JOIN usuario_roles ur ON ur.usuario_id = u.id
                INNER JOIN roles r ON r.id = ur.rol_id AND r.slug = 'dueno'
                INNER JOIN locales l ON l.id = ur.local_id
                LEFT JOIN estados_panel_local e ON e.local_id = l.id
                LEFT JOIN suscripciones_saas s ON s.local_id = l.id
                WHERE u.id = %s
                ORDER BY ur.creado_en
                LIMIT 1
                """,
                (normalized_client_id,),
            ).fetchone()
            if not owner:
                raise ValueError("Cliente no encontrado.")
            if conn.execute(
                "SELECT 1 FROM locales WHERE slug = %s AND id <> %s",
                (slug, owner["local_id"]),
            ).fetchone():
                raise ValueError("El subdominio ya esta en uso.")

            panel_state = owner.get("panel_state") or {}
            subscription_state = _display_state(
                owner.get("subscription_state"), owner.get("subscription_expiry")
            )
            if target_state == "activo" and subscription_state not in ("trial", "activo"):
                raise ValueError(
                    "La cuenta debe estar en trial o con un plan activo antes de publicar su subdominio."
                )
            if target_state == "activo" and (
                not panel_state.get("publicBookingEnabled")
                or not owner.get("direccion")
                or not owner.get("comuna")
                or not owner.get("ciudad")
            ):
                raise ValueError(
                    "El negocio debe publicar su agenda y completar direccion, comuna y ciudad antes de activar el subdominio."
                )

            conn.execute(
                """
                UPDATE locales
                SET slug = %s,
                    subdominio_estado = %s,
                    subdominio_activado_en = CASE WHEN %s = 'activo' THEN NOW() ELSE subdominio_activado_en END,
                    subdominio_activado_por = CASE WHEN %s = 'activo' THEN %s ELSE subdominio_activado_por END
                WHERE id = %s
                """,
                (
                    slug,
                    target_state,
                    target_state,
                    target_state,
                    normalized_actor_id,
                    owner["local_id"],
                ),
            )
            conn.execute(
                "UPDATE usuarios SET subdominio = %s WHERE id = %s",
                (f"{slug}.kauze.cl", normalized_client_id),
            )

    return {
        "status": "success",
        "message": "Subdominio activado correctamente." if target_state == "activo" else "Subdominio suspendido.",
        "subdominio": f"{slug}.kauze.cl",
        "subdominioEstado": target_state,
        "subdominioUrl": f"https://{slug}.kauze.cl" if target_state == "activo" else None,
    }


def activate_admin_client(client_id):
    now = datetime.now(timezone.utc)
    if not is_configured():
        db = read_local_db()
        item = next((row for row in db.get("subscriptions", []) if str(row.get("id")) == str(client_id)), None)
        if not item:
            raise ValueError("Cliente no encontrado.")
        plan = item.get("planTipo") or item.get("plan_tipo") or "trial"
        state = "trial" if plan == "trial" else "activo"
        item["estadoSuscripcion"] = state
        item["fechaVencimiento"] = _expiry(plan, now).isoformat()
        write_local_db(db)
        return {"status": "success", "message": "Cliente activado.", "state": state}

    with connection() as conn:
        with conn.transaction():
            conn.row_factory = dict_row
            row = conn.execute(
                """
                SELECT u.id, COALESCE(s.plan_tipo, u.plan_tipo, 'trial') AS plan_tipo,
                       l.id AS local_id
                FROM usuarios u
                INNER JOIN usuario_roles ur ON ur.usuario_id = u.id
                INNER JOIN roles r ON r.id = ur.rol_id AND r.slug = 'dueno'
                INNER JOIN locales l ON l.id = ur.local_id
                LEFT JOIN suscripciones_saas s ON s.local_id = l.id
                WHERE u.id = %s
                ORDER BY ur.creado_en
                LIMIT 1
                """,
                (client_id,),
            ).fetchone()
            if not row:
                raise ValueError("Cliente no encontrado.")
            plan = row["plan_tipo"]
            state = "trial" if plan == "trial" else "activo"
            expiry = _expiry(plan, now)
            conn.execute(
                """
                UPDATE usuarios
                SET estado = 'activo', estado_suscripcion = %s,
                    fecha_vencimiento = %s, requiere_aprobacion = FALSE
                WHERE id = %s
                """,
                (state, expiry, client_id),
            )
            conn.execute("UPDATE locales SET estado = 'activo' WHERE id = %s", (row["local_id"],))
            conn.execute(
                """
                INSERT INTO suscripciones_saas (
                  local_id, plan_tipo, estado, trial_fin_en, periodo_fin_en
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (local_id) DO UPDATE
                SET plan_tipo = EXCLUDED.plan_tipo,
                    estado = EXCLUDED.estado,
                    trial_fin_en = EXCLUDED.trial_fin_en,
                    periodo_fin_en = EXCLUDED.periodo_fin_en
                """,
                (row["local_id"], plan, state, expiry if plan == "trial" else None, expiry),
            )
    return {"status": "success", "message": "Cliente activado.", "state": state}


def reset_admin_client_access(client_id):
    if not is_configured():
        db = read_local_db()
        if not any(str(row.get("id")) == str(client_id) for row in db.get("subscriptions", [])):
            raise ValueError("Cliente no encontrado.")
        return {"status": "success", "message": "Correo simulado en el preview local.", "simulated": True}
    if not email_delivery_configured():
        raise RuntimeError("El servicio de correo no esta disponible.")

    raw_token = secrets.token_urlsafe(48)
    public_url = os.environ.get("KAUZE_PUBLIC_URL", "https://kauze.cl").rstrip("/")
    access_url = f"{public_url}/app/?reset_token={raw_token}"
    with connection() as conn:
        with conn.transaction():
            conn.row_factory = dict_row
            user = conn.execute(
                "SELECT id, nombre_completo, email FROM usuarios WHERE id = %s AND estado <> 'inactivo'",
                (client_id,),
            ).fetchone()
            if not user:
                raise ValueError("Cliente no encontrado.")
            conn.execute(
                """
                UPDATE tokens_restablecimiento_password
                SET usado_en = NOW()
                WHERE usuario_id = %s AND usado_en IS NULL
                """,
                (client_id,),
            )
            conn.execute(
                """
                INSERT INTO tokens_restablecimiento_password (
                  usuario_id, token_hash, expira_en, proposito
                ) VALUES (%s, %s, NOW() + (%s * INTERVAL '1 hour'), 'recuperacion')
                """,
                (client_id, _sha256(raw_token), INITIAL_ACCESS_HOURS),
            )
            delivery = _send_reset_email(
                user["email"],
                user["nombre_completo"],
                access_url,
                "admin-reset/" + hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            )
    return {
        "status": "success",
        "message": "Enlace de acceso enviado.",
        "emailAccepted": True,
        "emailProvider": delivery["provider"],
    }
