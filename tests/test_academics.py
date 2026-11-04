"""V5 scenarios on disposable SQLite; shared fixture setup, no duplicate V3 tests."""
from datetime import datetime,timezone
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import sysconfig
import time
import unittest
import httpx
from fastapi.testclient import TestClient
from backend.academics.service import record_result,academic_status,summarize
from backend.commands.seed_academics import seed_academics
from backend.config import ROOT,Settings
from backend.db import connection
from backend.migrations.manager import update,status
from tests import test_identity as identity
from tests.test_foundation import temporary

class AcademicTests(unittest.TestCase):
    setUpClass=classmethod(identity.IdentityTests.setUpClass.__func__)
    tearDownClass=classmethod(identity.IdentityTests.tearDownClass.__func__)
    setUp=identity.IdentityTests.setUp
    bootstrap=identity.IdentityTests.bootstrap
    login=identity.IdentityTests.login
    logout=identity.IdentityTests.logout

    def prepare(self):
        seed_academics(self.config,'2026-11-04')
        self.app.state.auth_service.clock=lambda:datetime(2026,11,4,12,tzinfo=timezone.utc).timestamp()
        self.assertEqual(self.login().status_code,200)
    def get(self,path='gradebook',**kwargs):return self.client.get('/api/v1/me/'+path,**kwargs)
    def attempt(self,key,count,outcome,grade=None,day='2026-11-04'):
        return record_result(self.config,key,count,outcome,grade,day,1793793600)

    def test_personal_gradebook_two_semesters_and_progress(self):
        self.prepare();r=self.get();self.assertEqual(r.status_code,200);data=r.json()
        self.assertIn('no-store',r.headers['cache-control'])
        self.assertEqual(len(data['semesters']),2)
        p=data['progress'];self.assertEqual(p,{'state':'ready','total':4,'completed':2,'upcoming':1,'debts':0,'pending':1,'percent':50})
        items=data['semesters'][1]['items']
        self.assertEqual({i['control'] for i in items},{'exam','credit','graded_credit'})
        self.assertEqual(next(i for i in items if i['id']=='academic-a-0')['attempts'][0]['grade'],5)
        self.assertEqual(self.get('progress').json()['progress'],p)
        self.assertEqual(len(self.get('exams').json()['exams']),5)
        self.assertEqual(self.get('debts').json()['debts'],[])

    def test_two_students_cannot_read_each_others_results(self):
        self.prepare();a=self.get().json()
        with TestClient(self.app,base_url=self.config.origin) as b:
            self.assertEqual(self.login('student_b',client=b).status_code,200)
            other=b.get('/api/v1/me/gradebook').json()
            self.assertNotEqual(a['semesters'][1]['items'],other['semesters'][1]['items'])
            self.assertEqual(other['progress']['debts'],1);self.assertEqual(other['progress']['completed'],1)
            self.assertEqual(other['progress']['percent'],25)
            self.assertEqual(len(other['debts']),1)
            for data,own,foreign in ((a,'a','b'),(other,'b','a')):
                self.assertTrue(all(i['id'].startswith('academic-'+own) for s in data['semesters'] for i in s['items']))
                self.assertNotIn('academic-'+foreign,json.dumps(data))
            self.logout();self.assertEqual(self.get().status_code,401)
            self.assertEqual(b.get('/api/v1/me/gradebook').status_code,200)

    def test_anonymous_staff_idor_query_json_and_mutations(self):
        paths=('gradebook','exams','debts','progress')
        for path in paths:self.assertEqual(self.get(path).status_code,401)
        self.login('staff_demo')
        for path in paths:self.assertEqual(self.get(path).status_code,403)
        self.login()
        for path in paths:
            for query in ({'student_id':self.ids['student_b']},{'user_id':"' OR 1=1--"},{'group_id':'demo-b'},{'role':'staff'}):
                self.assertEqual(self.get(path,params=query).status_code,422)
            self.assertEqual(self.get(path,headers={'X-Mgimov-User':self.ids['student_b']}).status_code,403)
            self.assertEqual(self.client.request('GET','/api/v1/me/'+path,content='{"student_id":"other"}').status_code,422)
            for method in ('POST','PUT','PATCH','DELETE'):
                r=self.client.request(method,'/api/v1/me/'+path,json={'grade':5},headers={'Origin':self.config.origin,'X-CSRF-Token':self.client.cookies.get(self.config.csrf_cookie)})
                self.assertEqual(r.status_code,405)
        self.assertEqual(self.get('gradebook/'+self.ids['student_b']).status_code,404)

    def test_retake_closes_debt_without_incrementing_total(self):
        self.prepare();self.login('student_b')
        before=self.get().json();self.assertEqual(before['progress']['total'],4)
        self.attempt('academic-b-0',1,'graded',4)
        after=self.get().json();self.assertEqual(after['progress']['total'],4)
        self.assertEqual(after['progress']['completed'],2);self.assertEqual(after['progress']['debts'],0)
        record=next(x for s in after['semesters'] for x in s['items'] if x['id']=='academic-b-0')
        self.assertEqual([a['grade'] for a in record['attempts']],[2,4])
        self.assertEqual(record['status'],'passed')
        with self.assertRaises(ValueError):self.attempt('academic-b-0',2,'graded',2)

    def test_missing_future_not_held_and_explicit_deadline(self):
        self.prepare()
        with connection(self.config,write=True) as db:
            db.execute("UPDATE assessments SET scheduled_on='2026-11-01',status='completed',deadline_on=NULL WHERE id='academic-a-3'")
        item=lambda:next(x for s in self.get().json()['semesters'] for x in s['items'] if x['id']=='academic-a-3')
        self.assertEqual(item()['status'],'ungraded');self.assertEqual(self.get().json()['progress']['debts'],0)
        with connection(self.config,write=True) as db:db.execute("UPDATE assessments SET deadline_on='2026-11-03' WHERE id='academic-a-3'")
        self.assertEqual(item()['status'],'overdue');self.assertEqual(self.get().json()['progress']['debts'],1)
        with connection(self.config,write=True) as db:db.execute("UPDATE assessments SET status='not_held' WHERE id='academic-a-3'")
        self.assertEqual(item()['status'],'not_held');self.assertEqual(self.get().json()['progress']['debts'],0)
        self.assertEqual(len(self.get().json()['upcoming']),1)

    def test_credit_failure_absence_and_retake_rules(self):
        self.prepare()
        with connection(self.config,write=True) as db:db.execute("UPDATE assessments SET status='completed',scheduled_on='2026-11-02' WHERE id='academic-a-3'")
        self.attempt('academic-a-3',0,'absent');self.assertEqual(self.get().json()['progress']['debts'],1)
        self.attempt('academic-a-3',1,'graded',3);self.assertEqual(self.get().json()['progress']['completed'],3)
        with self.assertRaises(ValueError):self.attempt('academic-a-1',1,'graded',4)
        with connection(self.config,write=True) as db:
            db.execute("UPDATE assessments SET status='completed',scheduled_on='2026-11-02' WHERE id='academic-b-1'")
        self.attempt('academic-b-1',0,'fail');self.login('student_b');self.assertEqual(self.get().json()['progress']['debts'],2)
        self.attempt('academic-b-1',1,'pass');self.assertEqual(self.get().json()['progress']['debts'],1)

    def test_no_data_and_optional_cancelled_progress(self):
        self.login();data=self.get().json();self.assertEqual(data['semesters'],[])
        self.assertEqual(data['progress']['state'],'no_data');self.assertIsNone(data['progress']['percent'])
        self.assertEqual(summarize([{'required':True,'status':'cancelled'},{'required':False,'status':'passed'}])['total'],0)
        self.assertEqual(summarize([{'required':True,'status':'passed'},{'required':True,'status':'upcoming'}])['percent'],50)
        # No invented debt for a scheduled date in the past with no completion/deadline.
        self.assertEqual(academic_status({'event_status':'scheduled','scheduled_on':'2020-01-01','deadline_on':None},[],'2026-11-04'),'unscheduled')
        self.assertEqual(academic_status({'event_status':'cancelled'},[{'outcome':'graded','grade':2}],'2026-11-04'),'cancelled')
        event={'event_status':'completed','scheduled_on':'2026-11-01','deadline_on':'2026-11-04'}
        self.assertEqual(academic_status(event,[],'2026-11-04'),'ungraded')
        self.assertEqual(academic_status(event,[],'2026-11-05'),'overdue')

    def test_local_validation_integrity_and_history_unchanged_on_rejection(self):
        self.prepare()
        for outcome,grade,day,count in [('graded',6,'2026-11-04',1),('graded',True,'2026-11-04',1),('graded',3,'2027-01-01',1),('graded',3,'2026-02-30',1),('graded',3,'2026-11-04',0),('pass',None,'2026-11-04',1)]:
            with self.assertRaises(ValueError):self.attempt('academic-b-0',count,outcome,grade,day)
        with self.assertRaises(ValueError):self.attempt('missing',0,'graded',4)
        with self.assertRaises(ValueError):self.attempt('academic-a-2',0,'graded',4)
        with self.assertRaises(ValueError):record_result(Settings(),'',0,'pass',None,'2026-11-04')
        with connection(self.config) as db:self.assertEqual(db.execute("SELECT count(*) FROM assessment_attempts WHERE assignment_id='academic-b-0'").fetchone()[0],1)
        for sql,params in [("UPDATE assessment_attempts SET grade=5 WHERE assignment_id=?",('academic-b-0',)),("DELETE FROM assessment_attempts WHERE assignment_id=?",('academic-b-0',)),('INSERT INTO student_assessments VALUES (?,?,?)',('wrong',self.ids['student_a'],'academic-b-0'))]:
            with self.assertRaises(sqlite3.IntegrityError):
                with connection(self.config,write=True) as db:db.execute(sql,params)

    def test_migration_existing_v4_database_and_no_data_loss(self):
        with temporary() as root:
            definitions=root/'v4';definitions.mkdir()
            for name in ('0001_initial','0002_identity','0003_schedule'):
                shutil.copyfile(ROOT/'backend/migrations'/(name+'.sql'),definitions/(name+'.sql'))
            path=root/'upgrade.sqlite3';update(path,create=True,directory=definitions)
            with connection(Settings(path),write=True) as db:db.execute("INSERT INTO app_metadata VALUES ('preserve-v4','yes')")
            backup=root/'backup.sqlite3';update(path,backup=backup)
            self.assertEqual(status(path)['applied'][-1],'0004_academics');self.assertTrue(backup.exists())
            with connection(Settings(path)) as db:
                self.assertEqual(db.execute("SELECT value FROM app_metadata WHERE key='preserve-v4'").fetchone()[0],'yes')
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(update(path)['pending'],[])

    def test_constraints_reject_wrong_program_control_and_attempt_sequence(self):
        self.prepare()
        statements=[
            ("INSERT INTO assessments VALUES ('wrong-program','academic-a-0','demo-b',NULL,NULL,'completed')",()),
            ("INSERT INTO assessment_attempts VALUES ('wrong-count','academic-b-0',3,'graded',4,'2026-11-04',1793793600)",()),
            ("INSERT INTO assessment_attempts VALUES ('wrong-control','academic-a-1',2,'graded',4,'2026-11-04',1793793600)",()),
            ("INSERT INTO assessment_attempts VALUES ('wrong-null','academic-b-0',2,'graded',NULL,'2026-11-04',1793793600)",()),
        ]
        for sql,params in statements:
            with self.assertRaises(sqlite3.IntegrityError):
                with connection(self.config,write=True) as db:db.execute(sql,params)

    def test_outside_semester_has_no_current_progress_but_keeps_history(self):
        self.prepare();self.client.cookies.clear()
        self.app.state.auth_service.clock=lambda:datetime(2027,1,1,9,tzinfo=timezone.utc).timestamp()
        self.login();data=self.get().json()
        self.assertIsNone(data['current_semester']);self.assertEqual(data['progress']['state'],'no_data')
        self.assertIsNone(data['progress']['percent']);self.assertEqual(len(data['semesters']),2)

    def test_seed_and_command_are_explicit_no_overwrite(self):
        self.prepare()
        with self.assertRaises(ValueError):seed_academics(self.config)
        r=subprocess.run([sys.executable,'-B','-m','backend.commands.record_result','--db',str(self.path),'--assignment','academic-b-0','--expected-attempts','1','--outcome','graded','--grade','4','--performed-on','2026-11-04','--confirm-demo'],cwd=ROOT,capture_output=True,timeout=10)
        self.assertEqual(r.returncode,0)
        self.login('student_b');self.assertEqual(self.get().json()['progress']['debts'],0)

    def test_real_http_personal_results_retake_and_method_denied(self):
        self.prepare()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        origin=f'http://127.0.0.1:{port}';env=dict(os.environ,MGIMOV_DB_PATH=str(self.path),MGIMOV_ORIGIN=origin,PYTHONDONTWRITEBYTECODE='1')
        script="import site;site.addsitedir("+repr(sysconfig.get_path('purelib'))+");import uvicorn;from backend.app import app;app.state.auth_service.clock=lambda:1793793600;uvicorn.run(app,host='127.0.0.1',port="+str(port)+",proxy_headers=False)"
        log=self.root/'academics-http.log'
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
                    else:self.fail('V5 HTTP server did not start')
                    self.assertEqual(a.get('/api/v1/me/gradebook').status_code,401)
                    for client,login in ((a,'student_a'),(b,'student_b')):
                        csrf=client.get('/api/v1/auth/csrf').json()['csrf']
                        self.assertEqual(client.post('/api/v1/auth/login',json={'login':login,'password':self.credentials[login]},headers={'Origin':origin,'X-CSRF-Token':csrf}).status_code,200)
                    self.assertEqual(a.get('/api/v1/me/progress').json()['progress']['completed'],2)
                    self.assertEqual(len(b.get('/api/v1/me/debts').json()['debts']),1)
                    self.attempt('academic-b-0',1,'graded',4)
                    self.assertEqual(b.get('/api/v1/me/debts').json()['debts'],[])
                    self.assertEqual(a.get('/api/v1/me/progress').json()['progress']['completed'],2)
                    self.assertEqual(a.get('/api/v1/me/gradebook',params={'student_id':self.ids['student_b']}).status_code,422)
                    self.assertEqual(a.post('/api/v1/me/gradebook',json={'grade':5},headers={'Origin':origin}).status_code,405)
            finally:server.terminate();server.wait(timeout=10)
        for password in self.credentials.values():self.assertNotIn(password,log.read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
