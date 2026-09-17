import hmac
import html
import re
import secrets
import time

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from services.nafath_bridge import get_callback_baseline
from config import AI_PUBLIC_BASE_URL
from database import get_db_connection
from services.action_logger import ai_action_log


router = APIRouter()


NAFATH_REQUEST_URL = "https://sisd.gulf.edu.sa/nafathapi/request.php"


# =========================================================
# تسجيل العمليات
# =========================================================

def log_action(
    request: Request,
    message: str,
    handler: str,
    context=None,
    direction="system"
):

    connection = None

    try:

        connection = get_db_connection()

        ai_action_log(
            connection=connection,

            message=message,

            handler=handler,

            conversation_key=request.session.get(
                "gulf_ai_log_conversation_key"
            ),

            context=context or {},

            direction=direction,

            verified_student_id=request.session.get(
                "gulf_ai_verified_student_id"
            ),

            student_id=request.session.get(
                "gulf_ai_student_id"
            )
        )

    except Exception as error:

        print(
            "Withdrawal start log error:",
            error
        )

    finally:

        if connection:
            connection.close()


# =========================================================
# إيقاف العملية وعرض الخطأ
# =========================================================

def stop_page(
    request: Request,
    message: str
):

    log_action(
        request=request,

        message=message,

        handler="withdrawal_start",

        context={},

        direction="error"
    )


    safe_message = html.escape(
        str(message)
    )


    page = f"""
    <!doctype html>

    <html lang="ar" dir="rtl">

    <head>

        <meta charset="utf-8">

        <meta
            name="viewport"
            content="width=device-width,initial-scale=1"
        >

        <title>
            تعذر متابعة الطلب
        </title>

    </head>


    <body
        style="
            font-family:Tahoma,Arial;
            background:#f5f2ed;
            padding:24px;
        "
    >

        <div
            style="
                max-width:620px;
                margin:auto;
                background:#fff;
                padding:24px;
                border-radius:14px;
            "
        >

            <h3>
                تعذر متابعة الطلب
            </h3>

            <p>
                {safe_message}
            </p>

            <a href="/">
                العودة للمساعد
            </a>

        </div>

    </body>

    </html>
    """


    return HTMLResponse(
        content=page
    )


# =========================================================
# بداية طلب الانسحاب
# =========================================================

@router.get(
    "/withdrawal/start"
)
async def withdrawal_start(
    request: Request
):

    # =====================================================
    # جلب بيانات الانسحاب من Session
    # =====================================================

    student_id = re.sub(
        r"\D",
        "",
        str(
            request.session.get(
                "gulf_ai_withdrawal_student_id",
                ""
            )
        )
    )


    reason = str(
        request.session.get(
            "gulf_ai_withdrawal_reason",
            ""
        )
    ).strip()


    stage = str(
        request.session.get(
            "gulf_ai_withdrawal_stage",
            ""
        )
    )


    # =====================================================
    # التأكد من أن الشات جهز الطلب
    # =====================================================

    if (
        not student_id
        or not reason
        or stage != "nafath_ready"
    ):

        return stop_page(
            request,

            (
                "ارجع للمحادثة وابدأ "
                "طلب الانسحاب من جديد."
            )
        )


    connection = None
    cursor = None


    try:

        connection = get_db_connection()

        cursor = connection.cursor(
            dictionary=True
        )


        # =================================================
        # البحث عن الطالب
        # =================================================

        cursor.execute(
            """
            SELECT
                id,
                student_id,
                iqama

            FROM sis_application

            WHERE student_id = %s

            LIMIT 1
            """,
            (student_id,)
        )


        application = cursor.fetchone()


        if not application:

            return stop_page(
                request,
                "تعذر العثور على ملف الطالب."
            )


        # =================================================
        # الهوية المسجلة
        # =================================================

        identity = re.sub(
            r"\D",
            "",
            str(
                application.get(
                    "iqama",
                    ""
                )
            )
        )


        # الهوية السعودية / الإقامة:
        # تبدأ بـ 1 أو 2 وتتكون من 10 أرقام
        if not re.fullmatch(
            r"[12]\d{9}",
            identity
        ):

            return stop_page(
                request,

                (
                    "رقم الهوية المسجل غير صالح "
                    "للتحقق عبر نفاذ."
                )
            )


        # =================================================
        # مطابقة الهوية التي أدخلها الطالب
        # مع الهوية الموجودة في ملفه
        # =================================================

        withdrawal_identity = re.sub(
            r"\D",
            "",
            str(
                request.session.get(
                    "gulf_ai_withdrawal_identity",
                    ""
                )
            )
        )


        if (
            not withdrawal_identity
            or not hmac.compare_digest(
                withdrawal_identity,
                identity
            )
        ):

            return stop_page(
                request,

                (
                    "رقم الهوية المدخل لا يطابق "
                    "ملف الطالب. "
                    "ارجعي للمساعد وابدئي "
                    "الطلب من جديد."
                )
            )


        # =================================================
        # منع إنشاء طلب انسحاب مكرر
        # =================================================

        cursor.execute(
            """
            SELECT
                id,
                status

            FROM sis_admission_retreat

            WHERE
                student_id = %s
                AND status IN (0, 1)

            ORDER BY id DESC

            LIMIT 1
            """,
            (student_id,)
        )


        active_request = (
            cursor.fetchone()
        )


        if active_request:

            return stop_page(
                request,

                (
                    "لديك طلب انسحاب قائم بالفعل، "
                    "ولن يتم إنشاء طلب مكرر."
                )
            )
        # =================================================
        # حفظ آخر Callback موجود قبل بدء نفاذ
        # =================================================

        nafath_callback_baseline = get_callback_baseline(
            connection,
            identity
        )


        # =================================================
        # إنشاء Token خاص بالعملية
        # =================================================

        token = secrets.token_hex(
            24
        )


        # =================================================
        # تخزين طلب الانسحاب المعلق
        # =================================================

        request.session[
            "gulf_ai_withdrawal_pending"
        ] = {

            "token":
                token,

            "student_id":
                student_id,

            "application_id":
                int(
                    application["id"]
                ),

            "identity":
                identity,

            "reason":
                reason[:500],

            "nafath_callback_baseline":
                nafath_callback_baseline,

            "created_at":
                int(
                    time.time()
                ),

            "consumed":
                0
        }
        # =================================================
        # رابط العودة بعد نجاح نفاذ
        # =================================================

        base_url = str(
            AI_PUBLIC_BASE_URL
            or "http://127.0.0.1:8000"
        ).rstrip("/")

        destination = (
            base_url
            + "/withdrawal/complete?token="
            + quote(
                token,
                safe=""
            )
        )
        # =================================================
        # تسجيل تجهيز العملية
        # =================================================

        log_action(
            request=request,

            message=(
                "تم تجهيز طلب الانسحاب "
                "وتحويل الطالب إلى "
                "التحقق عبر نفاذ."
            ),

            handler="withdrawal_start",

            context={

                "student_id":
                    student_id,

                "application_id":
                    int(
                        application["id"]
                    ),

                "reason":
                    reason,

                "destination":
                    destination
            },

            direction="system"
        )


        # =================================================
        # تجهيز القيم للـ HTML
        # =================================================

        safe_identity = html.escape(
            identity,
            quote=True
        )

        safe_destination = html.escape(
            destination,
            quote=True
        )

        safe_nafath_url = html.escape(
            NAFATH_REQUEST_URL,
            quote=True
        )


        # =================================================
        # صفحة التحويل إلى نفاذ
        # =================================================

        page = f"""
        <!doctype html>

        <html lang="ar" dir="rtl">

        <head>

            <meta charset="utf-8">

            <meta
                name="viewport"
                content="width=device-width,initial-scale=1"
            >

            <title>
                تأكيد طلب الانسحاب
            </title>

        </head>


        <body
            style="
                font-family:Tahoma,Arial;
                background:#f5f2ed;
                padding:24px;
            "
        >

            <div
                style="
                    max-width:620px;
                    margin:auto;
                    background:#fff;
                    padding:24px;
                    border-radius:14px;
                    text-align:center;
                "
            >

                <h3>
                    جاري تحويلك إلى نفاذ
                </h3>


                <p>
                    سيظهر لك رقم في الصفحة.
                    افتحي تطبيق نفاذ واختاري
                    الرقم نفسه لإكمال التحقق.
                </p>


                <form
                    id="nafathForm"
                    method="post"
                    action="{safe_nafath_url}"
                >

                    <input
                        type="hidden"
                        name="idnumber"
                        value="{safe_identity}"
                    >

                    <input
                        type="hidden"
                        name="destination_url"
                        value="{safe_destination}"
                    >


                    <button
                        type="submit"

                        style="
                            border:0;
                            background:#087f72;
                            color:#fff;
                            padding:12px 24px;
                            border-radius:9px;
                            font-family:inherit;
                            cursor:pointer;
                        "
                    >
                        الانتقال إلى نفاذ
                    </button>

                </form>

            </div>


            <script>

                document
                    .getElementById(
                        'nafathForm'
                    )
                    .submit();

            </script>


        </body>

        </html>
        """


        return HTMLResponse(
            content=page
        )


    except Exception as error:

        print(
            "Withdrawal start error:",
            error
        )


        return stop_page(
            request,

            (
                "حدث خطأ تقني أثناء تجهيز "
                "طلب الانسحاب. "
                "ارجعي للمساعد وحاولي مرة ثانية."
            )
        )


    finally:

        if cursor:

            try:
                cursor.close()

            except Exception:
                pass


        if connection:

            connection.close()