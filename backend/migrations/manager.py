"""Small transactional migration runner. No API startup hooks or default DB path."""

import hashlib
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


DIRECTORY = Path(__file__).resolve().parent
HISTORY_SQL = """CREATE TABLE schema_migrations (
    id TEXT PRIMARY KEY NOT NULL,
    applied_at TEXT NOT NULL,
    checksum TEXT NOT NULL
)"""


class MigrationError(Exception):
    """A safe diagnostic without payloads or SQL error values."""


def open_database(database, *, readonly=True, timeout=5):
    path = Path(database).resolve(strict=True)
    if not path.is_file():
        raise MigrationError("Путь базы должен указывать на существующий файл.")
    connection = sqlite3.connect(path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
                                 uri=True, isolation_level=None, timeout=timeout)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def definitions(directory=DIRECTORY):
    files = sorted(Path(directory).glob("*.sql"))
    result = []
    for number, path in enumerate(files, 1):
        if not re.fullmatch(rf"{number:04d}_[a-z0-9_]+\.sql", path.name):
            raise MigrationError("Имена миграций должны иметь непрерывные номера от 0001.")
        raw = path.read_bytes()
        result.append((path.stem, hashlib.sha256(raw).hexdigest(), raw.decode("utf-8")))
    if not result or result[0][0] != "0001_initial":
        raise MigrationError("Не найдена исходная миграция 0001_initial.")
    return result


def execute_sql(connection, sql):
    # execute(), unlike executescript(), does not commit our explicit transaction.
    # Authorizer also prevents a future SQL file from committing, attaching a DB,
    # changing journal settings, or modifying migration metadata itself.
    def authorize(action, first, second, database, trigger):
        denied = {sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT,
                  sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA}
        if action in denied or ("schema_migrations" in (first, second) and action in {
                sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
                sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE}):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection.set_authorizer(authorize)
    try:
        statement = ""
        for character in sql:
            statement += character
            if character == ";" and sqlite3.complete_statement(statement):
                connection.execute(statement)
                statement = ""
        # Permit trailing comments, but reject unterminated statements.
        remainder = re.sub(r"/\*.*?\*/|--[^\n]*", "", statement, flags=re.S).strip()
        if remainder:
            raise MigrationError("Каждая SQL-команда должна завершаться точкой с запятой.")
    finally:
        connection.set_authorizer(None)


def schema(connection, *, history=False):
    rows = connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_master "
                              "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
    result = []
    for kind, name, table, sql in rows:
        if (table == "schema_migrations") != history:
            continue
        # Preserve quoted values, ignore formatting/case of unquoted SQL tokens.
        tokens = re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|\w+|[^\s]", sql or "")
        normalized = tuple(t if t.startswith(("'", '"')) else t.lower() for t in tokens)
        result.append((kind, name, table, normalized))
    return result


def inspect(connection, migrations):
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise MigrationError("Проверка целостности SQLite не пройдена.")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise MigrationError("Проверка внешних ключей SQLite не пройдена.")
    has_history = bool(connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone())
    applied = []
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as expected:
        expected.execute(HISTORY_SQL)
        if has_history:
            if schema(connection, history=True) != schema(expected, history=True):
                raise MigrationError("Неожиданная структура истории миграций.")
            rows = connection.execute(
                "SELECT id, applied_at, checksum FROM schema_migrations ORDER BY id").fetchall()
            if not rows:
                raise MigrationError("История пуста: требуется исследование состояния базы.")
            for position, (identifier, applied_at, checksum) in enumerate(rows):
                if position >= len(migrations) or identifier != migrations[position][0]:
                    raise MigrationError("В истории неизвестная или пропущенная миграция.")
                if checksum != migrations[position][1]:
                    raise MigrationError("Контрольная сумма применённой миграции не совпадает: " + identifier)
                try:
                    timestamp = datetime.fromisoformat(applied_at)
                    if timestamp.tzinfo is None:
                        raise ValueError
                except (ValueError, TypeError):
                    raise MigrationError("Некорректное время в истории миграций.") from None
                execute_sql(expected, migrations[position][2])
                applied.append(identifier)
            kind = "managed"
        elif schema(connection):
            execute_sql(expected, migrations[0][2])
            kind = "legacy"
        else:
            kind = "empty"
        if schema(connection) != schema(expected):
            raise MigrationError("Схема отличается от ожидаемой. Автоматическое исправление запрещено.")
    return {"state": kind, "applied": applied,
            "pending": [item[0] for item in migrations[len(applied):]],
            "baseline_required": kind == "legacy"}


def status(database, directory=DIRECTORY):
    with closing(open_database(database)) as connection:
        connection.execute("BEGIN")
        return inspect(connection, definitions(directory))


def verified_backup(database, destination):
    """Online backup to a NEW file, then verify integrity and logical contents."""
    source = Path(database).resolve(strict=True)
    target = Path(destination).resolve()
    if target == source:
        raise MigrationError("Резервная копия должна быть отдельным новым файлом.")
    # Exclusive creation prevents overwriting an existing backup or database.
    with target.open("xb"):
        pass
    with closing(open_database(source)) as original, closing(open_database(target, readonly=False)) as copy:
        original.execute("BEGIN")
        original.backup(copy)
        if copy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise MigrationError("Резервная копия не прошла проверку целостности.")
        if list(original.iterdump()) != list(copy.iterdump()):
            raise MigrationError("Данные резервной копии не совпадают с источником.")
    return target


def update(database, *, backup=None, baseline=False, create=False,
           directory=DIRECTORY, timeout=5):
    migrations = definitions(directory)
    database = Path(database).resolve()
    if create:
        if baseline:
            raise MigrationError("Нельзя совмещать init и baseline.")
        with database.open("xb"):
            pass
    try:
        with closing(open_database(database, readonly=False, timeout=timeout)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                before = inspect(connection, migrations)
                if baseline and before["state"] == "empty":
                    raise MigrationError("Baseline предназначен для существующей legacy-схемы; используйте init/apply.")
                if before["baseline_required"] and not baseline:
                    raise MigrationError("Legacy-база: сначала выполните явный baseline с резервной копией.")
                if before["state"] == "managed" and (baseline or not before["pending"]):
                    connection.rollback()
                    return before
                if not create:
                    if backup is None:
                        raise MigrationError("Перед изменением существующей базы требуется новый путь --backup.")
                    verified_backup(database, backup)
                if before["state"] != "managed":
                    connection.execute(HISTORY_SQL)
                pending = migrations[len(before["applied"]):]
                if baseline:
                    pending = pending[:1]
                for identifier, checksum, sql in pending:
                    if not baseline:
                        execute_sql(connection, sql)
                    connection.execute("INSERT INTO schema_migrations VALUES (?, ?, ?)",
                                       (identifier, datetime.now(timezone.utc).isoformat(), checksum))
                after = inspect(connection, migrations)
                connection.commit()
                return after
            except BaseException:
                connection.rollback()
                raise
    except sqlite3.Error as error:
        if "locked" in str(error).lower() or "busy" in str(error).lower():
            raise MigrationError("База занята другим процессом. Повторите операцию позже.") from None
        raise MigrationError("Ошибка SQL; изменения схемы и истории отменены.") from None
