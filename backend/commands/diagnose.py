"""Full local read-only diagnosis; never exposed as an HTTP endpoint."""
import argparse
import sqlite3
from ..config import Settings
from ..migrations.manager import MigrationError, status

def main():
    parser = argparse.ArgumentParser(description='Full read-only SQLite/schema diagnosis')
    parser.add_argument('--db', required=True)
    args = parser.parse_args()
    try:
        report = status(Settings(database=args.db).database)
        if report['state'] != 'managed' or report['pending']:
            raise MigrationError('Schema not ready')
        print('Diagnosis OK: integrity, foreign keys, schema and migration checksums.')
        return 0
    except (ValueError, OSError, sqlite3.Error, MigrationError):
        print('Diagnosis failed; inspect the isolated database and migration state. No data printed.')
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
