"""Owned synthetic QR fixture; no external demo files or worktrees."""
import json
import socket
import sys
from datetime import datetime
from threading import Thread
import uvicorn
from backend.app import create_app
from backend.config import Settings
from backend.db import connection
from backend.schedule.service import MOSCOW
from tests.browser.coursework_server import setup_course
from tests.test_brs_foundation import BRSFoundationTests, temporary

def main():
    case=BRSFoundationTests()
    try:
        case.initialize(case.enterContext(temporary()),with_http=False)
        setup_course(case)
        case.now=int(datetime(2027,3,1,9,15,tzinfo=MOSCOW).timestamp())
        with connection(case.settings,write=True) as db:
            db.execute('UPDATE sessions SET expires_at=?',(case.now+86400,))
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));origin=f'http://127.0.0.1:{listener.getsockname()[1]}'
            app=create_app(Settings(case.settings.database,origin=origin));app.state.auth_service.clock=lambda:case.now
            sessions={who:[{'name':key,'value':value,'url':origin} for key,value in zip(
                (case.settings.session_cookie,case.settings.csrf_cookie),case.session_tokens[who])]
                for who in ('teacher','alice','bobby')}
            server=uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False))
            def controls():
                for line in sys.stdin:
                    if line.strip()!='expire':raise ValueError('Unknown fixture control')
                    case.now+=61;print('ok',flush=True)
                server.should_exit=True
            Thread(target=controls,daemon=True).start()
            print(json.dumps({'origin':origin,'sessions':sessions}),flush=True)
            server.run(sockets=[listener])
    finally:case.doCleanups()

if __name__=='__main__':main()
