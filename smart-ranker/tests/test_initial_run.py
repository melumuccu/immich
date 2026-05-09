from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from smart_ranker.collector import AssetDiffCollector
from smart_ranker.feature_pipeline import (
    AssetFeatureInputBuilder,
    FeatureAssembler,
    LabelResolver,
    LabelResolverConfig,
    PersonLabelConfig,
)
from smart_ranker.immich_client import ActionResult, AssetSnapshot, SearchResult
from smart_ranker.inference import ActionExecutor, ApplyConfig, InferenceJob
from smart_ranker.storage import bootstrap_storage
from smart_ranker.storage.repository import StorageRepository
from smart_ranker.training import TrainingJob


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
        self.calls: list[tuple[str, str, dict[str, object] | list[str]]] = []

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> ActionResult:
        self.calls.append(("add_assets_to_album", album_id, asset_ids))
        return ActionResult(status_code=200, ok=True, payload={"albumId": album_id, "ids": asset_ids})

    def update_asset(self, asset_id: str, payload: dict[str, object]) -> ActionResult:
        self.calls.append(("update_asset", asset_id, payload))
        return ActionResult(status_code=200, ok=True, payload={"assetId": asset_id, **payload})


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
            repository.insert_profile(profile_id="profile-1", immich_user_id="immich-user-1")
            repository.insert_action_policy(
                policy_id="policy-1",
                profile_id="profile-1",
                policy_key="review-policy",
                display_name="Review",
                execution_mode="manual",
            )
            repository.insert_action_destination(
                destination_id="dest-review",
                profile_id="profile-1",
                destination_key="review-album",
                destination_type="album",
                immich_resource_id="album-1",
            )
            repository.insert_action_destination(
                destination_id="dest-description",
                profile_id="profile-1",
                destination_key="asset-description",
                destination_type="asset_description",
                immich_resource_id="asset-description",
            )

            asset_client = FakeAssetClient(
                [
                    SearchResult(
                        items=[
                            make_asset(asset_id="child-positive", favorite=True, people=("kid-1",)),
                            make_asset(asset_id="child-negative", trashed=True, people=("kid-1",)),
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
                ]
            )
            timestamps = iter(["2026-05-09T12:00:00Z", "2026-05-09T12:10:00Z"])
            collector = AssetDiffCollector(
                repository,
                asset_client,
                profile_id="profile-1",
                now_factory=lambda: next(timestamps),
            )

            first_collect = collector.collect()

            embedding_reader = FakeEmbeddingReader(
                {
                    "child-positive": [2.0, 1.5],
                    "child-negative": [-2.0, -1.5],
                }
            )
            build_result = AssetFeatureInputBuilder(embedding_reader).build(first_collect.assets)

            self.assertEqual((), build_result.missing_embedding_asset_ids)
            self.assertEqual([["child-positive", "child-negative"]], embedding_reader.calls)
            inputs_by_asset_id = {asset_input.asset.id: asset_input for asset_input in build_result.inputs}
            self.assertTrue(inputs_by_asset_id["child-positive"].asset.is_favorite)
            self.assertTrue(inputs_by_asset_id["child-negative"].asset.is_trashed)
            self.assertEqual(("kid-1",), inputs_by_asset_id["child-positive"].asset.people)
            self.assertEqual([2.0, 1.5], list(inputs_by_asset_id["child-positive"].embedding))

            config = LabelResolverConfig(
                person_labels=PersonLabelConfig(child_person_ids=frozenset({"kid-1"})),
            )
            label_resolver = LabelResolver(config)
            feature_assembler = FeatureAssembler(config.known_category_keys)
            resolutions = [label_resolver.resolve(asset_input) for asset_input in build_result.inputs]

            training_result = TrainingJob(bootstrap_result.paths, feature_assembler).train(
                build_result.inputs,
                resolutions,
                trained_at="2026-05-09T12:20:00Z",
            )

            self.assertIn("generic", training_result.artifacts)
            self.assertIn("child", training_result.artifacts)

            action_client = FakeActionClient()
            inference_records = InferenceJob(
                bootstrap_result.paths,
                repository,
                feature_assembler,
                ActionExecutor(repository, action_client, profile_id="profile-1"),
                profile_id="profile-1",
            ).score_and_apply(
                build_result.inputs,
                resolutions,
                model_run_id=training_result.run_id,
                apply_config=ApplyConfig(
                    action_policy_id="policy-1",
                    review_album_destination_id="dest-review",
                    review_album_resource_id="album-1",
                    description_destination_id="dest-description",
                    review_threshold=1.1,
                ),
                occurred_at="2026-05-09T12:30:00Z",
                dry_run=False,
            )

            self.assertEqual(1, len(inference_records))
            self.assertEqual(1, len(repository.list_inference_traces("profile-1")))
            self.assertEqual(2, len(repository.list_action_execution_logs("profile-1")))
            self.assertEqual(2, len(action_client.calls))

            second_collect = collector.collect()

            self.assertEqual(
                {
                    "size": 1000,
                    "page": 1,
                    "updatedAfter": "2026-05-09T12:00:00Z",
                    "trashedAfter": "2026-05-09T12:00:00Z",
                },
                asset_client.calls[1],
            )
            self.assertEqual("2026-05-09T12:10:00Z", second_collect.cursor_after.updated_after)


if __name__ == "__main__":
    unittest.main()
