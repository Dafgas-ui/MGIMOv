"""Read-only preconditions and academic fingerprint for a disposable browser run."""
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from backend.academics.attestation import load, state
from backend.config import ROOT
from backend.migrations.manager import open_database

directory = Path(sys.argv[1]).resolve(strict=True)
if directory.parent != (ROOT / ".tmp/playwright-p1").resolve() or not directory.name.startswith("run-acceptance-"):
    raise SystemExit("Expected a disposable acceptance directory")

with closing(open_database(directory / "demo.sqlite3")) as db:
    db.row_factory = sqlite3.Row
    db.execute("BEGIN")
    fingerprint = hashlib.sha256()
    for statement in db.iterdump():
        # Login changes only session/auth bookkeeping. Never emit database rows.
        if not statement.startswith(('INSERT INTO "sessions"', 'INSERT INTO "auth_')):
            fingerprint.update(statement.encode())
    courses = {}
    for login, subject in (("s04", "methods"), ("s05", "law"), ("s10", "methods")):
        course, = db.execute(
            "SELECT id FROM brs_student_courses WHERE student_id=? AND curriculum_id=?", (login, subject)
        ).fetchone()
        slots, events = load(db, course)
        current = state(slots, events)
        courses[login] = dict(course=course, version=len(events), used=current["used"], debt=current["debt"],
                              grade=current["latest"]["data"]["grade"],
                              draft=next((key for key, value in current["stages"].items() if value == "draft"), None))
    print(json.dumps(dict(fingerprint=fingerprint.hexdigest(), courses=courses)))
