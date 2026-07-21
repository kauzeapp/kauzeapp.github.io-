import os
import re
import json
import uuid
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from psycopg.rows import dict_row

from backend.db import connection, is_configured
from backend.auth import _sha256
from backend.email_delivery import email_delivery_configured, kauze_email_html, send_email

DB_FILE = "subscriptions_db.json"
EMAIL_LOG_FILE = "sent_emails_log.txt"

hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)

def clean_subdomain(name):
    nfkd_form = unicodedata.normalize('NFKD', str(name or ""))
    only_ascii = nfkd_form.encode('ASCII', 'ignore').decode('utf-8')
    cleaned = only_ascii.lower().strip()
    cleaned = re.sub(r'[^a-z0-9]+', '-', cleaned).strip('-')
    return cleaned if cleaned else "negocio"

def log_email_simulation(recipient, subject, content):
    log_entry = f"=== EMAIL TO: {recipient} ===\nSubject: {subject}\nDate: {datetime.now().isoformat()}\n\n{content}\n=====================================\n\n"
    with open(EMAIL_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)
    print(f"[EMAIL SIMULATION] Sent to {recipient} (Logged to {EMAIL_LOG_FILE})")
    
    try:
        from backend.simulations import log_simulation
        log_simulation("Envío de Correo (Notificación)", recipient, f"Asunto: {subject} | Detalle: {content[:200]}...")
    except Exception as e:
        print("Failed to log email simulation to bridge:", e)
    
    try:
        from backend.simulations import log_simulation
        log_simulation("Envío de Correo (Notificación)", recipient, f"Asunto: {subject} | Detalle: {content[:200]}...")
    except Exception as e:
        print("Failed to log email simulation to bridge:", e)

def send_credentials_email(recipient, fullname, temp_password, subdominio):
    subject = "¡Bienvenido a KAUZE! Tu cuenta ha sido activada"
    url = f"https://{subdominio}" if not subdominio.endswith(".kauze.cl") else f"https://{subdominio}"
    content = (
        f"Hola {fullname},\n\n"
        f"Nos alegra contarte que tu cuenta de barbero en KAUZE ya está activa.\n\n"
        f"Aquí tienes tus credenciales de acceso para administrar tu negocio:\n"
        f"- Enlace de tu Barbería: {url}\n"
        f"- Usuario: {recipient}\n"
        f"- Contraseña Temporal: {temp_password}\n\n"
        f"Te recomendamos cambiar tu contraseña al ingresar por primera vez.\n\n"
        f"Atentamente,\n"
        f"El equipo de KAUZE.cl"
    )

    if not email_delivery_configured():
        log_email_simulation(recipient, subject, content)
        return {"provider": "simulation", "id": None}
    html = kauze_email_html(
        "Tu acceso KAUZE está listo",
        f"Hola {fullname}",
        [
            "Ya puedes ingresar al panel privado y comenzar a configurar tu negocio.",
            "Por seguridad, cambia la contraseña temporal después del primer ingreso.",
        ],
        "https://kauze.cl/app/",
        "Entrar al panel",
        [
            ("Usuario", recipient),
            ("Contraseña temporal", temp_password),
            ("Página pública", url),
        ],
    )
    return send_email(recipient, subject, content, html=html)

def send_reset_password_email(recipient, fullname, temp_password):
    subject = "Restablecimiento de contraseña KAUZE"
    content = (
        f"Hola {fullname},\n\n"
        f"El administrador ha restablecido tu contraseña para ingresar a KAUZE.\n\n"
        f"Tus nuevas credenciales de acceso son:\n"
        f"- Usuario: {recipient}\n"
        f"- Nueva Contraseña Temporal: {temp_password}\n\n"
        f"Te sugerimos cambiarla en tu panel de configuración a la brevedad.\n\n"
        f"Atentamente,\n"
        f"El equipo de KAUZE.cl"
    )

    if not email_delivery_configured():
        log_email_simulation(recipient, subject, content)
        return {"provider": "simulation", "id": None}
    html = kauze_email_html(
        "Tu contraseña fue renovada",
        f"Hola {fullname}",
        ["El administrador generó una nueva contraseña temporal para tu cuenta."],
        "https://kauze.cl/app/",
        "Ingresar a KAUZE",
        [("Usuario", recipient), ("Contraseña temporal", temp_password)],
    )
    return send_email(recipient, subject, content, html=html)

# ----------------- LOCAL JSON STORAGE FALLBACK -----------------

def read_local_db():
    if not os.path.exists(DB_FILE):
        return {"subscriptions": []}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"subscriptions": []}

def write_local_db(data):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error writing to local JSON db: {e}")

# ----------------- SUBSCRIPTION FLOW ACTIONS -----------------

def register_subscription(data):
    name = str(data.get("name") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    phone = str(data.get("phone") or "").strip()
    business_name = str(data.get("businessName") or "").strip()
    plan_tipo = str(data.get("planTipo") or "trial").strip().lower()
    categoria_slug = str(data.get("categoriaSlug") or "barberia").strip().lower()

    if not name or not email or not phone or not business_name:
        raise ValueError("Todos los campos (nombre, email, teléfono, nombre barbería) son requeridos.")
    if plan_tipo not in ('trial', 'mensual', 'trimestral', 'anual'):
        raise ValueError("El tipo de plan seleccionado no es válido.")

    # Calculate default 7 days trial
    expiry = datetime.now(timezone.utc) + timedelta(days=7)

    if is_configured():
        with connection() as conn:
            with conn.transaction():
                # Check duplicate email
                exists = conn.execute(
                    "SELECT 1 FROM usuarios WHERE LOWER(email) = %s", (email,)
                ).fetchone()
                if exists:
                    raise ValueError("El correo ya está registrado en la plataforma.")

                # Insert as user requesting approval
                conn.execute(
                    """
                    INSERT INTO usuarios (
                        nombre_completo, email, telefono_whatsapp, 
                        plan_tipo, estado_suscripcion, fecha_vencimiento, 
                        requiere_aprobacion, nombre_barberia, estado, categoria_slug
                    ) VALUES (%s, %s, %s, %s, 'trial', %s, TRUE, %s, 'activo', %s)
                    """,
                    (name, email, phone, plan_tipo, expiry, business_name, categoria_slug)
                )
    else:
        db = read_local_db()
        for sub in db["subscriptions"]:
            if sub["email"].lower() == email:
                raise ValueError("El correo ya está registrado en la plataforma.")

        new_sub = {
            "id": str(uuid.uuid4()),
            "nombre_completo": name,
            "email": email,
            "telefono": phone,
            "nombre_barberia": business_name,
            "plan_tipo": plan_tipo,
            "estado_suscripcion": "trial",
            "fecha_vencimiento": expiry.isoformat(),
            "requiere_aprobacion": True,
            "categoria_slug": categoria_slug,
            "subdominio": None,
            "creado_en": datetime.now(timezone.utc).isoformat()
        }
        db["subscriptions"].append(new_sub)
        write_local_db(db)

    print(f"[INTERNAL NOTIFICATION] Nuevo registro de Barbero: {business_name} ({email}) - Plan: {plan_tipo}. Requiere Aprobación.")
    return {"status": "success", "message": "Registro completado con éxito. Su cuenta está pendiente de aprobación."}

# ----------------- ADMIN DASHBOARD CONTROL -----------------

def safe_parse_datetime(date_str):
    if not date_str:
        return None
    s = date_str.strip()
    if s.endswith("Z"):
        s = s[:-1]
        if "+" not in s and "-" not in s[10:]:
            s += "+00:00"
    elif not s.endswith("+00:00") and "+" not in s and "-" not in s[10:]:
        s += "+00:00"
    
    if s.endswith("+00:00+00:00"):
        s = s[:-6]
        
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.now(timezone.utc)

def auto_update_expired_subscriptions(conn):
    now = datetime.now(timezone.utc)
    conn.execute(
        """
        UPDATE usuarios 
        SET estado_suscripcion = 'en_mora'
        WHERE plan_tipo IS NOT NULL 
          AND estado_suscripcion IN ('trial', 'activo')
          AND fecha_vencimiento < %s
        """,
        (now,)
    )

def safe_parse_datetime(date_str):
    if not date_str:
        return None
    s = date_str.strip()
    if s.endswith("Z"):
        s = s[:-1]
        if "+" not in s and "-" not in s[10:]:
            s += "+00:00"
    elif not s.endswith("+00:00") and "+" not in s and "-" not in s[10:]:
        s += "+00:00"
    
    if s.endswith("+00:00+00:00"):
        s = s[:-6]
        
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.now(timezone.utc)

def auto_update_expired_subscriptions(conn):
    now = datetime.now(timezone.utc)
    conn.execute(
        """
        UPDATE usuarios 
        SET estado_suscripcion = 'en_mora'
        WHERE plan_tipo IS NOT NULL 
          AND estado_suscripcion IN ('trial', 'activo')
          AND fecha_vencimiento < %s
        """,
        (now,)
    )

def get_dashboard_stats():
    stats = {"trial": 0, "activo": 0, "en_mora": 0, "desactivado": 0}

    if is_configured():
        with connection() as conn:
            auto_update_expired_subscriptions(conn)
            rows = conn.execute(
                """
                SELECT COALESCE(estado_suscripcion, 'activo') as estado, COUNT(*) as count 
                FROM usuarios 
                WHERE email IS NOT NULL AND estado = 'activo'
                GROUP BY COALESCE(estado_suscripcion, 'activo')
                """
            ).fetchall()
            for r in rows:
                k = str(r[0] or "trial").strip().lower()
                if k in stats:
                    stats[k] = int(r[1] or 0)
    else:
        db = read_local_db()
        now = datetime.now(timezone.utc)
        modified = False
        for sub in db["subscriptions"]:
            venc_str = sub.get("fecha_vencimiento") or sub.get("fechaVencimiento")
            status = str(sub.get("estado_suscripcion") or sub.get("estadoSuscripcion") or "trial").strip().lower()
            
            if venc_str:
                venc = safe_parse_datetime(venc_str)
                if status in ("trial", "activo") and venc < now:
                    if "estado_suscripcion" in sub:
                        sub["estado_suscripcion"] = "en_mora"
                    else:
                        sub["estadoSuscripcion"] = "en_mora"
                    status = "en_mora"
                    modified = True
            
            if status in stats:
                stats[status] += 1
        if modified:
            write_local_db(db)

    return stats


def get_admin_clients(status_filter=None, search_query=None):
    clients = []

    if is_configured():
        with connection() as conn:
            auto_update_expired_subscriptions(conn)
            conn.row_factory = dict_row
            query = """
                SELECT id, nombre_completo, email, telefono_whatsapp, 
                       plan_tipo, estado_suscripcion, fecha_vencimiento, 
                       subdominio, requiere_aprobacion, nombre_barberia, creado_en,
                       categoria_slug
                FROM usuarios
                WHERE email IS NOT NULL AND estado = 'activo'
            """
            params = []
            if status_filter and status_filter != 'todos':
                query += " AND COALESCE(estado_suscripcion, 'activo') = %s"
                params.append(status_filter)
            if search_query:
                query += " AND (nombre_completo ILIKE %s OR email ILIKE %s OR COALESCE(nombre_barberia, '') ILIKE %s)"
                q = f"%{search_query}%"
                params.extend([q, q, q])
            
            rows = conn.execute(query, params).fetchall()
            for r in rows:
                clients.append({
                    "id": str(r["id"]),
                    "name": r["nombre_completo"],
                    "email": r["email"],
                    "phone": r["telefono_whatsapp"] or "",
                    "planTipo": r["plan_tipo"] or "trial",
                    "estadoSuscripcion": r["estado_suscripcion"] or "activo",
                    "fechaVencimiento": r["fecha_vencimiento"].isoformat() if r["fecha_vencimiento"] else None,
                    "subdominio": r["subdominio"] or r["email"].split("@")[0],
                    "requiereAprobacion": bool(r["requiere_aprobacion"]),
                    "businessName": r["nombre_barberia"] or r["nombre_completo"],
                    "categoriaSlug": r["categoria_slug"] or "barberia",
                    "creadoEn": r["creado_en"].isoformat() if r["creado_en"] else None
                })
    else:
        db = read_local_db()
        now = datetime.now(timezone.utc)
        modified = False
        for sub in db["subscriptions"]:
            venc_str = sub.get("fecha_vencimiento") or sub.get("fechaVencimiento")
            status = sub.get("estado_suscripcion") or sub.get("estadoSuscripcion") or "trial"
            venc = safe_parse_datetime(venc_str)
            
            if venc_str and venc:
                if status in ("trial", "activo") and venc < now:
                    if "estado_suscripcion" in sub:
                        sub["estado_suscripcion"] = "en_mora"
                    else:
                        sub["estadoSuscripcion"] = "en_mora"
                    status = "en_mora"
                    modified = True

            match = True
            if status_filter and status_filter != 'todos':
                if status != status_filter:
                    match = False
            
            name = sub.get("nombre_completo") or sub.get("name") or ""
            email = sub.get("email") or ""
            business = sub.get("nombre_barberia") or sub.get("businessName") or ""
            
            if search_query:
                sq = search_query.lower()
                if (sq not in name.lower() and
                    sq not in email.lower() and
                    sq not in business.lower()):
                    match = False

            if match:
                creado_dt = safe_parse_datetime(sub.get("creado_en") or sub.get("creadoEn"))
                clients.append({
                    "id": sub.get("id"),
                    "name": name,
                    "email": email,
                    "phone": sub.get("telefono") or sub.get("phone") or "",
                    "planTipo": sub.get("plan_tipo") or sub.get("planTipo") or "trial",
                    "estadoSuscripcion": status,
                    "fechaVencimiento": venc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if venc else None,
                    "subdominio": sub.get("subdominio"),
                    "requiereAprobacion": sub.get("requiere_aprobacion") or sub.get("requiereAprobacion") or False,
                    "businessName": business,
                    "categoriaSlug": sub.get("categoria_slug") or sub.get("categoriaSlug") or "barberia",
                    "creadoEn": creado_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if creado_dt else None
                })
        if modified:
            write_local_db(db)

        clients.sort(key=lambda x: x.get("creadoEn") or "", reverse=True)

    return clients

def create_admin_client(data):
    name = str(data.get("name") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    phone = str(data.get("phone") or "").strip()
    business_name = str(data.get("businessName") or "").strip()
    plan_tipo = str(data.get("planTipo") or "trial").strip().lower()
    estado_suscripcion = str(data.get("estadoSuscripcion") or "trial").strip().lower()
    categoria_slug = str(data.get("categoriaSlug") or "barberia").strip().lower()

    if not name or not email or not phone or not business_name:
        raise ValueError("Todos los campos (nombre, email, teléfono, nombre barbería) son requeridos.")

    # Calculate expiration based on plan
    now = datetime.now(timezone.utc)
    if plan_tipo == 'mensual':
        days = 30
    elif plan_tipo == 'trimestral':
        days = 90
    elif plan_tipo == 'anual':
        days = 365
    else:
        days = 7 # trial
    expiry = now + timedelta(days=days)

    subdomain_slug = clean_subdomain(business_name) + "-" + secrets.token_hex(2)
    subdomain = f"{subdomain_slug}.kauze.cl"

    temp_password = secrets.token_urlsafe(10)

    # Sanitize phone to satisfy check constraint ^\+[1-9][0-9]{7,14}$
    digits = re.sub(r"[^\d]", "", phone)
    if not digits:
        digits = "56912345678"
    if phone.startswith("+"):
        clean_phone = "+" + digits
    elif digits.startswith("56"):
        clean_phone = "+" + digits
    else:
        clean_phone = "+56" + digits
    if len(clean_phone) > 15:
        clean_phone = clean_phone[:15]

    if is_configured():
        try:
            with connection() as conn:
                with conn.transaction():
                    # Check duplicate email
                    exists = conn.execute(
                        "SELECT id FROM usuarios WHERE LOWER(email) = %s", (email,)
                    ).fetchone()
                    if exists:
                        raise ValueError("El correo ya está registrado.")

                    # Create User
                    user_row = conn.execute(
                        """
                        INSERT INTO usuarios (
                            nombre_completo, email, telefono_whatsapp, 
                            plan_tipo, estado_suscripcion, fecha_vencimiento, 
                            subdominio, requiere_aprobacion, nombre_barberia, estado,
                            categoria_slug
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, %s, 'activo', %s)
                        RETURNING id
                        """,
                        (name, email, clean_phone, plan_tipo, estado_suscripcion, expiry, subdomain, business_name, categoria_slug)
                    ).fetchone()
                    user_id = user_row[0]

                    # Create Password Credentials
                    conn.execute(
                        "INSERT INTO credenciales_password (usuario_id, password_hash) VALUES (%s, %s)",
                        (user_id, hasher.hash(temp_password))
                    )

                    # Create Business Local
                    cat = conn.execute("SELECT id FROM categorias WHERE slug = %s AND activo = TRUE", (categoria_slug,)).fetchone()
                    if not cat:
                        cat = conn.execute("SELECT id FROM categorias WHERE activo = TRUE LIMIT 1").fetchone()
                    if not cat:
                        cat = conn.execute(
                            """
                            INSERT INTO categorias (nombre, slug, descripcion)
                            VALUES ('General', 'general', 'Categoría general')
                            ON CONFLICT (slug) DO UPDATE SET activo = TRUE
                            RETURNING id
                            """
                        ).fetchone()
                    cat_id = cat[0]

                    local_row = conn.execute(
                        """
                        INSERT INTO locales (categoria_id, nombre, slug, estado)
                        VALUES (%s, %s, %s, 'activo')
                        RETURNING id
                        """,
                        (cat_id, business_name, subdomain_slug)
                    ).fetchone()
                    local_id = local_row[0]

                    # Assign Owner Role
                    role = conn.execute("SELECT id FROM roles WHERE slug = 'dueno'").fetchone()
                    if role:
                        conn.execute(
                            "INSERT INTO usuario_roles (usuario_id, rol_id, local_id) VALUES (%s, %s, %s)",
                            (user_id, role[0], local_id)
                        )
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Error al guardar en base de datos: {e}")

    else:
        db = read_local_db()
        for sub in db["subscriptions"]:
            if sub["email"].lower() == email:
                raise ValueError("El correo ya está registrado.")

        new_sub = {
            "id": str(uuid.uuid4()),
            "nombre_completo": name,
            "email": email,
            "telefono": phone,
            "nombre_barberia": business_name,
            "plan_tipo": plan_tipo,
            "estado_suscripcion": estado_suscripcion,
            "fecha_vencimiento": expiry.isoformat(),
            "categoria_slug": categoria_slug,
            "subdominio": subdomain,
            "requiere_aprobacion": False,
            "creado_en": now.isoformat()
        }
        db["subscriptions"].append(new_sub)
        write_local_db(db)

    send_credentials_email(email, name, temp_password, subdomain)

    return {
        "status": "success",
        "client": {
            "name": name,
            "email": email,
            "subdominio": subdomain,
            "expiry": expiry.isoformat()
        }
    }

def confirm_client_activation(client_id):
    temp_password = secrets.token_urlsafe(10)
    now = datetime.now(timezone.utc)

    if is_configured():
        with connection() as conn:
            with conn.transaction():
                conn.row_factory = dict_row
                user = conn.execute(
                    """
                    SELECT id, nombre_completo, email, plan_tipo, nombre_barberia,
                           categoria_slug
                    FROM usuarios WHERE id = %s
                    """,
                    (client_id,)
                ).fetchone()
                if not user:
                    raise ValueError("Cliente no encontrado.")

                plan_tipo = user["plan_tipo"] or "trial"
                if plan_tipo == 'mensual':
                    days = 30
                elif plan_tipo == 'trimestral':
                    days = 90
                elif plan_tipo == 'anual':
                    days = 365
                else:
                    days = 7
                expiry = now + timedelta(days=days)

                subdomain_slug = clean_subdomain(user["nombre_barberia"]) + "-" + secrets.token_hex(2)
                subdomain = f"{subdomain_slug}.kauze.cl"

                # Update User
                status = 'trial' if plan_tipo == 'trial' else 'activo'
                conn.execute(
                    """
                    UPDATE usuarios 
                    SET estado_suscripcion = %s,
                        fecha_vencimiento = %s,
                        subdominio = %s,
                        requiere_aprobacion = FALSE,
                        estado = 'activo'
                    WHERE id = %s
                    """,
                    (status, expiry, subdomain, client_id)
                )

                # Insert/Update password
                conn.execute(
                    """
                    INSERT INTO credenciales_password (usuario_id, password_hash)
                    VALUES (%s, %s)
                    ON CONFLICT (usuario_id) DO UPDATE
                    SET password_hash = EXCLUDED.password_hash,
                        intentos_fallidos = 0,
                        bloqueado_hasta = NULL,
                        password_actualizada_en = NOW()
                    """,
                    (client_id, hasher.hash(temp_password))
                )

                # Create Local
                cat_slug = user["categoria_slug"] or "barberia"
                cat = conn.execute("SELECT id FROM categorias WHERE slug = %s", (cat_slug,)).fetchone()
                cat_id = cat["id"] if cat else None
                local_row = conn.execute(
                    """
                    INSERT INTO locales (categoria_id, nombre, slug, estado)
                    VALUES (%s, %s, %s, 'activo')
                    ON CONFLICT (slug) DO UPDATE SET estado = 'activo'
                    RETURNING id
                    """,
                    (cat_id, user["nombre_barberia"], subdomain_slug)
                ).fetchone()
                local_id = local_row["id"]

                # Link Role
                role = conn.execute("SELECT id FROM roles WHERE slug = 'dueno'").fetchone()
                if role:
                    conn.execute(
                        """
                        INSERT INTO usuario_roles (usuario_id, rol_id, local_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (usuario_id, rol_id, local_id) WHERE local_id IS NOT NULL
                        DO NOTHING
                        """,
                        (client_id, role["id"], local_id)
                    )

                email = user["email"]
                name = user["nombre_completo"]
    else:
        db = read_local_db()
        sub = next((item for item in db["subscriptions"] if item["id"] == client_id), None)
        if not sub:
            raise ValueError("Cliente no encontrado.")

        plan_tipo = sub["plan_tipo"] or "trial"
        if plan_tipo == 'mensual':
            days = 30
        elif plan_tipo == 'trimestral':
            days = 90
        elif plan_tipo == 'anual':
            days = 365
        else:
            days = 7
        expiry = now + timedelta(days=days)

        subdomain_slug = clean_subdomain(sub["nombre_barberia"]) + "-" + secrets.token_hex(2)
        subdomain = f"{subdomain_slug}.kauze.cl"

        status = 'trial' if plan_tipo == 'trial' else 'activo'
        sub["estado_suscripcion"] = status
        sub["fecha_vencimiento"] = expiry.isoformat()
        sub["subdominio"] = subdomain
        sub["requiere_aprobacion"] = False
        write_local_db(db)

        email = sub["email"]
        name = sub["nombre_completo"]

    send_credentials_email(email, name, temp_password, subdomain)
    return {"status": "success", "subdominio": subdomain}

def reset_client_password(client_id):
    temp_password = secrets.token_urlsafe(10)

    if is_configured():
        with connection() as conn:
            with conn.transaction():
                conn.row_factory = dict_row
                user = conn.execute(
                    "SELECT id, nombre_completo, email FROM usuarios WHERE id = %s", (client_id,)
                ).fetchone()
                if not user:
                    raise ValueError("Cliente no encontrado.")

                conn.execute(
                    """
                    INSERT INTO credenciales_password (usuario_id, password_hash)
                    VALUES (%s, %s)
                    ON CONFLICT (usuario_id) DO UPDATE
                    SET password_hash = EXCLUDED.password_hash,
                        intentos_fallidos = 0,
                        bloqueado_hasta = NULL,
                        password_actualizada_en = NOW()
                    """,
                    (client_id, hasher.hash(temp_password))
                )
                email = user["email"]
                name = user["nombre_completo"]
    else:
        db = read_local_db()
        sub = next((item for item in db["subscriptions"] if item["id"] == client_id), None)
        if not sub:
            raise ValueError("Cliente no encontrado.")
        email = sub["email"]
        name = sub["nombre_completo"]

    send_reset_password_email(email, name, temp_password)
    return {"status": "success", "message": "Contraseña restablecida correctamente."}


def update_client_details(client_id, data):
    if is_configured():
        with connection() as conn:
            with conn.transaction():
                # Format datetime safely
                venc_dt = safe_parse_datetime(data.get("fechaVencimiento"))
                conn.execute(
                    """
                    UPDATE usuarios
                    SET nombre_completo = %s,
                        email = %s,
                        telefono_whatsapp = %s,
                        plan_tipo = %s,
                        estado_suscripcion = %s,
                        fecha_vencimiento = %s,
                        subdominio = %s,
                        nombre_barberia = %s,
                        categoria_slug = %s
                    WHERE id = %s
                    """,
                    (
                        data["name"],
                        data["email"],
                        data["phone"],
                        data["planTipo"],
                        data["estadoSuscripcion"],
                        venc_dt,
                        data["subdominio"],
                        data["businessName"],
                        data.get("categoriaSlug", "barberia"),
                        client_id
                    )
                )
                local_row = conn.execute(
                    """
                    SELECT local_id FROM usuario_roles ur
                    JOIN roles r ON ur.rol_id = r.id
                    WHERE ur.usuario_id = %s AND r.slug = 'dueno'
                    """,
                    (client_id,)
                ).fetchone()
                if local_row and local_row[0]:
                    conn.execute(
                        """
                        UPDATE locales
                        SET nombre = %s,
                            categoria_id = (SELECT id FROM categorias WHERE slug = %s LIMIT 1)
                        WHERE id = %s
                        """,
                        (data["businessName"], data.get("categoriaSlug", "barberia"), local_row[0])
                    )
        return {"status": "success", "message": "Cliente actualizado correctamente en PostgreSQL."}
    else:
        db = read_local_db()
        for sub in db["subscriptions"]:
            if sub["id"] == client_id:
                name_key = "name" if "name" in sub else "nombre_completo"
                sub[name_key] = data["name"]
                sub["email"] = data["email"]
                phone_key = "phone" if "phone" in sub else "telefono"
                sub[phone_key] = data["phone"]
                plan_key = "planTipo" if "planTipo" in sub else "plan_tipo"
                sub[plan_key] = data["planTipo"]
                status_key = "estadoSuscripcion" if "estadoSuscripcion" in sub else "estado_suscripcion"
                sub[status_key] = data["estadoSuscripcion"]
                venc_key = "fechaVencimiento" if "fechaVencimiento" in sub else "fecha_vencimiento"
                sub[venc_key] = data["fechaVencimiento"]
                sub["subdominio"] = data["subdominio"]
                bus_key = "businessName" if "businessName" in sub else "nombre_barberia"
                sub[bus_key] = data["businessName"]
                cat_key = "categoriaSlug" if "categoriaSlug" in sub else "categoria_slug"
                sub[cat_key] = data.get("categoriaSlug", "barberia")
                
                write_local_db(db)
                from backend.simulations import log_simulation
                log_simulation("Modificación de Cliente (JSON)", data["email"], f"Modificados datos del barbero '{data['name']}' / Negocio: '{data['businessName']}'.")
                return {"status": "success", "message": "Cliente modificado en base de datos local."}
        raise ValueError("Cliente no encontrado.")

def delete_client(client_id):
    if is_configured():
        with connection() as conn:
            with conn.transaction():
                local_row = conn.execute(
                    """
                    SELECT local_id FROM usuario_roles ur
                    JOIN roles r ON ur.rol_id = r.id
                    WHERE ur.usuario_id = %s AND r.slug = 'dueno'
                    """,
                    (client_id,)
                ).fetchone()
                
                if local_row and local_row[0]:
                    local_id = local_row[0]
                    conn.execute("DELETE FROM suscripciones_saas WHERE local_id = %s", (local_id,))
                    conn.execute("DELETE FROM estados_panel_local WHERE local_id = %s", (local_id,))
                    conn.execute("DELETE FROM usuario_roles WHERE local_id = %s", (local_id,))
                    conn.execute("DELETE FROM locales WHERE id = %s", (local_id,))
                
                conn.execute("DELETE FROM usuario_roles WHERE usuario_id = %s", (client_id,))
                conn.execute("DELETE FROM tokens_restablecimiento_password WHERE usuario_id = %s", (client_id,))
                conn.execute("DELETE FROM usuarios WHERE id = %s", (client_id,))
        return {"status": "success", "message": "Cliente eliminado completamente de PostgreSQL."}
    else:
        db = read_local_db()
        orig_len = len(db["subscriptions"])
        db["subscriptions"] = [s for s in db["subscriptions"] if s["id"] != client_id]
        if len(db["subscriptions"]) == orig_len:
            raise ValueError("Cliente no encontrado.")
        write_local_db(db)
        from backend.simulations import log_simulation
        log_simulation("Eliminación de Cliente (JSON)", client_id, "Eliminado registro de barbero de 'subscriptions_db.json'.")
        return {"status": "success", "message": "Cliente eliminado de la base de datos local."}

def update_client_details(client_id, data):
    if is_configured():
        with connection() as conn:
            with conn.transaction():
                # Format datetime safely
                venc_dt = safe_parse_datetime(data.get("fechaVencimiento"))
                conn.execute(
                    """
                    UPDATE usuarios
                    SET nombre_completo = %s,
                        email = %s,
                        telefono_whatsapp = %s,
                        plan_tipo = %s,
                        estado_suscripcion = %s,
                        fecha_vencimiento = %s,
                        subdominio = %s,
                        nombre_barberia = %s,
                        categoria_slug = %s
                    WHERE id = %s
                    """,
                    (
                        data["name"],
                        data["email"],
                        data["phone"],
                        data["planTipo"],
                        data["estadoSuscripcion"],
                        venc_dt,
                        data["subdominio"],
                        data["businessName"],
                        data.get("categoriaSlug", "barberia"),
                        client_id
                    )
                )
                local_row = conn.execute(
                    """
                    SELECT local_id FROM usuario_roles ur
                    JOIN roles r ON ur.rol_id = r.id
                    WHERE ur.usuario_id = %s AND r.slug = 'dueno'
                    """,
                    (client_id,)
                ).fetchone()
                if local_row and local_row[0]:
                    conn.execute(
                        """
                        UPDATE locales
                        SET nombre = %s,
                            categoria_id = (SELECT id FROM categorias WHERE slug = %s LIMIT 1)
                        WHERE id = %s
                        """,
                        (data["businessName"], data.get("categoriaSlug", "barberia"), local_row[0])
                    )
        return {"status": "success", "message": "Cliente actualizado correctamente en PostgreSQL."}
    else:
        db = read_local_db()
        for sub in db["subscriptions"]:
            if sub["id"] == client_id:
                name_key = "name" if "name" in sub else "nombre_completo"
                sub[name_key] = data["name"]
                sub["email"] = data["email"]
                phone_key = "phone" if "phone" in sub else "telefono"
                sub[phone_key] = data["phone"]
                plan_key = "planTipo" if "planTipo" in sub else "plan_tipo"
                sub[plan_key] = data["planTipo"]
                status_key = "estadoSuscripcion" if "estadoSuscripcion" in sub else "estado_suscripcion"
                sub[status_key] = data["estadoSuscripcion"]
                venc_key = "fechaVencimiento" if "fechaVencimiento" in sub else "fecha_vencimiento"
                sub[venc_key] = data["fechaVencimiento"]
                sub["subdominio"] = data["subdominio"]
                bus_key = "businessName" if "businessName" in sub else "nombre_barberia"
                sub[bus_key] = data["businessName"]
                cat_key = "categoriaSlug" if "categoriaSlug" in sub else "categoria_slug"
                sub[cat_key] = data.get("categoriaSlug", "barberia")
                
                write_local_db(db)
                from backend.simulations import log_simulation
                log_simulation("Modificación de Cliente (JSON)", data["email"], f"Modificados datos del barbero '{data['name']}' / Negocio: '{data['businessName']}'.")
                return {"status": "success", "message": "Cliente modificado en base de datos local."}
        raise ValueError("Cliente no encontrado.")

def delete_client(client_id):
    if is_configured():
        with connection() as conn:
            with conn.transaction():
                local_row = conn.execute(
                    """
                    SELECT local_id FROM usuario_roles ur
                    JOIN roles r ON ur.rol_id = r.id
                    WHERE ur.usuario_id = %s AND r.slug = 'dueno'
                    """,
                    (client_id,)
                ).fetchone()
                
                if local_row and local_row[0]:
                    local_id = local_row[0]
                    conn.execute("DELETE FROM suscripciones_saas WHERE local_id = %s", (local_id,))
                    conn.execute("DELETE FROM estados_panel_local WHERE local_id = %s", (local_id,))
                    conn.execute("DELETE FROM usuario_roles WHERE local_id = %s", (local_id,))
                    conn.execute("DELETE FROM locales WHERE id = %s", (local_id,))
                
                conn.execute("DELETE FROM usuario_roles WHERE usuario_id = %s", (client_id,))
                conn.execute("DELETE FROM tokens_restablecimiento_password WHERE usuario_id = %s", (client_id,))
                conn.execute("DELETE FROM usuarios WHERE id = %s", (client_id,))
        return {"status": "success", "message": "Cliente eliminado completamente de PostgreSQL."}
    else:
        db = read_local_db()
        orig_len = len(db["subscriptions"])
        db["subscriptions"] = [s for s in db["subscriptions"] if s["id"] != client_id]
        if len(db["subscriptions"]) == orig_len:
            raise ValueError("Cliente no encontrado.")
        write_local_db(db)
        from backend.simulations import log_simulation
        log_simulation("Eliminación de Cliente (JSON)", client_id, "Eliminado registro de barbero de 'subscriptions_db.json'.")
        return {"status": "success", "message": "Cliente eliminado de la base de datos local."}
