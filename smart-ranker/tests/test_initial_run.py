from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from smart_ranker.immich_client import ActionResult, AssetSnapshot, SearchResult
from smart_ranker.storage import bootstrap_storage
from smart_ranker.storage.repository import StorageRepository
from smart_ranker.web.job_service import build_job_service


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


class FakeEmbeddingReader:
    def __init__(self, embeddings_by_asset_id: dict[str, list[float]]) -> None:
        self.embeddings_by_asset_id = embeddings_by_asset_id
        self.calls: list[list[str]] = []

    def fetch_embeddings(self, asset_ids) -> dict[str, list[float]]:
        requested_ids = list(asset_ids)
        self.calls.append(requested_ids)
        return {
            asset_id: list(self.embeddings_by_asset_id[asset_id])
            for asset_id in requested_ids
            if asset_id in self.embeddings_by_asset_id
        }


class FakeActionClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object]] = []

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> ActionResult:
        self.calls.append(("add_assets_to_album", album_id, list(asset_ids)))
        return ActionResult(status_code=200, ok=True, payload={"albumId": album_id, "ids": list(asset_ids)})

    def trash_assets(self, asset_ids: list[str], *, force: bool = False) -> ActionResult:
        self.calls.append(("trash_assets", list(asset_ids), {"force": force}))
        return ActionResult(status_code=200, ok=True, payload={"ids": list(asset_ids), "force": force})


def make_asset(
    *,
    asset_id: str,
    favorite: bool = False,
    trashed: bool = False,
    visibility: str = "timeline",
    people: tuple[str, ...] = (),
) -> AssetSnapshot:
    return AssetSnapshot(
        id=asset_id,
        is_favorite=favorite,
        is_trashed=trashed,
        visibility=visibility,
        people=people,
        original_file_name=f"{asset_id}.jpg",
        original_path=f"/library/{asset_id}.jpg",
        updated_at="2026-05-09T00:00:00Z",
        payload={"id": asset_id},
    )


class InitialRunTest(unittest.TestCase):
    def test_initial_run_conditions_pass_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bootstrap_result = bootstrap_storage(state_dir=Path(temp_dir) / "state")
            repository = StorageRepository(bootstrap_result.paths.db_path)
            asset_client = FakeAssetClient(
                [
                    SearchResult(
                        items=[make_asset(asset_id="child-positive", favorite=True, people=("kid-1",))],
                        next_page=None,
                        has_next_page=False,
                        raw={},
                    ),
                    SearchResult(
                        items=[make_asset(asset_id="child-negative", trashed=True, people=("kid-1",))],
                        next_page=None,
                        has_next_page=False,
                        raw={},
                    ),
                    SearchResult(
                        items=[
                            make_asset(asset_id="child-positive", favorite=True, people=("kid-1",)),
                            make_asset(asset_id="child-negative", trashed=True, people=("kid-1",)),
                            make_asset(asset_id="neutral-low"),
                        ],
                        next_page=None,
                        has_next_page=False,
                        raw={},
                    ),
                ]
            )

            action_client = FakeActionClient()
            job_service = build_job_service(
                storage_paths=bootstrap_result.paths,
                repository=repository,
                profile_id="profile-1",
                immich_user_id="immich-user-1",
                asset_client=asset_client,
                embedding_reader=FakeEmbeddingReader(
                    {
                        "child-positive": [2.0, 1.5],
                        "child-negative": [-2.0, -1.5],
                        "neutral-low": [-1.8, -1.4],
                    }
                ),
                action_client=action_client,
                review_album_resource_id="album-1",
                review_threshold=0.5,
                now_factory=lambda: "2026-05-09T12:00:00Z",
            )

            learn_run = job_service.submit("learn", {"trigger": "test"})
            score_run = job_service.submit("score", {"trigger": "test"})
            apply_run = job_service.submit("apply", {"trigger": "test"})

            self.assertEqual("completed", learn_run.status)
            self.assertEqual(1, learn_run.result["favoriteSignalCount"])
            self.assertEqual(1, learn_run.result["trashSignalCount"])
            self.assertEqual(2, learn_run.result["trainingAssetCount"])

            self.assertEqual("completed", score_run.status)
            self.assertEqual(3, score_run.result["scoredAssetCount"])
            self.assertIn("scoreRunId", score_run.result)

            self.assertEqual("completed", apply_run.status)
            self.assertEqual(1, apply_run.result["appliedCount"])
            self.assertEqual(["neutral-low"], apply_run.result["assetIds"])

            latest_score_run = repository.get_latest_completed_score_run("profile-1")
            self.assertIsNotNone(latest_score_run)
            self.assertEqual(1, len(repository.list_score_runs("profile-1")))
            self.assertEqual(3, len(repository.list_score_results("profile-1", score_run_id=str(latest_score_run["id"]))))
            self.assertEqual(1, len(repository.list_apply_exclusion_assets("profile-1")))
            self.assertEqual(1, len(repository.list_action_execution_logs("profile-1")))
            self.assertEqual(1, len(action_client.calls))
            self.assertEqual("add_assets_to_album", action_client.calls[0][0])
            self.assertEqual("album-1", action_client.calls[0][1])

            self.assertEqual(
                {"isFavorite": True, "size": 1000, "page": 1},
                asset_client.calls[0],
            )
            self.assertEqual(
                {"withDeleted": True, "trashedAfter": "1970-01-01T00:00:00Z", "size": 1000, "page": 1},
                asset_client.calls[1],
            )
            self.assertEqual(
                {"size": 1000, "page": 1},
                asset_client.calls[2],
            )

    def test_review_album_candidate_can_be_learned_after_manual_trash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bootstrap_result = bootstrap_storage(state_dir=Path(temp_dir) / "state")
            repository = StorageRepository(bootstrap_result.paths.db_path)
            asset_client = FakeAssetClient(
                [
                    SearchResult(
                        items=[make_asset(asset_id="child-positive", favorite=True, people=("kid-1",))],
                        next_page=None,
                        has_next_page=False,
                        raw={},
                    ),
                    SearchResult(
                        items=[make_asset(asset_id="child-negative", trashed=True, people=("kid-1",))],
                        next_page=None,
                        has_next_page=False,
                        raw={},
                    ),
                    SearchResult(
                        items=[
                            make_asset(asset_id="child-positive", favorite=True, people=("kid-1",)),
                            make_asset(asset_id="child-negative", trashed=True, people=("kid-1",)),
                            make_asset(asset_id="neutral-low"),
                        ],
                        next_page=None,
                        has_next_page=False,
                        raw={},
                    ),
                    SearchResult(
                        items=[make_asset(asset_id="child-positive", favorite=True, people=("kid-1",))],
                        next_page=None,
                        has_next_page=False,
                        raw={},
                    ),
                    SearchResult(
                        items=[
                            make_asset(asset_id="child-negative", trashed=True, people=("kid-1",)),
                            make_asset(asset_id="neutral-low", trashed=True),
                        ],
                        next_page=None,
                        has_next_page=False,
                        raw={},
                    ),
                ]
            )

            job_service = build_job_service(
                storage_paths=bootstrap_result.paths,
                repository=repository,
                profile_id="profile-1",
                immich_user_id="immich-user-1",
                asset_client=asset_client,
                embedding_reader=FakeEmbeddingReader(
                    {
                        "child-positive": [2.0, 1.5],
                        "child-negative": [-2.0, -1.5],
                        "neutral-low": [-1.8, -1.4],
                    }
                ),
                action_client=FakeActionClient(),
                review_album_resource_id="album-1",
                review_threshold=0.5,
                now_factory=lambda: "2026-05-09T12:00:00Z",
            )

            self.assertEqual("completed", job_service.submit("learn", {"trigger": "test"}).status)
            self.assertEqual("completed", job_service.submit("score", {"trigger": "test"}).status)
            self.assertEqual("completed", job_service.submit("apply", {"trigger": "test"}).status)

            learn_after_manual_trash = job_service.submit("learn", {"trigger": "manual-trash"})

            self.assertEqual("completed", learn_after_manual_trash.status)
            self.assertEqual(1, learn_after_manual_trash.result["favoriteSignalCount"])
            self.assertEqual(2, learn_after_manual_trash.result["trashSignalCount"])
            self.assertEqual(3, learn_after_manual_trash.result["trainingAssetCount"])
            self.assertEqual(2, len(repository.list_trash_signals("profile-1")))



if __name__ == "__main__":
    unittest.main()
