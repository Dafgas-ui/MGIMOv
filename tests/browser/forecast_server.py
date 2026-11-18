"""Private synthetic forecast browser fixture, real sessions and Uvicorn."""
import json
import secrets
import socket
import sys
from threading import Thread
import uvicorn
from backend.app import create_app
from backend.config import Settings
from backend.db import connection
from backend.brs import results
from tests import forecast_fixture as fixture
from tests.test_brs_foundation import BRSFoundationTests,temporary


def main():
    case=BRSFoundationTests()
    try:
        case.initialize(case.enterContext(temporary()),with_http=False)
        courses=fixture.prepare(case)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));origin=f'http://127.0.0.1:{listener.getsockname()[1]}'
            app=create_app(Settings(case.settings.database,origin=origin));app.state.auth_service.clock=lambda:case.now
            sessions={who:[{'name':key,'value':value,'url':origin} for key,value in zip(
                (case.settings.session_cookie,case.settings.csrf_cookie),case.session_tokens[who])]
                for who in ('alice','bobby','teacher')}
            print(json.dumps({'origin':origin,'sessions':sessions}),flush=True)
            server=uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False))
            def controls():
                for command in sys.stdin:
                    with connection(case.settings,write=True) as db:
                        if command.strip()=='publish':
                            for course in courses.values():fixture.total(db,case,course,49)
                        elif command.strip()=='correct':
                            for course in courses.values():
                                state=results.staff_result(db,fixture.TEACHER,case.now,course['offering'],course['id'],'c2')
                                results.change_result(db,fixture.TEACHER,case.now,course['offering'],course['id'],'c2',1,
                                    {'request_key':secrets.token_hex(16),'expected_result_version':state['result_version'],
                                     'points':10,'reason':'Synthetic correction'},command='correct')
                        else:raise ValueError('Unknown fixture control')
                    print('ok',flush=True)
                server.should_exit=True
            Thread(target=controls,daemon=True).start();server.run(sockets=[listener])
    finally:case.doCleanups()


if __name__=='__main__':main()
