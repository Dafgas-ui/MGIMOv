"""Restore a published daily SQLite backup to a new project-local test file."""
import argparse
from datetime import date
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from ..config import ROOT
from ..migrations.manager import MigrationError
from .backup_database import private_directory, published_files, sync_directory, validate_snapshot
from .contest_demo_permissions import check_windows_acl, check_windows_chain, windows_user_sid


def restore_database(backup_directory, day, output):
    output = ROOT / Path(output)
    scratch = ROOT / '.tmp'
    if ('..' in output.parts or not output.is_relative_to(scratch)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.sqlite3', output.name)):
        raise ValueError('Choose a new .sqlite3 file inside the test project .tmp directory.')
    parent = output.parent
    backup_directory = Path(backup_directory)
    if not backup_directory.is_absolute() or '..' in backup_directory.parts:
        raise ValueError('Provide an absolute, unredirected daily backup directory.')
    if any(part.casefold().startswith(('.snapshot-', '.quarantine-')) for part in backup_directory.parts):
        raise ValueError('Staging and quarantine are not published backups.')
    bundle = backup_directory / f'daily-{day.isoformat()}'
    if os.name == 'nt':
        sid = windows_user_sid()
        check_windows_chain(parent, sid)
        check_windows_acl(parent, sid, directory=True)
        check_windows_chain(bundle, sid)
        check_windows_acl(backup_directory, sid, directory=True)
        if parent.resolve(strict=True) != parent or bundle.resolve(strict=True) != bundle:
            raise PermissionError('Use canonical Windows paths for restore.')
    elif os.name == 'posix':
        private_directory(parent)
        private_directory(backup_directory)
        private_directory(bundle)
    else:
        raise PermissionError('Unsupported filesystem permissions for restore.')
    if parent.is_relative_to(backup_directory):
        raise ValueError('The restore destination must be outside the backup directory.')
    if any(os.path.lexists(output.with_name(output.name + suffix))
           for suffix in ('', '-wal', '-shm', '-journal')):
        raise FileExistsError('Restore destination or a SQLite sidecar already exists.')
    snapshot, receipt, expected = published_files(bundle)
    for file in (snapshot, receipt):
        if os.name == 'nt':
            check_windows_acl(file, sid, directory=False)
        else:
            info = file.stat()
            if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                raise PermissionError('Unsafe published backup file ownership or permissions.')

    fd, temporary = tempfile.mkstemp(prefix='.restore-', suffix='.sqlite3', dir=parent)
    staged = Path(temporary)
    try:
        with os.fdopen(fd, 'wb') as target, snapshot.open('rb') as source:
            if os.name == 'nt':
                check_windows_acl(staged, sid, directory=False)
            digest = hashlib.sha256()
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
                digest.update(chunk)
            target.flush()
            os.fsync(target.fileno())
        if expected != (digest.hexdigest() + '\n').encode('ascii'):
            raise ValueError('Backup checksum mismatch.')
        validate_snapshot(staged)
        # Same filesystem, atomic no-replace publication even if another writer won the name.
        os.link(staged, output)
    finally:
        staged.unlink()
    sync_directory(parent)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-directory', required=True, type=Path)
    parser.add_argument('--date', required=True, type=date.fromisoformat, help='UTC backup date, YYYY-MM-DD')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--confirm-test-restore', required=True, action='store_true')
    args = parser.parse_args()
    try:
        restore_database(args.backup_directory, args.date, args.output)
    except (OSError, ValueError, MigrationError, sqlite3.Error) as error:
        if type(error) is ValueError:
            print(f'Restore failed: {error}')
        else:
            print(f'Restore failed ({type(error).__name__}); check backup, schema and private paths.')
        return 1
    print('Restore verified and published in the test project.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
