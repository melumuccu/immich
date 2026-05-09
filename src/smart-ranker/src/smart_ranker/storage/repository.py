from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CollectorCursorRecord:
    id: str
    profile_id: str
    collector_key: str
    updated_after: str | None
    trashed_after: str | None
    last_succeeded_at: str | None
    last_attempted_at: str | None
    last_run_id: str | None


@dataclass(frozen=True)
class FeedbackEventRecord:
    id: str
    profile_id: str
    immich_asset_id: str
    feedback_type: str
    label_value: float
    sample_weight: float
    occurred_at: str
    category_id: str | None = None
    source_trace_id: str | None = None
    previous_score: float | None = None
    metadata: dict[str, Any] | None = None
    note: str | None = None


class StorageRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def get_collector_cursor(self, profile_id: str, collector_key: str) -> CollectorCursorRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, profile_id, collector_key, updated_after, trashed_after,
                       last_succeeded_at, last_attempted_at, last_run_id
                FROM collector_cursor
                WHERE profile_id = ? AND collector_key = ?
                """,
                (profile_id, collector_key),
            ).fetchone()

        if row is None:
            return None

        return CollectorCursorRecord(
            id=row["id"],
            profile_id=row["profile_id"],
            collector_key=row["collector_key"],
            updated_after=row["updated_after"],
            trashed_after=row["trashed_after"],
            last_succeeded_at=row["last_succeeded_at"],
            last_attempted_at=row["last_attempted_at"],
            last_run_id=row["last_run_id"],
        )

    def upsert_collector_cursor(self, record: CollectorCursorRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO collector_cursor (
                  id, profile_id, collector_key, updated_after, trashed_after,
                  last_succeeded_at, last_attempted_at, last_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, collector_key) DO UPDATE SET
                  updated_after = excluded.updated_after,
                  trashed_after = excluded.trashed_after,
                  last_succeeded_at = excluded.last_succeeded_at,
                  last_attempted_at = excluded.last_attempted_at,
                  last_run_id = excluded.last_run_id
                """,
                (
                    record.id,
                    record.profile_id,
                    record.collector_key,
                    record.updated_after,
                    record.trashed_after,
                    record.last_succeeded_at,
                    record.last_attempted_at,
                    record.last_run_id,
                ),
            )

    def insert_feedback_event(self, record: FeedbackEventRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO feedback_event (
                  id, profile_id, category_id, source_trace_id, immich_asset_id, feedback_type,
                  previous_score, label_value, sample_weight, metadata_json, note, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.profile_id,
                    record.category_id,
                    record.source_trace_id,
                    record.immich_asset_id,
                    record.feedback_type,
                    record.previous_score,
                    record.label_value,
                    record.sample_weight,
                    json.dumps(record.metadata or {}, ensure_ascii=True, sort_keys=True),
                    record.note,
                    record.occurred_at,
                ),
            )

    def insert_profile(
        self,
        *,
        profile_id: str,
        immich_user_id: str,
        display_name: str = "default",
        timezone: str = "UTC",
        locale: str = "ja-JP",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ranker_profile (id, immich_user_id, display_name, timezone, locale, enabled)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (profile_id, immich_user_id, display_name, timezone, locale),
            )

    def list_feedback_events(self, profile_id: str) -> list[sqlite3.Row]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM feedback_event WHERE profile_id = ? ORDER BY occurred_at ASC",
                (profile_id,),
            ).fetchall()
        return rows