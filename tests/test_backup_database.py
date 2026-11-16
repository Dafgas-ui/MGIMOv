from datetime import datetime, timezone
import sqlite3
import shutil
import hashlib
import os
from collections import namedtuple
from contextlib import closing
from pathlib import Path
import subprocess
import sys
import time
import sysconfig
import unittest
from unittest.mock import patch

from backend.commands.backup_database import backup_database, backup_lock, make_private_directory
from backend.commands.contest_demo_permissions import (
    PrivateDemoDirectory, check_windows_chain, create_windows_directory, windows_user_sid,
)
from backend.config import ROOT
from backend.migrations.manager import status, update


def private_backup_test_directory(test):
    scratch = ROOT / '.tmp'
    if os.name == 'nt':
        sid = windows_user_sid()
        try:
            check_windows_chain(ROOT, sid)
            if not os.path.lexists(scratch):
                create_windows_directory(scratch, sid)
            check_windows_chain(scratch, sid)
        except PermissionError:
            test.skipTest('Backup tests require a trusted private Windows checkout.')
    else:
        scratch.mkdir(exist_ok=True)
    workspace = PrivateDemoDirectory(scratch)
    test.addCleanup(shutil.rmtree, workspace.path)
    return workspace.path


class BackupDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.root = private_backup_test_directory(self)
        self.database = self.root / 'source.sqlite3'
        update(self.database, create=True)
        self.backups = self.root / 'backups'
        make_private_directory(self.backups)

    def snapshot(self, quota=10_000_000, *, day=14):
        return backup_database(self.database, self.backups,
                               now=datetime(2026, 11, day, tzinfo=timezone.utc),
                               max_bytes=quota)

    def test_verified_snapshot_and_rotation(self):
        manual = self.backups / 'pre-release.sqlite3'
        manual.write_bytes(b'fixture')
        source = self.database.read_bytes()
        days = (1, 2, 4, 6, 8, 11, 20, 28)
        snapshots = [self.snapshot(day=day) for day in days[:-1]]
        self.assertTrue(all(path.is_file() for path in snapshots))
        snapshot = self.snapshot(day=days[-1])
        self.assertEqual(status(snapshot)['pending'], [])
        restored = self.root / 'restored.sqlite3'
        shutil.copyfile(snapshot, restored)
        self.assertEqual(status(restored)['applied'], status(self.database)['applied'])
        self.assertEqual(self.database.read_bytes(), source)
        self.assertFalse(snapshots[0].parent.exists())
        self.assertTrue(all(path.is_file() for path in snapshots[1:]))
        self.assertTrue(manual.exists())
        with patch('backend.commands.backup_database.verified_backup', side_effect=AssertionError):
            self.assertEqual(self.snapshot(day=days[-1]), snapshot)

    def test_corrupt_daily_bundle_does_not_displace_an_older_success(self):
        verified = [self.snapshot(day=day) for day in (1, 2, 4, 6, 8, 11)]
        broken = self.snapshot(day=12)
        broken.write_bytes(b'bad database')
        broken.with_suffix('.sha256').write_bytes((hashlib.sha256(broken.read_bytes()).hexdigest() + '\n').encode())
        self.snapshot(day=14)
        self.assertTrue(all(path.is_file() for path in verified))
        self.assertEqual(broken.read_bytes(), b'bad database')

    def test_invalid_same_day_receipt_fails_without_replacing_backup(self):
        snapshot = self.snapshot()
        original = snapshot.read_bytes()
        receipt = snapshot.with_suffix('.sha256')
        receipt.write_bytes(b'0' * 64 + b'\n')
        with patch('backend.commands.backup_database.verified_backup', side_effect=AssertionError):
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                self.snapshot()
        self.assertEqual(snapshot.read_bytes(), original)
        self.assertEqual(receipt.read_bytes(), b'0' * 64 + b'\n')

    def test_failed_backup_preserves_previous_snapshots(self):
        previous = [self.snapshot(day=day) for day in (1, 2, 3, 4, 5, 6, 7)]
        expected = {path: path.read_bytes() for path in previous}
        with patch('backend.commands.backup_database.verified_backup', side_effect=sqlite3.OperationalError):
            with self.assertRaises(sqlite3.OperationalError):
                self.snapshot()
        self.assertEqual({path: path.read_bytes() for path in previous}, expected)
        self.assertFalse((self.backups / 'daily-2026-11-14').exists())

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
        previous = [self.snapshot(day=day) for day in (1, 2, 3, 4, 5, 6, 7)]

        def fail_publish(path, target):
            if path.name == '.snapshot-pending':
                raise OSError('simulated interruption')
            return original(path, target)

        with patch.object(Path, 'rename', fail_publish):
            with self.assertRaises(OSError):
                self.snapshot()
        self.assertTrue(all(path.is_file() for path in previous))
        self.assertFalse((self.backups / 'daily-2026-11-14').exists())
        with patch('backend.commands.backup_database.verified_backup', side_effect=AssertionError):
            with self.assertLogs(level='WARNING'):
                self.assertTrue(self.snapshot().is_file())
        self.assertFalse(previous[0].exists())
        self.assertTrue(all(path.is_file() for path in previous[1:]))

    def test_legacy_snapshot_without_receipt_is_preserved(self):
        old = self.backups / 'daily-2026-11-14.sqlite3'
        shutil.copyfile(self.database, old)
        self.assertNotEqual(self.snapshot(), old)
        self.assertEqual(old.read_bytes(), self.database.read_bytes())
        self.assertFalse(old.with_suffix('.sha256').exists())

    def test_invalid_legacy_snapshot_is_preserved(self):
        old = self.backups / 'daily-2026-11-14.sqlite3'
        old.write_bytes(b'incomplete')
        self.assertTrue(self.snapshot().is_file())
        self.assertEqual(old.read_bytes(), b'incomplete')

    def test_production_helper_rejects_arbitrary_destination(self):
        with self.assertRaises(PermissionError):
            backup_database(self.database, self.backups, production=True,
                            now=datetime.now(timezone.utc), max_bytes=10_000_000)
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
