from database import get_db_connection
from services.text_utils import clean, limit, normalize, contains


def program_alias_score(message: str, program: dict) -> int:
    message_n = normalize(message)
    name_n = normalize(program.get('name'))
    if name_n and name_n in message_n:
        return 1000
    score = 0
    generic = {'دبلوم','الدبلوم','عالي','العالي','متوسط','المتوسط','مشارك','المشارك','برنامج','البرنامج'}
    for word in name_n.split():
        if not word or word in generic or len(word) < 3:
            continue
        if word in message_n:
            score += 10
    if contains(message_n, 'سايبر') and (contains(name_n, 'سيبر') or contains(name_n, 'امن')):
        score += 50
    if any(contains(message_n, x) for x in ('سيبراني','سبراني','سيبرااني')) and (contains(name_n, 'سيبراني') or contains(name_n, 'الامن السيبراني')):
        score += 50
    if contains(message_n, 'اداره صحيه') and contains(name_n, 'اداره صحيه'):
        score += 50
    if contains(message_n, 'تحليل البيانات') and contains(name_n, 'تحليل البيانات'):
        score += 50
    if contains(message_n, 'تمريض') and contains(name_n, 'تمريض'):
        score += 40
    if contains(message_n, 'قانون') and contains(name_n, 'قانون'):
        score += 30
    return score


def get_plan_courses(plan_id: int) -> list[dict]:
    plan_id = int(plan_id or 0)
    if plan_id <= 0:
        return []
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT group1,group2,group3,group4,group5,group6,group7,group8
            FROM sis_plans WHERE id=%s LIMIT 1
        """, (plan_id,))
        plan = cur.fetchone()
        if not plan:
            return []
        result = []
        for level in range(1, 9):
            group_id = int(plan.get(f'group{level}') or 0)
            if group_id <= 0:
                continue
            group_name = f'المستوى {level}'
            cur.execute('SELECT name FROM sis_courses_groups WHERE id=%s LIMIT 1', (group_id,))
            group = cur.fetchone()
            if group and str(group.get('name') or '').strip():
                group_name = clean(group['name'])
            cur.execute("""
                SELECT c.id,c.code,c.name,c.edesc,c.credits,c.minimum
                FROM sis_courses_groups_enrol ge
                INNER JOIN sis_courses c ON c.id=ge.course
                WHERE ge.group_id=%s ORDER BY ge.id ASC
            """, (group_id,))
            courses = []
            for course in cur.fetchall():
                cur.execute("""
                    SELECT pc.id,pc.code,pc.name,pc.edesc
                    FROM sis_course_prerequisites cp
                    INNER JOIN sis_courses pc ON pc.id=cp.prerequisite
                    WHERE cp.course=%s ORDER BY cp.pre_no ASC
                """, (int(course['id']),))
                prerequisites = [{
                    'id': int(pre['id']), 'code': clean(pre.get('code')),
                    'arabic_name': clean(pre.get('name')), 'english_name': clean(pre.get('edesc'))
                } for pre in cur.fetchall()]
                courses.append({
                    'id': int(course['id']), 'code': clean(course.get('code')),
                    'arabic_name': clean(course.get('name')), 'english_name': clean(course.get('edesc')),
                    'credits': float(course.get('credits') or 0), 'minimum': clean(course.get('minimum')),
                    'prerequisites': prerequisites,
                })
            result.append({'level': level, 'group_id': group_id, 'group_name': group_name, 'courses': courses})
        return result
    finally:
        cur.close(); conn.close()


def training_course_from_plan(plan_data: list[dict]):
    for level in plan_data:
        for course in level.get('courses') or []:
            haystack = normalize(f"{course.get('arabic_name','')} {course.get('english_name','')} {course.get('code','')}")
            if any(contains(haystack, term) for term in ('تدريب','تعاوني','internship','cooperative training','field training')):
                return {
                    'level': int(level.get('level') or 0), 'name': course.get('arabic_name',''),
                    'code': course.get('code',''), 'credits': float(course.get('credits') or 0)
                }
    return None


def load_programs() -> list[dict]:
    conn = get_db_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT p.id,p.major_id,p.name,p.short_description,p.description,p.diploma_level,p.program_type,
                   p.credit_hours,p.duration,p.qualification,p.study_mode,p.language,p.price,p.target_group,p.importance,
                   p.goals,p.opportunities,p.careers,p.sectors,p.certificates,p.advantages,p.study_plan,p.admission_requirements,
                   p.study_plan_file,p.issuer,p.accreditation_number,p.registration_pid,p.start_date,p.end_date,p.accreditation,
                   p.professional_classification,p.classification_number,p.professional_license,p.licensing_authority
            FROM programs p WHERE p.status=1 ORDER BY p.sort_order ASC,p.name ASC
        """)
        rows = cur.fetchall()
    finally:
        cur.close(); conn.close()

    programs = []
    for row in rows:
        study_plan_file = str(row.get('study_plan_file') or '').strip()
        study_plan_id = int(study_plan_file) if study_plan_file.isdigit() else 0
        programs.append({
            'id': int(row.get('id') or 0), 'major_id': int(row.get('major_id') or 0),
            'registration_pid': int(row.get('registration_pid') or 0), 'name': clean(row.get('name')),
            'short_description': limit(row.get('short_description'),500), 'description': limit(row.get('description'),1200),
            'diploma_level': clean(row.get('diploma_level')), 'program_type': clean(row.get('program_type')),
            'credit_hours': clean(row.get('credit_hours')), 'duration': clean(row.get('duration')),
            'qualification': clean(row.get('qualification')), 'study_mode': clean(row.get('study_mode')),
            'language': 'العربية', 'price': float(row.get('price') or 0),
            'target_group': limit(row.get('target_group'),700), 'importance': limit(row.get('importance'),700),
            'goals': limit(row.get('goals'),700), 'opportunities': limit(row.get('opportunities'),700),
            'careers': limit(row.get('careers'),700), 'sectors': limit(row.get('sectors'),700),
            'certificates': limit(row.get('certificates'),700), 'advantages': limit(row.get('advantages'),700),
            'admission_requirements': limit(row.get('admission_requirements'),1000),
            'study_plan_text': limit(row.get('study_plan'),1000), 'study_plan_id': study_plan_id,
            'issuer': clean(row.get('issuer')), 'accreditation_number': clean(row.get('accreditation_number')),
            'accreditation': limit(row.get('accreditation'),800),
            'professional_classification': limit(row.get('professional_classification'),800),
            'classification_number': clean(row.get('classification_number')),
            'professional_license': limit(row.get('professional_license'),800),
            'licensing_authority': clean(row.get('licensing_authority')),
            'start_date': clean(row.get('start_date')), 'end_date': clean(row.get('end_date')),
        })
    return programs


def match_program(message: str, programs: list[dict], saved_program_id: int | None = None):
    matched = None; best = 0
    for program in programs:
        score = program_alias_score(message, program)
        if score > best:
            best, matched = score, program
    if best <= 0:
        matched = None
    if matched is None and saved_program_id:
        for program in programs:
            if int(program['id']) == int(saved_program_id):
                return program
    return matched


def program_list_for_ai(programs: list[dict]) -> list[dict]:
    keys = ('id','name','diploma_level','program_type','qualification','credit_hours','duration','study_mode','language','price')
    return [{k: p.get(k) for k in keys} for p in programs]
