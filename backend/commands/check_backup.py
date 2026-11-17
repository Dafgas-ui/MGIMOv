"""Check the published daily backup for an expected UTC date without modifying it."""
import argparse
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3
import stat

from ..migrations.manager import MigrationError
from .backup_database import plain_path, private_directory, verify_published


def check_backup(directory, day):
    directory = private_directory(directory).resolve(strict=True)
    if any(part.casefold().startswith(('.snapshot-', '.quarantine-')) for part in directory.parts):
        raise ValueError('Expected a daily backup root outside staging and quarantine.')
    bundle = directory / f'daily-{day.isoformat()}'
    if not plain_path(bundle, stat.S_IFDIR):
        raise ValueError('Expected a published backup directory.')
    private_directory(bundle)
    verify_published(bundle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--date', type=date.fromisoformat, help='Expected UTC day (default: today in UTC)')
    args = parser.parse_args()
    day = args.date or datetime.now(timezone.utc).date()
    try:
        check_backup(args.directory, day)
    except FileNotFoundError:
        reason = 'missing'
    except PermissionError:
        reason = 'access-denied'
    except (ValueError, MigrationError, sqlite3.Error):
        reason = 'invalid'
    except OSError:
        reason = 'io-error'
    else:
        print(f'MGIMOv backup verified for UTC {day.isoformat()}.')
        return 0
    print(f'MGIMOv backup check failed for UTC {day.isoformat()} ({reason}).')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
