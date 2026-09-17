import hashlib
import json
import re
import secrets
import time
from config import AI_LOG_ENABLED


def ai_action_log(connection, message, handler, conversation_key, context=None, direction='system', verified_student_id=None, student_id=None):
    if not AI_LOG_ENABLED or not conversation_key:
        return False
    context = context or {}
    cur = connection.cursor(dictionary=True)
    try:
        cur.execute("SHOW TABLES LIKE 'sis_ai_test_conversations'")
        if not cur.fetchone():
            return False
        cur.execute('SELECT id FROM sis_ai_test_conversations WHERE conversation_key=%s LIMIT 1', (conversation_key,))
        conversation = cur.fetchone()
        if not conversation:
            return False
        conversation_id = int(conversation['id'])
        raw = f'{secrets.token_hex(16)}{time.time_ns()}{conversation_key}'.encode()
        request_key = 'action_' + hashlib.sha256(raw).hexdigest()[:40]
        context_text = json.dumps(context, ensure_ascii=False, separators=(',', ':'), default=str) if context else ''
        cur.execute("""
            INSERT INTO sis_ai_test_messages
                (conversation_id,request_key,direction,handler,message_text,context_json,latency_ms,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,NULL,NOW())
        """, (conversation_id, request_key, str(direction)[:20], str(handler)[:60], str(message), context_text))
        final_student_id = re.sub(r'\D','',str(verified_student_id or student_id or ''))
        cur.execute("""
            UPDATE sis_ai_test_conversations
            SET message_count=message_count+1,
                student_id=IF(%s<>'',%s,student_id),
                last_message_at=NOW()
            WHERE id=%s LIMIT 1
        """, (final_student_id, final_student_id, conversation_id))
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        return False
    finally:
        cur.close()
