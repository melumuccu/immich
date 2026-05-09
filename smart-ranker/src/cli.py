from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from smart_ranker.master_data import resolve_seed_inputs, seed_master_data
from smart_ranker.storage.bootstrap import bootstrap_storage
from smart_ranker.storage.repository import StorageRepository


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

    seed_parser = subparsers.add_parser(
        "seed-master-data",
        help="seed profile, person groups, categories, routing, policies, and schedules",
    )
    seed_parser.add_argument(
        "--state-dir",
        type=Path,
        help="root directory for db, models, snapshots, and logs",
    )
    seed_parser.add_argument(
        "--db-path",
        type=Path,
        help="explicit SQLite database file path",
    )
    seed_parser.add_argument(
        "--profile-id",
        default="default-profile",
        help="profile identifier to seed",
    )
    seed_parser.add_argument(
        "--immich-user-id",
        help="Immich user id. Falls back to SMART_RANKER_IMMICH_USER_ID",
    )
    seed_parser.add_argument(
        "--review-album-id",
        help="Immich album id for review destination. Falls back to SMART_RANKER_REVIEW_ALBUM_ID",
    )
    seed_parser.add_argument(
        "--review-threshold",
        type=float,
        help="Review threshold. Falls back to SMART_RANKER_REVIEW_THRESHOLD or default",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "bootstrap-storage":
        result = bootstrap_storage(state_dir=args.state_dir, db_path=args.db_path)
        applied = ", ".join(result.migration_result.applied_migrations) or "-"
        skipped = ", ".join(result.migration_result.skipped_migrations) or "-"

        print(f"state_dir={result.paths.state_dir}")
        print(f"db_path={result.paths.db_path}")
        print(f"applied_migrations={applied}")
        print(f"skipped_migrations={skipped}")
        return 0

    if args.command == "seed-master-data":
        result = bootstrap_storage(state_dir=args.state_dir, db_path=args.db_path)
        repository = StorageRepository(result.paths.db_path)
        immich_user_id, review_album_resource_id, review_threshold = resolve_seed_inputs(
            immich_user_id=args.immich_user_id,
            review_album_resource_id=args.review_album_id,
            review_threshold=args.review_threshold,
        )
        seeded = seed_master_data(
            repository,
            profile_id=args.profile_id,
            immich_user_id=immich_user_id,
            review_album_resource_id=review_album_resource_id,
            review_threshold=review_threshold,
        )
        print(f"profile_id={args.profile_id}")
        print(f"db_path={result.paths.db_path}")
        print(f"person_groups={len(seeded['personGroups'])}")
        print(f"categories={len(seeded['categories'])}")
        print(f"routing_rules={len(seeded['routingRules'])}")
        print(f"policies={len(seeded['policies'])}")
        print(f"destinations={len(seeded['destinations'])}")
        print(f"schedules={len(seeded['schedules'])}")
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2
