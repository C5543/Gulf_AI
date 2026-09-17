import hmac
import html
import re
import secrets
import time

import httpx

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from config import TAQNYAT_BEARER_TOKEN
from database import get_db_connection
from services.action_logger import ai_action_log


router = APIRouter()


TAQNYAT_SMS_URL = "https://api.taqnyat.sa/v1/messages"
TAQNYAT_SENDER = "GulfCollege"


# ==========================================
# تنظيف رقم الجوال
# ==========================================

def normalize_mobile(mobile):

    mobile = re.sub(
        r"\D",
        "",
        str(mobile or "")
    )

    if mobile.startswith("00966"):
        mobile = mobile[2:]

    if mobile.startswith("966"):
        return mobile

    if mobile.startswith("05"):
        return "966" + mobile[1:]

    if mobile.startswith("5"):
        return "966" + mobile

    return ""


# ==========================================
# حفظ النتيجة في سجل المحادثة
# ==========================================

def remember_result(request, message):

    history = request.session.get(
        "gulf_ai_ui_history",
        []
    )

    if not isinstance(history, list):
        history = []

    history.append({
        "type": "bot",
        "text": str(message),
        "actions": []
    })

    # الاحتفاظ بآخر 40 رسالة
    request.session[
        "gulf_ai_ui_history"
    ] = history[-40:]


# ==========================================
# تسجيل العملية
# ==========================================

def log_action(
    request,
    message,
    handler,
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
            "Action log error:",
            error
        )

    finally:

        if connection:
            connection.close()


# ==========================================
# صفحة النتيجة / التأكيد
# ==========================================

def render_page(
    request,
    title,
    message,
    ok,
    show_form=False
):

    log_action(
        request=request,

        message=f"{title}: {message}",

        handler="resend_student_message",

        context={
            "show_confirmation_form":
                1 if show_form else 0
        },

        direction=(
            "system"
            if ok
            else "error"
        )
    )


    color = (
        "#087f72"
        if ok
        else "#a83232"
    )


    csrf = html.escape(
        str(
            request.session.get(
                "gulf_ai_resend_csrf",
                ""
            )
        )
    )


    safe_title = html.escape(
        str(title)
    )

    safe_message = html.escape(
        str(message)
    )


    confirmation_form = ""


    if show_form:

        confirmation_form = f"""
        <form method="post">

            <input
                type="hidden"
                name="csrf"
                value="{csrf}"
            >

            <button
                style="
                    border:0;
                    background:#087f72;
                    color:#fff;
                    padding:11px 20px;
                    border-radius:8px;
                    font-family:inherit;
                    cursor:pointer;
                "
                type="submit"
            >
                تأكيد إعادة الإرسال
            </button>

        </form>
        """


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
            {safe_title}
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

            <h3
                style="
                    color:{color};
                "
            >
                {safe_title}
            </h3>


            <p
                style="
                    line-height:1.9;
                "
            >
                {safe_message}
            </p>


            {confirmation_form}


            <p>

                <a href="/">
                    العودة للمساعد
                </a>

            </p>

        </div>

    </body>

    </html>
    """


    return HTMLResponse(
        content=page
    )


# ==========================================
# إرسال SMS إلى Taqnyat
# ==========================================

async def send_sms(
    message,
    mobile
):

    if not TAQNYAT_BEARER_TOKEN:
        raise RuntimeError(
            "TAQNYAT_BEARER_TOKEN is not configured"
        )

    payload = {
        "recipients": [
            int(mobile)
        ],
        "body": str(message),
        "sender": TAQNYAT_SENDER
    }

    headers = {
        "Authorization": f"Bearer {TAQNYAT_BEARER_TOKEN}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(
        timeout=20.0
    ) as client:

        response = await client.post(
            TAQNYAT_SMS_URL,
            json=payload,
            headers=headers
        )

        print(
            "SMS status:",
            response.status_code
        )

        print(
            "SMS response:",
            response.text
        )

    try:
        return response.json()

    except ValueError:
        return {
            "statusCode": response.status_code,
            "message": response.text
        }

    async with httpx.AsyncClient(
        timeout=20.0
    ) as client:

        response = await client.post(
            TAQNYAT_SMS_URL,
            json=payload,
            headers=headers
        )


    try:

        return response.json()

    except ValueError:

        return {
            "statusCode":
                response.status_code,

            "message":
                response.text
        }


# ==========================================
# إعادة إرسال بيانات الطالب
# ==========================================

@router.api_route(
    "/resend-student-message",
    methods=[
        "GET",
        "POST"
    ]
)
async def resend_student_message(
    request: Request
):

    # ======================================
    # جلب الهوية المتحقق منها
    # ======================================

    identity = re.sub(
        r"\D",
        "",
        str(
            request.session.get(
                "gulf_ai_verified_identity",
                ""
            )
        )
    )


    if not identity:

        return render_page(
            request,
            "تعذر إعادة الإرسال",
            "ارجع للمحادثة وتحقق من طلبك أولًا.",
            False
        )


    connection = None
    cursor = None


    try:

        connection = get_db_connection()

        cursor = connection.cursor(
            dictionary=True
        )


        # ==================================
        # بيانات الطالب
        # ==================================

        cursor.execute(
            """
            SELECT
                student_id,
                mobile

            FROM sis_application

            WHERE iqama = %s

            ORDER BY id DESC

            LIMIT 1
            """,
            (identity,)
        )


        application = cursor.fetchone()


        if (
            not application
            or not application.get(
                "student_id"
            )
        ):

            return render_page(
                request,
                "تعذر إعادة الإرسال",
                "لا يوجد رقم جامعي صادر لهذا الطلب.",
                False
            )


        student_id = str(
            application["student_id"]
        )


        # ==================================
        # جلب رسالة بيانات الدخول
        # ==================================

        cursor.execute(
            """
            SELECT
                body_sms,
                status

            FROM sis_queue

            WHERE student_id = %s

            LIMIT 1
            """,
            (student_id,)
        )


        queue = cursor.fetchone()


        if (
            not queue
            or str(
                queue.get(
                    "status",
                    ""
                )
            ).strip().lower()
            != "completed"
            or not str(
                queue.get(
                    "body_sms",
                    ""
                )
            ).strip()
        ):

            return render_page(
                request,

                "الرسالة غير جاهزة",

                (
                    "تجهيز الحساب لم يكتمل "
                    "أو نص الرسالة غير محفوظ، "
                    "لذلك لم نرسل رسالة ناقصة."
                ),

                False
            )


        # ==================================
        # رقم الجوال
        # ==================================

        mobile = normalize_mobile(
            application.get(
                "mobile"
            )
        )


        if not mobile:

            return render_page(
                request,

                "رقم الجوال غير صالح",

                (
                    "رقم الجوال المسجل يحتاج "
                    "تحديث قبل إعادة الإرسال."
                ),

                False
            )


        # ==================================
        # GET
        # عرض صفحة التأكيد
        # ==================================

        if request.method == "GET":

            request.session[
                "gulf_ai_resend_csrf"
            ] = secrets.token_hex(20)


            return render_page(
                request,

                "إعادة إرسال بيانات الدخول",

                (
                    "سنرسل بيانات الدخول "
                    "إلى رقم الجوال المسجل "
                    f"والمنتهي بـ {mobile[-2:]}."
                ),

                True,

                True
            )


        # ==================================
        # POST
        # ==================================

        form = await request.form()


        csrf = str(
            form.get(
                "csrf",
                ""
            )
        )


        session_csrf = str(
            request.session.get(
                "gulf_ai_resend_csrf",
                ""
            )
        )


        # ==================================
        # التحقق من CSRF
        # ==================================

        if (
            not session_csrf
            or not hmac.compare_digest(
                session_csrf,
                csrf
            )
        ):

            return render_page(
                request,

                "انتهت صلاحية التأكيد",

                (
                    "ارجع للمحادثة واطلب "
                    "إعادة الإرسال مرة ثانية."
                ),

                False
            )


        # ==================================
        # منع إعادة الإرسال خلال 5 دقائق
        # ==================================

        last_resend = int(
            request.session.get(
                "gulf_ai_last_resend_at",
                0
            )
            or 0
        )


        current_time = int(
            time.time()
        )


        if (
            last_resend
            and (
                current_time
                - last_resend
            ) < 300
        ):

            return render_page(
                request,

                "تم إرسالها قبل قليل",

                (
                    "انتظر خمس دقائق قبل "
                    "طلب إعادة إرسال أخرى."
                ),

                True,

                False
            )


        # ==================================
        # التأكد من وجود مفتاح Taqnyat
        # ==================================

        if not TAQNYAT_BEARER_TOKEN:

            return render_page(
                request,

                "الخدمة تحتاج تهيئة",

                (
                    "إعادة الإرسال مضافة، "
                    "لكن مفتاح خدمة الرسائل "
                    "غير مهيأ في إعدادات الخادم."
                ),

                False
            )


        # ==================================
        # إرسال الرسالة
        # ==================================

        try:

            gateway_response = await send_sms(
                message=queue[
                    "body_sms"
                ],

                mobile=mobile
            )


        except Exception as error:

            print(
                "SMS gateway error:",
                error
            )


            return render_page(
                request,

                "تعذر إعادة الإرسال",

                (
                    "حدث خطأ تقني أثناء "
                    "الاتصال ببوابة الرسائل، "
                    "ولم تتغير بياناتك."
                ),

                False
            )


        # ==================================
        # التأكد من نجاح Taqnyat
        # ==================================

        gateway_success = (
            isinstance(
                gateway_response,
                dict
            )
            and int(
                gateway_response.get(
                    "statusCode",
                    0
                )
                or 0
            )
            == 201
        )


        # ==================================
        # تسجيل رد بوابة الرسائل
        # ==================================

        log_action(
            request=request,

            message=(
                "وصل رد بوابة الرسائل "
                "على طلب إعادة إرسال "
                "بيانات الدخول."
            ),

            handler=(
                "sms_gateway_response"
            ),

            context={
                "student_id":
                    student_id,

                "mobile_ending":
                    mobile[-4:],

                "gateway_response":
                    gateway_response
            },

            direction=(
                "system"
                if gateway_success
                else "error"
            )
        )


        # ==================================
        # فشل بوابة الرسائل
        # ==================================

        if not gateway_success:

            return render_page(
                request,

                "تعذر إعادة الإرسال",

                (
                    "بوابة الرسائل لم تقبل الطلب. "
                    "لم يتم تغيير الرقم الجامعي "
                    "أو إعادة تشغيل المقررات."
                ),

                False
            )


        # ==================================
        # نجاح إعادة الإرسال
        # ==================================

        request.session[
            "gulf_ai_last_resend_at"
        ] = current_time


        request.session.pop(
            "gulf_ai_resend_csrf",
            None
        )


        remember_result(
            request,

            (
                "تمت إعادة إرسال بيانات الدخول "
                "إلى جوالك المسجل. "
                "تقدرين تكملين معي من هنا "
                "بدون ما تبدأ المحادثة من جديد."
            )
        )


        return render_page(
            request,

            "تمت إعادة الإرسال",

            (
                "قبلت بوابة الرسائل طلب الإرسال "
                "إلى جوالك المسجل. "
                "إذا ما وصلت خلال دقائق، "
                "تأكد من أن الرقم المسجل صحيح."
            ),

            True
        )


    except Exception as error:

        print(
            "Resend student message error:",
            error
        )


        return render_page(
            request,

            "تعذر إعادة الإرسال",

            (
                "حدث خطأ تقني أثناء تنفيذ الطلب، "
                "ولم تتغير بياناتك."
            ),

            False
        )


    finally:

        if cursor:

            try:
                cursor.close()

            except Exception:
                pass


        if connection:

            connection.close()