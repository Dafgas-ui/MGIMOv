"""Explicit publication of a reviewed Coursework attempt under the BRS plan rules."""
from uuid import uuid4

from .brs import results
from .brs.service import fail, get
from .events import audit


def publication_context(db, actor, now, assignment, recipient):
    if assignment['grading_mode'] != 'brs':
        fail(409, 'Работа не привязана к мероприятию БРС.')
    key, event = results.context(db, actor, now, assignment['offering_id'], recipient['enrollment_id'],
                                 assignment['event_code'])
    if key[0] != recipient['course_id']:
        fail(404)
    return key, event


def publish_review(db, actor, now, assignment, recipient, data, *, context):
    if not db.in_transaction:
        raise RuntimeError('Coursework BRS publication requires a write transaction.')
    attempt, revision, expected = (data[key] for key in ('attempt_no', 'review_revision', 'expected_result_version'))
    if (type(attempt) is not int or attempt < 1 or type(revision) is not int or revision < 1
            or type(expected) is not int or expected < 0):
        fail(422, 'Укажите версию проверки и результата БРС.')
    course, enrollment = recipient['course_id'], recipient['enrollment_id']
    key, event = context
    review = get(db, """SELECT * FROM coursework_reviews WHERE assignment_id=? AND course_id=?
                          ORDER BY attempt_no DESC,revision DESC LIMIT 1""", assignment['id'], course)
    if (review['attempt_no'], review['revision']) != (attempt, revision) or review['decision'] != 'reviewed':
        fail(409, 'Проверка устарела или ещё не завершена.')
    last_attempt = db.execute('SELECT max(number) FROM coursework_attempts WHERE assignment_id=? AND course_id=?',
                              (assignment['id'], course)).fetchone()[0]
    if last_attempt != attempt:
        fail(409, 'Последняя попытка ещё не проверена.')
    points = review['points']
    if points is None or points > event['maximum']:
        fail(422, 'Укажите баллы в пределах максимума мероприятия.')
    result, attempts, version = results.stream(db, key)
    if version != expected:
        fail(409, 'Версия результата БРС изменилась.')

    prior = db.execute("""SELECT v.*,s.review_revision FROM coursework_brs_sources s
        JOIN brs_attempt_versions v ON v.id=s.version_id
        WHERE (s.assignment_id,s.course_id,s.attempt_no)=(?,?,?) ORDER BY v.revision_no DESC LIMIT 1""",
        (assignment['id'], course, attempt)).fetchone()
    if prior:
        if prior['review_revision'] >= revision or prior['points'] == points or not review['reason']:
            fail(409, 'Для исправления нужна новая проверка с изменённым баллом и основанием.')
        if prior['result_id'] != result or prior['enrollment_id'] != enrollment:
            fail(409, 'Публикация относится к другому зачислению.')
        brs_attempt, brs_revision, reason = prior['attempt_no'], prior['revision_no'] + 1, review['reason']
    else:
        brs_attempt, brs_revision, reason = len(attempts) + 1, 1, None
        results.check_next(event, attempts, brs_attempt)
        results.check_submission(db, enrollment, key, brs_attempt, event, now)
    if result is None:
        result = uuid4().hex
        db.execute('INSERT INTO brs_event_results VALUES (?,?,?,?)', (result, *key))
    version_id = uuid4().hex
    db.execute('INSERT INTO coursework_brs_sources VALUES (?,?,?,?,?)',
               (version_id, assignment['id'], course, attempt, revision))
    db.execute('INSERT INTO brs_attempt_versions VALUES (?,?,?,?,?,?,?,?,?,?)',
               (version_id, result, enrollment, brs_attempt, brs_revision, version+1, points, actor['id'], now, reason))
    audit(db, actor, 'brs.attempt.coursework', 'brs_attempt_version', version_id, version+1, now, required=True)
    return {'brs_version_id': version_id, 'brs_result_version': version+1}


def publications(db, assignment, course):
    return [dict(row) for row in db.execute("""SELECT s.attempt_no,s.review_revision,v.id AS brs_version_id,
        v.attempt_no AS brs_attempt_no,v.revision_no,v.points,v.published_at
        FROM coursework_brs_sources s JOIN brs_attempt_versions v ON v.id=s.version_id
        WHERE s.assignment_id=? AND s.course_id=? ORDER BY v.result_version""", (assignment, course))]
