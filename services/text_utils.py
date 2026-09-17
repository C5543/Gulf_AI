import html
import re
from typing import Any

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
IGNORE_WORDS = {
    'في','من','على','عن','الى','الي','هل','وش','ايش','كيف','كم','ابي','ابغى','ابغا','طيب','بس',
    'هو','هي','هذا','هذه','ذا','ذي','عندكم','عندكو','عندي','لي','له','لها'
}


def clean(text: Any) -> str:
    text = '' if text is None else str(text)
    text = re.sub(r'<[^>]*>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text, flags=re.UNICODE)
    return text.strip()


def limit(text: Any, length: int = 1000) -> str:
    value = clean(text)
    return value if len(value) <= length else value[:length] + '...'


def contains(text: Any, word: Any) -> bool:
    word = '' if word is None else str(word)
    return bool(word) and word.casefold() in ('' if text is None else str(text)).casefold()


def normalize(text: Any) -> str:
    value = clean(text).lower()
    value = value.translate(str.maketrans({
        'أ':'ا','إ':'ا','آ':'ا','ى':'ي','ؤ':'و','ئ':'ي','ة':'ه','ـ':''
    }))
    value = re.sub(r'[^\u0600-\u06FFA-Za-z0-9\s]', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def words(text: Any) -> list[str]:
    result: list[str] = []
    for word in normalize(text).split():
        if not word or word in IGNORE_WORDS or len(word) < 2:
            continue
        if word not in result:
            result.append(word)
    return result


def money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return f'{number:,.0f}' if number.is_integer() else f'{number:,.2f}'


def remove_markdown(text: Any) -> str:
    value = str(text or '').strip()
    for token in ('**', '__', '###', '##', '#'):
        value = value.replace(token, '')
    value = re.sub(r'^\s*[-*]\s+', '- ', value, flags=re.MULTILINE)
    return value.strip()


def clean_reply(text: Any) -> str:
    value = re.sub(r'<[^>]*>', '', str(text or ''))
    value = html.unescape(value).replace('\r\n', '\n').replace('\r', '\n')
    lines = [re.sub(r'[\t ]+', ' ', line).strip() for line in value.split('\n')]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def extract_student_id(text: Any) -> str:
    value = str(text or '').translate(ARABIC_DIGITS)
    match = re.search(r'(?<!\d)(\d{7,9})(?!\d)', value)
    return match.group(1) if match else ''


def extract_national_id(text: Any) -> str:
    value = str(text or '').translate(ARABIC_DIGITS)
    match = re.search(r'(?<!\d)([12]\d{9})(?!\d)', value)
    return match.group(1) if match else ''


def extract_four_digits(text: Any) -> str:
    value = str(text or '').translate(ARABIC_DIGITS)
    match = re.search(r'(?<!\d)(\d{4})(?!\d)', value)
    return match.group(1) if match else ''


def extract_person_name(text: Any, awaiting: bool = False) -> str:
    value = clean(text)
    match = re.search(r'(?:اسمي|انا|أنا|معك)\s+([\u0600-\u06FF]+(?:\s+[\u0600-\u06FF]+){0,2})', value)
    if match:
        candidate = match.group(1).strip()
        candidate_n = normalize(candidate)
        for invalid in ('ابي','ابغى','اريد','احتاج','اعرف','وش','كيف','هل','انسحاب','تسجيل','معدل'):
            if contains(candidate_n, normalize(invalid)):
                return ''
        return candidate

    if awaiting and re.fullmatch(r'[\u0600-\u06FF]+(?:\s+[\u0600-\u06FF]+){0,3}', value) and len(value) <= 50:
        not_name = (
            'ابي','ابغى','ابغا','اريد','احتاج','اعرف','وش','ايش','كيف','هل','وين','متى','كم','ليش',
            'انسحاب','استرداد','تسجيل','مقررات','رسوم','برنامج','دبلوم','عقد','سداد','معدل','حاله','حالة'
        )
        normalized = normalize(value)
        if not any(contains(normalized, normalize(w)) for w in not_name):
            return value
    return ''


def guess_gender_from_name(name: Any) -> str:
    first = (normalize(name).split() or [''])[0]
    female_names = {
        'شوق','نوره','ساره','ريم','مها','هدي','عبير','منال','امل','فاطمه','عايشه','مريم','روان','رهف','جود','لمي',
        'هاجر','اروي','حنان','وفاء','خلود','دلال','العنود','موضي','غلا','شهد','دانا','ليان','لينا','رنا','رانيا','ياسمين',
        'الجوهره','هيا','بدور','بشاير','نجود','نجلاء','ابتسام'
    }
    return 'female' if first in female_names else 'unknown'


def is_greeting_only(text: Any) -> bool:
    return normalize(text) in {'هلا','هلا والله','السلام عليكم','سلام','مرحبا','صباح الخير','مساء الخير'}


def is_yes_reply(text: Any) -> bool:
    return normalize(text) in {'اي','ايه','ايوه','نعم','اكيد','تمام','كملي','كمل','موافق','موافقه','ابدئي','ابدا'}


def is_no_reply(text: Any) -> bool:
    return normalize(text) in {'لا','لا خلاص','الغاء','الغي','وقف','مو موافق','مو موافقه'}


def is_withdrawal_method_question(text: Any) -> bool:
    n = normalize(text)
    return any(contains(n, normalize(p)) for p in (
        'اليه الانسحاب','الية الانسحاب','طريقه الانسحاب','كيف انسحب','كيف اقدم انسحاب',
        'كيف اقدم طلب انسحاب','وش خطوات الانسحاب','وين اقدم الانسحاب'
    ))


def withdrawal_method_reply() -> str:
    return 'تقدر تقدم الطلب من نظام معلومات الطالب، أو أرفعه لك من هنا بعد التحقق عبر نفاذ. إذا تبي أبدأ معك الآن قل: أبي أقدم طلب انسحاب.'


def is_registration_method_question(text: Any) -> bool:
    n = normalize(text)
    return any(contains(n, p) for p in (
        'كيف اسجل مقررات','ابي اسجل مقررات جديده','ابغى اسجل مقررات جديده','اليه تسجيل المقررات','طريقه تسجيل المقررات'
    ))


def is_admission_registration_question(text: Any) -> bool:
    n = normalize(text)
    if any(contains(n, p) for p in ('مقرر','مقررات','باكج','بكج')):
        return False
    return any(contains(n, normalize(p)) for p in (
        'كيف اسجل','كيف اقدم','طريقه التسجيل','خطوات التسجيل','اليه التسجيل','الية التسجيل','وش طريقه التقديم',
        'ابي اسجل','ابغى اسجل','ودي اسجل','ابي اسجل بالكلية','ابغى اسجل بالكلية','ابي اكمل التسجيل',
        'ابغى اكمل التسجيل','اكمل تسجيلي','رابط التسجيل'
    ))


def admission_registration_reply(gender: str = 'unknown') -> str:
    if gender == 'female':
        return 'تدخلين بوابة القبول وتختارين نوع الدبلوم والبرنامج، ثم تضغطين «تسجيل الآن» وتسجلين الدخول عبر النفاذ الوطني. بعدها تكملين بيانات التسجيل والتحقق من البريد والمؤهل، وعند تأكيد التسجيل يحولك النظام إلى بوابة الدفع. بعد إتمام السداد توقعين العقد إلكترونياً، وبعد توقيع العقد يصدر رقمك الجامعي مباشرة. رابط التسجيل: https://reg.gulf.edu.sa/diploma.php'
    if gender == 'male':
        return 'تدخل بوابة القبول وتختار نوع الدبلوم والبرنامج، ثم تضغط «تسجيل الآن» وتسجل الدخول عبر النفاذ الوطني. بعدها تكمل بيانات التسجيل والتحقق من البريد والمؤهل، وعند تأكيد التسجيل يحولك النظام إلى بوابة الدفع. بعد إتمام السداد توقع العقد إلكترونياً، وبعد توقيع العقد يصدر رقمك الجامعي مباشرة. رابط التسجيل: https://reg.gulf.edu.sa/diploma.php'
    return 'يبدأ التسجيل من بوابة القبول باختيار نوع الدبلوم والبرنامج، ثم الضغط على «تسجيل الآن» والدخول عبر النفاذ الوطني. بعد ذلك تُستكمل بيانات التسجيل والتحقق من البريد والمؤهل، وعند تأكيد التسجيل يحوّل النظام إلى بوابة الدفع. بعد إتمام السداد يتم توقيع العقد إلكترونياً، ثم يصدر الرقم الجامعي مباشرة. رابط التسجيل: https://reg.gulf.edu.sa/diploma.php'


def registration_method_reply(gender: str = 'unknown') -> str:
    enter = 'ادخلي' if gender == 'female' else ('ادخل' if gender == 'male' else 'يتم الدخول إلى')
    press = 'اضغطي' if gender == 'female' else ('اضغط' if gender == 'male' else 'يتم الضغط على')
    return ('إذا هذا أول مستوى، المقررات تنزل تلقائياً بعد اكتمال التسجيل وإصدار الرقم الجامعي. أما إذا مو أول مستوى، '
            'فخلال فترة التسجيل وبعد اكتمال المبلغ المطلوب وفتح الحالة المالية، ' + enter +
            ' صفحة تسجيل المقررات؛ بيظهر باكج المستوى الحالي حسب الخطة والشعب المطروحة، وبعدها ' + press +
            ' «تسجيل الباكج» والتأكيد، ويسجل النظام كل المقررات المتاحة في الباكج.')


def portal_navigation_reply(text: Any, gender: str = 'unknown') -> str:
    n = normalize(text)
    open_word = 'افتحي' if gender == 'female' else 'افتح'
    choose = 'اختاري' if gender == 'female' else 'اختر'
    press = 'اضغطي' if gender == 'female' else 'اضغط'
    complete = 'كمّلي' if gender == 'female' else 'كمّل'
    if contains(n, 'دخول الطالب') or (contains(n, 'نظام معلومات الطالب') and (contains(n, 'كيف ادخل') or contains(n, 'وين ادخل'))):
        return 'دخول الطالب إلى نظام معلومات الطالب من الرابط: https://sisd.gulf.edu.sa/er'
    if (contains(n, 'احول') or contains(n, 'تحويل')) and contains(n, 'قسم'):
        return f'من نظام معلومات الطالب، {open_word} قائمة «الطلبات»، ثم {choose} «التحويل من قسم إلى قسم آخر»، وبعدها {press} «تقديم طلب» و{complete} البيانات المطلوبة.'
    if (contains(n, 'احول') or contains(n, 'تحويل')) and contains(n, 'مسار'):
        return f'من نظام معلومات الطالب، {open_word} قائمة «الطلبات»، ثم {choose} «التحويل من مسار إلى مسار آخر»، وبعدها {press} «تقديم طلب» و{complete} البيانات المطلوبة.'
    if contains(n, 'كيف اسجل مقررات الرسوب') or contains(n, 'تسجيل مقرر راسب'):
        action = 'حددي المقرر وكمّلي' if gender == 'female' else 'حدد المقرر وكمّل'
        return f'من نظام معلومات الطالب، {open_word} «التسجيل الإلكتروني»، ثم {choose} «تسجيل مقررات الرسوب». {action} الدفع؛ رسوم كل مقرر 1,000 ريال، والحد الأعلى 3 مقررات في الفصل.'
    if contains(n, 'المقررات المتبقيه') and (contains(n, 'وين') or contains(n, 'كيف')):
        return f'من نظام معلومات الطالب، {open_word} «السجل الأكاديمي»، ثم {choose} «المقررات المتبقية».'
    if contains(n, 'السجل الاكاديمي') and (contains(n, 'وين') or contains(n, 'كيف')):
        return f'من القائمة الرئيسية في نظام معلومات الطالب، {open_word} «السجل الأكاديمي»، ثم {choose} «السجل الأكاديمي».'
    if (contains(n, 'درجاتي') or contains(n, 'تقديراتي')) and (contains(n, 'وين') or contains(n, 'كيف')):
        return f'من نظام معلومات الطالب، {open_word} «السجل الأكاديمي»، ثم {choose} «الدرجات والتقديرات».'
    if contains(n, 'مقرراتي المسجله') and (contains(n, 'وين') or contains(n, 'كيف')):
        return f'من نظام معلومات الطالب، {open_word} «التسجيل الإلكتروني»، ثم {choose} «عرض المقررات المسجلة».'
    if contains(n, 'جدولي الدراسي') and (contains(n, 'وين') or contains(n, 'كيف')):
        return f'من نظام معلومات الطالب، {open_word} «التسجيل الإلكتروني»، ثم {choose} «الجدول الدراسي».'
    if (contains(n, 'انسحب من الكليه') or contains(n, 'طلب انسحاب من الكليه')) and any(contains(n, x) for x in ('كيف','وين','من وين','طريقه')):
        return f'من نظام معلومات الطالب، {open_word} قائمة «الطلبات»، ثم {choose} «طلب انسحاب من الكلية» و{press} «تقديم طلب». وإذا تبي يرفعه المساعد لك، قل: أبي أقدم طلب انسحاب.'
    return ''


def academic_calendar_reply(text: Any) -> str:
    n = normalize(text)
    if contains(n, 'التقويم الاكاديمي') or contains(n, 'مواعيد الترم'):
        return 'مواعيد الفصل الأول 2026-2027:\nتبدأ التهيئة وفترة الاعتذار والتحويل بين المسارات في 30 أغسطس 2026.\nتبدأ الدراسة في 6 سبتمبر، وتنتهي فترة الاعتذار والتحويل في 10 سبتمبر.\nإجازة اليوم الوطني يومي 23 و24 سبتمبر.\nتبدأ الاختبارات النهائية في 6 ديسمبر، وينتهي الفصل في 17 ديسمبر 2026.'
    if contains(n, 'متى التهيئه') or contains(n, 'بدايه التهيئه'):
        return 'تبدأ التهيئة يوم الأحد 30 أغسطس 2026، قبل بداية الدراسة بأسبوع.'
    if contains(n, 'متى تبدا الدراسه') or contains(n, 'بدايه الدراسه') or contains(n, 'متى يبدا الترم'):
        return 'تبدأ الدراسة يوم الأحد 6 سبتمبر 2026، والتهيئة تبدأ قبلها يوم 30 أغسطس.'
    if (contains(n, 'اعتذار') or contains(n, 'تحويل بين المسارات')) and any(contains(n, x) for x in ('متى','اخر','فتره')):
        return 'فترة الاعتذار والتحويل بين المسارات تبدأ يوم 30 أغسطس وتنتهي يوم الخميس 10 سبتمبر 2026.'
    if contains(n, 'متى الاختبارات النهائيه') or contains(n, 'بدايه الاختبارات النهائيه'):
        return 'تبدأ الاختبارات النهائية يوم الأحد 6 ديسمبر 2026، وينتهي الفصل يوم الخميس 17 ديسمبر.'
    if contains(n, 'متى ينتهي الفصل') or contains(n, 'نهايه الفصل') or contains(n, 'متى ينتهي الترم'):
        return 'ينتهي الفصل الدراسي الأول يوم الخميس 17 ديسمبر 2026.'
    if contains(n, 'اجازه اليوم الوطني') or contains(n, 'إجازة اليوم الوطني'):
        return 'إجازة اليوم الوطني يومي الأربعاء والخميس 23 و24 سبتمبر 2026.'
    return ''


def is_personal_request(text: Any) -> bool:
    n = normalize(text)
    phrases = (
        'انسحابي','حالة الانسحاب','قدمت طلب انسحاب','ابي انسحب','ابغى انسحب','ارغب بالانسحاب','ارغب في الانسحاب',
        'ابي اقدم طلب انسحاب','ابغى اقدم طلب انسحاب','ابي اقدم انسحاب','سوي لي طلب انسحاب','قدم لي طلب انسحاب','ارفعي لي طلب انسحاب',
        'استردادي','حالة الاسترداد','قدمت طلب استرداد','فلوسي','مبلغ الاسترداد','عقدي','وقعت العقد','دفعتي','دفعت','فاتورتي',
        'مبالغي','المبلغ المتبقي','كم باقي','باقي العقد','المتبقي من العقد','انقبلت','قبولي','طلبي','رقمي الجامعي','حجبي','محجوب',
        'مقفل','مغلق','ليش التسجيل','سجلي الاكاديمي','تسجيل المقررات عندي','تسجيلي محجوب','مقرراتي','المقررات حقتي','المواد حقتي',
        'موادي المسجله','المفروض تنزل لي','وش المفروض اسجل','باكجي','البكج حقي','ساعاتي','معدلي','حالتي','تخصصي المسجل','وش تخصصي في النظام',
        'اسم تخصصي عندكم','مرشدي','شهادتي','نقطه الخروج حقي'
    )
    return any(contains(n, normalize(p)) for p in phrases)


def is_withdrawal_submission_request(text: Any) -> bool:
    n = normalize(text)
    phrases = (
        'ابي انسحب','ابغى انسحب','ارغب بالانسحاب','ارغب في الانسحاب','قدم لي انسحاب','قدمي لي انسحاب','ارفعي طلب انسحاب','ارفع طلب انسحاب',
        'ابي اقدم طلب انسحاب','ابغى اقدم طلب انسحاب','ابي اقدم انسحاب','ابغى اقدم انسحاب','ابي اسوي طلب انسحاب','ابغى اسوي طلب انسحاب',
        'سوي لي طلب انسحاب','سو لي طلب انسحاب','قدم لي طلب انسحاب','قدمي لي طلب انسحاب','ارفعي لي طلب انسحاب','ارفع لي طلب انسحاب',
        'ابدأ طلب الانسحاب','ابدا طلب الانسحاب'
    )
    return any(contains(n, normalize(p)) for p in phrases)


def is_applicant_identity_request(text: Any) -> bool:
    n = normalize(text)
    mentions_issue = any(contains(n, p) for p in ('رقم جامعي','الرقم الجامعي','بيانات الدخول','رساله العقد','رابط العقد'))
    mentions_missing = any(contains(n, p) for p in ('ما وصل','ماوصل','لم يصل','ما جاء','ماجاء','ما جاني','ماجاني','ما ظهر','ماظهر','ما طلع','ماطلع'))
    if mentions_issue and mentions_missing:
        return True
    new_registration = any(contains(n, p) for p in ('سجلت','توني سجلت','كملت التسجيل','وقعت العقد','وقعت ودفعت','وقعت العقد ودفعت'))
    missing_message = (contains(n, 'رساله') or contains(n, 'رسالة') or contains(n, 'نصيه')) and mentions_missing
    if (new_registration and missing_message) or contains(n, 'وقعت العقد ودفعت') or contains(n, 'ماعرف رقمي الجامعي') or contains(n, 'ما اعرف رقمي الجامعي'):
        return True
    phrases = (
        'لم يصلني الرقم الجامعي','ما وصلني الرقم الجامعي','سجلت ماوصلتني رساله بالرقم الجامعي','سجلت وما وصلتني رساله بالرقم الجامعي',
        'وقعت وما وصلني الرقم الجامعي','وقعت العقد وما وصلني الرقم الجامعي','ما صدر رقمي الجامعي','ما طلع رقمي الجامعي',
        'دفعت ولم تصلني رساله العقد','دفعت وما وصلني العقد','لم يصلني العقد','ما وصلني رابط العقد','لم تصل بيانات الدخول','ما وصلت بيانات الدخول'
    )
    return any(contains(n, normalize(p)) for p in phrases)


def is_applicant_access_followup(text: Any) -> bool:
    n = normalize(text)
    return any(contains(n, p) for p in ('رساله نصيه','الرساله','بيانات الدخول','كيف ادخل','وين ادخل','دخول الطالب','ماوصلتني رساله','ما وصلتني رساله'))


def detect_level(message: Any) -> int | None:
    n = normalize(message)
    levels = {
        1:('المستوى الاول','اول مستوى','الاول بس','اول بس'), 2:('المستوى الثاني','ثاني مستوى','الثاني بس','ثاني بس'),
        3:('المستوى الثالث','ثالث مستوى','الثالث بس','ثالث بس'), 4:('المستوى الرابع','رابع مستوى','الرابع بس','رابع بس'),
        5:('المستوى الخامس','خامس مستوى','الخامس بس'), 6:('المستوى السادس','سادس مستوى','السادس بس'),
        7:('المستوى السابع','سابع مستوى','السابع بس'), 8:('المستوى الثامن','ثامن مستوى','الثامن بس')
    }
    for number, phrases in levels.items():
        if any(p in n for p in phrases):
            return number
    return None


def needs_plan(message: Any, session: dict) -> bool:
    n = normalize(message)
    keys = ('مواد','ماده','مقررات','مقرر','الخطة','خطه','المستوى','متطلب','متطلبات','ساعاتهم','تدريب','تعاوني','ميداني','وش ادرس')
    if any(k in n for k in keys):
        return True
    if session.get('gulf_ai_last_context') == 'study_plan':
        return any(k in n for k in ('الاول','الثاني','الثالث','الرابع','الخامس','السادس','السابع','الثامن','كم ساعاتهم','ساعاتهم','طيب الثاني','طيب الاول','بس'))
    return False
