"""Explicit project-local storage; no dotenv or legacy environment variables."""
from dataclasses import dataclass
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

@dataclass(frozen=True)
class Settings:
    database: Path = ROOT / "data" / "deanery.sqlite3"

    def __post_init__(self):
        path = Path(self.database).expanduser()
        path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_relative_to(ROOT) or path == ROOT:
            raise ValueError("Database must be a file inside the project directory.")
        object.__setattr__(self, "database", path)

    @classmethod
    def from_environment(cls):
        return cls(database=Path(os.environ.get("MGIMOV_DB_PATH", str(ROOT / "data" / "deanery.sqlite3"))))
