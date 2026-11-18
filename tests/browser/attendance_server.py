"""Private synthetic attendance browser fixture using the real HTTP app."""
import json
import socket
import sys
from threading import Thread

import uvicorn

from backend.app import create_app
from backend.config import Settings
from tests.browser.coursework_server import setup_course
from tests.test_brs_foundation import BRSFoundationTests, temporary


def main():
    case = BRSFoundationTests()
    try:
        case.initialize(case.enterContext(temporary()), with_http=False)
        setup_course(case)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
            app = create_app(Settings(case.settings.database, origin=origin))
            app.state.auth_service.clock = lambda: case.now
            sessions = {who:[{'name':key,'value':value,'url':origin} for key,value in zip(
                (case.settings.session_cookie,case.settings.csrf_cookie),case.session_tokens[who])]
                for who in ('teacher','alice','bobby')}
            print(json.dumps({'origin':origin,'sessions':sessions}), flush=True)
            server = uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False))
            def stop():
                sys.stdin.read()
                server.should_exit = True
            Thread(target=stop,daemon=True).start()
            server.run(sockets=[listener])
    finally:
        case.doCleanups()


if __name__ == '__main__':
    main()
