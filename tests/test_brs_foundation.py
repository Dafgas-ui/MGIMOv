import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
import secrets
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.auth.service import digest
from backend.brs.service import set_capability
from backend.config import ROOT, Settings
from backend.db import connection
from backend.migrations.manager import DIRECTORY, status, update
from backend.schedule.service import MOSCOW, change_in_transaction
from tests.test_foundation import temporary

ADMIN = "/api/v1/staff/brs/admin"
STAFF = "/api/v1/staff/brs"


class BRSFoundationTests(unittest.TestCase):
    def test_coursework_parent_guards_with_foreign_keys_on_and_off(self):
        from backend.coursework import create_draft, execute, student_work

        enrollment, path, _ = self.enroll_alice()
        offering, course = path.split('/')[-2], enrollment['course_id']
        self.assertEqual(self.bind().status_code, 201)
        self.assertEqual(self.grant(offering).status_code, 201)
        teacher = dict(id='teacher', role='staff')
        student = dict(id='alice', role='student')
        for foreign_keys in (0, 1):
            for recursive in (0, 1):
                with self.subTest(foreign_keys=foreign_keys, recursive_triggers=recursive), closing(
                        sqlite3.connect(self.settings.database)) as db:
                    db.row_factory = sqlite3.Row
                    db.execute(f'PRAGMA foreign_keys={foreign_keys}')
                    db.execute(f'PRAGMA recursive_triggers={recursive}')
                    db.execute('BEGIN IMMEDIATE')

                    def draft():
                        return create_draft(db, teacher, self.now, offering, kind='lab', title='Lab',
                                            description='Synthetic task', due_at=self.now+10, mode='both')

                    def command(key, actor, action, version, data):
                        return execute(db, actor, self.now, key, action, expected_version=version,
                                       request_key=secrets.token_hex(16), data=data)

                    work, published_empty, linked_draft, safe_draft = (draft() for _ in range(4))
                    command(work, teacher, 'publish', 1, {})
                    command(published_empty, teacher, 'publish', 1, {})
                    db.execute('DELETE FROM coursework_recipients WHERE assignment_id=?',
                               (published_empty,))
                    db.execute("""UPDATE coursework_assignments SET grading_mode='brs',event_code='e'
                        WHERE id=?""", (linked_draft,))
                    db.execute('INSERT INTO coursework_recipients VALUES (?,?,?,1)',
                               (linked_draft, course, enrollment['id']))
                    self.assertEqual(command(work, student, 'submit_text', 1,
                                             {'response':'Answer'})['attempt_no'], 1)
                    review = dict(course_id=course, attempt_no=1, decision='reviewed', comment='Checked')
                    command(work, teacher, 'review', 2, review)
                    before = student_work(db, student, work)

                    for sql, parameters in (
                        ('DELETE FROM coursework_recipients WHERE assignment_id=?', (work,)),
                        ('DELETE FROM coursework_assignments WHERE id=?', (published_empty,)),
                        ('DELETE FROM coursework_assignments WHERE id=?', (work,)),
                        ('DELETE FROM coursework_assignments WHERE id=?', (linked_draft,)),
                        ("UPDATE coursework_assignments SET id='changed' WHERE id=?", (work,)),
                        ('UPDATE coursework_recipients SET assignment_id=? WHERE assignment_id=?',
                         (safe_draft, work)),
                        ("UPDATE coursework_recipients SET course_id='changed' WHERE assignment_id=?", (work,)),
                        ("UPDATE coursework_recipients SET enrollment_id='changed' WHERE assignment_id=?", (work,)),
                        ('INSERT OR REPLACE INTO coursework_recipients SELECT * FROM coursework_recipients'
                         ' WHERE assignment_id=?', (work,)),
                        ('INSERT OR REPLACE INTO coursework_assignments SELECT * FROM coursework_assignments'
                         ' WHERE id=?', (work,)),
                        ("""INSERT OR REPLACE INTO coursework_assignments
                            SELECT 'replacement',offering_id,created_by,kind,title,description,due_at,
                            mode,created_at,status,version,event_code,grading_mode,max_points
                            FROM coursework_assignments WHERE id=?""", (linked_draft,)),
                        ("""UPDATE OR REPLACE coursework_assignments SET grading_mode='brs',event_code='e'
                            WHERE id=?""", (safe_draft,)),
                    ):
                        with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                            db.execute(sql, parameters)

                    self.assertEqual(student_work(db, student, work), before)
                    self.assertEqual(command(work, teacher, 'review', 3,
                                             dict(review, decision='retry_allowed',
                                                  reason='Allow resubmission'))['review_revision'], 2)
                    self.assertEqual(student_work(db, student, work)['attempts'], before['attempts'])
                    self.assertEqual(command(work, student, 'submit_text', 4,
                                             {'response':'Revised answer'})['attempt_no'], 2)
                    self.assertEqual(db.execute('DELETE FROM coursework_assignments WHERE id=?',
                                                (safe_draft,)).rowcount, 1)
                    self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                    db.rollback()

    def test_coursework_independent_grading_and_append_only_history(self):
        from backend.auth.service import AuthError
        from backend.coursework import create_draft, execute, student_work

        enrollment, path, _ = self.enroll_alice()
        offering = path.split('/')[-2]
        self.assertEqual(self.bind().status_code, 201)
        self.assertEqual(self.grant(offering).status_code, 201)
        course = enrollment['course_id']
        teacher = dict(id='teacher', role='staff')
        student = dict(id='alice', role='student')
        with connection(self.settings, write=True) as db:
            work = create_draft(db, teacher, self.now, offering, kind='lab', title='Lab',
                                description='Synthetic task', due_at=self.now+10, mode='both')

        def command(actor, action, version, data):
            with connection(self.settings, write=True) as db:
                return execute(db, actor, self.now, work, action, expected_version=version,
                               request_key=secrets.token_hex(16), data=data)

        with self.assertRaises(AuthError):
            command(teacher, 'publish', 1, {'grading_mode': 'independent', 'max_points': True})
        command(teacher, 'publish', 1, {'grading_mode': 'independent', 'max_points': 10})
        command(student, 'submit_text', 1, {'response': 'Answer'})
        review = dict(course_id=course, attempt_no=1, decision='reviewed', comment='Checked')
        for bad in (-1, 11, True):
            with self.assertRaises(AuthError) as error:
                command(teacher, 'review', 2, dict(review, points=bad))
            self.assertEqual(error.exception.status, 422)
        command(teacher, 'review', 2, dict(review, points=0))
        with self.assertRaises(AuthError):
            command(teacher, 'review', 3, dict(review, points=7))
        command(teacher, 'review', 3, dict(review, points=7, reason='Corrected total'))
        for mode in ('OFF', 'ON'):
            with closing(sqlite3.connect(self.settings.database)) as db:
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('PRAGMA recursive_triggers=' + mode)
                for sql in (
                    'UPDATE coursework_reviews SET points=1',
                    'DELETE FROM coursework_reviews',
                    'INSERT OR REPLACE INTO coursework_reviews SELECT * FROM coursework_reviews WHERE revision=1',
                    'DELETE FROM coursework_attempts',
                    'UPDATE coursework_attempts SET response=\'Rewritten\'',
                    'INSERT OR REPLACE INTO coursework_attempts SELECT * FROM coursework_attempts',
                    'INSERT OR REPLACE INTO coursework_recipients SELECT * FROM coursework_recipients',
                    'UPDATE coursework_assignments SET max_points=1',
                    'INSERT OR REPLACE INTO coursework_assignments SELECT * FROM coursework_assignments',
                ):
                    with self.assertRaises(sqlite3.IntegrityError):
                        db.execute(sql)
                for comment, timestamp, reason in (
                    ('', self.now, 'Valid reason'), (' \t\n\u00a0', self.now, 'Valid reason'),
                    ('x'*2001, self.now, 'Valid reason'), ('Checked', 0, 'Valid reason'),
                    ('Checked', 1.5, 'Valid reason'), ('Checked', self.now, None),
                    ('Checked', self.now, '\t\u00a0\n'),
                ):
                    with self.assertRaisesRegex(sqlite3.IntegrityError, 'Invalid coursework review'):
                        db.execute("""INSERT INTO coursework_reviews
                            VALUES (?,?,1,3,'reviewed',1,?,'teacher',?,?)""",
                                   (work, course, comment, timestamp, reason))
        with connection(self.settings) as db:
            item = student_work(db, student, work)
            self.assertEqual((item['grading_mode'], item['max_points']), ('independent', 10))
            self.assertEqual([(r['points'], r['reason']) for r in item['reviews']],
                             [(0, None), (7, 'Corrected total')])
            self.assertEqual(db.execute('SELECT count(*) FROM brs_attempt_versions').fetchone()[0], 0)
        with connection(self.settings, write=True) as db:
            work = create_draft(db, teacher, self.now, offering, kind='lab', title='No score',
                                description='Synthetic task', due_at=self.now+10, mode='both')
        command(teacher, 'publish', 1, {'grading_mode': 'ungraded'})
        command(student, 'submit_text', 1, {'response': 'Answer'})
        with self.assertRaises(AuthError):
            command(teacher, 'review', 2, dict(review, points=1))
        command(teacher, 'review', 2, review)

    def test_coursework_conflict_is_limited_to_published_results_in_recipient_flow(self):
        from backend.coursework import PublishedBRSConflict, create_draft, execute

        plan = self.locked()
        old, new = self.flow(plan), self.flow(plan, 'b')
        enrollment = self.post(f'{ADMIN}/offerings/{old}/enrollments',
                               {'student_id': 'alice', 'starts_on': '2027-02-01'}).json()
        self.assertEqual(self.bind().status_code, 201)
        self.assertEqual(self.grant(old).status_code, 201)
        teacher = dict(id='teacher', role='staff')
        with connection(self.settings, write=True) as db:
            db.execute("UPDATE lessons SET teacher_id='t' WHERE id='lb'")
            db.execute("INSERT INTO brs_event_results VALUES ('result',?,?,'e')",
                       (enrollment['course_id'], plan))
            db.execute("INSERT INTO brs_attempt_versions VALUES ('version','result',?,1,1,1,0,'teacher',?,NULL)",
                       (enrollment['id'], self.now))
            work = create_draft(db, teacher, self.now, old, kind='lab', title='Lab',
                                description='Synthetic task', due_at=self.now+10, mode='both')
        with connection(self.settings, write=True) as db:
            with self.assertRaises(PublishedBRSConflict) as conflict:
                execute(db, teacher, self.now, work, 'publish', expected_version=1,
                        request_key='conflict-example', data={'event_code': 'e'})
            self.assertEqual(conflict.exception.code, 'coursework_brs_result_already_published')
            self.assertEqual(tuple(db.execute('SELECT status,version FROM coursework_assignments').fetchone()),
                             ('draft', 1))
            for table in ('coursework_recipients', 'coursework_receipts'):
                self.assertEqual(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
            db.execute("INSERT INTO coursework_recipients VALUES (?,?,?,1)",
                       (work, enrollment['course_id'], enrollment['id']))
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'BRS result already published'):
                db.execute("""UPDATE coursework_assignments SET status='published',
                    grading_mode='brs', event_code='e' WHERE id=?""", (work,))
            db.execute("DELETE FROM coursework_recipients WHERE assignment_id=?", (work,))
            db.execute("""UPDATE coursework_assignments SET status='published',
                grading_mode='brs', event_code='e' WHERE id=?""", (work,))
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'BRS result already published'):
                db.execute("INSERT INTO coursework_recipients VALUES (?,?,?,1)",
                           (work, enrollment['course_id'], enrollment['id']))
        self.assertEqual(self.post(f"{ADMIN}/enrollments/{enrollment['id']}/transfer",
                                  {'target_offering_id': new, 'starts_on': '2027-02-20',
                                   'reason': 'Transfer'}).status_code, 201)
        self.assertEqual(self.grant(new, lesson='lb').status_code, 201)
        with connection(self.settings, write=True) as db:
            target = create_draft(db, teacher, self.now, new, kind='lab', title='Lab',
                                  description='New flow', due_at=self.now+10, mode='both')
            execute(db, teacher, self.now, target, 'publish', expected_version=1,
                    request_key='target-example-1', data={'event_code': 'e'})
            self.assertEqual(db.execute('SELECT count(*) FROM coursework_recipients').fetchone()[0], 1)

    def test_coursework_upgrade_populated_rc31_with_intermediate_draft_and_rollback(self):
        from backend.coursework import create_draft
        from backend.migrations.manager import MigrationError

        root = self.enterContext(temporary())
        migrations = root / 'migrations'
        migrations.mkdir()
        files = sorted(DIRECTORY.glob('*.sql'))
        for file in files[:14]:
            shutil.copyfile(file, migrations / file.name)
        self.initialize(root, migrations)
        enrollment, path, _ = self.enroll_alice()
        offering = path.split('/')[-2]
        self.assertEqual(self.bind().status_code, 201)
        self.assertEqual(self.grant(offering).status_code, 201)
        database = self.settings.database
        for file in files[14:15]:
            shutil.copyfile(file, migrations / file.name)
        update(database, backup=root/'before15.sqlite3', directory=migrations)
        with connection(self.settings, write=True) as db:
            draft = create_draft(db, dict(id='teacher', role='staff'), self.now, offering,
                                 kind='lab', title='Keep me', description='Synthetic task',
                                 due_at=self.now+10, mode='online')
        shutil.copyfile(files[15], migrations/files[15].name)
        update(database, backup=root/'before16.sqlite3', directory=migrations)
        with connection(self.settings, write=True) as db:
            self.assertEqual(tuple(db.execute('SELECT title,status,version FROM coursework_assignments'
                                              ' WHERE id=?', (draft,)).fetchone()), ('Keep me', 'draft', 1))
            db.execute("""INSERT INTO coursework_assignments
                (id,offering_id,created_by,kind,title,description,due_at,mode,created_at,status,version,event_code)
                VALUES ('legacy',?,'teacher','lab','Legacy','Synthetic',?,'online',?,'published',2,'e')""",
                       (offering, self.now+10, self.now))
            db.execute("INSERT INTO coursework_recipients VALUES ('legacy',?,?,2)",
                       (enrollment['course_id'], enrollment['id']))
            db.execute("INSERT INTO coursework_attempts VALUES ('legacy',?,1,'text','Answer',?,'alice',0)",
                       (enrollment['course_id'], self.now))
            db.execute("INSERT INTO coursework_reviews VALUES ('legacy',?,1,1,'reviewed',0,'Checked','teacher',?)",
                       (enrollment['course_id'], self.now))
        shutil.copyfile(files[16], migrations/files[16].name)
        self.assertEqual(update(database, backup=root/'before17.sqlite3', directory=migrations)['applied'][-1],
                         files[16].stem)
        with connection(self.settings, write=True) as db:
            plan = db.execute('SELECT plan_id FROM brs_offerings WHERE id=?', (offering,)).fetchone()[0]
            db.execute("INSERT INTO brs_event_results VALUES ('legacy-result',?,?,'e')",
                       (enrollment['course_id'], plan))
            db.execute("""INSERT INTO brs_attempt_versions
                VALUES ('legacy-version','legacy-result',?,1,1,1,0,'teacher',?,NULL)""",
                       (enrollment['id'], self.now))
        shutil.copyfile(files[17], migrations/files[17].name)
        self.assertEqual(update(database, backup=root/'before18.sqlite3', directory=migrations)['applied'][-1],
                         files[17].stem)
        broken = migrations / files[18].name
        broken.write_text(files[18].read_text(encoding='utf-8') + '\nINSERT INTO missing_table VALUES (1);',
                          encoding='utf-8')
        with self.assertRaises(MigrationError):
            update(database, backup=root/'before-broken.sqlite3', directory=migrations)
        self.assertEqual(status(database, directory=migrations)['pending'], [files[18].stem])
        self.assertEqual(update(database, backup=root/'before19.sqlite3')['applied'][-1], files[18].stem)
        self.assertEqual(update(database)['pending'], [])
        with connection(self.settings) as db:
            self.assertEqual(tuple(db.execute('''SELECT title,status,version,grading_mode FROM coursework_assignments
                                                 WHERE id=?''', (draft,)).fetchone()), ('Keep me', 'draft', 1, 'ungraded'))
            self.assertIsNotNone(db.execute('SELECT id FROM brs_enrollments WHERE id=?', (enrollment['id'],)).fetchone())
            self.assertEqual(tuple(db.execute("SELECT grading_mode,event_code FROM coursework_assignments"
                                              " WHERE id='legacy'").fetchone()), ('brs', 'e'))
            self.assertEqual(tuple(db.execute("SELECT revision,points,reason FROM coursework_reviews"
                                              " WHERE assignment_id='legacy'").fetchone()), (1, 0, None))
            self.assertEqual(tuple(db.execute("""SELECT n.enrollment_id,t.response FROM coursework_recipients n
                JOIN coursework_attempts t USING (assignment_id,course_id)
                WHERE n.assignment_id='legacy'""").fetchone()), (enrollment['id'], 'Answer'))
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        correction = self.post(f"{STAFF}/offerings/{offering}/enrollments/{enrollment['id']}/events/e/attempts/1/correct",
                               {'request_key':'legacy-correct','expected_result_version':1,
                                'points':1,'reason':'Correct existing result'}, 'teacher')
        self.assertEqual(correction.status_code, 200, correction.text)
        with connection(self.settings) as db:
            history = db.execute("""SELECT revision_no,points FROM brs_attempt_versions
                WHERE result_id='legacy-result' ORDER BY revision_no""").fetchall()
            self.assertEqual([tuple(row) for row in history], [(1, 0), (2, 1)])

    def test_coursework_lifecycle_and_concurrent_replay(self):
        from backend.auth.service import AuthError
        from backend.coursework import create_draft, execute, student_work

        plan = self.locked()
        old, new = self.flow(plan), self.flow(plan, 'b')
        enrollment = self.post(f'{ADMIN}/offerings/{old}/enrollments',
                               {'student_id': 'alice', 'starts_on': '2027-02-01'}).json()
        self.assertEqual(self.bind().status_code, 201)
        self.assertEqual(self.grant(old).status_code, 201)
        teacher = dict(id='teacher', role='staff')
        student = dict(id='alice', role='student')
        now = self.now
        with connection(self.settings, write=True) as db:
            work = create_draft(db, teacher, now, old, kind='lab', title='Lab',
                                description='Synthetic coursework', due_at=now+10, mode='both')

        def command(actor, action, version, key, data, *, at=now):
            with connection(self.settings, write=True) as db:
                return execute(db, actor, at, work, action, expected_version=version,
                               request_key=key.ljust(16, '_'), data=data)

        command(teacher, 'publish', 1, 'publish', {'event_code': 'e'})
        with self.assertRaises(AuthError):
            command(teacher, 'copy', 2, 'forbidden-copy', {'target_offering_id': new})
        with connection(self.settings, write=True) as db:
            db.execute("UPDATE lessons SET teacher_id='t' WHERE id='lb'")
        self.assertEqual(self.grant(new, lesson='lb').status_code, 201)
        copy_result = command(teacher, 'copy', 2, 'copy', {'target_offering_id': new})
        self.assertEqual(command(teacher, 'copy', 2, 'copy', {'target_offering_id': new}), copy_result)
        with connection(self.settings) as db:
            copied = db.execute('SELECT * FROM coursework_assignments WHERE id=?',
                                (copy_result['copy_id'],)).fetchone()
            self.assertEqual((copied['status'], copied['event_code'], copied['offering_id']),
                             ('draft', None, new))
            self.assertEqual(db.execute('SELECT count(*) FROM coursework_recipients WHERE assignment_id=?',
                                        (copied['id'],)).fetchone()[0], 0)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: command(student, 'submit_text', 1, 'submit',
                                                      {'response': 'Answer'}, at=now+11), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertTrue(results[0]['late'])
        with self.assertRaises(AuthError) as reused:
            command(student, 'submit_text', 1, 'submit', {'response': 'Different payload'})
        self.assertEqual(reused.exception.status, 409)
        with self.assertRaises(AuthError) as stale:
            command(student, 'submit_text', 1, 'stale', {'response': 'Stale version'})
        self.assertEqual(stale.exception.status, 409)
        course = enrollment['course_id']
        with self.assertRaises(AuthError) as conflict:
            command(student, 'submit_text', 2, 'different', {'response': 'Second'})
        self.assertEqual(conflict.exception.status, 409)
        command(teacher, 'review', 2, 'return', dict(course_id=course, attempt_no=1,
                                                    decision='returned', comment='Revise'))
        command(teacher, 'record_in_person', 3, 'in-person', {'course_id': course})
        command(teacher, 'review', 4, 'review', dict(course_id=course, attempt_no=2,
                                                    decision='reviewed', points=80, comment='Accepted'))
        self.assertEqual(self.count('brs_attempt_versions'), 0)
        with self.assertRaises(AuthError) as expired:
            command(teacher, 'review', 5, 'expired', dict(course_id=course, attempt_no=2,
                    decision='retry_allowed', comment='Retry'), at=now+60)
        self.assertEqual(expired.exception.status, 404)
        path = f"{ADMIN}/enrollments/{enrollment['id']}/transfer"
        self.assertEqual(self.post(path, {'target_offering_id': new, 'starts_on': '2027-02-20',
                                          'reason': 'Transfer'}).status_code, 201)
        with connection(self.settings) as db:
            item = student_work(db, student, work)
            self.assertEqual([p['method'] for p in item['attempts']], ['text', 'in_person'])
            self.assertEqual([r['decision'] for r in item['reviews']], ['returned', 'reviewed'])
            with self.assertRaises(AuthError):
                student_work(db, dict(id='bobby', role='student'), work)
        with self.assertRaises(AuthError):
            command(student, 'submit_text', 5, 'after-transfer', {'response': 'Old flow'})
        copied_id = copy_result['copy_id']
        with connection(self.settings, write=True) as db:
            execute(db, teacher, now, copied_id, 'publish', expected_version=1,
                    request_key='publish-new-flow', data={'event_code': 'e'})
            self.assertEqual(student_work(db, student, copied_id)['attempts'], [])

    def test_coursework_deadline_stays_within_semester(self):
        from backend.auth.service import AuthError
        from backend.coursework import create_draft

        flow = self.flow(self.locked())
        self.assertEqual(self.bind().status_code, 201)
        self.assertEqual(self.grant(flow).status_code, 201)
        next_term = int(datetime(2027, 7, 1, 12, tzinfo=MOSCOW).timestamp())
        with connection(self.settings, write=True) as db:
            with self.assertRaises(AuthError) as outside:
                create_draft(db, dict(id='teacher', role='staff'), self.now, flow, kind='test',
                             title='Exam practice', description='Synthetic', due_at=next_term, mode='both')
            self.assertEqual(outside.exception.status, 422)
            self.assertEqual(db.execute('SELECT count(*) FROM coursework_assignments').fetchone()[0], 0)

    def test_coursework_draft_requires_live_offering_assignment(self):
        from backend.auth.service import AuthError
        from backend.coursework import create_draft

        flow = self.flow(self.locked())
        self.assertEqual(self.bind().status_code, 201)
        self.assertEqual(self.grant(flow).status_code, 201)
        fields = dict(kind='lab', title='Lab', description='Synthetic task',
                      due_at=self.now + 86400, mode='in_person')
        with connection(self.settings, write=True) as db:
            for actor, when in ((dict(id='outside', role='staff'), self.now),
                                (dict(id='alice', role='student'), self.now),
                                (dict(id='teacher', role='staff'), self.now + 60)):
                with self.assertRaises(AuthError):
                    create_draft(db, actor, when, flow, **fields)
            key = create_draft(db, dict(id='teacher', role='staff'), self.now, flow, **fields)
            self.assertEqual(db.execute('SELECT id FROM coursework_assignments').fetchone()[0], key)
            self.assertEqual(db.execute("SELECT count(*) FROM staff_audit WHERE action='coursework.draft.create'").fetchone()[0], 1)

    def setUp(self):
        self.initialize(self.enterContext(temporary()))

    def initialize(self, folder, definitions=DIRECTORY):
        self.settings = Settings(folder / "brs.sqlite3")
        update(self.settings.database, create=True, directory=definitions)
        self.now = int(datetime(2027, 2, 20, 12, tzinfo=MOSCOW).timestamp())
        self.app = create_app(self.settings)
        self.app.state.auth_service.clock = lambda: self.now
        self.clients = {}
        with connection(self.settings, write=True) as db:
            for sql, rows in [
                ("INSERT INTO faculties VALUES (?,?)", [("f","Faculty"),("x","Other")]),
                ("INSERT INTO programs VALUES (?,?,?)", [("p","f","Program"),("q","x","Other")]),
                ("INSERT INTO study_groups VALUES (?,?,?,1)", [("a","p","A"),("b","p","B"),("x","q","X")]),
                ("INSERT INTO semesters VALUES (?,?,?,?)", [("s","Spring","2027-02-01","2027-06-30"),("old","Fall","2026-09-01","2026-12-30")]),
                ("INSERT INTO subjects VALUES (?,?)", [("math","Math"),("law","Law")]),
                ("INSERT INTO curriculum_items VALUES (?,?,?,?,'exam',1)",
                 [("math-s","p","math","s"),("law-s","p","law","s"),("math-x","q","math","s"),("math-old","p","math","old")]),
                ("INSERT INTO teachers VALUES (?,?)", [("t","Teacher"),("t2","Second")]),
            ]:
                db.executemany(sql, rows)
            db.execute("INSERT INTO buildings VALUES ('building','Building')")
            db.execute("INSERT INTO rooms VALUES ('room','building','1',20,'')")
            for index, (key, group, subject, teacher, day) in enumerate([
                ("l","a","math","t","2027-03-01"),("lb","b","math","t2","2027-03-01"),
                ("ll","a","law","t","2027-03-01"),("lx","x","math","t","2027-03-01"),
                ("lo","a","math","t","2026-11-01"),
            ]):
                start = 540 + index*90
                db.execute("INSERT INTO lessons VALUES (?,?,?,?,?,?,?,?,'lecture','scheduled',1,?)",
                           (key, group, subject, teacher, "room", day, start, start+60, self.now))
            for who in ("admin", "teacher", "second", "outside", "alice", "bobby"):
                role = "student" if who in ("alice", "bobby") else "staff"
                db.execute("INSERT INTO users VALUES (?,?,?, ?,1,?)", (who, who, "$argon2id$fixture", role, self.now))
                if role == "student":
                    db.execute("INSERT INTO student_profiles VALUES (?,?,?)", (who, who, "a"))
                else:
                    db.execute("INSERT INTO staff_profiles VALUES (?,?,?)", (who, who, role))
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,NULL)",
                           (who, who, digest(token), digest(csrf), self.now, self.now+3600))
                client = self.enterContext(TestClient(self.app, base_url=self.settings.origin))
                client.cookies.set(self.settings.session_cookie, token)
                client.cookies.set(self.settings.csrf_cookie, csrf)
                self.clients[who] = client
            for capability in ("manage_plans", "manage_teaching", "manage_enrollments"):
                set_capability(db, "admin", self.now, "admin", "f", capability, enabled=True)
            set_capability(db, "admin", self.now, "outside", "x", "manage_teaching", enabled=True)
            db.execute("INSERT INTO request_staff_scopes VALUES ('teacher','f')")

    def post(self, path, body, who="admin", **headers):
        client = self.clients[who]
        return client.post(path, json=body, headers={
            "Origin": self.settings.origin, "X-CSRF-Token": client.cookies.get(self.settings.csrf_cookie),
            **headers,
        })

    def created(self, path, body):
        response = self.post(path, body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def plan(self, curriculum="math-s"):
        return {
            "curriculum_id": curriculum, "source": "Faculty record #1",
            "approved_on": "2026-08-20" if curriculum == "math-old" else "2027-01-20",
            "rounding": "half_up", "admission_min": 41,
            "categories": [{"code":"all","title":"Coursework","maximum":100}],
            "events": [{"code":"e","category_code":"all","title":"Assignment","maximum":100,
                        "attempt_limit":2,"retake_policy":"highest",
                        "retake_until":"2026-12-10" if curriculum == "math-old" else "2027-06-20"}],
            "scale": [{"minimum":value,"outcome":str(outcome)}
                      for value,outcome in [(0,2),(60,3),(78,4),(91,5)]],
        }

    def locked(self, body=None):
        key = self.created(ADMIN+"/plans", body or self.plan())
        self.assertEqual(self.post(f"{ADMIN}/plans/{key}/lock", {}).status_code, 200)
        return key

    def flow(self, plan, group="a"):
        return self.created(ADMIN+"/offerings", {"plan_id":plan,"group_id":group})

    def seed_legacy_course(self):
        """Seed the pre-0011 schema without using today's API or score models."""
        with connection(self.settings, write=True) as db:
            db.execute("""INSERT INTO brs_plans VALUES
                ('old-plan','math-s','Fixture','2027-01-20','exact',5000,NULL,NULL)""")
            db.execute("INSERT INTO brs_categories VALUES ('old-plan','all','Coursework',10000,5000)")
            db.execute("""INSERT INTO brs_events VALUES
                ('old-plan','e','all','Assignment',10000,NULL,2,'highest','2027-06-20')""")
            db.executemany("INSERT INTO brs_scale VALUES ('old-plan',?,?)",
                           [(0,"2"),(5000,"3"),(7500,"4"),(9000,"5")])
            db.execute("UPDATE brs_plans SET locked_at=?,locked_by='admin' WHERE id='old-plan'", (self.now,))
            db.execute("INSERT INTO brs_offerings VALUES ('old-flow','old-plan','a')")
            db.execute("INSERT INTO brs_student_courses VALUES ('old-course','alice','math-s')")
            db.execute("""INSERT INTO brs_enrollments VALUES
                ('old-enrollment','old-course','old-flow','2027-02-01',NULL,NULL,'Fixture')""")
            db.execute("INSERT INTO brs_teacher_accounts VALUES ('teacher','t')")
            db.execute("""INSERT INTO brs_teaching_grants VALUES
                ('old-grant','old-flow','teacher','l',1,'admin',1,NULL,?,?,NULL)""",
                (self.now, self.now+60))
        return {"id":"old-enrollment","course_id":"old-course"}

    def bind(self, staff="teacher", teacher="t", lesson="l"):
        return self.post(ADMIN+"/teacher-accounts", {"staff_id":staff,"teacher_id":teacher,"lesson_id":lesson})

    def grant(self, flow, staff="teacher", lesson="l", who="admin", version=1):
        return self.post(f"{ADMIN}/offerings/{flow}/grants",
                         {"staff_id":staff,"lesson_id":lesson,"lesson_version":version,
                          "expires_at":self.now+60,"can_confirm_final":True}, who)

    def count(self, table):
        with connection(self.settings) as db:
            return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def test_validation_rejects_bad_maxima_scale_dates_and_retakes(self):
        for change in (
            lambda p:p["categories"][0].update(maximum=99),
            lambda p:p["events"][0].update(maximum=99),
            lambda p:p["events"][0].update(maximum=99, admission_min=100),
            lambda p:p["scale"][0].update(minimum=1),
            lambda p:p["scale"][1].update(minimum=0),
            lambda p:p["events"][0].update(retake_policy="none"),
            lambda p:p["events"][0].update(retake_until="2027-02-30"),
            lambda p:p.update(approved_on="2027-02-01"),
        ):
            plan = self.plan()
            change(plan)
            self.assertEqual(self.post(ADMIN+"/plans", plan).status_code, 422)
        self.assertEqual(self.count("brs_whole_plans"), 0)

    def test_plan_immutable_in_sql_and_http(self):
        key = self.locked()
        draft = self.created(ADMIN+"/plans", self.plan())
        self.assertEqual(self.post(f"{ADMIN}/plans/{key}/lock", {}).status_code, 409)
        self.assertEqual(self.clients["admin"].patch(f"{ADMIN}/plans/{key}", json={},
                         headers={"Origin":self.settings.origin}).status_code, 404)
        commands = [
            ("UPDATE brs_whole_plans SET admission_min=1 WHERE id=?", (key,)),
            ("DELETE FROM brs_whole_plans WHERE id=?", (key,)),
            ("INSERT OR REPLACE INTO brs_whole_plans SELECT id,curriculum_id,source,approved_on,rounding,admission_min,NULL,NULL FROM brs_whole_plans WHERE id=?", (key,)),
            ("UPDATE OR REPLACE brs_whole_plans SET id=? WHERE id=?", (key,draft)),
            ("INSERT INTO brs_events SELECT plan_id,'new',category_code,title,maximum,admission_min,attempt_limit,retake_policy,retake_until FROM brs_events WHERE plan_id=?", (key,)),
            ("UPDATE brs_events SET maximum=1 WHERE plan_id=?", (key,)),
            ("DELETE FROM brs_events WHERE plan_id=?", (key,)),
            ("UPDATE OR REPLACE brs_events SET plan_id=? WHERE plan_id=?", (key,draft)),
            ("UPDATE brs_events SET plan_id=? WHERE plan_id=?", (draft,key)),
            ("UPDATE brs_categories SET title='Changed' WHERE plan_id=?", (key,)),
            ("DELETE FROM brs_scale WHERE plan_id=?", (key,)),
        ]
        with connection(self.settings, write=True) as db:
            for sql, args in commands:
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "Locked BRS plan|new draft"):
                    db.execute(sql, args)

    def test_scope_schedule_edit_self_approval_expiry_and_revocation(self):
        plan = self.locked()
        flow = self.flow(plan)
        wrong_group = self.flow(plan, "b")
        wrong_subject = self.flow(self.locked(self.plan("law-s")))
        wrong_semester = self.flow(self.locked(self.plan("math-old")))
        access = f"{STAFF}/offerings/{flow}/access"
        self.assertEqual(self.bind().status_code, 201)
        with connection(self.settings) as db:
            row = db.execute("SELECT * FROM lessons WHERE id='l'").fetchone()
        edit = {k:row[k] for k in ("date","start_minute","end_minute","teacher_id","room_id","status","version")}
        edit.update(start_minute=550, reason="Staff schedule edit")
        self.assertEqual(self.post("/api/v1/staff/lessons/l", edit, "teacher").status_code, 200)
        self.assertEqual(self.clients["teacher"].get(access).status_code, 404)
        self.assertEqual(self.grant(flow, who="teacher", version=2).status_code, 404)
        with connection(self.settings, write=True) as db:
            set_capability(db,"admin",self.now,"teacher","f","manage_teaching",enabled=True)
        self.assertEqual(self.grant(flow, who="teacher", version=2).status_code, 403)
        self.assertEqual(self.grant(flow, who="outside", version=2).status_code, 404)
        for invalid in (wrong_group, wrong_subject, wrong_semester):
            self.assertEqual(self.grant(invalid, version=2).status_code, 404)
        self.assertEqual(self.grant(flow).status_code, 409)
        result = self.grant(flow, version=2)
        self.assertEqual(result.status_code, 201, result.text)
        key = result.json()["id"]
        self.assertEqual(self.clients["teacher"].get(access).status_code, 200)
        for who in ("admin","second","outside"):
            self.assertEqual(self.clients[who].get(access).status_code, 404)
        self.assertEqual(self.post(f"{ADMIN}/grants/{key}/revoke", {}, "outside").status_code, 404)
        self.assertEqual(self.post(f"{ADMIN}/grants/{key}/revoke", {}).status_code, 200)
        self.assertEqual(self.clients["teacher"].get(access).status_code, 404)
        self.assertEqual(self.grant(flow, version=2).status_code, 201)
        self.now += 61
        self.assertEqual(self.clients["teacher"].get(access).status_code, 404)
        self.assertEqual(self.grant(flow, version=2).status_code, 201)
        self.assertEqual(self.clients["teacher"].get(access).status_code, 200)
        with connection(self.settings) as db:
            actions = [row[0] for row in db.execute("SELECT action FROM staff_audit")]
        self.assertEqual(actions.count("brs.grant.approve"), 3)
        self.assertEqual(actions.count("brs.grant.revoke"), 1)

    def test_replacement_invalidates_grant_even_if_original_teacher_returns(self):
        flow = self.flow(self.locked())
        self.assertEqual(self.bind().status_code, 201)
        self.assertEqual(self.grant(flow).status_code, 201)
        access = f"{STAFF}/offerings/{flow}/access"
        self.assertEqual(self.clients["teacher"].get(access).status_code, 200)
        with connection(self.settings, write=True) as db:
            change_in_transaction(db,"l",1,"Replacement",{"teacher_id":"t2"},self.now)
            change_in_transaction(db,"l",2,"Return",{"teacher_id":"t"},self.now+1)
        self.assertEqual(self.clients["teacher"].get(access).status_code, 404)

    def test_substitute_appointment_is_limited_to_approved_event(self):
        flow = self.flow(self.locked())
        student = self.created(f"{ADMIN}/offerings/{flow}/enrollments", {"student_id":"alice","starts_on":"2027-02-01"})
        self.assertEqual(self.bind("second","t2","lb").status_code, 201)
        with connection(self.settings, write=True) as db:
            change_in_transaction(db,"l",1,"Replacement",{"teacher_id":"t2"},self.now)
        self.assertEqual(self.grant(flow,"second","l",version=2).status_code, 422)
        path = f"{ADMIN}/offerings/{flow}/grants"
        body = {"staff_id":"second","lesson_id":"l","lesson_version":2,
                "expires_at":self.now+60,"can_confirm_final":True,"event_code":"e"}
        self.assertEqual(self.post(path,body).status_code, 422)
        body["can_confirm_final"] = False
        self.assertEqual(self.post(path,body).status_code, 201)
        access = f"{STAFF}/offerings/{flow}/enrollments/{student}"
        self.assertEqual(self.clients["second"].get(access+"/access").status_code, 404)
        self.assertEqual(self.clients["second"].get(access+"/events/e/access").status_code, 200)
        self.assertEqual(self.clients["second"].get(access+"/events/other/access").status_code, 404)

    def test_transfer_keeps_same_course_and_separates_teacher_access(self):
        plan = self.locked()
        old, new = self.flow(plan), self.flow(plan,"b")
        key = self.created(f"{ADMIN}/offerings/{old}/enrollments", {"student_id":"alice","starts_on":"2027-02-01"})
        with connection(self.settings, write=True) as db:
            db.execute("INSERT INTO assessments VALUES ('legacy','math-old','a','2026-11-01',NULL,'completed')")
            db.execute("INSERT INTO student_assessments VALUES ('legacy-alice','alice','legacy')")
            db.execute("INSERT INTO assessment_attempts VALUES ('attempt','legacy-alice',1,'graded',4,'2026-11-01',?)", (self.now,))
        self.assertEqual(self.bind().status_code, 201)
        self.assertEqual(self.bind("second","t2","lb").status_code, 201)
        self.assertEqual(self.grant(old).status_code, 201)
        self.assertEqual(self.grant(new,"second","lb").status_code, 201)
        path = f"{ADMIN}/enrollments/{key}/transfer"
        payload = {"target_offering_id":new,"starts_on":"2027-02-20","reason":"Transfer"}
        with patch("backend.brs.service.audit",side_effect=sqlite3.OperationalError("test rollback")):
            self.assertEqual(self.post(path,payload).status_code, 503)
        self.assertEqual(self.count("brs_enrollments"), 1)
        result = self.post(path,payload)
        self.assertEqual(result.status_code, 201, result.text)
        target = result.json()["id"]
        self.assertEqual(self.post(path,payload).status_code, 409)
        with connection(self.settings) as db:
            rows = [tuple(r) for r in db.execute(
                "SELECT course_id,starts_on,ends_on,previous_id FROM brs_enrollments ORDER BY starts_on")]
            identity = db.execute("SELECT student_id,curriculum_id FROM brs_student_courses WHERE id=?",
                                  (result.json()["course_id"],)).fetchone()
        self.assertEqual(tuple(identity), ("alice", "math-s"))
        self.assertEqual(rows, [(result.json()["course_id"],"2027-02-01","2027-02-20",None),
                                (result.json()["course_id"],"2027-02-20",None,key)])
        for enrollment in (key,target):
            path = f"/api/v1/me/brs/enrollments/{enrollment}/plan"
            self.assertEqual(self.clients["alice"].get(path).json()["id"], plan)
            self.assertEqual(self.clients["bobby"].get(path).status_code, 404)
        legacy = self.clients["alice"].get("/api/v1/me/gradebook").json()["semesters"][0]["items"][0]
        self.assertEqual(legacy["attempts"][0]["grade"], 4)
        for who, flow, enrollment, expected in [
            ("teacher",old,key,404),("teacher",new,target,404),
            ("second",new,key,404),("second",new,target,200),
        ]:
            self.assertEqual(self.clients[who].get(
                f"{STAFF}/offerings/{flow}/enrollments/{enrollment}/access").status_code, expected)

    def test_different_plan_requires_explicit_nonduplicating_mapping(self):
        old = self.flow(self.locked())
        body = copy.deepcopy(self.plan())
        body["events"][0]["code"] = "new"
        new = self.flow(self.locked(body),"b")
        key = self.created(f"{ADMIN}/offerings/{old}/enrollments", {"student_id":"alice","starts_on":"2027-02-01"})
        path = f"{ADMIN}/enrollments/{key}/transfer"
        payload = {"target_offering_id":new,"starts_on":"2027-02-20","reason":"Approved mapping"}
        self.assertEqual(self.post(path,payload).status_code, 422)
        payload["mapping"] = [{"old_event":"e","new_event":"new"}]*2
        self.assertEqual(self.post(path,payload).status_code, 422)
        payload["mapping"].pop()
        self.assertEqual(self.post(path,payload).status_code, 201)
        self.assertEqual(self.count("brs_transfer_events"), 1)

    def test_origin_csrf_role_and_concurrent_lock(self):
        path = ADMIN+"/plans"
        self.assertEqual(self.post(path,self.plan(),Origin="https://invalid.test").status_code, 403)
        self.assertEqual(self.post(path,self.plan(),**{"X-CSRF-Token":"invalid"}).status_code, 403)
        self.assertEqual(self.post(path,self.plan(),"alice").status_code, 403)
        self.assertEqual(self.post(path,self.plan(),"outside").status_code, 404)
        with TestClient(self.app,base_url=self.settings.origin) as anonymous:
            self.assertEqual(anonymous.post(path,json=self.plan(),headers={"Origin":self.settings.origin}).status_code,401)
        key = self.created(path,self.plan())
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(lambda _:self.post(f"{path}/{key}/lock",{}).status_code,range(2)))
        self.assertEqual(sorted(codes),[200,409])
        with connection(self.settings) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM staff_audit WHERE action='brs.plan.lock'").fetchone()[0],1)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")

    def test_migration_of_populated_v6_and_repeat(self):
        with temporary() as root:
            definitions = root/"v6"
            definitions.mkdir()
            for file in (ROOT/"backend/migrations").glob("000[1-6]_*.sql"):
                shutil.copyfile(file,definitions/file.name)
            database = root/"existing.sqlite3"
            update(database,create=True,directory=definitions)
            with connection(Settings(database),write=True) as db:
                db.execute("INSERT INTO faculties VALUES ('prior','Prior')")
            backup = root/"backup.sqlite3"
            self.assertEqual(update(database,backup=backup)["applied"][-1],"0019_coursework_parent_guards")
            self.assertEqual(update(database)["pending"],[])
            for target in (database,backup):
                with connection(Settings(target)) as db:
                    self.assertEqual(db.execute("SELECT name FROM faculties WHERE id='prior'").fetchone()[0],"Prior")
                    self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")
                    self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])
            self.assertEqual(status(backup,directory=definitions)["applied"][-1],"0006_mvp")

    def enroll_alice(self):
        flow = self.flow(self.locked())
        path = f"{ADMIN}/offerings/{flow}/enrollments"
        body = {"student_id":"alice", "starts_on":"2027-02-01"}
        response = self.post(path, body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json(), path, body

    def assert_course_owner(self, enrollment):
        path = f"/api/v1/me/brs/enrollments/{enrollment['id']}/plan"
        self.assertEqual(self.clients["alice"].get(path).status_code, 200)
        self.assertEqual(self.clients["bobby"].get(path).status_code, 404)

    def test_course_identity_rejects_sql_mutations_and_preserves_api_ownership(self):
        enrollment, path, body = self.enroll_alice()
        key = enrollment["course_id"]
        self.assert_course_owner(enrollment)
        with connection(self.settings, write=True) as db:
            db.execute("PRAGMA recursive_triggers=OFF")
            queries = [
                ("UPDATE brs_student_courses SET student_id='bobby' WHERE student_id='alice'", ()),
                ("UPDATE brs_student_courses SET id='changed' WHERE id=?", (key,)),
                ("UPDATE OR REPLACE brs_student_courses SET rowid=rowid+100 WHERE id=?", (key,)),
                ("UPDATE OR REPLACE brs_student_courses SET curriculum_id='law-s' WHERE id=?", (key,)),
                ("INSERT OR REPLACE INTO brs_student_courses VALUES (?,'bobby','math-s')", (key,)),
                ("INSERT OR REPLACE INTO brs_student_courses VALUES ('replacement','alice','math-s')", ()),
                ("INSERT OR REPLACE INTO brs_student_courses(rowid,id,student_id,curriculum_id) SELECT rowid,'replacement','bobby','law-s' FROM brs_student_courses WHERE id=?", (key,)),
                ("INSERT OR IGNORE INTO brs_student_courses VALUES (?,'bobby','math-s')", (key,)),
                ("DELETE FROM brs_student_courses WHERE id=?", (key,)),
                ("INSERT INTO brs_student_courses VALUES (?,'bobby','law-s')", (key,)),
                ("INSERT OR REPLACE INTO brs_student_courses VALUES ('new-course','bobby','law-s'), (?,'bobby','math-s')", (key,)),
            ]
            for sql, args in queries:
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "course identity is immutable"):
                    db.execute(sql, args)
            for sql in ("DELETE FROM student_profiles WHERE user_id='alice'",
                        "UPDATE curriculum_items SET id='changed' WHERE id='math-s'",
                        "INSERT INTO brs_student_courses VALUES ('orphan','absent','math-s')"):
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY"):
                    db.execute(sql)
            self.assertEqual([tuple(row) for row in db.execute("SELECT * FROM brs_student_courses")],
                             [(key, "alice", "math-s")])
            self.assertEqual([tuple(row) for row in db.execute("SELECT id,course_id FROM brs_enrollments")],
                             [(enrollment["id"], key)])
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.post(path, body).status_code, 409)
        self.assertEqual(self.post(path, {**body, "course_id":key, "student_id":"bobby"}).status_code, 422)
        self.assertEqual(self.count("brs_student_courses"), 1)
        self.assertEqual(self.count("brs_enrollments"), 1)
        self.assert_course_owner(enrollment)

    def test_upgrade_populated_v8_preserves_courses_enrollments_and_backup(self):
        root = self.enterContext(temporary())
        definitions = root / "v8"
        definitions.mkdir()
        for file in DIRECTORY.glob("000[1-8]_*.sql"):
            shutil.copyfile(file, definitions / file.name)
        self.initialize(root, definitions)
        enrollment = self.seed_legacy_course()
        with connection(self.settings, write=True) as db:
            db.execute("INSERT INTO brs_student_courses(rowid,id,student_id,curriculum_id) VALUES (-1,'negative','bobby','law-s')")

        def snapshot(settings):
            with connection(settings) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
                return {table:[tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1")]
                        for table in ("brs_student_courses", "brs_enrollments", "staff_audit")}

        before = snapshot(self.settings)
        backup = root / "v8-backup.sqlite3"
        self.assertEqual(update(self.settings.database, backup=backup)["applied"][-1], "0019_coursework_parent_guards")
        self.assertEqual(update(self.settings.database)["pending"], [])
        self.assertEqual(status(backup, directory=definitions)["applied"][-1], "0008_brs_course_identity")
        self.assertEqual(snapshot(Settings(backup)), before)
        self.assertEqual(snapshot(self.settings), before)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "course identity is immutable"):
            with connection(self.settings, write=True) as db:
                db.execute("UPDATE brs_student_courses SET student_id='bobby' WHERE student_id='alice'")
        self.assert_course_owner(enrollment)
        law = self.flow(self.locked(self.plan("law-s")))
        response = self.post(f"{ADMIN}/offerings/{law}/enrollments",
                             {"student_id":"alice", "starts_on":"2027-02-01"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assert_course_owner(response.json())

    def test_negative_rowids_do_not_block_new_courses_or_allow_replacement(self):
        for recursive in ("OFF", "ON"):
            with self.subTest(recursive_triggers=recursive):
                self.initialize(self.enterContext(temporary()))
                with closing(sqlite3.connect(self.settings.database, isolation_level=None)) as db:
                    db.execute(f"PRAGMA recursive_triggers={recursive}")
                    # The trigger also protects ordinary SQL clients with FK enforcement off.
                    db.execute("PRAGMA foreign_keys=OFF")
                    db.execute("INSERT INTO brs_student_courses(rowid,id,student_id,curriculum_id) VALUES (-1,'negative','bobby','law-s')")
                    db.execute("INSERT INTO brs_student_courses(id,student_id,curriculum_id) VALUES ('legitimate','alice','law-s')")
                    self.assertEqual(db.execute("SELECT rowid FROM brs_student_courses WHERE id='negative'").fetchone(), (-1,))
                    self.assertNotEqual(db.execute("SELECT rowid FROM brs_student_courses WHERE id='legitimate'").fetchone(), (-1,))

                    def snapshot():
                        return tuple(db.execute("SELECT rowid,* FROM brs_student_courses ORDER BY id")), tuple(
                            db.execute("SELECT course_id FROM brs_course_insert_ledger ORDER BY course_id"))

                    before = snapshot()
                    for sql in (
                        "INSERT OR REPLACE INTO brs_student_courses(rowid,id,student_id,curriculum_id) VALUES (-1,'intruder','alice','math-s')",
                        "INSERT OR REPLACE INTO brs_student_courses VALUES ('legitimate','bobby','math-s')",
                        "INSERT OR REPLACE INTO brs_student_courses VALUES ('intruder','alice','law-s')",
                        "INSERT OR REPLACE INTO brs_student_courses(rowid,id,student_id,curriculum_id) VALUES (-20,'new-first','alice','math-s'),(-1,'intruder','bobby','math-s')",
                        "DELETE FROM brs_course_insert_ledger WHERE course_id='negative'",
                        "INSERT OR REPLACE INTO brs_course_insert_ledger VALUES ('negative')",
                        "INSERT INTO brs_course_insert_ledger VALUES ('invented')",
                    ):
                        with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "course identity is immutable"):
                            db.execute(sql)
                        self.assertEqual(snapshot(), before)
                    db.execute("INSERT INTO brs_student_courses(rowid,id,student_id,curriculum_id) VALUES (-20,'another','alice','math-s')")
                    db.execute("INSERT INTO brs_student_courses VALUES ('bulk-a','bobby','math-s'),('bulk-b','bobby','math-old')")
                    self.assertEqual(db.execute("SELECT count(*) FROM brs_course_insert_ledger").fetchone(), (5,))
                    db.execute("VACUUM")
                    db.execute("INSERT INTO brs_student_courses VALUES ('after-vacuum','alice','math-old')")
                    self.assertEqual(db.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                    self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
