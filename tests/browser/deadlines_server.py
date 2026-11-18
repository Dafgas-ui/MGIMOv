"""Synthetic sources for the Student academic-date browser scenario."""
import json
import secrets
import socket
import sys
from threading import Thread

import uvicorn

from backend.academics import attestation
from backend.app import create_app
from backend.config import Settings
from backend.coursework import create_draft, execute
from backend.db import connection
from tests.browser.coursework_server import setup_course
from tests.test_brs_foundation import BRSFoundationTests, temporary


def main():
    case = BRSFoundationTests()
    try:
        case.initialize(case.enterContext(temporary()), with_http=False)
        plan_data = case.plan()
        categories = [{'code':f'c{i}','title':f'Module {i}','maximum':maximum}
                      for i,maximum in enumerate((20,20,20,40))]
        plan_data['categories'] = categories
        plan_data['events'] = [{**row,'category_code':row['code'],'attempt_limit':1,'retake_policy':'none'}
                               for row in categories]
        case.plan = lambda:plan_data
        course, plan, offering = setup_course(case)
        teacher = {'id':'teacher','role':'staff'}
        admin = {'id':'admin','role':'staff'}
        with connection(case.settings, write=True) as db:
            for title, offset in [('Просроченная работа',1),('Ближайшая работа',86400),('Скрытый черновик',86400)]:
                work = create_draft(db, teacher, case.now, offering, kind='lab', title=title,
                    description='Синтетические условия', due_at=case.now+offset, mode='online')
                if title!='Скрытый черновик':
                    execute(db, teacher, case.now, work, 'publish', expected_version=1,
                        request_key=secrets.token_hex(16), data={})
            db.executemany('INSERT INTO attestation_permissions VALUES (?,?,?)',
                [('admin','f','schedule'),('teacher','f','examiner')])
            attestation.approve_policy(db, admin, case.now, plan, [])
            attestation.activate(db, admin, case.now, course)
            def command(db, kind, **data):
                version = db.execute('SELECT coalesce(max(version),0) FROM attestation_events WHERE course_id=?', (course,)).fetchone()[0]
                return attestation.execute(db, admin, case.now, course, kind,
                    dict(expected_version=version,request_key=secrets.token_hex(16),**data))
            slot = command(db, 'scheduled', starts_at=case.now+5*86400, ends_at=case.now+5*86400+3600,
                           examiner_id='teacher',room_id=None,commission=[])['slot_id']
            db.execute("INSERT INTO assessments VALUES ('legacy','law-s','a','2027-02-22','2027-02-23','scheduled')")
            db.execute("INSERT INTO student_assessments VALUES ('legacy-alice','alice','legacy')")
        case.now += 2
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0))
            origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
            app = create_app(Settings(case.settings.database, origin=origin))
            app.state.auth_service.clock = lambda:case.now
            sessions = {who:[{'name':key,'value':value,'url':origin} for key,value in zip(
                (case.settings.session_cookie,case.settings.csrf_cookie),case.session_tokens[who])]
                for who in ('alice','bobby')}
            print(json.dumps({'origin':origin,'sessions':sessions,'now':case.now,'course':course}),flush=True)
            server = uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False))
            def controls():
                nonlocal slot
                for line in sys.stdin:
                    if line.strip()=='advance-day':
                        case.now+=86400
                        # Keep synthetic sessions valid while moving the fixture clock.
                        with connection(case.settings,write=True) as db:
                            db.execute('UPDATE sessions SET expires_at=expires_at+86400')
                        print('ok',flush=True)
                        continue
                    with connection(case.settings,write=True) as db:
                        if line.strip() not in ('reschedule','cancel'):
                            raise ValueError('Unknown synthetic fixture command')
                        command(db, 'cancelled',slot_id=slot,reason='Synthetic cancellation')
                        if line.strip()=='reschedule':
                            slot = command(db, 'scheduled',starts_at=case.now+6*86400,ends_at=case.now+6*86400+3600,
                                           examiner_id='teacher',room_id=None,commission=[])['slot_id']
                    print('ok',flush=True)
                server.should_exit = True
            Thread(target=controls,daemon=True).start()
            server.run(sockets=[listener])
    finally:
        case.doCleanups()


if __name__ == '__main__':
    main()
