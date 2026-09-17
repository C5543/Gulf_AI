import json
import time
from pathlib import Path

import httpx

from config import OPENAI_API_KEY, OPENAI_MODEL
from services.chat_logging import log_api_call
from services.text_utils import limit, remove_markdown

OPENAI_RESPONSES_URL = 'https://api.openai.com/v1/responses'
PROMPT_PATH = Path(__file__).resolve().parent.parent / 'data' / 'system_prompt.txt'
PROMPT_TEMPLATE = PROMPT_PATH.read_text(encoding='utf-8')


def extract_openai_text(result: dict) -> str:
    reply = []
    for output in result.get('output') or []:
        if output.get('type') != 'message':
            continue
        for content in output.get('content') or []:
            if content.get('type') == 'output_text' and content.get('text') is not None:
                reply.append(str(content['text']))
    return ''.join(reply).strip()


def build_instructions(*, visitor_name: str, visitor_gender: str, program_list: list,
                       current_program: dict, official_knowledge: list, knowledge: list,
                       plan_data: list, student_context: dict, current_level: int) -> str:
    values = {
        'VISITOR_NAME_FOR_AI': visitor_name,
        'VISITOR_GENDER_FOR_AI': visitor_gender,
        'PROGRAM_LIST_JSON': json.dumps(program_list, ensure_ascii=False, separators=(',', ':'), default=str),
        'CURRENT_PROGRAM_JSON': json.dumps(current_program, ensure_ascii=False, separators=(',', ':'), default=str),
        'OFFICIAL_KNOWLEDGE_JSON': json.dumps(official_knowledge, ensure_ascii=False, separators=(',', ':'), default=str),
        'KNOWLEDGE_JSON': json.dumps(knowledge, ensure_ascii=False, separators=(',', ':'), default=str),
        'PLAN_JSON': json.dumps(plan_data, ensure_ascii=False, separators=(',', ':'), default=str),
        'STUDENT_CONTEXT_JSON': json.dumps(student_context, ensure_ascii=False, separators=(',', ':'), default=str),
        'CURRENT_LEVEL': str(current_level or 0),
    }
    prompt = PROMPT_TEMPLATE
    for key, value in values.items():
        prompt = prompt.replace(f'@@{key}@@', value)
    return prompt


async def classify_request_intent(request, message: str) -> str:
    if not OPENAI_API_KEY:
        return 'GENERAL'
    payload = {
        'model': OPENAI_MODEL,
        'instructions': (
            'صنّف الرسالة إلى رمز واحد فقط دون شرح:\n'
            'OUT_OF_SCOPE إذا كان السؤال لا يتعلق بكلية الخليج أو برامجها أو القبول والتسجيل أو الدراسة أو خدمات الطلاب أو الأنظمة الأكاديمية والمالية التابعة لها. أمثلة: المشاهير والفن والرياضة والطبخ والأخبار والمعلومات العامة. سؤال «تعرف راشد الماجد؟» هو OUT_OF_SCOPE.\n'
            'STUDENT_PERSONAL فقط إذا كانت الإجابة تحتاج قراءة سجل موجود فعلًا في نظام معلومات الطالب: مقرراته الحالية أو المتوقعة أو المتبقية أو الراسب فيها، الباكج، الجدول، الدرجات، المعدل، دفعاته والمتبقي، سبب إغلاق التسجيل، العقد، الانسحاب، الاسترداد، تخصصه المسجل، الرقم الجامعي، الشهادة أو حالة طلب شخصي.\n'
            'APPLICANT_PERSONAL إذا كانت عن متقدم قبل صدور الرقم الجامعي: حالة القبول أو السداد الأول أو وصول العقد أو بيانات الدخول وتحتاج الهوية.\n'
            'GENERAL إذا كانت سياسة أو شرحاً عاماً أو برامج أو رسوماً أو قبولاً أو ترشيح برنامج مناسب بناءً على المؤهل أو التخصص أو الاهتمامات، أو مقارنة هدفها معرفة مميزات كلية الخليج. سؤال مثل «أنا بكالوريوس هندسة برمجيات، وش يناسبني؟» هو GENERAL ولا يحتاج رقمًا جامعيًا.\n'
            'لا تعتبر كلمة «تخصصي» وحدها طلباً لسجل الطالب؛ قد يكون المستخدم يعرّف بمؤهله ليطلب توصية. عبارات مقرراتي ومعدلي وفلوسي وعقدي تدل على سجل شخصي. أخرج فقط OUT_OF_SCOPE أو STUDENT_PERSONAL أو APPLICANT_PERSONAL أو GENERAL.'
        ),
        'input': [{'role': 'user', 'content': limit(message, 700)}],
        'max_output_tokens': 32,
        'store': False,
    }
    started = time.perf_counter(); error_text = ''; status = 0; result = {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=3.0)) as client:
            response = await client.post(
                OPENAI_RESPONSES_URL,
                headers={'Content-Type':'application/json','Authorization':f'Bearer {OPENAI_API_KEY}'},
                json=payload,
            )
        status = response.status_code
        try:
            result = response.json()
        except ValueError:
            result = {'raw': response.text}
    except Exception as exc:
        error_text = str(exc)
    log_api_call(request, 'intent_classifier', OPENAI_MODEL, payload, result, status, error_text, started)
    if error_text or status < 200 or status >= 300:
        return 'GENERAL'
    text = extract_openai_text(result).upper()
    if 'OUT_OF_SCOPE' in text:
        return 'OUT_OF_SCOPE'
    if 'APPLICANT_PERSONAL' in text:
        return 'APPLICANT_PERSONAL'
    if 'STUDENT_PERSONAL' in text:
        return 'STUDENT_PERSONAL'
    return 'GENERAL'


async def generate_final_answer(request, *, message: str, history: list, instructions: str) -> tuple[str, dict]:
    if not OPENAI_API_KEY:
        raise RuntimeError('OPENAI_API_KEY is not configured')
    input_items = []
    for item in history[-6:]:
        role = item.get('role')
        content = item.get('content')
        if role not in ('user','assistant') or content is None:
            continue
        input_items.append({'role': role, 'content': limit(content, 2500)})
    input_items.append({'role':'user','content':message})
    payload = {'model': OPENAI_MODEL, 'instructions': instructions, 'input': input_items}
    started = time.perf_counter(); error_text = ''; status = 0; result = {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            response = await client.post(
                OPENAI_RESPONSES_URL,
                headers={'Content-Type':'application/json','Authorization':f'Bearer {OPENAI_API_KEY}'},
                json=payload,
            )
        status = response.status_code
        try:
            result = response.json()
        except ValueError:
            result = {'raw': response.text}
    except Exception as exc:
        error_text = str(exc)
    log_api_call(request, 'final_answer', OPENAI_MODEL, payload, result, status, error_text, started)
    if error_text:
        raise RuntimeError(error_text)
    if status < 200 or status >= 300:
        raise RuntimeError(f'OpenAI HTTP {status}: {result}')
    reply = remove_markdown(extract_openai_text(result))
    if not reply:
        raise RuntimeError('OpenAI returned no readable output text')
    return reply, result
