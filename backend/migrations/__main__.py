"""Explicit project-local migration CLI; never called at startup."""
import argparse
import sqlite3
from .manager import MigrationError, status, update
from ..config import Settings

def main():
    parser = argparse.ArgumentParser(description="MGIMOv schema management")
    parser.add_argument("command", choices=("init", "status", "apply"))
    parser.add_argument("--db", help="Project-local SQLite path; defaults to MGIMOV_DB_PATH")
    parser.add_argument("--backup", help="New project-local backup path for apply")
    args = parser.parse_args()
    try:
        settings = Settings(database=args.db) if args.db else Settings.from_environment()
        if args.command == "status":
            result = status(settings.database)
        elif args.command == "init":
            if settings.database.exists():
                raise MigrationError("Database already exists; init never overwrites it.")
            settings.database.parent.mkdir(parents=True, exist_ok=True)
            result = update(settings.database, create=True)
        else:
            backup = Settings(database=args.backup).database if args.backup else None
            result = update(settings.database, backup=backup)
        print("State:", result["state"], "Applied:", ", ".join(result["applied"]), "Pending:", ", ".join(result["pending"]))
        return 0
    except (ValueError, OSError, sqlite3.Error, MigrationError):
        print("Migration failed. Check the project-local path, schema and backup; existing data was not automatically repaired.")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
