from __future__ import annotations

import re
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from database import get_db_connection
from services.chat_logging import (
    close_current_conversation,
    conversation_key,
    latency_ms,
    log_message,
    make_key,
)
from services.knowledge_service import get_official_knowledge, get_relevant_knowledge
from services.openai_service import build_instructions, classify_request_intent, generate_final_answer
from services.program_service import (
    get_plan_courses,
    load_programs,
    match_program,
    program_list_for_ai,
    training_course_from_plan,
)
from services.student_service import (
    applicant_direct_reply,
    applicant_reply_actions,
    build_applicant_context,
    build_student_context,
    find_applicant_basic,
    find_student_basic,
    personal_direct_reply,
)
from services.text_utils import (
    academic_calendar_reply,
    admission_registration_reply,
    clean,
    clean_reply,
    contains,
    detect_level,
    extract_four_digits,
    extract_national_id,
    extract_person_name,
    extract_student_id,
    guess_gender_from_name,
    is_admission_registration_question,
    is_applicant_access_followup,
    is_applicant_identity_request,
    is_greeting_only,
    is_no_reply,
    is_personal_request,
    is_registration_method_question,
    is_withdrawal_method_question,
    is_withdrawal_submission_request,
    is_yes_reply,
    limit,
    money,
    needs_plan,
    normalize,
    portal_navigation_reply,
    registration_method_reply,
    withdrawal_method_reply,
)

router = APIRouter()
BUILD = 'student-assistant-py-v1'
WELCOME = 'حياك الله في كلية الخليج، ممكن أعرف اسمك؟'

class ChatRequest(BaseModel):
    action: Optional[str] = None
    message: Optional[str] = None

class ImmediateReply(Exception):
    def __init__(self, payload: dict, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code


class ChatFlow:
    def __init__(self, request: Request, message: str):
        self.request = request
        self.message = message

    def store_ui_exchange(self, user_text: str, assistant_text: str, actions=None):
        history = self.request.session.get('gulf_ai_ui_history')
        if not isinstance(history, list):
            history = []
        user_text = clean_reply(user_text)
        assistant_text = clean_reply(assistant_text)
        if user_text:
            history.append({'type':'user','text':user_text,'actions':[]})
        if assistant_text:
            history.append({'type':'bot','text':assistant_text,'actions':actions if isinstance(actions,list) else []})
        self.request.session['gulf_ai_ui_history'] = history[-40:]

    def reply(self, reply: str, extra=None, actions=None):
        extra = extra if isinstance(extra, dict) else {}
        actions = actions if isinstance(actions, list) else []
        self.store_ui_exchange(self.message, reply, actions)
        log_context = dict(extra)
        if actions:
            log_context['actions'] = actions
        log_message(self.request, 'assistant', reply, 'deterministic', log_context, latency_ms(self.request))
        payload = {'success':True,'reply':clean_reply(reply),'build':BUILD}
        if extra:
            payload['context'] = extra
        if actions:
            payload['actions'] = actions
        raise ImmediateReply(payload)


def _clear_keys(session: dict, *keys: str):
    for key in keys:
        session.pop(key, None)


def _active_withdrawal(student_id: str):
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT id,status FROM sis_admission_retreat
            WHERE student_id=%s AND status IN (0,1)
            ORDER BY id DESC LIMIT 1
        """, (student_id,))
        return cur.fetchone()
    finally:
        cur.close(); conn.close()


async def _process_chat(request: Request, data: dict) -> dict:
    session = request.session
    action = str(data.get('action') or '').strip()

    if action == 'reset':
        close_current_conversation(request)
        for key in list(session.keys()):
            if key.startswith('gulf_ai_'):
                session.pop(key, None)
        session['gulf_ai_awaiting_name'] = 1
        session['gulf_ai_ui_history'] = [{'type':'bot','text':WELCOME,'actions':[]}]
        conversation_key(request)
        log_message(request, 'system', WELCOME, 'conversation_reset')
        return {'success':True,'reset':True,'build':BUILD}

    if action == 'history':
        history = session.get('gulf_ai_ui_history')
        return {'success':True,'history':history if isinstance(history,list) else [],'build':BUILD}

    message = str(data.get('message') or '').strip()
    if not message:
        return {'success':False,'error':'اكتب رسالة أول'}

    request.state.gulf_ai_log_started_at = time.perf_counter()
    request.state.gulf_ai_log_request_key = make_key('req')
    log_message(request, 'user', message, 'incoming', {'request_body': data})
    flow = ChatFlow(request, message)

    n = normalize(flow.message)
    if contains(n, 'تغيير الطالب') or contains(n, 'تغيير الرقم'):
        _clear_keys(session,
            'gulf_ai_student_id','gulf_ai_verified_student_id','gulf_ai_pending_student_id',
            'gulf_ai_pending_personal_message','gulf_ai_awaiting_verification','gulf_ai_verified_identity',
            'gulf_ai_pending_identity','gulf_ai_pending_applicant_message','gulf_ai_awaiting_applicant_verification',
            'gulf_ai_withdrawal_stage','gulf_ai_withdrawal_reason','gulf_ai_withdrawal_pending')
        flow.reply('تمام، أرسل الرقم الجامعي الجديد.')

    awaiting_name = bool(session.get('gulf_ai_awaiting_name'))
    visitor_name = str(session.get('gulf_ai_visitor_name') or '').strip()
    if not visitor_name:
        detected_name = extract_person_name(flow.message, awaiting_name)
        if not detected_name:
            session['gulf_ai_awaiting_name'] = 1
            if not is_greeting_only(flow.message) and not session.get('gulf_ai_pending_first_message'):
                session['gulf_ai_pending_first_message'] = flow.message
            flow.reply(WELCOME)
        session['gulf_ai_visitor_name'] = detected_name
        session['gulf_ai_visitor_gender'] = guess_gender_from_name(detected_name)
        session['gulf_ai_awaiting_name'] = 0
        visitor_name = detected_name
        visitor_gender = session['gulf_ai_visitor_gender']
        visitor_label = ('أستاذة ' + visitor_name) if visitor_gender == 'female' else (('أستاذ ' + visitor_name) if visitor_gender == 'male' else visitor_name)
        send_identity = 'أرسلي' if visitor_gender == 'female' else 'أرسل'
        send_student_id = 'أرسلي رقمك الجامعي' if visitor_gender == 'female' else 'أرسل رقمك الجامعي'
        if session.get('gulf_ai_pending_first_message'):
            first_message = session.pop('gulf_ai_pending_first_message')
            if is_applicant_identity_request(first_message):
                session['gulf_ai_pending_applicant_message'] = first_message
                flow.reply(f'أهلين {visitor_label}، الله يسعدك. {send_identity} رقم الهوية عشان أتحقق من طلبك.')
            if is_withdrawal_submission_request(first_message):
                session['gulf_ai_withdrawal_stage'] = 'awaiting_identity'
                session['gulf_ai_withdrawal_original_message'] = first_message
                flow.reply(f'أهلين {visitor_label}، {send_identity} رقم الهوية عشان أبحث عن تسجيلك وأبدأ طلب الانسحاب.')
            if is_personal_request(first_message) or extract_student_id(first_message):
                session['gulf_ai_pending_personal_message'] = first_message
                flow.reply(f'أهلين {visitor_label}، الله يسعدك. {send_student_id} عشان أتحقق لك.')
            flow.message = first_message
        else:
            flow.reply(f'أهلين {visitor_label}، الله يسعدك. كيف أقدر أخدمك؟')

    known_gender = str(session.get('gulf_ai_visitor_gender') or 'unknown')
    navigation = portal_navigation_reply(flow.message, known_gender)
    if navigation:
        flow.reply(navigation)
    calendar = academic_calendar_reply(flow.message)
    if calendar:
        flow.reply(calendar)
    if is_withdrawal_method_question(flow.message) and not is_withdrawal_submission_request(flow.message):
        flow.reply(withdrawal_method_reply())

    # Early withdrawal workflow: identity -> reason -> confirmation -> Nafath.
    withdrawal_stage = str(session.get('gulf_ai_withdrawal_stage') or '')
    withdrawal_submit = is_withdrawal_submission_request(flow.message)
    female = known_gender == 'female'
    if withdrawal_submit and not withdrawal_stage:
        _clear_keys(session,'gulf_ai_withdrawal_reason','gulf_ai_withdrawal_identity','gulf_ai_withdrawal_student_id','gulf_ai_withdrawal_pending')
        session['gulf_ai_withdrawal_stage'] = 'awaiting_identity'
        session['gulf_ai_withdrawal_original_message'] = flow.message
        flow.reply('أرسلي رقم الهوية عشان أبحث عن تسجيلك وأبدأ طلب الانسحاب.' if female else 'أرسل رقم الهوية عشان أبحث عن تسجيلك وأبدأ طلب الانسحاب.')

    if withdrawal_stage == 'awaiting_identity':
        if is_no_reply(flow.message):
            _clear_keys(session,'gulf_ai_withdrawal_stage','gulf_ai_withdrawal_original_message')
            flow.reply('تم، ألغيت الإجراء وما انرفع أي طلب.')
        identity = extract_national_id(flow.message)
        if not identity:
            flow.reply('أرسلي رقم الهوية المكوّن من 10 أرقام عشان أبحث عن تسجيلك.' if female else 'أرسل رقم الهوية المكوّن من 10 أرقام عشان أبحث عن تسجيلك.')
        app = find_applicant_basic(identity)
        student_id = re.sub(r'\D','',str(app.get('student_id') or '')) if app else ''
        if not app:
            flow.reply('ما لقيت طلب تسجيل مرتبط بالهوية. تأكدي من الرقم وأرسليه مرة ثانية.')
        if not student_id:
            flow.reply('لقيت طلب التسجيل، لكن ما صدر له رقم جامعي للحين؛ لذلك ما أقدر أنشئ طلب انسحاب أكاديمي عليه.')
        active = _active_withdrawal(student_id)
        if active:
            _clear_keys(session,'gulf_ai_withdrawal_stage','gulf_ai_withdrawal_original_message')
            flow.reply(f"عندك طلب انسحاب قائم برقم {int(active['id'])}، لذلك ما راح أنشئ طلباً مكرراً.")
        session['gulf_ai_withdrawal_identity'] = identity
        session['gulf_ai_withdrawal_student_id'] = student_id
        session['gulf_ai_withdrawal_stage'] = 'awaiting_reason'
        flow.reply('تم، لقيت تسجيلك. وش سبب الانسحاب؟')

    if withdrawal_stage == 'awaiting_reason':
        if is_no_reply(flow.message):
            _clear_keys(session,'gulf_ai_withdrawal_stage','gulf_ai_withdrawal_original_message','gulf_ai_withdrawal_identity','gulf_ai_withdrawal_student_id')
            flow.reply('تم، ألغيت الإجراء وما انرفع أي طلب.')
        reason = clean(flow.message)
        if len(reason) < 3:
            flow.reply('اكتبي سبب الانسحاب بشكل مختصر عشان أسجله في الطلب.' if female else 'اكتب سبب الانسحاب بشكل مختصر عشان أسجله في الطلب.')
        session['gulf_ai_withdrawal_reason'] = limit(reason,500)
        session['gulf_ai_withdrawal_stage'] = 'awaiting_confirmation'
        flow.reply(f"سبب الانسحاب: «{session['gulf_ai_withdrawal_reason']}».\n\nبعد تأكيدك بفتح لك تحقق نفاذ، وبعد نجاحه ينرفع الطلب رسمياً بحالة «بصدد الدراسة». أكمّل؟")

    if withdrawal_stage == 'awaiting_confirmation':
        if is_no_reply(flow.message):
            _clear_keys(session,'gulf_ai_withdrawal_stage','gulf_ai_withdrawal_reason','gulf_ai_withdrawal_original_message','gulf_ai_withdrawal_identity','gulf_ai_withdrawal_student_id')
            flow.reply('تم، ألغيت الإجراء وما انرفع أي طلب.')
        if not is_yes_reply(flow.message):
            flow.reply('إذا تبين أكمل اكتبي «نعم»، وإذا تراجعتِ اكتبي «إلغاء».' if female else 'إذا تبي أكمل اكتب «نعم»، وإذا تراجعت اكتب «إلغاء».')
        session['gulf_ai_withdrawal_stage'] = 'nafath_ready'
        flow.reply('تمام، اضغطي الزر تحت وكمّلي التحقق من تطبيق نفاذ. الطلب ما راح ينشأ إلا بعد نجاح التحقق.',
                   {'withdrawal_identity_collected':True}, [{'label':'تأكيد الهوية عبر نفاذ','url':'/withdrawal/start'}])

    if withdrawal_stage == 'nafath_ready':
        flow.reply('طلب التحقق جاهز. اضغطي الزر تحت، وبيظهر لك رقم تختارينه داخل تطبيق نفاذ.',
                   {'withdrawal_identity_collected':True}, [{'label':'تأكيد الهوية عبر نفاذ','url':'/withdrawal/start'}])

    if is_admission_registration_question(flow.message):
        flow.reply(admission_registration_reply(known_gender))
    if is_registration_method_question(flow.message) and not session.get('gulf_ai_verified_student_id') and not any(contains(normalize(flow.message),x) for x in ('مقفل','محجوب','عندي')):
        flow.reply(registration_method_reply(known_gender))

    normalized_flow = normalize(flow.message)
    does_not_know_id = any(contains(normalized_flow,x) for x in ('ماعرف رقمي الجامعي','ما اعرف رقمي الجامعي','ما ادري وش رقمي الجامعي','ما عندي الرقم الجامعي'))
    if does_not_know_id:
        _clear_keys(session,'gulf_ai_pending_personal_message','gulf_ai_pending_student_id','gulf_ai_student_id','gulf_ai_awaiting_verification')
        session['gulf_ai_pending_applicant_message'] = 'سجلت ووقعت العقد وما وصلتني رسالة الرقم الجامعي وبيانات الدخول'
        send_identity = 'أرسلي رقم الهوية' if known_gender=='female' else 'أرسل رقم الهوية'
        flow.reply(f'ما تحتاج تعرف رقمك الجامعي. {send_identity}، وأنا أبحث عن طلبك وأتحقق من الرقم وحالة تجهيز الرسالة.')

    declares_not_registered = any(contains(normalized_flow,x) for x in (
        'ما سجلت عندكم','ماسجلت عندكم','ماني طالبه عندكم','ماني طالب عندكم','مو طالبه عندكم','مو طالب عندكم',
        'ما عندي رقم جامعي','لسا ما سجلت','لسا ماسجلت','للحين ما سجلت','للحين ماسجلت'))
    if declares_not_registered and not session.get('gulf_ai_verified_student_id'):
        _clear_keys(session,'gulf_ai_pending_personal_message','gulf_ai_pending_student_id','gulf_ai_student_id','gulf_ai_awaiting_verification')

    if session.get('gulf_ai_pending_personal_message') and not session.get('gulf_ai_awaiting_verification') and not extract_student_id(flow.message):
        _clear_keys(session,'gulf_ai_pending_personal_message','gulf_ai_pending_student_id','gulf_ai_student_id')
    if session.get('gulf_ai_pending_applicant_message') and not session.get('gulf_ai_awaiting_applicant_verification') and not extract_national_id(flow.message):
        _clear_keys(session,'gulf_ai_pending_applicant_message','gulf_ai_pending_identity')
    if session.get('gulf_ai_awaiting_verification') and not extract_four_digits(flow.message) and len(normalized_flow)>6:
        _clear_keys(session,'gulf_ai_awaiting_verification','gulf_ai_pending_personal_message','gulf_ai_pending_student_id','gulf_ai_student_id')
    if session.get('gulf_ai_awaiting_applicant_verification') and not extract_four_digits(flow.message) and len(normalized_flow)>6:
        _clear_keys(session,'gulf_ai_awaiting_applicant_verification','gulf_ai_pending_applicant_message','gulf_ai_pending_identity')

    verified_applicant_followup = bool(session.get('gulf_ai_verified_identity')) and (
        is_applicant_access_followup(flow.message) or
        (session.get('gulf_ai_last_applicant_topic') and normalize(flow.message) in {'كيف','طيب كيف','وين','طيب وين'})
    )
    if (
        not session.get('gulf_ai_pending_personal_message') and not session.get('gulf_ai_pending_applicant_message')
        and not session.get('gulf_ai_withdrawal_stage') and not verified_applicant_followup
        and not extract_student_id(flow.message) and not extract_national_id(flow.message)
        and not is_personal_request(flow.message) and not is_applicant_identity_request(flow.message) and not is_greeting_only(flow.message)
    ):
        semantic = await classify_request_intent(request, flow.message)
        if semantic == 'OUT_OF_SCOPE':
            q = 'وش حابة تعرفين عن الكلية؟' if known_gender=='female' else 'وش حاب تعرف عن الكلية؟'
            flow.reply('أقدر أساعدك بكل ما يخص كلية الخليج وبرامجها والقبول والتسجيل والخدمات الطلابية. '+q)
        if semantic == 'STUDENT_PERSONAL' and not session.get('gulf_ai_verified_student_id'):
            session['gulf_ai_pending_personal_message'] = flow.message
            flow.reply(('أرسلي رقمك الجامعي' if known_gender=='female' else 'أرسل رقمك الجامعي')+' عشان أفتح سجلك وأعطيك الإجابة الدقيقة.')
        if semantic == 'APPLICANT_PERSONAL' and not session.get('gulf_ai_verified_identity'):
            session['gulf_ai_pending_applicant_message'] = flow.message
            flow.reply(('أرسلي رقم الهوية' if known_gender=='female' else 'أرسل رقم الهوية')+' عشان أتحقق من طلبك وأعطيك حالته الدقيقة.')

    incoming_identity = extract_national_id(flow.message)
    verified_applicant_followup = bool(session.get('gulf_ai_verified_identity')) and (
        is_applicant_access_followup(flow.message) or
        (session.get('gulf_ai_last_applicant_topic') and normalize(flow.message) in {'كيف','طيب كيف','وين','طيب وين'})
    )
    applicant_request = is_applicant_identity_request(flow.message) or bool(session.get('gulf_ai_pending_applicant_message')) or bool(session.get('gulf_ai_awaiting_applicant_verification')) or verified_applicant_followup or bool(incoming_identity)
    if applicant_request:
        identity = incoming_identity or str(session.get('gulf_ai_pending_identity') or '')
        if session.get('gulf_ai_awaiting_applicant_verification'):
            four = extract_four_digits(flow.message)
            pending_identity = str(session.get('gulf_ai_pending_identity') or '')
            applicant = find_applicant_basic(pending_identity)
            mobile = re.sub(r'\D','',str(applicant.get('mobile') or '')) if applicant else ''
            expected = mobile[-4:] if len(mobile)>=4 else ''
            if not four or not expected or four != expected:
                flow.reply('الأرقام ما تطابقت مع رقم الجوال المسجل. تأكد من آخر أربعة أرقام وحاول مرة ثانية.')
            session['gulf_ai_verified_identity'] = pending_identity
            session['gulf_ai_awaiting_applicant_verification'] = 0
            identity = pending_identity
            if session.get('gulf_ai_pending_applicant_message'):
                flow.message = session.pop('gulf_ai_pending_applicant_message')
        if not identity:
            session['gulf_ai_pending_applicant_message'] = flow.message
            flow.reply(('أرسلي رقم الهوية' if known_gender=='female' else 'أرسل رقم الهوية')+' عشان أبحث عن طلب التسجيل وأتحقق من الرقم الجامعي والرسالة.')
        applicant = find_applicant_basic(identity)
        if not applicant:
            flow.reply('ما لقيت طلب تسجيل مرتبط برقم الهوية. تأكد من الرقم وأرسله مرة ثانية.')
        if not session.get('gulf_ai_verified_identity') or session.get('gulf_ai_verified_identity') != identity:
            session['gulf_ai_pending_identity'] = identity
            if not session.get('gulf_ai_pending_applicant_message'):
                session['gulf_ai_pending_applicant_message'] = flow.message
            session['gulf_ai_awaiting_applicant_verification'] = 1
            flow.reply('لقيت طلبك. للتأكد قبل عرض المعلومات، أرسل آخر أربعة أرقام من رقم الجوال المسجل.')
        applicant_context = build_applicant_context(identity)
        if verified_applicant_followup and normalize(flow.message) in {'كيف','طيب كيف','وين','طيب وين'}:
            flow.message = 'كيف ادخل نظام معلومات الطالب وما وصلتني الرسالة النصية وبيانات الدخول'
        applicant_reply = applicant_direct_reply(flow.message, applicant_context, known_gender)
        if applicant_reply:
            session['gulf_ai_last_applicant_topic'] = 'student_access'
            flow.reply(applicant_reply, {'applicant_verified':True,'application_id':applicant_context['application_id']}, applicant_reply_actions(applicant_context))

    withdrawal_submission = is_withdrawal_submission_request(flow.message)
    if withdrawal_submission and not session.get('gulf_ai_verified_student_id') and session.get('gulf_ai_verified_identity'):
        linked = find_applicant_basic(str(session['gulf_ai_verified_identity']))
        linked_id = re.sub(r'\D','',str(linked.get('student_id') or '')) if linked else ''
        if linked_id:
            session['gulf_ai_verified_student_id'] = linked_id
            session['gulf_ai_student_id'] = linked_id

    incoming_student_id = extract_student_id(flow.message)
    personal_request = is_personal_request(flow.message) or withdrawal_submission or bool(session.get('gulf_ai_pending_personal_message')) or bool(incoming_student_id)
    if personal_request:
        student_id = incoming_student_id or str(session.get('gulf_ai_student_id') or '')
        if session.get('gulf_ai_awaiting_verification'):
            four = extract_four_digits(flow.message)
            pending_id = str(session.get('gulf_ai_pending_student_id') or '')
            student = find_student_basic(pending_id)
            identity = re.sub(r'\D','',str(student.get('iqama') or '')) if student else ''
            expected = identity[-4:] if len(identity)>=4 else ''
            if not four or not expected or four != expected:
                flow.reply('الأرقام ما تطابقت مع بيانات الطالب. تأكد من آخر أربعة أرقام من الهوية وحاول مرة ثانية.')
            session['gulf_ai_verified_student_id'] = pending_id
            session['gulf_ai_student_id'] = pending_id
            session['gulf_ai_awaiting_verification'] = 0
            student_id = pending_id
            if session.get('gulf_ai_pending_personal_message'):
                flow.message = session.pop('gulf_ai_pending_personal_message')
        if not student_id:
            session['gulf_ai_pending_personal_message'] = flow.message
            flow.reply(f'تمام يا {visitor_name}، أرسل رقمك الجامعي عشان أتحقق لك.')
        student = find_student_basic(student_id)
        if not student:
            flow.reply('ما لقيت طالب بهذا الرقم. تأكد من الرقم الجامعي وأرسله مرة ثانية.')
        if not session.get('gulf_ai_verified_student_id') or session.get('gulf_ai_verified_student_id') != student_id:
            session['gulf_ai_pending_student_id'] = student_id
            if not session.get('gulf_ai_pending_personal_message'):
                session['gulf_ai_pending_personal_message'] = flow.message
            session['gulf_ai_awaiting_verification'] = 1
            flow.reply('لقيت بياناتك. للتأكد من الهوية قبل ما أعرض أي معلومات، أرسل آخر أربعة أرقام من رقم الهوية.')
        session['gulf_ai_student_id'] = student_id

    student_context = build_student_context(str(session['gulf_ai_verified_student_id'])) if session.get('gulf_ai_verified_student_id') else {}
    withdrawal_submission = is_withdrawal_submission_request(flow.message)
    if student_context:
        is_female = student_context.get('gender') == 'أنثى'
        stage = str(session.get('gulf_ai_withdrawal_stage') or '')
        if stage == 'awaiting_reason':
            reason = clean(flow.message)
            if len(reason)<3:
                flow.reply(('اكتبي' if is_female else 'اكتب')+' لي سبب الانسحاب بشكل مختصر عشان يظهر صحيح في الطلب.')
            session['gulf_ai_withdrawal_reason'] = limit(reason,500)
            session['gulf_ai_withdrawal_stage'] = 'awaiting_confirmation'
            flow.reply(f"تمام، سبب الانسحاب المسجل: «{session['gulf_ai_withdrawal_reason']}».\n\nبعد تأكيدك بحولك إلى نفاذ لإثبات الهوية، وبعد نجاح التحقق ينرفع الطلب رسميًا بحالة «بصدد الدراسة». مجرد رفع الطلب ما يعني تنفيذ الانسحاب، ولا تُحذف مقرراتك إلا بعد اعتماد الإدارة. أكمّل؟")
        if stage == 'awaiting_confirmation':
            if is_no_reply(flow.message):
                _clear_keys(session,'gulf_ai_withdrawal_stage','gulf_ai_withdrawal_reason')
                flow.reply('تم، ما رفعت أي طلب. إذا احتجت شيء ثاني أنا معك.')
            if not is_yes_reply(flow.message):
                flow.reply('إذا تبين أكمل اكتبي «نعم»، وإذا تراجعتِ اكتبي «إلغاء».' if is_female else 'إذا تبي أكمل اكتب «نعم»، وإذا تراجعت اكتب «إلغاء».')
            session['gulf_ai_withdrawal_stage'] = 'nafath_ready'
            flow.reply('تمام. '+('اضغطي' if is_female else 'اضغط')+' الزر و'+('كمّلي' if is_female else 'كمّل')+' التحقق من تطبيق نفاذ. ما راح ينشأ الطلب إلا بعد نجاح التحقق.',
                       {'student_verified':True}, [{'label':'تأكيد الهوية عبر نفاذ','url':'/withdrawal/start'}])
        if withdrawal_submission:
            existing = student_context.get('withdrawal') or {}
            if 'request_id' in existing and int(existing.get('status_code') or 0) in (0,1):
                flow.reply(f"عندك طلب انسحاب قائم برقم {int(existing['request_id'])}، وحالته: {existing['status']}. ما راح أنشئ طلبًا مكررًا.")
            session['gulf_ai_withdrawal_stage'] = 'awaiting_reason'
            session.pop('gulf_ai_withdrawal_reason',None)
            flow.reply('أقدر أرفع الطلب لك من هنا. قبل نبدأ، الانسحاب ما يتنفذ مباشرة؛ يمر بالمراجعة وتُدرس أهلية الاسترداد حسب العقد وتاريخ الطلب. وش سبب الانسحاب؟')

    if personal_request and student_context:
        direct = personal_direct_reply(flow.message, student_context)
        if direct:
            flow.reply(direct, {'student_verified':True,'student_id':session['gulf_ai_verified_student_id']})

    try:
        programs = load_programs()
    except Exception as exc:
        log_message(request,'error','تعذر قراءة البرامج من قاعدة البيانات: '+str(exc),'database_error',{},latency_ms(request))
        return {'success':False,'error':'تعذر قراءة البرامج','debug':str(exc)}

    matched = match_program(flow.message, programs, session.get('gulf_ai_program_id'))
    if matched:
        session['gulf_ai_program_id'] = int(matched['id'])
    requested_level = detect_level(flow.message)
    if requested_level is not None:
        session['gulf_ai_level'] = requested_level
    current_level = int(session.get('gulf_ai_level') or 0)
    plan_data = []
    if needs_plan(flow.message, session) and matched and int(matched.get('study_plan_id') or 0)>0:
        plan_data = get_plan_courses(int(matched['study_plan_id']))
        session['gulf_ai_last_context'] = 'study_plan'

    nm = normalize(flow.message)
    asks_language = any(contains(nm,x) for x in ('لغه الدراسه','لغه البرنامج','بالعربي','باللغه العربيه','بالانجليزي','باللغه الانجليزيه','يدرس بالانجليزي','تدرس بالانجليزي'))
    if asks_language:
        flow.reply('الدراسة في جميع برامج كلية الخليج باللغة العربية.')
    asks_training = any(contains(nm,x) for x in ('تدريب','تعاوني','ميداني'))
    if asks_training and matched and plan_data:
        training = training_course_from_plan(plan_data)
        if training:
            label = str(training.get('name') or '').strip() or 'التدريب التعاوني'
            if str(training.get('code') or '').strip(): label += ' ('+str(training['code']).strip()+')'
            reply = 'إيه، خطة '+matched['name']+' فيها مقرر '+label
            if float(training.get('credits') or 0)>0: reply += ' بعدد '+money(training['credits'])+' ساعات'
            if int(training.get('level') or 0)>0: reply += ' في المستوى '+str(training['level'])
            flow.reply(reply+'.')
        flow.reply('لا، خطة '+matched['name']+' ما فيها مقرر تدريب تعاوني.')

    knowledge = get_relevant_knowledge(flow.message,5)
    official = get_official_knowledge(flow.message,6)
    program_list = program_list_for_ai(programs)
    current_program = dict(matched) if matched else {}
    if current_program and float(current_program.get('price') or 0)>0:
        current_program['price_display'] = money(current_program['price'])+' ريال'
    history = session.get('gulf_ai_history')
    if not isinstance(history,list): history=[]; session['gulf_ai_history']=history
    visitor_gender_ai = str(session.get('gulf_ai_visitor_gender') or 'unknown')
    if student_context.get('gender')=='أنثى': visitor_gender_ai='female'
    elif student_context.get('gender')=='ذكر': visitor_gender_ai='male'
    instructions = build_instructions(
        visitor_name=clean(visitor_name), visitor_gender=visitor_gender_ai,
        program_list=program_list, current_program=current_program,
        official_knowledge=official, knowledge=knowledge, plan_data=plan_data,
        student_context=student_context, current_level=current_level,
    )
    try:
        reply, _ = await generate_final_answer(request,message=flow.message,history=history,instructions=instructions)
    except Exception as exc:
        log_message(request,'error','تعذر الاتصال أو قراءة رد خدمة OpenAI: '+str(exc),'openai_error',{},latency_ms(request))
        return {'success':False,'error':'تعذر الاتصال بالخدمة حالياً','debug':str(exc)}

    history.append({'role':'user','content':flow.message})
    history.append({'role':'assistant','content':reply})
    session['gulf_ai_history'] = history[-8:]
    flow.store_ui_exchange(flow.message, reply, [])
    log_message(request,'assistant',reply,'openai',{
        'program_id': int(matched['id']) if matched else None,
        'program_name': matched['name'] if matched else None,
        'level': current_level,
    }, latency_ms(request))
    return {
        'success':True,'reply':reply,'build':BUILD,
        'context':{'program_id':int(matched['id']) if matched else None,'program_name':matched['name'] if matched else None,'level':current_level}
    }


@router.post('/chat')
async def chat(body: ChatRequest, request: Request):
    data = body.model_dump(exclude_none=True)

    try:
        payload = await _process_chat(request, data)
        return JSONResponse(payload)

    except ImmediateReply as result:
        return JSONResponse(
            result.payload,
            status_code=result.status_code
        )