import uuid
from contextlib import contextmanager

from backend.db import connection


def _uuid_text(value, field_name):
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field_name} no es un UUID válido.") from exc


def set_tenant_context(conn, local_id, user_id=None):
    """Fija el negocio actual solo durante la transacción en curso."""
    normalized_local_id = _uuid_text(local_id, "local_id")
    conn.execute("SELECT set_config('app.local_id', %s, TRUE)", (normalized_local_id,))

    if user_id is not None:
        normalized_user_id = _uuid_text(user_id, "user_id")
        conn.execute("SELECT set_config('app.user_id', %s, TRUE)", (normalized_user_id,))

    return normalized_local_id


@contextmanager
def tenant_connection(local_id, user_id=None):
    """Entrega una conexión con el tenant fijado y la revierte al terminar."""
    with connection() as conn:
        with conn.transaction():
            set_tenant_context(conn, local_id, user_id)
            yield conn
