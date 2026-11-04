"""Session-derived group timetable; only synthetic temporary databases."""
from datetime import datetime, timezone
from contextlib import closing
import json
import secrets
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.commands.seed_schedule import seed_schedule
from backend.schedule.service import change_lesson, ScheduleConflict, date_range
from backend.db import connection
from backend.config import ROOT
from tests import test_identity as identity

class ScheduleTests(unittest.TestCase):
    setUpClass=classmethod(identity.IdentityTests.setUpClass.__func__)
    tearDownClass=classmethod(identity.IdentityTests.tearDownClass.__func__)
    setUp=identity.IdentityTests.setUp
    bootstrap=identity.IdentityTests.bootstrap
    login=identity.IdentityTests.login
    logout=identity.IdentityTests.logout

    def prepare(self):
        seed_schedule(self.config,'2026-11-04')
        self.client.cookies.clear() # Do not reuse a real-clock session after freezing test time.
        self.app.state.auth_service.clock=lambda:datetime(2026,11,4,9,tzinfo=timezone.utc).timestamp()
        self.assertEqual(self.login().status_code,200)
    def get(self,**params):
        return self.client.get('/api/v1/me/schedule',params=params)

    def test_today_and_week_have_moscow_date_and_all_lesson_fields(self):
        self.prepare();r=self.get();self.assertEqual(r.status_code,200);data=r.json()
        self.assertEqual(data['today'],'2026-11-04');self.assertEqual(len(data['days']),1)
        lesson=data['days'][0]['lessons'][0]
        for key in ('date','start_minute','end_minute','subject','teacher','room','building','capacity','equipment','kind','status','changes'):self.assertIn(key,lesson)
        self.assertEqual(lesson['start_minute'],540);self.assertEqual(lesson['room'],'202')
        self.assertEqual(lesson['changes'][0]['fields'],['room_id'])
        week=self.get(view='week').json();self.assertEqual(len(week['days']),7)
        self.assertEqual([day['date'] for day in week['days']],date_range('2026-11-04','week'))

    def test_separate_clients_groups_and_logout_do_not_cross(self):
        self.prepare()
        with TestClient(self.app,base_url=self.config.origin) as b:
            self.assertEqual(self.login('student_b',client=b).status_code,200)
            a=self.get().json();other=b.get('/api/v1/me/schedule').json()
            self.assertNotEqual(a['group']['id'],other['group']['id'])
            self.assertTrue(all(x['id'].startswith('demo-a-') for d in a['days'] for x in d['lessons']))
            self.assertTrue(all(x['id'].startswith('demo-b-') for d in other['days'] for x in d['lessons']))
            self.logout();self.assertEqual(self.get().status_code,401)
            self.assertEqual(b.get('/api/v1/me/schedule').status_code,200)

    def test_anonymous_staff_revoked_and_spoofed_group(self):
        seed_schedule(self.config,'2026-11-04')
        self.assertEqual(self.get().status_code,401)
        self.login('staff_demo');self.assertEqual(self.get().status_code,403)
        self.login();
        for params in ({'group_id':'demo-b'},{'user_id':self.ids['student_b']},{'role':'staff'},{'date':'2026-02-30'},{'date':'9999-12-31'},{'view':'month'}):
            self.assertEqual(self.get(**params).status_code,422)
        self.assertEqual(self.client.get('/api/v1/me/schedule?date=2026-11-04&date=2026-11-05').status_code,422)
        self.assertEqual(self.client.get('/api/v1/me/schedule',headers={'X-Mgimov-User':self.ids['student_b']}).status_code,403)
        self.assertEqual(self.client.get('/api/v1/me/schedule/'+self.ids['student_b']).status_code,404)
        self.assertEqual(self.client.request('GET','/api/v1/me/schedule',content=json.dumps({'group_id':'demo-b'})).status_code,422)
        self.logout();self.assertEqual(self.get().status_code,401)

    def test_week_boundaries_and_moscow_midnight(self):
        self.prepare()
        self.assertEqual(self.get(view='week',date='2027-01-03').json()['days'][0]['date'],'2026-12-28')
        self.assertEqual(self.get(view='week',date='2028-02-29').json()['days'][-1]['date'],'2028-03-05')
        self.app.state.auth_service.clock=lambda:datetime(2026,11,4,21,1,tzinfo=timezone.utc).timestamp()
        # Re-login after advancing beyond the former session lifetime.
        self.login();self.assertEqual(self.get().json()['today'],'2026-11-05')

    def test_cancel_transfer_teacher_room_and_old_slot_markers(self):
        self.prepare()
        monday=self.get(date='2026-11-02').json()['days'][0]['lessons'][0]
        self.assertEqual(monday['status'],'cancelled')
        tuesday=self.get(date='2026-11-03').json()['days'][0]['lessons'][0]
        self.assertEqual(tuesday['placement'],'moved_from');self.assertEqual(tuesday['actual']['date'],'2026-11-05')
        thursday=self.get(date='2026-11-05').json()['days'][0]['lessons']
        self.assertEqual(len(thursday),2)
        changed=next(x for x in thursday if x['id']=='demo-a-3')
        self.assertEqual(changed['teacher'],'Анна Учебная (вымышленная)');self.assertEqual(changed['changes'][0]['fields'],['teacher_id'])
        current=self.get(date='2026-11-04').json()['days'][0]['lessons'][0]
        self.assertEqual(current['changes'][0]['before']['room'],'101');self.assertEqual(current['room'],'202')

    def test_changes_are_atomic_versioned_and_preserve_intermediate_moves(self):
        self.prepare()
        change_lesson(self.config,'demo-a-1',2,'Ещё один перенос',{'date':'2026-11-09'},2000000000)
        self.assertEqual(self.get(date='2026-11-05').json()['days'][0]['lessons'][-1]['placement'],'moved_from')
        with self.assertRaises(ScheduleConflict):change_lesson(self.config,'demo-a-1',2,'Stale',{'status':'cancelled'},2000000001)
        with self.assertRaises(sqlite3.IntegrityError):change_lesson(self.config,'demo-a-1',3,'Wrong room',{'room_id':'missing'},2000000001)
        with self.assertRaises(ValueError):change_lesson(self.config,'demo-a-1',3,'Wrong interval',{'start_minute':900,'end_minute':800},2000000001)
        with connection(self.config) as db:
            self.assertEqual(db.execute("SELECT version FROM lessons WHERE id='demo-a-1'").fetchone()[0],3)
            self.assertEqual(db.execute("SELECT count(*) FROM lesson_changes WHERE lesson_id='demo-a-1'").fetchone()[0],2)

    def test_empty_schedule_and_unpublished_write_api(self):
        self.login();r=self.get(view='week',date='2026-11-04');self.assertEqual(r.status_code,200)
        self.assertTrue(all(not day['lessons'] for day in r.json()['days']))
        self.prepare();r=self.get(view='week',date='2026-11-16');self.assertTrue(all(not day['lessons'] for day in r.json()['days']))
        csrf=self.client.cookies.get(self.config.csrf_cookie)
        self.assertEqual(self.client.post('/api/v1/me/schedule',json={'status':'cancelled'},headers={'Origin':self.config.origin,'X-CSRF-Token':csrf}).status_code,405)

    def test_local_cli_change_and_no_seed_overwrite(self):
        self.prepare()
        r=subprocess.run([sys.executable,'-B','-m','backend.commands.change_lesson','--db',str(self.path),'--lesson','demo-a-4','--version','1','--reason','Демо-отмена','--status','cancelled','--confirm-change'],cwd=ROOT,capture_output=True,timeout=10)
        self.assertEqual(r.returncode,0)
        self.assertEqual(self.get(date='2026-11-06').json()['days'][0]['lessons'][0]['status'],'cancelled')
        with self.assertRaises(ValueError):seed_schedule(self.config,'2026-11-04')

    def test_real_http_group_schedule_and_live_change(self):
        import os,socket,sysconfig,time
        import httpx
        self.prepare()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        origin=f'http://127.0.0.1:{port}'
        env=dict(os.environ,MGIMOV_DB_PATH=str(self.path),MGIMOV_ORIGIN=origin,PYTHONDONTWRITEBYTECODE='1')
        script="import site; site.addsitedir("+repr(sysconfig.get_path('purelib'))+"); import uvicorn; uvicorn.run('backend.app:app',host='127.0.0.1',port="+str(port)+",proxy_headers=False)"
        log=self.root/'schedule-http.log'
        with log.open('wb') as stream:
            server=subprocess.Popen([sys._base_executable,'-B','-c',script],cwd=ROOT,env=env,stdout=stream,stderr=stream,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                with httpx.Client(base_url=origin,trust_env=False,timeout=2) as a,httpx.Client(base_url=origin,trust_env=False,timeout=2) as b:
                    deadline=time.monotonic()+15
                    while time.monotonic()<deadline:
                        try:
                            if a.get('/api/health').status_code==200:break
                        except httpx.HTTPError:pass
                        time.sleep(.1)
                    else:self.fail('V4 HTTP server did not start')
                    self.assertEqual(a.get('/api/v1/me/schedule').status_code,401)
                    for client,name in ((a,'student_a'),(b,'student_b')):
                        csrf=client.get('/api/v1/auth/csrf').json()['csrf']
                        self.assertEqual(client.post('/api/v1/auth/login',json={'login':name,'password':self.credentials[name]},headers={'Origin':origin,'X-CSRF-Token':csrf}).status_code,200)
                    query={'date':'2026-11-04','view':'week'}
                    first=a.get('/api/v1/me/schedule',params=query);second=b.get('/api/v1/me/schedule',params=query)
                    self.assertEqual(first.status_code,200);self.assertEqual(second.status_code,200)
                    self.assertNotEqual(first.json()['group']['id'],second.json()['group']['id'])
                    change_lesson(self.config,'demo-a-2',2,'HTTP regression change',{'status':'cancelled'},int(time.time()))
                    updated=a.get('/api/v1/me/schedule',params={'date':'2026-11-04'}).json()
                    self.assertEqual(updated['days'][0]['lessons'][0]['status'],'cancelled')
                    self.assertEqual(b.get('/api/v1/me/schedule',params={'date':'2026-11-04'}).json()['days'][0]['lessons'][0]['status'],'scheduled')
            finally:server.terminate();server.wait(timeout=10)
        text=log.read_text(encoding='utf-8')
        for password in self.credentials.values():self.assertFalse(password in text)

if __name__=='__main__':unittest.main(verbosity=2)
