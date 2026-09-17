import json
import secrets
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from starlette.datastructures import MutableHeaders
from database import get_db_connection
from config import SESSION_COOKIE_NAME, SESSION_COOKIE_SECURE


class DatabaseSessionMiddleware:
    """Server-side MySQL sessions while keeping request.session compatibility."""

    def __init__(self, app, max_age: int = 60 * 60 * 12):
        self.app = app
        self.max_age = max_age

    def _install_table(self):
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sis_ai_python_sessions (
                    session_id VARCHAR(64) NOT NULL,
                    data_json LONGTEXT NOT NULL,
                    updated_at DATETIME NOT NULL,
                    expires_at DATETIME NOT NULL,
                    PRIMARY KEY (session_id),
                    KEY idx_ai_py_session_expires (expires_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            conn.commit()
        finally:
            cur.close(); conn.close()

    def _load(self, session_id: str) -> dict:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT data_json FROM sis_ai_python_sessions WHERE session_id=%s AND expires_at > NOW() LIMIT 1",
                (session_id,),
            )
            row = cur.fetchone()
            if not row:
                return {}
            try:
                data = json.loads(row['data_json'])
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        finally:
            cur.close(); conn.close()

    def _save(self, session_id: str, data: dict):
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
            expires_at = datetime.now() + timedelta(seconds=self.max_age)
            cur.execute("""
                INSERT INTO sis_ai_python_sessions (session_id, data_json, updated_at, expires_at)
                VALUES (%s, %s, NOW(), %s)
                ON DUPLICATE KEY UPDATE data_json=VALUES(data_json), updated_at=NOW(), expires_at=VALUES(expires_at)
            """, (session_id, payload, expires_at))
            conn.commit()
        finally:
            cur.close(); conn.close()

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            await self.app(scope, receive, send)
            return

        if (
            scope['type'] == 'http'
            and scope.get('path') in (
                '/',
                '/health',
                '/create-ticket',
                '/tickets',
                '/docs',
                '/openapi.json',
                '/docs/oauth2-redirect',
                '/closing-message',
                '/favicon.ico',
            )
        ):
            await self.app(scope, receive, send)
            return

        if not getattr(self, '_installed', False):
            self._install_table()
            self._installed = True

        headers = dict(scope.get('headers') or [])

        cookie = SimpleCookie()
        cookie.load(
            headers.get(b'cookie', b'').decode('latin-1')
        )

        morsel = cookie.get(SESSION_COOKIE_NAME)

        session_id = (
            morsel.value
            if morsel
            else secrets.token_hex(24)
        )

        scope['session'] = self._load(session_id)

        async def send_wrapper(message):
            if message['type'] == 'http.response.start':

                self._save(
                    session_id,
                    scope['session']
                )

                mutable = MutableHeaders(
                    scope=message
                )

                cookie_bits = [
                    f'{SESSION_COOKIE_NAME}={session_id}',
                    'Path=/',
                    f'Max-Age={self.max_age}',
                    'HttpOnly',
                    'SameSite=Lax',
                ]

                if SESSION_COOKIE_SECURE:
                    cookie_bits.append('Secure')

                mutable.append(
                    'Set-Cookie',
                    '; '.join(cookie_bits)
                )

            await send(message)

        await self.app(
            scope,
            receive,
            send_wrapper
        )