import asyncio
import hmac
import html
import re
import time

import httpx

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from services.nafath_bridge import find_completed_callback
from database import get_db_connection
from services.action_logger import ai_action_log


router = APIRouter()

NAFATH_STATUS_URL = (
    "https://sa-api-sis.gulf.edu.sa/nafath_check_status"
)


# =========================================================
# حفظ رسالة داخل history الشات
# =========================================================

def remember_message(request: Request, message: str):

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

    request.session[
        "gulf_ai_ui_history"
    ] = history[-40:]


# =========================================================
# تسجيل العمليات في السجلات
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
            "Withdrawal log error:",
            error
        )

    finally:

        if connection:
            connection.close()


# =========================================================
# صفحة النتيجة
# =========================================================

def render_page(
    request: Request,
    title: str,
    message: str,
    ok: bool
):

    log_action(
        request=request,

        message=f"{title}: {message}",

        handler="withdrawal_complete",

        context={},

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

    safe_title = html.escape(
        str(title)
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

            <a
                style="
                    display:inline-block;
                    background:#087f72;
                    color:#fff;
                    padding:10px 18px;
                    border-radius:8px;
                    text-decoration:none;
                "
                href="/"
            >
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
# التأكد من callback نفاذ في قاعدة البيانات
# =========================================================

def callback_completed(
    connection,
    request_id: str,
    identity: str
):

    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            SELECT 1

            FROM nafath_callbacks

            WHERE
                request_id = %s
                AND PersonId = %s
                AND status = 'COMPLETED'

            ORDER BY id DESC

            LIMIT 1
            """,
            (
                request_id,
                identity
            )
        )

        return (
            cursor.fetchone()
            is not None
        )

    finally:

        cursor.close()


# =========================================================
# هل نفاذ مكتمل بحسب Session؟
# =========================================================

def session_nafath_completed(
    request: Request,
    request_id: str,
    identity: str
):

    verified_request_id = str(
        request.session.get(
            "nafath_verified_request_id",
            ""
        )
    ).strip()

    verified_identity = re.sub(
        r"\D",
        "",
        str(
            request.session.get(
                "nafath_verified_person_id",
                ""
            )
        )
    )

    verified_at = int(
        request.session.get(
            "nafath_verified_at",
            0
        )
        or 0
    )

    if not verified_request_id:
        return False

    if not verified_identity:
        return False

    if verified_at <= 0:
        return False

    # التحقق صالح لمدة 5 دقائق فقط
    if (
        int(time.time())
        - verified_at
    ) > 300:
        return False

    request_matches = (
        hmac.compare_digest(
            request_id,
            verified_request_id
        )
    )

    identity_matches = (
        hmac.compare_digest(
            identity,
            verified_identity
        )
    )

    return (
        request_matches
        and identity_matches
    )


# =========================================================
# الاستعلام المباشر من نفاذ
# =========================================================

async def live_nafath_status(
    request: Request,
    request_id: str,
    identity: str
):

    session_nid = re.sub(
        r"\D",
        "",
        str(
            request.session.get(
                "nid",
                ""
            )
        )
    )

    trans_id = str(
        request.session.get(
            "trans_id",
            ""
        )
    ).strip()

    random_value = str(
        request.session.get(
            "random",
            ""
        )
    ).strip()

    if (
        not request_id
        or not identity
        or not session_nid
        or not trans_id
        or not random_value
    ):

        return ""

    if not hmac.compare_digest(
        identity,
        session_nid
    ):

        return ""

    form_data = {
        "nid":
            session_nid,

        "random":
            random_value,

        "trans_id":
            trans_id,

        "requestId":
            request_id
    }

    response_data = None
    status_code = 0
    error_text = ""

    try:

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                10.0,
                connect=4.0
            )
        ) as client:

            response = await client.post(
                NAFATH_STATUS_URL,

                data=form_data,

                headers={
                    "Content-Type":
                        "application/x-www-form-urlencoded"
                }
            )

        status_code = (
            response.status_code
        )

        try:

            response_data = (
                response.json()
            )

        except ValueError:

            response_data = {
                "raw":
                    response.text
            }

    except Exception as error:

        error_text = str(error)

    # تسجيل عملية الاستعلام
    log_action(
        request=request,

        message=(
            "تم الاستعلام المباشر "
            "عن حالة تحقق نفاذ "
            "لطلب الانسحاب."
        ),

        handler="nafath_live_status",

        context={
            "request_id":
                request_id,

            "http_code":
                status_code,

            "error":
                error_text,

            "response":
                response_data
        },

        direction=(
            "system"
            if (
                status_code >= 200
                and status_code < 300
            )
            else "error"
        )
    )

    if (
        status_code < 200
        or status_code >= 300
        or not isinstance(
            response_data,
            dict
        )
    ):

        return ""

    return str(
        response_data.get(
            "status",
            ""
        )
    ).strip().upper()


# =========================================================
# إكمال الانسحاب
# =========================================================

@router.get(
    "/withdrawal/complete"
)
async def withdrawal_complete(
    request: Request,
    token: str = ""
):

    pending = request.session.get(
        "gulf_ai_withdrawal_pending",
        {}
    )

    # =====================================================
    # التأكد من Token الخاص بعملية الانسحاب
    # =====================================================

    pending_token = str(
        pending.get(
            "token",
            ""
        )
    )

    if (
        not pending
        or not pending_token
        or not token
        or not hmac.compare_digest(
            pending_token,
            token
        )
    ):

        return render_page(
            request,

            "تعذر التحقق",

            (
                "جلسة الطلب غير صحيحة. "
                "ارجعي للمساعد وابدئي "
                "الطلب من جديد."
            ),

            False
        )

    # =====================================================
    # التأكد أن العملية لم تستخدم وانتهت مدتها
    # =====================================================

    created_at = int(
        pending.get(
            "created_at",
            0
        )
        or 0
    )

    if (
        pending.get(
            "consumed"
        )
        or not created_at
        or (
            int(time.time())
            - created_at
        ) > 900
    ):

        return render_page(
            request,

            "انتهت جلسة الطلب",

            (
                "لم يتم إنشاء طلب جديد. "
                "ارجعي للمساعد وابدئي "
                "الطلب مرة ثانية."
            ),

            False
        )

    # =====================================================
    # بيانات نفاذ
    # =====================================================

    request_id = str(
        request.session.get(
            "request_id",
            ""
        )
    ).strip()

    identity = re.sub(
        r"\D",
        "",
        str(
            pending.get(
                "identity",
                ""
            )
        )
    )

    if not identity:

        return render_page(
            request,

            "لم يكتمل نفاذ",

            (
                "ما وصلنا تأكيد مكتمل "
                "من نفاذ، لذلك لم يتم "
                "إنشاء طلب الانسحاب."
            ),

            False
        )

    connection = None
    cursor = None

    try:

        connection = (
            get_db_connection()
        )

        # =================================================
        # الحصول على request_id من Callback نفاذ
        # إذا لم يكن موجودًا في Session
        # =================================================

        nafath_callback_baseline = int(
            pending.get(
                "nafath_callback_baseline",
                0
            )
            or 0
        )

        if not request_id:

            callback_data = find_completed_callback(
                connection,
                identity,
                nafath_callback_baseline
            )

            if callback_data:

                request_id = (
                    callback_data[
                        "request_id"
                    ]
                )

                request.session[
                    "request_id"
                ] = request_id

        # =================================================
        # انتظار Callback نفاذ لفترة قصيرة
        # =================================================

        if not request_id:

            for _ in range(5):

                await asyncio.sleep(
                    0.4
                )

                callback_data = (
                    find_completed_callback(
                        connection,
                        identity,
                        nafath_callback_baseline
                    )
                )

                if callback_data:

                    request_id = (
                        callback_data[
                            "request_id"
                        ]
                    )

                    request.session[
                        "request_id"
                    ] = request_id

                    break

        if not request_id:

            return render_page(
                request,

                "لم يكتمل نفاذ",

                (
                    "ما وصلنا تأكيد مكتمل "
                    "من نفاذ، لذلك لم يتم "
                    "إنشاء طلب الانسحاب."
                ),

                False
            )

        # =================================================
        # 1. التحقق من Session
        # =================================================

        nafath_completed = (
            session_nafath_completed(
                request,
                request_id,
                identity
            )
        )

        # =================================================
        # 2. التحقق من callback في DB
        # =================================================

        if not nafath_completed:

            nafath_completed = (
                callback_completed(
                    connection,
                    request_id,
                    identity
                )
            )

        # =================================================
        # 3. الاستعلام المباشر
        # =================================================

        if not nafath_completed:

            live_status = (
                await live_nafath_status(
                    request,
                    request_id,
                    identity
                )
            )

            nafath_completed = (
                live_status
                == "COMPLETED"
            )

        # =================================================
        # 4. انتظار callback لفترة قصيرة
        #
        # PHP كان:
        # 5 مرات × 0.4 ثانية
        # =================================================

        if not nafath_completed:

            for _ in range(5):

                await asyncio.sleep(
                    0.4
                )

                if callback_completed(
                    connection,
                    request_id,
                    identity
                ):

                    nafath_completed = True

                    break

        if not nafath_completed:

            return render_page(
                request,

                "لم يكتمل نفاذ",

                (
                    "لم نجد تحققًا مكتملًا "
                    "ومطابقًا لهذه العملية، "
                    "لذلك لم يتم إنشاء الطلب."
                ),

                False
            )

        # =================================================
        # الرقم الجامعي
        # =================================================

        student_id = re.sub(
            r"\D",
            "",
            str(
                pending.get(
                    "student_id",
                    ""
                )
            )
        )

        # =================================================
        # مطابقة الطالب والهوية
        # =================================================

        cursor = connection.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                id,
                student_id,
                iqama,
                ar_name1,
                ar_name2,
                ar_name3,
                ar_name4

            FROM sis_application

            WHERE
                student_id = %s
                AND iqama = %s

            LIMIT 1
            """,
            (
                student_id,
                identity
            )
        )

        application = (
            cursor.fetchone()
        )

        if not application:

            return render_page(
                request,

                "تعذر مطابقة البيانات",

                (
                    "الهوية التي تم التحقق "
                    "منها لا تطابق ملف الطالب، "
                    "ولم يتم إنشاء الطلب."
                ),

                False
            )

        # =================================================
        # هل لديه طلب انسحاب قائم؟
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

            pending["consumed"] = 1

            request.session[
                "gulf_ai_withdrawal_pending"
            ] = pending

            request.session.pop(
                "gulf_ai_withdrawal_stage",
                None
            )

            request.session.pop(
                "gulf_ai_withdrawal_reason",
                None
            )

            retreat_id = int(
                active_request["id"]
            )

            remember_message(
                request,

                (
                    "طلب الانسحاب موجود "
                    "مسبقاً برقم "
                    f"{retreat_id}، "
                    "لذلك ما أنشأت "
                    "طلباً مكرراً."
                )
            )

            return render_page(
                request,

                "الطلب موجود مسبقًا",

                (
                    "لديك طلب انسحاب قائم "
                    f"برقم {retreat_id}، "
                    "ولم ننشئ طلبًا مكررًا."
                ),

                True
            )

        # =================================================
        # بناء اسم الطالب
        # =================================================

        name_parts = [
            application.get(
                "ar_name1",
                ""
            ),
            application.get(
                "ar_name2",
                ""
            ),
            application.get(
                "ar_name3",
                ""
            ),
            application.get(
                "ar_name4",
                ""
            )
        ]

        student_name = " ".join(
            str(part).strip()
            for part in name_parts
            if part
        )

        # إزالة المسافات الزائدة
        student_name = re.sub(
            r"\s+",
            " ",
            student_name
        ).strip()

        # =================================================
        # سبب الانسحاب
        # =================================================

        reason = str(
            pending.get(
                "reason",
                ""
            )
        ).strip()[:500]

        # =================================================
        # IP
        # =================================================

        client_ip = ""

        if request.client:

            client_ip = (
                request.client.host
            )

        # =================================================
        # إنشاء طلب الانسحاب
        # =================================================

        cursor.execute(
            """
            INSERT INTO sis_admission_retreat
            (
                student_id,
                student_name,
                reason,
                attachment,
                app_date,
                status,
                p_ip
            )

            VALUES
            (
                %s,
                %s,
                %s,
                '',
                NOW(),
                0,
                %s
            )
            """,
            (
                student_id,
                student_name,
                reason,
                client_ip
            )
        )

        connection.commit()

        retreat_id = (
            cursor.lastrowid
        )

        if not retreat_id:

            return render_page(
                request,

                "تعذر رفع الطلب",

                (
                    "لم يتم حفظ الطلب بسبب "
                    "مشكلة تقنية. "
                    "لم ننفذ أي انسحاب، "
                    "ويمكنك المحاولة لاحقًا."
                ),

                False
            )

        # =================================================
        # تحديث Session
        # =================================================

        pending["consumed"] = 1

        request.session[
            "gulf_ai_withdrawal_pending"
        ] = pending

        request.session[
            "gulf_ai_verified_identity"
        ] = identity

        request.session[
            "gulf_ai_verified_student_id"
        ] = student_id

        request.session[
            "gulf_ai_student_id"
        ] = student_id

        # =================================================
        # حذف البيانات المؤقتة
        # =================================================

        keys_to_remove = [

            "gulf_ai_withdrawal_stage",

            "gulf_ai_withdrawal_reason",

            "gulf_ai_withdrawal_original_message",

            "gulf_ai_withdrawal_identity",

            "gulf_ai_withdrawal_student_id",

            "nafath_verified_request_id",

            "nafath_verified_person_id",

            "nafath_verified_at"
        ]

        for key in keys_to_remove:

            request.session.pop(
                key,
                None
            )

        # =================================================
        # حفظ الرسالة داخل الشات
        # =================================================

        remember_message(
            request,

            (
                "تم رفع طلب الانسحاب رسمياً "
                "بعد نجاح التحقق عبر نفاذ. "
                f"رقم الطلب {retreat_id} "
                "وحالته الآن «بصدد الدراسة»."
            )
        )

        # =================================================
        # تسجيل نجاح إنشاء الطلب
        # =================================================

        log_action(
            request=request,

            message=(
                "تم إنشاء طلب الانسحاب "
                "في قاعدة البيانات "
                "بعد نجاح نفاذ."
            ),

            handler="withdrawal_created",

            context={
                "retreat_id":
                    retreat_id,

                "student_id":
                    student_id,

                "nafath_request_id":
                    request_id,

                "status":
                    0
            },

            direction="system"
        )

        # =================================================
        # النتيجة النهائية
        # =================================================

        return render_page(
            request,

            "تم رفع طلب الانسحاب",

            (
                f"رقم الطلب: {retreat_id}. "
                "حالته الآن «بصدد الدراسة». "
                "رفع الطلب لا يعني تنفيذ الانسحاب، "
                "وستظهر لك حالته من خلال المساعد "
                "عند مراجعته."
            ),

            True
        )

    except Exception as error:

        if connection:

            try:
                connection.rollback()

            except Exception:
                pass

        print(
            "Withdrawal complete error:",
            error
        )

        return render_page(
            request,

            "تعذر رفع الطلب",

            (
                "لم يتم حفظ الطلب بسبب "
                "مشكلة تقنية. "
                "لم ننفذ أي انسحاب، "
                "ويمكنك المحاولة لاحقًا."
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