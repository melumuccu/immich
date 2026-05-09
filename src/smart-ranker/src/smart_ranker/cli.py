from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from smart_ranker.storage.bootstrap import bootstrap_storage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smart-ranker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap-storage",
        help="SQLite schema and runtime directories initialization",
    )
    bootstrap_parser.add_argument(
        "--state-dir",
        type=Path,
        help="root directory for db, models, snapshots, and logs",
    )
    bootstrap_parser.add_argument(
        "--db-path",
        type=Path,
        help="explicit SQLite database file path",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "bootstrap-storage":
        parser.error(f"unsupported command: {args.command}")

    result = bootstrap_storage(state_dir=args.state_dir, db_path=args.db_path)
    applied = ", ".join(result.migration_result.applied_migrations) or "-"
    skipped = ", ".join(result.migration_result.skipped_migrations) or "-"

    print(f"state_dir={result.paths.state_dir}")
    print(f"db_path={result.paths.db_path}")
    print(f"applied_migrations={applied}")
    print(f"skipped_migrations={skipped}")
    return 0