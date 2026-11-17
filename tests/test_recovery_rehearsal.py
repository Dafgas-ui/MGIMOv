"""Offline Windows release rehearsal, using real CLI subprocesses and loopback HTTP."""
from contextlib import closing, contextmanager
import base64
from datetime import datetime, timezone
import hashlib
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import unittest

import httpx

from backend.commands.backup_database import make_private_directory
from backend.commands.seed_contest_demo import ACCOUNTS, prepare
from backend.config import ROOT
from backend.migrations.manager import status
from tests.test_backup_database import private_backup_test_directory


SERVER = """
import os
from pathlib import Path
import socket
import sys
from threading import Thread

import uvicorn

with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    os.environ['MGIMOV_ORIGIN'] = f'http://127.0.0.1:{port}'
    server = uvicorn.Server(uvicorn.Config('backend.app:app', proxy_headers=False,
                                           log_level='warning', access_log=False))

    def stop_on_eof():
        sys.stdin.read()
        server.should_exit = True

    Thread(target=stop_on_eof, daemon=True).start()
    Path(sys.argv[1]).write_text(str(port), encoding='ascii')
    server.run(sockets=[listener])
"""


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_no_writer(database):
    with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=0,
                                 isolation_level=None)) as connection:
        connection.execute('BEGIN EXCLUSIVE')
        connection.rollback()
        busy, _, _ = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        if busy:
            raise sqlite3.OperationalError('SQLite WAL checkpoint is busy')


@unittest.skipUnless(os.name == 'nt', 'The CLI rehearsal requires a private Windows checkout; use the Ubuntu runbook on Linux.')
class RecoveryRehearsalTest(unittest.TestCase):
    def cli(self, working_directory, module, *args, expected=0):
        proc = subprocess.run([sys.executable, '-B', '-m', f'backend.commands.{module}', *map(str, args)],
                              cwd=working_directory, capture_output=True, text=True, timeout=40)
        self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
        return proc.stdout

    @contextmanager
    def serve(self, working_directory, database, health=200):
        ready = database.parent / ('.port-' + secrets.token_hex(8))
        env = dict(os.environ, MGIMOV_DB_PATH=str(database), PYTHONPATH='')
        with subprocess.Popen([sys.executable, '-B', '-c', SERVER, str(ready)], cwd=working_directory,
                              env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL) as process:
            try:
                deadline = time.monotonic() + 18
                with httpx.Client(timeout=2, trust_env=False) as probe:
                    while process.poll() is None and time.monotonic() < deadline:
                        port = ready.read_text(encoding='ascii').strip() if ready.exists() else ''
                        if port.isdecimal():
                            origin = f'http://127.0.0.1:{port}'
                            try:
                                response = probe.get(origin + '/api/health')
                            except httpx.TransportError:
                                pass
                            else:
                                self.assertEqual(response.status_code, health)
                                self.assertEqual(response.json()['status'], 'ok' if health == 200 else 'unavailable')
                                break
                        time.sleep(0.05)
                    else:
                        self.fail(f'Loopback Uvicorn did not become reachable (exit={process.poll()}).')
                yield origin
            finally:
                process.stdin.close()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    self.fail('Uvicorn did not stop after closing its control pipe.')
                ready.unlink(missing_ok=True)
            self.assertEqual(process.returncode, 0)
        check_no_writer(database)

    @contextmanager
    def login(self, origin, who, passwords):
        with httpx.Client(base_url=origin, timeout=5, trust_env=False) as client:
            csrf = self.get(client, '/auth/csrf')['csrf']
            response = client.post('/api/v1/auth/login', json={'login': who, 'password': passwords[who]},
                                   headers={'Origin': origin, 'X-CSRF-Token': csrf})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['user']['role'], 'staff' if who == 't01' else 'student')
            yield client

    def get(self, client, url, expected=200):
        response = client.get('/api/v1' + url)
        self.assertEqual(response.status_code, expected, url)
        return response.json()

    def write_coursework_history(self, student, teacher, course):
        work, = self.get(student, '/me/coursework')['items']
        url = f"/me/coursework/{work['id']}/submissions"
        review_url = f"/staff/coursework/{work['id']}/commands"

        def post(client, path, version, expected, **data):
            response = client.post('/api/v1' + path, json={**data, 'expected_version': version,
                                   'request_key': secrets.token_hex(16)},
                                   headers={'Origin': str(client.base_url).rstrip('/'),
                                            'X-CSRF-Token': client.cookies['mgimov_csrf']})
            self.assertEqual(response.status_code, expected, path)
            return response.json()

        post(student, url+'/with-files', work['recipient_version'], 201, response='Synthetic attempt one',
             files=[{'name':'answer.txt','content':base64.b64encode(b'Synthetic attachment').decode()}])
        returned = post(teacher, review_url, 2, 200, action='review', data={
            'course_id': course, 'attempt_no': 1, 'decision': 'returned', 'comment': 'Synthetic return',
        })
        post(student, url, returned['version'], 201, response='Synthetic attempt two')
        post(teacher, review_url, 4, 200, action='review', data={
            'course_id': course, 'attempt_no': 2, 'decision': 'reviewed', 'comment': 'Synthetic review', 'points': 8,
        })

    def controls(self, student, other, teacher, course, schedule_date):
        work, = self.get(student, '/me/coursework')['items']
        detail = self.get(student, '/me/coursework/' + work['id'])
        self.assertEqual(len(detail['attempts']), 2)
        self.assertEqual([entry['decision'] for entry in detail['reviews']], ['returned', 'reviewed'])
        self.assertEqual(detail['reviews'][-1]['points'], 8)
        attachment, = detail['files']
        self.assertEqual(attachment['attempt_no'], 1)
        download = '/api/v1/me/coursework/files/' + attachment['id']
        self.assertEqual(student.get(download).content, b'Synthetic attachment')
        self.assertEqual(other.get(download).status_code, 404)
        self.get(other, '/me/coursework/' + work['id'], 404)
        self.get(other, f'/me/brs/courses/{course}/results', 404)
        self.get(student, '/staff/coursework', 403)
        schedule = self.get(student, '/me/schedule?date=' + schedule_date)
        self.assertEqual(schedule['group']['id'], 'g-a')
        self.assertTrue(schedule['days'][0]['lessons'])
        gradebook = self.get(student, '/me/gradebook')
        official, = [item['official_result'] for item in gradebook['exams'] if item['id'] == course]
        self.assertEqual(official['grade'], 5)
        brs = self.get(student, f'/me/brs/courses/{course}/results')
        self.assertEqual(brs['combined_points'], 100)
        self.assertTrue(brs['plans'][0]['events'])
        staff_queue = self.get(teacher, '/staff/coursework')
        self.assertEqual(len(staff_queue['items']), 2)
        return schedule, gradebook, brs, detail, staff_queue

    def test_restore_and_repeated_rollback(self):
        run = private_backup_test_directory(self)
        backup_dir = run / 'daily-backups'
        make_private_directory(backup_dir)
        passwords = {who: secrets.token_urlsafe(24) for who in ACCOUNTS}
        source = prepare(passwords, parent=run)
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as db:
            roles = db.execute('SELECT id, role FROM users ORDER BY id').fetchall()
            course, = db.execute("SELECT id FROM brs_student_courses WHERE curriculum_id='law' AND student_id='s01'").fetchone()
            schedule_date, = db.execute("SELECT date FROM lessons WHERE group_id='g-a' AND subject_id='law'").fetchone()
        self.assertEqual(len(roles), 20)
        self.assertIn(('s01', 'student'), roles)
        self.assertIn(('t01', 'staff'), roles)
        with self.serve(ROOT, source) as origin:
            with self.login(origin, 's01', passwords) as a, self.login(origin, 's02', passwords) as b, self.login(origin, 't01', passwords) as staff:
                self.write_coursework_history(a, staff, course)
                expected = self.controls(a, b, staff, course, schedule_date)
        source_hash = digest(source)
        first_day = datetime.now(timezone.utc).date().isoformat()
        self.cli(ROOT, 'backup_database', '--db', source, '--directory', backup_dir,
                 '--keep-successful', 7, '--max-bytes', 25_000_000)
        bundle, = backup_dir.glob('daily-*')
        backup_day = bundle.name.removeprefix('daily-')
        self.assertIn(backup_day, (first_day, datetime.now(timezone.utc).date().isoformat()))
        backup = bundle / (bundle.name + '.sqlite3')
        receipt = backup.with_suffix('.sha256')
        original_bundle = digest(backup), digest(receipt)
        self.assertEqual(receipt.read_text(encoding='ascii').strip(), original_bundle[0])

        def restore(output, expected=0):
            return self.cli(ROOT, 'restore_database', '--backup-directory', backup_dir, '--date', backup_day,
                            '--output', output, '--confirm-test-restore', expected=expected)

        def verify_recovered(output):
            self.assertEqual(digest(output), original_bundle[0])
            self.cli(ROOT, 'diagnose', '--db', output)
            self.assertEqual(status(output)['applied'][-1], '0023_coursework_brs_server_audit')
            with closing(sqlite3.connect(output.as_uri() + '?mode=ro', uri=True)) as db:
                self.assertEqual(db.execute('SELECT id, role FROM users ORDER BY id').fetchall(), roles)
            with self.serve(ROOT, output) as origin:
                with self.login(origin, 's01', passwords) as a, self.login(origin, 's02', passwords) as b, self.login(origin, 't01', passwords) as staff:
                    self.assertEqual(self.controls(a, b, staff, course, schedule_date), expected)

        restored = run / 'restored.sqlite3'
        restore(restored)
        verify_recovered(restored)
        after_http = digest(restored)
        self.assertIn('FileExistsError', restore(restored, expected=1))
        self.assertEqual(digest(restored), after_http)

        invalid_root = run / 'invalid-backups'
        invalid_bundle = invalid_root / bundle.name
        make_private_directory(invalid_root)
        make_private_directory(invalid_bundle)
        shutil.copyfile(backup, invalid_bundle / backup.name)
        (invalid_bundle / receipt.name).write_bytes(b'0' * 64 + b'\n')
        invalid_output = run / 'invalid.sqlite3'
        rejected = self.cli(ROOT, 'restore_database', '--backup-directory', invalid_root, '--date', backup_day,
                            '--output', invalid_output, '--confirm-test-restore', expected=1)
        self.assertIn('Backup checksum mismatch', rejected)
        self.assertFalse(invalid_output.exists())
        self.assertEqual(list(run.glob('.restore-*')), [])

        candidate = run / 'candidate'
        make_private_directory(candidate)
        shutil.copytree(ROOT / 'backend', candidate / 'backend', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT / 'frontend', candidate / 'frontend')
        (candidate / 'backend/migrations/0024_rehearsal.sql').write_text(
            'CREATE TABLE rehearsal_upgrade (id INTEGER PRIMARY KEY);\n', encoding='ascii')
        candidate_db = candidate / 'candidate.sqlite3'
        shutil.copyfile(backup, candidate_db)
        with closing(sqlite3.connect(candidate_db, isolation_level=None)) as writer:
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            writer.execute("UPDATE study_groups SET name='Synthetic post-backup change' WHERE id='g-a'")
            self.assertTrue(candidate_db.with_suffix('.sqlite3-wal').is_file())
            self.assertTrue(candidate_db.with_suffix('.sqlite3-shm').is_file())
            writer.execute('BEGIN IMMEDIATE')
            with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                check_no_writer(candidate_db)
            writer.rollback()
        with self.serve(candidate, candidate_db, health=503):
            pass

        rollback = run / 'rollback.sqlite3'
        for suffix in ('-wal', '-shm'):
            sidecar = rollback.with_name(rollback.name + suffix)
            sidecar.write_bytes(b'synthetic leftover')
            self.assertIn('FileExistsError', restore(rollback, expected=1))
            self.assertFalse(rollback.exists())
            self.assertEqual(sidecar.read_bytes(), b'synthetic leftover')
            sidecar.unlink()
        restore(rollback)
        verify_recovered(rollback)
        repeated = run / 'rollback-repeat.sqlite3'
        restore(repeated)
        verify_recovered(repeated)

        with closing(sqlite3.connect(candidate_db.as_uri() + '?mode=ro', uri=True)) as db:
            self.assertEqual(db.execute("SELECT name FROM study_groups WHERE id='g-a'").fetchone()[0],
                             'Synthetic post-backup change')
        self.assertEqual(digest(source), source_hash)
        self.assertEqual((digest(backup), digest(receipt)), original_bundle)
