from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from smart_ranker.master_data import resolve_seed_inputs, seed_master_data
from smart_ranker.storage.bootstrap import bootstrap_storage
from smart_ranker.storage.paths import StoragePaths
from smart_ranker.storage.repository import StorageRepository


def _clear_runtime_artifacts(paths: StoragePaths) -> dict[str, int]:
    cleared_entries = {"models": 0, "snapshots": 0}
    for key, directory in (("models", paths.models_dir), ("snapshots", paths.snapshots_dir)):
        if not directory.exists():
            continue
        for child in directory.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            cleared_entries[key] += 1
    return cleared_entries


def _mark_runtime_reset(paths: StoragePaths) -> str:
    token = str(uuid4())
    paths.runtime_reset_token_path().write_text(token, encoding="utf-8")
    return token


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

    reset_parser = subparsers.add_parser(
        "reset-runtime-data",
        help="clear runtime DB rows and training artifacts while preserving settings tables",
    )
    reset_parser.add_argument(
        "--state-dir",
        type=Path,
        help="root directory for db, models, snapshots, and logs",
    )
    reset_parser.add_argument(
        "--db-path",
        type=Path,
        help="explicit SQLite database file path",
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

    if args.command == "reset-runtime-data":
        result = bootstrap_storage(state_dir=args.state_dir, db_path=args.db_path)
        repository = StorageRepository(result.paths.db_path)
        deleted_rows = repository.clear_runtime_data()
        cleared_entries = _clear_runtime_artifacts(result.paths)
        reset_token = _mark_runtime_reset(result.paths)

        print(f"db_path={result.paths.db_path}")
        print(f"deleted_collector_cursor={deleted_rows['collector_cursor']}")
        print(f"deleted_feedback_event={deleted_rows['feedback_event']}")
        print(f"deleted_inference_trace={deleted_rows['inference_trace']}")
        print(f"deleted_action_execution_log={deleted_rows['action_execution_log']}")
        print(f"deleted_favorite_signal={deleted_rows['favorite_signal']}")
        print(f"deleted_trash_signal={deleted_rows['trash_signal']}")
        print(f"deleted_apply_exclusion_asset={deleted_rows['apply_exclusion_asset']}")
        print(f"deleted_score_result={deleted_rows['score_result']}")
        print(f"deleted_score_run={deleted_rows['score_run']}")
        print(f"cleared_models={cleared_entries['models']}")
        print(f"cleared_snapshots={cleared_entries['snapshots']}")
        print(f"runtime_reset_token={reset_token}")
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2
