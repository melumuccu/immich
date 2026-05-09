from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from smart_ranker.storage.migrations import MigrationResult, apply_migrations
from smart_ranker.storage.paths import StoragePaths


@dataclass(frozen=True)
class BootstrapResult:
    paths: StoragePaths
    migration_result: MigrationResult


def ensure_runtime_directories(paths: StoragePaths) -> None:
    for directory in paths.runtime_directories():
        directory.mkdir(parents=True, exist_ok=True)


def bootstrap_storage(
    state_dir: Path | str | None = None,
    db_path: Path | str | None = None,
) -> BootstrapResult:
    paths = StoragePaths.from_root(state_dir=state_dir, db_path=db_path)
    ensure_runtime_directories(paths)
    migration_result = apply_migrations(paths.db_path, paths.migrations_dir)
    return BootstrapResult(paths=paths, migration_result=migration_result)
