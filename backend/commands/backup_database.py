"""Create, verify and rotate operator-managed SQLite snapshots."""
import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import errno
import logging
import hashlib
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
from uuid import uuid4

from ..config import ROOT, Settings
from ..migrations.manager import MigrationError, status, verified_backup
from .contest_demo_permissions import (
    check_windows_acl, check_windows_chain, create_windows_directory, windows_user_sid,
)


SNAPSHOT = re.compile(r'daily-(\d{4}-\d{2}-\d{2})\.sqlite3')
LINUX_DIRECTORY = Path('/opt/mgimov/backups/daily')


class BackupQuotaError(ValueError):
    pass


def private_directory(directory):
    path = Path(os.path.abspath(directory))
    if os.name == 'nt':
        sid = windows_user_sid()
        check_windows_chain(path, sid)
        check_windows_acl(path, sid, directory=True)
        return path
    if path.resolve(strict=True) != path or not path.is_dir():
        raise PermissionError('Backup directory must be a real directory without symlink components.')
    if os.name == 'posix':
        owner = os.geteuid()
        info = path.stat()
        if info.st_uid != owner or stat.S_IMODE(info.st_mode) != 0o700:
            raise PermissionError('Expected a backup directory owned by the job user with mode 0700.')
        for parent in path.parents:
            info = parent.stat()
            if info.st_uid not in (0, owner) or info.st_mode & 0o022:
                raise PermissionError('Unsafe backup directory parent.')
    return path


@contextmanager
def backup_lock(directory):
    path = directory / '.mgimov-backup.lock'
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise PermissionError('Unsafe lock path.')
    # Keep the inode in place. The kernel releases the lock when the handle closes.
    with path.open('a+b') as handle:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def snapshot_digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def directory_bytes(directory):
    return sum(path.lstat().st_size for path in directory.rglob('*')
               if not path.is_symlink() and path.is_file())


def plain_path(path, file_type):
    info = path.lstat()
    return (stat.S_IFMT(info.st_mode) == file_type
            and not getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            and (file_type != stat.S_IFREG or info.st_nlink == 1))


def validate_snapshot(path):
    if not plain_path(path, stat.S_IFREG):
        raise ValueError('Invalid snapshot file.')
    report = status(path, immutable=True)
    if report['state'] != 'managed' or report['pending']:
        raise ValueError('Snapshot schema is not ready.')


def bundle_day(bundle):
    match = SNAPSHOT.fullmatch(bundle.name + '.sqlite3')
    if not match:
        raise ValueError('Expected a published daily backup directory.')
    return date.fromisoformat(match[1])


def published_files(bundle):
    bundle_day(bundle)
    if not plain_path(bundle, stat.S_IFDIR):
        raise ValueError('Invalid published backup directory.')
    snapshot = bundle / (bundle.name + '.sqlite3')
    receipt = bundle / (bundle.name + '.sha256')
    if set(bundle.iterdir()) != {snapshot, receipt} or not all(
        plain_path(path, stat.S_IFREG) for path in (snapshot, receipt)
    ):
        raise ValueError('Invalid published backup contents.')
    with receipt.open('rb') as marker:
        expected = marker.read(66)
    if not re.fullmatch(rb'[0-9a-f]{64}\n', expected):
        raise ValueError('Invalid backup checksum receipt.')
    return snapshot, receipt, expected


def verify_published(bundle):
    snapshot, receipt, expected = published_files(bundle)
    if expected != (snapshot_digest(snapshot) + '\n').encode('ascii'):
        raise ValueError('Backup checksum mismatch.')
    validate_snapshot(snapshot)
    return snapshot, receipt


def rotate(directory, today, keep_successful):
    verified = []
    for bundle in directory.iterdir():
        try:
            day = bundle_day(bundle)
            if day < today:
                verified.append((day, bundle, *verify_published(bundle)))
        except (ValueError, MigrationError, sqlite3.Error):
            continue
    for _, bundle, snapshot, receipt in sorted(verified, reverse=True)[keep_successful - 1:]:
        snapshot.unlink()
        receipt.unlink()
        bundle.rmdir()
    sync_directory(directory)


def write_receipt(database, receipt):
    fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    with os.fdopen(fd, 'wb') as marker:
        marker.write((snapshot_digest(database) + '\n').encode('ascii'))
        marker.flush()
        os.fsync(marker.fileno())


def sync_directory(directory):
    if os.name == 'posix':
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def make_private_directory(path):
    if os.name == 'nt':
        create_windows_directory(path, windows_user_sid())
    else:
        path.mkdir(mode=0o700)


def quarantine(directory, *paths):
    if sum(1 for _ in directory.glob('.quarantine-*')) >= 7:
        raise OSError('Quarantine limit reached; operator review required.')
    target = directory / ('.quarantine-' + uuid4().hex)
    make_private_directory(target)
    for path in paths:
        if path.exists() or path.is_symlink():
            path.rename(target / path.name)
    logging.warning('Interrupted backup quarantined: %s', target.name)


def recover_pending(directory):
    pending = directory / '.snapshot-pending'
    if not pending.exists() and not pending.is_symlink():
        return
    if not plain_path(pending, stat.S_IFDIR):
        quarantine(directory, pending)
        return
    entries = list(pending.iterdir())
    candidates = [p for p in entries if SNAPSHOT.fullmatch(p.name)]
    if len(candidates) != 1:
        quarantine(directory, pending)
        return
    snapshot = candidates[0]
    receipt = snapshot.with_suffix('.sha256')
    writing = receipt.with_suffix('.sha256.pending')
    try:
        if set(entries) - {snapshot, receipt, writing} or (
            os.path.lexists(receipt) and not plain_path(receipt, stat.S_IFREG)
        ):
            raise ValueError('Unexpected staging contents.')
        validate_snapshot(snapshot)
        if writing.exists() or writing.is_symlink():
            quarantine(directory, writing)
        if not receipt.exists():
            write_receipt(snapshot, writing)
            writing.rename(receipt)
        if not receipt.is_file() or receipt.stat().st_size != 65 or receipt.read_bytes() != (snapshot_digest(snapshot) + '\n').encode():
            raise ValueError('Invalid publication receipt.')
    except (ValueError, MigrationError, sqlite3.Error):
        quarantine(directory, pending)
        return
    target = directory / snapshot.stem
    if target.exists() or target.is_symlink():
        quarantine(directory, pending)
        return
    sync_directory(pending)
    pending.rename(target)
    sync_directory(directory)
    logging.warning('Recovered interrupted backup: %s', target.name)


def backup_database(database, directory, *, now, keep_successful=7, max_bytes, production=False):
    database = Path(database).resolve(strict=True)
    directory = private_directory(directory)
    if database.is_relative_to(directory):
        raise ValueError('The source database must be outside the backup directory.')
    if production and directory != LINUX_DIRECTORY:
        raise PermissionError('Use the dedicated production backup directory.')
    if keep_successful < 7 or max_bytes < 1:
        raise ValueError('Retain at least seven successful backups and use a positive quota.')
    with backup_lock(directory):
        recover_pending(directory)
        for path in directory.iterdir():
            if re.fullmatch(r'\.snapshot-[a-z0-9_]{8}', path.name):
                quarantine(directory, path)
        today = now.astimezone(timezone.utc).date()
        target = directory / f'daily-{today}.sqlite3'
        receipt = target.with_suffix('.sha256')
        bundle = directory / target.stem
        if os.path.lexists(bundle):
            snapshot, _ = verify_published(bundle)
            rotate(directory, today, keep_successful)
            return snapshot
        estimated = database.stat().st_size
        wal = database.with_name(database.name + '-wal')
        if wal.exists():
            estimated += wal.stat().st_size
        if directory_bytes(directory) + estimated + 65 > max_bytes:
            raise BackupQuotaError('Snapshot quota exceeded; existing backups retained.')
        if shutil.disk_usage(directory).free < estimated + 65:
            raise OSError(errno.ENOSPC, 'Insufficient free space for snapshot.')
        pending = directory / '.snapshot-pending'
        make_private_directory(pending)
        copying = pending / 'copying.sqlite3'
        verified_backup(database, copying)
        validate_snapshot(copying)
        if directory_bytes(directory) + 65 > max_bytes:
            copying.unlink()
            pending.rmdir()
            raise BackupQuotaError('Snapshot quota exceeded; existing backups retained.')
        if os.name == 'posix':
            copying.chmod(0o600)
        with copying.open('r+b') as snapshot:
            os.fsync(snapshot.fileno())
        staged = copying.rename(pending / target.name)
        sync_directory(pending)
        writing = pending / (receipt.name + '.pending')
        write_receipt(staged, writing)
        writing.rename(pending / receipt.name)
        sync_directory(pending)
        pending.rename(bundle)
        sync_directory(directory)
        verify_published(bundle)
        rotate(directory, today, keep_successful)
        return bundle / target.name


def positive_int(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError('Expected a positive integer.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--production', action='store_true')
    parser.add_argument('--directory', required=True)
    retention = parser.add_mutually_exclusive_group()
    retention.add_argument('--keep-successful', type=positive_int, default=7)
    retention.add_argument('--keep-days', type=positive_int, help=argparse.SUPPRESS)
    parser.add_argument('--max-bytes', type=positive_int, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    os.umask(0o077)
    try:
        if args.keep_days is not None:
            logging.warning('--keep-days is deprecated; retention now counts successful daily backups.')
        production = args.production or os.name == 'posix'
        source = Settings(database=Path(args.db)).database
        if production:
            configured = os.environ.get('MGIMOV_DB_PATH')
            if not configured or not Path(args.db).is_absolute() or not Path(configured).is_absolute():
                raise ValueError('Production requires explicit absolute paths.')
            if source != Settings.from_environment().database or source.is_relative_to(ROOT / '.tmp'):
                raise ValueError('Source does not match production configuration.')
        target = backup_database(
            source, args.directory, production=production,
            now=datetime.now(timezone.utc),
            keep_successful=args.keep_days if args.keep_days is not None else args.keep_successful,
            max_bytes=args.max_bytes,
        )
    except (OSError, ValueError, sqlite3.Error, MigrationError) as error:
        reason = type(error).__name__
        if getattr(error, 'errno', None) == errno.ENOSPC:
            reason = 'Insufficient free space'
        logging.error('SQLite backup job failed (%s, errno=%s).', reason, getattr(error, 'errno', None))
        return 1
    logging.info('SQLite backup verified: %s', target.name)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
