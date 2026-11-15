import ast
from contextlib import contextmanager, closing
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import sysconfig
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from backend.app import ASSETS, create_app
from backend.config import ROOT, Settings
from backend.db import connection
from backend.migrations.manager import MigrationError, status, update
from backend.security.passwords import hash_password, verify_password, valid_password

@contextmanager
def temporary():
    (ROOT / ".tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / ".tmp", prefix="test-") as name:
        yield Path(name)

class FoundationTests(unittest.TestCase):
    def test_migration_sql_error_identifies_migration_and_preserves_cause(self):
        with temporary() as root:
            migrations = root / 'migrations'
            migrations.mkdir()
            (migrations / '0001_initial.sql').write_text(
                'CREATE TABLE audit_fixture (id TEXT);', encoding='utf8')
            (migrations / '0002_fixture.sql').write_text(
                "ALTER TABLE audit_fixture ADD COLUMN status TEXT DEFAULT 'draft' CHECK(status='draft');",
                encoding='utf8')
            database = root / 'initial.sqlite3'
            with self.assertRaisesRegex(MigrationError, '0002_fixture, SQLITE_AUTH') as error:
                update(database, create=True, directory=migrations)
            self.assertEqual(error.exception.__cause__.sqlite_errorname, 'SQLITE_AUTH')
            with closing(sqlite3.connect(database)) as db:
                self.assertEqual(db.execute("SELECT name FROM sqlite_master").fetchall(), [])

    def test_configuration_is_project_local_and_ignores_legacy_environment(self):
        with patch.dict(os.environ, {"DASHBOARD_DB_PATH": "unused.sqlite3"}, clear=True):
            self.assertEqual(Settings.from_environment().database, ROOT / "data/deanery.sqlite3")
        with patch.dict(os.environ, {"MGIMOV_DB_PATH": ".tmp/custom.sqlite3"}):
            self.assertEqual(Settings.from_environment().database, ROOT / ".tmp/custom.sqlite3")
        with self.assertRaises(ValueError):
            Settings(database=ROOT.parent / "outside.sqlite3")
        with self.assertRaises(ValueError):
            Settings(database=ROOT)

    def test_missing_database_not_created_by_app_or_connection(self):
        with temporary() as root:
            settings = Settings(database=root / "missing.sqlite3")
            with TestClient(create_app(settings)) as client:
                self.assertEqual(client.get("/api/health").status_code, 503)
                self.assertEqual(client.get("/api/health").json(), {"status": "unavailable"})
                self.assertEqual(client.get("/").status_code, 200)
            with self.assertRaises(FileNotFoundError):
                with connection(settings):
                    pass
            self.assertFalse(settings.database.exists())

    def test_health_assets_and_no_unlisted_file_serving(self):
        with temporary() as root:
            path = root / "test.sqlite3"
            update(path, create=True)
            with TestClient(create_app(Settings(path))) as client:
                response = client.get("/api/health")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"status": "ok"})
                self.assertEqual(response.headers["cache-control"], "no-store")
                for url in ASSETS:
                    response = client.get(url)
                    self.assertEqual(response.status_code, 200, url)
                    self.assertIn("default-src 'none'", response.headers["content-security-policy"])
                self.assertIn("Конкурсный концепт. Неофициальный сервис. Все данные вымышлены", client.get("/").text)
                self.assertIn("javascript", client.get("/js/app.js").headers["content-type"])
                for url in ("/data/deanery.sqlite3", "/.env", "/backend/config.py", "/api/events", "/api/schedule", "/api/auth/me"):
                    self.assertEqual(client.get(url).status_code, 404, url)

    def test_health_rejects_corrupt_and_unmanaged_database(self):
        with temporary() as root:
            path = root / "bad.sqlite3"
            path.write_bytes(b"not sqlite")
            with TestClient(create_app(Settings(path))) as client:
                self.assertEqual(client.get("/api/health").status_code, 503)
            path.write_bytes(b"")
            with TestClient(create_app(Settings(path))) as client:
                self.assertEqual(client.get("/api/health").status_code, 503)

    def test_transactions_foreign_keys_and_readonly_mode(self):
        with temporary() as root:
            settings = Settings(root / "test.sqlite3")
            update(settings.database, create=True)
            with self.assertRaises(RuntimeError):
                with connection(settings, write=True) as db:
                    self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                    db.execute("INSERT INTO app_metadata VALUES ('temporary','value')")
                    raise RuntimeError("rollback")
            with connection(settings) as db:
                self.assertIsNone(db.execute("SELECT value FROM app_metadata WHERE key='temporary'").fetchone())
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute("DELETE FROM app_metadata")
            with connection(settings, write=True) as db:
                db.execute("INSERT INTO app_metadata VALUES ('committed','value')")
            with connection(settings) as db:
                self.assertEqual(db.execute("SELECT value FROM app_metadata WHERE key='committed'").fetchone()[0], "value")

    def test_migration_repeat_checksum_and_explicit_backup(self):
        with temporary() as root:
            path, definitions = root / "test.sqlite3", root / "migrations"
            definitions.mkdir()
            first = (ROOT / "backend/migrations/0001_initial.sql").read_text()
            (definitions / "0001_initial.sql").write_text(first)
            update(path, create=True, directory=definitions)
            self.assertEqual(status(path, definitions)["applied"], ["0001_initial"])
            self.assertEqual(update(path, directory=definitions)["pending"], [])
            (definitions / "0002_extra.sql").write_text("CREATE TABLE extra (id INTEGER PRIMARY KEY);")
            with self.assertRaises(MigrationError):
                update(path, directory=definitions)
            backup = root / "backup.sqlite3"
            update(path, backup=backup, directory=definitions)
            self.assertEqual(status(path, definitions)["applied"], ["0001_initial", "0002_extra"])
            self.assertEqual(status(backup, definitions)["applied"], ["0001_initial"])
            (definitions / "0001_initial.sql").write_text(first + "-- modified\n")
            with self.assertRaises(MigrationError):
                status(path, definitions)

    def test_failed_migration_batch_rolls_back_and_protects_metadata(self):
        with temporary() as root:
            definitions = root / "migrations"
            definitions.mkdir()
            (definitions / "0001_initial.sql").write_text("CREATE TABLE example (id INTEGER PRIMARY KEY);")
            path = root / "test.sqlite3"
            update(path, create=True, directory=definitions)
            (definitions / "0002_failure.sql").write_text("CREATE TABLE extra (id INTEGER); INSERT INTO missing VALUES (1);")
            with self.assertRaises(MigrationError):
                update(path, backup=root / "backup.sqlite3", directory=definitions)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM schema_migrations").fetchone()[0], 1)
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='extra'").fetchone())
            (definitions / "0002_failure.sql").write_text("DELETE FROM schema_migrations;")
            with self.assertRaises(MigrationError):
                update(path, backup=root / "backup2.sqlite3", directory=definitions)

    def test_cli_init_status_and_no_overwrite(self):
        with temporary() as root:
            path = root / "cli.sqlite3"
            def cli(command, database=path):
                return subprocess.run([sys.executable, "-B", "-m", "backend.migrations", command, "--db", str(database)],
                    cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(cli("init").returncode, 0)
            before = path.read_bytes()
            self.assertEqual(cli("status").returncode, 0)
            self.assertEqual(cli("init").returncode, 1)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(cli("init", ROOT.parent / "outside.sqlite3").returncode, 1)

    def test_argon2id_salts_verification_and_bounds(self):
        password = secrets.token_urlsafe(24)
        first, second = hash_password(password), hash_password(password)
        self.assertTrue(first.startswith("$argon2id$"))
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password(first, password))
        self.assertFalse(verify_password(first, secrets.token_urlsafe(24)))
        self.assertFalse(valid_password("x" * 14))
        self.assertFalse(valid_password("x" * 129))
        self.assertFalse(verify_password("not a hash", password))

    def test_python_syntax_and_no_source_runtime_dependency(self):
        for path in (ROOT / "backend").rglob("*.py"):
            text = path.read_text(encoding="utf-8-sig")
            ast.parse(text, filename=str(path))
            self.assertNotIn("AI-Student-Dashboard", text)
        for path in (ROOT / "frontend/js").rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            if path.name == "account.js":
                # The only approved localStorage access is account-bound appearance preferences.
                self.assertEqual(text.count("globalThis.localStorage"), 1)
                self.assertNotIn("localStorage", text.replace("globalThis.localStorage", ""))
            else:
                self.assertNotIn("localStorage", text)
            self.assertNotIn("127.0.0.1", text)

    def test_real_uvicorn_start_health_and_page(self):
        with temporary() as root:
            path = root / "http.sqlite3"
            update(path, create=True)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = dict(os.environ, MGIMOV_DB_PATH=str(path), PYTHONDONTWRITEBYTECODE="1")
            with (root / "server.log").open("wb") as log:
                # Use the actual interpreter, not the Windows venv redirector process.
                script = ("import site; site.addsitedir(" + repr(sysconfig.get_path("purelib")) + "); "
                          "import uvicorn; uvicorn.run('backend.app:app', host='127.0.0.1', port=" + str(port) + ", proxy_headers=False)")
                process = subprocess.Popen([sys._base_executable, "-B", "-c", script],
                    cwd=ROOT, env=env, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                try:
                    with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=1) as client:
                        deadline = time.monotonic() + 15
                        while time.monotonic() < deadline:
                            try:
                                response = client.get("/api/health")
                                if response.status_code == 200:
                                    break
                            except httpx.HTTPError:
                                pass
                            time.sleep(.1)
                        else:
                            self.fail("Uvicorn startup failed")
                        self.assertEqual(response.json(), {"status": "ok"})
                        self.assertEqual(client.get("/").status_code, 200)
                finally:
                    process.terminate()
                    process.wait(timeout=10)

if __name__ == "__main__":
    unittest.main(verbosity=2)
