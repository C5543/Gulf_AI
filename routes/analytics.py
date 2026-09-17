from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from database import get_db_connection


router = APIRouter()


# =========================================================
# أسماء الجداول
# =========================================================

CONVERSATIONS_TABLE = "sis_ai_test_conversations"
MESSAGES_TABLE = "sis_ai_test_messages"
API_CALLS_TABLE = "sis_ai_test_api_calls"
TICKETS_TABLE = "sis_ai_support_tickets"


# =========================================================
# Helpers
# =========================================================

def table_exists(cursor, table_name):

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name = %s
        """,
        (table_name,)
    )

    row = cursor.fetchone()

    return bool(
        row
        and int(row["total"] or 0) > 0
    )


def get_columns(cursor, table_name):

    if not table_exists(
        cursor,
        table_name
    ):
        return set()

    cursor.execute(
        f"SHOW COLUMNS FROM `{table_name}`"
    )

    rows = cursor.fetchall()

    return {
        row["Field"]
        for row in rows
    }


def count_table(cursor, table_name):

    if not table_exists(
        cursor,
        table_name
    ):
        return 0

    cursor.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM `{table_name}`
        """
    )

    row = cursor.fetchone()

    return int(
        row["total"] or 0
    )


# =========================================================
# عدد التذاكر حسب الحالة
# =========================================================

def ticket_statistics(cursor):

    result = {
        "total": 0,
        "open": 0,
        "closed": 0
    }

    if not table_exists(
        cursor,
        TICKETS_TABLE
    ):
        return result

    columns = get_columns(
        cursor,
        TICKETS_TABLE
    )

    result["total"] = count_table(
        cursor,
        TICKETS_TABLE
    )

    if "status" not in columns:
        return result


    # -----------------------------------------
    # التذاكر المفتوحة
    # -----------------------------------------

    cursor.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM `{TICKETS_TABLE}`
        WHERE LOWER(TRIM(status)) IN (
            'open',
            'pending',
            'in_progress',
            'in progress',
            'new'
        )
        """
    )

    row = cursor.fetchone()

    result["open"] = int(
        row["total"] or 0
    )


    # -----------------------------------------
    # التذاكر المغلقة
    # -----------------------------------------

    cursor.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM `{TICKETS_TABLE}`
        WHERE LOWER(TRIM(status)) IN (
            'closed',
            'resolved',
            'completed',
            'done'
        )
        """
    )

    row = cursor.fetchone()

    result["closed"] = int(
        row["total"] or 0
    )


    return result


# =========================================================
# عدد مرات فشل الرد
# =========================================================

def failed_replies_count(cursor):

    if not table_exists(
        cursor,
        MESSAGES_TABLE
    ):
        return 0

    columns = get_columns(
        cursor,
        MESSAGES_TABLE
    )

    conditions = []


    # -----------------------------------------
    # إذا عندنا handler
    # مثل:
    # openai_error
    # database_error
    # -----------------------------------------

    if "handler" in columns:

        conditions.append(
            """
            LOWER(handler) LIKE '%error%'
            """
        )


    # -----------------------------------------
    # إذا عندنا direction
    # -----------------------------------------

    if "direction" in columns:

        conditions.append(
            """
            LOWER(direction) = 'error'
            """
        )


    # -----------------------------------------
    # إذا عندنا role
    # -----------------------------------------

    if "role" in columns:

        conditions.append(
            """
            LOWER(role) = 'error'
            """
        )


    # -----------------------------------------
    # بعض الردود التي تظهر للمستخدم
    # عند فشل المعالجة
    # -----------------------------------------

    text_column = None

    for candidate in [
        "message",
        "content",
        "text"
    ]:

        if candidate in columns:
            text_column = candidate
            break


    if text_column:

        conditions.append(
            f"""
            (
                `{text_column}` LIKE '%تعذر الاتصال بالخدمة%'
                OR
                `{text_column}` LIKE '%صار عندي خطأ%'
                OR
                `{text_column}` LIKE '%تعذر معالجة%'
                OR
                `{text_column}` LIKE '%حدث خطأ تقني%'
            )
            """
        )


    if not conditions:
        return 0


    where_clause = " OR ".join(
        conditions
    )


    cursor.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM `{MESSAGES_TABLE}`
        WHERE {where_clause}
        """
    )

    row = cursor.fetchone()

    return int(
        row["total"] or 0
    )


# =========================================================
# عدد Errors
# =========================================================

def error_count(cursor):

    total_errors = 0


    # =========================================
    # API Errors
    # =========================================

    if table_exists(
        cursor,
        API_CALLS_TABLE
    ):

        columns = get_columns(
            cursor,
            API_CALLS_TABLE
        )


        # HTTP status مثل 400 / 401 / 500

        if "status_code" in columns:

            cursor.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM `{API_CALLS_TABLE}`
                WHERE status_code >= 400
                """
            )

            row = cursor.fetchone()

            total_errors += int(
                row["total"] or 0
            )


        # إذا فيه error_message

        elif "error_message" in columns:

            cursor.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM `{API_CALLS_TABLE}`
                WHERE error_message IS NOT NULL
                  AND TRIM(error_message) != ''
                """
            )

            row = cursor.fetchone()

            total_errors += int(
                row["total"] or 0
            )


    # =========================================
    # Errors المسجلة داخل messages
    # =========================================

    if table_exists(
        cursor,
        MESSAGES_TABLE
    ):

        columns = get_columns(
            cursor,
            MESSAGES_TABLE
        )


        if "direction" in columns:

            cursor.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM `{MESSAGES_TABLE}`
                WHERE LOWER(direction) = 'error'
                """
            )

            row = cursor.fetchone()

            total_errors += int(
                row["total"] or 0
            )


    return total_errors


# =========================================================
# تحميل كل الإحصائيات
# =========================================================

def load_statistics():

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )

    try:

        conversations = count_table(
            cursor,
            CONVERSATIONS_TABLE
        )


        ticket_stats = ticket_statistics(
            cursor
        )


        failed_replies = failed_replies_count(
            cursor
        )


        errors = error_count(
            cursor
        )


        return {

            "conversations":
                conversations,

            "problems":
                ticket_stats["total"],

            "open_tickets":
                ticket_stats["open"],

            "closed_tickets":
                ticket_stats["closed"],

            "failed_replies":
                failed_replies,

            "errors":
                errors,

            "tickets_table_exists":
                table_exists(
                    cursor,
                    TICKETS_TABLE
                )
        }

    finally:

        cursor.close()
        connection.close()


# =========================================================
# Dashboard
# =========================================================

@router.get(
    "/analytics",
    response_class=HTMLResponse
)
def analytics_dashboard():

    try:

        stats = load_statistics()

    except Exception as error:

        return HTMLResponse(
            content=f"""
            <!doctype html>

            <html lang="ar" dir="rtl">

            <head>

                <meta charset="utf-8">

                <title>
                    خطأ في لوحة الإحصائيات
                </title>

            </head>

            <body
                style="
                    font-family:Tahoma,Arial;
                    padding:40px;
                "
            >

                <h2>
                    تعذر تحميل الإحصائيات
                </h2>

                <p>
                    {str(error)}
                </p>

            </body>

            </html>
            """,
            status_code=500
        )


    ticket_note = ""


    if not stats["tickets_table_exists"]:

        ticket_note = """
        <div class="warning">
            جدول التذاكر
            sis_ai_support_tickets
            غير موجود حاليًا في قاعدة البيانات،
            لذلك إحصائيات المشاكل والتذاكر تظهر 0.
        </div>
        """


    page = f"""
    <!doctype html>

    <html lang="ar" dir="rtl">

    <head>

        <meta charset="utf-8">

        <meta
            name="viewport"
            content="width=device-width, initial-scale=1"
        >

        <title>
            لوحة إحصائيات مساعد كلية الخليج
        </title>


        <style>

            * {{
                box-sizing: border-box;
            }}


            body {{

                margin: 0;

                font-family:
                    Tahoma,
                    Arial,
                    sans-serif;

                background:
                    #f4f6f8;

                color:
                    #333;

            }}


            .container {{

                max-width:
                    1200px;

                margin:
                    auto;

                padding:
                    35px 20px;

            }}


            h1 {{

                color:
                    #075e54;

                margin-bottom:
                    30px;

            }}


            .cards {{

                display:
                    grid;

                grid-template-columns:
                    repeat(
                        auto-fit,
                        minmax(220px, 1fr)
                    );

                gap:
                    18px;

            }}


            .card {{

                background:
                    white;

                padding:
                    25px;

                border-radius:
                    14px;

                box-shadow:
                    0 2px 10px
                    rgba(0,0,0,.08);

            }}


            .title {{

                font-size:
                    14px;

                color:
                    #777;

                margin-bottom:
                    12px;

            }}


            .number {{

                font-size:
                    34px;

                font-weight:
                    bold;

                color:
                    #075e54;

            }}


            .warning {{

                margin-top:
                    25px;

                background:
                    #fff3cd;

                padding:
                    15px;

                border-radius:
                    10px;

                line-height:
                    1.8;

            }}


            .footer {{

                margin-top:
                    30px;

                color:
                    #777;

                font-size:
                    13px;

            }}

        </style>

    </head>


    <body>


        <div class="container">


            <h1>
                لوحة إحصائيات مساعد كلية الخليج
            </h1>


            <div class="cards">


                <div class="card">

                    <div class="title">
                        عدد المحادثات
                    </div>

                    <div class="number">
                        {stats["conversations"]}
                    </div>

                </div>


                <div class="card">

                    <div class="title">
                        عدد المشاكل
                    </div>

                    <div class="number">
                        {stats["problems"]}
                    </div>

                </div>


                <div class="card">

                    <div class="title">
                        التذاكر المفتوحة
                    </div>

                    <div class="number">
                        {stats["open_tickets"]}
                    </div>

                </div>


                <div class="card">

                    <div class="title">
                        التذاكر المغلقة
                    </div>

                    <div class="number">
                        {stats["closed_tickets"]}
                    </div>

                </div>


                <div class="card">

                    <div class="title">
                        مرات فشل الرد
                    </div>

                    <div class="number">
                        {stats["failed_replies"]}
                    </div>

                </div>


                <div class="card">

                    <div class="title">
                        عدد Errors
                    </div>

                    <div class="number">
                        {stats["errors"]}
                    </div>

                </div>


            </div>


            {ticket_note}


            <div class="footer">

                الإحصائيات تُقرأ مباشرة
                من قاعدة بيانات مساعد كلية الخليج.

            </div>


        </div>


    </body>

    </html>
    """


    return HTMLResponse(
        content=page
    )