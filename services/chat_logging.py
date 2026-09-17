import hashlib
import json
import secrets
import time
from typing import Any

from config import AI_LOG_ENABLED, AI_LOG_FULL_PAYLOAD
from database import get_db_connection


def log_enabled() -> bool:
    return bool(AI_LOG_ENABLED)


def log_full_payload_enabled() -> bool:
    return bool(AI_LOG_FULL_PAYLOAD)


def install_tables(connection=None):
    if not log_enabled():
        return
    own = connection is None
    conn = connection or get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sis_ai_test_conversations (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                conversation_key VARCHAR(64) NOT NULL,
                php_session_hash CHAR(64) DEFAULT NULL,
                visitor_name VARCHAR(190) DEFAULT NULL,
                student_id VARCHAR(30) DEFAULT NULL,
                identity_masked VARCHAR(30) DEFAULT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'open',
                message_count INT UNSIGNED NOT NULL DEFAULT 0,
                last_ip VARCHAR(45) DEFAULT NULL,
                last_user_agent VARCHAR(500) DEFAULT NULL,
                started_at DATETIME NOT NULL,
                last_message_at DATETIME NOT NULL,
                closed_at DATETIME DEFAULT NULL,
                PRIMARY KEY (id),
                UNIQUE KEY uq_ai_test_conversation_key (conversation_key),
                KEY idx_ai_test_conversation_student (student_id),
                KEY idx_ai_test_conversation_last (last_message_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sis_ai_test_messages (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                conversation_id BIGINT UNSIGNED NOT NULL,
                request_key VARCHAR(64) DEFAULT NULL,
                direction VARCHAR(20) NOT NULL,
                handler VARCHAR(60) DEFAULT NULL,
                message_text MEDIUMTEXT,
                context_json MEDIUMTEXT,
                latency_ms INT UNSIGNED DEFAULT NULL,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                KEY idx_ai_test_message_conversation (conversation_id, id),
                KEY idx_ai_test_message_request (request_key),
                KEY idx_ai_test_message_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sis_ai_test_api_calls (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                conversation_id BIGINT UNSIGNED NOT NULL,
                request_key VARCHAR(64) DEFAULT NULL,
                purpose VARCHAR(60) DEFAULT NULL,
                provider VARCHAR(30) NOT NULL DEFAULT 'openai',
                model VARCHAR(100) DEFAULT NULL,
                request_json LONGTEXT,
                response_json LONGTEXT,
                http_code INT DEFAULT NULL,
                curl_error TEXT,
                input_tokens INT UNSIGNED DEFAULT NULL,
                output_tokens INT UNSIGNED DEFAULT NULL,
                total_tokens INT UNSIGNED DEFAULT NULL,
                duration_ms INT UNSIGNED DEFAULT NULL,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                KEY idx_ai_test_api_conversation (conversation_id, id),
                KEY idx_ai_test_api_request (request_key),
                KEY idx_ai_test_api_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        conn.commit()
    finally:
        cur.close()
        if own:
            conn.close()


def make_key(prefix: str) -> str:
    raw = f'{secrets.token_hex(24)}:{time.time_ns()}'.encode()
    return f'{prefix}_{hashlib.sha256(raw).hexdigest()[:40]}'


def conversation_key(request) -> str:
    key = request.session.get('gulf_ai_log_conversation_key')
    if not key:
        key = make_key('conv')
        request.session['gulf_ai_log_conversation_key'] = key
    return key


def request_key(request) -> str:
    key = getattr(request.state, 'gulf_ai_log_request_key', None)
    if not key:
        key = make_key('req')
        request.state.gulf_ai_log_request_key = key
    return key


def mask_identity(identity: Any) -> str:
    digits = ''.join(ch for ch in str(identity or '') if ch.isdigit())
    if len(digits) < 4:
        return ''
    return '*' * max(0, len(digits) - 4) + digits[-4:]


def latency_ms(request):
    started = getattr(request.state, 'gulf_ai_log_started_at', None)
    if not started:
        return None
    return max(0, int(round((time.perf_counter() - started) * 1000)))


def conversation_id(request, connection=None) -> int:
    if not log_enabled():
        return 0
    own = connection is None
    conn = connection or get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        install_tables(conn)
        key = conversation_key(request)
        visitor_name = str(request.session.get('gulf_ai_visitor_name', '')).strip()
        student_id = ''.join(ch for ch in str(
            request.session.get('gulf_ai_verified_student_id') or request.session.get('gulf_ai_student_id') or ''
        ) if ch.isdigit())
        identity_masked = mask_identity(request.session.get('gulf_ai_verified_identity', ''))
        ip = request.client.host if getattr(request, 'client', None) else ''
        user_agent = str(request.headers.get('user-agent', ''))[:500]
        # No PHP session exists in Python; hash the Python server-side session id surrogate.
        session_hash = hashlib.sha256(key.encode()).hexdigest()
        cur.execute("""
            INSERT INTO sis_ai_test_conversations
                (conversation_key, php_session_hash, visitor_name, student_id, identity_masked,
                 status, message_count, last_ip, last_user_agent, started_at, last_message_at)
            VALUES (%s,%s,%s,%s,%s,'open',0,%s,%s,NOW(),NOW())
            ON DUPLICATE KEY UPDATE
                visitor_name=IF(VALUES(visitor_name)<>'',VALUES(visitor_name),visitor_name),
                student_id=IF(VALUES(student_id)<>'',VALUES(student_id),student_id),
                identity_masked=IF(VALUES(identity_masked)<>'',VALUES(identity_masked),identity_masked),
                last_ip=VALUES(last_ip), last_user_agent=VALUES(last_user_agent), last_message_at=NOW()
        """, (key, session_hash, visitor_name, student_id, identity_masked, ip, user_agent))
        cur.execute('SELECT id FROM sis_ai_test_conversations WHERE conversation_key=%s LIMIT 1', (key,))
        row = cur.fetchone()
        conn.commit()
        return int(row['id']) if row else 0
    finally:
        cur.close()
        if own:
            conn.close()


def log_message(request, direction: str, text: Any, handler: str = '', context=None, latency=None):
    if not log_enabled():
        return
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cid = conversation_id(request, conn)
        if cid <= 0:
            return
        context_text = '' if not context else json.dumps(context, ensure_ascii=False, separators=(',', ':'), default=str)
        cur.execute("""
            INSERT INTO sis_ai_test_messages
                (conversation_id, request_key, direction, handler, message_text, context_json, latency_ms, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
        """, (cid, request_key(request), str(direction)[:20], str(handler)[:60], str(text), context_text, latency))
        cur.execute("UPDATE sis_ai_test_conversations SET message_count=message_count+1,last_message_at=NOW() WHERE id=%s LIMIT 1", (cid,))
        conn.commit()
    finally:
        cur.close(); conn.close()


def log_api_call(request, purpose: str, model: str, request_payload: dict, response_payload: Any,
                 http_code: int, error_text: str, started_at: float):
    if not log_enabled():
        return
    if isinstance(response_payload, (dict, list)):
        response_obj = response_payload
        raw_response = json.dumps(response_payload, ensure_ascii=False, separators=(',', ':'), default=str)
    else:
        raw_response = str(response_payload or '')
        try:
            response_obj = json.loads(raw_response)
        except Exception:
            response_obj = {}
    usage = response_obj.get('usage', {}) if isinstance(response_obj, dict) else {}
    input_tokens = int(usage.get('input_tokens') or 0)
    output_tokens = int(usage.get('output_tokens') or 0)
    total_tokens = int(usage.get('total_tokens') or (input_tokens + output_tokens))
    duration = max(0, int(round((time.perf_counter() - started_at) * 1000)))
    request_text = json.dumps(request_payload, ensure_ascii=False, separators=(',', ':'), default=str) if log_full_payload_enabled() else ''
    response_text = raw_response if log_full_payload_enabled() else ''

    conn = get_db_connection(); cur = conn.cursor()
    try:
        cid = conversation_id(request, conn)
        if cid <= 0:
            return
        cur.execute("""
            INSERT INTO sis_ai_test_api_calls
                (conversation_id,request_key,purpose,provider,model,request_json,response_json,http_code,curl_error,
                 input_tokens,output_tokens,total_tokens,duration_ms,created_at)
            VALUES (%s,%s,%s,'openai',%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        """, (cid, request_key(request), str(purpose)[:60], str(model)[:100], request_text, response_text,
              int(http_code or 0), str(error_text or ''), input_tokens, output_tokens, total_tokens, duration))
        conn.commit()
    finally:
        cur.close(); conn.close()


def close_current_conversation(request):
    if not log_enabled():
        return
    key = request.session.get('gulf_ai_log_conversation_key')
    if not key:
        return
    conn = get_db_connection(); cur = conn.cursor()
    try:
        install_tables(conn)
        cur.execute("""
            UPDATE sis_ai_test_conversations
            SET status='closed', closed_at=NOW(), last_message_at=NOW()
            WHERE conversation_key=%s LIMIT 1
        """, (key,))
        conn.commit()
    finally:
        cur.close(); conn.close()
