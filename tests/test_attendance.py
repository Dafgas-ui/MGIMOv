"""Attendance HTTP tests on isolated synthetic SQLite and real sessions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import shutil
import sqlite3
from threading import Barrier
import unittest

from backend.db import connection
from backend.migrations.manager import DIRECTORY, MigrationError, status, update, verified_backup
from backend.schedule.service import change_in_transaction
from tests import test_brs_foundation as foundation


STAFF = '/api/v1/staff/attendance/lessons'
ME = '/api/v1/me/attendance'


class AttendanceTests(unittest.TestCase):
    def setUp(self):
        self.case = foundation.BRSFoundationTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.enrollment, path, _ = self.case.enroll_alice()
        self.flow = path.split('/')[-2]
        self.assertEqual(self.case.bind().status_code, 201)

    def detail(self, lesson='l', who='teacher'):
        response = self.case.clients[who].get(STAFF+'/'+lesson)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def confirm(self, detail=None, lesson='l', who='teacher'):
        detail = detail or self.detail(lesson)
        return self.case.post(STAFF+'/'+lesson, {'action':'confirm', 'expected_version':detail['version'],
            'lesson_version':detail['lesson']['version'], 'reason':'Roster verified',
            'candidate_token':detail['candidate_token']}, who)

    def mark(self, detail=None, student='alice', value='present', who='teacher', reason='Teacher observation'):
        detail = detail or self.detail(who=who)
        return self.case.post(STAFF+'/l', {'action':'mark', 'expected_version':detail['version'],
            'lesson_version':detail['lesson']['version'], 'student_id':student, 'status':value, 'reason':reason}, who)

    def reschedule(self, **changes):
        with connection(self.case.settings, write=True) as db:
            version = db.execute("SELECT version FROM lessons WHERE id='l'").fetchone()[0]
            change_in_transaction(db, 'l', version, 'Synthetic schedule change', changes, self.case.now)

    def test_lifecycle_permissions_privacy_and_history(self):
        # A dated enrollment, independent of Bobby's current profile, defines membership.
        self.assertEqual(self.case.post(f'{foundation.ADMIN}/offerings/{self.flow}/enrollments',
                                       {'student_id':'bobby','starts_on':'2027-02-01'}).status_code, 201)
        initial = self.detail()
        self.assertTrue(initial['needs_confirmation'])
        self.assertEqual(self.mark(initial).status_code, 422)  # no confirmed version
        self.assertEqual(self.case.clients['outside'].get(STAFF+'/l').status_code, 404)
        self.assertEqual(self.case.clients['alice'].get(STAFF+'/l').status_code, 403)
        self.assertEqual(self.confirm(initial).status_code, 200)
        self.assertEqual([row['status'] for row in self.detail()['students']], ['unmarked','unmarked'])
        self.assertEqual(self.mark(student='outside').status_code, 404)
        confirmed = self.detail()
        self.assertEqual(self.mark(confirmed, who='outside').status_code, 404)
        self.assertEqual(self.mark(confirmed, who='alice').status_code, 403)
        first = self.mark()
        self.assertEqual(first.status_code, 200, first.text)
        old = first.json()
        self.assertEqual(self.mark(old, value='late', reason='  ').status_code, 422)
        second = self.mark(old, value='late', reason='Corrected arrival time')
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(self.mark(old, value='absent').status_code, 409)
        alice = self.case.clients['alice'].get(ME+'/lessons/l')
        self.assertEqual(alice.status_code, 200)
        own = alice.json()
        self.assertEqual(own['status'], 'late')
        self.assertNotIn('bobby', alice.text)
        self.assertEqual([row['payload']['previous'] for row in own['history'] if row['kind']=='mark'], ['unmarked','present'])
        self.assertEqual(own['history'][-1]['reason'], 'Corrected arrival time')
        self.assertEqual(own['history'][-1]['actor_id'], 'teacher')
        self.assertEqual(self.case.clients['bobby'].get(ME+'/lessons/l').json()['status'], 'unmarked')
        self.assertEqual(self.case.clients['outside'].get(ME+'/lessons/l').status_code, 403)
        self.assertEqual(self.case.clients['alice'].get(ME+'/lessons/ll').status_code, 404)
        self.assertEqual(self.case.clients['alice'].get(ME, params={'student_id':'bobby'}).status_code, 422)
        self.assertEqual(len(self.case.clients['alice'].get(ME).json()['items']), 1)
        for table in ('brs_attempt_versions','coursework_attempts','assessment_attempts'):
            self.assertEqual(self.case.count(table), 0)

    def test_missing_ambiguous_and_empty_rosters(self):
        absent = self.detail('ll')
        self.assertIsNone(absent['candidate'])
        self.assertTrue(absent['blocked_reason'])
        request = {'action':'confirm','expected_version':0,'lesson_version':1,'reason':'Check','candidate_token':'0'*64}
        unavailable = self.case.post(STAFF+'/ll', request, 'teacher')
        self.assertEqual(unavailable.status_code, 409)
        self.assertEqual(unavailable.json()['detail'], absent['blocked_reason'])
        self.assertEqual(self.case.count('attendance_journals'), 0)
        other = self.case.flow(self.case.locked(self.case.plan('law-s')))
        empty = self.detail('ll')
        self.assertIsNone(empty['candidate'])
        self.assertIn('нет подходящих зачисленных студентов', empty['blocked_reason'])
        before = {table:self.case.count(table) for table in ('attendance_journals','attendance_events','staff_audit')}
        rejected = self.case.post(STAFF+'/ll', request, 'teacher')
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()['detail'], empty['blocked_reason'])
        self.assertNotEqual(rejected.json()['detail'], unavailable.json()['detail'])
        self.assertEqual({table:self.case.count(table) for table in before}, before)
        self.assertEqual(self.case.clients['alice'].get(ME).json()['items'], [])
        # Two matching curricula make the lesson ambiguous, even within one semester.
        with connection(self.case.settings, write=True) as db:
            db.execute("INSERT INTO curriculum_items VALUES ('math-credit','p','math','s','credit',1)")
        plan = self.case.plan('math-credit')
        plan['scale'] = [{'minimum':0,'outcome':'fail'}, {'minimum':50,'outcome':'pass'}]
        self.case.flow(self.case.locked(plan))
        ambiguous = self.detail()
        self.assertIsNone(ambiguous['candidate'])
        invalid = {'action':'confirm','expected_version':0,'lesson_version':1,'reason':'Check','candidate_token':'0'*64}
        self.assertEqual(self.case.post(STAFF+'/l', invalid, 'teacher').status_code, 409)
        self.assertEqual(self.case.count('attendance_journals'), 0)

    def test_transfer_reschedule_reconfirmation_and_cancellation(self):
        self.assertEqual(self.confirm().status_code, 200)
        self.assertEqual(self.mark().status_code, 200)
        original = self.detail()
        with connection(self.case.settings) as db:
            plan = db.execute('SELECT plan_id FROM brs_offerings WHERE id=?', (self.flow,)).fetchone()[0]
        target = self.case.flow(plan, 'b')
        moved = self.case.post(f"{foundation.ADMIN}/enrollments/{self.enrollment['id']}/transfer",
            {'target_offering_id':target,'starts_on':'2027-02-20','reason':'Synthetic transfer'})
        self.assertEqual(moved.status_code, 201, moved.text)
        # General profile still says A, but the dated source excludes Alice in March.
        self.assertFalse(self.detail()['can_mark'])
        self.assertEqual(self.mark(original, value='late').status_code, 409)
        self.assertEqual(self.confirm(original).status_code, 409)
        self.assertEqual(self.detail()['students'][0]['status'], 'present')
        self.reschedule(date='2027-02-19')
        detail = self.detail()
        self.assertTrue(detail['needs_confirmation'])
        self.assertEqual(detail['candidate']['students'][0]['id'], 'alice')
        self.assertEqual(self.confirm(detail).status_code, 200)
        self.assertTrue(self.detail()['can_mark'])
        self.assertEqual(self.detail()['students'][0]['status'], 'present')
        self.reschedule(date='2027-03-02')
        self.assertFalse(self.detail()['can_mark'])
        before = self.detail()['history']
        detail = self.detail()
        request = {'action':'confirm','expected_version':detail['version'],
                   'lesson_version':detail['lesson']['version'],'reason':'Check','candidate_token':'0'*64}
        self.assertEqual(self.case.post(STAFF+'/l', request, 'teacher').status_code, 409)
        self.assertEqual(self.detail()['history'], before)
        own = self.case.clients['alice'].get(ME+'/lessons/l').json()
        self.assertEqual(own['status'], 'present')
        self.assertFalse(own['active'])
        self.assertTrue(own['needs_confirmation'])
        self.assertTrue(all(row['previous_version']==row['version']-1 for row in own['history']))
        self.reschedule(status='cancelled')
        self.assertEqual(self.mark(value='absent').status_code, 409)
        self.assertTrue(self.case.clients['alice'].get(ME+'/lessons/l').json()['cancelled'])
        self.assertEqual(len(self.detail()['history']), 3)

    def test_lesson_teacher_and_not_brs_scope_controls_permission(self):
        self.assertEqual(self.case.grant(self.flow).status_code, 201)
        self.assertEqual(self.confirm().status_code, 200)
        self.reschedule(teacher_id='t2')
        self.assertEqual(self.case.clients['teacher'].get(STAFF+'/l').status_code, 404)
        self.assertEqual(self.case.bind(staff='second', teacher='t2').status_code, 201)
        replacement = self.detail(who='second')
        self.assertTrue(replacement['needs_confirmation'])
        self.assertEqual(self.confirm(replacement, who='second').status_code, 200)
        self.assertEqual(self.mark(who='second').status_code, 200)

    def test_concurrency_csrf_and_transaction_rollback(self):
        self.assertEqual(self.confirm().status_code, 200)
        detail = self.detail()
        barrier = Barrier(2)
        def write(value):
            barrier.wait(timeout=5)
            return self.mark(detail, value=value).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(write, ['present','absent'])), [200,409])
        with connection(self.case.settings, write=True) as db:
            db.execute("""CREATE TRIGGER broken_attendance_audit BEFORE INSERT ON staff_audit
                WHEN NEW.action LIKE 'attendance.%' BEGIN SELECT RAISE(IGNORE); END""")
        before = self.detail()
        self.assertEqual(self.mark(before, value='late').status_code, 503)
        self.assertEqual(self.detail(), before)
        request = {'action':'mark','expected_version':before['version'],'lesson_version':1,
                   'student_id':'alice','status':'late','reason':'Checked'}
        self.assertEqual(self.case.post(STAFF+'/l', request, 'teacher', Origin='https://other.invalid').status_code, 403)
        self.assertEqual(self.case.post(STAFF+'/l', request, 'teacher', **{'X-CSRF-Token':'bad'}).status_code, 403)
        self.assertEqual(self.case.clients['teacher'].post(STAFF+'/l', json=request).status_code, 403)

    def test_history_sql_guards_and_populated_upgrade(self):
        self.assertEqual(self.confirm().status_code, 200)
        self.assertEqual(self.mark().status_code, 200)
        before = self.detail()
        for foreign_keys in (0,1):
            with closing(sqlite3.connect(self.case.settings.database)) as db:
                db.execute(f'PRAGMA foreign_keys={foreign_keys}')
                for sql in ("DELETE FROM attendance_events", "UPDATE attendance_events SET reason='Changed'",
                            'INSERT OR REPLACE INTO attendance_events SELECT * FROM attendance_events',
                            'DELETE FROM attendance_journals', 'DELETE FROM lessons WHERE id=\'l\'',
                            'INSERT OR REPLACE INTO lessons SELECT * FROM lessons WHERE id=\'l\''):
                    with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                        db.execute(sql)
        self.assertEqual(self.detail(), before)
        source = self.case.settings.database
        old = source.with_name('populated-0023.sqlite3')
        verified_backup(source, old)
        with closing(sqlite3.connect(old)) as db, db:
            triggers = db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'attendance_%'").fetchall()
            for (name,) in triggers:
                db.execute('DROP TRIGGER '+name)
            db.execute('DROP TABLE attendance_events')
            db.execute('DROP TABLE attendance_journals')
            db.execute("DELETE FROM schema_migrations WHERE id='0024_attendance'")
        self.assertEqual(status(old)['pending'], ['0024_attendance'])
        with closing(sqlite3.connect(old)) as db:
            users = db.execute('SELECT id,role FROM users ORDER BY id').fetchall()
            controls = {name:db.execute('SELECT * FROM "'+name+'"').fetchall() for (name,) in
                        db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name<>'schema_migrations'").fetchall()}
        broken = old.with_name('broken-migrations')
        broken.mkdir()
        for sql in DIRECTORY.glob('*.sql'):
            shutil.copyfile(sql, broken/sql.name)
        migration = broken/'0024_attendance.sql'
        migration.write_text(migration.read_text(encoding='utf8')+'\nSELECT * FROM invalid_attendance_table;\n', encoding='utf8')
        with self.assertRaisesRegex(MigrationError, '0024_attendance'):
            update(old, backup=old.with_name('before-failed24.sqlite3'), directory=broken)
        self.assertEqual(status(old)['pending'], ['0024_attendance'])
        self.assertEqual(update(old, backup=old.with_name('before24.sqlite3'))['pending'], [])
        self.assertEqual(update(old)['pending'], [])
        with closing(sqlite3.connect(old)) as db:
            self.assertEqual(db.execute('SELECT id,role FROM users ORDER BY id').fetchall(), users)
            self.assertEqual({name:db.execute('SELECT * FROM "'+name+'"').fetchall() for name in controls}, controls)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
