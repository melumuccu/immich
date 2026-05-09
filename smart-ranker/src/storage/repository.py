from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


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


@dataclass(frozen=True)
class InferenceTraceRecord:
    id: str
    profile_id: str
    immich_asset_id: str
    trigger_type: str
    execution_mode: str
    candidate_categories: list[str]
    score: dict[str, float]
    final_score: float
    threshold_snapshot: dict[str, Any]
    protected: bool
    occurred_at: str


@dataclass(frozen=True)
class ActionExecutionLogRecord:
    id: str
    profile_id: str
    inference_trace_id: str
    action_policy_id: str
    destination_id: str
    immich_asset_id: str
    action_type: str
    execution_mode: str
    dry_run: bool
    status: str
    request: dict[str, Any]
    response: dict[str, Any]
    error_message: str | None
    executed_at: str


RUNTIME_DATA_TABLES = (
    "action_execution_log",
    "feedback_event",
    "inference_trace",
    "collector_cursor",
)


class StorageRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    @staticmethod
    def _dump_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=True, sort_keys=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _open(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_collector_cursor(self, profile_id: str, collector_key: str) -> CollectorCursorRecord | None:
        with self._open() as connection:
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
        with self._open() as connection:
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
        with self._open() as connection:
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
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO ranker_profile (id, immich_user_id, display_name, timezone, locale, enabled)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (profile_id, immich_user_id, display_name, timezone, locale),
            )

    def ensure_profile(
        self,
        *,
        profile_id: str,
        immich_user_id: str,
        display_name: str = "default",
        timezone: str = "UTC",
        locale: str = "ja-JP",
    ) -> str:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO ranker_profile (id, immich_user_id, display_name, timezone, locale, enabled)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                  immich_user_id = excluded.immich_user_id,
                  display_name = excluded.display_name,
                  timezone = excluded.timezone,
                  locale = excluded.locale,
                  enabled = 1
                """,
                (profile_id, immich_user_id, display_name, timezone, locale),
            )
            row = connection.execute(
                "SELECT id FROM ranker_profile WHERE id = ?",
                (profile_id,),
            ).fetchone()

        assert row is not None
        return str(row["id"])

    def get_profile(self, profile_id: str) -> sqlite3.Row | None:
        with self._open() as connection:
            row = connection.execute(
                "SELECT * FROM ranker_profile WHERE id = ?",
                (profile_id,),
            ).fetchone()
        return row

    def insert_person_group(
        self,
        *,
        group_id: str,
        profile_id: str,
        group_key: str,
        display_name: str,
        group_type: str,
    ) -> None:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO person_group (
                  id, profile_id, group_key, display_name, group_type, aliases_json, enabled
                ) VALUES (?, ?, ?, ?, ?, '[]', 1)
                """,
                (group_id, profile_id, group_key, display_name, group_type),
            )

    def upsert_person_group(
        self,
        *,
        group_id: str,
        profile_id: str,
        group_key: str,
        display_name: str,
        group_type: str,
        aliases: Sequence[str] | None = None,
        enabled: bool = True,
    ) -> str:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO person_group (
                  id, profile_id, group_key, display_name, group_type, aliases_json, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, group_key) DO UPDATE SET
                  display_name = excluded.display_name,
                  group_type = excluded.group_type,
                  aliases_json = excluded.aliases_json,
                  enabled = excluded.enabled
                """,
                (
                    group_id,
                    profile_id,
                    group_key,
                    display_name,
                    group_type,
                    self._dump_json(list(aliases or [])),
                    int(enabled),
                ),
            )
            row = connection.execute(
                "SELECT id FROM person_group WHERE profile_id = ? AND group_key = ?",
                (profile_id, group_key),
            ).fetchone()

        assert row is not None
        return str(row["id"])

    def replace_person_group_members(
        self,
        person_group_id: str,
        members: Sequence[tuple[str, str, str, int, int]],
    ) -> None:
        with self._open() as connection:
            connection.execute(
                "DELETE FROM person_group_member WHERE person_group_id = ?",
                (person_group_id,),
            )
            connection.executemany(
                """
                INSERT INTO person_group_member (
                  id, person_group_id, immich_person_id, immich_person_name, sort_order, enabled
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        member_id,
                        person_group_id,
                        immich_person_id,
                        immich_person_name,
                        sort_order,
                        enabled,
                    )
                    for member_id, immich_person_id, immich_person_name, sort_order, enabled in members
                ],
            )

    def list_person_group_members(self, profile_id: str) -> list[sqlite3.Row]:
        with self._open() as connection:
            rows = connection.execute(
                """
                SELECT pgm.*, pg.group_key
                FROM person_group_member pgm
                JOIN person_group pg ON pg.id = pgm.person_group_id
                WHERE pg.profile_id = ?
                ORDER BY pg.display_name ASC, pgm.sort_order ASC, pgm.immich_person_name ASC
                """,
                (profile_id,),
            ).fetchall()
        return rows

    def insert_category(
        self,
        *,
        category_id: str,
        profile_id: str,
        category_key: str,
        display_name: str,
        category_type: str,
        media_scope: str,
    ) -> None:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO category (
                  id, profile_id, category_key, display_name, category_type, media_scope, aliases_json, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, '[]', 1)
                """,
                (category_id, profile_id, category_key, display_name, category_type, media_scope),
            )

    def upsert_category(
        self,
        *,
        category_id: str,
        profile_id: str,
        category_key: str,
        display_name: str,
        category_type: str,
        media_scope: str,
        aliases: Sequence[str] | None = None,
        enabled: bool = True,
    ) -> str:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO category (
                  id, profile_id, category_key, display_name, category_type, media_scope, aliases_json, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, category_key) DO UPDATE SET
                  display_name = excluded.display_name,
                  category_type = excluded.category_type,
                  media_scope = excluded.media_scope,
                  aliases_json = excluded.aliases_json,
                  enabled = excluded.enabled
                """,
                (
                    category_id,
                    profile_id,
                    category_key,
                    display_name,
                    category_type,
                    media_scope,
                    self._dump_json(list(aliases or [])),
                    int(enabled),
                ),
            )
            row = connection.execute(
                "SELECT id FROM category WHERE profile_id = ? AND category_key = ?",
                (profile_id, category_key),
            ).fetchone()

        assert row is not None
        return str(row["id"])

    def insert_action_policy(
        self,
        *,
        policy_id: str,
        profile_id: str,
        policy_key: str,
        display_name: str,
        execution_mode: str,
    ) -> None:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO action_policy (id, profile_id, policy_key, display_name, execution_mode, display_json, enabled)
                VALUES (?, ?, ?, ?, ?, '{}', 1)
                """,
                (policy_id, profile_id, policy_key, display_name, execution_mode),
            )

    def ensure_action_policy(
        self,
        *,
        policy_id: str,
        profile_id: str,
        policy_key: str,
        display_name: str,
        execution_mode: str,
    ) -> str:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO action_policy (id, profile_id, policy_key, display_name, execution_mode, display_json, enabled)
                VALUES (?, ?, ?, ?, ?, '{}', 1)
                ON CONFLICT(profile_id, policy_key) DO UPDATE SET
                  display_name = excluded.display_name,
                  execution_mode = excluded.execution_mode,
                  enabled = 1
                """,
                (policy_id, profile_id, policy_key, display_name, execution_mode),
            )
            row = connection.execute(
                "SELECT id FROM action_policy WHERE profile_id = ? AND policy_key = ?",
                (profile_id, policy_key),
            ).fetchone()

        assert row is not None
        return str(row["id"])

    def upsert_action_policy(
        self,
        *,
        policy_id: str,
        profile_id: str,
        policy_key: str,
        display_name: str,
        execution_mode: str,
        display: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> str:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO action_policy (
                  id, profile_id, policy_key, display_name, execution_mode, display_json, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, policy_key) DO UPDATE SET
                  display_name = excluded.display_name,
                  execution_mode = excluded.execution_mode,
                  display_json = excluded.display_json,
                  enabled = excluded.enabled
                """,
                (
                    policy_id,
                    profile_id,
                    policy_key,
                    display_name,
                    execution_mode,
                    self._dump_json(display or {}),
                    int(enabled),
                ),
            )
            row = connection.execute(
                "SELECT id FROM action_policy WHERE profile_id = ? AND policy_key = ?",
                (profile_id, policy_key),
            ).fetchone()

        assert row is not None
        return str(row["id"])

    def list_person_groups(self, profile_id: str) -> list[sqlite3.Row]:
        with self._open() as connection:
            rows = connection.execute(
                "SELECT * FROM person_group WHERE profile_id = ? ORDER BY display_name ASC",
                (profile_id,),
            ).fetchall()
        return rows

    def list_categories(self, profile_id: str) -> list[sqlite3.Row]:
        with self._open() as connection:
            rows = connection.execute(
                "SELECT * FROM category WHERE profile_id = ? ORDER BY display_name ASC",
                (profile_id,),
            ).fetchall()
        return rows

    def upsert_routing_rule(
        self,
        *,
        rule_id: str,
        profile_id: str,
        category_id: str,
        rule_name: str,
        priority: int,
        match: dict[str, Any] | None = None,
        assignment_mode: str,
        stop_after_match: bool,
        enabled: bool = True,
    ) -> str:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO routing_rule (
                  id, profile_id, category_id, rule_name, priority, match_json,
                  assignment_mode, stop_after_match, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  profile_id = excluded.profile_id,
                  category_id = excluded.category_id,
                  rule_name = excluded.rule_name,
                  priority = excluded.priority,
                  match_json = excluded.match_json,
                  assignment_mode = excluded.assignment_mode,
                  stop_after_match = excluded.stop_after_match,
                  enabled = excluded.enabled
                """,
                (
                    rule_id,
                    profile_id,
                    category_id,
                    rule_name,
                    priority,
                    self._dump_json(match or {}),
                    assignment_mode,
                    int(stop_after_match),
                    int(enabled),
                ),
            )
        return rule_id

    def list_routing_rules(self, profile_id: str) -> list[sqlite3.Row]:
        with self._open() as connection:
            rows = connection.execute(
                """
                SELECT rr.*, c.category_key
                FROM routing_rule rr
                JOIN category c ON c.id = rr.category_id
                WHERE rr.profile_id = ?
                ORDER BY rr.priority ASC, rr.rule_name ASC
                """,
                (profile_id,),
            ).fetchall()
        return rows

    def list_action_policies(self, profile_id: str) -> list[sqlite3.Row]:
        with self._open() as connection:
            rows = connection.execute(
                "SELECT * FROM action_policy WHERE profile_id = ? ORDER BY display_name ASC",
                (profile_id,),
            ).fetchall()
        return rows

    def insert_action_destination(
        self,
        *,
        destination_id: str,
        profile_id: str,
        destination_key: str,
        destination_type: str,
        immich_resource_id: str,
        config: dict[str, Any] | None = None,
    ) -> None:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO action_destination (
                  id, profile_id, destination_key, destination_type, immich_resource_id, config_json, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    destination_id,
                    profile_id,
                    destination_key,
                    destination_type,
                    immich_resource_id,
                    json.dumps(config or {}, ensure_ascii=True, sort_keys=True),
                ),
            )

    def ensure_action_destination(
        self,
        *,
        destination_id: str,
        profile_id: str,
        destination_key: str,
        destination_type: str,
        immich_resource_id: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO action_destination (
                  id, profile_id, destination_key, destination_type, immich_resource_id, config_json, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(profile_id, destination_key) DO UPDATE SET
                  destination_type = excluded.destination_type,
                  immich_resource_id = excluded.immich_resource_id,
                  config_json = excluded.config_json,
                  enabled = 1
                """,
                (
                    destination_id,
                    profile_id,
                    destination_key,
                    destination_type,
                    immich_resource_id,
                    json.dumps(config or {}, ensure_ascii=True, sort_keys=True),
                ),
            )
            row = connection.execute(
                "SELECT id FROM action_destination WHERE profile_id = ? AND destination_key = ?",
                (profile_id, destination_key),
            ).fetchone()

        assert row is not None
        return str(row["id"])

    def upsert_action_destination(
        self,
        *,
        destination_id: str,
        profile_id: str,
        destination_key: str,
        destination_type: str,
        immich_resource_id: str,
        config: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> str:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO action_destination (
                  id, profile_id, destination_key, destination_type, immich_resource_id, config_json, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, destination_key) DO UPDATE SET
                  destination_type = excluded.destination_type,
                  immich_resource_id = excluded.immich_resource_id,
                  config_json = excluded.config_json,
                  enabled = excluded.enabled
                """,
                (
                    destination_id,
                    profile_id,
                    destination_key,
                    destination_type,
                    immich_resource_id,
                    self._dump_json(config or {}),
                    int(enabled),
                ),
            )
            row = connection.execute(
                "SELECT id FROM action_destination WHERE profile_id = ? AND destination_key = ?",
                (profile_id, destination_key),
            ).fetchone()

        assert row is not None
        return str(row["id"])

    def list_action_destinations(self, profile_id: str) -> list[sqlite3.Row]:
        with self._open() as connection:
            rows = connection.execute(
                "SELECT * FROM action_destination WHERE profile_id = ? ORDER BY destination_key ASC",
                (profile_id,),
            ).fetchall()
        return rows

    def upsert_execution_schedule(
        self,
        *,
        schedule_id: str,
        profile_id: str,
        job_type: str,
        run_mode: str,
        cron_expr: str | None,
        dry_run: bool,
        batch_size: int,
        enabled: bool = True,
    ) -> str:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO execution_schedule (
                  id, profile_id, job_type, run_mode, cron_expr, dry_run, batch_size, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, job_type) DO UPDATE SET
                  run_mode = excluded.run_mode,
                  cron_expr = excluded.cron_expr,
                  dry_run = excluded.dry_run,
                  batch_size = excluded.batch_size,
                  enabled = excluded.enabled
                """,
                (
                    schedule_id,
                    profile_id,
                    job_type,
                    run_mode,
                    cron_expr,
                    int(dry_run),
                    batch_size,
                    int(enabled),
                ),
            )
            row = connection.execute(
                "SELECT id FROM execution_schedule WHERE profile_id = ? AND job_type = ?",
                (profile_id, job_type),
            ).fetchone()

        assert row is not None
        return str(row["id"])

    def list_execution_schedules(self, profile_id: str) -> list[sqlite3.Row]:
        with self._open() as connection:
            rows = connection.execute(
                "SELECT * FROM execution_schedule WHERE profile_id = ? ORDER BY job_type ASC",
                (profile_id,),
            ).fetchall()
        return rows

    def insert_inference_trace(self, record: InferenceTraceRecord) -> None:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO inference_trace (
                  id, profile_id, immich_asset_id, trigger_type, execution_mode,
                  candidate_categories_json, score_json, final_score,
                  threshold_snapshot_json, protected, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.profile_id,
                    record.immich_asset_id,
                    record.trigger_type,
                    record.execution_mode,
                    json.dumps(record.candidate_categories, ensure_ascii=True, sort_keys=True),
                    json.dumps(record.score, ensure_ascii=True, sort_keys=True),
                    record.final_score,
                    json.dumps(record.threshold_snapshot, ensure_ascii=True, sort_keys=True),
                    int(record.protected),
                    record.occurred_at,
                ),
            )

    def list_inference_traces(self, profile_id: str) -> list[sqlite3.Row]:
        with self._open() as connection:
            rows = connection.execute(
                "SELECT * FROM inference_trace WHERE profile_id = ? ORDER BY occurred_at ASC",
                (profile_id,),
            ).fetchall()
        return rows

    def insert_action_execution_log(self, record: ActionExecutionLogRecord) -> None:
        with self._open() as connection:
            connection.execute(
                """
                INSERT INTO action_execution_log (
                  id, profile_id, inference_trace_id, action_policy_id, destination_id,
                  immich_asset_id, action_type, execution_mode, dry_run, status,
                  request_json, response_json, error_message, executed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.profile_id,
                    record.inference_trace_id,
                    record.action_policy_id,
                    record.destination_id,
                    record.immich_asset_id,
                    record.action_type,
                    record.execution_mode,
                    int(record.dry_run),
                    record.status,
                    json.dumps(record.request, ensure_ascii=True, sort_keys=True),
                    json.dumps(record.response, ensure_ascii=True, sort_keys=True),
                    record.error_message,
                    record.executed_at,
                ),
            )

    def list_action_execution_logs(self, profile_id: str) -> list[sqlite3.Row]:
        with self._open() as connection:
            rows = connection.execute(
                "SELECT * FROM action_execution_log WHERE profile_id = ? ORDER BY executed_at ASC",
                (profile_id,),
            ).fetchall()
        return rows

    def list_feedback_events(self, profile_id: str) -> list[sqlite3.Row]:
        with self._open() as connection:
            rows = connection.execute(
                "SELECT * FROM feedback_event WHERE profile_id = ? ORDER BY occurred_at ASC",
                (profile_id,),
            ).fetchall()
        return rows

    def clear_runtime_data(self) -> dict[str, int]:
        deleted_rows: dict[str, int] = {}
        with self._open() as connection:
            for table_name in RUNTIME_DATA_TABLES:
                cursor = connection.execute(f"DELETE FROM {table_name}")
                deleted_rows[table_name] = max(cursor.rowcount, 0)
        return deleted_rows
