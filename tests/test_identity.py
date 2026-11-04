"""Identity and real HTTP checks against disposable synthetic SQLite only."""
from dataclasses import replace
import json, os, secrets, shutil, socket, subprocess, sys, sysconfig, time, unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.config import ROOT, Settings
from backend.db import connection
from backend.migrations.manager import update, status
from backend.commands.seed_demo import seed_demo
from backend.auth.service import digest
from backend.security import passwords
from tests.test_foundation import temporary

class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx=temporary(); cls.root=cls.ctx.__enter__(); cls.template=cls.root/'template.sqlite3'
        cls.config=Settings(cls.template); update(cls.template,create=True)
        cls.credentials={name:secrets.token_urlsafe(24) for name in ('student_a','student_b','staff_demo')}
        cls.ids=seed_demo(cls.config,cls.credentials)
        cls.dummy=passwords.hash_password(secrets.token_urlsafe(24))
    @classmethod
    def tearDownClass(cls):cls.ctx.__exit__(None,None,None)
    def setUp(self):
        self.tmp=temporary(); self.root=self.tmp.__enter__(); self.path=self.root/'case.sqlite3'
        shutil.copyfile(self.template,self.path); self.config=replace(self.config,database=self.path)
        with patch('backend.auth.service.passwords.hash_password',return_value=self.dummy):self.app=create_app(self.config)
        self.client=TestClient(self.app,base_url=self.config.origin)
        self.addCleanup(self.tmp.__exit__,None,None,None);self.addCleanup(self.client.close)
    def bootstrap(self,client=None):return (client or self.client).get('/api/v1/auth/csrf').json()['csrf']
    def login(self,name='student_a',password=None,client=None):
        client=client or self.client
        return client.post('/api/v1/auth/login',json={'login':name,'password':password if password is not None else self.credentials[name]},headers={'Origin':self.config.origin,'X-CSRF-Token':self.bootstrap(client)})
    def logout(self,**extra):
        return self.client.post('/api/v1/auth/logout',json={},headers={'Origin':self.config.origin,'X-CSRF-Token':self.client.cookies.get(self.config.csrf_cookie),**extra})
    def test_login_cookie_and_hash_only_storage(self):
        r=self.login();self.assertEqual(r.status_code,200);self.assertEqual(r.json()['user']['id'],self.ids['student_a'])
        cookie=next(c for c in r.headers.get_list('set-cookie') if c.startswith(self.config.session_cookie+'='))
        for flag in ('HttpOnly','SameSite=strict','Path=/'):self.assertIn(flag,cookie)
        with connection(self.config) as db:
            row=db.execute('SELECT * FROM sessions').fetchone();raw=json.dumps(dict(row))
            self.assertTrue(row['token_hash']==digest(self.client.cookies.get(self.config.session_cookie)))
            self.assertFalse(self.client.cookies.get(self.config.session_cookie) in raw)
            self.assertFalse(self.client.cookies.get(self.config.csrf_cookie) in raw)
    def test_wrong_unknown_disabled_same_error(self):
        a=self.login(password=secrets.token_urlsafe(24));b=self.login('unknown',password=secrets.token_urlsafe(24))
        with connection(self.config,write=True) as db:db.execute('UPDATE users SET active=0 WHERE id=?',(self.ids['student_a'],))
        c=self.login();self.assertEqual([a.status_code,b.status_code,c.status_code],[401]*3);self.assertEqual(a.json(),b.json());self.assertEqual(a.json(),c.json())
    def test_unknown_performs_real_dummy_verification(self):
        with patch('backend.auth.service.passwords.verify_password',wraps=passwords.verify_password) as verify:
            self.assertEqual(self.login('unknown',password=secrets.token_urlsafe(24)).status_code,401);self.assertEqual(verify.call_count,1)
    def test_anonymous_and_invalid_cookie_denied(self):
        for path in ('/api/v1/auth/me','/api/v1/me/profile'):self.assertEqual(self.client.get(path).status_code,401)
        self.client.cookies.set(self.config.session_cookie,secrets.token_urlsafe(32));self.assertEqual(self.client.get('/api/v1/me/profile').status_code,401)
    def test_two_students_and_staff_own_profiles(self):
        for name in self.credentials:
            self.assertEqual(self.login(name).status_code,200)
            r=self.client.get('/api/v1/me/profile');self.assertEqual(r.status_code,200);data=r.json()
            self.assertEqual(data['user']['id'],self.ids[name])
            if name=='staff_demo':
                self.assertEqual(data['user']['role'],'staff');self.assertEqual(set(data['profile']),{'full_name','position'})
            else:
                self.assertEqual(data['user']['role'],'student')
                self.assertEqual(data['profile']['study_group'],'ДЕМО-А' if name=='student_a' else 'ДЕМО-Б')
                self.assertEqual(set(data['profile']),{'full_name','faculty','program','course','study_group'})
            for other in self.ids:
                if other!=name:self.assertFalse(self.ids[other] in r.text)
    def test_idor_query_body_role_and_methods(self):
        self.login();other=self.ids['student_b']
        for query in ('?id='+other,'?user_id='+other,'?role=staff','?id=x&id='+other):
            self.assertEqual(self.client.get('/api/v1/me/profile'+query).status_code,422)
        self.assertEqual(self.client.get('/api/v1/me/profile/'+other).status_code,404)
        r=self.client.request('GET','/api/v1/me/profile',content=json.dumps({'user_id':other,'nested':{'id':other}}),headers={'Content-Type':'application/json'})
        self.assertEqual(r.status_code,422)
        for method in ('POST','PUT','PATCH','DELETE'):
            self.assertEqual(self.client.request(method,'/api/v1/me/profile',json={'id':other},headers={'Origin':self.config.origin}).status_code,405)
        self.assertEqual(self.client.get('/api/v1/me/profile',headers={'X-User-Id':other,'X-Role':'staff'}).json()['user']['id'],self.ids['student_a'])
        self.assertEqual(self.client.get('/api/v1/me/profile',headers={'X-Mgimov-User':other}).status_code,403)
        self.assertEqual(self.client.get('/api/v1/staff/requests').status_code,404)
    def test_login_csrf_and_origin_required(self):
        body={'login':'student_a','password':self.credentials['student_a']};csrf=self.bootstrap()
        for headers in ({'Origin':self.config.origin},{'Origin':self.config.origin,'X-CSRF-Token':secrets.token_urlsafe(32)},{'Origin':'https://foreign.invalid','X-CSRF-Token':csrf},{'X-CSRF-Token':csrf}):
            self.assertEqual(self.client.post('/api/v1/auth/login',json=body,headers=headers).status_code,403)
    def test_logout_revoke_and_repeat_login(self):
        self.login();old=self.client.cookies.get(self.config.session_cookie);self.assertEqual(self.logout().status_code,204)
        self.assertEqual(self.client.get('/api/v1/me/profile').status_code,401)
        self.client.cookies.set(self.config.session_cookie,old);self.assertEqual(self.client.get('/api/v1/me/profile').status_code,401)
        self.client.cookies.clear();self.assertEqual(self.login().status_code,200);self.assertTrue(old!=self.client.cookies.get(self.config.session_cookie))
    def test_logout_csrf_and_expected_owner(self):
        self.login()
        for csrf in ('',secrets.token_urlsafe(32)):self.assertEqual(self.logout(**{'X-CSRF-Token':csrf}).status_code,403)
        self.assertEqual(self.logout(**{'X-Mgimov-User':self.ids['student_b']}).status_code,403)
        self.assertEqual(self.client.get('/api/v1/me/profile').status_code,200)
    def test_expired_revoked_disabled_denied(self):
        for kind in ('expired','revoked','disabled'):
            self.client.cookies.clear();self.login();token=self.client.cookies.get(self.config.session_cookie)
            with connection(self.config,write=True) as db:
                if kind=='expired':db.execute('UPDATE sessions SET created_at=1,expires_at=2 WHERE token_hash=?',(digest(token),))
                elif kind=='revoked':db.execute('UPDATE sessions SET revoked_at=created_at WHERE token_hash=?',(digest(token),))
                else:db.execute('UPDATE users SET active=0 WHERE id=?',(self.ids['student_a'],))
            for path in ('/api/v1/auth/me','/api/v1/me/profile'):self.assertEqual(self.client.get(path).status_code,401)
    def test_login_rotates_previous_cookie_and_rejects_stale_owner(self):
        self.login();old=self.client.cookies.get(self.config.session_cookie);self.login('student_b')
        self.assertTrue(old!=self.client.cookies.get(self.config.session_cookie))
        with connection(self.config) as db:self.assertIsNotNone(db.execute('SELECT revoked_at FROM sessions WHERE token_hash=?',(digest(old),)).fetchone()[0])
        self.assertEqual(self.client.get('/api/v1/me/profile',headers={'X-Mgimov-User':self.ids['student_a']}).status_code,403)
        self.assertEqual(self.logout(**{'X-Mgimov-User':self.ids['student_a']}).status_code,403)
    def test_validation_no_secret_echo_or_mass_assignment(self):
        secret=secrets.token_urlsafe(24);csrf=self.bootstrap()
        for body in ({'login':'student_a','password':secret,'role':'staff'},{'login':'a','password':secret},{'login':'student_a','password':secret*10}):
            r=self.client.post('/api/v1/auth/login',json=body,headers={'Origin':self.config.origin,'X-CSRF-Token':csrf});self.assertEqual(r.status_code,422);self.assertFalse(secret in r.text)
    def test_invalid_unicode_password_is_rejected_without_echo(self):
        csrf=self.bootstrap()
        response=self.client.post('/api/v1/auth/login',content=json.dumps({'login':'student_a','password':chr(0xd800)}),headers={'Origin':self.config.origin,'X-CSRF-Token':csrf,'Content-Type':'application/json'})
        self.assertEqual(response.status_code,422)
        self.assertEqual(response.json(),{'detail':'Некорректная кодировка поля.'})

    def test_bounded_body_host_origin_and_fetch_metadata(self):
        self.assertEqual(self.client.post('/api/v1/auth/login',content='x'*8193,headers={'Origin':self.config.origin}).status_code,413)
        self.assertEqual(self.client.post('/api/v1/auth/login',content='x',headers={'Origin':self.config.origin}).status_code,415)
        for headers,code in [({'Host':'foreign.invalid'},400),({'Origin':'null'},403),({'Sec-Fetch-Site':'cross-site'},403)]:self.assertEqual(self.client.get('/api/v1/auth/me',headers=headers).status_code,code)
    def test_rate_limits_persist_and_expire(self):
        now=int(time.time());self.app.state.auth_service.clock=lambda:now
        with patch('backend.auth.service.passwords.verify_password',return_value=False):
            for _ in range(5):self.assertEqual(self.login(password=secrets.token_urlsafe(24)).status_code,401)
            self.assertEqual(self.login().status_code,429)
            self.app.state.auth_service.clock=lambda:now+61
            self.assertEqual(self.login(password=secrets.token_urlsafe(24)).status_code,401)
    def test_https_cookie_flags_and_unsafe_http_config(self):
        with self.assertRaises(ValueError):Settings(origin='http://public.invalid')
        config=replace(self.config,origin='https://deanery.invalid')
        with TestClient(create_app(config),base_url=config.origin) as client:
            csrf=self.bootstrap(client);r=client.post('/api/v1/auth/login',json={'login':'student_a','password':self.credentials['student_a']},headers={'Origin':config.origin,'X-CSRF-Token':csrf})
            self.assertEqual(r.status_code,200)
            cookie=next(c for c in r.headers.get_list('set-cookie') if c.startswith('__Host-mgimov_session='))
            for flag in ('Secure','HttpOnly','SameSite=strict','Path=/'):self.assertIn(flag,cookie)
            self.assertNotIn('Domain=',cookie)
    def test_missing_database_fails_without_creation(self):
        config=replace(self.config,database=self.root/'missing.sqlite3')
        with TestClient(create_app(config),base_url=config.origin) as client:
            r=client.get('/api/v1/me/profile');self.assertEqual(r.status_code,503);self.assertNotIn(str(config.database),r.text)
        self.assertFalse(config.database.exists())
    def test_v2_upgrade_repeat_and_seed_refuses_existing_users(self):
        with temporary() as root:
            definitions=root/'v2';definitions.mkdir();shutil.copyfile(ROOT/'backend/migrations/0001_initial.sql',definitions/'0001_initial.sql')
            db=root/'upgrade.sqlite3';update(db,create=True,directory=definitions)
            with connection(Settings(db),write=True) as c:c.execute("INSERT INTO app_metadata VALUES ('preserve','yes')")
            update(db,backup=root/'before.sqlite3');self.assertEqual(status(db)['applied'],['0001_initial','0002_identity'])
            self.assertEqual(update(db)['pending'],[])
            with connection(Settings(db)) as c:self.assertEqual(c.execute("SELECT value FROM app_metadata WHERE key='preserve'").fetchone()[0],'yes')
        with self.assertRaises(ValueError):seed_demo(self.config,self.credentials)
    def test_mismatched_role_profile_fails_closed(self):
        self.login()
        with connection(self.config,write=True) as db:db.execute("UPDATE users SET role='staff' WHERE id=?",(self.ids['student_a'],))
        self.assertEqual(self.client.get('/api/v1/me/profile').status_code,503)
    def test_real_http_two_accounts_and_logout(self):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        origin=f'http://127.0.0.1:{port}';env=dict(os.environ,MGIMOV_DB_PATH=str(self.path),MGIMOV_ORIGIN=origin,PYTHONDONTWRITEBYTECODE='1')
        script="import site; site.addsitedir("+repr(sysconfig.get_path('purelib'))+"); import uvicorn; uvicorn.run('backend.app:app',host='127.0.0.1',port="+str(port)+",proxy_headers=False)"
        log=self.root/'http.log'
        with log.open('wb') as stream:
            process=subprocess.Popen([sys._base_executable,'-B','-c',script],cwd=ROOT,env=env,stdout=stream,stderr=stream,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                with httpx.Client(base_url=origin,trust_env=False,timeout=2) as client:
                    deadline=time.monotonic()+15
                    while time.monotonic()<deadline:
                        try:
                            if client.get('/api/health').status_code==200:break
                        except httpx.HTTPError:pass
                        time.sleep(.1)
                    else:self.fail('HTTP startup failed')
                    for name in self.credentials:
                        csrf=self.bootstrap(client)
                        r=client.post('/api/v1/auth/login',json={'login':name,'password':self.credentials[name]},headers={'Origin':origin,'X-CSRF-Token':csrf})
                        self.assertEqual(r.status_code,200);self.assertEqual(client.get('/api/v1/me/profile').json()['user']['id'],self.ids[name])
                        self.assertEqual(client.post('/api/v1/auth/logout',json={},headers={'Origin':origin,'X-CSRF-Token':client.cookies.get(self.config.csrf_cookie)}).status_code,204)
                        self.assertEqual(client.get('/api/v1/me/profile').status_code,401)
            finally:process.terminate();process.wait(timeout=10)
        text=log.read_text(encoding='utf-8')
        for password in self.credentials.values():self.assertFalse(password in text)

if __name__=='__main__':unittest.main(verbosity=2)
