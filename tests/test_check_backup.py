from contextlib import closing, redirect_stdout
from datetime import date, datetime, timezone
from io import StringIO
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from backend.commands.backup_database import backup_database, make_private_directory, write_receipt
from backend.commands.check_backup import main
from backend.migrations.manager import DIRECTORY, update
from tests.test_backup_database import private_backup_test_directory


class CheckBackupTest(unittest.TestCase):
    day = date(2026, 11, 14)

    def setUp(self):
        self.workspace = private_backup_test_directory(self)
        self.backups = self.workspace / 'backups'
        make_private_directory(self.backups)

    def published(self, *, directory=None, migrations=DIRECTORY):
        bundle = (directory or self.backups) / f'daily-{self.day.isoformat()}'
        make_private_directory(bundle)
        snapshot = bundle / (bundle.name + '.sqlite3')
        update(snapshot, create=True, directory=migrations)
        return snapshot

    def check(self, *, directory=None, day=None):
        args = ['check_backup', '--directory', str(directory or self.backups)]
        if day is not None:
            args.extend(('--date', day.isoformat()))
        output = StringIO()
        with patch.object(sys, 'argv', args), redirect_stdout(output):
            result = main()
        return result, output.getvalue().strip()

    def assert_failed(self, reason, *, directory=None, day=None):
        day = day or self.day
        self.assertEqual(self.check(directory=directory, day=day),
                         (1, f'MGIMOv backup check failed for UTC {day.isoformat()} ({reason}).'))

    def test_cli_verifies_a_backup_and_leaves_bundle_unchanged(self):
        source = self.workspace / 'source.sqlite3'
        update(source, create=True)
        snapshot = backup_database(source, self.backups, now=datetime(2026, 11, 14, tzinfo=timezone.utc),
                                   max_bytes=25_000_000)
        before = {path.name: path.read_bytes() for path in snapshot.parent.iterdir()}
        result = subprocess.run([sys.executable, '-B', '-m', 'backend.commands.check_backup',
                                 '--directory', str(self.backups), '--date', self.day.isoformat()],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual((result.returncode, result.stdout.strip(), result.stderr),
                         (0, 'MGIMOv backup verified for UTC 2026-11-14.', ''))
        self.assertEqual({path.name: path.read_bytes() for path in snapshot.parent.iterdir()}, before)

    def test_no_published_backup(self):
        self.assert_failed('missing')
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_only_an_older_verified_backup_uses_current_utc_day(self):
        snapshot = self.published()
        write_receipt(snapshot, snapshot.with_suffix('.sha256'))
        with patch('backend.commands.check_backup.datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 15, tzinfo=timezone.utc)
            self.assertEqual(self.check(), (1, 'MGIMOv backup check failed for UTC 2026-11-15 (missing).'))
        clock.now.assert_called_once_with(timezone.utc)

    def test_checksum_mismatch(self):
        snapshot = self.published()
        snapshot.with_suffix('.sha256').write_bytes(b'0' * 64 + b'\n')
        self.assert_failed('invalid')

    def test_corrupted_sqlite_with_matching_checksum(self):
        snapshot = self.published()
        snapshot.write_bytes(b'synthetic corruption')
        write_receipt(snapshot, snapshot.with_suffix('.sha256'))
        self.assert_failed('invalid')

    def test_foreign_key_violation_with_matching_checksum(self):
        snapshot = self.published()
        with closing(sqlite3.connect(snapshot)) as db:
            db.execute("INSERT INTO student_profiles VALUES ('missing', 'Synthetic', 'missing')")
            db.commit()
        write_receipt(snapshot, snapshot.with_suffix('.sha256'))
        self.assert_failed('invalid')

    def test_incompatible_schema_with_matching_checksum(self):
        old_migrations = self.workspace / 'old-migrations'
        old_migrations.mkdir()
        for migration in sorted(DIRECTORY.glob('*.sql'))[:14]:
            shutil.copyfile(migration, old_migrations / migration.name)
        snapshot = self.published(migrations=old_migrations)
        write_receipt(snapshot, snapshot.with_suffix('.sha256'))
        self.assert_failed('invalid')

    def test_staging_and_quarantine_are_excluded(self):
        for name in ('.snapshot-pending', '.quarantine-fixture'):
            with self.subTest(name=name):
                private = self.backups / name
                make_private_directory(private)
                snapshot = self.published(directory=private)
                write_receipt(snapshot, snapshot.with_suffix('.sha256'))
                self.assert_failed('invalid', directory=private)
        self.assert_failed('missing')

    def test_reports_access_failure_without_diagnostics_or_path(self):
        secret_marker = 'sensitive fixture details'
        with patch('backend.commands.check_backup.verify_published', side_effect=PermissionError(secret_marker)):
            self.published()
            self.assert_failed('access-denied')

    def test_rejects_directory_without_required_private_permissions(self):
        unprotected = self.workspace / 'unprotected'
        unprotected.mkdir(mode=0o755)
        if os.name == 'posix':
            unprotected.chmod(0o755)
        self.assert_failed('access-denied', directory=unprotected)
