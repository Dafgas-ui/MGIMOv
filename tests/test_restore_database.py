from contextlib import closing
from datetime import date, datetime, timezone
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from backend.commands.backup_database import backup_database, make_private_directory, write_receipt
from backend.commands.contest_demo_permissions import check_windows_acl, windows_user_sid
from backend.commands.restore_database import restore_database
from backend.config import ROOT
from backend.migrations.manager import MigrationError, status, update
from tests.test_backup_database import private_backup_test_directory


class RestoreDatabaseTest(unittest.TestCase):
    day = date(2026, 11, 16)

    def setUp(self):
        self.root = private_backup_test_directory(self)
        self.output = self.root / 'restored.sqlite3'
        self.backups = self.root / 'backups'
        make_private_directory(self.backups)
        db = self.root / 'source.sqlite3'
        update(db, create=True)
        self.snapshot = backup_database(db, self.backups, now=datetime(2026, 11, 16, tzinfo=timezone.utc),
                                        max_bytes=10_000_000)

    def restore(self, output=None):
        return restore_database(self.backups, self.day, output or self.output)

    def assert_no_output(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('.restore-*')), [])

    def refresh_receipt(self):
        receipt = self.snapshot.with_suffix('.sha256')
        receipt.unlink()
        write_receipt(self.snapshot, receipt)

    def test_cli_restores_new_file_without_changing_snapshot(self):
        original = self.snapshot.read_bytes()
        command = [sys.executable, '-B', '-m', 'backend.commands.restore_database',
                   '--backup-directory', str(self.backups), '--date', self.day.isoformat(),
                   '--output', str(self.output)]
        unconfirmed = subprocess.run(command, capture_output=True, timeout=25)
        self.assertEqual(unconfirmed.returncode, 2)
        self.assert_no_output()
        result = subprocess.run([*command, '--confirm-test-restore'], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.output.read_bytes(), original)
        self.assertEqual(self.snapshot.read_bytes(), original)
        self.assertEqual(status(self.output)['pending'], [])
        if os.name == 'nt':
            check_windows_acl(self.output, windows_user_sid(), directory=False)
        else:
            self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    def test_checksum_mismatch_cleans_temporary_file(self):
        self.snapshot.with_suffix('.sha256').write_bytes(b'0' * 64 + b'\n')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.restore()
        self.assert_no_output()

    def test_invalid_sqlite_with_matching_checksum_is_rejected(self):
        self.snapshot.write_bytes(b'not SQLite')
        self.refresh_receipt()
        with self.assertRaises(sqlite3.DatabaseError):
            self.restore()
        self.assert_no_output()

    def test_foreign_key_violation_with_matching_checksum_is_rejected(self):
        with closing(sqlite3.connect(self.snapshot)) as db:
            db.execute("INSERT INTO student_profiles VALUES ('missing', 'Synthetic', 'missing')")
            db.commit()
        self.refresh_receipt()
        with self.assertRaisesRegex(MigrationError, 'внешних ключей'):
            self.restore()
        self.assert_no_output()

    def test_older_migration_requires_matching_release(self):
        migrations = self.root / 'migrations'
        migrations.mkdir()
        for migration in sorted((ROOT / 'backend' / 'migrations').glob('*.sql'))[:14]:
            shutil.copyfile(migration, migrations / migration.name)
        self.snapshot.unlink()
        update(self.snapshot, create=True, directory=migrations)
        self.refresh_receipt()
        with self.assertRaisesRegex(ValueError, 'schema is not ready'):
            self.restore()
        self.assert_no_output()

    def test_published_directory_requires_exact_pair(self):
        self.snapshot.with_suffix('.sha256').unlink()
        with self.assertRaisesRegex(ValueError, 'backup contents'):
            self.restore()
        self.assert_no_output()

    def test_staging_and_quarantine_are_rejected_even_with_valid_pair(self):
        for name in ('.snapshot-pending', '.quarantine-test'):
            with self.subTest(name=name):
                private = self.root / name
                private.mkdir(mode=0o700)
                shutil.copytree(self.snapshot.parent, private / self.snapshot.parent.name)
                with self.assertRaisesRegex(ValueError, 'Staging and quarantine'):
                    restore_database(private, self.day, self.output)
                self.assert_no_output()

    def test_existing_destination_and_sidecar_are_retained(self):
        for path in (self.output, self.output.with_suffix('.sqlite3-wal')):
            with self.subTest(path=path.name):
                path.write_bytes(b'keep')
                with self.assertRaises(FileExistsError):
                    self.restore()
                self.assertEqual(path.read_bytes(), b'keep')
                path.unlink()
        self.assert_no_output()

    def test_destination_created_between_checks_is_never_overwritten(self):
        real_link = os.link

        def race(staged, output):
            output.write_bytes(b'other writer')
            real_link(staged, output)

        with patch('backend.commands.restore_database.os.link', side_effect=race):
            with self.assertRaises(FileExistsError):
                self.restore()
        self.assertEqual(self.output.read_bytes(), b'other writer')
        self.assertEqual(list(self.root.glob('.restore-*')), [])

    def test_private_destination_and_project_boundaries(self):
        with self.assertRaises(ValueError):
            self.restore(self.root / '..' / self.output.name)
        with self.assertRaises(ValueError):
            self.restore(ROOT / self.output.name)
        denied = self.root / 'not-private'
        denied.mkdir(mode=0o755)
        if os.name == 'posix':
            denied.chmod(0o755)
        with self.assertRaises(PermissionError):
            self.restore(denied / self.output.name)
        self.assertEqual(list(denied.iterdir()), [])

    def test_failed_publication_leaves_only_untouched_backup(self):
        original = self.snapshot.read_bytes()
        with patch('backend.commands.restore_database.os.link', side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                self.restore()
        self.assert_no_output()
        self.assertEqual(self.snapshot.read_bytes(), original)

    def test_redirected_source_and_destination_are_rejected(self):
        alias = self.root / 'redirect'
        if os.name == 'nt':
            shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            env = dict(os.environ, MGIMOV_TEST_LINK=str(alias), MGIMOV_TEST_TARGET=str(self.backups))
            result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command',
                                     "$ErrorActionPreference='Stop'; New-Item -ItemType Junction "
                                     "-Path $env:MGIMOV_TEST_LINK -Target $env:MGIMOV_TEST_TARGET | Out-Null"],
                                    env=env, capture_output=True, timeout=20)
            if result.returncode:
                self.skipTest('Windows could not create the test junction.')
            self.addCleanup(alias.rmdir)
        else:
            alias.symlink_to(self.backups, target_is_directory=True)
            self.addCleanup(alias.unlink)
        self.assertTrue(alias.samefile(self.backups))
        with self.assertRaises(PermissionError):
            restore_database(alias, self.day, self.output)
        with self.assertRaises(PermissionError):
            self.restore(alias / self.output.name)
        self.assertFalse((self.backups / self.output.name).exists())
        self.assert_no_output()
