"""MVP-01..03: real SQLite and HTTP regressions against a disposable source-local DB."""
from contextlib import contextmanager
import json,os,secrets,socket,subprocess,sys,sysconfig,time,unittest,uuid
import httpx
from backend.config import ROOT
from backend.db import connection
from backend.events import notify
from backend.requests.service import create_in_transaction,transition_in_transaction
from tests import test_mvp as fixtures

class RCRegressionTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.MVPTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.MVPTests.tearDownClass.__func__)
    setUp=fixtures.MVPTests.setUp
    login=fixtures.MVPTests.login
    post=fixtures.MVPTests.post

    def restricted_staff(self):
        with connection(self.settings,write=True) as db:
            db.execute('DELETE FROM request_staff_scopes WHERE staff_id=?',(self.ids['staff_demo'],))
            db.execute("INSERT INTO faculties VALUES ('rc-other','Другой вымышленный факультет')")
            db.execute('INSERT INTO request_staff_scopes VALUES (?,?)',(self.ids['staff_demo'],'rc-other'))

    def fingerprint(self):
        with connection(self.settings) as db:return {name:[tuple(row) for row in db.execute('SELECT * FROM '+name+' ORDER BY 1')] for name in ('notifications','lessons','lesson_changes','staff_audit')}

    def denied_pairs(self,staff,origin):
        lesson=staff.get('/api/v1/staff/lessons').json()['items'][0]
        body={k:lesson[k] for k in ('date','start_minute','end_minute','teacher_id','room_id','status','version')};body['reason']='Forbidden update'
        self.restricted_staff();before=self.fingerprint()
        pairs=[(self.post(staff,'/api/v1/staff/notifications',{'student_id':key,'title':'Test','body':'Test'},origin) for key in (self.ids['student_a'],str(uuid.uuid4()))),
               (self.post(staff,'/api/v1/staff/lessons/'+key,body,origin) for key in (lesson['id'],uuid.uuid4().hex))]
        for pair in pairs:
            a,b=list(pair);self.assertEqual(a.status_code,404);self.assertEqual((a.status_code,a.json()),(b.status_code,b.json()))
        self.assertTrue(before==self.fingerprint(),'Denied operations changed data or audit')

    def test_mvp01_identical_denials_no_side_effects(self):
        self.denied_pairs(self.login('staff_demo'),self.settings.origin)

    def old_certificate(self):
        now=int(time.time())
        with connection(self.settings,write=True) as db:
            users={row['login']:dict(row) for row in db.execute('SELECT id,login,role FROM users')}
            item,_=create_in_transaction(db,users['student_a'],'study_certificate','RC old page','RC certificate beyond first page',uuid.uuid4().hex,now-259200)
            item=transition_in_transaction(db,users['staff_demo'],item['id'],1,'processing','Synthetic processing',now-259200)
            item=transition_in_transaction(db,users['staff_demo'],item['id'],2,'approved','Synthetic approval',now-259200)
            for index in range(25):create_in_transaction(db,users['student_'+('abcd'[index%4])],'appeal','','Synthetic queue '+str(index),uuid.uuid4().hex,now-172800+index*700)
        return item

    def test_mvp02_old_detail_sign_deliver_scope_version_and_owner(self):
        item=self.old_certificate();staff=self.login('staff_demo');a=self.login('student_a');b=self.login('student_b')
        first=staff.get('/api/v1/staff/requests').json();self.assertNotIn(item['id'],[r['id'] for r in first['items']])
        second=staff.get('/api/v1/staff/requests',params={'offset':first['next_offset']}).json();self.assertIn(item['id'],[r['id'] for r in second['items']])
        detail=staff.get('/api/v1/staff/requests/'+item['id']).json();self.assertIsNone(detail['document'])
        self.assertEqual(self.post(staff,'/api/v1/staff/requests/'+item['id']+'/sign',{'version':2}).status_code,409)
        signed=self.post(staff,'/api/v1/staff/requests/'+item['id']+'/sign',{'version':3});self.assertEqual(signed.status_code,200);doc=signed.json()['id']
        self.assertEqual(staff.get('/api/v1/staff/requests/'+item['id']).json()['document']['id'],doc)
        self.assertEqual(a.get('/api/v1/me/documents/'+doc).status_code,404)
        self.assertEqual(self.post(staff,'/api/v1/staff/documents/'+doc+'/deliver').status_code,200)
        self.assertEqual(a.get('/api/v1/me/documents/'+doc).status_code,200);self.assertEqual(b.get('/api/v1/me/documents/'+doc).status_code,404)
        self.restricted_staff()
        self.assertEqual(staff.get('/api/v1/staff/requests/'+item['id']).status_code,404)
        self.assertEqual(self.post(staff,'/api/v1/staff/requests/'+item['id']+'/sign',{'version':3}).status_code,404)
        self.assertEqual(self.post(staff,'/api/v1/staff/documents/'+doc+'/deliver').status_code,404)

    def many_notifications(self):
        with connection(self.settings,write=True) as db:
            for i in range(110):notify(db,self.ids['student_a'],'RC '+str(i),'Synthetic notification','message',None,1700000000+i//3)
            return [r['id'] for r in db.execute('SELECT id FROM notifications WHERE user_id=? ORDER BY created_at DESC,id DESC',(self.ids['student_a'],))]

    def test_mvp03_cursor_complete_stable_reads_and_isolation(self):
        expected=self.many_notifications();a=self.login('student_a');b=self.login('student_b');seen=[];cursor=None
        while True:
            page=a.get('/api/v1/me/notifications',params={'cursor':cursor} if cursor else {}).json()
            seen.extend(row['id'] for row in page['items']);cursor=page['next_cursor']
            if not cursor:break
        self.assertEqual(seen,expected);self.assertEqual(len(seen),len(set(seen)));oldest=seen[-1]
        unread=a.get('/api/v1/me/notifications').json()['unread']
        self.assertEqual(self.post(b,'/api/v1/me/notifications/'+oldest+'/read').status_code,404)
        self.assertEqual(self.post(a,'/api/v1/me/notifications/'+oldest+'/read').status_code,200)
        self.assertEqual(a.get('/api/v1/me/notifications').json()['unread'],unread-1)
        first=a.get('/api/v1/me/notifications').json()
        with connection(self.settings,write=True) as db:notify(db,self.ids['student_a'],'New','New','message',None,2000000000)
        older=a.get('/api/v1/me/notifications',params={'cursor':first['next_cursor']}).json()
        self.assertEqual([r['id'] for r in older['items']],expected[100:])
        self.assertFalse(set(expected)&{r['id'] for r in b.get('/api/v1/me/notifications',params={'cursor':first['next_cursor']}).json()['items']})
        for query in ({'cursor':'invalid'},{'cursor':'x'*301},{'user_id':self.ids['student_b']}):self.assertEqual(a.get('/api/v1/me/notifications',params=query).status_code,422)

    @contextmanager
    def http_server(self, extra_staff_session=False):
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        origin=f'http://127.0.0.1:{port}';env={**os.environ,'MGIMOV_DB_PATH':str(self.path),'MGIMOV_ORIGIN':origin}
        code='import site;site.addsitedir('+repr(sysconfig.get_path('purelib'))+");import uvicorn;uvicorn.run('backend.app:app',host='127.0.0.1',port="+str(port)+',proxy_headers=False)'
        with (self.root/'rc-http.log').open('wb') as output:
            process=subprocess.Popen([sys._base_executable,'-B','-c',code],cwd=ROOT,env=env,stdout=output,stderr=output,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            clients={name:httpx.Client(base_url=origin,timeout=4,trust_env=False) for name in ('student_a','student_b','staff_demo')}
            if extra_staff_session:clients['staff_second']=httpx.Client(base_url=origin,timeout=4,trust_env=False)
            try:
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    try:
                        if clients['student_a'].get('/api/health').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:self.fail('RC HTTP startup failed')
                for name,client in clients.items():self.login('staff_demo' if name=='staff_second' else name,client,origin)
                yield origin,clients
            finally:
                for client in clients.values():client.close()
                process.terminate();process.wait(timeout=10)

    def test_rc_frontend_controllers_against_real_http(self):
        item=self.old_certificate();self.many_notifications()
        with self.http_server() as (origin,clients):
            bridge={'origin':origin,'request_id':item['id'],'users':{}}
            for name,client in clients.items():bridge['users'][name]={'cookie':'; '.join(f'{k}={v}' for k,v in client.cookies.items()),'csrf':client.cookies.get(self.settings.csrf_cookie),'user':client.get('/api/v1/auth/me').json()['user']}
            result=subprocess.run(['node','tests/rc-http.mjs'],cwd=ROOT,input=json.dumps(bridge),text=True,capture_output=True,timeout=25)
            self.assertEqual(result.returncode,0,'RC frontend / HTTP scenario failed: '+result.stderr[-1000:])
            self.denied_pairs(clients['staff_demo'],origin)

    def test_rc2_01_terminal_reply_conflict_two_real_http_sessions(self):
        with connection(self.settings,write=True) as db:
            actor=lambda name:dict(db.execute('SELECT id,login,role FROM users WHERE id=?',(self.ids[name],)).fetchone())
            now=int(time.time())
            item,_=create_in_transaction(db,actor('student_a'),'appeal','','Synthetic conflict',uuid.uuid4().hex,now)
            item=transition_in_transaction(db,actor('staff_demo'),item['id'],1,'processing','Synthetic processing',now)
        with self.http_server(extra_staff_session=True) as (origin,clients):
            def session(name):
                client=clients[name]
                return {'cookie':'; '.join(f'{k}={v}' for k,v in client.cookies.items()),
                        'csrf':client.cookies.get(self.settings.csrf_cookie),
                        'user':client.get('/api/v1/auth/me').json()['user']}
            a,b=session('staff_demo'),session('staff_second')
            self.assertTrue(a['cookie']!=b['cookie'],'Expected independent Staff sessions')
            bridge={'origin':origin,'request_id':item['id'],'a':a,'b':b,'student':session('student_b')}
            result=subprocess.run(['node','tests/rc2-01-http.mjs'],cwd=ROOT,input=json.dumps(bridge),text=True,capture_output=True,timeout=25)
            self.assertEqual(result.returncode,0,'RC2-01 scenario failed: '+result.stderr[-1500:])

if __name__=='__main__':unittest.main()
