from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Sequence
from uuid import uuid4

from smart_ranker.collector import AssetDiffCollector, RescueFeedbackInput
from smart_ranker.feature_pipeline import (
    AssetFeatureInput,
    AssetFeatureInputBuilder,
    FeatureAssembler,
    LabelResolution,
    LabelResolver,
    LabelResolverConfig,
)
from smart_ranker.immich_client import ActionWriteClient, AssetReadClient, ImmichSession
from smart_ranker.immich_db_reader import ImmichDbConfig, ImmichDbReader
from smart_ranker.inference import ActionExecutor, ApplyConfig, InferenceJob
from smart_ranker.storage.paths import StoragePaths
from smart_ranker.storage.repository import StorageRepository
from smart_ranker.training import TrainingJob, TrainingResult, WeakPositiveSignal

IMMICH_BASE_URL_ENV = "SMART_RANKER_IMMICH_BASE_URL"
IMMICH_API_KEY_ENV = "SMART_RANKER_IMMICH_API_KEY"
IMMICH_DB_DSN_ENV = "SMART_RANKER_IMMICH_DB_DSN"
IMMICH_USER_ID_ENV = "SMART_RANKER_IMMICH_USER_ID"
REVIEW_ALBUM_ID_ENV = "SMART_RANKER_REVIEW_ALBUM_ID"
REVIEW_THRESHOLD_ENV = "SMART_RANKER_REVIEW_THRESHOLD"

JOB_TYPES = ("collect", "train", "score", "apply")
DEFAULT_REVIEW_THRESHOLD = 0.5
DEFAULT_POLICY_KEY = "review-policy"
DEFAULT_POLICY_DISPLAY_NAME = "Review Policy"
DEFAULT_REVIEW_DESTINATION_KEY = "review-album"
DEFAULT_DESCRIPTION_DESTINATION_KEY = "asset-description"
DEFAULT_DESCRIPTION_RESOURCE_ID = "asset-description"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class JobConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobRuntimeConfig:
    immich_base_url: str
    immich_api_key: str
    immich_db_dsn: str
    immich_user_id: str
    review_album_resource_id: str | None = None
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD

    @classmethod
    def from_env(cls) -> "JobRuntimeConfig":
        env_values = {
            IMMICH_BASE_URL_ENV: os.getenv(IMMICH_BASE_URL_ENV),
            IMMICH_API_KEY_ENV: os.getenv(IMMICH_API_KEY_ENV),
            IMMICH_DB_DSN_ENV: os.getenv(IMMICH_DB_DSN_ENV),
            IMMICH_USER_ID_ENV: os.getenv(IMMICH_USER_ID_ENV),
        }
        missing = [name for name, value in env_values.items() if not value]
        if missing:
            joined = ", ".join(missing)
            raise JobConfigurationError(f"Missing runtime configuration: {joined}")

        review_threshold_raw = os.getenv(REVIEW_THRESHOLD_ENV)
        review_threshold = DEFAULT_REVIEW_THRESHOLD
        if review_threshold_raw:
            try:
                review_threshold = float(review_threshold_raw)
            except ValueError as error:
                raise JobConfigurationError(
                    f"Invalid {REVIEW_THRESHOLD_ENV}: {review_threshold_raw}"
                ) from error

        return cls(
            immich_base_url=env_values[IMMICH_BASE_URL_ENV] or "",
            immich_api_key=env_values[IMMICH_API_KEY_ENV] or "",
            immich_db_dsn=env_values[IMMICH_DB_DSN_ENV] or "",
            immich_user_id=env_values[IMMICH_USER_ID_ENV] or "",
            review_album_resource_id=os.getenv(REVIEW_ALBUM_ID_ENV),
            review_threshold=review_threshold,
        )


@dataclass
class JobRuntimeCache:
    feature_inputs: list[AssetFeatureInput] = field(default_factory=list)
    label_resolutions: list[LabelResolution] = field(default_factory=list)
    training_result: TrainingResult | None = None


class SmartRankerJobRunner:
    def __init__(
        self,
        *,
        storage_paths: StoragePaths,
        repository: StorageRepository,
        collector: AssetDiffCollector,
        feature_input_builder: AssetFeatureInputBuilder,
        label_resolver: LabelResolver,
        training_job: TrainingJob,
        inference_job: InferenceJob,
        profile_id: str,
        immich_user_id: str,
        review_album_resource_id: str | None,
        review_threshold: float,
        now_factory: Callable[[], str],
    ) -> None:
        self.storage_paths = storage_paths
        self.repository = repository
        self.collector = collector
        self.feature_input_builder = feature_input_builder
        self.label_resolver = label_resolver
        self.training_job = training_job
        self.inference_job = inference_job
        self.profile_id = profile_id
        self.immich_user_id = immich_user_id
        self.review_album_resource_id = review_album_resource_id
        self.review_threshold = review_threshold
        self.now_factory = now_factory
        self.cache = JobRuntimeCache()

    def handlers(self) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
        return {
            "collect": self.collect,
            "train": self.train,
            "score": self.score,
            "apply": self.apply,
        }

    def collect(self, payload: dict[str, Any]) -> dict[str, Any]:
        rescued_assets = self._parse_rescued_assets(payload.get("rescuedAssets", ()))
        collect_result = self.collector.collect(rescued_assets=rescued_assets)
        build_result = self.feature_input_builder.build(collect_result.assets)
        resolutions = [self.label_resolver.resolve(asset_input) for asset_input in build_result.inputs]

        self.cache.feature_inputs = list(build_result.inputs)
        self.cache.label_resolutions = resolutions
        self.cache.training_result = None

        return {
            "runId": collect_result.run_id,
            "assetCount": len(collect_result.assets),
            "featureInputCount": len(build_result.inputs),
            "missingEmbeddingAssetIds": list(build_result.missing_embedding_asset_ids),
            "feedbackCount": collect_result.feedback_count,
            "cursorUpdatedAfter": collect_result.cursor_after.updated_after,
        }

    def train(self, payload: dict[str, Any]) -> dict[str, Any]:
        inputs, resolutions = self._ensure_inputs(payload)
        training_result = self.training_job.train(
            inputs,
            resolutions,
            weak_positive_signals=self._load_weak_positive_signals(),
            trained_at=self.now_factory(),
        )
        self.cache.training_result = training_result

        return {
            "runId": training_result.run_id,
            "modelCount": len(training_result.artifacts),
            "modelKeys": sorted(training_result.artifacts),
            "snapshotPath": str(training_result.snapshot_path),
        }

    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._run_inference(payload, dry_run=True)

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._run_inference(payload, dry_run=bool(payload.get("dryRun", False)))

    def _run_inference(self, payload: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        inputs, resolutions = self._ensure_inputs(payload)
        model_run_id = self._resolve_model_run_id(payload)
        apply_config = self._ensure_apply_config(payload)
        records = self.inference_job.score_and_apply(
            inputs,
            resolutions,
            model_run_id=model_run_id,
            apply_config=apply_config,
            occurred_at=self.now_factory(),
            dry_run=dry_run,
        )
        return {
            "modelRunId": model_run_id,
            "traceCount": len(records),
            "traceIds": [record.trace_id for record in records],
            "dryRun": dry_run,
        }

    def _ensure_inputs(self, payload: dict[str, Any]) -> tuple[Sequence[AssetFeatureInput], Sequence[LabelResolution]]:
        force_collect = bool(payload.get("forceCollect", False))
        if force_collect or not self.cache.feature_inputs:
            self.collect({})
        return self.cache.feature_inputs, self.cache.label_resolutions

    def _resolve_model_run_id(self, payload: dict[str, Any]) -> str:
        explicit_model_run_id = payload.get("modelRunId")
        if explicit_model_run_id:
            return str(explicit_model_run_id)
        if self.cache.training_result is not None:
            return self.cache.training_result.run_id

        latest_model_run_id = self._latest_model_run_id()
        if latest_model_run_id is not None:
            return latest_model_run_id

        training_result = self.train({})
        run_id = training_result.get("runId")
        if not run_id:
            raise JobConfigurationError("No model run available for inference")
        return str(run_id)

    def _latest_model_run_id(self) -> str | None:
        for snapshot_path in sorted(self.storage_paths.snapshots_dir.glob("train-*.json"), reverse=True):
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            run_id = payload.get("run_id")
            if run_id:
                return str(run_id)
        return None

    def _load_weak_positive_signals(self) -> list[WeakPositiveSignal]:
        signals: list[WeakPositiveSignal] = []
        for row in self.repository.list_feedback_events(self.profile_id):
            immich_asset_id = row["immich_asset_id"]
            if not immich_asset_id:
                continue
            signals.append(
                WeakPositiveSignal(
                    immich_asset_id=str(immich_asset_id),
                    sample_weight=float(row["sample_weight"]),
                    label_value=float(row["label_value"]),
                    feedback_type=str(row["feedback_type"]),
                )
            )
        return signals

    def _ensure_apply_config(self, payload: dict[str, Any]) -> ApplyConfig:
        self.repository.ensure_profile(profile_id=self.profile_id, immich_user_id=self.immich_user_id)
        action_policy_id = self.repository.ensure_action_policy(
            policy_id=f"{self.profile_id}-review-policy",
            profile_id=self.profile_id,
            policy_key=DEFAULT_POLICY_KEY,
            display_name=DEFAULT_POLICY_DISPLAY_NAME,
            execution_mode="manual",
        )
        description_destination_id = self.repository.ensure_action_destination(
            destination_id=f"{self.profile_id}-asset-description",
            profile_id=self.profile_id,
            destination_key=DEFAULT_DESCRIPTION_DESTINATION_KEY,
            destination_type="asset_description",
            immich_resource_id=DEFAULT_DESCRIPTION_RESOURCE_ID,
        )

        review_album_resource_id = payload.get("reviewAlbumResourceId", self.review_album_resource_id)
        review_album_destination_id: str | None = None
        if review_album_resource_id:
            review_album_destination_id = self.repository.ensure_action_destination(
                destination_id=f"{self.profile_id}-review-album",
                profile_id=self.profile_id,
                destination_key=DEFAULT_REVIEW_DESTINATION_KEY,
                destination_type="album",
                immich_resource_id=str(review_album_resource_id),
            )

        description_destination_enabled = payload.get("updateDescription", True)
        review_threshold = float(payload.get("reviewThreshold", self.review_threshold))

        return ApplyConfig(
            action_policy_id=action_policy_id,
            review_album_destination_id=review_album_destination_id,
            review_album_resource_id=str(review_album_resource_id) if review_album_resource_id else None,
            description_destination_id=description_destination_id if description_destination_enabled else None,
            review_threshold=review_threshold,
        )

    @staticmethod
    def _parse_rescued_assets(raw_items: Iterable[dict[str, Any]] | Any) -> list[RescueFeedbackInput]:
        if not isinstance(raw_items, Iterable) or isinstance(raw_items, (str, bytes, dict)):
            return []

        rescued_assets: list[RescueFeedbackInput] = []
        for item in raw_items:
            if not isinstance(item, dict) or not item.get("immichAssetId"):
                continue
            rescued_assets.append(
                RescueFeedbackInput(
                    immich_asset_id=str(item["immichAssetId"]),
                    previous_score=float(item["previousScore"]) if item.get("previousScore") is not None else None,
                    category_id=str(item["categoryId"]) if item.get("categoryId") else None,
                    source_trace_id=str(item["sourceTraceId"]) if item.get("sourceTraceId") else None,
                    sample_weight=float(item.get("sampleWeight", 0.5)),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else None,
                    note=str(item["note"]) if item.get("note") else None,
                    occurred_at=str(item["occurredAt"]) if item.get("occurredAt") else None,
                )
            )
        return rescued_assets


@dataclass(frozen=True)
class JobRun:
    id: str
    job_type: str
    status: str
    submitted_at: str
    payload: dict[str, Any]
    result: dict[str, Any] | None = None


class JobService:
    def __init__(
        self,
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
        now_factory: Callable[[], str] = utc_now_iso,
    ) -> None:
        self.handlers = handlers or {}
        self.now_factory = now_factory
        self._jobs: dict[str, JobRun] = {}

    def submit(self, job_type: str, payload: dict[str, Any] | None = None) -> JobRun:
        job_id = str(uuid4())
        submitted_at = self.now_factory()
        handler = self.handlers.get(job_type)
        status = "completed"
        if handler is None:
            result = {"accepted": True}
        else:
            try:
                result = handler(payload or {})
            except Exception as error:
                status = "failed"
                result = {
                    "error": str(error),
                    "errorType": type(error).__name__,
                }
        job_run = JobRun(
            id=job_id,
            job_type=job_type,
            status=status,
            submitted_at=submitted_at,
            payload=payload or {},
            result=result,
        )
        self._jobs[job_id] = job_run
        return job_run

    def get(self, job_id: str) -> JobRun | None:
        return self._jobs.get(job_id)


def build_job_service(
    *,
    storage_paths: StoragePaths,
    repository: StorageRepository,
    profile_id: str,
    immich_user_id: str | None = None,
    asset_client: AssetReadClient | Any | None = None,
    embedding_reader: ImmichDbReader | Any | None = None,
    action_client: ActionWriteClient | Any | None = None,
    review_album_resource_id: str | None = None,
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
    now_factory: Callable[[], str] = utc_now_iso,
) -> JobService:
    try:
        runtime_config: JobRuntimeConfig | None = None
        session: ImmichSession | None = None
        if asset_client is None or embedding_reader is None or action_client is None or immich_user_id is None:
            runtime_config = JobRuntimeConfig.from_env()
            immich_user_id = immich_user_id or runtime_config.immich_user_id
            review_album_resource_id = review_album_resource_id or runtime_config.review_album_resource_id
            review_threshold = runtime_config.review_threshold if review_threshold == DEFAULT_REVIEW_THRESHOLD else review_threshold
            if asset_client is None or action_client is None:
                session = ImmichSession(runtime_config.immich_base_url, runtime_config.immich_api_key)
            if asset_client is None:
                asset_client = AssetReadClient(session or ImmichSession(runtime_config.immich_base_url, runtime_config.immich_api_key))
            if action_client is None:
                action_client = ActionWriteClient(session or ImmichSession(runtime_config.immich_base_url, runtime_config.immich_api_key))
            if embedding_reader is None:
                embedding_reader = ImmichDbReader(ImmichDbConfig(runtime_config.immich_db_dsn))

        if immich_user_id is None:
            raise JobConfigurationError(f"Missing runtime configuration: {IMMICH_USER_ID_ENV}")

        repository.ensure_profile(profile_id=profile_id, immich_user_id=immich_user_id)
        label_resolver_config = LabelResolverConfig()
        label_resolver = LabelResolver(label_resolver_config)
        feature_assembler = FeatureAssembler(label_resolver_config.known_category_keys)
        collector = AssetDiffCollector(
            repository,
            asset_client,
            profile_id=profile_id,
            now_factory=now_factory,
        )
        feature_input_builder = AssetFeatureInputBuilder(embedding_reader)
        training_job = TrainingJob(storage_paths, feature_assembler)
        inference_job = InferenceJob(
            storage_paths,
            repository,
            feature_assembler,
            ActionExecutor(repository, action_client, profile_id=profile_id),
            profile_id=profile_id,
        )
        runner = SmartRankerJobRunner(
            storage_paths=storage_paths,
            repository=repository,
            collector=collector,
            feature_input_builder=feature_input_builder,
            label_resolver=label_resolver,
            training_job=training_job,
            inference_job=inference_job,
            profile_id=profile_id,
            immich_user_id=immich_user_id,
            review_album_resource_id=review_album_resource_id,
            review_threshold=review_threshold,
            now_factory=now_factory,
        )
        return JobService(handlers=runner.handlers(), now_factory=now_factory)
    except JobConfigurationError as error:
        return _build_configuration_error_service(error, now_factory)


def _build_configuration_error_service(
    error: JobConfigurationError,
    now_factory: Callable[[], str],
) -> JobService:
    def handler(_: dict[str, Any]) -> dict[str, Any]:
        raise error

    return JobService(
        handlers={job_type: handler for job_type in JOB_TYPES},
        now_factory=now_factory,
    )
