"""Fixture-level checks for contest-final synthetic SQLite data."""
from datetime import datetime, time, timedelta
import hashlib
import json
import os
import shutil
import stat
import secrets
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from backend.academics.attestation import load as load_attestation
from backend.academics.forecast import student_forecasts
from backend.attendance import student_detail
from backend.auth.service import AuthError, digest, resolve
from backend.brs import service as brs
from backend.commands.seed_attestations import ACCOUNTS, DEANERY, STUDENTS, TEACHERS, seed as seed_base
from backend.commands import seed_attestations, seed_contest_final
from backend.commands.seed_contest_final import ANCHOR_DATE, prepare, seed
from backend.config import ROOT, Settings
from backend.coursework import staff_works, student_works
from backend.db import connection
from backend.migrations.manager import definitions, status
from backend.room_routes import available_rooms
from backend.schedule.service import MOSCOW
from backend.security.passwords import verify_password


def stamp(day, hour=8):
    return int(datetime.combine(day, time(hour), MOSCOW).timestamp())


class ContestFinalDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = ROOT / '.tmp'
        scratch.mkdir(exist_ok=True)
        cls._temporary = tempfile.TemporaryDirectory(dir=scratch, prefix='test-contest-final-')
        cls.addClassCleanup(cls._temporary.cleanup)
        cls.root = ROOT / '.tmp' / cls._temporary.name
        cls.settings = Settings(cls.root / 'contest-final.sqlite3')
        cls.passwords = {key: secrets.token_urlsafe(24) for key in ACCOUNTS}
        cls.summary = seed(cls.settings, cls.passwords, ANCHOR_DATE)
        cls.now = stamp(ANCHOR_DATE)

    def setUp(self):
        self.actors = {key: {'id': key, 'role': 'student' if key in STUDENTS else 'staff'}
                       for key in ACCOUNTS}

    def test_accounts_migrations_and_database_integrity(self):
        self.assertEqual(set(ACCOUNTS), set(STUDENTS + TEACHERS + DEANERY + ('a01',)))
        self.assertEqual(self.summary['accounts'], 20)
        self.assertEqual(self.summary['students'], 11)
        self.assertEqual(self.summary['staff'], 9)
        self.assertEqual(self.summary['rooms'], 51)
        migration_ids = [migration[0] for migration in definitions()]
        migration_status = status(self.settings.database)
        self.assertEqual(migration_status['pending'], [])
        self.assertEqual(migration_status['applied'], migration_ids)
        with connection(self.settings, write=True) as db:
            rows = {row['id']: row for row in db.execute(
                'SELECT id,login,password_hash,role,active FROM users')}
            self.assertEqual(set(rows), set(ACCOUNTS))
            for account in ACCOUNTS:
                self.assertEqual(rows[account]['login'], account)
                self.assertEqual(rows[account]['role'], 'student' if account in STUDENTS else 'staff')
                self.assertEqual(rows[account]['active'], 1)
                self.assertTrue(verify_password(rows[account]['password_hash'], self.passwords[account]))
            self.assertEqual(db.execute('SELECT count(*) FROM rooms').fetchone()[0], 51)
            self.assertEqual(db.execute("SELECT count(*) FROM rooms WHERE id LIKE 'contest-%'").fetchone()[0], 50)
            self.assertEqual(db.execute("SELECT count(*) FROM buildings WHERE id LIKE 'contest-%'").fetchone()[0], 5)
            self.assertGreater(db.execute("SELECT count(DISTINCT capacity) FROM rooms WHERE id LIKE 'contest-%'").fetchone()[0], 5)
            self.assertGreater(db.execute("SELECT count(DISTINCT equipment) FROM rooms WHERE id LIKE 'contest-%'").fetchone()[0], 5)
            self.assertEqual(db.execute("SELECT count(*) FROM building_open_hours WHERE building_id='contest-c'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM room_unavailability").fetchone()[0], 4)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            for account in ACCOUNTS:
                token = secrets.token_urlsafe(32)
                db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,NULL)',
                           (uuid4().hex, account, digest(token), digest(secrets.token_urlsafe(32)),
                            self.now, self.now + 3600))
                actor = resolve(db, token, self.now, account)
                self.assertEqual(actor['role'], self.actors[account]['role'])

    def test_existing_base_seed_remains_compatible_without_optional_overrides(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp', prefix='test-contest-base-') as name:
            settings = Settings(ROOT / '.tmp' / name / 'base.sqlite3')
            passwords = {key: secrets.token_urlsafe(24) for key in ACCOUNTS}
            self.assertEqual(seed_base(settings, passwords, ANCHOR_DATE), 20)
            self.assertEqual(status(settings.database)['pending'], [])

    def test_existing_database_and_repeat_seed_never_overwrite(self):
        before = hashlib.sha256(self.settings.database.read_bytes()).digest()
        with self.assertRaises(ValueError):
            seed(self.settings, self.passwords, ANCHOR_DATE)
        self.assertEqual(hashlib.sha256(self.settings.database.read_bytes()).digest(), before)

        sentinel = self.root / 'existing.sqlite3'
        sentinel.write_bytes(b'pre-existing synthetic file')
        sentinel_before = sentinel.read_bytes()
        with self.assertRaises(ValueError):
            seed(Settings(sentinel), self.passwords, ANCHOR_DATE)
        self.assertEqual(sentinel.read_bytes(), sentinel_before)

        race_target = self.root / 'race.sqlite3'
        raced_bytes = b'created after preflight by another process'

        def populate_then_race(settings, credentials, anchor_date):
            Path(settings.database).write_bytes(b'complete staging placeholder')
            race_target.write_bytes(raced_bytes)
            return {'synthetic': True}

        with patch.object(seed_contest_final, '_populate', side_effect=populate_then_race):
            with self.assertRaises(OSError):
                seed(Settings(race_target), self.passwords, ANCHOR_DATE)
        self.assertEqual(race_target.read_bytes(), raced_bytes)

    def test_final_database_backup_restore_preserves_complete_schema_and_data(self):
        from datetime import timezone
        from backend.commands.backup_database import backup_database, make_private_directory
        from backend.commands.restore_database import restore_database
        from tests.test_backup_database import private_backup_test_directory

        # tempfile's Windows DACL is not the backup helper's private-path contract.
        # Use the same verified fixture as the existing backup/restore tests.
        workspace = private_backup_test_directory(self)
        backups = workspace / 'backups'
        make_private_directory(backups)
        before = hashlib.sha256(self.settings.database.read_bytes()).digest()
        snapshot = backup_database(self.settings.database, backups,
            now=datetime(2026, 11, 21, tzinfo=timezone.utc), max_bytes=20_000_000)
        snapshot_hash = hashlib.sha256(snapshot.read_bytes()).digest()
        output = workspace / 'restored.sqlite3'
        restore_database(backups, ANCHOR_DATE, output)
        self.assertEqual(hashlib.sha256(snapshot.read_bytes()).digest(), snapshot_hash)
        self.assertEqual(hashlib.sha256(self.settings.database.read_bytes()).digest(), before)
        self.assertEqual(status(output)['applied'], [item[0] for item in definitions()])
        with connection(Settings(output)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 20)
            self.assertEqual(db.execute('SELECT count(*) FROM rooms').fetchone()[0], 51)
            self.assertTrue(db.execute('SELECT count(*) FROM attendance_events').fetchone()[0])
            self.assertTrue(db.execute('SELECT count(*) FROM coursework_attempts').fetchone()[0])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_schema WHERE name='attendance_qr_sessions'").fetchone())

    def test_invalid_seed_paths_do_not_create_files(self):
        invalid_paths = (self.root / 'wrong-extension.db', ROOT.parent / f'outside-demo-{uuid4().hex}.sqlite3')
        for path in invalid_paths:
            with self.subTest(path=path.name):
                self.assertFalse(path.exists())
                with self.assertRaises(ValueError):
                    seed(Settings(path), self.passwords, ANCHOR_DATE)
                self.assertFalse(path.exists())

    def test_mid_generation_failure_does_not_publish_or_leave_database(self):
        path = self.root / 'partial.sqlite3'
        with patch.object(seed_contest_final, '_add_coursework', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                seed(Settings(path), self.passwords, ANCHOR_DATE)
        self.assertFalse(path.exists())
        self.assertFalse(list(self.root.glob('.partial.building-*.sqlite3*')))

    def test_no_exam_students_s04_has_no_stale_exam_slot_or_review(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp', prefix='test-no-exam-s04-') as name:
            settings = Settings(Path(name) / 'no-exam.sqlite3')
            passwords = {key: secrets.token_urlsafe(24) for key in ACCOUNTS}
            self.assertEqual(seed_attestations.seed(
                settings, passwords, today=ANCHOR_DATE, no_exam_students={'s04'}), 20)
            with connection(settings) as db:
                course = db.execute("""SELECT id FROM brs_student_courses
                    WHERE student_id='s04' AND curriculum_id='law'""").fetchone()['id']
                slots, events = load_attestation(db, course)
                self.assertEqual(slots, {})
                self.assertEqual(events, [])

    def test_prepare_keeps_credentials_private_and_returns_distinct_runs(self):
        from backend.commands.demo_credentials import protect
        from backend.commands.contest_demo_permissions import check_windows_acl

        passwords = {key: secrets.token_urlsafe(24) for key in ACCOUNTS}
        created = []
        try:
            for _ in range(2):
                database, credential_file, summary = prepare(passwords, anchor_date=ANCHOR_DATE)
                created.append(database.parent)
                self.assertTrue(database.is_file())
                self.assertEqual(summary['anchor_date'], ANCHOR_DATE.isoformat())
                self.assertEqual(status(database)['applied'], [item[0] for item in definitions()])
                if os.name == 'nt':
                    self.assertIsNotNone(credential_file)
                    check_windows_acl(credential_file, seed_contest_final.windows_user_sid(), directory=False)
                    encrypted = credential_file.read_bytes()
                    self.assertTrue(all(password.encode() not in encrypted for password in passwords.values()))
                    self.assertEqual(json.loads(protect(encrypted, decrypt=True)), passwords)
                else:
                    self.assertIsNone(credential_file)
                    self.assertEqual(stat.S_IMODE(database.parent.stat().st_mode), 0o700)
                    self.assertEqual(stat.S_IMODE(database.stat().st_mode), 0o600)
                    self.assertFalse((database.parent / 'credentials.dpapi').exists())
            self.assertNotEqual(created[0], created[1])
            self.assertNotEqual(created[0] / 'demo.sqlite3', created[1] / 'demo.sqlite3')
        finally:
            scratch = (ROOT / '.tmp').resolve()
            for directory in created:
                if directory.is_symlink():
                    raise AssertionError('Refusing to remove a redirected test directory.')
                resolved = directory.resolve(strict=True)
                if not resolved.is_relative_to(scratch):
                    raise AssertionError('Refusing to remove a directory outside this test run.')
                shutil.rmtree(resolved)

    def test_brs_boundaries_debt_and_exam_result_separation(self):
        with connection(self.settings) as db:
            forecasts = {student: next(item for item in student_forecasts(db, self.actors[student], self.now)['items']
                                        if item['subject'] == 'Демонстрационное право')
                         for student in ('s01', 's02', 's03')}
            self.assertEqual([forecasts[key]['published_points'] for key in ('s01', 's02', 's03')], [49, 50, 51])
            self.assertEqual([forecasts[key]['admission'] for key in ('s01', 's02', 's03')], [False, True, True])
            self.assertEqual(forecasts['s01']['result_reason'], 'examiner_decides')
            self.assertIsNone(forecasts['s01']['predicted_result'])
            prior_debt = db.execute("""SELECT t.grade,s.ends_on FROM curriculum_items c
                JOIN student_assessments sa ON sa.student_id='s02'
                JOIN assessments a ON a.id=sa.assessment_id AND a.curriculum_id=c.id
                JOIN assessment_attempts t ON t.assignment_id=sa.id
                JOIN semesters s ON s.id=c.semester_id WHERE c.semester_id='phase3-prior'""").fetchone()
            self.assertEqual(prior_debt['grade'], 2)
            self.assertLess(prior_debt['ends_on'], ANCHOR_DATE.isoformat())
            course = db.execute("SELECT id FROM brs_student_courses WHERE student_id='s01' AND curriculum_id='law'").fetchone()[0]
            slots, events = load_attestation(db, course)
            self.assertEqual(slots, {})
            self.assertEqual(events, [])
            s04_course = db.execute("SELECT id FROM brs_student_courses WHERE student_id='s04' AND curriculum_id='law'").fetchone()[0]
            self.assertEqual(load_attestation(db, s04_course), ({}, []))
            # Student BRS and official gradebook remain distinct; only prior synthetic debt is legacy.
            self.assertTrue(db.execute("SELECT 1 FROM assessment_attempts t JOIN student_assessments s ON s.id=t.assignment_id WHERE s.student_id='s02'").fetchone())

    def test_coursework_scope_deadlines_and_attendance_history(self):
        with connection(self.settings) as db:
            a = student_works(db, self.actors['s01'], self.now)['items']
            b = student_works(db, self.actors['s02'], self.now)['items']
            self.assertEqual(len(a), 1)
            self.assertEqual(len(b), 1)
            self.assertNotEqual(a[0]['id'], b[0]['id'])
            self.assertGreater(a[0]['due_at'], self.now)
            self.assertGreater(b[0]['due_at'], a[0]['due_at'])
            self.assertEqual(a[0]['latest_attempt_no'], 1)
            self.assertEqual(a[0]['latest_attempt_state'], 'submitted')
            self.assertEqual(db.execute("SELECT method FROM coursework_attempts WHERE course_id=(SELECT id FROM brs_student_courses WHERE student_id='s01' AND curriculum_id='law') AND assignment_id=?", (a[0]['id'],)).fetchone()[0], 'text')
            self.assertTrue(staff_works(db, self.actors['t01'], self.now)['items'])
            lesson = db.execute("SELECT id FROM lessons WHERE group_id='g-a' AND subject_id='law'").fetchone()[0]
            self.assertEqual(student_detail(db, self.actors['s01'], lesson)['status'], 'present')
            with self.assertRaises(AuthError) as denied:
                student_detail(db, self.actors['s02'], lesson)
            self.assertEqual(denied.exception.status, 404)
            history = db.execute("""SELECT e.payload FROM attendance_events e
                WHERE e.lesson_id=(SELECT id FROM lessons WHERE group_id='g-a' AND subject_id='language')
                AND e.kind='roster'""").fetchone()[0]
            self.assertIn('s05', history)
            self.assertEqual(db.execute("SELECT group_id FROM student_profiles WHERE user_id='s05'").fetchone()[0], 'g-b')
            # A teacher without the offering assignment cannot list these works.
            self.assertEqual(staff_works(db, self.actors['t02'], self.now)['items'], [])

    def room_map(self, db, day, start, end):
        left = int(start[:2]) * 60 + int(start[3:])
        right = int(end[:2]) * 60 + int(end[3:])
        return {row['id']: row for row in available_rooms(db, day, left, right)}

    def test_rooms_scenarios_use_real_schedule_and_assessment_tables(self):
        with connection(self.settings) as db:
            saturday = self.room_map(db, ANCHOR_DATE, '09:00', '10:00')
            self.assertNotIn('contest-a-01', saturday)
            self.assertNotIn('contest-a-02', saturday)
            self.assertNotIn('contest-a-09', saturday)  # temporary closure
            self.assertNotIn('contest-a-10', saturday)  # permanent closure
            self.assertEqual(saturday['contest-c-01']['access_rules'], 'unknown')
            self.assertEqual(saturday['contest-b-01']['access_rules'], 'known')
            ten = self.room_map(db, ANCHOR_DATE, '10:00', '11:00')
            self.assertIn('contest-a-03', ten)  # cancelled lesson is not a conflict
            assessment_day = ANCHOR_DATE + timedelta(days=2)
            exams = self.room_map(db, assessment_day, '14:00', '15:00')
            self.assertNotIn('contest-e-01', exams)  # active S02 assessment
            self.assertIn('contest-e-03', exams)     # cancelled S11 assessment
            after_maintenance = self.room_map(db, ANCHOR_DATE, '13:00', '14:00')
            self.assertIn('contest-a-09', after_maintenance)
            self.assertNotIn('contest-a-10', after_maintenance)
            sunday = ANCHOR_DATE + timedelta(days=1)
            closed = self.room_map(db, sunday, '09:00', '10:00')
            self.assertFalse(any(row['building_id'] in ('contest-b', 'contest-e') for row in closed.values()))
            moved_from = self.room_map(db, sunday, '11:00', '12:00')
            moved_to = self.room_map(db, sunday, '12:00', '13:00')
            self.assertIn('contest-a-06', moved_from)
            self.assertNotIn('contest-d-01', moved_to)
            active_exam = self.room_map(db, ANCHOR_DATE + timedelta(days=3), '14:00', '15:00')
            self.assertNotIn('contest-a-04', active_exam)
            serialized = str(saturday | exams)
            self.assertNotIn('student', serialized.lower())
            self.assertNotIn('maintenance', serialized.lower())


if __name__ == '__main__':
    unittest.main()
