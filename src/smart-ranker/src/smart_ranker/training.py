from __future__ import annotations

import json
import pickle
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from uuid import uuid4

from sklearn.linear_model import LogisticRegression

from smart_ranker.feature_pipeline import AssetFeatureInput, FeatureAssembler, LabelResolution
from smart_ranker.storage.paths import StoragePaths


PERSON_CATEGORY_KEYS = frozenset({"person", "family", "child"})


@dataclass(frozen=True)
class WeakPositiveSignal:
    immich_asset_id: str
    sample_weight: float = 0.5
    label_value: float = 1.0
    feedback_type: str = "delete_candidate_rescued"


@dataclass(frozen=True)
class TrainingDecision:
    immich_asset_id: str
    label_value: int | None
    sample_weight: float
    source: str | None


@dataclass(frozen=True)
class TrainedModelArtifact:
    model_key: str
    feature_names: tuple[str, ...]
    sample_count: int
    positive_count: int
    negative_count: int
    artifact_path: Path


@dataclass(frozen=True)
class TrainingResult:
    run_id: str
    snapshot_path: Path
    artifacts: dict[str, TrainedModelArtifact]
    decisions: list[TrainingDecision]


class TrainingLabelResolver:
    def resolve(
        self,
        asset_input: AssetFeatureInput,
        weak_positive_by_asset: dict[str, WeakPositiveSignal],
    ) -> TrainingDecision:
        asset = asset_input.asset
        if asset.is_trashed:
            return TrainingDecision(asset.id, 0, 1.0, "trash")
        if asset.visibility == "archive":
            return TrainingDecision(asset.id, None, 0.0, "archive")
        if asset.is_favorite:
            return TrainingDecision(asset.id, 1, 1.0, "favorite")
        weak_positive = weak_positive_by_asset.get(asset.id)
        if weak_positive is not None:
            return TrainingDecision(
                asset.id,
                int(weak_positive.label_value),
                weak_positive.sample_weight,
                weak_positive.feedback_type,
            )
        return TrainingDecision(asset.id, None, 0.0, None)


class TrainingJob:
    def __init__(
        self,
        storage_paths: StoragePaths,
        feature_assembler: FeatureAssembler,
        *,
        label_resolver: TrainingLabelResolver | None = None,
    ) -> None:
        self.storage_paths = storage_paths
        self.feature_assembler = feature_assembler
        self.label_resolver = label_resolver or TrainingLabelResolver()

    def train(
        self,
        inputs: Sequence[AssetFeatureInput],
        resolutions: Sequence[LabelResolution],
        *,
        weak_positive_signals: Iterable[WeakPositiveSignal] = (),
        trained_at: str,
    ) -> TrainingResult:
        weak_positive_by_asset = {
            signal.immich_asset_id: signal for signal in weak_positive_signals
        }
        decisions = [
            self.label_resolver.resolve(asset_input, weak_positive_by_asset)
            for asset_input in inputs
        ]
        feature_matrix = self.feature_assembler.build_matrix(inputs, resolutions)

        grouped_samples: dict[str, dict[str, list[object]]] = defaultdict(
            lambda: {"X": [], "y": [], "sample_weight": [], "asset_ids": []}
        )

        for row, resolution, decision in zip(feature_matrix.rows, resolutions, decisions):
            if decision.label_value is None:
                continue

            for model_key in self._model_keys_for_resolution(resolution):
                grouped_samples[model_key]["X"].append(row.vector)
                grouped_samples[model_key]["y"].append(decision.label_value)
                grouped_samples[model_key]["sample_weight"].append(decision.sample_weight)
                grouped_samples[model_key]["asset_ids"].append(row.asset_id)

        run_id = str(uuid4())
        model_dir = self.storage_paths.models_dir / run_id
        model_dir.mkdir(parents=True, exist_ok=True)

        artifacts: dict[str, TrainedModelArtifact] = {}
        snapshot_payload = {
            "run_id": run_id,
            "trained_at": trained_at,
            "feature_names": list(feature_matrix.feature_names),
            "models": [],
            "decisions": [decision.__dict__ for decision in decisions],
        }

        for model_key, sample_set in grouped_samples.items():
            labels = sample_set["y"]
            if len(set(labels)) < 2:
                continue

            estimator = LogisticRegression(max_iter=1000)
            estimator.fit(
                sample_set["X"],
                labels,
                sample_weight=sample_set["sample_weight"],
            )
            artifact_path = model_dir / f"{model_key}.pkl"
            with artifact_path.open("wb") as file:
                pickle.dump(
                    {
                        "model": estimator,
                        "feature_names": feature_matrix.feature_names,
                        "model_key": model_key,
                    },
                    file,
                )

            positive_count = sum(1 for label in labels if label == 1)
            negative_count = sum(1 for label in labels if label == 0)
            artifact = TrainedModelArtifact(
                model_key=model_key,
                feature_names=feature_matrix.feature_names,
                sample_count=len(labels),
                positive_count=positive_count,
                negative_count=negative_count,
                artifact_path=artifact_path,
            )
            artifacts[model_key] = artifact
            snapshot_payload["models"].append(
                {
                    "model_key": model_key,
                    "artifact_path": str(artifact_path),
                    "sample_count": artifact.sample_count,
                    "positive_count": artifact.positive_count,
                    "negative_count": artifact.negative_count,
                }
            )

        snapshot_path = self.storage_paths.snapshots_dir / f"train-{run_id}.json"
        with snapshot_path.open("w", encoding="utf-8") as file:
            json.dump(snapshot_payload, file, ensure_ascii=True, indent=2, sort_keys=True)

        return TrainingResult(
            run_id=run_id,
            snapshot_path=snapshot_path,
            artifacts=artifacts,
            decisions=decisions,
        )

    @staticmethod
    def _model_keys_for_resolution(resolution: LabelResolution) -> list[str]:
        model_keys = ["generic"]
        if resolution.selected_person_label is not None:
            model_keys.append(resolution.selected_person_label)
        model_keys.extend(
            category_key
            for category_key in resolution.candidate_labels
            if category_key not in PERSON_CATEGORY_KEYS
        )
        return model_keys
