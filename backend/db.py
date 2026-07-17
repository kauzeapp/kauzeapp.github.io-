import os
import threading
from contextlib import contextmanager


_pool = None
_pool_lock = threading.Lock()


class DatabaseNotConfigured(RuntimeError):
    pass


def database_url():
    return os.environ.get("DATABASE_URL", "").strip()


def is_configured():
    return bool(database_url())


def get_pool():
    global _pool
    if _pool is not None:
        return _pool

    url = database_url()
    if not url:
        raise DatabaseNotConfigured("DATABASE_URL no está configurada.")

    with _pool_lock:
        if _pool is None:
            from psycopg_pool import ConnectionPool

            _pool = ConnectionPool(
                conninfo=url,
                min_size=1,
                max_size=int(os.environ.get("KAUZE_DB_POOL_MAX", "5")),
                timeout=10,
                open=True,
                check=ConnectionPool.check_connection,
            )
    return _pool


@contextmanager
def connection():
    with get_pool().connection() as conn:
        yield conn


def close_pool():
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
