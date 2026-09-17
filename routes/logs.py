import hmac
import json
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from config import AI_LOG_VIEW_KEY
from database import get_db_connection


router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


# ==========================================
# Response security headers
# ==========================================

def add_security_headers(response):
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"

    return response


# ==========================================
# Password comparison
# ==========================================

def logs_key_equals(known, given):
    return hmac.compare_digest(
        str(known),
        str(given),
    )


# ==========================================
# Check table exists
# ==========================================

def logs_table_exists(connection, table_name):

    cursor = connection.cursor()

    try:
        cursor.execute(
            "SHOW TABLES LIKE %s",
            (table_name,),
        )

        return cursor.fetchone() is not None

    finally:
        cursor.close()


# ==========================================
# Fetch all
# ==========================================

def logs_fetch_all(
    connection,
    query,
    params=None,
):

    cursor = connection.cursor(
        dictionary=True
    )

    try:

        cursor.execute(
            query,
            params or (),
        )

        return cursor.fetchall()

    finally:
        cursor.close()


# ==========================================
# Fetch one
# ==========================================

def logs_fetch_one(
    connection,
    query,
    params=None,
):

    cursor = connection.cursor(
        dictionary=True
    )

    try:

        cursor.execute(
            query,
            params or (),
        )

        return cursor.fetchone()

    finally:
        cursor.close()


# ==========================================
# Pretty JSON
# ==========================================

def logs_pretty_json(value):

    if value is None:
        return ""

    value = str(value)

    if not value:
        return ""

    try:

        decoded = json.loads(value)

        return json.dumps(
            decoded,
            ensure_ascii=False,
            indent=2,
        )

    except (json.JSONDecodeError, TypeError):

        return value


# ==========================================
# Message direction labels
# ==========================================

def logs_direction_label(direction):

    labels = {
        "user": "الطالب",
        "assistant": "المساعد",
        "system": "النظام",
        "error": "خطأ",
    }

    return labels.get(
        direction,
        direction,
    )


# ==========================================
# Convert database values to JSON-safe values
# ==========================================

def json_safe(value):

    if isinstance(value, dict):

        return {
            key: json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, list):

        return [
            json_safe(item)
            for item in value
        ]

    if isinstance(
        value,
        (datetime, date),
    ):
        return value.isoformat()

    return value


# ==========================================
# Login page
# ==========================================

def show_login(
    request: Request,
    error="",
):

    response = templates.TemplateResponse(
        request=request,
        name="logs_login.html",
        context={
            "error": error,
        },
    )

    return add_security_headers(
        response
    )


# ==========================================
# Login
# ==========================================

@router.post("/logs/login")
async def logs_login(
    request: Request,
    view_key: str = Form(...),
):

    if (
        not AI_LOG_VIEW_KEY
        or len(str(AI_LOG_VIEW_KEY)) < 12
    ):

        return show_login(
            request,
            "أضيفي AI_LOG_VIEW_KEY في ملف .env بكلمة مرور قوية لا تقل عن 12 خانة.",
        )

    if logs_key_equals(
        AI_LOG_VIEW_KEY,
        view_key.strip(),
    ):

        request.session[
            "gulf_ai_logs_authenticated"
        ] = True

        response = RedirectResponse(
            url="/logs",
            status_code=303,
        )

        return add_security_headers(
            response
        )

    return show_login(
        request,
        "كلمة المرور غير صحيحة.",
    )


# ==========================================
# Logout
# ==========================================

@router.post("/logs/logout")
async def logs_logout(
    request: Request,
):

    request.session.pop(
        "gulf_ai_logs_authenticated",
        None,
    )

    response = RedirectResponse(
        url="/logs",
        status_code=303,
    )

    return add_security_headers(
        response
    )


# ==========================================
# Logs main page
# ==========================================

@router.get("/logs")
async def logs_page(
    request: Request,
    conversation: int = 0,
    q: str = "",
):

    # --------------------------------------
    # Validate log password configuration
    # --------------------------------------

    if (
        not AI_LOG_VIEW_KEY
        or len(str(AI_LOG_VIEW_KEY)) < 12
    ):

        return show_login(
            request,
            "أضيفي AI_LOG_VIEW_KEY في ملف .env بكلمة مرور قوية لا تقل عن 12 خانة.",
        )

    # --------------------------------------
    # Check authentication
    # --------------------------------------

    if not request.session.get(
        "gulf_ai_logs_authenticated"
    ):

        return show_login(request)

    search = q.strip()

    stats = {
        "conversations": 0,
        "messages": 0,
        "errors": 0,
        "tokens": 0,
    }

    conversations = []

    selected_conversation = None

    messages = []

    api_calls = []

    connection = None

    tables_ready = False

    try:

        connection = get_db_connection()

        # --------------------------------------
        # Check required tables
        # --------------------------------------

        tables_ready = (
            logs_table_exists(
                connection,
                "sis_ai_test_conversations",
            )
            and logs_table_exists(
                connection,
                "sis_ai_test_messages",
            )
            and logs_table_exists(
                connection,
                "sis_ai_test_api_calls",
            )
        )

        if tables_ready:

            # ==================================
            # Statistics
            # ==================================

            row = logs_fetch_one(
                connection,
                """
                SELECT COUNT(*) AS total
                FROM sis_ai_test_conversations
                """,
            )

            stats["conversations"] = (
                int(row["total"])
                if row
                else 0
            )


            row = logs_fetch_one(
                connection,
                """
                SELECT COUNT(*) AS total
                FROM sis_ai_test_messages
                """,
            )

            stats["messages"] = (
                int(row["total"])
                if row
                else 0
            )


            row = logs_fetch_one(
                connection,
                """
                SELECT COUNT(*) AS total
                FROM sis_ai_test_messages
                WHERE direction = 'error'
                """,
            )

            stats["errors"] = (
                int(row["total"])
                if row
                else 0
            )


            row = logs_fetch_one(
                connection,
                """
                SELECT
                    COALESCE(
                        SUM(total_tokens),
                        0
                    ) AS total
                FROM sis_ai_test_api_calls
                """,
            )

            stats["tokens"] = (
                int(row["total"])
                if row
                else 0
            )


            # ==================================
            # Conversations
            # ==================================

            query = """
                SELECT
                    c.*,

                    (
                        SELECT
                            m.message_text

                        FROM
                            sis_ai_test_messages m

                        WHERE
                            m.conversation_id = c.id

                        ORDER BY
                            m.id DESC

                        LIMIT 1
                    ) AS last_message

                FROM
                    sis_ai_test_conversations c
            """

            params = []


            if search:

                search_value = (
                    f"%{search}%"
                )

                query += """
                    WHERE
                    (
                        c.visitor_name LIKE %s

                        OR c.student_id LIKE %s

                        OR c.conversation_key LIKE %s

                        OR EXISTS
                        (
                            SELECT 1

                            FROM sis_ai_test_messages sm

                            WHERE
                                sm.conversation_id = c.id

                                AND sm.message_text LIKE %s
                        )
                    )
                """

                params.extend(
                    [
                        search_value,
                        search_value,
                        search_value,
                        search_value,
                    ]
                )


            query += """
                ORDER BY
                    c.last_message_at DESC,
                    c.id DESC

                LIMIT 200
            """


            conversations = logs_fetch_all(
                connection,
                query,
                tuple(params),
            )


            # ==================================
            # Selected conversation
            # ==================================

            if conversation > 0:

                selected_conversation = (
                    logs_fetch_one(
                        connection,
                        """
                        SELECT *
                        FROM sis_ai_test_conversations
                        WHERE id = %s
                        LIMIT 1
                        """,
                        (conversation,),
                    )
                )


                if selected_conversation:

                    messages = logs_fetch_all(
                        connection,
                        """
                        SELECT *
                        FROM sis_ai_test_messages
                        WHERE conversation_id = %s
                        ORDER BY id ASC
                        """,
                        (conversation,),
                    )


                    api_calls = logs_fetch_all(
                        connection,
                        """
                        SELECT *
                        FROM sis_ai_test_api_calls
                        WHERE conversation_id = %s
                        ORDER BY id ASC
                        """,
                        (conversation,),
                    )


                    # Format JSON fields
                    for item in messages:

                        item[
                            "pretty_context"
                        ] = logs_pretty_json(
                            item.get(
                                "context_json"
                            )
                        )


                    for call in api_calls:

                        call[
                            "pretty_request"
                        ] = logs_pretty_json(
                            call.get(
                                "request_json"
                            )
                        )

                        call[
                            "pretty_response"
                        ] = logs_pretty_json(
                            call.get(
                                "response_json"
                            )
                        )

    finally:

        if connection:
            connection.close()


    response = templates.TemplateResponse(
        request=request,
        name="logs.html",
        context={
            "tables_ready":
                tables_ready,

            "stats":
                stats,

            "conversations":
                conversations,

            "selected_conversation":
                selected_conversation,

            "messages":
                messages,

            "api_calls":
                api_calls,

            "conversation_id":
                conversation,

            "search":
                search,

            "direction_label":
                logs_direction_label,
        },
    )

    return add_security_headers(
        response
    )


# ==========================================
# JSON Export
# ==========================================

@router.get(
    "/logs/export/{conversation_id}"
)
async def export_conversation(
    request: Request,
    conversation_id: int,
):

    if not request.session.get(
        "gulf_ai_logs_authenticated"
    ):

        return RedirectResponse(
            url="/logs",
            status_code=303,
        )

    connection = None

    try:

        connection = get_db_connection()

        conversation = logs_fetch_one(
            connection,
            """
            SELECT *
            FROM sis_ai_test_conversations
            WHERE id = %s
            LIMIT 1
            """,
            (conversation_id,),
        )

        if not conversation:

            return Response(
                content="Conversation not found",
                status_code=404,
            )


        messages = logs_fetch_all(
            connection,
            """
            SELECT *
            FROM sis_ai_test_messages
            WHERE conversation_id = %s
            ORDER BY id ASC
            """,
            (conversation_id,),
        )


        api_calls = logs_fetch_all(
            connection,
            """
            SELECT *
            FROM sis_ai_test_api_calls
            WHERE conversation_id = %s
            ORDER BY id ASC
            """,
            (conversation_id,),
        )


        data = {
            "conversation":
                conversation,

            "messages":
                messages,

            "api_calls":
                api_calls,
        }


        content = json.dumps(
            json_safe(data),
            ensure_ascii=False,
            indent=2,
        )


        response = Response(
            content=content,
            media_type=(
                "application/json; charset=utf-8"
            ),
            headers={
                "Content-Disposition":
                    (
                        "attachment; "
                        f'filename="ai-conversation-{conversation_id}.json"'
                    )
            },
        )

        return add_security_headers(
            response
        )

    finally:

        if connection:
            connection.close()