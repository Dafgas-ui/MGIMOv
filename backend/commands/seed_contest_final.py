"""Build a fresh, private and date-anchored final contest demo from synthetic data."""
import argparse
from datetime import date, datetime, time, timedelta
import os
from pathlib import Path
import secrets
import stat
import sys
from uuid import uuid4

from ..academics import attestation
from ..attendance import change as change_attendance, staff_detail
from ..brs import service as brs
from ..config import ROOT, Settings
from ..coursework import create_draft, execute as coursework_command
from ..db import connection
from ..migrations.manager import status
from ..schedule.service import MOSCOW, change_in_transaction
from . import seed_attestations
from .contest_demo_permissions import (
    PrivateDemoDirectory, check_windows_acl, check_windows_chain,
    create_windows_directory, windows_user_sid,
)

ANCHOR_DATE = date(2026, 11, 21)
STUDENTS = seed_attestations.STUDENTS
TEACHERS = seed_attestations.TEACHERS
DEANERY = seed_attestations.DEANERY
STAFF = TEACHERS + DEANERY + ('a01',)
ACCOUNTS = seed_attestations.ACCOUNTS
SCORE_OVERRIDES = {
    ('s01', 'law'): (10, 10, 10, 19),
    ('s02', 'law'): (10, 10, 10, 20),
    ('s03', 'law'): (11, 10, 10, 20),
}

BUILDINGS = (
    ('contest-a', 'Корпус «Север» (вымышленный)'),
    ('contest-b', 'Корпус «Юг» (вымышленный)'),
    ('contest-c', 'Корпус «Архив» (режим неизвестен)'),
    ('contest-d', 'Корпус «Форум» (вымышленный)'),
    ('contest-e', 'Корпус «Лаборатория» (вымышленный)'),
)
CAPACITIES = (16, 18, 20, 24, 28, 32, 40, 48, 64, 96)
EQUIPMENT = (
    'Доска', 'Проектор, доска', 'Компьютеры', 'Проектор, система аудио',
    'Доска, доступная мебель', 'Компьютеры, проектор', 'Проектор',
    'Документ-камера, доска', 'Компьютеры, доступная мебель', 'Проектор, доска, аудио',
)


def _timestamp(day, hour, minute=0):
    return int(datetime.combine(day, time(hour, minute), MOSCOW).timestamp())


def _validate_credentials(credentials):
    if (set(credentials) != set(ACCOUNTS) or len(set(credentials.values())) != len(ACCOUNTS)
            or any(not isinstance(value, str) or not 15 <= len(value) <= 128
                   for value in credentials.values())):
        raise ValueError('Provide twenty distinct synthetic passwords, 15–128 characters each.')


def seed(settings, credentials, anchor_date=ANCHOR_DATE):
    """Populate a fresh database privately, publishing it only after validation."""
    _validate_credentials(credentials)
    if type(anchor_date) is not date or not date(2020, 1, 1) <= anchor_date <= date(2099, 12, 30):
        raise ValueError('Provide an explicit supported Moscow calendar date.')
    database = Path(settings.database).resolve()
    scratch = (ROOT / '.tmp').resolve()
    if (database.exists() or database.suffix != '.sqlite3' or not database.is_relative_to(scratch)):
        raise ValueError('Choose a new .tmp/*.sqlite3 synthetic database.')
    staging = database.with_name(f'.{database.stem}.building-{uuid4().hex}.sqlite3')
    try:
        summary = _populate(Settings(database=staging), credentials, anchor_date)
        # Publish atomically without replacing a path created after preflight.
        # Windows rename refuses an existing destination; POSIX uses link's
        # atomic create-if-absent semantics and then removes the staging name.
        if os.name == 'nt':
            os.rename(staging, database)
        else:
            os.link(staging, database)
            staging.unlink()
        return summary
    finally:
        # Only remove this invocation's unpredictable staging name and SQLite sidecars.
        for suffix in ('', '-journal', '-wal', '-shm'):
            candidate = staging.with_name(staging.name + suffix)
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass


def _populate(settings, credentials, anchor_date):
    """Build and validate one private staging SQLite; never publishes it."""
    _validate_credentials(credentials)
    if type(anchor_date) is not date or not date(2020, 1, 1) <= anchor_date <= date(2099, 12, 30):
        raise ValueError('Provide an explicit supported Moscow calendar date.')
    database = Path(settings.database).resolve()
    scratch = (ROOT / '.tmp').resolve()
    if database.exists() or database.suffix != '.sqlite3' or not database.is_relative_to(scratch):
        raise ValueError('Choose a new .tmp/*.sqlite3 staging database.')

    # Keep the established 20-account/BRS/attestation fixture as the base.
    seed_attestations.seed(settings, credentials, today=anchor_date,
                           score_overrides=SCORE_OVERRIDES, no_exam_students={'s01', 's04'})
    now = _timestamp(anchor_date, 8)
    with connection(settings, write=True) as db:
        db.execute("INSERT INTO account_languages VALUES ('s06','en')")
        _add_rooms(db, anchor_date)
        lessons = _arrange_lessons(db, anchor_date, now)
        assignments = _add_coursework(db, anchor_date, now, lessons)
        _add_exam_slots(db, anchor_date, now)
        _add_attendance(db, anchor_date, now, lessons)
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Demo foreign-key check failed.')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Demo SQLite integrity check failed.')

    report = status(database)
    if report['state'] != 'managed' or report['pending']:
        raise ValueError('Demo migration verification failed.')
    return {
        'anchor_date': anchor_date.isoformat(),
        'accounts': len(ACCOUNTS), 'students': len(STUDENTS), 'staff': len(STAFF),
        'buildings': len(BUILDINGS), 'rooms': len(BUILDINGS) * len(CAPACITIES) + 1,
        'rooms_added': len(BUILDINGS) * len(CAPACITIES),
        'coursework_assignments': len(assignments), 'migrations': len(report['applied']),
    }


def _add_rooms(db, anchor_date):
    db.executemany('INSERT INTO buildings VALUES (?,?)', BUILDINGS)
    rooms = []
    for building_index, (building_id, _) in enumerate(BUILDINGS):
        prefix = chr(ord('A') + building_index)
        for index, capacity in enumerate(CAPACITIES, 1):
            rooms.append((f'{building_id}-{index:02d}', building_id, f'{prefix}{100 + index}',
                          capacity, EQUIPMENT[(index + building_index - 1) % len(EQUIPMENT)]))
    db.executemany('INSERT INTO rooms VALUES (?,?,?,?,?)', rooms)

    for weekday in range(7):
        db.execute('INSERT INTO building_open_hours VALUES (?,?,?,?)',
                   ('contest-a', weekday, 8 * 60, 20 * 60))
        if weekday == 6:
            db.execute('INSERT INTO building_open_hours VALUES (?,?,NULL,NULL)', ('contest-b', weekday))
            db.execute('INSERT INTO building_open_hours VALUES (?,?,NULL,NULL)', ('contest-e', weekday))
        else:
            db.execute('INSERT INTO building_open_hours VALUES (?,?,?,?)',
                       ('contest-b', weekday, 9 * 60, 18 * 60))
            db.execute('INSERT INTO building_open_hours VALUES (?,?,?,?)',
                       ('contest-e', weekday, 8 * 60, 19 * 60))
        db.execute('INSERT INTO building_open_hours VALUES (?,?,?,?)',
                   ('contest-d', weekday, 8 * 60, 21 * 60))
    # contest-c intentionally has no rules: the UI must report unknown, not closed.
    db.executemany('INSERT INTO room_unavailability VALUES (?,?,?,?,?)', [
        ('contest-temp-a09', 'contest-a-09', _timestamp(anchor_date, 8),
         _timestamp(anchor_date, 12), 'Synthetic temporary maintenance.'),
        ('contest-permanent-a10', 'contest-a-10', _timestamp(anchor_date, 0),
         None, 'Synthetic long-term closure.'),
        ('contest-temp-e05', 'contest-e-05', _timestamp(anchor_date + timedelta(days=1), 8),
         _timestamp(anchor_date + timedelta(days=1), 17), 'Synthetic temporary maintenance.'),
        ('contest-permanent-e10', 'contest-e-10', _timestamp(anchor_date, 0),
         None, 'Synthetic long-term closure.'),
    ])


def _arrange_lessons(db, anchor_date, now):
    plans = {
        ('g-a', 'law'): (anchor_date, 9, 10, 'contest-a-01'),
        ('g-b', 'methods'): (anchor_date, 9, 10, 'contest-a-02'),
        ('g-a', 'seminar'): (anchor_date, 10, 11, 'contest-a-03'),
        ('g-b', 'law'): (anchor_date + timedelta(days=1), 9, 10, 'contest-a-04'),
        ('g-a', 'methods'): (anchor_date + timedelta(days=1), 10, 11, 'contest-a-05'),
        ('g-b', 'seminar'): (anchor_date + timedelta(days=1), 11, 12, 'contest-a-06'),
        ('g-a', 'language'): (anchor_date - timedelta(days=3), 13, 14, 'contest-a-07'),
        ('g-b', 'language'): (anchor_date + timedelta(days=1), 14, 15, 'contest-a-08'),
    }
    result = {}
    for key, (day, start, end, room_id) in plans.items():
        rows = db.execute('SELECT id,version FROM lessons WHERE group_id=? AND subject_id=?', key).fetchall()
        if len(rows) != 1:
            raise ValueError(f'Expected one synthetic lesson for {key}.')
        lesson_id, version = rows[0]
        changed = change_in_transaction(db, lesson_id, version, 'Конкурсная демо-фикстура: дата и аудитория', {
            'date': day.isoformat(), 'start_minute': start * 60, 'end_minute': end * 60,
            'room_id': room_id,
        }, now)
        result[key] = {'id': lesson_id, 'version': changed['version']}

    key = ('g-a', 'seminar')
    row = result[key]
    cancelled = change_in_transaction(db, row['id'], row['version'],
        'Демонстрация отменённого занятия', {'status': 'cancelled'}, now)
    result[key]['version'] = cancelled['version']

    key = ('g-b', 'seminar')
    row = result[key]
    moved = change_in_transaction(db, row['id'], row['version'],
        'Демонстрация переноса занятия', {
            'start_minute': 12 * 60, 'end_minute': 13 * 60, 'room_id': 'contest-d-01',
        }, now)
    result[key]['version'] = moved['version']
    return result


def _add_coursework(db, anchor_date, now, lessons):
    admin = {'id': 'd01', 'role': 'staff'}
    teacher = {'id': 't01', 'role': 'staff'}
    student = {'id': 's01', 'role': 'student'}
    db.execute("INSERT INTO brs_capabilities VALUES ('d01','phase3-f','manage_teaching')")
    assignments = {}
    for group, due_day, title in (
        ('g-a', anchor_date + timedelta(days=2), 'Практика A · аргументированный вывод'),
        ('g-b', anchor_date + timedelta(days=3), 'Практика B · проверка источника'),
    ):
        row = brs.get(db, """SELECT o.id,l.id AS lesson_id,l.version FROM brs_offerings o
            JOIN brs_whole_plans p ON p.id=o.plan_id
            JOIN lessons l ON l.group_id=o.group_id
            WHERE o.group_id=? AND p.curriculum_id='law' AND l.subject_id='law' AND l.teacher_id='t01'""", group)
        expires = _timestamp(anchor_date + timedelta(days=7), 8)
        brs.grant_teaching(db, admin, now, row['id'], {
            'staff_id': teacher['id'], 'lesson_id': row['lesson_id'], 'lesson_version': row['version'],
            'expires_at': expires, 'can_confirm_final': False, 'event_code': None,
        })
        assignment = create_draft(db, teacher, now, row['id'], kind='practice', title=title,
            description='Только синтетический учебный материал. Кратко обоснуйте свой вывод.',
            due_at=_timestamp(due_day, 17, 30), mode='online')
        coursework_command(db, teacher, now, assignment, 'publish', expected_version=1,
            request_key=secrets.token_hex(16), data={'grading_mode': 'independent', 'max_points': 10})
        assignments[group] = assignment
    db.execute("DELETE FROM brs_capabilities WHERE staff_id='d01' AND capability='manage_teaching'")
    flow = brs.get(db, """SELECT c.id FROM brs_student_courses c
        JOIN brs_enrollments n ON n.course_id=c.id
        WHERE c.student_id='s01' AND n.offering_id=(SELECT offering_id FROM coursework_assignments WHERE id=?)
          AND n.ends_on IS NULL""", assignments['g-a'])
    coursework_command(db, student, now, assignments['g-a'], 'submit_text', expected_version=1,
        request_key=secrets.token_hex(16), data={'response': 'Синтетический ответ студента s01.'})
    return assignments


def _add_exam_slots(db, anchor_date, now):
    schedule_admin = {'id': 'd01', 'role': 'staff'}
    courses = {row['student_id']: row['id'] for row in db.execute(
        "SELECT student_id,id FROM brs_student_courses WHERE curriculum_id='law'")}
    def command(student, action, day, hour, room_id, *, slot_id=None, reason=None, examiner_id='t02'):
        course = courses[student]
        version = db.execute('SELECT count(*) FROM attestation_events WHERE course_id=?', (course,)).fetchone()[0]
        data = {'expected_version': version, 'request_key': secrets.token_hex(16)}
        if action == 'scheduled':
            data.update(starts_at=_timestamp(day, hour), ends_at=_timestamp(day, hour + 1),
                        examiner_id=examiner_id, room_id=room_id, commission=[])
        else:
            data.update(slot_id=slot_id, reason=reason)
        return attestation.execute(db, schedule_admin, now, course, action, data)

    assessment_day = anchor_date + timedelta(days=2)
    command('s02', 'scheduled', assessment_day, 14, 'contest-e-01')
    # S11 already has a scheduled appointment at anchor+2 from the base seed.
    # Cancel it and explicitly reassign the same unused attempt during the contest.
    course = courses['s11']
    previous = db.execute("""SELECT s.id FROM attestation_slots s
        WHERE s.course_id=? AND NOT EXISTS(SELECT 1 FROM attestation_events e
          WHERE e.slot_id=s.id AND e.kind IN ('cancelled','excused','unexcused','published','completed'))""",
        (course,)).fetchall()
    if len(previous) != 1:
        raise ValueError('Expected one active synthetic S11 appointment to move.')
    command('s11', 'cancelled', anchor_date + timedelta(days=2), 14, 'contest-e-03',
            slot_id=previous[0]['id'], reason='Демонстрация переноса экзамена')
    cancelled = command('s11', 'scheduled', assessment_day, 14, 'contest-e-03', examiner_id='t03')
    command('s11', 'cancelled', assessment_day, 8, 'contest-e-03',
            slot_id=cancelled['slot_id'], reason='Демонстрация отменённого испытания')
    command('s11', 'scheduled', anchor_date + timedelta(days=3), 14, 'contest-a-04', examiner_id='t03')


def _add_attendance(db, anchor_date, now, lessons):
    def confirm(key, marks):
        lesson = lessons[key]
        teacher_id = db.execute('SELECT teacher_id FROM lessons WHERE id=?', (lesson['id'],)).fetchone()[0]
        teacher = {'id': teacher_id, 'role': 'staff'}
        detail = staff_detail(db, teacher, lesson['id'])
        if detail['candidate'] is None:
            raise ValueError(f'Attendance roster is ambiguous for {key}: {detail["blocked_reason"]}')
        detail = change_attendance(db, teacher, now, lesson['id'], {
            'action': 'confirm', 'expected_version': detail['version'],
            'lesson_version': detail['lesson']['version'], 'reason': 'Подтверждение синтетического состава',
            'candidate_token': detail['candidate_token'],
        })
        for student_id, state in marks.items():
            detail = change_attendance(db, teacher, now, lesson['id'], {
                'action': 'mark', 'expected_version': detail['version'],
                'lesson_version': detail['lesson']['version'], 'reason': 'Демонстрационная отметка',
                'student_id': student_id, 'status': state,
            })
    confirm(('g-a', 'law'), {'s01': 'present', 's03': 'late'})
    confirm(('g-b', 'law'), {'s02': 'absent'})
    confirm(('g-a', 'language'), {'s05': 'late'})


def prepare(credentials, *, anchor_date=ANCHOR_DATE, parent=None):
    """Make a new private run; never opens an existing database for writes."""
    _validate_credentials(credentials)
    scratch = ROOT / '.tmp'
    if os.name == 'nt':
        sid = windows_user_sid()
        check_windows_chain(ROOT, sid)
        if not os.path.lexists(scratch):
            create_windows_directory(scratch, sid)
        check_windows_chain(scratch, sid)
    elif os.name == 'posix':
        scratch.mkdir(mode=0o700, exist_ok=True)
        info = scratch.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise PermissionError('Project .tmp must be an owned, non-redirected directory with mode 0700.')
    else:
        raise PermissionError('Unsupported filesystem permissions for contest demo.')

    parent = ROOT / Path(parent) if parent is not None else scratch
    if '..' in parent.parts or not parent.is_relative_to(scratch):
        raise ValueError('Demo runs must be created inside project .tmp.')
    if os.name == 'posix' and parent.resolve(strict=True) != parent:
        raise ValueError('Expected a project-local .tmp directory without redirects.')

    directory = PrivateDemoDirectory(parent)
    settings = Settings(database=directory.path / 'demo.sqlite3')
    credential_file = directory.path / 'credentials.dpapi' if os.name == 'nt' else None
    database_published = False
    try:
        directory.check_directory()
        summary = seed(settings, credentials, anchor_date)
        database_published = True
        directory.check_database(settings.database)
        if os.name == 'nt':
            from .demo_credentials import save
            if os.path.lexists(credential_file):
                raise FileExistsError('Credential file already exists in the new demo directory.')
            save(credential_file.relative_to(ROOT).as_posix(), credentials)
            check_windows_acl(credential_file, directory.user_sid, directory=False)
        directory.check_database(settings.database)
        return settings.database, credential_file, summary
    except Exception as error:
        # Never leave a database or credential file that a failed run could be
        # mistaken for. The run directory itself was created exclusively above.
        if credential_file is not None and os.path.lexists(credential_file):
            credential_file.unlink()
        if database_published:
            for suffix in ('', '-journal', '-wal', '-shm'):
                candidate = settings.database.with_name(settings.database.name + suffix)
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass
        raise RuntimeError(f'Demo not ready; inspect only this run directory: {directory.path}. {error}') from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-demo', action='store_true', required=True)
    parser.add_argument('--anchor-date', default=ANCHOR_DATE.isoformat())
    args = parser.parse_args()
    try:
        anchor = date.fromisoformat(args.anchor_date)
        if anchor.isoformat() != args.anchor_date:
            raise ValueError
    except ValueError:
        parser.error('--anchor-date must be an exact YYYY-MM-DD date.')
    if not sys.stdin.isatty() or (os.name != 'nt' and not sys.stdout.isatty()):
        parser.error('Run from a private interactive terminal; credentials must not be piped to a file.')
    credentials = {account: secrets.token_urlsafe(24) for account in ACCOUNTS}
    try:
        database, credential_file, summary = prepare(credentials, anchor_date=anchor)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    print(f'DEMO_DB={database}')
    print(f'DEMO_SUMMARY={summary}')
    if credential_file:
        print(f'DEMO_CREDENTIALS_DPAPI={credential_file}')
        print('Reveal passwords only in a private console with backend.commands.demo_credentials.')
    else:
        print('Synthetic credentials (store securely; do not record or share):')
        for account, password in credentials.items():
            print(f'{account}: {password}')


if __name__ == '__main__':
    main()
