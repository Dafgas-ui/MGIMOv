"""Connections require an existing file; writes use explicit transactions."""
from contextlib import contextmanager
import sqlite3
from .config import Settings

@contextmanager
def connection(settings: Settings, *, write=False):
    path = settings.database.resolve(strict=True)
    database = sqlite3.connect(path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
                               uri=True, isolation_level=None, timeout=5)
    database.row_factory = sqlite3.Row
    try:
        database.execute("PRAGMA foreign_keys=ON")
        if write:
            database.execute("BEGIN IMMEDIATE")
        yield database
        if write:
            database.commit()
    except BaseException:
        if write:
            database.rollback()
        raise
    finally:
        database.close()
