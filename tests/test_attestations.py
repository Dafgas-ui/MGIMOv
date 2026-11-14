import secrets
import shutil
import sqlite3
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.commands.seed_attestations import ACCOUNTS,seed
from backend.config import Settings
from backend.db import connection
from backend.migrations.manager import DIRECTORY,status,update
from backend.schedule.service import MOSCOW
from tests.test_foundation import temporary


class AttestationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = cls.enterClassContext(temporary())
        cls.settings = Settings(root/'phase3.sqlite3')
        cls.passwords = {key:secrets.token_urlsafe(22) for key in ACCOUNTS}
        cls.today = datetime.now(MOSCOW).date()
        seed(cls.settings,cls.passwords,cls.today)
        cls.app = create_app(cls.settings)

    def client(self, login):
        client = self.enterContext(TestClient(self.app,base_url=self.settings.origin))
        csrf = client.get('/api/v1/auth/csrf').json()['csrf']
        response = client.post('/api/v1/auth/login',json={'login':login,'password':self.passwords[login]},
                               headers={'Origin':self.settings.origin,'X-CSRF-Token':csrf})
        self.assertEqual(response.status_code,200,response.text)
        return client

    def post(self, client, endpoint, body, **headers):
        return client.post(endpoint,json=body,headers={
            'Origin':self.settings.origin,'X-CSRF-Token':client.cookies.get(self.settings.csrf_cookie),
            **headers,
        })

    def records(self, login):
        client = self.client(login)
        response = client.get('/api/v1/me/attestations')
        self.assertEqual(response.status_code,200,response.text)
        return {x['subject']:x for x in response.json()['items']}

    def test_demo_scenarios_and_privacy(self):
        with connection(self.settings) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone()[0],20)
            self.assertEqual(db.execute("SELECT count(*) FROM users WHERE role='student'").fetchone()[0],11)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],'ok')
        self.assertEqual(status(self.settings.database)['applied'][-1],'0014_legacy_attempt_history')
        self.assertEqual(update(self.settings.database)['pending'],[])
        subject = 'Демонстрационное право'
        corrected = self.records('s04')[subject]
        self.assertFalse(corrected['debt'])
        self.assertEqual([x['grade'] for x in corrected['history'] if 'grade' in x],[2,3])
        self.assertEqual([x['active'] for x in corrected['debt_history']],[True,False])
        self.assertTrue(self.records('s05')[subject]['debt'])
        self.assertEqual([x['kind'] for x in self.records('s07')[subject]['history']],['scheduled'])
        self.assertEqual(self.records('s11')[subject]['used'],0)
        for login,grade in [('s09',3),('s10',2)]:
            row = self.records(login)[subject]
            self.assertEqual(row['used'],3)
            self.assertEqual(row['awaiting_deanery'],grade==2)
            self.assertEqual([x['grade'] for x in row['history'] if x['kind']=='published'],[2,2,grade])
            self.assertTrue([x for x in row['history'] if x['kind']=='published'][-1]['commission'])
            self.assertNotIn('review_version',str(row))
        student = self.client('s01')
        book = student.get('/api/v1/me/gradebook').json()
        items = {i['control']:i['official_result'] for s in book['semesters'] for i in s['items']}
        self.assertEqual(items['credit']['outcome'],'pass')
        self.assertEqual(items['graded_credit']['grade'],5)
        debt_book = self.client('s02').get('/api/v1/me/gradebook').json()
        self.assertEqual({semester['id'] for semester in debt_book['semesters']},
                         {'phase3-prior','phase3-current'})
        self.assertIn('prior-s02',{item['id'] for item in debt_book['debts']})

    def test_review_executor_projection_and_official_correction(self):
        student = self.client('s02')
        examiner = self.client('t02')
        other = self.client('t05')
        deanery = self.client('d01')
        reviewer = self.client('d02')
        own = '/api/v1/me/attestations'
        course = next(x['id'] for x in student.get(own).json()['items']
                      if x['subject']=='Методы исследования')
        endpoint = '/api/v1/staff/attestations/'+course

        def read(client):
            result = client.get(endpoint)
            self.assertEqual(result.status_code,200,result.text)
            return result.json()

        def command(client, action, key, code=200, **fields):
            fields.setdefault('expected_version',read(examiner)['version'])
            result = self.post(client,endpoint+'/commands',dict(action=action,request_key=key,**fields))
            self.assertEqual(result.status_code,code,result.text)
            return result.json()

        # Give the other examiner course access through a separate slot.
        starts = int(time.time())+86400
        starts = int(datetime.fromtimestamp(starts,MOSCOW).replace(hour=20,minute=0,second=0).timestamp())
        separate = command(deanery,'scheduled','review-other-slot',starts_at=starts,ends_at=starts+3600,
                           examiner_id='t05')['slot_id']
        command(deanery,'cancelled','review-other-cancel',slot_id=separate,reason='Separate slot cancelled')
        slot = read(examiner)['state']['latest']['slot_id']

        def request_review(key):
            return command(examiner,'review_requested',key,slot_id=slot,executor_id='t02',
                           grade=4,reason='Verified correction',reference='PRIVATE-REFERENCE')['version']

        cancelled = request_review('review-first')
        self.assertEqual(read(examiner)['applicable_review_versions'],[])
        command(examiner,'corrected','review-unapproved',409,review_version=cancelled)
        command(reviewer,'review_approved','review-first-approval',review_version=cancelled)
        command(reviewer,'review_revoked','review-first-revoke',review_version=cancelled,reason='Withdraw approval')
        self.assertEqual(read(examiner)['applicable_review_versions'],[])
        command(examiner,'corrected','review-cancelled',409,review_version=cancelled)

        request = request_review('review-second')
        approval = command(reviewer,'review_approved','review-second-approval',review_version=request)
        view = read(examiner)
        self.assertEqual(view['applicable_review_versions'],[request])
        self.assertFalse(any(event['version']==approval['version'] for event in view['events']))
        other_view = read(other)
        self.assertEqual(other_view['applicable_review_versions'],[])
        self.assertFalse(any(event['kind'].startswith('review_') for event in other_view['events']))
        self.assertNotIn('PRIVATE-REFERENCE',str(other_view))
        command(other,'corrected','review-other-apply',404,review_version=request)
        command(examiner,'corrected','review-stale-version',409,review_version=request,
                expected_version=approval['version']-1)
        with connection(self.settings,write=True) as db:
            db.execute("DELETE FROM attestation_permissions WHERE staff_id='d02' AND permission='review'")
        try:
            self.assertEqual(read(examiner)['applicable_review_versions'],[])
            command(examiner,'corrected','review-invalid-authority',409,review_version=request)
        finally:
            with connection(self.settings,write=True) as db:
                db.execute("INSERT INTO attestation_permissions VALUES ('d02','phase3-f','review')")
        self.assertEqual(read(examiner)['version'],approval['version'])
        competing = request_review('review-competing')
        latest = command(reviewer,'review_approved','review-competing-approval',review_version=competing)
        applied = command(examiner,'corrected','review-apply',review_version=request)
        self.assertEqual(command(examiner,'corrected','review-apply',review_version=request,
                                 expected_version=latest['version']),applied)
        self.assertEqual(read(examiner)['applicable_review_versions'],[])
        command(examiner,'corrected','review-stale-target',409,review_version=competing)
        command(examiner,'corrected','review-duplicate',409,review_version=request)
        self.assertEqual(read(examiner)['version'],applied['version'])
        item = next(x for x in student.get(own).json()['items'] if x['id']==course)
        self.assertEqual([x['grade'] for x in item['history'] if 'grade' in x],[2,4])
        self.assertEqual([x['active'] for x in item['debt_history']],[True,False])
        self.assertFalse(item['debt'])
        book = student.get('/api/v1/me/gradebook').json()
        official = next(x['official_result'] for semester in book['semesters']
                        for x in semester['items'] if x['id']==course)
        self.assertEqual(official['grade'],4)
        self.assertTrue(official['corrected'])
        self.assertNotIn(course,{x['id'] for x in book['debts']})
        with connection(self.settings) as db:
            self.assertEqual(db.execute("""SELECT count(*) FROM staff_audit WHERE resource_id=?
                AND action='attestation.corrected' AND actor_id='t02'""",(course,)).fetchone()[0],1)

    def test_role_origin_csrf_replay_and_concurrent_scheduling(self):
        student = self.client('s02')
        deanery = self.client('d01')
        admin = self.client('a01')
        other = self.client('t05')
        course = next(x for x in student.get('/api/v1/me/attestations').json()['items']
                      if x['subject']=='Демонстрационное право')['id']
        endpoint = '/api/v1/staff/attestations/'+course
        self.assertEqual(student.get(endpoint).status_code,403)
        self.assertEqual(admin.get(endpoint).status_code,404)
        self.assertEqual(other.get(endpoint).status_code,404)
        detail = deanery.get(endpoint).json()
        starts = int(datetime.combine(self.today+timedelta(days=12),datetime.min.time(),MOSCOW).timestamp())+36000
        payload = {'action':'scheduled','expected_version':detail['version'],'request_key':'schedule-1',
                   'starts_at':starts,'ends_at':starts+3600,'examiner_id':'t02'}
        self.assertEqual(self.post(deanery,endpoint+'/commands',payload,Origin='http://foreign.test').status_code,403)
        self.assertEqual(self.post(deanery,endpoint+'/commands',payload,**{'X-CSRF-Token':'bad'}).status_code,403)
        self.assertEqual(self.post(admin,endpoint+'/commands',payload).status_code,404)
        self.assertEqual(self.post(deanery,endpoint+'/commands',
            {**payload,'starts_at':int(time.time())-10}).status_code,422)
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = sorted(pool.map(lambda key:self.post(deanery,endpoint+'/commands',
                {**payload,'request_key':key}).status_code,('schedule-1','schedule-2')))
        self.assertEqual(codes,[200,409])
        current = deanery.get(endpoint).json()
        slot = next(key for key,value in current['slots'].items() if value['starts_at']==starts)
        winner = next(e for e in current['events'] if e['slot_id']==slot)
        with connection(self.settings) as db:
            key = db.execute("SELECT request_key FROM attestation_receipts WHERE course_id=? AND version=?",
                             (course,winner['version'])).fetchone()[0]
        self.assertEqual(self.post(deanery,endpoint+'/commands',{**payload,'request_key':key}).json()['slot_id'],slot)
        cancel = {'action':'cancelled','slot_id':slot,'reason':'Отмена для проверки',
                  'request_key':'cancel-retry','expected_version':current['version']}
        with patch('backend.academics.attestation.audit',side_effect=sqlite3.OperationalError('test')):
            self.assertEqual(self.post(deanery,endpoint+'/commands',cancel).status_code,503)
        self.assertEqual(deanery.get(endpoint).json()['version'],current['version'])
        self.assertEqual(self.post(deanery,endpoint+'/commands',cancel).status_code,200)
        self.assertTrue(student.get('/api/v1/me/attestations').json()['items'])

    def test_language_is_account_scoped(self):
        first = self.client('s06')
        second = self.client('s08')
        url = '/api/v1/me/language'
        self.assertEqual(first.get(url).json(),{'language':'ru'})
        self.assertEqual(self.post(first,url,{'language':'en'}).json(),{'language':'en'})
        self.assertEqual(first.get(url).json(),{'language':'en'})
        self.assertEqual(second.get(url).json(),{'language':'ru'})
        self.assertEqual(self.post(first,url,{'language':'es'}).status_code,422)

    def test_examiner_publishes_only_after_assessment_starts(self):
        student = self.client('s11')
        examiner = self.client('t02')
        course = next(x for x in student.get('/api/v1/me/attestations').json()['items']
                      if x['subject']=='Методы исследования')
        endpoint = '/api/v1/staff/attestations/'+course['id']
        detail = examiner.get(endpoint).json()
        slot = next(key for key,value in detail['state']['stages'].items() if value=='scheduled')
        now = detail['slots'][slot]['ends_at']
        base = {'slot_id':slot,'expected_version':detail['version']}
        draft = {**base,'action':'draft','grade':3,'request_key':'examiner-draft'}
        self.assertEqual(self.post(examiner,endpoint+'/commands',draft).status_code,409)
        # Advance the application clock for this test only and keep both sessions valid.
        with connection(self.settings,write=True) as db:
            db.execute("UPDATE sessions SET expires_at=? WHERE user_id IN ('t02','s11')",(now+60,))
        with patch.object(self.app.state.auth_service,'clock',return_value=now):
            response = self.post(examiner,endpoint+'/commands',draft)
            self.assertEqual(response.status_code,200,response.text)
            visible = next(x for x in student.get('/api/v1/me/attestations').json()['items'] if x['id']==course['id'])
            self.assertEqual(visible,course)
            publish = {**base,'action':'published','request_key':'examiner-publish',
                       'expected_version':response.json()['version']}
            published = self.post(examiner,endpoint+'/commands',publish)
            self.assertEqual(published.status_code,200,published.text)
            self.assertEqual(self.post(examiner,endpoint+'/commands',publish).json(),published.json())
            book = student.get('/api/v1/me/gradebook').json()
            item = next(i for s in book['semesters'] for i in s['items'] if i['id']==course['id'])
            self.assertEqual(item['official_result']['grade'],3)

    def test_upgrade_populated_0011_preserves_legacy(self):
        root = self.enterContext(temporary())
        prior = root/'prior'
        prior.mkdir()
        for file in sorted(DIRECTORY.glob('*.sql'))[:11]:
            shutil.copyfile(file,prior/file.name)
        settings = Settings(root/'upgrade.sqlite3')
        update(settings.database,create=True,directory=prior)
        with connection(settings,write=True) as db:
            db.execute("INSERT INTO faculties VALUES ('upgrade','Upgrade fixture')")
        backup = root/'backup.sqlite3'
        self.assertEqual(update(settings.database,backup=backup)['applied'][-1],'0014_legacy_attempt_history')
        self.assertEqual(status(backup,directory=prior)['applied'][-1],'0011_brs_integer_points')
        self.assertEqual(update(settings.database)['pending'],[])
        with connection(settings) as db:
            self.assertEqual(db.execute("SELECT name FROM faculties WHERE id='upgrade'").fetchone()[0],'Upgrade fixture')
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],'ok')

    def test_history_resists_sql_replacement_and_legacy_write(self):
        with connection(self.settings,write=True) as db:
            course = db.execute("SELECT id FROM brs_student_courses WHERE student_id='s01' AND curriculum_id='law'").fetchone()[0]
            for sql in (
                "UPDATE attestation_events SET kind='cancelled' WHERE course_id=?",
                "DELETE FROM attestation_events WHERE course_id=?",
                "INSERT OR REPLACE INTO attestation_events SELECT * FROM attestation_events WHERE course_id=?",
            ):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql,(course,))
            today = self.today.isoformat()
            db.execute("INSERT INTO assessments VALUES ('legacy-check','law','g-a',?,?,'completed')",(today,today))
            db.execute("INSERT INTO student_assessments VALUES ('legacy-check','s01','legacy-check')")
            with self.assertRaisesRegex(sqlite3.IntegrityError,'Conflicting official result source'):
                db.execute("INSERT INTO assessment_attempts VALUES ('blocked','legacy-check',1,'graded',5,?,?)",
                           (today,int(time.time())))
