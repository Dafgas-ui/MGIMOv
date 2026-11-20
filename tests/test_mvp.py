"""Four independent sessions, real SQLite, scoped Staff and protected demo documents."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,os,secrets,shutil,socket,sqlite3,subprocess,sys,sysconfig,time,unittest,uuid
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from backend.app import create_app,ASSETS
from backend.config import ROOT,Settings
from backend.db import connection
from backend.commands.seed_mvp_demo import seed,ACCOUNTS
from backend.commands.create_invitation import issue
from backend.security.passwords import hash_password,verify_password
from tests.test_foundation import temporary

class MVPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=temporary();cls.template_root=cls.context.__enter__();cls.template=cls.template_root/'template.sqlite3'
        cls.credentials={n:secrets.token_urlsafe(24) for n in ACCOUNTS};cls.ids=seed(Settings(cls.template),cls.credentials)
        cls.dummy=hash_password(secrets.token_urlsafe(24))
    @classmethod
    def tearDownClass(cls):cls.context.__exit__(None,None,None)
    def setUp(self):
        self.context_case=temporary();self.root=self.context_case.__enter__();self.path=self.root/'case.sqlite3';shutil.copyfile(self.template,self.path)
        self.settings=Settings(self.path)
        with patch('backend.auth.service.passwords.hash_password',return_value=self.dummy):self.app=create_app(self.settings)
        self.clients={n:TestClient(self.app,base_url=self.settings.origin) for n in ACCOUNTS}
        self.addCleanup(self.context_case.__exit__,None,None,None)
        for client in self.clients.values():self.addCleanup(client.close)
    def login(self,name,client=None,origin=None):
        client=client or self.clients[name];origin=origin or self.settings.origin
        csrf=client.get('/api/v1/auth/csrf').json()['csrf']
        self.assertEqual(client.post('/api/v1/auth/login',json={'login':name,'password':self.credentials[name]},headers={'Origin':origin,'X-CSRF-Token':csrf}).status_code,200)
        return client
    def post(self,client,path,body=None,origin=None):
        return client.post(path,json={} if body is None else body,headers={'Origin':origin or self.settings.origin,'X-CSRF-Token':client.cookies.get(self.settings.csrf_cookie,'')})
    def test_four_students_personal_data_and_seed_guard(self):
        groups=set();documents=set()
        for name in ACCOUNTS[:4]:
            client=self.login(name);profile=client.get('/api/v1/me/profile').json();groups.add(profile['profile']['study_group'])
            self.assertEqual(profile['user']['id'],self.ids[name])
            self.assertTrue(client.get('/api/v1/me/gradebook').json()['semesters'])
            schedule=client.get('/api/v1/me/schedule?view=week').json();self.assertTrue(any(d['lessons'] for d in schedule['days']))
            own=client.get('/api/v1/me/documents').json()['items'];self.assertEqual(len(own),1);documents.add(own[0]['id'])
            self.assertGreater(client.get('/api/v1/me/notifications').json()['unread'],0)
        self.assertEqual(len(groups),4);self.assertEqual(len(documents),4)
        before=hashlib.sha256(self.path.read_bytes()).digest()
        with self.assertRaises(ValueError):seed(self.settings,self.credentials)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(),before)
        with connection(self.settings) as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            for row in db.execute('SELECT login,password_hash FROM users'):self.assertTrue(verify_password(row['password_hash'],self.credentials[row['login']]))
    def scenario(self,clients,origin):
        for name,client in clients.items():self.login(name,client,origin)
        student=clients['student_a'];staff=clients['staff_demo']
        self.assertEqual(student.get('/api/v1/me/schedule').status_code,200)
        request=self.post(student,'/api/v1/me/requests',{'type':'appeal','purpose':'','message':'Консультация (демо)','request_key':uuid.uuid4().hex},origin)
        self.assertEqual(request.status_code,201);appeal=request.json()
        request=self.post(student,'/api/v1/me/requests',{'type':'study_certificate','purpose':'Демо','message':'Нужна справка','request_key':uuid.uuid4().hex},origin)
        self.assertEqual(request.status_code,201);certificate=request.json()
        lessons=staff.get('/api/v1/staff/lessons').json()['items'];lesson=next(x for x in lessons if x['group_id']=='demo-a' and x['status']=='scheduled')
        room=next(x['id'] for x in staff.get('/api/v1/staff/catalogue').json()['rooms'] if x['id']=='demo-spare')
        body={k:lesson[k] for k in ('date','start_minute','end_minute','teacher_id','status','version')};body.update(room_id=room,reason='Тестовая замена аудитории')
        response=self.post(staff,'/api/v1/staff/lessons/'+lesson['id'],body,origin);self.assertEqual(response.status_code,200);new=response.json()
        own=student.get('/api/v1/me/schedule',params={'view':'today','date':lesson['date']}).json()
        self.assertTrue(any(x['id']==lesson['id'] and x['room']==new['room'] and x['changes'] for x in own['days'][0]['lessons']))
        self.assertTrue(any(x['kind']=='lesson' and x['resource_id']==lesson['id'] for x in student.get('/api/v1/me/notifications').json()['items']))
        reply=self.post(staff,'/api/v1/staff/requests/'+appeal['id']+'/reply',{'version':1,'comment':'Ответ сотрудника'},origin);self.assertEqual(reply.status_code,200)
        self.assertEqual(student.get('/api/v1/me/requests/'+appeal['id']).json()['history'][-1]['comment'],'Ответ сотрудника')
        for version,action in [(1,'processing'),(2,'approved')]:self.assertEqual(self.post(staff,'/api/v1/staff/requests/'+certificate['id']+'/decision',{'version':version,'action':action,'comment':'Демо'},origin).status_code,200)
        signed=self.post(staff,'/api/v1/staff/requests/'+certificate['id']+'/sign',{'version':3},origin);self.assertEqual(signed.status_code,200);doc=signed.json()['id']
        self.assertEqual(student.get('/api/v1/me/documents/'+doc).status_code,404)
        self.assertEqual(self.post(staff,'/api/v1/staff/documents/'+doc+'/deliver',origin=origin).status_code,200)
        document=student.get('/api/v1/me/documents/'+doc);self.assertEqual(document.status_code,200)
        self.assertIn('НЕ ЯВЛЯЕТСЯ ЮРИДИЧЕСКИ',document.json()['content'])
        self.assertIn('no-store',document.headers['cache-control'])
        for name in ACCOUNTS[1:4]:
            client=clients[name]
            for resource in ('requests/'+appeal['id'],'requests/'+certificate['id'],'documents/'+doc):self.assertEqual(client.get('/api/v1/me/'+resource).status_code,404)
            self.assertFalse(any(n['resource_id']==lesson['id'] for n in client.get('/api/v1/me/notifications').json()['items']))
        return doc
    def test_end_to_end_four_sessions(self):self.scenario(self.clients,self.settings.origin)
    def test_roles_csrf_owner_and_faculty_denied(self):
        student=self.login('student_a');staff=self.login('staff_demo');other=self.login('student_b')
        notice=student.get('/api/v1/me/notifications').json()['items'][0]['id']
        self.assertEqual(self.post(other,'/api/v1/me/notifications/'+notice+'/read').status_code,404)
        self.assertEqual(student.post('/api/v1/me/notifications/'+notice+'/read',json={},headers={'Origin':self.settings.origin}).status_code,403)
        self.assertEqual(self.post(student,'/api/v1/me/notifications/'+notice+'/read').status_code,200)
        for path in ['students','catalogue','lessons','documents','requests']:self.assertEqual(student.get('/api/v1/staff/'+path,headers={'X-Role':'staff'}).status_code,403)
        self.assertEqual(self.post(student,'/api/v1/staff/notifications',{'student_id':self.ids['student_b'],'title':'X','body':'Y'}).status_code,403)
        self.assertEqual(student.get('/api/v1/me/notifications?student_id='+self.ids['student_b']).status_code,422)
        with connection(self.settings,write=True) as db:db.execute('DELETE FROM request_staff_scopes WHERE staff_id=?',(self.ids['staff_demo'],))
        self.assertEqual(staff.get('/api/v1/staff/students').json()['items'],[])
        self.assertEqual(staff.get('/api/v1/staff/documents').json()['items'],[])
        self.assertEqual(self.post(staff,'/api/v1/staff/notifications',{'student_id':self.ids['student_a'],'title':'X','body':'Y'}).status_code,404)
    def test_lesson_create_conflict_move_cancel_and_atomic_events(self):
        staff=self.login('staff_demo');catalogue=staff.get('/api/v1/staff/catalogue').json()
        body={'group_id':'demo-a','subject_id':catalogue['subjects'][0]['id'],'teacher_id':catalogue['teachers'][0]['id'],'room_id':catalogue['rooms'][0]['id'],'date':'2027-01-12','start_minute':600,'end_minute':660,'kind':'lecture','status':'scheduled','reason':'Создание'}
        first=self.post(staff,'/api/v1/staff/lessons',body);self.assertEqual(first.status_code,200);lesson=first.json()
        self.assertEqual(self.post(staff,'/api/v1/staff/lessons',body).status_code,409)
        update={k:body[k] for k in ('date','start_minute','end_minute','teacher_id','room_id','status','reason')};update.update(date='2027-01-13',version=1,reason='Перенос')
        self.assertEqual(self.post(staff,'/api/v1/staff/lessons/'+lesson['id'],update).status_code,200)
        self.assertEqual(self.post(staff,'/api/v1/staff/lessons/'+lesson['id'],update).status_code,409)
        update.update(version=2,status='cancelled',reason='Отмена');self.assertEqual(self.post(staff,'/api/v1/staff/lessons/'+lesson['id'],update).status_code,200)
        with connection(self.settings) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM staff_audit WHERE resource_id=?',(lesson['id'],)).fetchone()[0],3)
            self.assertEqual(db.execute('SELECT count(*) FROM notifications WHERE resource_id=?',(lesson['id'],)).fetchone()[0],3)
        for invalid in [dict(body,date='2027-02-30'),dict(body,end_minute=500),dict(body,room_id='missing'),dict(body,group_id='missing')]:self.assertIn(self.post(staff,'/api/v1/staff/lessons',invalid).status_code,(422,404))
    def test_registration_invitation_once_and_server_assigned_role(self):
        client=self.clients['student_a'];token=issue(self.settings,'demo-a')
        csrf=client.get('/api/v1/auth/csrf').json()['csrf'];headers={'Origin':self.settings.origin,'X-CSRF-Token':csrf}
        data={'login':'new_student','password':secrets.token_urlsafe(24),'full_name':'Тестовый студент','invitation':token}
        self.assertEqual(client.post('/api/v1/auth/register',json={**data,'role':'staff'},headers=headers).status_code,422)
        self.assertEqual(client.post('/api/v1/auth/register',json=data,headers={'Origin':self.settings.origin}).status_code,403)
        self.assertEqual(client.post('/api/v1/auth/register',json=data,headers=headers).status_code,201)
        self.assertEqual(client.post('/api/v1/auth/register',json={**data,'login':'another'},headers=headers).status_code,422)
        with connection(self.settings) as db:
            row=db.execute("SELECT u.role,p.group_id,u.password_hash FROM users u JOIN student_profiles p ON p.user_id=u.id WHERE u.login='new_student'").fetchone()
            self.assertEqual((row['role'],row['group_id']),('student','demo-a'));self.assertTrue(verify_password(row['password_hash'],data['password']))
    def test_parallel_updates_commit_one_event_and_audit(self):
        staff=self.login('staff_demo');lesson=staff.get('/api/v1/staff/lessons').json()['items'][0]
        body={k:lesson[k] for k in ('date','start_minute','end_minute','teacher_id','room_id','version')};body.update(status='cancelled',reason='Параллельная отмена')
        headers={'Origin':self.settings.origin,'X-CSRF-Token':staff.cookies.get(self.settings.csrf_cookie)}
        def send(_):
            with TestClient(self.app,base_url=self.settings.origin) as client:
                client.cookies.update(dict(staff.cookies));return client.post('/api/v1/staff/lessons/'+lesson['id'],json=body,headers=headers).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(send,range(2)))
        self.assertEqual(sorted(results),[200,409])
        with connection(self.settings) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM staff_audit WHERE resource_id=?',(lesson['id'],)).fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM notifications WHERE resource_id=?',(lesson['id'],)).fetchone()[0],1)
    def test_notification_failure_rolls_back_lesson_and_audit(self):
        staff=self.login('staff_demo');lesson=staff.get('/api/v1/staff/lessons').json()['items'][0]
        body={k:lesson[k] for k in ('date','start_minute','end_minute','teacher_id','room_id','version')};body.update(status='cancelled',reason='Проверка rollback')
        with patch('backend.deanery.service.notify_group',side_effect=sqlite3.OperationalError('simulated')):
            self.assertEqual(self.post(staff,'/api/v1/staff/lessons/'+lesson['id'],body).status_code,503)
        with connection(self.settings) as db:
            row=db.execute('SELECT version,status FROM lessons WHERE id=?',(lesson['id'],)).fetchone();self.assertEqual((row['version'],row['status']),(lesson['version'],lesson['status']))
            self.assertEqual(db.execute('SELECT count(*) FROM staff_audit WHERE resource_id=?',(lesson['id'],)).fetchone()[0],0)
    def test_revoked_scope_blocks_lesson_document_and_reply(self):
        staff=self.login('staff_demo');lesson=staff.get('/api/v1/staff/lessons').json()['items'][0];doc=staff.get('/api/v1/staff/documents').json()['items'][0]
        request=next(x for x in staff.get('/api/v1/staff/requests').json()['items'] if x['status']=='submitted')
        with connection(self.settings,write=True) as db:db.execute('DELETE FROM request_staff_scopes WHERE staff_id=?',(self.ids['staff_demo'],))
        body={k:lesson[k] for k in ('date','start_minute','end_minute','teacher_id','room_id','status','version')};body['reason']='Недопустимо'
        self.assertEqual(self.post(staff,'/api/v1/staff/lessons/'+lesson['id'],body).status_code,404)
        self.assertEqual(self.post(staff,'/api/v1/staff/documents/'+doc['id']+'/deliver').status_code,404)
        self.assertEqual(self.post(staff,'/api/v1/staff/requests/'+request['id']+'/reply',{'version':request['version'],'comment':'Недопустимо'}).status_code,404)
    def test_documents_and_audit_immutable_and_default_database_untouched(self):
        with connection(self.settings) as db:
            doc=dict(db.execute('SELECT * FROM demo_documents LIMIT 1').fetchone())
            self.assertEqual(hashlib.sha256(doc['content'].encode()).hexdigest(),doc['content_hash'])
        for sql in ["UPDATE demo_documents SET content='forged'","UPDATE staff_audit SET action='forged'","DELETE FROM staff_audit"]:
            with self.assertRaises(sqlite3.IntegrityError):
                with connection(self.settings,write=True) as db:db.execute(sql)
        with self.assertRaises(ValueError):seed(Settings(),self.credentials)
    def test_upgrade_populated_v5_preserves_records_and_backup(self):
        from backend.migrations.manager import update,status
        from backend.commands.seed_demo import seed_demo
        from backend.commands.seed_schedule import seed_schedule
        from backend.commands.seed_academics import seed_academics
        definitions=self.root/'v5-migrations';definitions.mkdir()
        for path in (ROOT/'backend/migrations').glob('000[1-5]_*.sql'):shutil.copyfile(path,definitions/path.name)
        path=self.root/'v5.sqlite3';config=Settings(path);update(path,create=True,directory=definitions)
        ids=seed_demo(config,{n:self.credentials[n] for n in ('student_a','student_b','staff_demo')});seed_schedule(config);seed_academics(config)
        now=int(time.time());request=uuid.uuid4().hex
        with connection(config,write=True) as db:
            db.execute("INSERT INTO student_requests VALUES (?,?,?,'appeal','','Preserved synthetic request','submitted',1,?,?,?,?)",(request,ids['student_a'],'demo-f',now,now,uuid.uuid4().hex,'0'*64))
        tables=('users','student_profiles','lessons','lesson_changes','student_assessments','assessment_attempts','student_requests')
        def fingerprints(settings):
            with connection(settings) as db:return {table:hashlib.sha256(json.dumps([tuple(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY 1')],ensure_ascii=False).encode()).digest() for table in tables}
        before=fingerprints(config);backup=self.root/'v5-backup.sqlite3';update(path,backup=backup)
        self.assertTrue(before==fingerprints(config),'Upgrade changed existing records')
        self.assertTrue(before==fingerprints(Settings(backup)),'Backup changed existing records')
        self.assertEqual(status(path)['applied'][-1],'0026_attendance_qr');self.assertEqual(update(path)['pending'],[])
        self.assertEqual(status(backup,directory=definitions)['pending'],[])
    def test_real_http_and_assets(self):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        origin=f'http://127.0.0.1:{port}';env={**os.environ,'MGIMOV_DB_PATH':str(self.path),'MGIMOV_ORIGIN':origin}
        script='import site;site.addsitedir('+repr(sysconfig.get_path('purelib'))+");import uvicorn;uvicorn.run('backend.app:app',host='127.0.0.1',port="+str(port)+',proxy_headers=False)'
        with (self.root/'http.log').open('wb') as output:
            server=subprocess.Popen([sys._base_executable,'-B','-c',script],cwd=ROOT,env=env,stdout=output,stderr=output,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            clients={n:httpx.Client(base_url=origin,trust_env=False,timeout=4) for n in ACCOUNTS}
            try:
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    try:
                        if clients['student_a'].get('/api/health').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:self.fail('MVP HTTP startup failed')
                for path in ASSETS:self.assertEqual(clients['student_a'].get(path).status_code,200)
                self.assertEqual(clients['student_a'].get('/api/v1/me/documents').status_code,401)
                self.scenario(clients,origin)
            finally:
                for client in clients.values():client.close()
                server.terminate();server.wait(timeout=10)
        log=(self.root/'http.log').read_text(encoding='utf-8')
        for password in self.credentials.values():self.assertNotIn(password,log)

if __name__=='__main__':unittest.main()
