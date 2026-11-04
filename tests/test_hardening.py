"""Small controlled security regressions; no working DB, no stress tests."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import secrets
import shutil
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.auth.service import AuthError
from backend.auth.limits import PAIR_LIMIT, SOURCE_LIMIT, WINDOW
from backend.commands.cleanup_sessions import cleanup
from backend.config import ROOT, Settings
from backend.db import connection
from backend.migrations.manager import update, status
from tests import test_identity as identity
from tests.test_foundation import temporary

class HardeningTests(unittest.TestCase):
    setUpClass = classmethod(identity.IdentityTests.setUpClass.__func__)
    tearDownClass = classmethod(identity.IdentityTests.tearDownClass.__func__)
    setUp = identity.IdentityTests.setUp
    bootstrap = identity.IdentityTests.bootstrap
    login = identity.IdentityTests.login
    logout = identity.IdentityTests.logout

    def set_clock(self):
        self.now=200000
        self.service=self.app.state.auth_service
        self.service.clock=lambda:self.now

    def attempt_failure(self, name, peer):
        try:
            self.service.login(name,'synthetic-invalid',peer)
        except AuthError as error:
            return error.status
        raise AssertionError('Unexpected successful synthetic attempt')

    def test_unknown_budget_does_not_lock_independent_account_on_same_nat(self):
        self.set_clock()
        with patch('backend.auth.service.passwords.verify_password',return_value=False):
            for _ in range(PAIR_LIMIT):self.assertEqual(self.attempt_failure('unknown','nat'),401)
            self.assertEqual(self.attempt_failure('unknown','nat'),429)
        user,_,_=self.service.login('student_a',self.credentials['student_a'],'nat')
        self.assertEqual(user['id'],self.ids['student_a'])

    def test_foreign_failures_cannot_lock_owner_from_other_source(self):
        self.set_clock()
        with patch('backend.auth.service.passwords.verify_password',return_value=False):
            for _ in range(PAIR_LIMIT):self.assertEqual(self.attempt_failure('student_a','attacker'),401)
            self.assertEqual(self.attempt_failure('student_a','attacker'),429)
        user,_,_=self.service.login('student_a',self.credentials['student_a'],'owner')
        self.assertEqual(user['id'],self.ids['student_a'])
        with connection(self.config) as db:
            self.assertEqual(db.execute('SELECT max(attempts) FROM auth_rate_limits').fetchone()[0],PAIR_LIMIT)

    def test_rotating_login_cannot_bypass_source_budget_and_other_source_works(self):
        self.set_clock()
        with patch('backend.auth.service.passwords.verify_password',return_value=False):
            for index in range(SOURCE_LIMIT):self.assertEqual(self.attempt_failure('unknown_'+str(index),'source'),401)
            self.assertEqual(self.attempt_failure('new_name','source'),429)
        user,_,_=self.service.login('student_b',self.credentials['student_b'],'independent')
        self.assertEqual(user['id'],self.ids['student_b'])

    def test_successes_refund_own_reservation_without_clearing_failures(self):
        self.set_clock()
        with patch('backend.auth.service.passwords.verify_password',return_value=False):self.assertEqual(self.attempt_failure('student_a','nat'),401)
        for _ in range(PAIR_LIMIT+2):
            self.service.login('student_a',self.credentials['student_a'],'nat')
        with connection(self.config) as db:
            counts=[r['attempts'] for r in db.execute('SELECT attempts FROM auth_rate_limits')]
        self.assertEqual(sorted(counts),[1,1])

    def test_window_expiry_and_counts_persist_across_limiter_instances(self):
        self.set_clock()
        with patch('backend.auth.service.passwords.verify_password',return_value=False):
            for _ in range(PAIR_LIMIT):self.assertEqual(self.attempt_failure('unknown','source'),401)
            from backend.auth.limits import LoginLimits
            second=LoginLimits(self.config)
            with self.assertRaises(AuthError):second.reserve('unknown','source',self.now)
            self.now+=WINDOW
            self.assertEqual(self.attempt_failure('unknown','source'),401)

    def test_parallel_reservations_cannot_overshoot_pair_budget(self):
        self.set_clock()
        def reserve(_):
            try:self.service.limits.reserve('unknown','source',self.now);return 200
            except AuthError as error:return error.status
        with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(reserve,range(PAIR_LIMIT+2)))
        self.assertEqual(results.count(200),PAIR_LIMIT)
        self.assertEqual(results.count(429),2)
        with connection(self.config) as db:self.assertEqual(max(r['attempts'] for r in db.execute('SELECT attempts FROM auth_rate_limits')),PAIR_LIMIT)

    def test_client_forwarded_header_cannot_reset_source_bucket(self):
        self.set_clock()
        with patch('backend.auth.service.passwords.verify_password',return_value=False):
            for _ in range(PAIR_LIMIT):self.assertEqual(self.login(password='synthetic-invalid').status_code,401)
            csrf=self.bootstrap()
            response=self.client.post('/api/v1/auth/login',json={'login':'student_a','password':'synthetic-invalid'},headers={'Origin':self.config.origin,'X-CSRF-Token':csrf,'X-Forwarded-For':'203.0.113.55'})
            self.assertEqual(response.status_code,429)

    def test_stale_counter_cleanup_is_bounded_and_keeps_current_reservations(self):
        self.set_clock()
        with connection(self.config,write=True) as db:
            db.executemany('INSERT INTO auth_rate_limits VALUES (?,?,1)', [('old-'+str(i),self.now-WINDOW) for i in range(25)])
        self.service.limits.reserve('unknown','source',self.now)
        with connection(self.config) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM auth_rate_limits WHERE bucket LIKE 'old-%'").fetchone()[0],5)
            self.assertEqual(db.execute('SELECT count(*) FROM auth_rate_limits WHERE window_start=?',(self.now,)).fetchone()[0],2)

    def test_source_rotation_does_not_bypass_per_account_or_global_concurrency(self):
        self.set_clock()
        with self.service.limits.verification('student_a'):
            with self.assertRaises(AuthError) as error:
                with self.service.limits.verification('student_a'):pass
            self.assertEqual(error.exception.status,503)
            with self.service.limits.verification('student_b'):
                with self.assertRaises(AuthError) as error:
                    with self.service.limits.verification('new_login'):pass
                self.assertEqual(error.exception.status,503)
        self.assertEqual(self.service.limits.active,set())

    def test_repeated_429_neither_writes_nor_runs_argon(self):
        self.set_clock()
        with patch('backend.auth.service.passwords.verify_password',return_value=False):
            for _ in range(PAIR_LIMIT):self.attempt_failure('unknown','source')
        with patch('backend.auth.limits.connection',wraps=connection) as calls, patch('backend.auth.service.passwords.verify_password') as verify:
            self.assertEqual(self.attempt_failure('unknown','source'),429)
            self.assertFalse(any(call.kwargs.get('write') for call in calls.call_args_list))
            verify.assert_not_called()

    def test_logout_preflight_rejects_invalid_token_and_csrf_without_writer(self):
        self.login()
        with patch('backend.auth.service.connection',wraps=connection) as calls:
            self.assertEqual(self.logout(**{'X-CSRF-Token':'invalid'}).status_code,403)
            self.assertFalse(any(call.kwargs.get('write') for call in calls.call_args_list))
        self.client.cookies.clear()
        with patch('backend.auth.service.connection',wraps=connection) as calls:
            self.assertEqual(self.client.post('/api/v1/auth/logout',json={},headers={'Origin':self.config.origin}).status_code,401)
            calls.assert_not_called()

    def test_contention_denials_still_work_and_login_logout_recover(self):
        self.set_clock();self.login()
        with patch('backend.auth.service.passwords.verify_password',return_value=False):
            for _ in range(PAIR_LIMIT):self.attempt_failure('unknown','blocked')
        with closing(sqlite3.connect(self.path,isolation_level=None)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            self.assertEqual(self.attempt_failure('unknown','blocked'),429)
            self.assertEqual(self.logout(**{'X-CSRF-Token':'invalid'}).status_code,403)
            self.assertEqual(self.logout().status_code,503)
            self.assertEqual(self.login('student_b').status_code,503)
            writer.rollback()
        self.assertEqual(self.logout().status_code,204)
        self.assertEqual(self.login('student_b').status_code,200)

    def test_two_independent_students_logout_a_keeps_b_active(self):
        with TestClient(self.app,base_url=self.config.origin) as second:
            self.assertEqual(self.login('student_a').status_code,200)
            self.assertEqual(self.login('student_b',client=second).status_code,200)
            self.assertEqual(self.logout().status_code,204)
            self.assertEqual(self.client.get('/api/v1/me/profile').status_code,401)
            b=second.get('/api/v1/me/profile')
            self.assertEqual(b.status_code,200);self.assertEqual(b.json()['user']['id'],self.ids['student_b'])
            self.assertFalse(self.ids['student_b'] in self.client.get('/api/v1/auth/me').text)

    def test_public_health_never_calls_full_diagnostic(self):
        with patch('backend.migrations.manager.status',side_effect=AssertionError('Full diagnosis invoked')), patch('backend.migrations.manager.inspect',side_effect=AssertionError('Full scan invoked')):
            response=self.client.get('/api/health')
            self.assertEqual(response.status_code,200);self.assertEqual(response.json(),{'status':'ok'})
        with connection(self.config,write=True) as db:db.execute("UPDATE schema_migrations SET checksum='invalid' WHERE id='0002_identity'")
        self.assertEqual(self.client.get('/api/health').status_code,503)

    def test_diagnostic_cli_finds_corruption_and_is_not_public(self):
        good=subprocess.run([sys.executable,'-B','-m','backend.commands.diagnose','--db',str(self.path)],cwd=ROOT,capture_output=True,timeout=10)
        self.assertEqual(good.returncode,0)
        bad=self.root/'corrupt.sqlite3';bad.write_bytes(b'not a sqlite database')
        result=subprocess.run([sys.executable,'-B','-m','backend.commands.diagnose','--db',str(bad)],cwd=ROOT,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,1)
        for path in ('/api/diagnose','/api/v1/diagnose','/api/health/full'):
            self.assertEqual(self.client.get(path).status_code,404)

    def test_bounded_cleanup_preserves_live_and_recently_revoked_sessions(self):
        now=200000
        with connection(self.config,write=True) as db:
            for name,expires,revoked in [('expired1',now-1,None),('expired2',now-2,None),('old-revoked',now+1000,1),('live',now+1000,None),('recent-revoked',now+1000,now-1)]:
                db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?)',(name,self.ids['student_a'],secrets.token_hex(32),secrets.token_hex(32),1,expires,revoked))
        self.assertEqual(cleanup(self.config,now=now,limit=2),2)
        self.assertEqual(cleanup(self.config,now=now,limit=2),1)
        self.assertEqual(cleanup(self.config,now=now,limit=2),0)
        with connection(self.config) as db:
            rows=db.execute('SELECT id,expires_at FROM sessions ORDER BY id').fetchall()
        self.assertEqual([(r['id'],r['expires_at']) for r in rows],[('live',now+1000),('recent-revoked',now+1000)])
        with self.assertRaises(ValueError):cleanup(self.config,limit=0)


class BodyDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_trickle_does_not_reset_absolute_body_deadline(self):
        import asyncio
        from backend.auth.http import IdentityGuard
        called=[];messages=[]
        async def app(scope,receive,send):called.append(True)
        async def receive():
            await asyncio.sleep(.02)
            return {'type':'http.request','body':b'x','more_body':True}
        async def send(message):messages.append(message)
        scope={'type':'http','path':'/api/v1/auth/login','scheme':'http','method':'POST',
               'headers':[(b'host',b'127.0.0.1:8010'),(b'origin',b'http://127.0.0.1:8010'),(b'content-type',b'application/json')]}
        await IdentityGuard(app,Settings(),body_timeout=.05)(scope,receive,send)
        self.assertFalse(called)
        self.assertEqual(next(m['status'] for m in messages if m['type']=='http.response.start'),408)

if __name__=='__main__':unittest.main(verbosity=2)
