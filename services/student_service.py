from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from database import get_db_connection
from services.text_utils import clean, clean_reply, contains, money, normalize

_COLUMN_CACHE: dict[str, bool] = {}
_TABLE_CACHE: dict[str, bool] = {}


def _digits(value: Any) -> str:
    return re.sub(r'\D', '', str(value or ''))


def table_has_column(table: str, column: str) -> bool:
    key = f'{table}.{column}'
    if key in _COLUMN_CACHE:
        return _COLUMN_CACHE[key]
    safe_table = table.replace('`', '')
    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute(f'SHOW COLUMNS FROM `{safe_table}` LIKE %s', (column,))
        result = cur.fetchone() is not None
        _COLUMN_CACHE[key] = result
        return result
    finally:
        cur.close(); conn.close()


def table_exists(table: str) -> bool:
    safe_table = table.replace('`', '')
    if safe_table in _TABLE_CACHE:
        return _TABLE_CACHE[safe_table]
    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute('SHOW TABLES LIKE %s', (safe_table,))
        result = cur.fetchone() is not None
        _TABLE_CACHE[safe_table] = result
        return result
    finally:
        cur.close(); conn.close()


def build_queue_context(student_id: str) -> dict:
    student_id = _digits(student_id)
    if not student_id or not table_exists('sis_queue'):
        return {'found': False}

    columns = ['status']
    for column in ('error', 'log_sms', 'body_sms'):
        if table_has_column('sis_queue', column):
            columns.append(column)
    order = 'id DESC' if table_has_column('sis_queue', 'id') else 'student_id DESC'
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute(f"SELECT {','.join(columns)} FROM sis_queue WHERE student_id=%s ORDER BY {order} LIMIT 1", (student_id,))
        row = cur.fetchone()
    finally:
        cur.close(); conn.close()
    if not row:
        return {'found': False}

    status = str(row.get('status') or '').strip().lower()
    error = str(row.get('error') or '').strip()
    error_n = normalize(error).lower()
    public_status = 'غير معروفة'; public_detail = ''
    if status == 'completed':
        public_status = 'مكتمل'
        public_detail = 'اكتمل تجهيز الحساب والمقررات، وقبلت بوابة الرسائل طلب الإرسال.'
    elif status == 'initiated':
        public_status = 'بانتظار التنفيذ'
        public_detail = 'الرقم الجامعي صدر والطلب ينتظر بدء تجهيز الحساب والمقررات.'
    elif status == 'in progress':
        public_status = 'تحت التنفيذ'
        public_detail = 'يجري حالياً تجهيز الحساب والمقررات.'
    elif status == 'error':
        public_status = 'متوقف ويحتاج معالجة'
        public_detail = 'توقف تجهيز الحساب بسبب مشكلة تقنية.'
        if 'payment' in error_n or contains(error_n, 'الدفع'):
            public_detail = 'توقف التجهيز لأن السداد لم يظهر للكيو وقت التنفيذ.'
        elif 'disabled' in error_n:
            public_detail = 'توقف التجهيز لأن الحساب الجامعي موجود لكنه غير مفعّل.'
        elif 'missing courses' in error_n or contains(error_n, 'لا توجد مقررات'):
            public_detail = 'توقف التجهيز لأن مقررات المستوى الأول غير مكتملة في الخطة أو الطرح.'
        elif 'session' in error_n or contains(error_n, 'شعبه'):
            public_detail = 'توقف التجهيز لأن إحدى الشعب المطلوبة غير مطروحة بشكل مكتمل.'
        elif 'moodle' in error_n or contains(error_n, 'نظام اداره التعلم'):
            public_detail = 'توقف التجهيز أثناء إنشاء الحساب أو تسجيل المقررات في منصة التعلم.'
        elif 'already exist' in error_n or contains(error_n, 'لديه مقررات'):
            public_detail = 'الحساب أو المقررات موجودة مسبقاً، وتحتاج الحالة مطابقة بدل إعادة الإنشاء.'

    # PHP source returned an uninitialized $sms_body. Fixed here.
    sms_body = clean_reply(row.get('body_sms') or '')
    if len(sms_body) > 2500:
        sms_body = sms_body[:2500] + '...'
    return {
        'found': True,
        'status': public_status,
        'detail': public_detail,
        'sms_request_recorded': bool(row.get('log_sms')),
        'sms_body_available': bool(str(row.get('body_sms') or '').strip()),
        'sms_body': sms_body,
    }


def ensure_queue_entry(student_id: str) -> bool:
    student_id = _digits(student_id)
    if not student_id or not table_exists('sis_queue'):
        return False
    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute('SELECT 1 FROM sis_queue WHERE student_id=%s LIMIT 1', (student_id,))
        if cur.fetchone():
            return True
        cur.execute("INSERT INTO sis_queue (student_id,status) VALUES (%s,'initiated')", (student_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback(); return False
    finally:
        cur.close(); conn.close()


def refund_status_text(status: Any) -> str:
    return {0:'قيد المراجعة',1:'مقبول وبانتظار تنفيذ الاسترداد',2:'لا يوجد مبلغ مستحق للاسترداد',3:'مرفوض',4:'تم تنفيذ الاسترداد واعتماده'}.get(int(status or 0), 'حالة غير معروفة')


def retreat_status_text(status: Any, final_done: Any) -> str:
    if int(final_done or 0) == 1:
        return 'تم تنفيذ الانسحاب نهائياً'
    return {0:'في انتظار المراجعة',1:'تم قبول الانسحاب وبانتظار الاعتماد النهائي',2:'تم رفض طلب الانسحاب'}.get(int(status or 0), 'حالة غير معروفة')


def find_student_basic(student_id: str):
    student_id = str(student_id or '').strip()
    if not re.fullmatch(r'\d{7,12}', student_id):
        return None
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT * FROM sis_application WHERE student_id=%s LIMIT 1', (student_id,))
        row = cur.fetchone()
        if row:
            return row
        cur.execute('SELECT * FROM sis_application_withdrawn WHERE student_id=%s LIMIT 1', (student_id,))
        return cur.fetchone()
    finally:
        cur.close(); conn.close()


def find_applicant_basic(identity: str):
    identity = _digits(identity)
    if not re.fullmatch(r'[12]\d{9}', identity):
        return None
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT * FROM sis_application WHERE iqama=%s ORDER BY id DESC LIMIT 1', (identity,))
        return cur.fetchone()
    finally:
        cur.close(); conn.close()


def build_applicant_context(identity: str) -> dict:
    app = find_applicant_basic(identity)
    if not app:
        return {}
    application_id = int(app['id'])
    student_id = str(app.get('student_id') or '').strip()
    full_name = re.sub(r'\s+', ' ', ' '.join(str(app.get(f'ar_name{i}') or '') for i in range(1,5))).strip()
    major_name = ''
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        if app.get('major_id'):
            cur.execute('SELECT name FROM sis_majors WHERE id=%s LIMIT 1', (int(app['major_id']),))
            major_row = cur.fetchone()
            if major_row:
                major_name = clean(major_row.get('name'))

        paid = 0.0
        if table_has_column('sis_external_invoices', 'app_id'):
            cur.execute('SELECT IFNULL(SUM(amount),0) AS paid FROM sis_external_invoices WHERE app_id=%s AND amount>1.01', (application_id,))
            row = cur.fetchone(); paid = float(row.get('paid') or 0) if row else 0
        if paid <= 0 and student_id and table_has_column('sis_external_invoices', 'student_id'):
            cur.execute('SELECT IFNULL(SUM(amount),0) AS paid FROM sis_external_invoices WHERE student_id=%s AND amount>1.01', (student_id,))
            row = cur.fetchone(); paid = float(row.get('paid') or 0) if row else 0

        cur.execute("""
            SELECT signed_date,total_price,eachterm,major
            FROM sis_signed_contracts WHERE iqama=%s ORDER BY signed_date DESC LIMIT 1
        """, (identity,))
        contract = cur.fetchone()
    finally:
        cur.close(); conn.close()

    queue = build_queue_context(student_id) if student_id else {'found': False}
    return {
        'found': True,
        'application_id': application_id,
        'applicant_name': clean(full_name),
        'major': major_name,
        'student_id_issued': bool(student_id),
        'student_id': student_id,
        'paid_amount': paid,
        'contract_signed': bool(contract),
        'contract_signed_date': clean(contract.get('signed_date')) if contract else '',
        'queue': queue,
        'application_date': clean(app.get('application_date')),
    }


def applicant_direct_reply(message: str, context: dict, gender: str = 'unknown') -> str:
    if not context.get('found'):
        return ''
    text = normalize(message); parts: list[str] = []
    asks_contract = contains(text, 'عقد')
    asks_number = contains(text, 'رقم جامعي') or contains(text, 'الرقم الجامعي')
    asks_sms = contains(text, 'رساله') or contains(text, 'رسالة') or contains(text, 'نصيه')
    asks_login = any(contains(text, x) for x in ('بيانات الدخول','كيف ادخل','وين ادخل','دخول الطالب')) or asks_sms
    asks_payment = contains(text, 'دفعت') or contains(text, 'سداد')
    press_resend = (
        'اضغطي زر «إعادة إرسال بيانات الدخول» تحت، وبنرسل نفس الرسالة لجوالك المسجل.' if gender == 'female' else
        'اضغط زر «إعادة إرسال بيانات الدخول» تحت، وبنرسل نفس الرسالة لجوالك المسجل.' if gender == 'male' else
        'اضغط زر «إعادة إرسال بيانات الدخول» تحت، وبنرسل نفس الرسالة للجوال المسجل.'
    )
    if asks_payment:
        parts.append('إيه، السداد الفعلي ظاهر عندنا بمبلغ ' + money(context['paid_amount']) + ' ريال.' if float(context.get('paid_amount') or 0) > 0 else 'ما ظهر على طلبك سداد دراسي فعلي للحين.')
    if asks_contract and not asks_number and not asks_login:
        parts.append('إيه، عقدك موقع ومكتمل عندنا.' if context.get('contract_signed') else 'عقدك للحين ما ظهر كموقّع في النظام.')
    if asks_number or asks_login:
        if context.get('student_id_issued'):
            queue = context.get('queue') or {'found': False}
            if queue.get('found'):
                if queue.get('status') == 'مكتمل':
                    parts.append(f"تم، لقيت طلبك وكل شيء مكتمل. رقمك الجامعي {context['student_id']} وبيانات الدخول جاهزة.")
                    if asks_sms and queue.get('sms_body'):
                        parts.append('هذي نفس الرسالة المسجلة لك:\n' + queue['sms_body'])
                    parts.append(press_resend)
                elif queue.get('status') in ('بانتظار التنفيذ','تحت التنفيذ'):
                    parts.append(f"رقمك الجامعي صدر وهو {context['student_id']}، وحسابك حالياً تحت التجهيز. ما يحتاج تعيد التسجيل أو تدفع مرة ثانية.")
                elif queue.get('status') == 'متوقف ويحتاج معالجة':
                    parts.append(f"رقمك الجامعي صدر وهو {context['student_id']}، لكن تجهيز الحساب توقف بسبب مشكلة تقنية ويحتاج إعادة معالجة. ما يحتاج تعيد التسجيل أو الدفع.")
                else:
                    parts.append(f"رقمك الجامعي صدر وهو {context['student_id']}، لكن حالة تجهيز الرسالة تحتاج مراجعة.")
            else:
                if context.get('contract_signed') and ensure_queue_entry(context['student_id']):
                    parts.append(f"رقمك الجامعي صدر وهو {context['student_id']}. طلب التجهيز ما كان داخل الطابور، وأضفته الآن تلقائياً. ما يحتاج تعيد التسجيل أو الدفع.")
                else:
                    parts.append(f"رقمك الجامعي صدر وهو {context['student_id']}، لكن طلب تجهيز الحساب ما ظهر في الطابور ويحتاج معالجة.")
        else:
            if context.get('contract_signed'):
                parts.append('تأكدت من طلبك: العقد موقع، لكن الرقم الجامعي ما انصدر للحين. طلبك يحتاج استكمال خطوة الإصدار على نفس التسجيل، وما يحتاج تعيد التسجيل أو السداد.')
            else:
                parts.append('لقيت طلبك، لكن العقد للحين ما ظهر كموقّع؛ لذلك الرقم الجامعي ما انصدر.')
    return '\n'.join(dict.fromkeys(parts))


def applicant_reply_actions(context: dict) -> list[dict]:
    if not context.get('student_id_issued') or not (context.get('queue') or {}).get('found'):
        return []
    queue = context['queue']
    if queue.get('status') != 'مكتمل' or not queue.get('sms_body_available'):
        return []
    return [{'label': 'إعادة إرسال بيانات الدخول', 'url': '/resend-student-message'}]


def config_date_value(name: str) -> str:
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT fieldvalue FROM sis_config WHERE name=%s LIMIT 1', (name,))
        row = cur.fetchone()
        return str(row.get('fieldvalue') or '').strip() if row else ''
    finally:
        cur.close(); conn.close()


def date_from_dmy(value: str) -> dict:
    value = str(value or '').strip()
    parts = re.split(r'[/\-]', value)
    if len(parts) != 3:
        return {'display': value, 'date': None}
    try:
        dt = datetime(int(parts[2]), int(parts[1]), int(parts[0])).date()
    except Exception:
        return {'display': value, 'date': None}
    return {'display': dt.strftime('%d/%m/%Y'), 'date': dt}


def registration_window_context() -> dict:
    start = date_from_dmy(config_date_value('registration_start'))
    end = date_from_dmy(config_date_value('registration_end'))
    today = datetime.now().date(); status = 'غير محددة'
    if start['date'] and end['date']:
        if today < start['date']:
            status = 'لم تبدأ'
        elif today > end['date']:
            status = 'منتهية'
        else:
            status = 'مفتوحة'
    return {'status': status, 'start_date': start['display'], 'end_date': end['display']}


def build_registration_finance_context(student: dict, contract: dict | None) -> dict:
    student_id = str(student.get('student_id') or '').strip()
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        total_paid = 0.0
        cur.execute("""
            SELECT n.amount,n.fees_type,n.notes,f.name AS fee_name
            FROM sis_financial_notes n
            LEFT JOIN sis_financial_fees f ON f.id=n.fees_type
            WHERE n.student=%s ORDER BY n.added_date ASC
        """, (student_id,))
        for row in cur.fetchall():
            amount = float(row.get('amount') or 0); fee_type = int(row.get('fees_type') or 0)
            desc = normalize(f"{row.get('notes') or ''} {row.get('fee_name') or ''}")
            if abs(amount) <= 1.009:
                continue
            is_registration_fee = any(contains(desc, x) for x in ('رسوم التسجيل','رسوم تقديم الطلب','رسوم التقديم','registration fee'))
            is_medium_payment = contains(desc, 'رسوم') and contains(desc, 'دبلوم متوسط')
            is_change_major = any(contains(desc, x) for x in ('تغير مسار','تغيير مسار','تحويل مسار','تغير التخصص','تغيير التخصص','تحويل التخصص','استكمال رسوم الفصل بعد تغيير المسار'))
            is_tuition = fee_type in (1,3)
            student_bachelor_type = int(student.get('bachelor_type') or 0)
            contract_period = int(contract.get('period') or 0) if contract else 0
            is_high_contract = student_bachelor_type > 0 or contract_period == 2
            if is_high_contract and is_medium_payment:
                continue
            if not is_registration_fee and (is_tuition or is_change_major):
                total_paid += amount
        total_paid = max(0.0, total_paid)

        cur.execute("""
            SELECT COUNT(*) AS registered_terms FROM (
                SELECT year,semester FROM sis_academic_record WHERE st_id=%s GROUP BY year,semester
            ) registered_semesters
        """, (student_id,))
        row = cur.fetchone(); registered_terms = int(row.get('registered_terms') or 0) if row else 0
    finally:
        cur.close(); conn.close()

    result = {
        'calculation_available': False,
        'registration_status': 'مفتوح' if student.get('registration_finance_status') else 'مغلق',
        'registered_terms': registered_terms,
        'paid_for_registration': total_paid,
        'window': registration_window_context(),
    }
    if not contract:
        return result

    discount = str(student.get('discount') or '').strip(); discount_upper = discount.upper()
    bachelor_type = int(student.get('bachelor_type') or 0)
    signed_total = float(contract.get('total_price') or 0); signed_term = float(contract.get('eachterm') or 0)
    signed_period = max(1, int(contract.get('period') or 0)); is_high = bachelor_type > 0 or signed_period == 2
    if discount_upper == 'FREE':
        base_total = 0.0; base_term = 0.0; term_count = signed_period
    elif is_high and abs(signed_total - 14800) < 0.01 and discount:
        base_total = 9800.0; base_term = 4900.0; term_count = 2
    elif not is_high and abs(signed_total - 15000) < 0.01 and discount:
        base_total = 10000.0; base_term = 2500.0; term_count = 4
    else:
        base_total = signed_total; base_term = signed_term; term_count = signed_period

    identity = str(student.get('iqama') or '').strip()
    tax_rate = 0.0 if identity.startswith('1') else 0.15
    contract_total = base_total * (1 + tax_rate); term_amount = base_term * (1 + tax_rate)
    required_term_number = min(term_count, registered_terms + 1)
    required_amount = min(contract_total, term_amount * required_term_number)
    contract_remaining = max(0.0, contract_total - total_paid)
    shortage = max(0.0, required_amount - total_paid)
    result.update({
        'calculation_available': True, 'tax_rate': tax_rate, 'term_count': term_count,
        'term_amount': term_amount, 'contract_total': contract_total, 'contract_remaining': contract_remaining,
        'required_term_number': required_term_number, 'required_amount_for_registration': required_amount,
        'registration_shortage': shortage, 'has_paid_required_amount': contract_total <= 0 or total_paid + 0.009 >= required_amount,
    })
    return result


def build_gpa_context(student_id: str) -> dict:
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT mini_mark,max_mark,max_point FROM sis_full_scales')
        scales = cur.fetchall()
        cur.execute("""
            SELECT r.year,r.semester,r.mid_mark,r.final_mark,c.credits
            FROM sis_academic_record r
            LEFT JOIN sis_courses c ON c.full_code=r.course_id
            WHERE r.st_id=%s AND EXISTS (
                SELECT 1 FROM sis_academic_record valid_record
                WHERE valid_record.st_id=r.st_id AND valid_record.year=r.year
                  AND valid_record.semester=r.semester AND valid_record.valid=1
            )
            ORDER BY r.year ASC,r.semester ASC,r.id DESC
        """, (student_id,))
        rows = cur.fetchall()
    finally:
        cur.close(); conn.close()

    credits_total = points_total = 0.0; records_count = 0
    for row in rows:
        credits = float(row.get('credits') or 0)
        if credits <= 0:
            continue
        mark = float(row.get('mid_mark') or 0) + float(row.get('final_mark') or 0)
        if mark >= 95:
            point = 5.0
        elif mark < 60:
            point = 1.0
        else:
            point = 0.0
            for scale in scales:
                if float(scale.get('mini_mark') or 0) <= mark < float(scale.get('max_mark') or 0):
                    point = float(scale.get('max_point') or 0); break
        points_total += credits * point; credits_total += credits; records_count += 1
    if credits_total <= 0 or records_count == 0:
        return {'available': False}
    gpa = round(points_total / credits_total, 2)
    grade = 'ممتاز' if gpa >= 4.5 else 'جيد جداً' if gpa >= 3.75 else 'جيد' if gpa >= 2.75 else 'مقبول' if gpa >= 2 else 'ضعيف'
    return {'available': True, 'gpa': gpa, 'scale': 5, 'grade': grade, 'calculated_credits': credits_total}


def registration_group_source():
    if table_has_column('sis_courses_groups_enrol', 'group_id') and table_has_column('sis_courses_groups_enrol', 'course'):
        return {'table':'sis_courses_groups_enrol','group_column':'group_id','course_column':'course','course_is_id':True}
    tables = ('sis_courses_groups_courses','sis_course_groups_courses','sis_courses_group_courses','sis_courses_groups_items','sis_course_group_items','sis_group_courses','sis_courses_group')
    group_columns = ('group_id','courses_group_id','course_group_id','group','gid')
    course_columns = ('course_id','course','full_code','course_code')
    for table in tables:
        group_column = next((c for c in group_columns if table_has_column(table,c)), '')
        course_column = next((c for c in course_columns if table_has_column(table,c)), '')
        if group_column and course_column:
            return {'table':table,'group_column':group_column,'course_column':course_column,'course_is_id':False}
    return None


def student_plan_id(student_id: str, major_id: int) -> int:
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT cp.plan_id,COUNT(DISTINCT cp.course_id) AS matched_courses
            FROM sis_check_plan cp
            INNER JOIN sis_academic_record ar ON ar.course_id=cp.course_id
            WHERE ar.st_id=%s AND cp.major_id=%s AND ar.valid=1
            GROUP BY cp.plan_id HAVING matched_courses>0
            ORDER BY matched_courses DESC,cp.plan_id DESC LIMIT 1
        """, (student_id, int(major_id)))
        row = cur.fetchone()
        if row and row.get('plan_id'):
            return int(row['plan_id'])
        cur.execute('SELECT plan_id FROM sis_check_plan WHERE major_id=%s GROUP BY plan_id ORDER BY plan_id DESC LIMIT 1', (int(major_id),))
        row = cur.fetchone(); return int(row['plan_id']) if row and row.get('plan_id') else 0
    finally:
        cur.close(); conn.close()


def group_courses(source: dict | None, group_id: int) -> list[dict]:
    if not source or int(group_id or 0) <= 0:
        return []
    table = source['table'].replace('`',''); gc = source['group_column'].replace('`',''); cc = source['course_column'].replace('`','')
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        if source.get('course_is_id'):
            cur.execute(f"SELECT c.full_code AS code,c.name,c.credits FROM `{table}` gc INNER JOIN sis_courses c ON c.id=gc.`{cc}` WHERE gc.`{gc}`=%s ORDER BY c.id ASC", (int(group_id),))
        else:
            cur.execute(f"SELECT gc.`{cc}` AS code,c.name,c.credits FROM `{table}` gc LEFT JOIN sis_courses c ON TRIM(c.full_code)=TRIM(gc.`{cc}`) WHERE gc.`{gc}`=%s ORDER BY c.id ASC", (int(group_id),))
        return [{'code':clean(r.get('code')),'name':clean(r.get('name')),'credits':float(r.get('credits') or 0)} for r in cur.fetchall()]
    finally:
        cur.close(); conn.close()


def student_has_course(student_id: str, course_code: str) -> bool:
    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute('SELECT id FROM sis_academic_record WHERE st_id=%s AND TRIM(course_id)=TRIM(%s) LIMIT 1', (student_id, course_code))
        if cur.fetchone():
            return True
        cur.execute('SELECT id FROM sis_academic_outside_record WHERE st_id=%s AND TRIM(course_id)=TRIM(%s) LIMIT 1', (student_id, course_code))
        return cur.fetchone() is not None
    finally:
        cur.close(); conn.close()


def build_expected_package(student: dict) -> dict:
    student_id = str(student.get('student_id') or '').strip(); major_id = int(student.get('major_id') or 0)
    plan_id = student_plan_id(student_id, major_id); source = registration_group_source()
    if not student_id or plan_id <= 0 or not source:
        return {'available': False}
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT group1,group2,group3,group4,group5,group6,group7,group8 FROM sis_plans WHERE id=%s LIMIT 1', (plan_id,))
        plan = cur.fetchone()
        if not plan:
            return {'available': False}
        for level in range(1,9):
            group_id = int(plan.get(f'group{level}') or 0)
            if group_id <= 0:
                continue
            courses = group_courses(source, group_id)
            if not courses:
                continue
            missing = [c for c in courses if not student_has_course(student_id, c['code'])]
            if missing:
                cur.execute('SELECT name FROM sis_courses_groups WHERE id=%s LIMIT 1', (group_id,))
                row = cur.fetchone(); group_name = clean(row.get('name')) if row else ''
                return {'available':True,'plan_id':plan_id,'level':level,'group_id':group_id,'group_name':group_name,'courses':missing}
        return {'available':True,'plan_id':plan_id,'completed':True,'courses':[]}
    finally:
        cur.close(); conn.close()


def build_student_context(student_id: str) -> dict:
    student = find_student_basic(student_id)
    if not student:
        return {}
    major_id = int(student.get('major_id') or 0); major = {}
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        if major_id > 0:
            cur.execute('SELECT id,name,period FROM sis_majors WHERE id=%s LIMIT 1', (major_id,)); major = cur.fetchone() or {}
        full_name = re.sub(r'\s+', ' ', ' '.join(str(student.get(f'ar_name{i}') or '') for i in range(1,5))).strip()
        context = {
            'found':True,'student_id':str(student_id),'student_name':clean(full_name),
            'gender':'أنثى' if str(student.get('gender')) != '' and int(student.get('gender') or 0)==0 else ('ذكر' if str(student.get('gender')) != '' else 'غير محدد'),
            'major':clean(major.get('name')),'program_period':int(major.get('period')) if major.get('period') is not None else None,
            'exit_point_approved':bool(student.get('exit_point_approved')),
            'academic_record_access':'مفتوح' if student.get('finance_status') else 'مغلق',
            'course_registration_access':'مفتوح' if student.get('registration_finance_status') else 'مغلق',
        }
        cur.execute("""
            SELECT IFNULL(SUM(CASE WHEN amount>0 THEN amount ELSE 0 END),0) AS paid,
                   ABS(IFNULL(SUM(CASE WHEN amount<0 THEN amount ELSE 0 END),0)) AS refunded,
                   IFNULL(SUM(scholarship_amount),0) AS discounts, IFNULL(SUM(tax),0) AS tax
            FROM sis_financial_notes WHERE student=%s
        """, (student_id,))
        financial = cur.fetchone() or {}
        context['finance'] = {
            'total_positive_payments':float(financial.get('paid') or 0),'total_refunded_entries':float(financial.get('refunded') or 0),
            'discounts':float(financial.get('discounts') or 0),'tax':float(financial.get('tax') or 0),
        }

        cur.execute("""
            SELECT id,student_id,reason,app_date,status,remarks,final_done,final_date
            FROM sis_admission_retreat WHERE student_id=%s ORDER BY id DESC LIMIT 1
        """, (student_id,))
        retreat = cur.fetchone()
        if retreat:
            context['withdrawal'] = {
                'request_id':int(retreat['id']),'request_date':clean(retreat.get('app_date')),'reason':clean(retreat.get('reason')),
                'status_code':int(retreat.get('status') or 0),'status':retreat_status_text(retreat.get('status'),retreat.get('final_done')),
                'final_done':int(retreat.get('final_done') or 0)==1,'final_date':clean(retreat.get('final_date')),'remarks':clean(retreat.get('remarks')),
            }
            cur.execute("""
                SELECT id,refund_amount,status,remarks,app_date FROM sis_admission_retreat_refund
                WHERE retreat_id=%s ORDER BY id DESC LIMIT 1
            """, (int(retreat['id']),))
            refund = cur.fetchone()
            context['refund'] = ({
                'status_code':int(refund.get('status') or 0),'status':refund_status_text(refund.get('status')),
                'amount':float(refund.get('refund_amount') or 0),'date':clean(refund.get('app_date')),'remarks':clean(refund.get('remarks')),
            } if refund else {'status':'لا يوجد طلب استرداد مرتبط بالانسحاب'})
        else:
            context['withdrawal'] = {'status':'لا يوجد طلب انسحاب مسجل'}
            context['refund'] = {'status':'لا يوجد طلب استرداد مسجل'}

        identity = str(student.get('iqama') or '').strip(); contract = None
        if identity:
            cur.execute("""
                SELECT signed_date,period,total_price,eachterm,major FROM sis_signed_contracts
                WHERE iqama=%s ORDER BY signed_date DESC LIMIT 1
            """, (identity,)); contract = cur.fetchone()
        context['contract'] = ({
            'signed':True,'signed_date':clean(contract.get('signed_date')),'total_price':float(contract.get('total_price') or 0),
            'term_price':float(contract.get('eachterm') or 0),'major':clean(contract.get('major')),
        } if contract else {'signed':False,'status':'لا يوجد عقد موقع مسجل'})

        cur.execute("""
            SELECT r.course_id,r.year,r.semester,r.status,r.valid,c.name,c.credits
            FROM sis_academic_record r LEFT JOIN sis_courses c ON c.full_code=r.course_id
            WHERE r.st_id=%s ORDER BY r.year DESC,r.semester DESC,r.id DESC LIMIT 30
        """, (student_id,))
        courses = []
        for course in cur.fetchall():
            status_text = 'مجتاز' if int(course.get('status') or 0)==1 else 'معتذر' if int(course.get('status') or 0)==6 else 'مسجل'
            courses.append({'code':clean(course.get('course_id')),'name':clean(course.get('name')),'credits':float(course.get('credits') or 0),
                            'year':clean(course.get('year')),'semester':clean(course.get('semester')),'status':status_text,'valid':int(course.get('valid') or 0)})
        context['latest_academic_records'] = courses
    finally:
        cur.close(); conn.close()

    context['registration_finance'] = build_registration_finance_context(student, contract)
    context['academic_summary'] = build_gpa_context(student_id)
    context['expected_registration_package'] = build_expected_package(student)
    return context


def personal_direct_reply(message: str, context: dict) -> str:
    if not context or not context.get('found'):
        return ''
    text = normalize(message); parts: list[str] = []
    asks_withdrawal = contains(text,'انسحاب')
    asks_refund = contains(text,'استرداد') or contains(text,'فلوسي ترجع') or contains(text,'رجع المبلغ')
    asks_contract = contains(text,'عقد')
    asks_balance = any(contains(text,x) for x in ('كم باقي','باقي العقد','المتبقي من العقد','تفاصيل المبالغ'))
    asks_payment = any(contains(text,x) for x in ('دفعت','دفعتي','فاتورتي','كم دفعت','المبلغ المدفوع')) or asks_balance
    asks_access = any(contains(text,x) for x in ('محجوب','حجب','مقفل','مغلق','ليش التسجيل','السجل الاكاديمي','تسجيل المقررات عندي'))
    asks_registration_method = any(contains(text,x) for x in ('كيف اسجل','ابي اسجل مقررات جديده','ابغى اسجل مقررات جديده','تسجيل مقررات جديده'))
    asks_expected_courses = not asks_registration_method and any(contains(text,x) for x in ('المقررات حقتي','المواد حقتي','المفروض تنزل','المفروض اسجل','لازم اسجل','المقررات المتبقيه','باكجي','البكج حقي'))
    asks_courses = not asks_registration_method and any(contains(text,x) for x in ('مقرراتي','موادي المسجله','المواد المسجله','وش مسجل'))
    asks_student_number = contains(text,'رقمي الجامعي'); asks_major = contains(text,'تخصصي')
    asks_gpa = contains(text,'معدلي') or contains(text,'المعدل العام') or contains(text,'كم المعدل')
    is_female = context.get('gender') == 'أنثى'

    if asks_withdrawal:
        w = context.get('withdrawal') or {}
        if 'request_id' not in w:
            parts.append('ما عندك طلب انسحاب مسجل في النظام.')
        else:
            code = int(w.get('status_code',-1)); final = bool(w.get('final_done'))
            if final:
                line = 'طلب انسحابك تم تنفيذه واعتماده نهائياً.'
                if w.get('final_date'): line += ' تاريخ التنفيذ: ' + str(w['final_date']) + '.'
                parts.append(line)
            elif code == 0: parts.append('طلب انسحابك موجود، لكنه للحين بانتظار المراجعة وما تم قبوله.')
            elif code == 1: parts.append('تمت الموافقة الأولية على طلب انسحابك، لكن الانسحاب للحين ما اكتمل ولا تم اعتماده نهائياً.')
            elif code == 2:
                line='طلب انسحابك مرفوض.'
                if w.get('remarks'): line += ' الملاحظة المسجلة: ' + str(w['remarks']) + '.'
                parts.append(line)
            else: parts.append('طلب انسحابك موجود، لكن حالته تحتاج مراجعة من الموظف المختص.')

    if asks_refund:
        r = context.get('refund') or {}; finance = context.get('finance') or {}; total_paid=float(finance.get('total_positive_payments') or 0)
        if 'status_code' not in r:
            parts.append('ما عندك طلب استرداد مسجل مرتبط بالانسحاب.')
        else:
            code=int(r.get('status_code') or 0); amount=float(r.get('amount') or 0); amount_text=money(amount)+' ريال'
            if code==0: parts.append('الاسترداد للحين قيد المراجعة وما تم اعتماده.')
            elif code==1:
                line='تم قبول استرداد مبلغ '+amount_text+'، لكنه بانتظار التنفيذ المالي.'
                if total_paid>0 and abs(amount-total_paid)<0.01: line+=' وهذا يساوي كامل الدفعات المسجلة عندك.'
                elif total_paid>0: line+=' إجمالي الدفعات المسجلة عندك '+money(total_paid)+' ريال.'
                parts.append(line)
            elif code==2: parts.append('المسجل على طلبك أنه ما فيه مبلغ مستحق للاسترداد.')
            elif code==3:
                line='طلب الاسترداد مرفوض.'
                if r.get('remarks'): line+=' الملاحظة المسجلة: '+str(r['remarks'])+'.'
                parts.append(line)
            elif code==4:
                line='تم تنفيذ واعتماد استرداد مبلغ '+amount_text+'.'
                if total_paid>0 and abs(amount-total_paid)<0.01: line+=' إيه، هذا كامل المبلغ المدفوع المسجل عندك.'
                elif total_paid>0: line+=' إجمالي الدفعات المسجلة عندك '+money(total_paid)+' ريال، لذلك الاسترداد مو كامل.'
                parts.append(line)

    if asks_contract:
        c=context.get('contract') or {}
        if c.get('signed'):
            line='عقدك موقع ومسجل في النظام'
            if c.get('signed_date'): line+=' بتاريخ '+str(c['signed_date'])
            parts.append(line+'.')
        else: parts.append('ما ظهر لك عقد موقع في النظام حالياً.')

    if asks_payment:
        finance=context.get('finance') or {}; reg=context.get('registration_finance') or {}
        paid=float(finance.get('total_positive_payments') or 0); refunded=float(finance.get('total_refunded_entries') or 0)
        line='تفاصيل حسابك المالية:\nإجمالي كل الدفعات المسجلة: '+money(paid)+' ريال.'
        if reg.get('calculation_available'):
            counted=float(reg.get('paid_for_registration') or 0); total=float(reg.get('contract_total') or 0); remaining=float(reg.get('contract_remaining') or 0)
            required=float(reg.get('required_amount_for_registration') or 0); shortage=float(reg.get('registration_shortage') or 0)
            line += '\nالمحتسب منها ضمن الرسوم الدراسية: '+money(counted)+' ريال.'
            line += '\nإجمالي العقد بعد الضريبة إن وجدت: '+money(total)+' ريال.'
            line += '\nالمتبقي من كامل العقد: '+money(remaining)+' ريال.'
            if shortage>0:
                line += '\nالمطلوب وصول دفعاتك إليه لتسجيل الفصل القادم: '+money(required)+' ريال.'
                line += '\nالناقص عليك الآن لفتح التسجيل: '+money(shortage)+' ريال.'
            else: line += '\nما عليك نقص مالي لفتح تسجيل الفصل القادم.'
        if refunded>0: line += '\nإجمالي قيود الاسترداد المسجلة: '+money(refunded)+' ريال.'
        parts.append(line)

    if asks_access:
        reg=context.get('registration_finance') or {}; window=reg.get('window') or {}
        if window.get('status')=='لم تبدأ': parts.append(f"تسجيلك مقفل لأن فترة التسجيل ما بدأت للحين. تفتح بتاريخ {window.get('start_date','')} وتنتهي بتاريخ {window.get('end_date','')}.")
        elif window.get('status')=='منتهية': parts.append(f"تسجيلك مقفل لأن فترة التسجيل انتهت بتاريخ {window.get('end_date','')}.")
        elif context.get('course_registration_access')=='مفتوح': parts.append('تسجيل المقررات مفتوح لك حالياً، و'+('تقدرين تدخلين وتسجلين' if is_female else 'تقدر تدخل وتسجل')+' الباكج.')
        elif reg.get('calculation_available') and float(reg.get('registration_shortage') or 0)>0:
            parts.append('تسجيلك مقفل لأن باقي عليك '+money(reg['registration_shortage'])+' ريال. '+('سددي' if is_female else 'سدد')+' المبلغ، وبعد اكتمال السداد '+('تنفتح لك' if is_female else 'ينفتح لك')+' التسجيل.')
        elif reg.get('calculation_available') and reg.get('has_paid_required_amount'):
            parts.append('المبلغ المطلوب مكتمل عندك، لكن التسجيل للحين ظاهر مقفل. '+('ادخلي' if is_female else 'ادخل')+' صفحة السداد أو التسجيل عشان تتحدث الحالة، وإذا بقي مقفل فالمشكلة من تحديث الحالة المالية وليست من المبلغ.')
        else: parts.append('تسجيل المقررات عندك ظاهر كمغلق، لكن ما توفرت بيانات كافية تحدد هل السبب من الفترة أو السداد.')

    if asks_registration_method:
        reg=context.get('registration_finance') or {}; first=int(reg.get('registered_terms') or 0)==0
        if first: parts.append('أنت ما عندك فصل مسجل سابق، لذلك تعتبر هذه أول عملية تسجيل لك، ومقررات المستوى الأول تنزل تلقائياً بعد اكتمال التسجيل وإصدار الرقم الجامعي.')
        elif context.get('course_registration_access')=='مفتوح': parts.append('بما أنك مو في أول تسجيل، تسجيلك مفتوح الآن: '+('ادخلي' if is_female else 'ادخل')+' صفحة تسجيل المقررات، وبيظهر باكج مستواك الحالي، ثم '+('اضغطي' if is_female else 'اضغط')+' «تسجيل الباكج» و'+('أكدي' if is_female else 'أكد')+'؛ بعدها يسجل النظام كل المقررات المتاحة في الباكج.')
        else: parts.append('بما أنك مو في أول تسجيل، وقت ما تفتح فترة التسجيل ويكتمل المبلغ المطلوب، '+('ادخلي' if is_female else 'ادخل')+' صفحة تسجيل المقررات و'+('اضغطي' if is_female else 'اضغط')+' «تسجيل الباكج»؛ النظام يسجل كل مقررات المستوى الحالي المتاحة. حالياً تسجيلك ظاهر كمغلق.')

    if asks_gpa:
        a=context.get('academic_summary') or {}
        parts.append(f"معدلك العام {float(a.get('gpa')):.2f} من {int(a.get('scale'))}، وتقديرك {a.get('grade')}." if a.get('available') else 'ما ظهر معدل قابل للحساب حالياً؛ غالباً ما عندك فصل معتمد بدرجات مكتملة إلى الآن.')

    if asks_expected_courses:
        p=context.get('expected_registration_package') or {}
        if p.get('available') and p.get('courses'):
            lines=[]
            for c in p['courses']:
                name=str(c.get('name') or '').strip(); code=str(c.get('code') or '').strip(); label=name or code
                if code and name: label += f' ({code})'
                credits=float(c.get('credits') or 0); lines.append('- '+label+(f' — {money(credits)} ساعات' if credits>0 else ''))
            title=p.get('group_name') or f"المستوى {int(p.get('level') or 0)}"
            parts.append('حسب خطتك وسجلك، الباكج المستحق لك هو '+title+':\n'+'\n'.join(lines))
        elif p.get('completed'): parts.append('حسب الخطة والسجل الحالي، ما بقي لك باكج مقررات غير مجتاز ظاهر في الخطة.')
        else: parts.append('فتحت سجلك، لكن ما قدرت أحدد الباكج المستحق من ربط الخطة الحالي. هنا يلزم مراجعة ربط الخطة بالشعب المطروحة.')

    if asks_courses:
        records=context.get('latest_academic_records') or []
        if not records: parts.append('ما ظهرت لك مقررات مسجلة في السجل الأكاديمي حالياً.')
        else:
            year=records[0]['year']; semester=records[0]['semester']; lines=[]
            for r in records:
                if r['year']!=year or r['semester']!=semester: continue
                name=str(r.get('name') or '').strip(); code=str(r.get('code') or '').strip(); label=name or code
                if code and name: label += f' ({code})'
                lines.append(f"- {label} — {r.get('status')}")
            parts.append('مقررات آخر فصل ظاهر في سجلك ('+str(year)+'/'+str(semester)+'):\n'+'\n'.join(lines) if lines else 'ما ظهرت لك مقررات في آخر فصل مسجل.')

    if asks_student_number: parts.append('رقمك الجامعي هو '+str(context.get('student_id'))+'.')
    if asks_major: parts.append('تخصصك المسجل هو '+str(context.get('major'))+'.' if context.get('major') else 'اسم التخصص ما ظهر في بياناتك الحالية.')
    return '\n\n'.join(parts)
