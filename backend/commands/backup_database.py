"""Create, verify and rotate operator-managed SQLite snapshots."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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


SNAPSHOT = re.compile(r'daily-(\d{4}-\d{2}-\d{2})\.sqlite3')
LINUX_DIRECTORY = Path('/opt/mgimov/backups/daily')


def private_directory(directory):
    path = Path(os.path.abspath(directory))
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


def validate_snapshot(path, *, require_latest=True):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Invalid snapshot file.')
    report = status(path)
    if report['state'] != 'managed' or (require_latest and report['pending']):
        raise ValueError('Snapshot schema is not ready.')


def write_receipt(database, receipt):
    with receipt.open('x', encoding='ascii', newline='\n') as marker:
        marker.write(snapshot_digest(database) + '\n')
        marker.flush()
        os.fsync(marker.fileno())


def sync_directory(directory):
    if os.name == 'posix':
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def quarantine(directory, *paths):
    if sum(1 for _ in directory.glob('.quarantine-*')) >= 7:
        raise OSError('Quarantine limit reached; operator review required.')
    target = directory / ('.quarantine-' + uuid4().hex)
    target.mkdir(mode=0o700)
    for path in paths:
        if path.exists() or path.is_symlink():
            path.rename(target / path.name)
    logging.warning('Interrupted backup quarantined: %s', target.name)


def recover_pending(directory):
    pending = directory / '.snapshot-pending'
    if not pending.exists() and not pending.is_symlink():
        return
    if pending.is_symlink() or not pending.is_dir():
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
        if set(entries) - {snapshot, receipt, writing} or receipt.is_symlink():
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


def backup_database(database, directory, *, now, keep_days, max_bytes, production=False):
    database = Path(database).resolve(strict=True)
    directory = private_directory(directory)
    if database.is_relative_to(directory):
        raise ValueError('The source database must be outside the backup directory.')
    if production and directory != LINUX_DIRECTORY:
        raise PermissionError('Use the dedicated production backup directory.')
    if keep_days < 1 or max_bytes < 1:
        raise ValueError('Retention and quota must be positive.')
    with backup_lock(directory):
        before_recovery = directory / f'daily-{now.astimezone(timezone.utc).date()}'
        existed = before_recovery.exists()
        recover_pending(directory)
        for path in directory.iterdir():
            if re.fullmatch(r'\.snapshot-[a-z0-9_]{8}', path.name):
                quarantine(directory, path)
        today = now.astimezone(timezone.utc).date()
        target = directory / f'daily-{today}.sqlite3'
        receipt = target.with_suffix('.sha256')
        bundle = directory / target.stem
        if bundle.is_symlink() or (bundle.exists() and existed):
            raise FileExistsError('A snapshot already exists for this UTC date.')
        if not bundle.exists() and (target.exists() or receipt.exists() or target.is_symlink() or receipt.is_symlink()):
            if not receipt.exists() and not receipt.is_symlink():
                try:
                    validate_snapshot(target)
                except (ValueError, MigrationError, sqlite3.Error):
                    quarantine(directory, target)
                else:
                    temporary_receipt = directory / '.legacy-recovery.sha256'
                    if temporary_receipt.exists() or temporary_receipt.is_symlink():
                        quarantine(directory, temporary_receipt)
                    write_receipt(target, temporary_receipt)
                    temporary_receipt.rename(receipt)
                    sync_directory(directory)
                    logging.warning('Recovered legacy snapshot without a checksum: %s', target.name)
                    return target
            elif (not target.is_symlink() and target.is_file() and not receipt.is_symlink()
                  and receipt.is_file() and receipt.stat().st_size == 65
                  and receipt.read_bytes() == (snapshot_digest(target) + '\n').encode()):
                raise FileExistsError('A snapshot already exists for this UTC date.')
            else:
                quarantine(directory, target, receipt)
        cutoff = today - timedelta(days=keep_days - 1)
        expired = []
        existing_bytes = directory_bytes(directory)
        for path in directory.iterdir():
            if path.is_symlink():
                continue
            folder = path if path.is_dir() and SNAPSHOT.fullmatch(path.name + '.sqlite3') else None
            if folder:
                path = folder / (folder.name + '.sqlite3')
            match = SNAPSHOT.fullmatch(path.name)
            if not match or path.is_symlink() or not path.is_file():
                continue
            try:
                day = datetime.strptime(match[1], '%Y-%m-%d').date()
            except ValueError:
                continue
            if path.samefile(database):
                raise ValueError('Source database overlaps the rotation namespace.')
            marker = path.with_suffix('.sha256')
            if day < cutoff and not marker.is_symlink() and marker.is_file() and marker.stat().st_size == 65:
                if marker.read_bytes() == (snapshot_digest(path) + '\n').encode('ascii'):
                    if folder is None or set(folder.iterdir()) == {path, marker}:
                        try:
                            validate_snapshot(path, require_latest=False)
                        except (ValueError, MigrationError, sqlite3.Error):
                            continue
                        expired.append((path, marker, folder))
        estimated = database.stat().st_size
        wal = database.with_name(database.name + '-wal')
        if wal.exists():
            estimated += wal.stat().st_size
        if not bundle.exists() and existing_bytes + estimated + 65 > max_bytes:
            raise ValueError('Snapshot quota exceeded.')
        if not bundle.exists() and shutil.disk_usage(directory).free < estimated + 65:
            raise OSError('Insufficient free space for snapshot.')
        pending = directory / '.snapshot-pending'
        if not bundle.exists():
            pending.mkdir(mode=0o700)
            copying = pending / 'copying.sqlite3'
            verified_backup(database, copying)
            validate_snapshot(copying)
            if directory_bytes(directory) + 65 > max_bytes:
                raise ValueError('Snapshot quota exceeded.')
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
        for path, marker, folder in expired:
            path.unlink()
            marker.unlink()
            if folder:
                folder.rmdir()
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
    parser.add_argument('--keep-days', type=positive_int, default=7)
    parser.add_argument('--max-bytes', type=positive_int, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    os.umask(0o077)
    try:
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
            now=datetime.now(timezone.utc), keep_days=args.keep_days, max_bytes=args.max_bytes,
        )
    except (OSError, ValueError, sqlite3.Error, MigrationError) as error:
        logging.error('SQLite backup job failed (%s, errno=%s).', type(error).__name__,
                      getattr(error, 'errno', None))
        return 1
    logging.info('SQLite backup verified: %s', target.name)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
