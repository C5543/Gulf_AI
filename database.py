import mysql.connector
from mysql.connector import pooling

from config import (
    DB_HOST,
    DB_PORT,
    DB_NAME,
    DB_USER,
    DB_PASSWORD,
)

_db_pool = None


def get_connection_pool():
    global _db_pool

    if _db_pool is None:

        if not DB_HOST or not DB_NAME or not DB_USER:
            raise RuntimeError(
                "Database settings are missing. "
                "Add DB_HOST, DB_PORT, DB_NAME, DB_USER and DB_PASSWORD to .env"
            )

        _db_pool = pooling.MySQLConnectionPool(
            pool_name="gulf_ai_pool",
            pool_size=8,
            pool_reset_session=True,

            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,

            charset="utf8mb4",
            collation="utf8mb4_unicode_ci",

            autocommit=False,
        )

    return _db_pool


def get_db_connection():
    conn = get_connection_pool().get_connection()

    conn.set_charset_collation(
        "utf8mb4",
        "utf8mb4_unicode_ci"
    )

    return conn