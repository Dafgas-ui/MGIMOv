"""Cheap readiness, deliberately not a full integrity or schema audit."""
from .db import connection
from .migrations.manager import definitions

class Readiness:
    def __init__(self, settings):
        self.settings = settings
        self.expected = [(name, checksum) for name, checksum, _ in definitions()]

    def check(self):
        with connection(self.settings, timeout=.25) as db:
            db.execute('BEGIN')
            history = [(r['id'], r['checksum']) for r in db.execute('SELECT id,checksum FROM schema_migrations ORDER BY id')]
            if history != self.expected:
                return False
            row = db.execute("SELECT value FROM app_metadata WHERE key='application'").fetchone()
            if row is None or row['value'] != 'mgimov':
                return False
            # Check essential query availability without scanning user data.
            db.execute('SELECT id FROM users LIMIT 0')
            db.execute('SELECT token_hash FROM sessions LIMIT 0')
            return True
