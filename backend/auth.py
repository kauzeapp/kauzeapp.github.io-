import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.db import connection
from backend.email_delivery import email_delivery_configured, send_email
from backend.tenant import tenant_connection


SESSION_HOURS = 8
REMEMBER_DAYS = 30
LOCK_AFTER_ATTEMPTS = 5
LOCK_MINUTES = 15
RESET_MINUTES = 30
MIN_PASSWORD_LENGTH = 12

_password_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)
_dummy_hash = _password_hasher.hash(secrets.token_urlsafe(24))


class InvalidCredentials(RuntimeError):
    pass


class AccountUnavailable(RuntimeError):
    pass


class BusinessSelectionRequired(RuntimeError):
    def __init__(self, businesses):
        super().__init__("Se debe elegir un negocio.")
        self.businesses = businesses


def _sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _verify_or_dummy(password, encoded_hash=None):
    target = encoded_hash or _dummy_hash
    try:
        return _password_hasher.verify(target, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _profile_image_value(value):
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if re.fullmatch(
        r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+",
        candidate,
    ) and len(candidate) <= 750_000:
        return candidate
    if candidate.startswith("https://") and len(candidate) <= 1_000:
        return candidate
    raise ValueError("La imagen de perfil no es válida.")


def _account_payload(row):
    return {
        "user": {
            "id": str(row["usuario_id"]),
            "name": row["nombre_completo"],
            "email": row["email"],
            "profileImage": row.get("foto_perfil_url") or "",
        },
        "business": {
            "id": str(row["local_id"]),
            "name": row["local_nombre"],
            "slug": row["local_slug"],
            "type": row["categoria_slug"],
            "status": row["local_estado"],
        },
        "role": {
            "id": str(row["rol_id"]),
            "name": row["rol_nombre"],
            "slug": row["rol_slug"],
        },
        "isSuperAdmin": bool(row.get("is_superadmin")),
    }


def login(email, password, remember=False, local_slug=None, user_agent=""):
    normalized_email = str(email or "").strip().lower()
    password = str(password or "")
    if not normalized_email or not password:
        _verify_or_dummy(password)
        raise InvalidCredentials()

    with connection() as conn:
        conn.row_factory = dict_row
        credential = conn.execute(
            """
            SELECT
              u.id AS usuario_id,
              u.nombre_completo,
              u.email,
              u.estado AS usuario_estado,
              c.password_hash,
              c.intentos_fallidos,
              c.bloqueado_hasta
            FROM usuarios u
            LEFT JOIN credenciales_password c ON c.usuario_id = u.id
            WHERE LOWER(u.email) = %s
            LIMIT 1
            """,
            (normalized_email,),
        ).fetchone()

        if not credential or not credential["password_hash"]:
            _verify_or_dummy(password)
            raise InvalidCredentials()

        now = datetime.now(timezone.utc)
        locked_until = credential["bloqueado_hasta"]
        if credential["usuario_estado"] != "activo" or (
            locked_until and locked_until > now
        ):
            _verify_or_dummy(password)
            raise InvalidCredentials()

        if not _verify_or_dummy(password, credential["password_hash"]):
            attempts = min(int(credential["intentos_fallidos"] or 0) + 1, 50)
            conn.execute(
                """
                UPDATE credenciales_password
                SET intentos_fallidos = %s,
                    bloqueado_hasta = CASE
                      WHEN %s >= %s THEN NOW() + (%s * INTERVAL '1 minute')
                      ELSE NULL
                    END
                WHERE usuario_id = %s
                """,
                (
                    attempts,
                    attempts,
                    LOCK_AFTER_ATTEMPTS,
                    LOCK_MINUTES,
                    credential["usuario_id"],
                ),
            )
            conn.commit()
            raise InvalidCredentials()

        memberships = conn.execute(
            """
            SELECT
              u.id AS usuario_id,
              u.nombre_completo,
              u.email,
              u.foto_perfil_url,
              l.id AS local_id,
              l.nombre AS local_nombre,
              l.slug AS local_slug,
              l.estado AS local_estado,
              c.slug AS categoria_slug,
              r.id AS rol_id,
              r.nombre AS rol_nombre,
              r.slug AS rol_slug,
              EXISTS (
                SELECT 1
                FROM usuario_roles ur_admin
                INNER JOIN roles r_admin
                  ON r_admin.id = ur_admin.rol_id
                 AND r_admin.slug = 'superadmin'
                 AND r_admin.activo = TRUE
                WHERE ur_admin.usuario_id = u.id
                  AND ur_admin.local_id IS NULL
              ) AS is_superadmin
            FROM usuarios u
            INNER JOIN usuario_roles ur ON ur.usuario_id = u.id
            INNER JOIN roles r ON r.id = ur.rol_id AND r.activo = TRUE
            INNER JOIN locales l ON l.id = ur.local_id AND l.estado = 'activo'
            INNER JOIN categorias c ON c.id = l.categoria_id AND c.activo = TRUE
            WHERE u.id = %s
              AND r.slug = 'dueno'
            ORDER BY
              l.nombre
            """,
            (credential["usuario_id"],),
        ).fetchall()

        if not memberships:
            raise AccountUnavailable("La cuenta no tiene un negocio activo asignado.")

        selected = None
        if local_slug:
            selected = next(
                (row for row in memberships if row["local_slug"] == local_slug), None
            )
            if selected is None:
                raise AccountUnavailable("El negocio indicado no está disponible.")
        elif len(memberships) == 1:
            selected = memberships[0]
        else:
            businesses = [
                {
                    "name": row["local_nombre"],
                    "slug": row["local_slug"],
                    "role": row["rol_nombre"],
                    "type": row["categoria_slug"],
                }
                for row in memberships
            ]
            raise BusinessSelectionRequired(businesses)

        if _password_hasher.check_needs_rehash(credential["password_hash"]):
            conn.execute(
                """
                UPDATE credenciales_password
                SET password_hash = %s, password_actualizada_en = NOW()
                WHERE usuario_id = %s
                """,
                (_password_hasher.hash(password), credential["usuario_id"]),
            )

        conn.execute(
            """
            UPDATE credenciales_password
            SET intentos_fallidos = 0, bloqueado_hasta = NULL
            WHERE usuario_id = %s
            """,
            (credential["usuario_id"],),
        )
        conn.execute(
            "UPDATE usuarios SET ultimo_acceso_en = NOW() WHERE id = %s",
            (credential["usuario_id"],),
        )
        conn.execute(
            "DELETE FROM sesiones_auth WHERE expira_en <= NOW() OR revocada_en IS NOT NULL"
        )

        session_token = secrets.token_urlsafe(48)
        expires_at = now + (
            timedelta(days=REMEMBER_DAYS)
            if remember
            else timedelta(hours=SESSION_HOURS)
        )
        user_agent_hash = _sha256(user_agent) if user_agent else None
        conn.execute(
            """
            INSERT INTO sesiones_auth (
              usuario_id, local_id, rol_id, token_hash, user_agent_hash, expira_en
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                selected["usuario_id"],
                selected["local_id"],
                selected["rol_id"],
                _sha256(session_token),
                user_agent_hash,
                expires_at,
            ),
        )

        return {
            "token": session_token,
            "expires_at": expires_at,
            "remember": bool(remember),
            "account": _account_payload(selected),
        }


def current_session(session_token):
    if not session_token:
        return None

    with connection() as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            """
            SELECT
              s.id AS session_id,
              u.id AS usuario_id,
              u.nombre_completo,
              u.email,
              u.foto_perfil_url,
              l.id AS local_id,
              l.nombre AS local_nombre,
              l.slug AS local_slug,
              l.estado AS local_estado,
              c.slug AS categoria_slug,
              r.id AS rol_id,
              r.nombre AS rol_nombre,
              r.slug AS rol_slug,
              s.expira_en,
              EXISTS (
                SELECT 1
                FROM usuario_roles ur_admin
                INNER JOIN roles r_admin
                  ON r_admin.id = ur_admin.rol_id
                 AND r_admin.slug = 'superadmin'
                 AND r_admin.activo = TRUE
                WHERE ur_admin.usuario_id = u.id
                  AND ur_admin.local_id IS NULL
              ) AS is_superadmin
            FROM sesiones_auth s
            INNER JOIN usuarios u ON u.id = s.usuario_id AND u.estado = 'activo'
            INNER JOIN locales l ON l.id = s.local_id AND l.estado = 'activo'
            INNER JOIN categorias c ON c.id = l.categoria_id AND c.activo = TRUE
            INNER JOIN roles r ON r.id = s.rol_id AND r.activo = TRUE
            INNER JOIN usuario_roles ur
              ON ur.usuario_id = s.usuario_id
             AND ur.local_id = s.local_id
             AND ur.rol_id = s.rol_id
            WHERE s.token_hash = %s
              AND s.revocada_en IS NULL
              AND s.expira_en > NOW()
              AND r.slug = 'dueno'
            LIMIT 1
            """,
            (_sha256(session_token),),
        ).fetchone()

        if row:
            conn.execute(
                "UPDATE sesiones_auth SET ultimo_uso_en = NOW() WHERE id = %s",
                (row["session_id"],),
            )
            return _account_payload(row)
        return None


def logout(session_token):
    if not session_token:
        return
    with connection() as conn:
        conn.execute(
            "UPDATE sesiones_auth SET revocada_en = NOW() WHERE token_hash = %s",
            (_sha256(session_token),),
        )


def load_business_state(local_id):
    with tenant_connection(local_id) as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            "SELECT estado, version, actualizado_en FROM estados_panel_local WHERE local_id = %s",
            (local_id,),
        ).fetchone()
        if not row:
            return {"state": {}, "version": 0}
        return {
            "state": row["estado"],
            "version": int(row["version"]),
            "updatedAt": row["actualizado_en"].isoformat(),
        }


def save_business_state(local_id, user_id, state):
    if not isinstance(state, dict):
        raise ValueError("El estado del panel debe ser un objeto.")
    with tenant_connection(local_id, user_id) as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            """
            INSERT INTO estados_panel_local (local_id, estado, actualizado_por)
            VALUES (%s, %s, %s)
            ON CONFLICT (local_id) DO UPDATE
            SET estado = EXCLUDED.estado,
                actualizado_por = EXCLUDED.actualizado_por,
                actualizado_en = NOW(),
                version = estados_panel_local.version + 1
            RETURNING version, actualizado_en
            """,
            (local_id, Jsonb(state), user_id),
        ).fetchone()
        return {
            "version": int(row["version"]),
            "updatedAt": row["actualizado_en"].isoformat(),
        }


def update_user_profile_image(user_id, profile_image):
    normalized = _profile_image_value(profile_image)
    with connection() as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            """
            UPDATE usuarios
            SET foto_perfil_url = %s,
                actualizado_en = NOW()
            WHERE id = %s AND estado = 'activo'
            RETURNING foto_perfil_url
            """,
            (normalized, user_id),
        ).fetchone()
        if not row:
            raise AccountUnavailable("La cuenta no está disponible.")
        return {"profileImage": row["foto_perfil_url"] or ""}


def _smtp_is_configured():
    return email_delivery_configured()


def _send_reset_email(recipient, reset_url):
    content = (
        "Recibimos una solicitud para restablecer tu contraseña de KAUZE.\n\n"
        f"Abre este enlace durante los próximos {RESET_MINUTES} minutos:\n"
        f"{reset_url}\n\n"
        "Si no solicitaste este cambio, ignora este mensaje."
    )
    send_email(recipient, "Restablece tu acceso a KAUZE", content)


def request_password_reset(email):
    normalized_email = str(email or "").strip().lower()
    if not normalized_email or not _smtp_is_configured():
        return False

    raw_token = secrets.token_urlsafe(48)
    with connection() as conn:
        conn.row_factory = dict_row
        user = conn.execute(
            "SELECT id, email FROM usuarios WHERE LOWER(email) = %s AND estado = 'activo'",
            (normalized_email,),
        ).fetchone()
        if not user:
            return False
        recent = conn.execute(
            """
            SELECT 1
            FROM tokens_restablecimiento_password
            WHERE usuario_id = %s
              AND usado_en IS NULL
              AND creado_en > NOW() - INTERVAL '2 minutes'
            """,
            (user["id"],),
        ).fetchone()
        if recent:
            return True
        conn.execute(
            "DELETE FROM tokens_restablecimiento_password WHERE usuario_id = %s OR expira_en <= NOW()",
            (user["id"],),
        )
        conn.execute(
            """
            INSERT INTO tokens_restablecimiento_password (usuario_id, token_hash, expira_en)
            VALUES (%s, %s, NOW() + (%s * INTERVAL '1 minute'))
            """,
            (user["id"], _sha256(raw_token), RESET_MINUTES),
        )

    public_url = os.environ.get("KAUZE_PUBLIC_URL", "https://kauze.cl").rstrip("/")
    reset_url = f"{public_url}/app/?reset_token={raw_token}"
    try:
        _send_reset_email(normalized_email, reset_url)
        return True
    except Exception:
        with connection() as conn:
            conn.execute(
                "DELETE FROM tokens_restablecimiento_password WHERE token_hash = %s",
                (_sha256(raw_token),),
            )
        raise


def reset_password(raw_token, new_password):
    raw_token = str(raw_token or "")
    new_password = str(new_password or "")
    if len(new_password) < MIN_PASSWORD_LENGTH or len(new_password) > 128:
        raise ValueError(
            f"La contraseña debe tener entre {MIN_PASSWORD_LENGTH} y 128 caracteres."
        )

    with connection() as conn:
        conn.row_factory = dict_row
        token = conn.execute(
            """
            SELECT id, usuario_id, proposito
            FROM tokens_restablecimiento_password
            WHERE token_hash = %s
              AND usado_en IS NULL
              AND expira_en > NOW()
            FOR UPDATE
            """,
            (_sha256(raw_token),),
        ).fetchone()
        if not token:
            raise ValueError("El enlace venció o ya fue utilizado.")

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
            (token["usuario_id"], _password_hasher.hash(new_password)),
        )
        conn.execute(
            "UPDATE tokens_restablecimiento_password SET usado_en = NOW() WHERE id = %s",
            (token["id"],),
        )
        if token["proposito"] == "acceso_inicial":
            conn.execute(
                """
                UPDATE usuarios
                SET email_verificado = TRUE,
                    estado = 'activo',
                    actualizado_en = NOW()
                WHERE id = %s
                """,
                (token["usuario_id"],),
            )
        conn.execute(
            "UPDATE sesiones_auth SET revocada_en = NOW() WHERE usuario_id = %s AND revocada_en IS NULL",
            (token["usuario_id"],),
        )
