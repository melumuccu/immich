from __future__ import annotations

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
from smart_ranker.inference import ActionExecutor, InferenceJob
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
        self.calls: list[tuple[str, object, object]] = []

    def trash_assets(self, asset_ids: list[str], *, force: bool = False) -> ActionResult:
        self.calls.append(("trash_assets", list(asset_ids), {"force": force}))
        return ActionResult(status_code=200, ok=True, payload={"ids": list(asset_ids), "force": force})


class InferenceTest(unittest.TestCase):
    def test_score_all_assets_persists_score_run_and_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository, paths, feature_assembler, label_resolver, training_result = self._prepare_training(Path(temp_dir))

            score_inputs = [
                AssetFeatureInput(
                    asset=make_asset(asset_id="candidate-low", file_name="invoice-low.jpg", path="/docs/invoice-low.jpg"),
                    embedding=[-1.4, -1.1],
                    ocr_text="invoice overdue",
                ),
                AssetFeatureInput(
                    asset=make_asset(asset_id="candidate-high", people=("kid-1",)),
                    embedding=[1.9, 1.4],
                ),
            ]
            score_resolutions = [label_resolver.resolve(asset_input) for asset_input in score_inputs]

            action_client = FakeActionClient()
            inference_job = InferenceJob(
                paths,
                repository,
                feature_assembler,
                ActionExecutor(repository, action_client, profile_id="profile-1"),
                profile_id="profile-1",
            )
            summary = inference_job.score_all_assets(
                score_inputs,
                score_resolutions,
                model_run_id=training_result.run_id,
                threshold_value=0.5,
                occurred_at="2026-05-09T12:30:00Z",
            )

            self.assertEqual(2, summary.scored_asset_count)
            self.assertEqual([], action_client.calls)

            latest_score_run = repository.get_latest_completed_score_run("profile-1")
            self.assertIsNotNone(latest_score_run)
            self.assertEqual(summary.score_run_id, latest_score_run["id"])

            score_results = repository.list_score_results("profile-1", score_run_id=summary.score_run_id)
            self.assertEqual(2, len(score_results))
            self.assertEqual("candidate-low", score_results[0]["immich_asset_id"])
            self.assertEqual("candidate-high", score_results[1]["immich_asset_id"])

    def test_apply_score_threshold_trashes_only_low_score_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository, paths, feature_assembler, label_resolver, training_result = self._prepare_training(Path(temp_dir))
            repository.insert_action_policy(
                policy_id="policy-1",
                profile_id="profile-1",
                policy_key="review-policy",
                display_name="Trash Threshold Policy",
                execution_mode="manual",
            )
            repository.insert_action_destination(
                destination_id="dest-trash",
                profile_id="profile-1",
                destination_key="trash-bin",
                destination_type="trash",
                immich_resource_id="trash",
            )

            score_inputs = [
                AssetFeatureInput(
                    asset=make_asset(asset_id="candidate-low", file_name="invoice-low.jpg", path="/docs/invoice-low.jpg"),
                    embedding=[-1.4, -1.1],
                    ocr_text="invoice overdue",
                ),
                AssetFeatureInput(
                    asset=make_asset(asset_id="candidate-high", people=("kid-1",)),
                    embedding=[1.9, 1.4],
                ),
            ]
            score_resolutions = [label_resolver.resolve(asset_input) for asset_input in score_inputs]

            action_client = FakeActionClient()
            inference_job = InferenceJob(
                paths,
                repository,
                feature_assembler,
                ActionExecutor(repository, action_client, profile_id="profile-1"),
                profile_id="profile-1",
            )
            summary = inference_job.score_all_assets(
                score_inputs,
                score_resolutions,
                model_run_id=training_result.run_id,
                threshold_value=0.5,
                occurred_at="2026-05-09T12:30:00Z",
            )

            applied_records = inference_job.apply_score_threshold(
                score_run_id=summary.score_run_id,
                threshold_value=0.5,
                action_policy_id="policy-1",
                destination_id="dest-trash",
                occurred_at="2026-05-09T12:31:00Z",
                dry_run=False,
            )

            self.assertEqual(1, len(applied_records))
            self.assertEqual("candidate-low", applied_records[0].immich_asset_id)
            self.assertEqual(1, len(action_client.calls))
            self.assertEqual("trash_assets", action_client.calls[0][0])

            action_logs = repository.list_action_execution_logs("profile-1")
            self.assertEqual(1, len(action_logs))
            self.assertEqual("executed", action_logs[0]["status"])

            exclusions = repository.list_apply_exclusion_assets("profile-1")
            self.assertEqual(1, len(exclusions))
            self.assertEqual("candidate-low", exclusions[0]["immich_asset_id"])

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
