from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

MIGRATION_TABLE = "schema_migrations"


@dataclass(frozen=True)
class MigrationResult:
    applied_migrations: list[str]
    skipped_migrations: list[str]


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
          version TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _load_applied_versions(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(f"SELECT version FROM {MIGRATION_TABLE}")
    return {row[0] for row in rows.fetchall()}


def _discover_migrations(migrations_dir: Path) -> list[Path]:
    return sorted(migrations_dir.glob("*.sql"))


def apply_migrations(db_path: Path, migrations_dir: Path) -> MigrationResult:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    applied: list[str] = []
    skipped: list[str] = []

    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _ensure_migration_table(connection)
        existing_versions = _load_applied_versions(connection)

        for migration_path in _discover_migrations(migrations_dir):
            version = migration_path.name
            if version in existing_versions:
                skipped.append(version)
                continue

            migration_sql = migration_path.read_text(encoding="utf-8")
            with connection:
                connection.executescript(migration_sql)
                connection.execute(
                    f"INSERT INTO {MIGRATION_TABLE} (version) VALUES (?)",
                    (version,),
                )

            applied.append(version)
            existing_versions.add(version)

    return MigrationResult(applied_migrations=applied, skipped_migrations=skipped)
