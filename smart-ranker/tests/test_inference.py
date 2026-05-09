from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from smart_ranker.feature_pipeline import (
    AssetFeatureInput,
    FeatureAssembler,
    LabelResolver,
    LabelResolverConfig,
    MechanicalRule,
    PersonLabelConfig,
)
from smart_ranker.immich_client import ActionResult, AssetSnapshot
from smart_ranker.inference import ActionExecutor, ApplyConfig, InferenceJob
from smart_ranker.storage import bootstrap_storage
from smart_ranker.storage.repository import StorageRepository
from smart_ranker.training import TrainingJob, WeakPositiveSignal


def make_asset(
    *,
    asset_id: str,
    favorite: bool = False,
    trashed: bool = False,
    visibility: str = "timeline",
    people: tuple[str, ...] = (),
    file_name: str = "IMG_0001.JPG",
    path: str = "/library/IMG_0001.JPG",
) -> AssetSnapshot:
    return AssetSnapshot(
        id=asset_id,
        is_favorite=favorite,
        is_trashed=trashed,
        visibility=visibility,
        people=people,
        original_file_name=file_name,
        original_path=path,
        updated_at="2026-05-09T00:00:00Z",
        payload={"id": asset_id},
    )


class FakeActionClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object] | list[str]]] = []

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> ActionResult:
        self.calls.append(("add_assets_to_album", album_id, asset_ids))
        return ActionResult(status_code=200, ok=True, payload={"albumId": album_id, "ids": asset_ids})

    def update_asset(self, asset_id: str, payload: dict[str, object]) -> ActionResult:
        self.calls.append(("update_asset", asset_id, payload))
        return ActionResult(status_code=200, ok=True, payload={"assetId": asset_id, **payload})


class InferenceTest(unittest.TestCase):
    def test_inference_job_records_trace_and_dry_run_logs_without_api_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository, paths, feature_assembler, label_resolver, training_result = self._prepare_training(Path(temp_dir))
            repository.insert_action_policy(
                policy_id="policy-1",
                profile_id="profile-1",
                policy_key="review-policy",
                display_name="review",
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

            candidate_input = AssetFeatureInput(
                asset=make_asset(asset_id="candidate-1", file_name="invoice-low.jpg", path="/docs/invoice-low.jpg"),
                embedding=[-1.4, -1.1],
                ocr_text="invoice overdue",
            )
            skipped_input = AssetFeatureInput(
                asset=make_asset(asset_id="skip-1", visibility="archive"),
                embedding=[-0.1, -0.2],
            )
            inputs = [candidate_input, skipped_input]
            resolutions = [label_resolver.resolve(asset_input) for asset_input in inputs]

            action_client = FakeActionClient()
            inference_job = InferenceJob(
                paths,
                repository,
                feature_assembler,
                ActionExecutor(repository, action_client, profile_id="profile-1"),
                profile_id="profile-1",
            )
            result = inference_job.score_and_apply(
                inputs,
                resolutions,
                model_run_id=training_result.run_id,
                apply_config=ApplyConfig(
                    action_policy_id="policy-1",
                    review_album_destination_id="dest-review",
                    review_album_resource_id="album-1",
                    description_destination_id="dest-description",
                    review_threshold=0.5,
                ),
                occurred_at="2026-05-09T12:30:00Z",
                dry_run=True,
            )

            self.assertEqual(1, len(result))
            self.assertEqual([], action_client.calls)

            traces = repository.list_inference_traces("profile-1")
            self.assertEqual(1, len(traces))
            self.assertEqual("candidate-1", traces[0]["immich_asset_id"])

            logs = repository.list_action_execution_logs("profile-1")
            self.assertEqual(2, len(logs))
            self.assertTrue(all(log["dry_run"] == 1 for log in logs))
            self.assertTrue(all(log["status"] == "planned" for log in logs))

    def test_inference_job_executes_album_and_description_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository, paths, feature_assembler, label_resolver, training_result = self._prepare_training(Path(temp_dir))
            repository.insert_action_policy(
                policy_id="policy-1",
                profile_id="profile-1",
                policy_key="review-policy",
                display_name="review",
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

            candidate_input = AssetFeatureInput(
                asset=make_asset(asset_id="candidate-1", file_name="invoice-low.jpg", path="/docs/invoice-low.jpg"),
                embedding=[-1.4, -1.1],
                ocr_text="invoice overdue",
            )
            action_client = FakeActionClient()
            inference_job = InferenceJob(
                paths,
                repository,
                feature_assembler,
                ActionExecutor(repository, action_client, profile_id="profile-1"),
                profile_id="profile-1",
            )

            inference_job.score_and_apply(
                [candidate_input],
                [label_resolver.resolve(candidate_input)],
                model_run_id=training_result.run_id,
                apply_config=ApplyConfig(
                    action_policy_id="policy-1",
                    review_album_destination_id="dest-review",
                    review_album_resource_id="album-1",
                    description_destination_id="dest-description",
                    review_threshold=0.5,
                ),
                occurred_at="2026-05-09T12:30:00Z",
                dry_run=False,
            )

            self.assertEqual(2, len(action_client.calls))
            self.assertEqual("add_assets_to_album", action_client.calls[0][0])
            self.assertEqual("update_asset", action_client.calls[1][0])

            logs = repository.list_action_execution_logs("profile-1")
            self.assertEqual(2, len(logs))
            self.assertTrue(all(log["status"] == "executed" for log in logs))
            update_request = json.loads(logs[1]["request_json"])
            self.assertIn("smart-ranker score=", update_request["description"])

    @staticmethod
    def _prepare_training(temp_root: Path):
        config = LabelResolverConfig(
            person_labels=PersonLabelConfig(child_person_ids=frozenset({"kid-1"})),
            mechanical_rules=(
                MechanicalRule(category_key="document", source="ocr_text", keywords=("invoice",)),
            ),
        )
        label_resolver = LabelResolver(config)
        feature_assembler = FeatureAssembler(config.known_category_keys)
        bootstrap_result = bootstrap_storage(state_dir=temp_root / "state")
        repository = StorageRepository(bootstrap_result.paths.db_path)
        repository.insert_profile(profile_id="profile-1", immich_user_id="immich-user-1")

        training_inputs = [
            AssetFeatureInput(
                asset=make_asset(asset_id="child-positive", people=("kid-1",), favorite=True),
                embedding=[2.0, 1.5],
            ),
            AssetFeatureInput(
                asset=make_asset(asset_id="child-negative", people=("kid-1",), trashed=True),
                embedding=[-2.0, -1.5],
            ),
            AssetFeatureInput(
                asset=make_asset(asset_id="doc-positive", file_name="invoice.jpg", path="/docs/invoice.jpg"),
                embedding=[1.5, 1.0],
                ocr_text="invoice total 1000",
            ),
            AssetFeatureInput(
                asset=make_asset(asset_id="doc-negative", trashed=True, file_name="invoice-2.jpg", path="/docs/invoice-2.jpg"),
                embedding=[-1.5, -1.0],
                ocr_text="invoice overdue",
            ),
        ]
        training_resolutions = [label_resolver.resolve(asset_input) for asset_input in training_inputs]
        training_result = TrainingJob(bootstrap_result.paths, feature_assembler).train(
            training_inputs,
            training_resolutions,
            weak_positive_signals=[WeakPositiveSignal("doc-positive", sample_weight=0.5)],
            trained_at="2026-05-09T12:00:00Z",
        )

        return repository, bootstrap_result.paths, feature_assembler, label_resolver, training_result


if __name__ == "__main__":
    unittest.main()
