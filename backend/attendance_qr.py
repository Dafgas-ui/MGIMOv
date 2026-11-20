"""Short-lived lesson challenges. OS permissions remain SQLite's trust boundary."""
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, time

from . import attendance
from .auth.service import digest, valid_token
from .events import audit
from .schedule.service import MOSCOW


def lesson_window(lesson, now):
    midnight = int(datetime.combine(datetime.fromisoformat(lesson['date']).date(), time(), MOSCOW).timestamp())
    end = midnight + lesson['end_minute'] * 60
    if not midnight + lesson['start_minute'] * 60 <= now < end:
        attendance.fail(409, 'QR доступен только во время занятия.')
    return end


def context(db, actor, now, lesson_id):
    detail = attendance.staff_detail(db, actor, lesson_id)
    if not detail['can_mark']:
        attendance.fail(409, 'Требуется актуальный подтверждённый состав.')
    end = lesson_window(detail['lesson'], now)
    roster_version = max(event['version'] for event in detail['history'] if event['kind'] == 'roster')
    return detail, roster_version, end


def verify_challenge(db, row, now):
    if row['revoked_at'] is not None or not row['created_at'] <= now < row['expires_at']:
        attendance.fail(409, 'QR истёк или отозван. Запросите новый код.')
    issuer = db.execute('''SELECT u.id,u.role FROM users u JOIN sessions s ON s.user_id=u.id
        WHERE s.id=? AND u.id=? AND u.active=1 AND u.role='staff'
        AND s.revoked_at IS NULL AND s.created_at<=? AND s.expires_at>?''',
        (row['issuer_session'], row['actor_id'], now, now)).fetchone()
    if issuer is None:
        attendance.fail(409, 'QR больше не действует.')
    detail, roster_version, _ = context(db, issuer, now, row['lesson_id'])
    if (row['lesson_version'], row['roster_version'], row['roster_hash']) != (
            detail['lesson']['version'], roster_version, detail['candidate_token']):
        attendance.fail(409, 'Занятие или состав изменились. Запросите новый QR.')
    return detail


def issue(db, actor, now, lesson_id, data, origin):
    detail, roster_version, end = context(db, actor, now, lesson_id)
    old = db.execute('''SELECT * FROM attendance_qr_sessions
        WHERE issuer_session=? AND lesson_id=? AND request_key=?''',
        (actor['session_id'], lesson_id, data['request_key'])).fetchone()
    if old:
        if (old['expected_version'], old['lesson_version']) != (data['expected_version'], data['lesson_version']):
            attendance.fail(409, 'Ключ запроса уже использован для другой операции.')
        verify_challenge(db, old, now)
        # Only a hash is stored: a lost plaintext challenge cannot be recovered.
        return {'id': old['id'], 'expires_at': old['expires_at'], 'code_available': False}
    if (detail['version'], detail['lesson']['version']) != (data['expected_version'], data['lesson_version']):
        attendance.fail(409, 'Ведомость изменилась. Обновите данные.')
    # Prevent challenge spam even when the caller changes request keys.
    count = db.execute('SELECT count(*) FROM attendance_qr_sessions WHERE actor_id=? AND created_at>?',
                       (actor['id'], now-60)).fetchone()[0]
    if count >= 10:
        attendance.fail(429, 'Слишком много QR. Повторите через минуту.')
    db.execute('UPDATE attendance_qr_sessions SET revoked_at=? WHERE lesson_id=? AND revoked_at IS NULL',
               (now, lesson_id))
    token = secrets.token_urlsafe(32)
    key = uuid.uuid4().hex
    expires = min(now+60, end)
    db.execute('INSERT INTO attendance_qr_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)',
               (key, lesson_id, actor['id'], actor['session_id'], detail['lesson']['version'],
                roster_version, detail['candidate_token'], digest(token), data['request_key'],
                data['expected_version'], now, expires))
    audit(db, actor, 'attendance.qr.issue', 'lesson', lesson_id, detail['version'], now, required=True)
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    url = origin + '/#attendance-qr=' + token
    qr.add_data(url); qr.make(fit=True)
    return {'id': key, 'expires_at': expires, 'expires_in': expires-now,
            'code_available': True, 'url': url, 'matrix': qr.get_matrix()}


def close(db, actor, now, lesson_id, qr_id):
    attendance.teacher_lesson(db, actor, lesson_id)
    row = db.execute('SELECT * FROM attendance_qr_sessions WHERE id=? AND lesson_id=?', (qr_id, lesson_id)).fetchone()
    if row is None:
        attendance.fail(404)
    if row['revoked_at'] is None:
        db.execute('UPDATE attendance_qr_sessions SET revoked_at=? WHERE id=?', (now, qr_id))
        audit(db, actor, 'attendance.qr.close', 'lesson', lesson_id, None, now, required=True)
    return {'closed': True}


def student_context(db, actor, now, token):
    if actor['role'] != 'student':
        attendance.fail(403)
    if not valid_token(token):
        attendance.fail(422, 'Некорректный QR.')
    row = db.execute('SELECT * FROM attendance_qr_sessions WHERE token_hash=?', (digest(token),)).fetchone()
    if row is None:
        attendance.fail(404, 'QR недоступен.')
    detail = verify_challenge(db, row, now)
    student = next((student for student in detail['students'] if student['id'] == actor['id']), None)
    if student is None:
        attendance.fail(404, 'QR недоступен.')
    return row, detail, student


def preview(db, actor, now, token):
    row, detail, student = student_context(db, actor, now, token)
    return {'lesson_id': row['lesson_id'], 'subject': detail['lesson']['subject'],
            'date': detail['lesson']['date'], 'status': student['status'], 'expires_at': row['expires_at']}


def check_in(db, actor, now, token):
    row, detail, student = student_context(db, actor, now, token)
    manual = any(event['kind'] == 'mark' and event['payload']['student_id'] == actor['id']
                 for event in detail['history'])
    old = db.execute('SELECT outcome FROM attendance_qr_receipts WHERE qr_id=? AND student_id=?',
                     (row['id'], actor['id'])).fetchone()
    if old:
        outcome = old['outcome']
    else:
        outcome = 'manual_priority' if manual else 'already_present' if student['status'] == 'present' else 'present'
        version = detail['version']
        if outcome == 'present':
            version += 1
            db.execute('UPDATE attendance_journals SET version=? WHERE lesson_id=?', (version, row['lesson_id']))
            cursor = db.execute('INSERT INTO attendance_events VALUES (?,?,?,?,?,?,?)',
                (row['lesson_id'], version, 'qr_mark', actor['id'], now, 'QR self check-in',
                 json.dumps({'student_id': actor['id'], 'previous': student['status'],
                             'status': 'present', 'qr_id': row['id']})))
            if cursor.rowcount != 1:
                raise sqlite3.OperationalError('Required attendance event was not inserted')
        cursor = db.execute('INSERT INTO attendance_qr_receipts VALUES (?,?,?,?,?)',
                            (row['id'], actor['id'], now, outcome, version))
        if cursor.rowcount != 1:
            raise sqlite3.OperationalError('Required QR receipt was not inserted')
    own = attendance.student_detail(db, actor, row['lesson_id'])
    return {'lesson_id': row['lesson_id'], 'subject': own['subject'], 'date': own['date'],
            'status': own['status'], 'outcome': outcome, 'manual_mark': manual}
