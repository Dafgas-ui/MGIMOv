"""Start only on a fresh project-local copy of the saved Astra fixture."""
import json
import os
import socket
import sys
from contextlib import closing
from pathlib import Path

import uvicorn

from backend.commands.demo_credentials import path_for, protect
from backend.config import ROOT
from backend.migrations.manager import open_database, update, verified_backup
from tests.browser.commission_fixture import prepare_commission

SOURCE = ROOT / ".tmp/astra-phase3-browser-20261113/demo.sqlite3"
RUNS = ROOT / ".tmp/playwright-p1"


def run(directory, scenario):
    database = directory / "demo.sqlite3"
    verified_backup(SOURCE, database)
    update(database, backup=directory / "before-migration.sqlite3")
    login, subject_id = {"p1": ("s04", "methods"), "s02": ("s02", "methods"),
                         "s05": ("s05", "law"), "acceptance": ("s04", "methods")}[scenario]
    with closing(open_database(database)) as db:
        target = db.execute("""
            SELECT c.id, p.full_name, s.name
            FROM brs_student_courses c JOIN student_profiles p ON p.user_id=c.student_id
            JOIN curriculum_items i ON i.id=c.curriculum_id
            JOIN subjects s ON s.id=i.subject_id
            WHERE c.student_id=? AND i.subject_id=?
        """, (login, subject_id)).fetchall()
    if len(target) != 1:
        raise ValueError("Expected exactly one matching course in the fixture")
    course, student, subject = target[0]
    instant = prepare_commission(database, course, login) if scenario in ("s02", "s05") else None
    credentials = json.loads(protect(path_for(SOURCE.with_suffix(".dpapi")).read_bytes(), True))

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        os.environ["MGIMOV_DB_PATH"] = str(database)
        os.environ["MGIMOV_ORIGIN"] = origin
        # The parent reads this private pipe. Never print or attach its contents.
        users = ("t02", "t03", "d02", "s04") if scenario == "p1" else ("t02", "t03", "d01", login)
        if scenario == "acceptance":
            users = ("s05", "s06", "t03", "a01", "d01")
        print(json.dumps(dict(origin=origin, course=course, student=student, subject=subject, instant=instant,
                              credentials={user: credentials[user] for user in users})),
              flush=True)
        from backend.app import app
        if instant is not None:
            app.state.auth_service.clock = lambda: instant
        config = uvicorn.Config(app, access_log=False, log_level="warning")
        uvicorn.Server(config).run(sockets=[listener])


if __name__ == "__main__":
    try:
        RUNS.mkdir(exist_ok=True)
        # Parent supplies its own temporary directory so it can clean up after Windows terminates Uvicorn.
        directory = Path(sys.argv[1]).resolve(strict=True)
        if directory.parent != RUNS.resolve() or not directory.name.startswith("run-"):
            raise ValueError("Invalid test directory")
        run(directory, sys.argv[2] if len(sys.argv) == 3 else "p1")
    except Exception:
        sys.exit("Fixture startup failed. Check the Astra SQLite, migration checksums and current-user DPAPI.")
