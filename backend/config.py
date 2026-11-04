"""Explicit project-local storage; no dotenv or legacy environment variables."""
from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent

@dataclass(frozen=True)
class Settings:
    database: Path = ROOT / "data" / "deanery.sqlite3"

    origin: str = "http://127.0.0.1:8010"
    session_seconds: int = 8 * 60 * 60

    def __post_init__(self):
        origin=urlsplit(self.origin)
        if (origin.scheme not in ('http','https') or not origin.hostname or origin.username or origin.password
            or origin.path or origin.query or origin.fragment or self.origin!=self.origin.lower()):
            raise ValueError('Exact lowercase origin without path required.')
        origin.port
        if origin.scheme=='http' and origin.hostname not in ('127.0.0.1','localhost','::1'):
            raise ValueError('HTTP is allowed only on loopback.')
        if type(self.session_seconds) is not int or not 60<=self.session_seconds<=86400:
            raise ValueError('Session lifetime must be 60..86400 seconds.')
        path = Path(self.database).expanduser()
        path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_relative_to(ROOT) or path == ROOT:
            raise ValueError("Database must be a file inside the project directory.")
        object.__setattr__(self, "database", path)

    @property
    def secure(self): return self.origin.startswith('https://')

    @property
    def host(self): return urlsplit(self.origin).netloc

    @property
    def session_cookie(self): return ('__Host-' if self.secure else '')+'mgimov_session'

    @property
    def csrf_cookie(self): return ('__Host-' if self.secure else '')+'mgimov_csrf'

    @property
    def login_csrf_cookie(self): return ('__Host-' if self.secure else '')+'mgimov_login_csrf'

    @classmethod
    def from_environment(cls):
        return cls(database=Path(os.environ.get("MGIMOV_DB_PATH", str(ROOT / "data" / "deanery.sqlite3"))), origin=os.environ.get("MGIMOV_ORIGIN", "http://127.0.0.1:8010"))
