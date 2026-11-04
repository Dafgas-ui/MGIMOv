"""Authentication operations; credentials never appear in DTOs or logs."""
import hashlib
import hmac
import re
import secrets
import time
import uuid
from ..db import connection
from ..security import passwords
from .limits import LoginLimits

class AuthError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)

LOGIN_ERROR = "Неверный логин или пароль."
SESSION_ERROR = "Сессия завершилась. Войдите снова."

def digest(value):
    return hashlib.sha256(value.encode('ascii')).hexdigest()

def valid_token(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', value) is not None

def public_user(row):
    return {key: row[key] for key in ('id', 'login', 'role')}

def resolve(db, token, now, expected=None):
    if not valid_token(token):
        raise AuthError(401, SESSION_ERROR)
    row = db.execute("SELECT u.id,u.login,u.role,s.id AS session_id,s.csrf_hash FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.active=1", (digest(token), now)).fetchone()
    if row is None:
        raise AuthError(401, SESSION_ERROR)
    if expected is not None and expected != row['id']:
        raise AuthError(403, "Аккаунт изменился. Повторите проверку входа.")
    return row

def verify_csrf(row, header, cookie):
    if (not valid_token(header) or not valid_token(cookie) or
        not hmac.compare_digest(header, cookie) or not hmac.compare_digest(digest(header), row['csrf_hash'])):
        raise AuthError(403, "Проверка CSRF не пройдена.")

class AuthService:
    def __init__(self, settings, clock=time.time):
        self.settings, self.clock = settings, clock
        self.limits = LoginLimits(settings)
        # Unknown accounts incur the same Argon2 verification work, with no known dummy password.
        self.dummy_hash = passwords.hash_password(secrets.token_urlsafe(32))

    def login(self, login, password, peer, previous=None):
        login=login.strip().lower()
        with self.limits.verification(login):
            receipt=self.limits.reserve(login,peer,int(self.clock()))
            with connection(self.settings) as db:
                row=db.execute('SELECT * FROM users WHERE login=?',(login,)).fetchone()
            encoded=row['password_hash'] if row else self.dummy_hash
            verified=passwords.verify_password(encoded,password)
            if not verified or row is None or not row['active']:
                raise AuthError(401,LOGIN_ERROR)
        token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        now=int(self.clock())
        with connection(self.settings,write=True,timeout=.25) as db:
            current=db.execute('SELECT * FROM users WHERE id=?',(row['id'],)).fetchone()
            if not current or not current['active'] or current['password_hash']!=encoded or current['role']!=row['role']:
                raise AuthError(401,LOGIN_ERROR)
            self.limits.refund(db,receipt)
            if valid_token(previous):
                db.execute('UPDATE sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL',(now,digest(previous)))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,NULL)',(str(uuid.uuid4()),row['id'],digest(token),digest(csrf),now,now+self.settings.session_seconds))
            return public_user(current),token,csrf

    def me(self, token, expected=None):
        with connection(self.settings) as db:
            return public_user(resolve(db,token,int(self.clock()),expected))

    def logout(self,token,header,cookie,expected=None):
        if not valid_token(token):
            raise AuthError(401,SESSION_ERROR)
        # Invalid/revoked/expired/CSRF-mismatched requests must not wait for a writer.
        with connection(self.settings) as db:
            preliminary=resolve(db,token,int(self.clock()),expected)
            verify_csrf(preliminary,header,cookie)
        # Authentication and CSRF are still rechecked atomically with revocation.
        with connection(self.settings,write=True,timeout=.25) as db:
            now=int(self.clock()); row=resolve(db,token,now,expected)
            verify_csrf(row,header,cookie)
            db.execute('UPDATE sessions SET revoked_at=? WHERE id=?',(now,row['session_id']))
