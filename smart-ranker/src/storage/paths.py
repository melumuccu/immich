from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

STATE_DIR_ENV = "SMART_RANKER_STATE_DIR"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_state_root(explicit_state_dir: Path | str | None = None) -> Path:
    if explicit_state_dir is not None:
        return Path(explicit_state_dir).expanduser().resolve()

    state_dir = os.getenv(STATE_DIR_ENV)
    if state_dir:
        return Path(state_dir).expanduser().resolve()

    return project_root() / "var"


@dataclass(frozen=True)
class StoragePaths:
    state_dir: Path
    db_dir: Path
    db_path: Path
    models_dir: Path
    snapshots_dir: Path
    logs_dir: Path
    migrations_dir: Path

    @classmethod
    def from_root(
        cls,
        state_dir: Path | str | None = None,
        db_path: Path | str | None = None,
    ) -> "StoragePaths":
        resolved_state_dir = resolve_state_root(state_dir)
        resolved_db_path = (
            Path(db_path).expanduser().resolve()
            if db_path is not None
            else resolved_state_dir / "db" / "smart-ranker.sqlite3"
        )

        return cls(
            state_dir=resolved_state_dir,
            db_dir=resolved_db_path.parent,
            db_path=resolved_db_path,
            models_dir=resolved_state_dir / "models",
            snapshots_dir=resolved_state_dir / "snapshots",
            logs_dir=resolved_state_dir / "logs",
            migrations_dir=Path(__file__).resolve().parent / "sql",
        )

    def runtime_directories(self) -> tuple[Path, ...]:
        return (self.db_dir, self.models_dir, self.snapshots_dir, self.logs_dir)
