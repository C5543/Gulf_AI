import json
from pathlib import Path
from database import get_db_connection
from services.text_utils import clean, limit, normalize, words

_DATA = Path(__file__).resolve().parent.parent / 'data' / 'official_knowledge.json'
with _DATA.open('r', encoding='utf-8') as f:
    OFFICIAL_KNOWLEDGE = json.load(f)


def get_relevant_knowledge(message: str, limit_count: int = 8) -> list[dict]:
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT id, category, title, content, keywords, priority
            FROM ai_knowledge
            WHERE status = 1
            ORDER BY priority DESC, id DESC
        """)
        rows = cur.fetchall()
    finally:
        cur.close(); conn.close()

    message_n = normalize(message)
    message_words = words(message)
    matches = []
    for row in rows:
        score = int(row.get('priority') or 0) / 100
        title_n = normalize(row.get('title'))
        category_n = normalize(row.get('category'))
        keywords_n = normalize(row.get('keywords'))
        content_n = normalize(row.get('content'))
        if title_n and title_n in message_n:
            score += 20
        if category_n and category_n in message_n:
            score += 8
        for word in message_words:
            if keywords_n and word in keywords_n:
                score += 6
            if title_n and word in title_n:
                score += 5
            if content_n and word in content_n:
                score += 2
        if score > 1:
            matches.append({
                'score': score,
                'category': clean(row.get('category')),
                'title': clean(row.get('title')),
                'content': limit(row.get('content'), 1200),
            })
    matches.sort(key=lambda x: x['score'], reverse=True)
    return matches[:limit_count]


def get_official_knowledge(message: str, limit_count: int = 6) -> list[dict]:
    message_n = normalize(message)
    message_words = words(message)
    matches = []
    for entry in OFFICIAL_KNOWLEDGE:
        title_n = normalize(entry.get('title'))
        category_n = normalize(entry.get('category'))
        keywords_n = normalize(entry.get('keywords'))
        content_n = normalize(entry.get('content'))
        score = int(entry.get('priority') or 0) / 100
        if title_n and title_n in message_n:
            score += 40
        if category_n and category_n in message_n:
            score += 10
        for word in message_words:
            if keywords_n and word in keywords_n:
                score += 8
            if title_n and word in title_n:
                score += 6
            if content_n and word in content_n:
                score += 2
        if score > 2:
            matches.append({
                'score': score,
                'category': entry.get('category', ''),
                'title': entry.get('title', ''),
                'content': entry.get('content', ''),
            })
    matches.sort(key=lambda x: x['score'], reverse=True)
    return matches[:limit_count]
