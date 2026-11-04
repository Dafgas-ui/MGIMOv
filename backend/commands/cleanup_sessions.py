"""Explicit bounded cleanup; no scheduler and no changes to live sessions."""
import argparse
import sqlite3
import time
from ..config import Settings
from ..db import connection
from ..migrations.manager import MigrationError

REVOKED_RETENTION = 86400

def cleanup(settings, *, now=None, limit=100):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('Batch size must be 1..500')
    now = int(time.time()) if now is None else int(now)
    predicate = 'expires_at<=? OR (revoked_at IS NOT NULL AND revoked_at<=?)'
    args = (now, now-REVOKED_RETENTION)
    # An empty cleanup is read-only. Recheck under the transaction before deletion.
    with connection(settings) as db:
        if not db.execute('SELECT 1 FROM sessions WHERE '+predicate+' LIMIT 1', args).fetchone():
            return 0
    with connection(settings, write=True, timeout=.25) as db:
        rows = db.execute('SELECT id FROM sessions WHERE '+predicate+' LIMIT ?', (*args, limit)).fetchall()
        count = 0
        for row in rows:
            count += db.execute('DELETE FROM sessions WHERE id=? AND ('+predicate+')', (row['id'], *args)).rowcount
        return count

def main():
    parser = argparse.ArgumentParser(description='Delete only expired or old-revoked sessions in a bounded batch')
    parser.add_argument('--db', required=True)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--confirm-cleanup', action='store_true', required=True)
    args = parser.parse_args()
    try:
        count = cleanup(Settings(database=args.db), limit=args.limit)
        print('Sessions removed:', count)
        return 0
    except (ValueError, OSError, sqlite3.Error, MigrationError):
        print('Cleanup failed. Check the explicit database path and schema.')
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
