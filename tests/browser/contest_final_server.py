"""Real Uvicorn over a fresh final demo in an owned private project copy."""
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
from threading import Thread


def main():
    if os.environ.get('MGIMOV_FINAL_FIXTURE_CHILD') != '1':
        from backend.commands.contest_demo_permissions import PrivateDemoDirectory
        directory = PrivateDemoDirectory(Path.home())
        try:
            directory.check_directory()
            for name in ('backend', 'frontend'):
                shutil.copytree(Path.cwd() / name, directory.path / name,
                                ignore=shutil.ignore_patterns('__pycache__'))
            target = directory.path / 'tests' / 'browser'
            target.mkdir(parents=True)
            (directory.path / 'tests' / '__init__.py').touch()
            (target / '__init__.py').touch()
            shutil.copy2(Path(__file__), target / 'contest_final_server.py')
            child = subprocess.Popen([sys.executable, '-B', '-m', 'tests.browser.contest_final_server'],
                                     cwd=directory.path, stdin=subprocess.PIPE,
                                     env={**os.environ, 'MGIMOV_FINAL_FIXTURE_CHILD': '1'})

            def forward_input():
                try:
                    for line in sys.stdin:
                        child.stdin.write(line.encode())
                        child.stdin.flush()
                finally:
                    child.stdin.close()

            Thread(target=forward_input, daemon=True).start()
            try:
                if child.wait():
                    raise RuntimeError('Private demo HTTP child failed.')
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
        finally:
            if directory.path.parent != Path.home() or directory.path.is_symlink():
                raise RuntimeError('Unsafe fixture cleanup.')
            shutil.rmtree(directory.path)
        return

    import uvicorn
    from datetime import datetime, time
    from backend.app import create_app
    from backend.commands.seed_contest_final import ACCOUNTS, ANCHOR_DATE, prepare
    from backend.config import Settings
    from backend.db import connection
    from backend.schedule.service import MOSCOW

    passwords = {account: secrets.token_urlsafe(24) for account in ACCOUNTS}
    database, _, summary = prepare(passwords)
    now = int(datetime.combine(ANCHOR_DATE, time(9, 15), MOSCOW).timestamp())
    with connection(Settings(database)) as db:
        lesson = db.execute("SELECT id FROM lessons WHERE group_id='g-a' AND subject_id='law'").fetchone()[0]
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
        app = create_app(Settings(database, origin=origin))
        app.state.auth_service.clock = lambda: now
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))

        def controls():
            for _ in sys.stdin:
                raise ValueError('No mutable fixture controls.')
            server.should_exit = True

        Thread(target=controls, daemon=True).start()
        # Private IPC only: caller must never log this line or record login traces.
        print(json.dumps({'origin': origin, 'passwords': passwords, 'lesson': lesson,
                          'summary': summary}), flush=True)
        server.run(sockets=[listener])


if __name__ == '__main__':
    main()
