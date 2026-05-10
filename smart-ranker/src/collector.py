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
    has_more: bool = False
    batch_size: int | None = None
    next_page: str | None = None


class AssetDiffCollector:
    DEFAULT_SEARCH_PAGE_SIZE = 1000

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

    def collect(
        self,
        rescued_assets: Iterable[RescueFeedbackInput] | None = None,
        max_assets: int | None = None,
    ) -> CollectorRunResult:
        cursor_before = self.repository.get_collector_cursor(self.profile_id, self.collector_key)
        run_id = str(uuid4())
        run_started_at = self.now_factory()

        request_state = self._build_request_state(cursor_before, run_started_at, max_assets)
        assets, next_page = self._collect_pages(
            request_state["payload"],
            max_assets=request_state["max_assets"],
        )
        feedback_count = self._insert_feedback_events(rescued_assets or [], run_started_at)

        cursor_after = self._build_cursor_after(
            cursor_before=cursor_before,
            run_id=run_id,
            run_started_at=run_started_at,
            window_updated_before=str(request_state["window_updated_before"]),
            window_trashed_before=str(request_state["window_trashed_before"]),
            page_size=int(request_state["page_size"]),
            next_page=next_page,
        )
        self.repository.upsert_collector_cursor(cursor_after)

        return CollectorRunResult(
            assets=assets,
            feedback_count=feedback_count,
            cursor_before=cursor_before,
            cursor_after=cursor_after,
            run_id=run_id,
            has_more=next_page is not None,
            batch_size=int(request_state["page_size"]),
            next_page=next_page,
        )

    def _build_request_state(
        self,
        cursor_before: CollectorCursorRecord | None,
        run_started_at: str,
        max_assets: int | None,
    ) -> dict[str, object]:
        is_incremental = bool(cursor_before and cursor_before.updated_after)
        if cursor_before and cursor_before.pending_page:
            page_size = self._normalize_page_size(cursor_before.pending_page_size)
            page = self._normalize_page_value(cursor_before.pending_page)
            window_updated_before = cursor_before.pending_updated_before or run_started_at
            window_trashed_before = cursor_before.pending_trashed_before or window_updated_before
            effective_max_assets = page_size if max_assets is not None else None
        else:
            page_size = self._normalize_page_size(max_assets)
            page = 1
            window_updated_before = run_started_at
            window_trashed_before = run_started_at
            effective_max_assets = page_size if max_assets is not None else None

        payload: dict[str, object] = {
            "size": page_size,
            "page": page,
        }
        if is_incremental:
            payload["updatedBefore"] = window_updated_before
            payload["trashedBefore"] = window_trashed_before
            payload["updatedAfter"] = cursor_before.updated_after
            if cursor_before and cursor_before.trashed_after:
                payload["trashedAfter"] = cursor_before.trashed_after
        else:
            payload["createdBefore"] = window_updated_before

        return {
            "payload": payload,
            "page_size": page_size,
            "max_assets": effective_max_assets,
            "window_updated_before": window_updated_before,
            "window_trashed_before": window_trashed_before,
        }

    def _collect_pages(
        self,
        initial_payload: dict[str, object],
        *,
        max_assets: int | None,
    ) -> tuple[list[AssetSnapshot], str | None]:
        payload = dict(initial_payload)
        collected: list[AssetSnapshot] = []

        while True:
            response = self.asset_client.search_metadata(payload)
            collected.extend(response.items)
            next_page = str(response.next_page) if response.next_page is not None else None
            if not response.has_next_page or not next_page:
                return collected, None
            if max_assets is not None and len(collected) >= max_assets:
                return collected[:max_assets], next_page
            payload["page"] = self._normalize_page_value(next_page)

    def _build_cursor_after(
        self,
        *,
        cursor_before: CollectorCursorRecord | None,
        run_id: str,
        run_started_at: str,
        window_updated_before: str,
        window_trashed_before: str,
        page_size: int,
        next_page: str | None,
    ) -> CollectorCursorRecord:
        if next_page is None:
            return CollectorCursorRecord(
                id=cursor_before.id if cursor_before else str(uuid4()),
                profile_id=self.profile_id,
                collector_key=self.collector_key,
                updated_after=window_updated_before,
                trashed_after=window_trashed_before,
                last_succeeded_at=run_started_at,
                last_attempted_at=run_started_at,
                last_run_id=run_id,
            )

        return CollectorCursorRecord(
            id=cursor_before.id if cursor_before else str(uuid4()),
            profile_id=self.profile_id,
            collector_key=self.collector_key,
            updated_after=cursor_before.updated_after if cursor_before else None,
            trashed_after=cursor_before.trashed_after if cursor_before else None,
            last_succeeded_at=run_started_at,
            last_attempted_at=run_started_at,
            last_run_id=run_id,
            pending_page=next_page,
            pending_page_size=page_size,
            pending_updated_before=window_updated_before,
            pending_trashed_before=window_trashed_before,
        )

    def _normalize_page_size(self, page_size: int | None) -> int:
        if page_size is None:
            return self.DEFAULT_SEARCH_PAGE_SIZE
        return max(1, min(int(page_size), self.DEFAULT_SEARCH_PAGE_SIZE))

    @staticmethod
    def _normalize_page_value(page: str | int) -> str | int:
        page_text = str(page)
        return int(page_text) if page_text.isdigit() else page_text

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
