from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from smart_ranker.collector import AssetDiffCollector, RescueFeedbackInput
from smart_ranker.immich_client.dto import AssetSnapshot, SearchResult
from smart_ranker.storage import bootstrap_storage
from smart_ranker.storage.repository import CollectorCursorRecord, StorageRepository


class FakeAssetClient:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def search_metadata(self, payload: dict[str, object]) -> SearchResult:
        self.calls.append(dict(payload))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_asset(asset_id: str) -> AssetSnapshot:
    return AssetSnapshot(
        id=asset_id,
        is_favorite=False,
        is_trashed=False,
        visibility="timeline",
        people=(),
        original_file_name=f"{asset_id}.jpg",
        original_path=f"/library/{asset_id}.jpg",
        updated_at="2026-05-09T00:00:00Z",
        payload={"id": asset_id},
    )


class CollectorTest(unittest.TestCase):
    def test_collect_supports_batched_continuation_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            bootstrap_result = bootstrap_storage(state_dir=state_dir)
            repository = StorageRepository(bootstrap_result.paths.db_path)
            repository.insert_profile(profile_id="profile-1", immich_user_id="immich-user-1")

            asset_client = FakeAssetClient(
                [
                    SearchResult(items=[make_asset("asset-1")], next_page="2", has_next_page=True, raw={}),
                    SearchResult(items=[make_asset("asset-2")], next_page=None, has_next_page=False, raw={}),
                ]
            )
            timestamps = iter(["2026-05-09T12:00:00Z", "2026-05-09T12:05:00Z"])
            collector = AssetDiffCollector(
                repository,
                asset_client,
                profile_id="profile-1",
                now_factory=lambda: next(timestamps),
            )

            first_result = collector.collect(max_assets=1)

            self.assertEqual(["asset-1"], [asset.id for asset in first_result.assets])
            self.assertTrue(first_result.has_more)
            self.assertEqual(
                [
                    {
                        "size": 1,
                        "page": 1,
                        "createdBefore": "2026-05-09T12:00:00Z",
                    }
                ],
                asset_client.calls,
            )

            first_cursor = repository.get_collector_cursor("profile-1", "asset-diff")
            assert first_cursor is not None
            self.assertIsNone(first_cursor.updated_after)
            self.assertEqual("2", first_cursor.pending_page)
            self.assertEqual(1, first_cursor.pending_page_size)
            self.assertEqual("2026-05-09T12:00:00Z", first_cursor.pending_updated_before)
            self.assertEqual("2026-05-09T12:00:00Z", first_cursor.pending_trashed_before)

            second_result = collector.collect(max_assets=1)

            self.assertEqual(["asset-2"], [asset.id for asset in second_result.assets])
            self.assertFalse(second_result.has_more)
            self.assertEqual(
                {
                    "size": 1,
                    "page": 2,
                    "createdBefore": "2026-05-09T12:00:00Z",
                },
                asset_client.calls[1],
            )

            second_cursor = repository.get_collector_cursor("profile-1", "asset-diff")
            assert second_cursor is not None
            self.assertEqual("2026-05-09T12:00:00Z", second_cursor.updated_after)
            self.assertEqual("2026-05-09T12:00:00Z", second_cursor.trashed_after)
            self.assertIsNone(second_cursor.pending_page)

    def test_collect_updates_cursor_and_writes_feedback_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            bootstrap_result = bootstrap_storage(state_dir=state_dir)
            repository = StorageRepository(bootstrap_result.paths.db_path)
            repository.insert_profile(profile_id="profile-1", immich_user_id="immich-user-1")

            asset_client = FakeAssetClient(
                [
                    SearchResult(items=[make_asset("asset-1")], next_page=None, has_next_page=False, raw={}),
                ]
            )
            collector = AssetDiffCollector(
                repository,
                asset_client,
                profile_id="profile-1",
                now_factory=lambda: "2026-05-09T12:00:00Z",
            )

            result = collector.collect(
                rescued_assets=[
                    RescueFeedbackInput(
                        immich_asset_id="asset-1",
                        previous_score=0.12,
                        metadata={"smart_categories": ["landscape"]},
                        note="manual rescue",
                    )
                ]
            )

            self.assertEqual(1, len(result.assets))
            self.assertEqual(1, result.feedback_count)
            self.assertEqual(
                [
                    {
                        "size": 1000,
                        "page": 1,
                        "createdBefore": "2026-05-09T12:00:00Z",
                    }
                ],
                asset_client.calls,
            )

            cursor = repository.get_collector_cursor("profile-1", "asset-diff")
            assert cursor is not None
            self.assertEqual("2026-05-09T12:00:00Z", cursor.updated_after)
            self.assertEqual("2026-05-09T12:00:00Z", cursor.trashed_after)

            events = repository.list_feedback_events("profile-1")
            self.assertEqual(1, len(events))
            self.assertEqual("delete_candidate_rescued", events[0]["feedback_type"])
            self.assertEqual("asset-1", events[0]["immich_asset_id"])
            self.assertEqual(
                {"smart_categories": ["landscape"]},
                json.loads(events[0]["metadata_json"]),
            )

    def test_collect_keeps_cursor_unchanged_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            bootstrap_result = bootstrap_storage(state_dir=state_dir)
            repository = StorageRepository(bootstrap_result.paths.db_path)
            repository.insert_profile(profile_id="profile-1", immich_user_id="immich-user-1")
            repository.upsert_collector_cursor(
                CollectorCursorRecord(
                    id="cursor-1",
                    profile_id="profile-1",
                    collector_key="asset-diff",
                    updated_after="2026-05-08T00:00:00Z",
                    trashed_after="2026-05-08T00:00:00Z",
                    last_succeeded_at="2026-05-08T00:00:00Z",
                    last_attempted_at="2026-05-08T00:00:00Z",
                    last_run_id="run-0",
                )
            )

            asset_client = FakeAssetClient([RuntimeError("boom")])
            collector = AssetDiffCollector(
                repository,
                asset_client,
                profile_id="profile-1",
                now_factory=lambda: "2026-05-09T12:00:00Z",
            )

            with self.assertRaisesRegex(RuntimeError, "boom"):
                collector.collect()

            cursor = repository.get_collector_cursor("profile-1", "asset-diff")
            assert cursor is not None
            self.assertEqual("2026-05-08T00:00:00Z", cursor.updated_after)
            self.assertEqual("2026-05-08T00:00:00Z", cursor.trashed_after)
            self.assertEqual(
                [{
                    "size": 1000,
                    "page": 1,
                    "updatedAfter": "2026-05-08T00:00:00Z",
                    "trashedAfter": "2026-05-08T00:00:00Z",
                    "updatedBefore": "2026-05-09T12:00:00Z",
                    "trashedBefore": "2026-05-09T12:00:00Z",
                }],
                asset_client.calls,
            )


if __name__ == "__main__":
    unittest.main()
