from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import base64
import json
import secrets
import shutil
import sqlite3
from threading import Barrier
import unittest

from fastapi.testclient import TestClient

from backend.db import connection
from backend.migrations.manager import DIRECTORY, MigrationError, status, update, verified_backup
from tests import test_brs_foundation as foundation


STUDENT = '/api/v1/me/coursework'
STAFF = '/api/v1/staff/coursework'


class CourseworkHTTPTests(unittest.TestCase):
    def setUp(self):
        self.case = foundation.BRSFoundationTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.enrollment, path, _ = self.case.enroll_alice()
        self.flow = path.split('/')[-2]
        self.assertEqual(self.case.bind().status_code, 201)
        grant = self.case.grant(self.flow)
        self.assertEqual(grant.status_code, 201)
        self.grant = grant.json()['id']

    def payload(self, version=1, **fields):
        return {'expected_version': version, 'request_key': secrets.token_hex(16), **fields}

    def draft_payload(self, **fields):
        return {'request_key': secrets.token_hex(16), 'offering_id': self.flow, 'kind': 'lab',
                'title': 'Lab', 'description': 'Synthetic coursework', 'due_at': self.case.now+10,
                'mode': 'both', **fields}

    def create(self):
        response = self.case.post(STAFF, self.draft_payload(), 'teacher')
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['assignment_id']

    def command(self, work, action, version, **data):
        return self.case.post(f'{STAFF}/{work}/commands',
                              self.payload(version, action=action, data=data), 'teacher')

    def test_record_in_person_permissions_replay_and_recipient_version(self):
        work = self.create()
        course = self.enrollment['course_id']
        self.assertEqual(self.command(work, 'publish', 1).status_code, 200)
        commands = f'{STAFF}/{work}/commands'
        detail = f'{STAFF}/{work}/recipients/{course}'
        request = self.payload(action='record_in_person', data={'course_id': course})
        teacher = self.case.clients['teacher']
        self.assertTrue(teacher.get(detail).json()['can_record_in_person'])
        self.assertEqual(self.case.post(commands, request, 'outside').status_code, 404)
        self.assertEqual(self.case.post(commands, request, 'bobby').status_code, 403)
        recorded = self.case.post(commands, request, 'teacher')
        self.assertEqual(recorded.status_code, 200)
        self.assertEqual(self.case.post(commands, request, 'teacher').json(), recorded.json())
        self.assertFalse(teacher.get(detail).json()['can_record_in_person'])
        self.assertEqual(self.command(work, 'record_in_person', 1, course_id=course).status_code, 409)
        self.assertEqual(self.case.clients['bobby'].get(f'{STUDENT}/{work}').status_code, 404)
        attempts = self.case.clients['alice'].get(f'{STUDENT}/{work}').json()['attempts']
        self.assertEqual([attempt['method'] for attempt in attempts], ['in_person'])

    def test_private_files_are_versioned_and_committed_with_attempt(self):
        work = self.create()
        posted = f'{STAFF}/{work}/materials'
        material = {'name':'guide.txt', 'content':base64.b64encode(b'Synthetic material').decode()}
        case = self.case
        body = self.payload(files=[material])
        self.assertEqual(case.post(posted, body, 'outside').status_code, 404)
        added = case.post(posted, body, 'teacher')
        self.assertEqual(added.status_code, 200, added.text)
        self.assertEqual(case.post(posted, body, 'teacher').json(), added.json())
        item, = case.clients['teacher'].get(f'{STAFF}/{work}').json()['materials']
        material_url = f"{STUDENT}/files/{item['id']}"
        self.assertEqual(case.clients['alice'].get(material_url).status_code, 404)
        self.assertEqual(self.command(work, 'publish', 2).status_code, 200)
        self.assertEqual(case.clients['alice'].get(material_url).content, b'Synthetic material')
        self.assertEqual(case.clients['bobby'].get(material_url).status_code, 404)
        self.assertEqual(case.post(posted, self.payload(version=3, files=[material]), 'teacher').status_code, 409)

        url = f'{STUDENT}/{work}/submissions/with-files'
        for file in ({**material, 'name':'../bad.txt'}, {**material, 'name':'bad.pdf'},
                     {**material, 'name':'CON.txt'}, {**material, 'content':'AA=='},
                     {**material, 'content':base64.b64encode(b'x' * 65537).decode()}):
            self.assertEqual(case.post(url, self.payload(response='Answer', files=[file]), 'alice').status_code, 422)
        self.assertEqual(case.count('coursework_attempts'), 0)
        self.assertEqual(case.post(url, self.payload(response='Answer', files=[material]*3), 'alice').status_code, 422)
        attached = self.payload(response='Answer', files=[{**material, 'name':'answer.md'}])
        self.assertEqual(case.post(url, attached, 'bobby').status_code, 404)
        barrier = Barrier(2)

        def submit_same_request():
            barrier.wait(timeout=5)
            return case.post(url, attached, 'alice')

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = (future.result(timeout=10) for future in
                             [pool.submit(submit_same_request), pool.submit(submit_same_request)])
        self.assertEqual([first.status_code, second.status_code], [201, 201])
        self.assertEqual(first.json(), second.json())
        self.assertEqual(case.count('coursework_attempts'), 1)
        attempt_file, = case.clients['alice'].get(f'{STUDENT}/{work}').json()['files']
        self.assertEqual(attempt_file['attempt_no'], 1)
        path = f"/files/{attempt_file['id']}"
        self.assertEqual(case.clients['bobby'].get(STUDENT+path).status_code, 404)
        self.assertEqual(case.clients['outside'].get(STAFF+path).status_code, 404)
        downloaded = case.clients['teacher'].get(STAFF+path)
        self.assertEqual(downloaded.content, b'Synthetic material')
        self.assertEqual(downloaded.headers['content-type'], 'application/octet-stream')
        self.assertTrue(downloaded.headers['content-disposition'].startswith('attachment;'))
        with connection(case.settings, write=True) as db:
            for sql in ('UPDATE coursework_files SET content=X\'00\' WHERE id=?',
                        'DELETE FROM coursework_files WHERE id=?',
                        'INSERT OR REPLACE INTO coursework_files SELECT * FROM coursework_files WHERE id=?'):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql, (attempt_file['id'],))

    def test_publish_review_to_brs_with_provenance_and_explicit_correction(self):
        work = self.create()
        case = self.case
        course = self.enrollment['course_id']
        commands = f'{STAFF}/{work}/commands'
        sources = f'{STUDENT}/{work}'
        self.assertEqual(self.command(work, 'publish', 1, event_code='e').status_code, 200)
        self.assertEqual(case.post(sources+'/submissions', self.payload(response='Answer'), 'alice').status_code, 201)
        review = {'course_id':course, 'attempt_no':1, 'decision':'reviewed', 'comment':'Checked', 'points':8}
        self.assertEqual(self.command(work, 'review', 2, **review).status_code, 200)
        fields = {'course_id':course, 'attempt_no':1, 'review_revision':1, 'expected_result_version':0}
        payload = self.payload(version=3, action='publish_brs', data=fields)
        self.assertEqual(case.post(commands, payload, 'outside').status_code, 404)
        self.assertEqual(case.post(commands, payload, 'alice').status_code, 403)
        self.assertEqual(self.command(work, 'publish_brs', 3, **{**fields, 'review_revision':2}).status_code, 409)
        self.assertEqual(case.count('brs_attempt_versions'), 0)
        before_gradebook = case.clients['alice'].get('/api/v1/me/gradebook').json()
        barrier = Barrier(2)

        def publish_same_request():
            barrier.wait(timeout=5)
            return case.post(commands, payload, 'teacher')

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = (future.result(timeout=10) for future in
                             [pool.submit(publish_same_request), pool.submit(publish_same_request)])
        self.assertEqual([first.status_code, second.status_code], [200, 200], first.text)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(case.count('brs_attempt_versions'), 1)
        self.assertEqual(self.command(work, 'publish_brs', 3, **fields).status_code, 409)

        self.assertEqual(self.command(work, 'review', 4, **{**review, 'points':7, 'reason':'Corrected calculation'}).status_code, 200)
        correction = {**fields, 'review_revision':2, 'expected_result_version':1}

        def publish_competing_correction():
            barrier.wait(timeout=5)
            return self.command(work, 'publish_brs', 5, **correction)

        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = [pool.submit(publish_competing_correction), pool.submit(publish_competing_correction)]
            self.assertEqual(sorted(reply.result(timeout=10).status_code for reply in replies), [200, 409])
        history = case.clients['alice'].get(sources).json()['brs_publications']
        self.assertEqual([(item['brs_attempt_no'], item['revision_no'], item['review_revision'], item['points'])
                          for item in history], [(1, 1, 1, 8), (1, 2, 2, 7)])
        self.assertEqual(case.clients['alice'].get('/api/v1/me/gradebook').json(), before_gradebook)
        with connection(case.settings, write=True) as db:
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'Coursework owns'):
                db.execute("""INSERT INTO brs_attempt_versions
                    SELECT 'forged',result_id,enrollment_id,attempt_no,3,3,6,actor_id,published_at,'Forged correction'
                    FROM brs_attempt_versions WHERE id=?""", (history[-1]['brs_version_id'],))
        brs_path = f"/api/v1/staff/brs/offerings/{self.flow}/enrollments/{self.enrollment['id']}/events/e/attempts"
        direct = case.post(brs_path+'/1/correct', {
            'expected_result_version':2, 'request_key':secrets.token_hex(16), 'points':6,
            'reason':'Direct correction',
        }, 'teacher')
        self.assertEqual(direct.status_code, 409)
        self.assertEqual(self.command(work, 'review', 6, **{**review, 'decision':'retry_allowed',
                             'points':None, 'reason':'Authorize retake'}).status_code, 200)
        self.assertEqual(case.post(sources+'/submissions', self.payload(version=7, response='Retry'), 'alice').status_code, 201)
        self.assertEqual(self.command(work, 'review', 8, **{**review, 'attempt_no':2, 'points':6}).status_code, 200)
        retake = {**fields, 'attempt_no':2, 'expected_result_version':2}
        self.assertEqual(self.command(work, 'publish_brs', 9, **retake).status_code, 422)
        self.assertEqual(case.post(brs_path+'/2/submission', {}, 'teacher').status_code, 200)
        self.assertEqual(self.command(work, 'publish_brs', 9, **retake).status_code, 200)
        result = case.clients['alice'].get(f'/api/v1/me/brs/courses/{course}/results').json()
        self.assertEqual(result['combined_points'], 7)  # Existing highest policy prefers corrected attempt 1.
        self.assertEqual(case.clients['alice'].get('/api/v1/me/gradebook').json(), before_gradebook)
        with connection(case.settings) as db:
            records = db.execute("""SELECT a.actor_id,a.version,a.created_at,v.published_at
                FROM staff_audit a JOIN coursework_brs_sources s ON s.version_id=a.resource_id
                JOIN brs_attempt_versions v ON v.id=s.version_id
                WHERE a.action='brs.attempt.coursework' AND a.resource_kind='brs_attempt_version'
                ORDER BY a.version""").fetchall()
            self.assertEqual([tuple(row) for row in records],
                             [('teacher', number, case.now, case.now) for number in range(1, 4)])
        self.assertEqual(self.command(work, 'review', 10, **{**review, 'attempt_no':2, 'points':5,
                             'reason':'Corrected calculation'}).status_code, 200)
        self.assertEqual(case.post(f'{foundation.ADMIN}/grants/{self.grant}/revoke', {}).status_code, 200)
        self.assertEqual(case.post(commands, payload, 'teacher').status_code, 404)
        pending = {**retake, 'review_revision':2, 'expected_result_version':3}
        self.assertEqual(self.command(work, 'publish_brs', 11, **pending).status_code, 404)
        self.assertEqual(case.count('brs_attempt_versions'), 3)

    def reviewed_work(self):
        work = self.create()
        course = self.enrollment['course_id']
        self.assertEqual(self.command(work, 'publish', 1, event_code='e').status_code, 200)
        self.assertEqual(self.case.post(f'{STUDENT}/{work}/submissions',
                                       self.payload(response='Answer'), 'alice').status_code, 201)
        self.assertEqual(self.command(work, 'review', 2, course_id=course, attempt_no=1,
                                      decision='reviewed', comment='Checked', points=8).status_code, 200)
        return work, course

    def insert_unchecked_publication(self, db, work, course, actor):
        db.execute("""INSERT INTO brs_event_results
            SELECT 'fake-result',?,plan_id,'e' FROM brs_offerings WHERE id=?""", (course, self.flow))
        db.execute("INSERT INTO coursework_brs_sources VALUES ('fake-version',?,?,1,1)", (work, course))
        db.execute("""INSERT INTO brs_attempt_versions
            VALUES ('fake-version','fake-result',?,1,1,1,8,?,?,NULL)""",
                   (self.enrollment['id'], actor, self.case.now))

    def test_coursework_replay_requires_current_enrollment_with_an_active_grant(self):
        work, course = self.reviewed_work()
        payload = self.payload(3, action='publish_brs', data={
            'course_id':course, 'attempt_no':1, 'review_revision':1, 'expected_result_version':0,
        })
        endpoint = f'{STAFF}/{work}/commands'
        self.assertEqual(self.case.post(endpoint, payload, 'teacher').status_code, 200)
        with connection(self.case.settings, write=True) as db:
            db.execute("UPDATE brs_enrollments SET ends_on='2027-02-02' WHERE id=?", (self.enrollment['id'],))
        access = f'/api/v1/staff/brs/offerings/{self.flow}/access'
        self.assertEqual(self.case.clients['teacher'].get(access).status_code, 200)
        self.assertEqual(self.case.post(endpoint, payload, 'teacher').status_code, 404)
        self.assertEqual(self.case.count('brs_attempt_versions'), 1)

    def test_missing_audit_rolls_back_publication_and_allows_retry(self):
        work, course = self.reviewed_work()
        case = self.case
        payload = self.payload(3, action='publish_brs', data={
            'course_id':course, 'attempt_no':1, 'review_revision':1, 'expected_result_version':0,
        })
        endpoint = f'{STAFF}/{work}/commands'
        with connection(case.settings, write=True) as db:
            db.execute("""CREATE TRIGGER simulate_lost_audit BEFORE INSERT ON staff_audit
                WHEN NEW.action='brs.attempt.coursework' BEGIN SELECT RAISE(IGNORE); END""")
        denied = case.post(endpoint, payload, 'teacher')
        self.assertEqual(denied.status_code, 503, denied.text)
        for table in ('brs_event_results', 'brs_attempt_versions', 'coursework_brs_sources'):
            self.assertEqual(case.count(table), 0)
        with connection(case.settings, write=True) as db:
            self.assertEqual(db.execute('SELECT version FROM coursework_recipients WHERE assignment_id=? AND course_id=?',
                                        (work, course)).fetchone()[0], 3)
            self.assertIsNone(db.execute("SELECT 1 FROM staff_audit WHERE action='brs.attempt.coursework'").fetchone())
            self.assertIsNone(db.execute('SELECT 1 FROM coursework_receipts WHERE request_key=?',
                                         (payload['request_key'],)).fetchone())
            db.execute('DROP TRIGGER simulate_lost_audit')
        self.assertEqual(case.post(endpoint, payload, 'teacher').status_code, 200)
        self.assertEqual(case.count('brs_attempt_versions'), 1)

    def test_upgrade_from_0021_requires_and_preserves_publication_audit(self):
        work, course = self.reviewed_work()
        path = self.case.settings.database
        previous = '0022_coursework_brs_authorization'
        release = '0023_coursework_brs_server_audit'
        latest = '0026_attendance_qr'
        tail = ['0024_attendance', '0025_room_availability', latest]
        with closing(sqlite3.connect(path)) as db, db:
            # Recreate the exact 0021 schema in this test's private database.
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'attendance_%'").fetchall():
                db.execute('DROP TRIGGER '+name)
            db.execute('DROP TABLE attendance_qr_receipts')
            db.execute('DROP TABLE attendance_qr_sessions')
            db.execute('DROP TABLE attendance_events')
            db.execute('DROP TABLE attendance_journals')
            db.execute('DROP TABLE room_unavailability')
            db.execute('DROP TABLE building_open_hours')
            db.executemany('DELETE FROM schema_migrations WHERE id=?', [(item,) for item in tail])
            db.execute('DELETE FROM schema_migrations WHERE id IN (?,?)', (previous, release))
            self.insert_unchecked_publication(db, work, course, 'teacher')
        self.assertEqual(status(path)['pending'], [previous, release, *tail])
        with self.assertRaisesRegex(MigrationError, previous):
            update(path, backup=path.with_name('before-missing-audit.sqlite3'))
        self.assertEqual(status(path)['pending'], [previous, release, *tail])
        with closing(sqlite3.connect(path)) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM coursework_brs_sources').fetchone()[0], 1)
            db.execute("""INSERT INTO staff_audit VALUES
                ('legacy-audit','teacher','brs.attempt.coursework','brs_attempt_version','fake-version',1,?)""",
                       (self.case.now,))
        direct = path.with_name('direct-from-0021.sqlite3')
        verified_backup(path, direct)
        self.assertEqual(update(direct, backup=path.with_name('before-direct-0021.sqlite3'))['applied'][-1], latest)

        prefix = path.with_name('through-0022')
        prefix.mkdir()
        for sql in sorted(DIRECTORY.glob('*.sql'))[:22]:
            shutil.copyfile(sql, prefix / sql.name)
        self.assertEqual(update(path, backup=path.with_name('before-0022.sqlite3'), directory=prefix)['applied'][-1], previous)
        self.assertEqual(status(path)['pending'], [release, *tail])
        self.assertEqual(update(path, backup=path.with_name('before-0023.sqlite3'))['applied'][-1], latest)
        self.assertEqual(update(path)['pending'], [])
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT points FROM brs_attempt_versions').fetchall(), [(8,)])
            self.assertEqual(db.execute("SELECT id FROM staff_audit WHERE resource_id='fake-version'").fetchall(),
                             [('legacy-audit',)])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE sql LIKE '%mgimov_coursework_publication%'").fetchone())

    def test_http_lifecycle_replays_versions_lateness_and_review_history(self):
        teacher = self.case.clients['teacher']
        alice = self.case.clients['alice']
        draft = self.draft_payload()
        created = self.case.post(STAFF, draft, 'teacher')
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(self.case.post(STAFF, draft, 'teacher').json(), created.json())
        self.assertEqual(self.case.post(STAFF, {**draft, 'title':'Changed'}, 'teacher').status_code, 409)
        work = created.json()['assignment_id']
        self.assertEqual(alice.get(f'{STUDENT}/{work}').status_code, 404)
        patch = self.payload(data={'title':'Revised lab'})
        headers = {'Origin': self.case.settings.origin,
                   'X-CSRF-Token': teacher.cookies.get(self.case.settings.csrf_cookie)}
        edited = teacher.patch(f'{STAFF}/{work}', json=patch, headers=headers)
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(teacher.patch(f'{STAFF}/{work}', json=patch, headers=headers).json(), edited.json())
        self.assertEqual(self.command(work, 'publish', 1).status_code, 409)
        self.assertEqual(self.command(work, 'publish', 2, grading_mode='independent', max_points=10).status_code, 200)
        self.assertEqual(teacher.patch(f'{STAFF}/{work}', json=self.payload(3, data={'title':'X'}),
                                       headers=headers).status_code, 409)
        own = alice.get(STUDENT, params={'semester_id':'s', 'offering_id':self.flow})
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual([(row['title'],row['max_points']) for row in own.json()['items']], [('Revised lab',10)])
        self.assertEqual(alice.get(STUDENT, params={'semester_id':'old'}).json(), {'items':[]})
        self.assertEqual(teacher.get(STAFF, params={'semester_id':'old'}).json(), {'items':[], 'offerings':[]})
        self.assertEqual(teacher.get(STAFF).json()['offerings'][0]['id'], self.flow)
        self.case.now += 11
        url = f'{STUDENT}/{work}/submissions'
        submit = self.payload(response='Answer')
        first = self.case.post(url, submit, 'alice')
        self.assertEqual(first.status_code, 201, first.text)
        self.assertTrue(first.json()['late'])
        self.assertEqual(self.case.post(url, submit, 'alice').json(), first.json())
        self.assertEqual(self.case.post(url, self.payload(2, response='Early retry'), 'alice').status_code, 409)
        course = self.enrollment['course_id']
        review = dict(course_id=course, attempt_no=1, decision='returned', comment='Please revise')
        self.assertEqual(self.command(work, 'review', 2, **review).status_code, 200)
        self.assertEqual(self.command(work, 'review', 3, **review, reason='Correct comment').status_code, 200)
        self.assertEqual(self.case.post(url, self.payload(4, response='Revision'), 'alice').status_code, 201)
        second = dict(course_id=course, attempt_no=2, decision='reviewed', comment='Accepted', points=8)
        self.assertEqual(self.command(work, 'review', 5, **second).status_code, 200)
        self.assertEqual(self.command(work, 'review', 6, **second).status_code, 422)
        self.assertEqual(self.command(work, 'review', 6, **{**second,'points':9},
                                      reason='Correct score').status_code, 200)
        detail = alice.get(f'{STUDENT}/{work}').json()
        self.assertEqual([r['points'] for r in detail['reviews']], [None,None,8,9])
        self.assertNotIn('created_by', detail)
        self.assertEqual(teacher.get(f'{STAFF}/{work}').json()['recipients'][0]['course_id'], course)
        self.assertEqual(teacher.get(f'{STAFF}/{work}/recipients/{course}').json()['attempts'], detail['attempts'])

    def test_http_permissions_origin_csrf_and_validation(self):
        work = self.create()
        self.assertEqual(self.command(work, 'publish', 1).status_code, 200)
        case = self.case
        path = f'{STUDENT}/{work}'
        alice = case.clients['alice']
        self.assertEqual(alice.get(path).headers['cache-control'], 'no-store')
        self.assertEqual(case.clients['bobby'].get(path).status_code, 404)
        self.assertEqual(case.clients['bobby'].get(STUDENT).json(), {'items':[]})
        self.assertEqual(case.clients['teacher'].get(path).status_code, 403)
        for who in ('admin','outside','second'):
            self.assertEqual(case.clients[who].get(f'{STAFF}/{work}').status_code, 404)
            self.assertEqual(case.clients[who].get(STAFF).json(), {'items':[], 'offerings':[]})
            self.assertEqual(case.post(STAFF, self.draft_payload(), who).status_code, 404)
        with TestClient(case.app, base_url=case.settings.origin) as anonymous:
            self.assertEqual(anonymous.get(path).status_code, 401)
        self.assertEqual(alice.get(STUDENT, params={'student_id':'bobby'}).status_code, 422)
        self.assertEqual(alice.get(STUDENT+'?semester_id=s&semester_id=old').status_code, 422)
        submission = path+'/submissions'
        valid = self.payload(response='Answer')
        for body in ({}, {**valid,'student_id':'alice'}, {**valid,'response':' '},
                     {**valid,'response':'x'*4001}, {**valid,'expected_version':True}):
            self.assertEqual(case.post(submission, body, 'alice').status_code, 422)
        self.assertEqual(case.post(submission, valid, 'bobby').status_code, 404)
        self.assertEqual(case.post(submission, valid, 'alice', Origin='http://other.invalid').status_code, 403)
        self.assertEqual(case.post(submission, valid, 'alice', **{'X-CSRF-Token':'invalid'}).status_code, 403)
        self.assertEqual(alice.post(submission, json=valid).status_code, 403)
        self.assertEqual(alice.post(submission, content='{', headers={
            'Origin': case.settings.origin, 'Content-Type':'application/json',
            'X-CSRF-Token':alice.cookies.get(case.settings.csrf_cookie),
        }).status_code, 422)
        self.assertEqual(case.post(submission, {**valid,'response':'x'*32769}, 'alice').status_code, 413)
        with connection(case.settings, write=True):
            blocked = case.post(submission, valid, 'alice')
        self.assertEqual(blocked.status_code, 503, blocked.text)
        self.assertEqual(set(blocked.json()), {'detail'})
        self.assertEqual(case.count('coursework_attempts'), 0)
        case.now += 61
        self.assertEqual(case.clients['teacher'].get(f'{STAFF}/{work}').status_code, 404)

    def test_http_brs_conflict_and_copy_to_authorized_offering(self):
        case = self.case
        work = self.create()
        with connection(case.settings, write=True) as db:
            plan = db.execute('SELECT plan_id FROM brs_offerings WHERE id=?', (self.flow,)).fetchone()[0]
            db.execute("INSERT INTO brs_event_results VALUES ('existing',?,?,'e')",
                       (self.enrollment['course_id'], plan))
            db.execute("""INSERT INTO brs_attempt_versions VALUES
                ('existing-version','existing',?,1,1,1,7,'teacher',?,NULL)""",
                       (self.enrollment['id'], case.now))
            db.execute("UPDATE lessons SET teacher_id='t' WHERE id='lb'")
        conflict = self.command(work, 'publish', 1, event_code='e')
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()['code'], 'coursework_brs_result_already_published')
        self.assertEqual(set(conflict.json()), {'detail','code'})
        self.assertEqual(case.count('brs_attempt_versions'), 1)
        target = case.flow(plan, 'b')
        self.assertEqual(self.command(work, 'copy', 1, target_offering_id=target).status_code, 404)
        self.assertEqual(case.grant(target, lesson='lb').status_code, 201)
        copied = self.command(work, 'copy', 1, target_offering_id=target)
        self.assertEqual(copied.status_code, 200, copied.text)
        other = copied.json()['copy_id']
        self.assertEqual(self.command(other, 'publish', 1, event_code='e').status_code, 200)
        detail = case.clients['teacher'].get(f'{STAFF}/{other}').json()
        self.assertEqual((detail['offering_id'], detail['max_points'], detail['recipients']), (target,100,[]))
        self.assertEqual(case.clients['alice'].get(f'{STUDENT}/{other}').status_code, 404)
        self.assertEqual(self.command(work, 'publish', 1).status_code, 200)
        self.assertEqual(self.command(work, 'record_in_person', 1,
                                      course_id=self.enrollment['course_id']).status_code, 200)

    def test_http_student_lists_historical_semester_without_granting_new_submission(self):
        case = self.case
        prior = case.flow(case.locked(case.plan('math-old')))
        old_enrollment = case.post(f'{foundation.ADMIN}/offerings/{prior}/enrollments',
                                   {'student_id':'alice','starts_on':'2026-09-01'}).json()
        work = self.create()
        self.assertEqual(self.command(work, 'publish', 1).status_code, 200)
        with connection(case.settings, write=True) as db:
            db.execute("""INSERT INTO coursework_assignments
                (id,offering_id,created_by,kind,title,description,due_at,mode,created_at,status)
                VALUES ('prior-work',?,'teacher','lab','Prior','Synthetic',?,'both',?,'published')""",
                       (prior, case.now-100, case.now-200))
            db.execute('INSERT INTO coursework_recipients VALUES (?,?,?,1)',
                       ('prior-work', old_enrollment['course_id'], old_enrollment['id']))
            db.execute('UPDATE brs_enrollments SET ends_on=? WHERE id=?',
                       ('2026-12-30', old_enrollment['id']))
        alice = case.clients['alice']
        self.assertEqual([item['id'] for item in alice.get(STUDENT).json()['items']], ['prior-work', work])
        self.assertEqual([item['id'] for item in alice.get(STUDENT, params={'semester_id':'old'}).json()['items']],
                         ['prior-work'])
        self.assertEqual(alice.get(f'{STUDENT}/prior-work').status_code, 200)
        self.assertEqual(case.post(f'{STUDENT}/prior-work/submissions',
                                   self.payload(response='Too late'), 'alice').status_code, 404)

    def test_text_submission_unicode_and_byte_limits(self):
        case = self.case
        alice = case.clients['alice']
        headers = {'Origin':case.settings.origin, 'Content-Type':'application/json',
                   'X-CSRF-Token':alice.cookies.get(case.settings.csrf_cookie)}
        for char in ('a', 'я', '😀'):
            with self.subTest(char=char):
                work = self.create()
                self.assertEqual(self.command(work, 'publish', 1).status_code, 200)
                url = f'{STUDENT}/{work}/submissions'
                self.assertEqual(case.post(url, self.payload(response=char*4001), 'alice').status_code, 422)
                body = json.dumps(self.payload(response=char*4000), ensure_ascii=False).encode('utf-8')
                boundary = body.ljust(32768)
                self.assertEqual(alice.post(url, content=boundary+b' ', headers=headers).status_code, 413)
                response = alice.post(url, content=boundary, headers=headers)
                self.assertEqual(response.status_code, 201, response.text)
                self.assertEqual(alice.get(f'{STUDENT}/{work}').json()['attempts'][0]['response'], char*4000)
        self.assertEqual(case.post(STAFF, self.draft_payload(description='😀'*2100), 'teacher').status_code, 413)

    def test_concurrent_submission_receipts_and_version_conflict(self):
        for same_key in (True, False):
            with self.subTest(same_key=same_key):
                work = self.create()
                self.assertEqual(self.command(work, 'publish', 1).status_code, 200)
                first = self.payload(response='Concurrent answer')
                second = first if same_key else self.payload(response='Another answer')
                start = Barrier(2, timeout=5)

                def submit(data):
                    start.wait()
                    return self.case.post(f'{STUDENT}/{work}/submissions', data, 'alice')

                with ThreadPoolExecutor(max_workers=2) as pool:
                    responses = list(pool.map(submit, (first, second)))
                self.assertEqual(sorted(r.status_code for r in responses), [201,201 if same_key else 409])
                if same_key:
                    self.assertEqual(responses[0].json(), responses[1].json())
                detail = self.case.clients['alice'].get(f'{STUDENT}/{work}').json()
                self.assertEqual((len(detail['attempts']), detail['recipient_version']), (1,2))

    def test_projection_names_queue_and_permissions_follow_server_state(self):
        work = self.create()
        self.assertEqual(self.command(work, 'publish', 1).status_code, 200)
        case = self.case
        alice, teacher = case.clients['alice'], case.clients['teacher']
        url = f'{STUDENT}/{work}'
        staff_url = f'{STAFF}/{work}'
        course = self.enrollment['course_id']
        history_url = f'{staff_url}/recipients/{course}'
        other_plan = case.locked(case.plan('math-old'))
        other_flow = case.flow(other_plan)
        other = case.post(f'{foundation.ADMIN}/offerings/{other_flow}/enrollments',
                          {'student_id':'bobby','starts_on':'2026-09-01'}).json()['course_id']
        self.assertEqual(teacher.get(f'{staff_url}/recipients/{other}').status_code, 404)
        self.assertEqual(case.clients['outside'].get(history_url).status_code, 404)
        self.assertEqual(case.clients['bobby'].get(url).status_code, 404)
        self.assertEqual(case.clients['bobby'].get(STUDENT).json(), {'items':[]})
        self.assertEqual((alice.get(url).json()['subject_name'], alice.get(url).json()['group_name']), ('Math','A'))
        self.assertTrue(alice.get(url).json()['can_submit_text'])
        self.assertIsNone(alice.get(url).json()['latest_attempt_state'])
        self.assertEqual(case.post(url+'/submissions', self.payload(response='Answer'), 'alice').status_code, 201)
        state = alice.get(STUDENT).json()['items'][0]
        self.assertEqual((state['latest_attempt_state'],state['has_latest_review'],state['can_resubmit']),
                         ('submitted',False,False))
        staff_list = teacher.get(STAFF).json()
        self.assertEqual(staff_list['offerings'][0]['group_name'], 'A')
        self.assertEqual(staff_list['items'][0]['queue'], dict(recipients=1, submitted=1,
                                                               awaiting_review=1, reviewed=0, returned=0))
        self.assertEqual(teacher.get(staff_url).json()['recipients'][0]['student_name'], 'alice')
        self.assertEqual(teacher.get(history_url).json()['student_name'], 'alice')
        for key in ('student_name','queue','enrollment_id','student_id'):
            self.assertNotIn(key, state)
            self.assertNotIn(key, alice.get(url).json())
        self.assertEqual(self.command(work, 'review', 2, course_id=course, attempt_no=1,
                                      decision='returned', comment='Revise').status_code, 200)
        returned = alice.get(url).json()
        self.assertEqual((returned['latest_attempt_state'],returned['has_latest_review'],returned['can_resubmit']),
                         ('returned',True,True))
        self.assertEqual(teacher.get(staff_url).json()['queue']['returned'], 1)
        with connection(case.settings) as db:
            plan = db.execute('SELECT plan_id FROM brs_offerings WHERE id=?', (self.flow,)).fetchone()[0]
        target = case.flow(plan, 'b')
        transfer = case.post(f"{foundation.ADMIN}/enrollments/{self.enrollment['id']}/transfer",
                             {'target_offering_id':target, 'starts_on':'2027-02-20', 'reason':'Transfer'})
        self.assertEqual(transfer.status_code, 201, transfer.text)
        self.assertFalse(alice.get(url).json()['can_resubmit'])
        self.assertEqual(alice.get(url).json()['group_name'], 'A')
        self.assertEqual(alice.get(url).json()['attempts'][0]['response'], 'Answer')
        self.assertEqual(case.post(f'{foundation.ADMIN}/grants/{self.grant}/revoke', {}).status_code, 200)
        self.assertEqual(teacher.get(STAFF).json(), {'items':[], 'offerings':[]})
        self.assertEqual(teacher.get(history_url).status_code, 404)
        self.assertEqual(self.command(work, 'review', 3, course_id=course, attempt_no=1,
                                      decision='reviewed', comment='Check', reason='Correction').status_code, 404)
        with connection(case.settings, write=True) as db:
            db.execute("UPDATE users SET role='student' WHERE id='teacher'")
        self.assertEqual(teacher.get(STAFF).status_code, 403)
        self.assertEqual(teacher.get(STUDENT).json(), {'items':[]})
        case.now += 3601
        self.assertEqual(alice.get(url).status_code, 401)
        self.assertEqual(case.post(url+'/submissions', self.payload(3, response='Second'), 'alice').status_code, 401)
