"""Real HTTP source contracts used by the unified Student deadline view."""
from datetime import datetime
import secrets
import unittest

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.commands.seed_attestations import ACCOUNTS, seed
from backend.config import Settings
from backend.db import connection
from backend.schedule.service import MOSCOW
from tests import test_coursework_http as source
from tests.test_foundation import temporary


class DeadlineSourceTests(unittest.TestCase):
    def test_published_coursework_source_owns_active_submission_and_excludes_drafts(self):
        fixture = source.CourseworkHTTPTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        work = fixture.create()
        alice = fixture.case.clients['alice']
        clock = alice.get('/api/v1/me/time')
        self.assertEqual(clock.status_code,200)
        self.assertEqual(clock.json(),{'server_time':fixture.case.now})
        self.assertEqual(fixture.case.clients['teacher'].get('/api/v1/me/time').status_code,403)
        self.assertEqual(alice.get(source.STUDENT).json()['items'], [])
        self.assertEqual(fixture.command(work, 'publish', 1).status_code, 200)
        row, = alice.get(source.STUDENT).json()['items']
        self.assertTrue(row['needs_submission'])
        self.assertEqual(row['due_at'], fixture.case.now+10)
        self.assertEqual(fixture.case.clients['bobby'].get(source.STUDENT).json()['items'], [])
        self.assertEqual(fixture.case.clients['teacher'].get(source.STUDENT).status_code, 403)
        physical = fixture.case.post(source.STAFF, fixture.draft_payload(mode='in_person'), 'teacher')
        self.assertEqual(physical.status_code, 201)
        self.assertEqual(fixture.command(physical.json()['assignment_id'], 'publish', 1).status_code, 200)
        in_person = next(row for row in alice.get(source.STUDENT).json()['items'] if row['mode']=='in_person')
        self.assertTrue(in_person['needs_submission'])
        self.assertFalse(in_person['can_submit_text'])
        with connection(fixture.case.settings, write=True) as db:
            db.execute("UPDATE brs_enrollments SET ends_on='2027-02-20' WHERE id=?", (fixture.enrollment['id'],))
        self.assertTrue(all(not row['needs_submission'] for row in alice.get(source.STUDENT).json()['items']))

    def test_real_student_attestation_projection_never_exposes_staff_drafts(self):
        with temporary() as root:
            settings = Settings(root/'demo.sqlite3')
            credentials = {key:secrets.token_urlsafe(24) for key in ACCOUNTS}
            seed(settings, credentials, datetime.now(MOSCOW).date())
            app = create_app(settings)
            def read(who):
                with TestClient(app, base_url=settings.origin) as client:
                    csrf = client.get('/api/v1/auth/csrf').json()['csrf']
                    response = client.post('/api/v1/auth/login', json={'login':who,'password':credentials[who]},
                        headers={'Origin':settings.origin,'X-CSRF-Token':csrf})
                    self.assertEqual(response.status_code, 200)
                    return client.get('/api/v1/me/attestations')
            first, second = read('s07'), read('s08')
            self.assertEqual(first.status_code, 200)
            self.assertTrue(first.json()['items'])
            for item in first.json()['items']:
                self.assertEqual([event['kind'] for event in item['history']], ['scheduled'])
                self.assertNotIn('grade', str(item['history']))
            self.assertTrue({row['id'] for row in first.json()['items']}.isdisjoint(
                {row['id'] for row in second.json()['items']}))
            self.assertEqual(read('d01').status_code, 403)
