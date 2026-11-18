"""V6 authorization, atomicity, throttling and real HTTP; temporary project-local SQLite."""
from concurrent.futures import ThreadPoolExecutor
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
import uuid
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from backend.auth.service import AuthError
from backend.commands.seed_requests import seed_requests
from backend.config import ROOT,Settings
from backend.db import connection
from backend.migrations.manager import update,status
from backend.requests.service import create_request,transition_request
from tests import test_identity as identity
from tests.test_foundation import temporary

class RequestTests(unittest.TestCase):
    setUpClass=classmethod(identity.IdentityTests.setUpClass.__func__)
    tearDownClass=classmethod(identity.IdentityTests.tearDownClass.__func__)
    setUp=identity.IdentityTests.setUp
    bootstrap=identity.IdentityTests.bootstrap
    login=identity.IdentityTests.login
    logout=identity.IdentityTests.logout

    def post(self,path,body,client=None,**headers):
        c=client or self.client
        return c.post(path,json=body,headers={'Origin':self.config.origin,'X-CSRF-Token':c.cookies.get(self.config.csrf_cookie) or '',**headers})
    def create(self,client=None,key=None,**content):
        return self.post('/api/v1/me/requests',{'type':'appeal','purpose':'','message':'Вымышленный вопрос','request_key':key or uuid.uuid4().hex,**content},client)
    def staff(self):
        with connection(self.config,write=True) as db:db.execute('INSERT INTO request_staff_scopes VALUES (?,?)',(self.ids['staff_demo'],'demo-f'))
        self.login('staff_demo')
    def decision(self,item,action='processing',comment='Демонстрационный комментарий'):
        return self.post('/api/v1/staff/requests/'+item['id']+'/decision',{'version':item['version'],'action':action,'comment':comment})
    def tokens(self):
        return {'token':self.client.cookies.get(self.config.session_cookie),'header':self.client.cookies.get(self.config.csrf_cookie),'cookie':self.client.cookies.get(self.config.csrf_cookie)}

    def test_create_own_list_details_and_server_author(self):
        self.login();r=self.create(type='study_certificate',purpose='Демонстрационное назначение')
        self.assertEqual(r.status_code,201);item=r.json();self.assertEqual(item['status'],'submitted')
        self.assertEqual(item['version'],1);self.assertEqual(item['actions'],['cancel'])
        self.assertEqual(item['history'][0]['actor_role'],'student')
        self.assertIn('no-store',r.headers['cache-control'])
        rows=self.client.get('/api/v1/me/requests').json();self.assertEqual(rows['items'][0]['id'],item['id'])
        self.assertEqual(self.client.get('/api/v1/me/requests/'+item['id']).json(),item)
        with connection(self.config) as db:
            row=db.execute('SELECT student_id,faculty_id FROM student_requests').fetchone()
            self.assertEqual(tuple(row),(self.ids['student_a'],'demo-f'))
            self.assertEqual(db.execute('SELECT actor_id FROM request_history').fetchone()[0],self.ids['student_a'])
        self.assertEqual(self.create(type='general_certificate',purpose='Вымышленное назначение').status_code,201)

    def test_two_students_idor_read_cancel_and_expected_owner(self):
        self.login();a=self.create().json()
        with TestClient(self.app,base_url=self.config.origin) as b:
            self.login('student_b',client=b);other=self.create(client=b).json()
            self.assertEqual(b.get('/api/v1/me/requests/'+a['id']).status_code,404)
            self.assertEqual(self.client.get('/api/v1/me/requests/'+other['id']).status_code,404)
            self.assertEqual(self.post('/api/v1/me/requests/'+other['id']+'/cancel',{'version':1}).status_code,404)
            self.assertEqual(self.client.get('/api/v1/me/requests').json()['items'][0]['id'],a['id'])
            self.assertEqual(b.get('/api/v1/me/requests').json()['items'][0]['id'],other['id'])
            self.assertEqual(self.client.get('/api/v1/me/requests',headers={'X-Mgimov-User':self.ids['student_b']}).status_code,403)
            self.logout();self.assertEqual(self.client.get('/api/v1/me/requests').status_code,401)
            self.assertEqual(b.get('/api/v1/me/requests').status_code,200)

    def test_anonymous_student_admin_and_role_spoof_denied(self):
        for path in ('/api/v1/me/requests','/api/v1/staff/requests','/api/v1/staff/requests/missing'):
            self.assertEqual(self.client.get(path).status_code,401)
        self.assertEqual(self.create().status_code,401)
        self.login();item=self.create().json()
        self.assertEqual(self.client.get('/api/v1/staff/requests').status_code,403)
        self.assertEqual(self.decision(item).status_code,403)
        for field,value in (('role','staff'),('student_id',self.ids['student_b']),('faculty_id','demo-f'),('status','approved'),('actor_id',self.ids['staff_demo'])):
            self.assertEqual(self.create(**{field:value}).status_code,422)
        self.staff();self.assertEqual(self.create().status_code,403)
        self.assertEqual(self.client.get('/api/v1/me/requests').status_code,403)
        self.assertEqual(self.post('/api/v1/me/requests/'+item['id']+'/cancel',{'version':1}).status_code,403)
        self.assertEqual(self.client.get('/api/v1/me/gradebook').status_code,403)

    def test_staff_scope_is_explicit_and_foreign_faculty_is_hidden(self):
        self.login();item=self.create().json();self.login('staff_demo')
        self.assertEqual(self.client.get('/api/v1/staff/requests').json()['items'],[])
        self.assertEqual(self.client.get('/api/v1/staff/requests/'+item['id']).status_code,404)
        self.assertEqual(self.decision(item).status_code,404)
        with connection(self.config,write=True) as db:
            db.execute("INSERT INTO faculties VALUES ('other-f','Иной вымышленный факультет')")
            db.execute('INSERT INTO request_staff_scopes VALUES (?,?)',(self.ids['staff_demo'],'other-f'))
        self.assertEqual(self.client.get('/api/v1/staff/requests').json()['items'],[])
        self.assertEqual(self.decision(item).status_code,404)
        with connection(self.config,write=True) as db:db.execute('INSERT INTO request_staff_scopes VALUES (?,?)',(self.ids['staff_demo'],'demo-f'))
        self.assertEqual(self.decision(item).status_code,200)
        detail=self.client.get('/api/v1/staff/requests/'+item['id']).json()
        self.assertEqual(set(detail['student']),{'full_name','study_group'})
        self.assertNotIn('student_id',detail);self.assertNotIn('password_hash',json.dumps(detail))

    def test_status_machine_approval_rejection_and_terminal_states(self):
        self.login();a=self.create().json();b=self.create().json();self.staff()
        self.assertEqual(self.decision(a,'approved').status_code,409)
        for item,target in ((a,'approved'),(b,'rejected')):
            processing=self.decision(item).json();self.assertEqual(processing['version'],2)
            final=self.decision(processing,target,'Демонстрационная причина решения').json()
            self.assertEqual(final['status'],target);self.assertEqual(final['actions'],[])
            self.assertEqual([x['version'] for x in final['history']],[1,2,3])
            self.assertEqual([x['actor_role'] for x in final['history']],['student','staff','staff'])
            self.assertEqual(final['history'][-1]['comment'],'Демонстрационная причина решения')
            self.assertEqual(self.decision(final,'processing').status_code,409)
        self.login();self.assertEqual(self.client.get('/api/v1/me/requests/'+b['id']).json()['history'][-1]['to_status'],'rejected')

    def test_cancel_only_submitted_then_terminal(self):
        self.login();a=self.create().json();b=self.create().json()
        path='/api/v1/me/requests/'+a['id']+'/cancel'
        cancelled=self.post(path,{'version':1}).json()
        self.assertEqual(cancelled['status'],'cancelled');self.assertEqual(cancelled['version'],2)
        self.assertEqual(self.post(path,{'version':2}).status_code,409)
        self.staff();self.assertEqual(self.decision(cancelled).status_code,409)
        self.assertEqual(self.decision(b).status_code,200)
        self.login();self.assertEqual(self.post('/api/v1/me/requests/'+b['id']+'/cancel',{'version':2}).status_code,409)

    def test_csrf_origin_content_type_and_staff_no_store(self):
        self.login();item=self.create().json()
        payload={'type':'appeal','purpose':'','message':'Демо','request_key':uuid.uuid4().hex}
        self.assertEqual(self.client.post('/api/v1/me/requests',json=payload).status_code,403)
        self.assertEqual(self.client.post('/api/v1/me/requests',json=payload,headers={'Origin':self.config.origin}).status_code,403)
        self.assertEqual(self.post('/api/v1/me/requests/'+item['id']+'/cancel',{'version':1},**{'X-CSRF-Token':'wrong'}).status_code,403)
        self.staff();path='/api/v1/staff/requests/'+item['id']+'/decision';body={'version':1,'action':'processing','comment':'Demo'}
        self.assertEqual(self.client.post(path,json=body,headers={'Origin':self.config.origin}).status_code,403)
        self.assertEqual(self.client.post(path,json=body,headers={'Origin':'https://foreign.invalid'}).status_code,403)
        self.assertEqual(self.client.post(path,content='plain',headers={'Origin':self.config.origin,'Content-Type':'text/plain'}).status_code,415)
        response=self.client.get('/api/v1/staff/requests');self.assertIn('no-store',response.headers['cache-control'])
        response=self.post(path,{**body,'role':'staff'});self.assertEqual(response.status_code,422)
        self.assertEqual(response.json(),{'detail':'Проверьте формат и длину полей.'})
        self.assertIn('no-store',response.headers['cache-control'])
        with connection(self.config) as db:self.assertEqual(db.execute('SELECT count(*) FROM request_history').fetchone()[0],1)

    def test_repeat_same_payload_is_idempotent_conflict_is_safe(self):
        self.login();key=uuid.uuid4().hex;first=self.create(key=key);retry=self.create(key=key)
        self.assertEqual([first.status_code,retry.status_code],[201,200]);self.assertEqual(first.json()['id'],retry.json()['id'])
        self.assertEqual(self.create(key=key,message='Другой текст').status_code,409)
        with connection(self.config) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM student_requests').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM request_history').fetchone()[0],1)

    def test_persistent_create_limit_is_per_student_includes_cancelled(self):
        self.login();key=uuid.uuid4().hex;first=self.create(key=key).json()
        self.post('/api/v1/me/requests/'+first['id']+'/cancel',{'version':1})
        for _ in range(4):self.assertEqual(self.create().status_code,201)
        self.assertEqual(self.create().status_code,429)
        self.assertEqual(self.create(key=key).status_code,200)
        self.login('student_b');self.assertEqual(self.create().status_code,201)

    def test_validation_sql_text_unknown_query_and_safe_errors(self):
        self.login();raw="<img src=x onerror=bad> '); DROP TABLE users; --"
        item=self.create(message=raw).json();self.assertEqual(item['message'],raw)
        for changes in ({'message':' '},{'message':'x'*2001},{'message':'bad\x00text'},{'type':'unknown'},{'purpose':'x'*201},{'type':'study_certificate','purpose':''},{'request_key':'bad'}):
            self.assertEqual(self.create(**changes).status_code,422)
        for path in ('/api/v1/me/requests?student_id=other','/api/v1/me/requests?offset=0&offset=1','/api/v1/me/requests?offset=-1'):
            self.assertEqual(self.client.get(path).status_code,422)
        self.assertEqual(self.client.request('GET','/api/v1/me/requests',content='{"role":"staff"}').status_code,422)
        with connection(self.config) as db:self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0],3)

    def test_daily_quota_and_window_expiry(self):
        self.login();now=[int(time.time())];self.app.state.auth_service.clock=lambda:now[0]
        for _ in range(20):
            now[0]+=601;self.assertEqual(self.create().status_code,201)
        self.assertEqual(self.create().status_code,429)
        now[0]+=86401;self.client.cookies.clear();self.login()
        self.assertEqual(self.create().status_code,201)

    def test_mutation_rechecks_live_identity_after_preflight(self):
        self.login();item=self.create().json();self.staff()
        from backend.requests import service
        original=service.preflight
        def disable(*args,**kwargs):
            original(*args,**kwargs)
            with connection(self.config,write=True) as db:db.execute('UPDATE users SET active=0 WHERE id=?',(self.ids['staff_demo'],))
        with patch('backend.requests.service.preflight',side_effect=disable):
            self.assertEqual(self.decision(item).status_code,401)
        with connection(self.config) as db:self.assertEqual(db.execute('SELECT count(*) FROM request_history').fetchone()[0],1)

    def test_staff_guard_and_query_no_scope_override(self):
        self.login();item=self.create().json();self.staff()
        path='/api/v1/staff/requests/'+item['id']+'/decision'
        self.assertEqual(self.client.get('/api/v1/staff/requests?faculty_id=other').status_code,422)
        self.assertEqual(self.client.get('/api/v1/staff/requests',headers={'Host':'foreign.invalid'}).status_code,400)
        self.assertEqual(self.client.get('/api/v1/staff/requests',headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)
        body={'version':1,'action':'processing','comment':'Demo'}
        duplicate=self.client.post(path,json=body,headers=[('Origin',self.config.origin),('X-CSRF-Token','a'),('X-CSRF-Token','b')])
        self.assertEqual(duplicate.status_code,400)
        self.assertIn('no-store',duplicate.headers['cache-control'])
        self.assertEqual(self.client.post(path,content='x'*8193,headers={'Origin':self.config.origin,'Content-Type':'application/json'}).status_code,413)
        self.assertEqual(self.decision(item,comment=' ').status_code,422)
        self.assertEqual(self.decision(item,comment='x'*1001).status_code,422)
        with connection(self.config,write=True) as db:db.execute('DELETE FROM request_staff_scopes WHERE staff_id=?',(self.ids['staff_demo'],))
        self.assertEqual(self.decision(item).status_code,404)

    def test_empty_and_pagination(self):
        self.login();self.assertEqual(self.client.get('/api/v1/me/requests').json(),{'items':[],'offset':0,'next_offset':None})
        # Build history over separate quota windows, without bypassing the service.
        now=[1800000000];self.app.state.auth_service.clock=lambda:now[0]
        self.client.cookies.clear();self.login()
        for i in range(21):
            now[0]+=650
            if i%5==0:self.login()
            if i==20:now[0]+=86401;self.client.cookies.clear();self.login()
            self.assertEqual(self.create().status_code,201)
        page=self.client.get('/api/v1/me/requests').json();self.assertEqual(len(page['items']),20);self.assertEqual(page['next_offset'],20)
        last=self.client.get('/api/v1/me/requests?offset=20').json();self.assertEqual(len(last['items']),1);self.assertIsNone(last['next_offset'])

    def test_concurrent_two_staff_decisions_have_one_winner(self):
        self.login();item=self.create().json();self.staff();tokens=self.tokens();service=self.app.state.auth_service
        # A second separately authenticated staff member with the same explicit scope.
        with connection(self.config,write=True) as db:
            db.execute("INSERT INTO users SELECT 'second-staff','second_staff',password_hash,'staff',1,created_at FROM users WHERE id=?",(self.ids['staff_demo'],))
            db.execute("INSERT INTO staff_profiles VALUES ('second-staff','Второй демо-сотрудник','Оператор')")
            db.execute("INSERT INTO request_staff_scopes VALUES ('second-staff','demo-f')")
        with TestClient(self.app,base_url=self.config.origin) as other:
            csrf=self.bootstrap(other);self.assertEqual(other.post('/api/v1/auth/login',json={'login':'second_staff','password':self.credentials['staff_demo']},headers={'Origin':self.config.origin,'X-CSRF-Token':csrf}).status_code,200)
            other_tokens={'token':other.cookies.get(self.config.session_cookie),'header':other.cookies.get(self.config.csrf_cookie),'cookie':other.cookies.get(self.config.csrf_cookie)}
            processing=self.decision(item).json()
            def change(pair):
                action,t=pair
                try:return transition_request(service,role='staff',request_id=item['id'],version=2,action=action,comment='Демо-решение',**t)['status']
                except AuthError as error:return error.status
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(change,[('approved',tokens),('rejected',other_tokens)]))
        self.assertEqual(results.count(409),1)
        with connection(self.config) as db:
            self.assertEqual(db.execute('SELECT version FROM student_requests').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT count(*) FROM request_history').fetchone()[0],3)
            winner=db.execute('SELECT actor_id FROM request_history WHERE version=3').fetchone()[0]
            self.assertIn(winner,(self.ids['staff_demo'],'second-staff'))

    def test_concurrent_same_create_has_single_row(self):
        self.login();tokens=self.tokens();key=uuid.uuid4().hex
        def send(_):return create_request(self.app.state.auth_service,kind='appeal',purpose='',message='Concurrent demo',key=key,**tokens)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(send,range(2)))
        self.assertEqual({r[0]['id'] for r in results},{results[0][0]['id']});self.assertEqual(sum(r[1] for r in results),1)
        with connection(self.config) as db:self.assertEqual(db.execute('SELECT count(*) FROM request_history').fetchone()[0],1)

    def test_history_failure_rolls_back_status(self):
        self.login();item=self.create().json();self.staff()
        with patch('backend.requests.service.history',side_effect=sqlite3.IntegrityError('synthetic failure')):
            response=self.decision(item);self.assertEqual(response.status_code,503)
            self.assertNotIn('synthetic',response.text)
        with connection(self.config) as db:
            self.assertEqual(tuple(db.execute('SELECT status,version FROM student_requests').fetchone()),('submitted',1))
            self.assertEqual(db.execute('SELECT count(*) FROM request_history').fetchone()[0],1)
        for sql in ("UPDATE request_history SET comment='changed'",'DELETE FROM request_history'):
            with self.assertRaises(sqlite3.IntegrityError):
                with connection(self.config,write=True) as db:db.execute(sql)

    def test_seed_four_statuses_no_overwrite_and_working_db_refused(self):
        seed_requests(self.config)
        with connection(self.config) as db:
            self.assertEqual({r[0] for r in db.execute('SELECT status FROM student_requests')},{'submitted','processing','approved','rejected'})
        with self.assertRaises(ValueError):seed_requests(self.config)
        with self.assertRaises(ValueError):seed_requests(Settings())

    def test_migration_existing_v5_preserves_data(self):
        with temporary() as root:
            definitions=root/'v5';definitions.mkdir()
            for sql in (ROOT/'backend/migrations').glob('000[1-4]_*.sql'):shutil.copyfile(sql,definitions/sql.name)
            path=root/'upgrade.sqlite3';update(path,create=True,directory=definitions)
            with connection(Settings(path),write=True) as db:db.execute("INSERT INTO app_metadata VALUES ('v5-preserved','yes')")
            update(path,backup=root/'backup.sqlite3');self.assertEqual(status(path)['applied'][-1],'0024_attendance')
            with connection(Settings(path)) as db:
                self.assertEqual(db.execute("SELECT value FROM app_metadata WHERE key='v5-preserved'").fetchone()[0],'yes')
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_real_http_two_students_staff_and_decision(self):
        seed_requests(self.config)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        origin=f'http://127.0.0.1:{port}';env=dict(os.environ,MGIMOV_DB_PATH=str(self.path),MGIMOV_ORIGIN=origin,PYTHONDONTWRITEBYTECODE='1')
        script="import site;site.addsitedir("+repr(sysconfig.get_path('purelib'))+");import uvicorn;uvicorn.run('backend.app:app',host='127.0.0.1',port="+str(port)+",proxy_headers=False)"
        log=self.root/'requests-http.log'
        with log.open('wb') as stream:
            server=subprocess.Popen([sys._base_executable,'-B','-c',script],cwd=ROOT,env=env,stdout=stream,stderr=stream,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                with httpx.Client(base_url=origin,trust_env=False,timeout=2) as a,httpx.Client(base_url=origin,trust_env=False,timeout=2) as b,httpx.Client(base_url=origin,trust_env=False,timeout=2) as staff:
                    deadline=time.monotonic()+15
                    while time.monotonic()<deadline:
                        try:
                            if a.get('/api/health').status_code==200:break
                        except httpx.HTTPError:pass
                        time.sleep(.1)
                    else:self.fail('V6 HTTP server did not start')
                    self.assertEqual(a.get('/api/v1/staff/requests').status_code,401)
                    for c,name in ((a,'student_a'),(b,'student_b'),(staff,'staff_demo')):
                        csrf=c.get('/api/v1/auth/csrf').json()['csrf']
                        self.assertEqual(c.post('/api/v1/auth/login',json={'login':name,'password':self.credentials[name]},headers={'Origin':origin,'X-CSRF-Token':csrf}).status_code,200)
                    key=uuid.uuid4().hex;body={'type':'appeal','purpose':'','message':'HTTP demo <b>literal</b>','request_key':key}
                    headers={'Origin':origin,'X-CSRF-Token':a.cookies.get(self.config.csrf_cookie)}
                    response=a.post('/api/v1/me/requests',json=body,headers=headers);self.assertEqual(response.status_code,201);item=response.json()
                    self.assertEqual(a.post('/api/v1/me/requests',json=body,headers=headers).status_code,200)
                    self.assertEqual(b.get('/api/v1/me/requests/'+item['id']).status_code,404)
                    self.assertEqual(a.get('/api/v1/staff/requests').status_code,403)
                    path='/api/v1/staff/requests/'+item['id']+'/decision';headers={'Origin':origin,'X-CSRF-Token':staff.cookies.get(self.config.csrf_cookie)}
                    for version,action in ((1,'processing'),(2,'approved')):
                        self.assertEqual(staff.post(path,json={'version':version,'action':action,'comment':'HTTP demo decision'},headers=headers).status_code,200)
                    final=a.get('/api/v1/me/requests/'+item['id']);self.assertEqual(final.json()['status'],'approved');self.assertEqual(len(final.json()['history']),3)
                    self.assertIn('no-store',staff.get('/api/v1/staff/requests').headers['cache-control'])
                    bridge={'origin':origin,'cookie':'; '.join(f'{k}={v}' for k,v in a.cookies.items()),'csrf':a.cookies.get(self.config.csrf_cookie),'user':a.get('/api/v1/auth/me').json()['user']}
                    result=subprocess.run(['node','tests/request-recovery-http.mjs'],input=json.dumps(bridge),text=True,capture_output=True,cwd=ROOT,timeout=20)
                    self.assertEqual(result.returncode,0,'AUD-02 frontend/HTTP recovery failed')
            finally:server.terminate();server.wait(timeout=10)
        for password in self.credentials.values():self.assertNotIn(password,log.read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
