"""A fresh contest demo exercised via the real application routes."""
from contextlib import closing, contextmanager
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import stat
import subprocess
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.commands.contest_demo_permissions import (
    PrivateDemoDirectory, check_windows_acl, check_windows_chain, create_windows_directory, windows_user_sid,
)
from backend.commands.seed_contest_demo import ACCOUNTS, prepare
from backend.config import ROOT, Settings
from backend.db import connection
from backend.migrations.manager import status
from tests.test_foundation import temporary


class ContestDemoTest(unittest.TestCase):
    def require_trusted_checkout(self):
        if os.name == 'nt':
            try:
                check_windows_chain(ROOT, windows_user_sid())
            except PermissionError:
                self.skipTest('Windows demo preparation requires a private checkout.')

    @contextmanager
    def trusted_temporary(self):
        self.require_trusted_checkout()
        if os.name != 'nt':
            with temporary() as path:
                yield path
            return
        scratch = ROOT / '.tmp'
        if not os.path.lexists(scratch):
            create_windows_directory(scratch, windows_user_sid())
        directory = PrivateDemoDirectory(scratch)
        try:
            directory.check_directory()
            yield directory.path
        finally:
            if directory.path.resolve() != directory.path or directory.path.parent != scratch:
                raise RuntimeError('Refusing to clean a redirected test directory.')
            shutil.rmtree(directory.path)

    @unittest.skipUnless(os.name == 'nt', 'Windows ACL integration')
    def test_windows_acl_covers_database_and_live_sqlite_sidecars(self):
        root = self.enterContext(self.trusted_temporary())
        path = prepare({who: secrets.token_urlsafe(24) for who in ACCOUNTS}, parent=root)
        sid = windows_user_sid()
        check_windows_acl(path.parent, sid, directory=True)
        check_windows_acl(path, sid, directory=False)
        with closing(sqlite3.connect(path, isolation_level=None)) as db:
            for mode, suffixes in (('delete', ('-journal',)), ('wal', ('-wal', '-shm'))):
                self.assertEqual(db.execute(f'PRAGMA journal_mode={mode}').fetchone()[0], mode)
                db.execute('BEGIN IMMEDIATE')
                try:
                    db.execute('CREATE TABLE acl_sidecar_probe (id INTEGER)')
                    for suffix in suffixes:
                        file = path.with_name(path.name + suffix)
                        self.assertTrue(file.is_file())
                        check_windows_acl(file, sid, directory=False)
                finally:
                    db.rollback()
            self.assertEqual(db.execute('PRAGMA journal_mode=delete').fetchone()[0], 'delete')

    @unittest.skipUnless(os.name == 'nt', 'Windows ACL integration')
    def test_unsafe_parent_delete_child_fails_before_database_creation(self):
        root = self.enterContext(self.trusted_temporary())
        protected = PrivateDemoDirectory(root)
        check_windows_chain(protected.path, windows_user_sid())
        try:
            original = self.run_fixture_powershell(root, """
                $acl = [IO.Directory]::GetAccessControl($env:MGIMOV_FIXTURE_PATH)
                $acl.GetSecurityDescriptorSddlForm('Access')
            """)
        except (OSError, subprocess.SubprocessError) as error:
            self.skipTest(f'Cannot read the original fixture DACL: {error}')
        self.addCleanup(self.run_fixture_powershell, root, """
            $acl = [IO.Directory]::GetAccessControl($env:MGIMOV_FIXTURE_PATH)
            $acl.SetSecurityDescriptorSddlForm($env:MGIMOV_FIXTURE_DACL, 'Access')
            [IO.Directory]::SetAccessControl($env:MGIMOV_FIXTURE_PATH, $acl)
        """, MGIMOV_FIXTURE_DACL=original)
        credentials = {who: secrets.token_urlsafe(24) for who in ACCOUNTS}

        def widen_parent_after_checkout_check(path, sid):
            check_windows_chain(path, sid)
            grant_error = None
            try:
                self.grant_fixture_right(root, 'DC')
            except (OSError, subprocess.SubprocessError) as error:
                grant_error = error
            try:
                confirmed = self.run_fixture_powershell(root, """
                    $acl = [IO.Directory]::GetAccessControl($env:MGIMOV_FIXTURE_PATH)
                    $raw = [Security.AccessControl.RawSecurityDescriptor]::new(
                        $acl.GetSecurityDescriptorBinaryForm(), 0)
                    foreach ($ace in $raw.DiscretionaryAcl) {
                        if ($ace.AceType -eq 'AccessAllowed' -and
                            $ace.SecurityIdentifier.Value -eq 'S-1-5-11' -and
                            -not ([int]$ace.AceFlags -band 8) -and ($ace.AccessMask -band 0x40)) {
                            'DELETE_CHILD_CONFIRMED'
                            break
                        }
                    }
                """)
            except (OSError, subprocess.SubprocessError) as error:
                self.skipTest(f'Cannot read the fixture DELETE_CHILD ACL: {error}')
            if confirmed != 'DELETE_CHILD_CONFIRMED':
                reason = f' Grant command failed: {grant_error}' if grant_error else ''
                self.skipTest(f'The fixture DACL has no effective DELETE_CHILD allow ACE for S-1-5-11.{reason}')

        with patch('backend.commands.seed_contest_demo.check_windows_chain',
                   side_effect=widen_parent_after_checkout_check):
            with self.assertRaisesRegex(PermissionError, 'Windows path or ACL is not trusted'):
                prepare(credentials, parent=protected.path)
        self.assertEqual(list(root.iterdir()), [protected.path])
        self.assertEqual(list(protected.path.iterdir()), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows ACL integration')
    def test_unsafe_checkout_stops_before_creating_scratch(self):
        root = self.enterContext(temporary())
        self.grant_fixture_right(root, 'M')
        credentials = {who: secrets.token_urlsafe(24) for who in ACCOUNTS}
        with patch('backend.commands.seed_contest_demo.ROOT', root):
            with self.assertRaisesRegex(PermissionError, 'private copy'):
                prepare(credentials)
        self.assertEqual(list(root.iterdir()), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows junction integration')
    def test_junction_parent_is_rejected(self):
        root = self.enterContext(self.trusted_temporary())
        dest = self.enterContext(self.trusted_temporary())
        junction = root / 'redirect'
        try:
            try:
                self.run_fixture_powershell(junction, """
                    New-Item -ItemType Junction -Path $env:MGIMOV_FIXTURE_PATH -Target $env:MGIMOV_FIXTURE_TARGET | Out-Null
                """, MGIMOV_FIXTURE_TARGET=str(dest))
            except (OSError, subprocess.SubprocessError) as error:
                if not os.path.lexists(junction):
                    self.skipTest(f'Windows could not create the test junction: {error}')
            info = junction.lstat()
            self.assertTrue(info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            self.assertEqual(info.st_reparse_tag, stat.IO_REPARSE_TAG_MOUNT_POINT)
            self.assertTrue(junction.samefile(dest))
            with self.assertRaisesRegex(PermissionError, 'Windows path or ACL is not trusted'):
                prepare({who: secrets.token_urlsafe(24) for who in ACCOUNTS}, parent=junction)
            self.assertEqual(list(root.iterdir()), [junction])
            self.assertEqual(list(dest.iterdir()), [])
        finally:
            if os.path.lexists(junction):
                junction.rmdir()

    @staticmethod
    def run_fixture_powershell(path, script, **values):
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        env = dict(os.environ, MGIMOV_FIXTURE_PATH=str(path), **values)
        result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command',
                                 "$ErrorActionPreference='Stop'; " + script],
                                env=env, check=True, capture_output=True, timeout=20)
        return result.stdout.decode('ascii', errors='replace').strip()

    @unittest.skipUnless(os.name == 'nt', 'Windows ACL integration')
    def test_insecure_directory_creation_fails_before_database_creation(self):
        root = self.enterContext(self.trusted_temporary())
        credentials = {who: secrets.token_urlsafe(24) for who in ACCOUNTS}

        def unsafe_creation(path, sid):
            path.mkdir()
            self.grant_fixture_right(path, 'M')

        with patch('backend.commands.contest_demo_permissions.create_windows_directory', side_effect=unsafe_creation):
            with self.assertRaisesRegex(RuntimeError, 'Inspect and clean up only this run directory') as failure:
                prepare(credentials, parent=root)
        directory, = root.iterdir()
        self.assertIn(str(directory), str(failure.exception))
        self.assertEqual(list(directory.iterdir()), [])
        self.assertIsInstance(failure.exception.__cause__, PermissionError)

    @staticmethod
    def grant_fixture_right(root, right):
        icacls = Path(os.environ['SystemRoot']) / 'System32' / 'icacls.exe'
        subprocess.run([icacls, root, '/grant', f'*S-1-5-11:({right})' if right == 'DC' else '*S-1-5-11:M'],
                       check=True, capture_output=True, timeout=15)

    def test_repeat_preparation_and_authenticated_demo(self):
        root = self.enterContext(self.trusted_temporary())
        passwords = {who: secrets.token_urlsafe(24) for who in ACCOUNTS}
        first = prepare(passwords, parent=root)
        original = first.read_bytes()
        second = prepare(passwords, parent=root)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), original)
        settings = Settings(second)
        for path in (first, second):
            report = status(path)
            self.assertEqual(report['applied'][-1], '0019_coursework_parent_guards')
            self.assertEqual(report['pending'], [])
            with connection(Settings(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM coursework_assignments').fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 20)
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

        app = create_app(settings)

        def post(client, path, data, csrf=None):
            token = csrf or client.cookies.get(settings.csrf_cookie)
            return client.post('/api/v1'+path, json=data, headers={
                'Origin':settings.origin, 'X-CSRF-Token':token,
            })

        clients = {}
        for who in ACCOUNTS:
            client = self.enterContext(TestClient(app, base_url=settings.origin))
            csrf = client.get('/api/v1/auth/csrf').json()['csrf']
            signed_in = post(client, '/auth/login', {'login':who,'password':passwords[who]}, csrf)
            self.assertEqual(signed_in.status_code, 200)
            self.assertEqual(signed_in.json()['user']['role'], 'staff' if who == 't01' else 'student')
            clients[who] = client

        def get(client, path, expected=200):
            response = client.get('/api/v1'+path)
            self.assertEqual(response.status_code, expected, response.text)
            return response.json()

        a, b, teacher = (clients[who] for who in ACCOUNTS)
        a_items, b_items = (get(client, '/me/coursework')['items'] for client in (a, b))
        self.assertEqual((len(a_items), len(b_items)), (1, 1))
        work, other = a_items[0], b_items[0]
        self.assertNotEqual(work['id'], other['id'])
        self.assertTrue(work['can_submit_text'])
        with connection(settings) as db:
            courses = dict(db.execute("SELECT student_id,id FROM brs_student_courses WHERE curriculum_id='law'"))
        gradebooks = []
        brs_results = []
        for client, who, group in ((a,'s01','g-a'), (b,'s02','g-b')):
            schedule = get(client, '/me/schedule')
            self.assertEqual(schedule['group']['id'], group)
            self.assertTrue(schedule['days'][0]['lessons'])
            grades = get(client, '/me/gradebook')
            self.assertTrue(grades['semesters'])
            gradebooks.append(grades)
            results = get(client, f'/me/brs/courses/{courses[who]}/results')
            self.assertTrue(results['plans'][0]['events'])
            brs_results.append(results)
            self.assertTrue(any(row.get('preview') for row in get(client, '/me/attestations')['items']))
        self.assertNotEqual(*gradebooks)
        self.assertNotEqual(*brs_results)
        get(b, '/me/brs/courses/'+courses['s01']+'/results', 404)
        get(b, '/me/coursework/'+work['id'], 404)
        get(a, '/me/coursework/'+other['id'], 404)
        get(a, '/staff/coursework', 403)
        get(teacher, '/me/coursework', 403)

        def submit(client, version, response):
            return post(client, f"/me/coursework/{work['id']}/submissions", {
                'expected_version': version, 'request_key':secrets.token_hex(16), 'response':response,
            })

        assigned = get(teacher, '/staff/coursework')['items']
        self.assertEqual({item['id'] for item in assigned}, {work['id'], other['id']})
        self.assertEqual(submit(a, work['recipient_version'], 'Первый ответ').status_code, 201)
        self.assertEqual(submit(b, work['recipient_version'], 'Чужая работа').status_code, 404)

        def review(attempt, version, decision, comment, **fields):
            response = post(teacher, f"/staff/coursework/{work['id']}/commands", {
                'action':'review', 'expected_version':version, 'request_key':secrets.token_hex(16),
                'data':{'course_id':courses['s01'], 'attempt_no':attempt, 'decision':decision,
                        'comment':comment, **fields},
            })
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        returned = review(1, 2, 'returned', 'Уточните второй аргумент')
        self.assertTrue(get(a, '/me/coursework/'+work['id'])['can_resubmit'])
        self.assertEqual(submit(a, returned['version'], 'Уточнённый ответ 😀').status_code, 201)
        review(2, 4, 'reviewed', 'Аргументы проверены', points=8)
        own = get(a, '/me/coursework/'+work['id'])
        self.assertEqual([r['decision'] for r in own['reviews']], ['returned', 'reviewed'])
        self.assertEqual(own['reviews'][-1]['points'], 8)
        self.assertFalse(own['can_resubmit'])
        self.assertEqual(get(b, '/me/coursework/'+other['id'])['attempts'], [])
        self.assertEqual(get(a, '/me/gradebook'), gradebooks[0])
        self.assertEqual(get(a, '/me/brs/courses/'+courses['s01']+'/results'), brs_results[0])
