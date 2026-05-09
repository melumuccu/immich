from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable
from uuid import uuid4

from smart_ranker.immich_client import AssetReadClient, AssetSnapshot, SearchResult
from smart_ranker.storage.repository import CollectorCursorRecord, FeedbackEventRecord, StorageRepository


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RescueFeedbackInput:
    immich_asset_id: str
    previous_score: float | None = None
    category_id: str | None = None
    source_trace_id: str | None = None
    sample_weight: float = 0.5
    metadata: dict[str, object] | None = None
    note: str | None = None
    occurred_at: str | None = None


@dataclass(frozen=True)
class CollectorRunResult:
    assets: list[AssetSnapshot]
    feedback_count: int
    cursor_before: CollectorCursorRecord | None
    cursor_after: CollectorCursorRecord
    run_id: str


class AssetDiffCollector:
    def __init__(
        self,
        repository: StorageRepository,
        asset_client: AssetReadClient,
        *,
        profile_id: str,
        collector_key: str = "asset-diff",
        now_factory: Callable[[], str] = utc_now_iso,
    ) -> None:
        self.repository = repository
        self.asset_client = asset_client
        self.profile_id = profile_id
        self.collector_key = collector_key
        self.now_factory = now_factory

    def collect(self, rescued_assets: Iterable[RescueFeedbackInput] | None = None) -> CollectorRunResult:
        cursor_before = self.repository.get_collector_cursor(self.profile_id, self.collector_key)
        run_id = str(uuid4())
        run_started_at = self.now_factory()

        search_payload = {"size": 1000, "page": 1}
        if cursor_before and cursor_before.updated_after:
            search_payload["updatedAfter"] = cursor_before.updated_after
        if cursor_before and cursor_before.trashed_after:
            search_payload["trashedAfter"] = cursor_before.trashed_after

        assets = self._collect_all_pages(search_payload)
        feedback_count = self._insert_feedback_events(rescued_assets or [], run_started_at)

        cursor_after = CollectorCursorRecord(
            id=cursor_before.id if cursor_before else str(uuid4()),
            profile_id=self.profile_id,
            collector_key=self.collector_key,
            updated_after=run_started_at,
            trashed_after=run_started_at,
            last_succeeded_at=run_started_at,
            last_attempted_at=run_started_at,
            last_run_id=run_id,
        )
        self.repository.upsert_collector_cursor(cursor_after)

        return CollectorRunResult(
            assets=assets,
            feedback_count=feedback_count,
            cursor_before=cursor_before,
            cursor_after=cursor_after,
            run_id=run_id,
        )

    def _collect_all_pages(self, initial_payload: dict[str, object]) -> list[AssetSnapshot]:
        payload = dict(initial_payload)
        collected: list[AssetSnapshot] = []

        while True:
            response = self.asset_client.search_metadata(payload)
            collected.extend(response.items)
            if not response.has_next_page or not response.next_page:
                return collected
            payload["page"] = int(response.next_page)

    def _insert_feedback_events(self, rescued_assets: Iterable[RescueFeedbackInput], default_occurred_at: str) -> int:
        count = 0
        for rescued_asset in rescued_assets:
            self.repository.insert_feedback_event(
                FeedbackEventRecord(
                    id=str(uuid4()),
                    profile_id=self.profile_id,
                    category_id=rescued_asset.category_id,
                    source_trace_id=rescued_asset.source_trace_id,
                    immich_asset_id=rescued_asset.immich_asset_id,
                    feedback_type="delete_candidate_rescued",
                    previous_score=rescued_asset.previous_score,
                    label_value=1.0,
                    sample_weight=rescued_asset.sample_weight,
                    metadata=rescued_asset.metadata,
                    note=rescued_asset.note,
                    occurred_at=rescued_asset.occurred_at or default_occurred_at,
                )
            )
            count += 1

        return count