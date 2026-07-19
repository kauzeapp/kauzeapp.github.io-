import hashlib
import os
import re
import uuid
from pathlib import Path

import psycopg
from argon2 import PasswordHasher

from backend.db import database_url
from backend.tenant import TENANT_RUNTIME_ROLE


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


def verify_owner_business_model(conn):
    required_relations = (
        "clientes",
        "reservas",
        "suscripciones_saas",
        "kauze_backups.pre_owner_model_usuarios",
        "kauze_backups.pre_owner_model_locales",
        "kauze_backups.pre_owner_model_profesionales",
    )
    missing = [
        relation
        for relation in required_relations
        if conn.execute("SELECT to_regclass(%s)", (relation,)).fetchone()[0] is None
    ]
    if missing:
        raise RuntimeError(
            "La migración del modelo dueño/negocio quedó incompleta: "
            + ", ".join(missing)
        )

    professional_user_nullable = conn.execute(
        """
        SELECT is_nullable = 'YES'
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'profesionales'
          AND column_name = 'usuario_id'
        """
    ).fetchone()
    if not professional_user_nullable or not professional_user_nullable[0]:
        raise RuntimeError("Los profesionales todavía exigen una cuenta de usuario.")

    rls_rows = conn.execute(
        """
        SELECT relname, relrowsecurity, relforcerowsecurity
        FROM pg_class
        WHERE relnamespace = 'public'::regnamespace
          AND relname IN (
            'profesionales',
            'servicios',
            'clientes',
            'reservas',
            'suscripciones_saas',
            'estados_panel_local',
            'eventos_reserva'
          )
        """
    ).fetchall()
    invalid_rls = [
        row[0]
        for row in rls_rows
        if not bool(row[1]) or not bool(row[2])
    ]
    if len(rls_rows) != 7 or invalid_rls:
        raise RuntimeError("RLS no quedó forzado en todas las tablas multi-negocio.")

    runtime_role = conn.execute(
        "SELECT rolcanlogin, rolinherit, rolbypassrls FROM pg_roles WHERE rolname = %s",
        (TENANT_RUNTIME_ROLE,),
    ).fetchone()
    if not runtime_role or any(bool(value) for value in runtime_role):
        raise RuntimeError("El rol limitado de negocio no quedó configurado de forma segura.")

    print("Modelo dueño/negocio verificado: backups, fichas internas y RLS activos.")


def verify_tenant_row_isolation(conn):
    """Prueba RLS con dos negocios temporales y revierte ante cualquier fallo."""
    suffix = uuid.uuid4().hex[:12]
    with conn.transaction():
        category = conn.execute(
            "SELECT id FROM categorias WHERE activo = TRUE ORDER BY slug LIMIT 1"
        ).fetchone()
        if not category:
            raise RuntimeError("No existe una categoría activa para probar RLS.")

        local_a = conn.execute(
            """
            INSERT INTO locales (categoria_id, nombre, slug, estado)
            VALUES (%s, %s, %s, 'activo')
            RETURNING id
            """,
            (category[0], "Prueba seguridad A", f"seguridad-a-{suffix}"),
        ).fetchone()[0]
        local_b = conn.execute(
            """
            INSERT INTO locales (categoria_id, nombre, slug, estado)
            VALUES (%s, %s, %s, 'activo')
            RETURNING id
            """,
            (category[0], "Prueba seguridad B", f"seguridad-b-{suffix}"),
        ).fetchone()[0]

        conn.execute(f"SET LOCAL ROLE {TENANT_RUNTIME_ROLE}")
        conn.execute("SELECT set_config('app.local_id', %s, TRUE)", (str(local_a),))
        service_a = conn.execute(
            """
            INSERT INTO servicios (
              local_id, nombre, slug, duracion_minutos, precio_clp, activo
            ) VALUES (%s, 'Servicio aislado A', %s, 30, 10000, TRUE)
            RETURNING id
            """,
            (local_a, f"servicio-aislado-{suffix}"),
        ).fetchone()[0]

        conn.execute("SELECT set_config('app.local_id', %s, TRUE)", (str(local_b),))
        leaked = conn.execute(
            "SELECT 1 FROM servicios WHERE id = %s",
            (service_a,),
        ).fetchone()
        if leaked:
            raise RuntimeError(
                "Fallo crítico RLS: el negocio B pudo leer un servicio del negocio A."
            )

        cross_write_blocked = False
        try:
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO servicios (
                      local_id, nombre, slug, duracion_minutos, precio_clp, activo
                    ) VALUES (%s, 'Escritura cruzada', %s, 30, 10000, TRUE)
                    """,
                    (local_a, f"escritura-cruzada-{suffix}"),
                )
        except psycopg.errors.InsufficientPrivilege:
            cross_write_blocked = True

        if not cross_write_blocked:
            raise RuntimeError(
                "Fallo crítico RLS: el negocio B pudo escribir dentro del negocio A."
            )

        conn.execute("SELECT set_config('app.local_id', %s, TRUE)", (str(local_a),))
        conn.execute("DELETE FROM servicios WHERE id = %s", (service_a,))

        conn.execute("RESET ROLE")
        conn.execute("DELETE FROM locales WHERE id IN (%s, %s)", (local_a, local_b))

    print("Aislamiento RLS verificado: negocio B no puede leer ni escribir datos de A.")


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
        INSERT INTO usuarios (
          nombre_completo,
          email,
          estado,
          proveedor_auth,
          email_verificado
        )
        VALUES (%s, %s, 'activo', 'password', TRUE)
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


def provision_demo_businesses(conn):
    function_name = conn.execute(
        "SELECT to_regprocedure('provisionar_masterplan_demo()')"
    ).fetchone()[0]
    if not function_name:
        return
    provisioned = conn.execute("SELECT provisionar_masterplan_demo()").fetchone()[0]
    if provisioned:
        print("Negocio de prueba Masterplan listo.")


def main():
    url = database_url()
    if not url:
        print("Migraciones omitidas: DATABASE_URL no está configurada.")
        return

    with psycopg.connect(url, autocommit=True) as conn:
        apply_migrations(conn)
        verify_owner_business_model(conn)
        verify_tenant_row_isolation(conn)
        with conn.transaction():
            bootstrap_owner(conn)
            provision_demo_businesses(conn)


if __name__ == "__main__":
    main()
