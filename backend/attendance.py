"""Lesson-scoped attendance with explicitly confirmed, dated roster snapshots."""
import hashlib
import json

from .auth.service import AuthError
from .events import audit
from .schedule.service import SELECT, snapshot


def fail(code, message='Занятие недоступно.'):
    raise AuthError(code, message)


def teacher_lesson(db, actor, lesson_id):
    if actor['role'] != 'staff':
        fail(403)
    if not db.execute("""SELECT 1 FROM lessons l JOIN brs_whole_teacher_accounts t ON t.teacher_id=l.teacher_id
        JOIN users u ON u.id=t.staff_id WHERE l.id=? AND t.staff_id=? AND u.role='staff' AND u.active=1""",
        (lesson_id, actor['id'])).fetchone():
        fail(404)
    return snapshot(db, lesson_id)


def roster_candidates(db, lesson):
    flows = db.execute("""SELECT o.id,c.id AS curriculum_id FROM brs_offerings o
        JOIN brs_whole_plans p ON p.id=o.plan_id JOIN curriculum_items c ON c.id=p.curriculum_id
        JOIN semesters s ON s.id=c.semester_id JOIN study_groups g ON g.id=o.group_id
        WHERE o.group_id=? AND c.subject_id=? AND c.program_id=g.program_id
        AND ? BETWEEN s.starts_on AND s.ends_on AND p.locked_at IS NOT NULL""",
        (lesson['group_id'], lesson['subject_id'], lesson['date'])).fetchall()
    if len(flows) != 1:
        return None, 'Нет однозначного потока БРС для дисциплины, группы, семестра и даты занятия.'
    students = [dict(row) for row in db.execute("""SELECT c.student_id AS id,p.full_name,n.id AS enrollment_id
        FROM brs_enrollments n JOIN brs_student_courses c ON c.id=n.course_id
        JOIN student_profiles p ON p.user_id=c.student_id
        WHERE n.offering_id=? AND c.curriculum_id=? AND n.starts_on<=?
        AND (n.ends_on IS NULL OR ?<n.ends_on) ORDER BY c.student_id""",
        (flows[0]['id'], flows[0]['curriculum_id'], lesson['date'], lesson['date']))]
    if len({row['id'] for row in students}) != len(students):
        return None, 'Обнаружены неоднозначные зачисления. Требуется сверка состава.'
    if not students:
        return None, 'На дату занятия нет подходящих зачисленных студентов. Подтверждение состава запрещено.'
    return {'date':lesson['date'], 'lesson_version':lesson['version'],
            'offering_id':flows[0]['id'], 'students':students}, None


def fingerprint(candidate):
    return hashlib.sha256(json.dumps(candidate, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def history(db, lesson_id):
    return [{**dict(row), 'previous_version':row['version']-1, 'payload':json.loads(row['payload'])} for row in db.execute(
        'SELECT version,kind,actor_id,created_at,reason,payload FROM attendance_events WHERE lesson_id=? ORDER BY version',
        (lesson_id,))]


def state(db, lesson_id):
    events = history(db, lesson_id)
    rosters = [event for event in events if event['kind'] == 'roster']
    marks = {event['payload']['student_id']:event['payload']['status'] for event in events if event['kind'] == 'mark'}
    return events, rosters[-1]['payload'] if rosters else None, marks


def staff_detail(db, actor, lesson_id):
    lesson = teacher_lesson(db, actor, lesson_id)
    candidate, error = roster_candidates(db, lesson)
    events, roster, marks = state(db, lesson_id)
    current = bool(roster is not None and candidate is not None and roster == candidate)
    students = [] if roster is None else [{**row, 'status':marks.get(row['id'], 'unmarked')} for row in roster['students']]
    return {'lesson':lesson, 'version':events[-1]['version'] if events else 0,
            'candidate':candidate, 'candidate_token':fingerprint(candidate) if candidate is not None else None,
            'blocked_reason':error, 'needs_confirmation':not current,
            'can_mark':current and lesson['status']=='scheduled', 'students':students, 'history':events}


def lessons(db, actor):
    if actor['role'] != 'staff':
        fail(403)
    query = SELECT.replace('SELECT l.*,', 'SELECT l.*,g.name AS study_group,')
    return {'items':[dict(row) for row in db.execute(query+""" JOIN study_groups g ON g.id=l.group_id WHERE EXISTS (
        SELECT 1 FROM brs_whole_teacher_accounts t WHERE t.teacher_id=l.teacher_id AND t.staff_id=?)
        ORDER BY l.date DESC,l.start_minute LIMIT 200""", (actor['id'],))]}


def change(db, actor, now, lesson_id, data):
    if not db.in_transaction:
        raise RuntimeError('Attendance requires a write transaction.')
    detail = staff_detail(db, actor, lesson_id)
    lesson = detail['lesson']
    if lesson['status'] != 'scheduled':
        fail(409, 'Занятие отменено. История доступна только для чтения.')
    if (detail['version'], lesson['version']) != (data['expected_version'], data['lesson_version']):
        fail(409, 'Ведомость или занятие изменились. Обновите данные.')
    reason = data['reason'].strip()
    if not reason:
        fail(422, 'Укажите основание подтверждения или изменения.')
    if data['action'] == 'confirm':
        if detail['candidate'] is None:
            fail(409, detail['blocked_reason'])
        if data['candidate_token'] != detail['candidate_token']:
            fail(409, 'Состав изменился. Проверьте и подтвердите новый список.')
        payload = detail['candidate']
        kind = 'roster'
    else:
        if not detail['can_mark']:
            fail(409, 'Требуется повторное подтверждение состава ведомости.')
        student = next((row for row in detail['students'] if row['id']==data['student_id']), None)
        if student is None:
            fail(404)
        if student['status'] == data['status']:
            fail(409, 'Отметка уже имеет это значение.')
        payload = {'student_id':student['id'], 'previous':student['status'], 'status':data['status']}
        kind = 'mark'
    version = detail['version']+1
    if detail['version'] == 0:
        db.execute('INSERT INTO attendance_journals VALUES (?,?)', (lesson_id, version))
    else:
        db.execute('UPDATE attendance_journals SET version=? WHERE lesson_id=?', (version, lesson_id))
    db.execute('INSERT INTO attendance_events VALUES (?,?,?,?,?,?,?)',
               (lesson_id, version, kind, actor['id'], now, reason, json.dumps(payload, ensure_ascii=False)))
    audit(db, actor, 'attendance.'+kind, 'lesson', lesson_id, version, now, required=True)
    return staff_detail(db, actor, lesson_id)


def student_detail(db, actor, lesson_id):
    if actor['role'] != 'student':
        fail(403)
    events, roster, marks = state(db, lesson_id)
    own_rosters = [event for event in events if event['kind']=='roster' and
                   any(row['id']==actor['id'] for row in event['payload']['students'])]
    lesson = snapshot(db, lesson_id) if own_rosters else None
    if lesson is None:
        fail(404)
    own_history = []
    for event in events:
        if event['kind']=='mark' and event['payload']['student_id']==actor['id']:
            own_history.append(event)
        elif event['kind']=='roster' and event['version']>=own_rosters[0]['version']:
            own_history.append({**event, 'payload':{'date':event['payload']['date'],
                'included':any(row['id']==actor['id'] for row in event['payload']['students'])}})
    included = any(row['id']==actor['id'] for row in roster['students'])
    candidate, _ = roster_candidates(db, lesson)
    return {'lesson_id':lesson_id, 'date':lesson['date'], 'subject':lesson['subject'],
            'status':marks.get(actor['id'], 'unmarked'),
            'active':lesson['status']=='scheduled' and included and candidate==roster,
            'cancelled':lesson['status']=='cancelled', 'needs_confirmation':candidate!=roster,
            'history':own_history}
