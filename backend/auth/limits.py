"""Persistent source budgets and bounded process-local verification concurrency.

No global 15-minute denial and no anonymous cross-source account lockout.
IP rotation still requires perimeter controls; this is a single-process MVP.
"""
from contextlib import contextmanager
from hashlib import sha256
from threading import BoundedSemaphore, Lock
from ..db import connection

WINDOW = 60
PAIR_LIMIT = 5
SOURCE_LIMIT = 30

class LoginLimits:
    def __init__(self, settings):
        self.settings = settings
        self.capacity = BoundedSemaphore(2)
        self.lock = Lock()
        self.active = set()  # At most two entries, never an unbounded login dictionary.

    @contextmanager
    def verification(self, login):
        from .service import AuthError
        if not self.capacity.acquire(blocking=False):
            raise AuthError(503, 'Сервис входа занят. Повторите позже.')
        entered = False
        try:
            with self.lock:
                if login in self.active:
                    raise AuthError(503, 'Сервис входа занят. Повторите позже.')
                self.active.add(login)
                entered = True
            yield
        finally:
            if entered:
                with self.lock:
                    self.active.remove(login)
            self.capacity.release()

    @staticmethod
    def buckets(login, peer):
        # JSON-like length delimiters avoid ambiguous source/login concatenations.
        pair = f'{len(peer)}:{peer}:{login}'
        return [(sha256(('v3h:pair:'+pair).encode()).hexdigest(), PAIR_LIMIT),
                (sha256(('v3h:source:'+peer).encode()).hexdigest(), SOURCE_LIMIT)]

    @staticmethod
    def available(db, buckets, now):
        from .service import AuthError
        for key, limit in buckets:
            row = db.execute('SELECT attempts,window_start FROM auth_rate_limits WHERE bucket=?', (key,)).fetchone()
            if row and row['window_start'] > now-WINDOW and row['attempts'] >= limit:
                raise AuthError(429, 'Слишком много попыток с этого источника. Повторите позже.')

    def reserve(self, login, peer, now):
        buckets = self.buckets(login, peer)
        # Repeated denials neither acquire a writer lock nor update counters.
        with connection(self.settings) as db:
            self.available(db, buckets, now)
        receipt = []
        with connection(self.settings, write=True, timeout=.25) as db:
            self.available(db, buckets, now)  # Recheck under writer lock, not a TOCTOU allowance.
            # Bound stale state cleanup to accepted reservations; repeated 429 never writes.
            db.execute('DELETE FROM auth_rate_limits WHERE rowid IN (SELECT rowid FROM auth_rate_limits WHERE window_start<=? LIMIT 20)', (now-WINDOW,))
            for key, _ in buckets:
                row = db.execute('SELECT window_start FROM auth_rate_limits WHERE bucket=?', (key,)).fetchone()
                if row and row['window_start'] > now-WINDOW:
                    start = row['window_start']
                    db.execute('UPDATE auth_rate_limits SET attempts=attempts+1 WHERE bucket=?', (key,))
                else:
                    start = now
                    db.execute('INSERT INTO auth_rate_limits VALUES (?,?,1) ON CONFLICT(bucket) DO UPDATE SET window_start=excluded.window_start,attempts=1', (key, start))
                receipt.append((key, start))
        return receipt

    @staticmethod
    def refund(db, receipt):
        for key, start in receipt:
            row = db.execute('SELECT attempts FROM auth_rate_limits WHERE bucket=? AND window_start=?', (key, start)).fetchone()
            if row is None:
                continue
            if row['attempts'] == 1:
                db.execute('DELETE FROM auth_rate_limits WHERE bucket=? AND window_start=?', (key, start))
            else:
                db.execute('UPDATE auth_rate_limits SET attempts=attempts-1 WHERE bucket=? AND window_start=?', (key, start))
