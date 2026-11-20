"""Loopback-only synthetic room-search fixture, cleaned up on stdin close."""
import json
import socket
import sys
from threading import Thread
import uvicorn
from backend.app import create_app
from backend.config import Settings
from backend.db import connection
from tests.test_brs_foundation import BRSFoundationTests, temporary

def main():
 case=BRSFoundationTests()
 try:
  case.initialize(case.enterContext(temporary()),with_http=False)
  with connection(case.settings,write=True) as db:
   db.execute("INSERT INTO building_open_hours VALUES ('building',0,480,1080)")
   db.execute("INSERT INTO rooms VALUES ('second','building','Room 2',30,'')")
   db.execute("INSERT INTO buildings VALUES ('unknown','Synthetic unknown access')")
   db.execute("INSERT INTO rooms VALUES ('third','unknown','Room 3',70,'')")
  with socket.socket() as listener:
   listener.bind(('127.0.0.1',0));origin=f'http://127.0.0.1:{listener.getsockname()[1]}'
   app=create_app(Settings(case.settings.database,origin=origin));app.state.auth_service.clock=lambda:case.now
   sessions={who:[{'name':key,'value':value,'url':origin} for key,value in zip((case.settings.session_cookie,case.settings.csrf_cookie),case.session_tokens[who])] for who in ('alice','bobby','teacher')}
   server=uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False))
   print(json.dumps({'origin':origin,'sessions':sessions}),flush=True)
   def controls():
    for line in sys.stdin:pass
    server.should_exit=True
   Thread(target=controls,daemon=True).start();server.run(sockets=[listener])
 finally:case.doCleanups()

if __name__=='__main__':main()
