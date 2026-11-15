"""Coursework commands executed inside the caller's BEGIN IMMEDIATE transaction."""
import hashlib
import json
import re
from uuid import uuid4

from .auth.service import AuthError
from .brs.service import date_at, fail, get, teaching_access
from .events import audit


def create_draft(db, actor, now, offering_id, *, kind, title, description, due_at, mode):
    """Run inside the caller's write transaction."""
    if not db.in_transaction:
        raise RuntimeError('Coursework commands require a write transaction.')
    flow = teaching_access(db, actor, now, offering_id)
    if type(due_at) is not int or not now < due_at <= 4102444800:
        fail(422, 'Укажите будущий срок сдачи.')
    if date_at(due_at) > flow['ends_on']:
        fail(422, 'Срок сдачи выходит за пределы учебного периода.')
    if (kind not in ('lab', 'test', 'practice', 'other')
            or mode not in ('in_person', 'online', 'both')
            or not isinstance(title, str) or not 1 <= len(title.strip()) <= 160
            or not isinstance(description, str) or not 1 <= len(description.strip()) <= 4000):
        fail(422, 'Проверьте поля учебной работы.')
    key = uuid4().hex
    db.execute("""INSERT INTO coursework_assignments
        (id,offering_id,created_by,kind,title,description,due_at,mode,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (key, offering_id, actor['id'], kind, title.strip(), description.strip(), due_at, mode, now))
    audit(db, actor, 'coursework.draft.create', 'coursework_assignment', key, None, now)
    return key


COMMAND_FIELDS = {
    'publish': (set(), {'event_code', 'grading_mode', 'max_points'}),
    'copy': ({'target_offering_id'}, {'due_at'}),
    'submit_text': ({'response'}, set()),
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


def student_work(db, actor, assignment_id):
    if actor['role'] != 'student':
        fail(403)
    own = recipient(db, actor, assignment_id)
    assignment = get(db, "SELECT * FROM coursework_assignments WHERE id=? AND status='published'", assignment_id)
    args = (assignment_id, own['course_id'])
    return {**dict(assignment), 'recipient_version': own['version'], 'attempts': [dict(row) for row in db.execute(
        """SELECT number,method,response,submitted_at,late FROM coursework_attempts
           WHERE assignment_id=? AND course_id=? ORDER BY number""", args)],
        'reviews': [dict(row) for row in db.execute(
            """SELECT attempt_no,revision,decision,points,comment,reviewed_at,reason FROM coursework_reviews
               WHERE assignment_id=? AND course_id=? ORDER BY attempt_no,revision""", args)]}


def staff_work(db, actor, now, assignment_id):
    assignment = get(db, 'SELECT * FROM coursework_assignments WHERE id=?', assignment_id)
    teaching_access(db, actor, now, assignment['offering_id'])
    roster = db.execute("""SELECT r.course_id,r.enrollment_id,r.version,c.student_id
        FROM coursework_recipients r JOIN brs_student_courses c ON c.id=r.course_id
        WHERE r.assignment_id=? ORDER BY r.course_id""", (assignment_id,))
    return {**dict(assignment), 'recipients': [dict(row) for row in roster]}


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
        if not decision or decision[0] not in ('returned', 'retry_allowed'):
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


def execute(db, actor, now, assignment_id, action, *, expected_version, request_key, data):
    """Execute a validated command with an identity supplied by the server."""
    if not db.in_transaction:
        raise RuntimeError('Coursework commands require a write transaction.')
    if (not isinstance(action, str) or action not in COMMAND_FIELDS
            or type(expected_version) is not int or expected_version < 1
            or not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', request_key)
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
        teaching_access(db, actor, now, assignment['offering_id'])
        if action == 'copy':
            teaching_access(db, actor, now, data['target_offering_id'])
        elif action in ('record_in_person', 'review'):
            own = recipient(db, actor, assignment_id, data['course_id'])
    if own is not None and assignment['status'] != 'published':
        fail(404)
    payload = json.dumps([assignment_id, action, expected_version, data], sort_keys=True)
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()
    receipt = db.execute('SELECT fingerprint,result FROM coursework_receipts WHERE actor_id=? AND request_key=?',
                         (actor['id'], request_key)).fetchone()
    if receipt:
        if receipt['fingerprint'] != fingerprint:
            fail(409, 'Ключ уже использован для другой команды.')
        return json.loads(receipt['result'])
    if (own if own is not None else assignment)['version'] != expected_version:
        fail(409, 'Версия задания изменилась.')

    result = {'assignment_id': assignment_id, 'version': expected_version + int(action != 'copy')}
    if action == 'publish':
        publish(db, assignment, now, data)
    elif action == 'copy':
        if data['target_offering_id'] == assignment['offering_id']:
            fail(422, 'Выберите другой поток.')
        fields = {key: assignment[key] for key in ('kind', 'title', 'description', 'mode')}
        result['copy_id'] = create_draft(db, actor, now, data['target_offering_id'],
                                         due_at=data.get('due_at', assignment['due_at']), **fields)
    else:
        if action == 'submit_text':
            response = data['response']
            if not isinstance(response, str) or not 1 <= len(response.strip()) <= 4000:
                fail(422, 'Укажите текст работы.')
            result.update(add_attempt(db, actor, now, assignment, own, 'text', response.strip()))
        else:
            if action == 'record_in_person':
                result.update(add_attempt(db, actor, now, assignment, own, 'in_person', None))
            else:
                result.update(review_attempt(db, actor, now, assignment, own, data))
    if own is not None:
        db.execute('UPDATE coursework_recipients SET version=? WHERE assignment_id=? AND course_id=?',
                   (result['version'], assignment_id, own['course_id']))
    elif action == 'publish':
        db.execute('UPDATE coursework_assignments SET version=? WHERE id=?', (result['version'], assignment_id))
    if actor['role'] == 'staff':
        audit(db, actor, 'coursework.' + action, 'coursework_assignment', assignment_id, result['version'], now)
    db.execute('INSERT INTO coursework_receipts VALUES (?,?,?,?)',
               (actor['id'], request_key, fingerprint, json.dumps(result)))
    return result
