"""Coursework commands executed inside the caller's BEGIN IMMEDIATE transaction."""
import hashlib
import json
import re
from uuid import uuid4

from .auth.service import AuthError
from .brs.service import date_at, fail, get, teaching_access, teaching_offerings
from .events import audit
from .coursework_files import list_files, store_files
from .coursework_brs import publication_context, publications, publish_review


def create_draft(db, actor, now, offering_id, *, kind, title, description, due_at, mode):
    """Run inside the caller's write transaction."""
    if not db.in_transaction:
        raise RuntimeError('Coursework commands require a write transaction.')
    flow = teaching_access(db, actor, now, offering_id)
    fields = draft_fields(flow, now, kind=kind, title=title, description=description, due_at=due_at, mode=mode)
    key = uuid4().hex
    db.execute("""INSERT INTO coursework_assignments
        (id,offering_id,created_by,kind,title,description,due_at,mode,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (key, offering_id, actor['id'], *fields, now))
    audit(db, actor, 'coursework.draft.create', 'coursework_assignment', key, None, now)
    return key


DRAFT_FIELDS = ('kind', 'title', 'description', 'due_at', 'mode')


def draft_fields(flow, now, *, kind, title, description, due_at, mode):
    if type(due_at) is not int or not now < due_at <= 4102444800:
        fail(422, 'Укажите будущий срок сдачи.')
    if date_at(due_at) > flow['ends_on']:
        fail(422, 'Срок сдачи выходит за пределы учебного периода.')
    if (kind not in ('lab', 'test', 'practice', 'other')
            or mode not in ('in_person', 'online', 'both')
            or not isinstance(title, str) or '\0' in title or not 1 <= len(title.strip()) <= 160
            or not isinstance(description, str) or '\0' in description or not 1 <= len(description.strip()) <= 4000):
        fail(422, 'Проверьте поля учебной работы.')
    return kind, title.strip(), description.strip(), due_at, mode


COMMAND_FIELDS = {
    'edit_draft': (set(), set(DRAFT_FIELDS)),
    'publish': (set(), {'event_code', 'grading_mode', 'max_points'}),
    'copy': ({'target_offering_id'}, {'due_at'}),
    'submit_text': ({'response'}, {'files'}),
    'attach_materials': ({'files'}, set()),
    'publish_brs': ({'course_id', 'attempt_no', 'review_revision', 'expected_result_version'}, set()),
    'record_in_person': ({'course_id'}, set()),
    'review': ({'course_id', 'attempt_no', 'decision', 'comment'}, {'points', 'reason'}),
}

ACTIVE_RECIPIENTS = """SELECT n.course_id,n.id FROM brs_enrollments n
    JOIN brs_student_courses c ON c.id=n.course_id JOIN users u ON u.id=c.student_id
    WHERE n.offering_id=? AND n.starts_on<=? AND n.ends_on IS NULL
    AND u.active=1 AND u.role='student'"""


class PublishedBRSConflict(AuthError):
    code = 'coursework_brs_result_already_published'

    def __init__(self):
        super().__init__(409, 'Для мероприятия уже опубликованы результаты БРС.')


def recipient(db, actor, assignment_id, course_id=None):
    if actor['role'] == 'student':
        return get(db, """SELECT r.* FROM coursework_recipients r JOIN brs_student_courses c
            ON c.id=r.course_id WHERE r.assignment_id=? AND c.student_id=?""",
            assignment_id, actor['id'])
    return get(db, 'SELECT * FROM coursework_recipients WHERE assignment_id=? AND course_id=?',
               assignment_id, course_id)


def student_work(db, actor, assignment_id, *, now=None):
    if actor['role'] != 'student':
        fail(403)
    own = recipient(db, actor, assignment_id)
    # Existing service callers use this function for history without a session clock.
    row = get(db, STUDENT_WORKS + " AND a.id=?", actor['id'], assignment_id)
    return {**student_summary(row, now), **work_history(db, assignment_id, own['course_id']),
            'materials': list_files(db, assignment_id)}


def work_history(db, assignment_id, course_id):
    args = (assignment_id, course_id)
    return {'files': list_files(db, assignment_id, course_id),
            'brs_publications': publications(db, assignment_id, course_id), 'attempts': [dict(row) for row in db.execute(
        """SELECT number,method,response,submitted_at,late FROM coursework_attempts
           WHERE assignment_id=? AND course_id=? ORDER BY number""", args)],
        'reviews': [dict(row) for row in db.execute(
            """SELECT attempt_no,revision,decision,points,comment,reviewed_at,reason FROM coursework_reviews
               WHERE assignment_id=? AND course_id=? ORDER BY attempt_no,revision""", args)]}


WORK_FIELDS = """a.id,a.offering_id,a.kind,a.title,a.description,a.due_at,a.mode,a.created_at,
    a.status,a.version,a.event_code,a.grading_mode,c.semester_id,s.name AS subject_name,g.name AS group_name,
    CASE WHEN a.grading_mode='brs' THEN e.maximum ELSE a.max_points END AS max_points"""
WORK_CONTEXT = """JOIN brs_offerings o ON o.id=a.offering_id
    JOIN brs_whole_plans p ON p.id=o.plan_id JOIN curriculum_items c ON c.id=p.curriculum_id
    JOIN subjects s ON s.id=c.subject_id JOIN study_groups g ON g.id=o.group_id
    LEFT JOIN brs_events e ON (e.plan_id,e.code)=(o.plan_id,a.event_code)"""
LATEST_ATTEMPT = """LEFT JOIN coursework_attempts t ON (t.assignment_id,t.course_id)=(r.assignment_id,r.course_id)
    AND t.number=(SELECT max(number) FROM coursework_attempts WHERE (assignment_id,course_id)=(r.assignment_id,r.course_id))
    LEFT JOIN coursework_reviews v ON (v.assignment_id,v.course_id,v.attempt_no)=(t.assignment_id,t.course_id,t.number)
    AND v.revision=(SELECT max(revision) FROM coursework_reviews
        WHERE (assignment_id,course_id,attempt_no)=(t.assignment_id,t.course_id,t.number))"""
STUDENT_WORKS = f"""SELECT {WORK_FIELDS},r.version AS recipient_version,t.number AS latest_attempt_no,
    v.decision AS latest_decision,n.starts_on AS enrollment_start,n.ends_on AS enrollment_end
    FROM coursework_recipients r JOIN coursework_assignments a ON a.id=r.assignment_id
    JOIN brs_student_courses sc ON sc.id=r.course_id
    JOIN brs_enrollments n ON n.id=r.enrollment_id
    {WORK_CONTEXT} {LATEST_ATTEMPT}
    WHERE sc.student_id=? AND a.status='published'"""
STAFF_WORKS = f"""SELECT {WORK_FIELDS}, (SELECT json_object(
        'recipients',count(*),'submitted',count(t.number),
        'awaiting_review',count(CASE WHEN t.number IS NOT NULL AND v.decision IS NULL THEN 1 END),
        'reviewed',count(CASE WHEN v.decision='reviewed' THEN 1 END),
        'returned',count(CASE WHEN v.decision IN ('returned','retry_allowed') THEN 1 END))
        FROM coursework_recipients r {LATEST_ATTEMPT} WHERE r.assignment_id=a.id) AS queue
    FROM coursework_assignments a {WORK_CONTEXT}"""


def retry_allowed(decision):
    return decision in ('returned', 'retry_allowed')


def student_summary(row, now):
    result = dict(row)
    decision = result.pop('latest_decision')
    start = result.pop('enrollment_start')
    end = result.pop('enrollment_end')
    attempted = result['latest_attempt_no'] is not None
    text_available = now is not None and end is None and start <= date_at(now) and row['mode'] != 'in_person'
    return {**result, 'latest_attempt_state': (decision or 'submitted') if attempted else None,
            'has_latest_review': decision is not None,
            'can_submit_text': text_available and (not attempted or retry_allowed(decision)),
            'can_resubmit': text_available and attempted and retry_allowed(decision)}


def student_works(db, actor, now, offering_id=None, semester_id=None):
    if actor['role'] != 'student':
        fail(403)
    rows = db.execute(STUDENT_WORKS + """ AND (? IS NULL OR a.offering_id=?)
        AND (? IS NULL OR c.semester_id=?) ORDER BY a.due_at,a.id""",
        (actor['id'], offering_id, offering_id, semester_id, semester_id))
    return {'items': [student_summary(row, now) for row in rows]}


def staff_summary(row):
    result = dict(row)
    result['queue'] = json.loads(result['queue'])
    return result


def staff_works(db, actor, now, offering_id=None, semester_id=None):
    keys = ('id', 'group_id', 'subject_id', 'semester_id', 'subject_name', 'group_name')
    offers = [{key: flow[key] for key in keys}
              for flow in teaching_offerings(db, actor, now, offering_id, semester_id=semester_id)]
    rows = db.execute(STAFF_WORKS + """ WHERE a.offering_id IN (SELECT value FROM json_each(?))
        ORDER BY a.offering_id,a.due_at,a.id""", (json.dumps([offer['id'] for offer in offers]),))
    return {'items': [staff_summary(row) for row in rows], 'offerings': offers}


def staff_recipient_work(db, actor, now, assignment_id, course_id):
    assignment = get(db, "SELECT * FROM coursework_assignments WHERE id=? AND status='published'", assignment_id)
    teaching_access(db, actor, now, assignment['offering_id'])
    own = get(db, """SELECT r.version, p.full_name AS student_name, n.starts_on, n.ends_on
        FROM coursework_recipients r JOIN brs_enrollments n ON n.id=r.enrollment_id
        JOIN brs_student_courses c ON c.id=r.course_id JOIN student_profiles p ON p.user_id=c.student_id
        WHERE r.assignment_id=? AND r.course_id=?""", assignment_id, course_id)
    history = work_history(db, assignment_id, course_id)
    reviews = history['reviews']
    latest = history['attempts'][-1] if history['attempts'] else None
    can_retry = latest and reviews and reviews[-1]['attempt_no'] == latest['number'] and retry_allowed(reviews[-1]['decision'])
    brs_version = db.execute("""SELECT coalesce(max(v.result_version),0) FROM brs_attempt_versions v
        JOIN brs_event_results b ON b.id=v.result_id
        JOIN brs_offerings o ON o.plan_id=b.plan_id
        WHERE o.id=? AND b.event_code=? AND b.course_id=?""",
        (assignment['offering_id'], assignment['event_code'], course_id)).fetchone()[0]
    return {'course_id': course_id, 'recipient_version': own['version'],
            'brs_result_version': brs_version,
            'student_name': own['student_name'],
            'can_record_in_person': bool(assignment['mode'] != 'online' and own['ends_on'] is None
                                         and own['starts_on'] <= date_at(now) and (not latest or can_retry)),
            **history}


def staff_work(db, actor, now, assignment_id):
    scope = get(db, 'SELECT offering_id FROM coursework_assignments WHERE id=?', assignment_id)
    teaching_access(db, actor, now, scope['offering_id'])
    assignment = get(db, STAFF_WORKS + ' WHERE a.id=?', assignment_id)
    roster = db.execute("""SELECT r.course_id,r.enrollment_id,r.version,c.student_id,p.full_name AS student_name
        FROM coursework_recipients r JOIN brs_student_courses c ON c.id=r.course_id
        JOIN student_profiles p ON p.user_id=c.student_id
        WHERE r.assignment_id=? ORDER BY r.course_id""", (assignment_id,))
    return {**staff_summary(assignment), 'recipients': [dict(row) for row in roster],
            'materials': list_files(db, assignment_id)}


def download_file(db, actor, now, file_id):
    file = get(db, 'SELECT id,assignment_id,course_id,name FROM coursework_files WHERE id=?', file_id)
    assignment = get(db, 'SELECT id,status,offering_id FROM coursework_assignments WHERE id=?', file['assignment_id'])
    if actor['role'] == 'student':
        own = recipient(db, actor, assignment['id'])
        if assignment['status'] != 'published' or file['course_id'] not in (None, own['course_id']):
            fail(404)
    else:
        teaching_access(db, actor, now, assignment['offering_id'])
    return file['name'], get(db, 'SELECT content FROM coursework_files WHERE id=?', file_id)['content']


def publish(db, assignment, now, data):
    if assignment['status'] != 'draft':
        fail(409, 'Задание уже опубликовано.')
    event_code = data.get('event_code')
    grading_mode = data.get('grading_mode', 'brs' if event_code is not None else 'ungraded')
    maximum = data.get('max_points')
    if grading_mode not in ('ungraded', 'independent', 'brs'):
        fail(422, 'Укажите режим оценивания.')
    if (grading_mode == 'independent' and (type(maximum) is not int or not 1 <= maximum <= 100)
            or grading_mode != 'independent' and maximum is not None
            or grading_mode != 'brs' and event_code is not None):
        fail(422, 'Параметры не соответствуют режиму оценивания.')
    scope = (assignment['offering_id'], date_at(now))
    if grading_mode == 'brs':
        if not isinstance(event_code, str) or not event_code:
            fail(422, 'Укажите код мероприятия.')
        get(db, """SELECT e.code FROM brs_events e JOIN brs_offerings o ON o.plan_id=e.plan_id
                   WHERE o.id=? AND e.code=?""", assignment['offering_id'], event_code)
        if db.execute('SELECT 1 FROM coursework_assignments WHERE offering_id=? AND event_code=?',
                      (assignment['offering_id'], event_code)).fetchone():
            fail(409, 'Мероприятие уже связано с другой работой потока.')
        if db.execute(f"""WITH recipients AS ({ACTIVE_RECIPIENTS})
            SELECT 1 FROM recipients r JOIN brs_published_event_scopes p ON p.course_id=r.course_id
            JOIN brs_offerings o ON (o.id,o.plan_id)=(p.offering_id,p.plan_id)
            WHERE o.id=? AND p.event_code=? LIMIT 1""",
            (*scope, assignment['offering_id'], event_code)).fetchone():
            raise PublishedBRSConflict()
    db.execute("""UPDATE coursework_assignments SET status='published',event_code=?,
        grading_mode=?,max_points=? WHERE id=?""", (event_code, grading_mode, maximum, assignment['id']))
    db.execute(f"""WITH recipients AS ({ACTIVE_RECIPIENTS})
        INSERT INTO coursework_recipients (assignment_id,course_id,enrollment_id)
        SELECT ?,course_id,id FROM recipients""", (*scope, assignment['id']))


def add_attempt(db, actor, now, assignment, own, method, response):
    get(db, """SELECT id FROM brs_enrollments WHERE id=? AND starts_on<=?
               AND ends_on IS NULL""", own['enrollment_id'], date_at(now))
    if (method == 'text' and assignment['mode'] == 'in_person' or
            method == 'in_person' and assignment['mode'] == 'online'):
        fail(409, 'Этот способ сдачи недоступен.')
    args = (assignment['id'], own['course_id'])
    previous = db.execute("""SELECT max(number) FROM coursework_attempts
                             WHERE assignment_id=? AND course_id=?""", args).fetchone()[0]
    if previous is not None:
        decision = db.execute("""SELECT decision FROM coursework_reviews WHERE assignment_id=?
            AND course_id=? AND attempt_no=? ORDER BY revision DESC LIMIT 1""",
            (*args, previous)).fetchone()
        if not decision or not retry_allowed(decision[0]):
            fail(409, 'Повторная сдача не разрешена.')
    number = (previous or 0) + 1
    late = now > assignment['due_at']
    db.execute('INSERT INTO coursework_attempts VALUES (?,?,?,?,?,?,?,?)',
               (*args, number, method, response, now, actor['id'], int(late)))
    return {'attempt_no': number, 'late': late}


def review_attempt(db, actor, now, assignment, own, data):
    attempt = data['attempt_no']
    decision = data['decision']
    comment = data['comment']
    points = data.get('points')
    if (type(attempt) is not int or attempt < 1 or decision not in ('reviewed', 'returned', 'retry_allowed')
            or not isinstance(comment, str) or '\0' in comment or not 1 <= len(comment.strip()) <= 2000
            or (points is not None and (decision != 'reviewed' or type(points) is not int or points < 0))):
        fail(422, 'Проверьте решение, балл и комментарий.')
    args = (assignment['id'], own['course_id'])
    latest = db.execute('SELECT max(number) FROM coursework_attempts WHERE assignment_id=? AND course_id=?',
                        args).fetchone()[0]
    if latest != attempt:
        fail(409, 'Проверить можно только последнюю попытку.')
    if points is not None:
        maximum = assignment['max_points']
        if assignment['grading_mode'] == 'brs':
            maximum = get(db, """SELECT e.maximum FROM brs_events e JOIN brs_offerings o ON o.plan_id=e.plan_id
                                  WHERE o.id=? AND e.code=?""", assignment['offering_id'],
                          assignment['event_code'])['maximum']
        if maximum is None or points > maximum:
            fail(422, 'Баллы недопустимы для выбранного режима или превышают максимум.')
    revision = db.execute("""SELECT coalesce(max(revision),0)+1 FROM coursework_reviews
                             WHERE assignment_id=? AND course_id=? AND attempt_no=?""",
                          (*args, attempt)).fetchone()[0]
    reason = data.get('reason')
    if (revision > 1 and (not isinstance(reason, str) or '\0' in reason or not 3 <= len(reason.strip()) <= 500)
            or revision == 1 and reason is not None):
        fail(422, 'Укажите основание для новой версии проверки.')
    db.execute("""INSERT INTO coursework_reviews
        (assignment_id,course_id,attempt_no,revision,decision,points,comment,reviewer_id,reviewed_at,reason)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (*args, attempt, revision, decision, points, comment.strip(), actor['id'], now,
         reason.strip() if reason is not None else None))
    return {'attempt_no': attempt, 'review_revision': revision}


def receipt_for(db, actor, request_key, payload):
    if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', request_key):
        fail(422, 'Некорректный ключ повтора.')
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    receipt = db.execute('SELECT fingerprint,result FROM coursework_receipts WHERE actor_id=? AND request_key=?',
                         (actor['id'], request_key)).fetchone()
    if receipt:
        if receipt['fingerprint'] != fingerprint:
            fail(409, 'Ключ уже использован для другой команды.')
        return fingerprint, json.loads(receipt['result'])
    return fingerprint, None


def save_receipt(db, actor, request_key, fingerprint, result):
    db.execute('INSERT INTO coursework_receipts VALUES (?,?,?,?)',
               (actor['id'], request_key, fingerprint, json.dumps(result)))


def create_work(db, actor, now, offering_id, request_key, data):
    if not db.in_transaction:
        raise RuntimeError('Coursework commands require a write transaction.')
    teaching_access(db, actor, now, offering_id)
    fingerprint, previous = receipt_for(db, actor, request_key, ['create', offering_id, data])
    if previous is not None:
        return previous
    key = create_draft(db, actor, now, offering_id, **data)
    result = {'assignment_id': key, 'version': 1}
    save_receipt(db, actor, request_key, fingerprint, result)
    return result


def execute(db, actor, now, assignment_id, action, *, expected_version, request_key, data):
    """Execute a validated command with an identity supplied by the server."""
    if not db.in_transaction:
        raise RuntimeError('Coursework commands require a write transaction.')
    if (not isinstance(action, str) or action not in COMMAND_FIELDS
            or type(expected_version) is not int or expected_version < 1
            or not isinstance(data, dict)):
        fail(422, 'Некорректная команда.')
    required, optional = COMMAND_FIELDS[action]
    if not required <= data.keys() or data.keys() - required - optional:
        fail(422, 'Некорректные поля команды.')
    for key in ('target_offering_id', 'course_id'):
        if key in data and (not isinstance(data[key], str) or not 1 <= len(data[key]) <= 64):
            fail(422, 'Некорректный идентификатор.')
    assignment = get(db, 'SELECT * FROM coursework_assignments WHERE id=?', assignment_id)
    own = None
    if action == 'submit_text':
        if actor['role'] != 'student':
            fail(403)
        own = recipient(db, actor, assignment_id)
    else:
        # Commands operate on the offering as a whole.
        flow = teaching_access(db, actor, now, assignment['offering_id'])
        if action == 'copy':
            teaching_access(db, actor, now, data['target_offering_id'])
        elif action in ('record_in_person', 'review', 'publish_brs'):
            own = recipient(db, actor, assignment_id, data['course_id'])
    if own is not None and assignment['status'] != 'published':
        fail(404)
    if action == 'publish_brs':
        brs_context = publication_context(db, actor, now, assignment, own)
    fingerprint, previous = receipt_for(db, actor, request_key, [assignment_id, action, expected_version, data])
    if previous is not None:
        return previous
    if (own if own is not None else assignment)['version'] != expected_version:
        fail(409, 'Версия задания изменилась.')

    result = {'assignment_id': assignment_id, 'version': expected_version + int(action != 'copy')}
    if action == 'edit_draft':
        if assignment['status'] != 'draft':
            fail(409, 'Изменить можно только черновик.')
        if not data:
            fail(422, 'Укажите поля для изменения.')
        fields = draft_fields(flow, now, **{key: data.get(key, assignment[key]) for key in DRAFT_FIELDS})
        db.execute("""UPDATE coursework_assignments SET kind=?,title=?,description=?,due_at=?,mode=?
            WHERE id=?""", (*fields, assignment_id))
    elif action == 'publish':
        publish(db, assignment, now, data)
    elif action == 'attach_materials':
        if assignment['status'] != 'draft':
            fail(409, 'Материалы можно добавить только в черновик.')
        store_files(db, assignment_id, data['files'])
    elif action == 'publish_brs':
        result.update(publish_review(db, actor, now, assignment, own, data, context=brs_context))
    elif action == 'copy':
        if data['target_offering_id'] == assignment['offering_id']:
            fail(422, 'Выберите другой поток.')
        fields = {key: assignment[key] for key in ('kind', 'title', 'description', 'mode')}
        result['copy_id'] = create_draft(db, actor, now, data['target_offering_id'],
                                         due_at=data.get('due_at', assignment['due_at']), **fields)
    else:
        if action == 'submit_text':
            response = data['response']
            if not isinstance(response, str) or '\0' in response or not 1 <= len(response.strip()) <= 4000:
                fail(422, 'Укажите текст работы.')
            result.update(add_attempt(db, actor, now, assignment, own, 'text', response.strip()))
            if 'files' in data:
                store_files(db, assignment_id, data['files'], course=own['course_id'], attempt=result['attempt_no'])
        else:
            if action == 'record_in_person':
                result.update(add_attempt(db, actor, now, assignment, own, 'in_person', None))
            else:
                result.update(review_attempt(db, actor, now, assignment, own, data))
    if own is not None:
        db.execute('UPDATE coursework_recipients SET version=? WHERE assignment_id=? AND course_id=?',
                   (result['version'], assignment_id, own['course_id']))
    elif action in ('publish', 'edit_draft', 'attach_materials'):
        db.execute('UPDATE coursework_assignments SET version=? WHERE id=?', (result['version'], assignment_id))
    if actor['role'] == 'staff':
        audit(db, actor, 'coursework.' + action, 'coursework_assignment', assignment_id, result['version'], now,
              required=action == 'publish_brs')
    save_receipt(db, actor, request_key, fingerprint, result)
    return result
