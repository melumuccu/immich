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
from smart_ranker.immich_client import AssetSnapshot
from smart_ranker.storage import bootstrap_storage
from smart_ranker.training import TrainingJob, TrainingLabelResolver, WeakPositiveSignal


def make_asset(
    *,
    asset_id: str,
    people: tuple[str, ...] = (),
    favorite: bool = False,
    trashed: bool = False,
    visibility: str = "timeline",
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


class TrainingTest(unittest.TestCase):
    def test_training_label_resolver_respects_priority(self) -> None:
        resolver = TrainingLabelResolver()
        archive_input = AssetFeatureInput(
            asset=make_asset(asset_id="archive-1", favorite=True, visibility="archive"),
            embedding=[0.1, 0.2],
        )
        trash_input = AssetFeatureInput(
            asset=make_asset(asset_id="trash-1", favorite=True, trashed=True),
            embedding=[0.1, 0.2],
        )
        weak_input = AssetFeatureInput(
            asset=make_asset(asset_id="weak-1"),
            embedding=[0.1, 0.2],
        )

        archive_decision = resolver.resolve(
            archive_input,
            {"archive-1": WeakPositiveSignal("archive-1", sample_weight=0.5)},
        )
        trash_decision = resolver.resolve(
            trash_input,
            {"trash-1": WeakPositiveSignal("trash-1", sample_weight=0.5)},
        )
        weak_decision = resolver.resolve(
            weak_input,
            {"weak-1": WeakPositiveSignal("weak-1", sample_weight=0.25)},
        )

        self.assertIsNone(archive_decision.label_value)
        self.assertEqual("archive", archive_decision.source)
        self.assertEqual(0, trash_decision.label_value)
        self.assertEqual("trash", trash_decision.source)
        self.assertEqual(1, weak_decision.label_value)
        self.assertEqual(0.25, weak_decision.sample_weight)

    def test_training_job_trains_generic_and_specialized_models_and_saves_artifacts(self) -> None:
        config = LabelResolverConfig(
            person_labels=PersonLabelConfig(child_person_ids=frozenset({"kid-1"})),
            mechanical_rules=(
                MechanicalRule(category_key="document", source="ocr_text", keywords=("invoice",)),
            ),
        )
        label_resolver = LabelResolver(config)
        feature_assembler = FeatureAssembler(config.known_category_keys)

        inputs = [
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
        resolutions = [label_resolver.resolve(asset_input) for asset_input in inputs]

        with tempfile.TemporaryDirectory() as temp_dir:
            bootstrap_result = bootstrap_storage(state_dir=Path(temp_dir) / "state")
            training_job = TrainingJob(bootstrap_result.paths, feature_assembler)

            result = training_job.train(
                inputs,
                resolutions,
                weak_positive_signals=[WeakPositiveSignal("doc-positive", sample_weight=0.5)],
                trained_at="2026-05-09T12:00:00Z",
            )

            self.assertIn("generic", result.artifacts)
            self.assertIn("child", result.artifacts)
            self.assertIn("document", result.artifacts)

            for artifact in result.artifacts.values():
                self.assertTrue(artifact.artifact_path.exists())
                self.assertGreaterEqual(artifact.sample_count, 2)

            self.assertTrue(result.snapshot_path.exists())
            snapshot = json.loads(result.snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(result.run_id, snapshot["run_id"])
            self.assertIn("generic", [model["model_key"] for model in snapshot["models"]])


if __name__ == "__main__":
    unittest.main()