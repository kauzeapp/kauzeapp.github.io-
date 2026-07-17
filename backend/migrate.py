import hashlib
import os
import re
from pathlib import Path

import psycopg
from argon2 import PasswordHasher

from backend.db import database_url


DATABASE_DIR = Path(__file__).resolve().parent / "database"
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def apply_migrations(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          nombre TEXT PRIMARY KEY,
          aplicado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    for path in sorted(DATABASE_DIR.glob("*.sql")):
        applied = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE nombre = %s", (path.name,)
        ).fetchone()
        if applied:
            continue
        conn.execute(path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations (nombre) VALUES (%s)", (path.name,)
        )
        print(f"Migración aplicada: {path.name}")


def bootstrap_owner(conn):
    email = os.environ.get("KAUZE_BOOTSTRAP_EMAIL", "").strip().lower()
    password = os.environ.get("KAUZE_BOOTSTRAP_PASSWORD", "")
    invite_token = os.environ.get("KAUZE_BOOTSTRAP_INVITE_TOKEN", "")
    local_slug = os.environ.get("KAUZE_BOOTSTRAP_LOCAL_SLUG", "").strip().lower()
    if not email or not local_slug or (not password and not invite_token):
        print("Cuenta inicial: omitida (variables KAUZE_BOOTSTRAP_* incompletas).")
        return
    if "@" not in email:
        raise ValueError("KAUZE_BOOTSTRAP_EMAIL no es válido.")
    if password and len(password) < 12:
        raise ValueError("KAUZE_BOOTSTRAP_PASSWORD debe tener al menos 12 caracteres.")
    if invite_token and len(invite_token) < 32:
        raise ValueError("KAUZE_BOOTSTRAP_INVITE_TOKEN debe tener al menos 32 caracteres.")
    if not SLUG_PATTERN.fullmatch(local_slug):
        raise ValueError("KAUZE_BOOTSTRAP_LOCAL_SLUG no tiene un formato válido.")

    owner_name = os.environ.get("KAUZE_BOOTSTRAP_OWNER_NAME", "Dueño KAUZE").strip()
    local_name = os.environ.get("KAUZE_BOOTSTRAP_LOCAL_NAME", "Negocio KAUZE").strip()
    category_slug = os.environ.get("KAUZE_BOOTSTRAP_CATEGORY", "barberia").strip()

    category = conn.execute(
        "SELECT id FROM categorias WHERE slug = %s AND activo = TRUE",
        (category_slug,),
    ).fetchone()
    if not category:
        raise ValueError(f"La categoría '{category_slug}' no existe.")

    local = conn.execute(
        """
        INSERT INTO locales (categoria_id, nombre, slug, estado)
        VALUES (%s, %s, %s, 'activo')
        ON CONFLICT (slug) DO UPDATE
        SET nombre = EXCLUDED.nombre,
            categoria_id = EXCLUDED.categoria_id,
            estado = 'activo',
            actualizado_en = NOW()
        RETURNING id
        """,
        (category[0], local_name, local_slug),
    ).fetchone()

    user = conn.execute(
        """
        INSERT INTO usuarios (nombre_completo, email, estado)
        VALUES (%s, %s, 'activo')
        ON CONFLICT (LOWER(email)) WHERE email IS NOT NULL DO UPDATE
        SET nombre_completo = EXCLUDED.nombre_completo,
            estado = 'activo',
            actualizado_en = NOW()
        RETURNING id
        """,
        (owner_name, email),
    ).fetchone()

    existing_credential = conn.execute(
        "SELECT 1 FROM credenciales_password WHERE usuario_id = %s", (user[0],)
    ).fetchone()
    if password:
        hasher = PasswordHasher(
            time_cost=2,
            memory_cost=19456,
            parallelism=1,
            hash_len=32,
            salt_len=16,
        )
        if not existing_credential:
            conn.execute(
                "INSERT INTO credenciales_password (usuario_id, password_hash) VALUES (%s, %s)",
                (user[0], hasher.hash(password)),
            )
        elif os.environ.get("KAUZE_BOOTSTRAP_ROTATE_PASSWORD", "0") == "1":
            conn.execute(
                """
                UPDATE credenciales_password
                SET password_hash = %s,
                    intentos_fallidos = 0,
                    bloqueado_hasta = NULL,
                    password_actualizada_en = NOW()
                WHERE usuario_id = %s
                """,
                (hasher.hash(password), user[0]),
            )

    if invite_token and not existing_credential:
        conn.execute(
            """
            INSERT INTO tokens_restablecimiento_password (usuario_id, token_hash, expira_en)
            VALUES (%s, %s, NOW() + INTERVAL '24 hours')
            ON CONFLICT (token_hash) DO NOTHING
            """,
            (user[0], hashlib.sha256(invite_token.encode("utf-8")).hexdigest()),
        )

    owner_role = conn.execute(
        "SELECT id FROM roles WHERE slug = 'dueno' AND activo = TRUE"
    ).fetchone()
    conn.execute(
        """
        INSERT INTO usuario_roles (usuario_id, rol_id, local_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (usuario_id, rol_id, local_id) WHERE local_id IS NOT NULL
        DO NOTHING
        """,
        (user[0], owner_role[0], local[0]),
    )
    print(f"Cuenta inicial lista para el negocio: {local_slug}")


def main():
    url = database_url()
    if not url:
        print("Migraciones omitidas: DATABASE_URL no está configurada.")
        return

    with psycopg.connect(url, autocommit=True) as conn:
        apply_migrations(conn)
        with conn.transaction():
            bootstrap_owner(conn)


if __name__ == "__main__":
    main()
