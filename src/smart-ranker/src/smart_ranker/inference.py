from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from smart_ranker.feature_pipeline import AssetFeatureInput, FeatureAssembler, LabelResolution
from smart_ranker.storage.paths import StoragePaths
from smart_ranker.storage.repository import (
    ActionExecutionLogRecord,
    InferenceTraceRecord,
    StorageRepository,
)
from smart_ranker.training import PERSON_CATEGORY_KEYS


@dataclass(frozen=True)
class ApplyConfig:
    action_policy_id: str
    review_album_destination_id: str | None
    review_album_resource_id: str | None
    description_destination_id: str | None
    review_threshold: float
    trigger_type: str = "manual"
    execution_mode: str = "manual"
    description_prefix: str = "smart-ranker score="


@dataclass(frozen=True)
class InferenceRecord:
    trace_id: str
    immich_asset_id: str
    scores: dict[str, float]
    final_score: float


class ModelBundle:
    def __init__(self, models: dict[str, dict[str, Any]]) -> None:
        self.models = models

    @classmethod
    def load(cls, model_dir: Path) -> "ModelBundle":
        models: dict[str, dict[str, Any]] = {}
        for artifact_path in sorted(model_dir.glob("*.pkl")):
            with artifact_path.open("rb") as file:
                payload = pickle.load(file)
            models[payload["model_key"]] = payload
        return cls(models)


class ActionExecutor:
    def __init__(self, repository: StorageRepository, action_client: Any, *, profile_id: str) -> None:
        self.repository = repository
        self.action_client = action_client
        self.profile_id = profile_id

    def apply(
        self,
        *,
        trace_id: str,
        asset_id: str,
        final_score: float,
        apply_config: ApplyConfig,
        occurred_at: str,
        dry_run: bool,
    ) -> None:
        if apply_config.review_album_destination_id and apply_config.review_album_resource_id and final_score < apply_config.review_threshold:
            request = {"albumId": apply_config.review_album_resource_id, "assetIds": [asset_id]}
            response = {}
            status = "planned"
            error_message = None
            if not dry_run:
                try:
                    client_result = self.action_client.add_assets_to_album(
                        apply_config.review_album_resource_id,
                        [asset_id],
                    )
                    response = client_result.payload if hasattr(client_result, "payload") else {}
                    status = "executed"
                except Exception as error:  # pragma: no cover - defensive path
                    response = {}
                    status = "failed"
                    error_message = str(error)

            self.repository.insert_action_execution_log(
                ActionExecutionLogRecord(
                    id=str(uuid4()),
                    profile_id=self.profile_id,
                    inference_trace_id=trace_id,
                    action_policy_id=apply_config.action_policy_id,
                    destination_id=apply_config.review_album_destination_id,
                    immich_asset_id=asset_id,
                    action_type="add_to_album",
                    execution_mode=apply_config.execution_mode,
                    dry_run=dry_run,
                    status=status,
                    request=request,
                    response=response,
                    error_message=error_message,
                    executed_at=occurred_at,
                )
            )

        if apply_config.description_destination_id:
            description = f"{apply_config.description_prefix}{final_score:.4f}"
            request = {"description": description}
            response = {}
            status = "planned"
            error_message = None
            if not dry_run:
                try:
                    client_result = self.action_client.update_asset(asset_id, request)
                    response = client_result.payload if hasattr(client_result, "payload") else {}
                    status = "executed"
                except Exception as error:  # pragma: no cover - defensive path
                    response = {}
                    status = "failed"
                    error_message = str(error)

            self.repository.insert_action_execution_log(
                ActionExecutionLogRecord(
                    id=str(uuid4()),
                    profile_id=self.profile_id,
                    inference_trace_id=trace_id,
                    action_policy_id=apply_config.action_policy_id,
                    destination_id=apply_config.description_destination_id,
                    immich_asset_id=asset_id,
                    action_type="update_description",
                    execution_mode=apply_config.execution_mode,
                    dry_run=dry_run,
                    status=status,
                    request=request,
                    response=response,
                    error_message=error_message,
                    executed_at=occurred_at,
                )
            )


class InferenceJob:
    def __init__(
        self,
        storage_paths: StoragePaths,
        repository: StorageRepository,
        feature_assembler: FeatureAssembler,
        action_executor: ActionExecutor,
        *,
        profile_id: str,
    ) -> None:
        self.storage_paths = storage_paths
        self.repository = repository
        self.feature_assembler = feature_assembler
        self.action_executor = action_executor
        self.profile_id = profile_id

    def score_and_apply(
        self,
        inputs: Sequence[AssetFeatureInput],
        resolutions: Sequence[LabelResolution],
        *,
        model_run_id: str,
        apply_config: ApplyConfig,
        occurred_at: str,
        dry_run: bool,
    ) -> list[InferenceRecord]:
        model_bundle = ModelBundle.load(self.storage_paths.models_dir / model_run_id)
        feature_matrix = self.feature_assembler.build_matrix(inputs, resolutions)
        inference_records: list[InferenceRecord] = []

        for asset_input, resolution, row in zip(inputs, resolutions, feature_matrix.rows):
            asset = asset_input.asset
            if asset.is_trashed or asset.visibility != "timeline":
                continue

            model_keys = self._model_keys_for_resolution(resolution)
            scores: dict[str, float] = {}
            for model_key in model_keys:
                model_payload = model_bundle.models.get(model_key)
                if model_payload is None:
                    continue
                if tuple(model_payload["feature_names"]) != feature_matrix.feature_names:
                    raise ValueError(f"feature mismatch for model {model_key}")
                estimator = model_payload["model"]
                scores[model_key] = float(estimator.predict_proba([row.vector])[0][1])

            final_score = max(scores.values()) if scores else 0.0
            trace_id = str(uuid4())
            self.repository.insert_inference_trace(
                InferenceTraceRecord(
                    id=trace_id,
                    profile_id=self.profile_id,
                    immich_asset_id=asset.id,
                    trigger_type=apply_config.trigger_type,
                    execution_mode=apply_config.execution_mode,
                    candidate_categories=list(resolution.candidate_labels),
                    score=scores,
                    final_score=final_score,
                    threshold_snapshot={"review_threshold": apply_config.review_threshold},
                    protected=False,
                    occurred_at=occurred_at,
                )
            )
            self.action_executor.apply(
                trace_id=trace_id,
                asset_id=asset.id,
                final_score=final_score,
                apply_config=apply_config,
                occurred_at=occurred_at,
                dry_run=dry_run,
            )
            inference_records.append(
                InferenceRecord(
                    trace_id=trace_id,
                    immich_asset_id=asset.id,
                    scores=scores,
                    final_score=final_score,
                )
            )

        return inference_records

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
