from datetime import datetime, timezone
import sqlite3
import shutil
import hashlib
from collections import namedtuple
from contextlib import closing
from pathlib import Path
import subprocess
import sys
import time
import sysconfig
import unittest
from unittest.mock import patch

from backend.commands.backup_database import backup_database, backup_lock
from backend.migrations.manager import status, update
from tests.test_foundation import temporary


class BackupDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.root = self.enterContext(temporary())
        self.database = self.root / 'source.sqlite3'
        update(self.database, create=True)
        self.backups = self.root / 'backups'
        self.backups.mkdir(mode=0o700)

    def snapshot(self, quota=10_000_000):
        return backup_database(self.database, self.backups,
                               now=datetime(2026, 11, 14, tzinfo=timezone.utc),
                               keep_days=7, max_bytes=quota)

    def test_verified_snapshot_and_rotation(self):
        expired = self.backups / 'daily-2026-11-07.sqlite3'
        retained = self.backups / 'daily-2026-11-08.sqlite3'
        manual = self.backups / 'pre-release.sqlite3'
        for path in (expired, retained, manual):
            path.write_bytes(b'fixture')
        shutil.copyfile(self.database, expired)
        unrelated = self.backups / 'daily-2026-11-06.sqlite3'
        unrelated.write_bytes(b'unrelated')
        expired.with_suffix('.sha256').write_bytes(
            (hashlib.sha256(expired.read_bytes()).hexdigest() + '\n').encode()
        )
        source = self.database.read_bytes()
        snapshot = self.snapshot()
        self.assertEqual(status(snapshot)['pending'], [])
        restored = self.root / 'restored.sqlite3'
        shutil.copyfile(snapshot, restored)
        self.assertEqual(status(restored)['applied'], status(self.database)['applied'])
        self.assertEqual(self.database.read_bytes(), source)
        self.assertFalse(expired.exists())
        self.assertTrue(retained.exists())
        self.assertTrue(manual.exists())
        self.assertTrue(unrelated.exists())
        with self.assertRaises(FileExistsError):
            self.snapshot()

    def test_failed_backup_preserves_previous_snapshots(self):
        expired = self.backups / 'daily-2026-11-07.sqlite3'
        expired.write_bytes(b'fixture')
        with patch('backend.commands.backup_database.verified_backup', side_effect=sqlite3.OperationalError):
            with self.assertRaises(sqlite3.OperationalError):
                self.snapshot()
        self.assertEqual({p.name for p in self.backups.iterdir()},
                         {expired.name, '.mgimov-backup.lock', '.snapshot-pending'})

    def test_failed_receipt_recovers_verified_snapshot_on_retry(self):
        with patch('backend.commands.backup_database.write_receipt', side_effect=OSError):
            with self.assertRaises(OSError):
                self.snapshot()
        with patch('backend.commands.backup_database.verified_backup', side_effect=AssertionError):
            with self.assertLogs(level='WARNING'):
                snapshot = self.snapshot()
        self.assertTrue(snapshot.is_file())
        self.assertEqual(list(self.backups.glob('.quarantine-*')), [])

    def test_interrupted_copy_is_preserved_in_quarantine(self):
        def interrupted(source, target):
            target.write_bytes(b'partial')
            raise OSError('simulated interruption')

        with patch('backend.commands.backup_database.verified_backup', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.snapshot()
        with self.assertLogs(level='WARNING'):
            self.assertTrue(self.snapshot().is_file())
        quarantined, = self.backups.glob('.quarantine-*/.snapshot-pending/copying.sqlite3')
        self.assertEqual(quarantined.read_bytes(), b'partial')

    def test_partial_receipt_is_quarantined_and_snapshot_recovered(self):
        def interrupted(database, receipt):
            receipt.write_bytes(b'partial')
            raise OSError('simulated interruption')

        with patch('backend.commands.backup_database.write_receipt', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.snapshot()
        with patch('backend.commands.backup_database.verified_backup', side_effect=AssertionError):
            with self.assertLogs(level='WARNING'):
                self.assertTrue(self.snapshot().is_file())
        quarantined, = self.backups.glob('.quarantine-*/daily-*.sha256.pending')
        self.assertEqual(quarantined.read_bytes(), b'partial')

    def test_online_snapshot_matches_committed_wal_state(self):
        with closing(sqlite3.connect(self.database)) as writer:
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            writer.execute("UPDATE schema_migrations SET applied_at='2026-11-14T12:00:00+00:00'")
            writer.commit()
            self.assertGreater(self.database.with_suffix('.sqlite3-wal').stat().st_size, 0)
            writer.execute("UPDATE schema_migrations SET applied_at='2026-11-14T13:00:00+00:00'")
            with closing(sqlite3.connect(self.snapshot())) as restored:
                self.assertEqual(restored.execute('SELECT DISTINCT applied_at FROM schema_migrations').fetchall(),
                                 [('2026-11-14T12:00:00+00:00',)])

    def test_verified_staging_is_recovered_after_rename_failure(self):
        from pathlib import Path
        original = Path.rename

        def fail_publish(path, target):
            if path.name == '.snapshot-pending':
                raise OSError('simulated interruption')
            return original(path, target)

        with patch.object(Path, 'rename', fail_publish):
            with self.assertRaises(OSError):
                self.snapshot()
        with patch('backend.commands.backup_database.verified_backup', side_effect=AssertionError):
            with self.assertLogs(level='WARNING'):
                self.assertTrue(self.snapshot().is_file())

    def test_legacy_snapshot_without_receipt_is_validated(self):
        old = self.backups / 'daily-2026-11-14.sqlite3'
        shutil.copyfile(self.database, old)
        with self.assertLogs(level='WARNING'):
            self.assertEqual(self.snapshot(), old)
        self.assertTrue(old.with_suffix('.sha256').is_file())

    def test_invalid_legacy_snapshot_is_preserved_in_quarantine(self):
        old = self.backups / 'daily-2026-11-14.sqlite3'
        old.write_bytes(b'incomplete')
        with self.assertLogs(level='WARNING'):
            self.assertTrue(self.snapshot().is_file())
        quarantined, = self.backups.glob('.quarantine-*/daily-2026-11-14.sqlite3')
        self.assertEqual(quarantined.read_bytes(), b'incomplete')

    def test_production_helper_rejects_arbitrary_destination(self):
        with self.assertRaises(PermissionError):
            backup_database(self.database, self.backups, production=True,
                            now=datetime.now(timezone.utc), keep_days=7, max_bytes=10_000_000)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_quota_and_lock_prevent_publication(self):
        with self.assertRaisesRegex(ValueError, 'quota'):
            self.snapshot(quota=1)
        with backup_lock(self.backups):
            with self.assertRaises(OSError):
                self.snapshot()
        self.assertTrue(self.snapshot().is_file())

    def test_footprint_and_free_space(self):
        stale = self.backups / '.snapshot-abandoned'
        stale.mkdir()
        (stale / 'partial').write_bytes(b'fixture')
        (self.backups / 'manual.sqlite3').write_bytes(b'manual')
        with self.assertRaisesRegex(ValueError, 'quota'):
            self.snapshot(quota=self.database.stat().st_size + 65)
        usage = namedtuple('Usage', 'total used free')
        with patch('backend.commands.backup_database.shutil.disk_usage', return_value=usage(100, 100, 0)):
            with self.assertRaisesRegex(OSError, 'free space'):
                self.snapshot()
        self.assertTrue((stale / 'partial').exists())

    def test_killed_process_releases_lock(self):
        ready = self.root / 'locked'
        child = subprocess.Popen([sys._base_executable, '-B', '-c',
            'from pathlib import Path; import sys,time,site; '
            f'site.addsitedir({sysconfig.get_path("purelib")!r}); '
            'from backend.commands.backup_database import backup_lock\n'
            'with backup_lock(Path(sys.argv[1])):\n'
            ' Path(sys.argv[2]).touch(); time.sleep(30)\n',
            str(self.backups), str(ready)])
        try:
            deadline = time.monotonic() + 8
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(ready.exists())
            with self.assertRaises(OSError):
                self.snapshot()
        finally:
            child.kill()
            child.wait(timeout=10)
        self.assertTrue(self.snapshot().is_file())
