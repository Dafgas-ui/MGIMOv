"""Start an isolated coursework acceptance server and pass synthetic sessions over stdout."""
import json
import secrets
import socket
import sys
from threading import Thread

import uvicorn

from backend.app import create_app
from backend.brs import models, service
from backend.config import Settings
from backend.coursework import create_draft, execute
from backend.db import connection
from backend.security.passwords import hash_password
from tests.test_brs_foundation import BRSFoundationTests, temporary


def setup_course(case):
    admin = {'id': 'admin', 'role': 'staff'}
    now = case.now
    with connection(case.settings, write=True) as db:
        plan = service.create_plan(db, admin, now, models.Plan(**case.plan()).model_dump())['id']
        service.lock_plan(db, admin, now, plan)
        offering = service.create_offering(db, admin, now, {'plan_id': plan, 'group_id': 'a'})['id']
        enrollment = service.enroll(db, admin, now, offering, {'student_id': 'alice', 'starts_on': '2027-02-01'})
        service.bind_teacher(db, admin, now, {'staff_id': 'teacher', 'teacher_id': 't', 'lesson_id': 'l'})
        service.grant_teaching(db, admin, now, offering, {
            'staff_id': 'teacher', 'lesson_id': 'l', 'lesson_version': 1,
            'expires_at': now + 60, 'can_confirm_final': True, 'event_code': None,
        })
        return enrollment['course_id'], plan, offering


def separate_student_works(db, now, plan, first_offering):
    admin = {'id': 'admin', 'role': 'staff'}
    teacher = {'id': 'teacher', 'role': 'staff'}
    db.execute("UPDATE student_profiles SET group_id='b' WHERE user_id='bobby'")
    db.execute("UPDATE lessons SET teacher_id='t' WHERE id='lb'")
    second_offering = service.create_offering(db, admin, now, {'plan_id': plan, 'group_id': 'b'})['id']
    service.enroll(db, admin, now, second_offering, {'student_id': 'bobby', 'starts_on': '2027-02-01'})
    service.grant_teaching(db, admin, now, second_offering, {
        'staff_id': 'teacher', 'lesson_id': 'lb', 'lesson_version': 1,
        'expires_at': now + 60, 'can_confirm_final': True, 'event_code': None,
    })
    for offering, title in ((first_offering, 'Работа только Alice'), (second_offering, 'Работа только Bobby')):
        assignment = create_draft(db, teacher, now, offering, kind='lab', title=title,
                                  description='Синтетическое задание', due_at=now+3600, mode='online')
        execute(db, teacher, now, assignment, 'publish',
                expected_version=1, request_key=secrets.token_hex(16), data={})


def main():
    case = BRSFoundationTests()
    try:
        case.initialize(case.enterContext(temporary()), with_http=False)
        course, plan, offering = setup_course(case)
        passwords = {who: secrets.token_urlsafe(24) for who in ('alice', 'bobby')}
        with connection(case.settings, write=True) as db:
            db.executemany('UPDATE users SET password_hash=? WHERE id=?',
                           [(hash_password(password), who) for who, password in passwords.items()])
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            origin = f'http://127.0.0.1:{port}'
            # IdentityGuard reads the configured origin, so install a new app for this socket.
            app = create_app(Settings(case.settings.database, origin=origin))
            app.state.auth_service.clock = lambda: case.now
            sessions = {
                who: [{'name': key, 'value': value, 'url': origin} for key, value in zip(
                    (case.settings.session_cookie, case.settings.csrf_cookie), case.session_tokens[who])]
                for who in ('teacher', 'alice', 'bobby')
            }
            print(json.dumps({'origin': origin, 'sessions': sessions, 'course': course,
                              'passwords': passwords}), flush=True)
            server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))

            def controls():
                for command in sys.stdin:
                    command = command.strip()
                    with connection(case.settings, write=True) as db:
                        if command in ('expire:alice', 'expire:teacher'):
                            db.execute('UPDATE sessions SET created_at=?,expires_at=? WHERE user_id=?',
                                       (case.now - 2, case.now - 1, command.split(':')[1]))
                        elif command == 'role:teacher':
                            db.execute("INSERT INTO student_profiles VALUES ('teacher','teacher','a')")
                            db.execute("UPDATE users SET role='student' WHERE id='teacher'")
                        elif command == 'renew:teacher':
                            db.execute("UPDATE sessions SET revoked_at=NULL WHERE user_id='teacher'")
                        elif command == 'separate-student-works':
                            separate_student_works(db, case.now, plan, offering)
                        elif command == 'long-coursework-title':
                            db.execute("UPDATE coursework_assignments SET title=? WHERE title='Работа только Alice'",
                                       ('ДлинноеНазваниеУчебнойРаботы' * 5,))
                        else:
                            raise ValueError('Unknown fixture command')
                    print('ok', flush=True)
                server.should_exit = True

            Thread(target=controls, daemon=True).start()
            server.run(sockets=[listener])
    finally:
        case.doCleanups()


if __name__ == '__main__':
    main()
