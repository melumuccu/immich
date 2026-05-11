from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from smart_ranker.feature_pipeline import AssetFeatureInputBuilder, FeatureAssembler, LabelResolver
from smart_ranker.immich_client import ActionWriteClient, AssetReadClient, ImmichSession
from smart_ranker.immich_db_reader import ImmichDbConfig, ImmichDbReader
from smart_ranker.inference import ActionExecutor, InferenceJob
from smart_ranker.learning import ManualSignalCollector, fetch_assets_by_search
from smart_ranker.master_data import load_runtime_settings
from smart_ranker.storage.paths import StoragePaths
from smart_ranker.storage.repository import StorageRepository
from smart_ranker.training import TrainingJob, TrainingResult

IMMICH_BASE_URL_ENV = "SMART_RANKER_IMMICH_BASE_URL"
IMMICH_API_KEY_ENV = "SMART_RANKER_IMMICH_API_KEY"
IMMICH_DB_DSN_ENV = "SMART_RANKER_IMMICH_DB_DSN"
IMMICH_USER_ID_ENV = "SMART_RANKER_IMMICH_USER_ID"
REVIEW_ALBUM_ID_ENV = "SMART_RANKER_REVIEW_ALBUM_ID"
REVIEW_THRESHOLD_ENV = "SMART_RANKER_REVIEW_THRESHOLD"

JOB_TYPES = ("learn", "score", "apply")
DEFAULT_REVIEW_THRESHOLD = 0.5
DEFAULT_BATCH_SIZE = 1000
DEFAULT_POLICY_KEY = "review-policy"
DEFAULT_POLICY_DISPLAY_NAME = "Trash Threshold Policy"
DEFAULT_TRASH_DESTINATION_KEY = "trash-bin"
DEFAULT_TRASH_DESTINATION_RESOURCE_ID = "trash"


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
            raise JobConfigurationError(f"Missing runtime configuration: {', '.join(missing)}")

        review_threshold_raw = os.getenv(REVIEW_THRESHOLD_ENV)
        review_threshold = DEFAULT_REVIEW_THRESHOLD
        if review_threshold_raw:
            try:
                review_threshold = float(review_threshold_raw)
            except ValueError as error:
                raise JobConfigurationError(f"Invalid {REVIEW_THRESHOLD_ENV}: {review_threshold_raw}") from error

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
    training_result: TrainingResult | None = None
    latest_score_run_id: str | None = None


class SmartRankerJobRunner:
    def __init__(
        self,
        *,
        storage_paths: StoragePaths,
        repository: StorageRepository,
        asset_client: Any,
        signal_collector: ManualSignalCollector,
        feature_input_builder: AssetFeatureInputBuilder,
        label_resolver: LabelResolver,
        training_job: TrainingJob,
        inference_job: InferenceJob,
        profile_id: str,
        immich_user_id: str,
        batch_size: int,
        review_threshold: float,
        now_factory: Callable[[], str],
    ) -> None:
        self.storage_paths = storage_paths
        self.repository = repository
        self.asset_client = asset_client
        self.signal_collector = signal_collector
        self.feature_input_builder = feature_input_builder
        self.label_resolver = label_resolver
        self.training_job = training_job
        self.inference_job = inference_job
        self.profile_id = profile_id
        self.immich_user_id = immich_user_id
        self.batch_size = batch_size
        self.review_threshold = review_threshold
        self.now_factory = now_factory
        self.cache = JobRuntimeCache()

    def handlers(self) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
        return {
            "learn": self.learn,
            "score": self.score,
            "apply": self.apply,
        }

    def learn(self, payload: dict[str, Any]) -> dict[str, Any]:
        batch_size = self._resolve_batch_size(payload)
        sync_result = self.signal_collector.sync(batch_size=batch_size, max_assets=payload.get("maxAssets"))
        build_result = self.feature_input_builder.build(sync_result.training_assets)
        resolutions = [self.label_resolver.resolve(asset_input) for asset_input in build_result.inputs]
        training_result = self.training_job.train(
            build_result.inputs,
            resolutions,
            weak_positive_signals=(),
            trained_at=self.now_factory(),
        )
        self.cache.training_result = training_result
        self.cache.latest_score_run_id = None

        return {
            "runId": training_result.run_id,
            "favoriteSignalCount": len(sync_result.favorite_assets),
            "trashSignalCount": len(sync_result.trash_assets),
            "trainingAssetCount": len(sync_result.training_assets),
            "featureInputCount": len(build_result.inputs),
            "missingEmbeddingAssetIds": list(build_result.missing_embedding_asset_ids),
            "favoriteClearedCount": sync_result.favorite_cleared_count,
            "trashRestoredCount": sync_result.trash_restored_count,
            "excludedTrashCount": sync_result.excluded_trash_count,
            "modelCount": len(training_result.artifacts),
            "modelKeys": sorted(training_result.artifacts),
            "snapshotPath": str(training_result.snapshot_path),
            "batchSize": batch_size,
        }

    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        batch_size = self._resolve_batch_size(payload)
        model_run_id = self._resolve_model_run_id(payload)
        assets = fetch_assets_by_search(
            self.asset_client,
            batch_size=batch_size,
            max_assets=payload.get("maxAssets"),
        )
        build_result = self.feature_input_builder.build(assets)
        resolutions = [self.label_resolver.resolve(asset_input) for asset_input in build_result.inputs]
        threshold_value = float(payload.get("reviewThreshold", self.review_threshold))
        summary = self.inference_job.score_all_assets(
            build_result.inputs,
            resolutions,
            model_run_id=model_run_id,
            threshold_value=threshold_value,
            occurred_at=self.now_factory(),
        )
        self.cache.latest_score_run_id = summary.score_run_id

        return {
            "modelRunId": model_run_id,
            "scoreRunId": summary.score_run_id,
            "assetCount": summary.asset_count,
            "scoredAssetCount": summary.scored_asset_count,
            "threshold": summary.threshold_value,
            "missingEmbeddingAssetIds": list(build_result.missing_embedding_asset_ids),
        }

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        score_run_id = self._resolve_score_run_id(payload)
        threshold_value = float(payload.get("reviewThreshold", self.review_threshold))
        action_policy_id, destination_id = self._ensure_apply_context()
        records = self.inference_job.apply_score_threshold(
            score_run_id=score_run_id,
            threshold_value=threshold_value,
            action_policy_id=action_policy_id,
            destination_id=destination_id,
            occurred_at=self.now_factory(),
            dry_run=bool(payload.get("dryRun", False)),
        )
        return {
            "scoreRunId": score_run_id,
            "appliedCount": len(records),
            "assetIds": [record.immich_asset_id for record in records],
            "threshold": threshold_value,
            "dryRun": bool(payload.get("dryRun", False)),
        }

    def _resolve_batch_size(self, payload: dict[str, Any]) -> int:
        raw_value = payload.get("batchSize", self.batch_size)
        try:
            return max(1, int(raw_value))
        except (TypeError, ValueError):
            return self.batch_size

    def _resolve_model_run_id(self, payload: dict[str, Any]) -> str:
        explicit_model_run_id = payload.get("modelRunId")
        if explicit_model_run_id:
            return str(explicit_model_run_id)
        if self.cache.training_result is not None:
            return self.cache.training_result.run_id

        latest_model_run_id = self._latest_model_run_id()
        if latest_model_run_id is not None:
            return latest_model_run_id

        learn_result = self.learn({})
        run_id = learn_result.get("runId")
        if not run_id:
            raise JobConfigurationError("No model run available for score")
        return str(run_id)

    def _latest_model_run_id(self) -> str | None:
        for snapshot_path in sorted(self.storage_paths.snapshots_dir.glob("train-*.json"), reverse=True):
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            run_id = payload.get("run_id")
            if run_id:
                return str(run_id)
        return None

    def _resolve_score_run_id(self, payload: dict[str, Any]) -> str:
        explicit_score_run_id = payload.get("scoreRunId")
        if explicit_score_run_id:
            return str(explicit_score_run_id)
        if self.cache.latest_score_run_id is not None:
            return self.cache.latest_score_run_id

        latest_score_run = self.repository.get_latest_completed_score_run(self.profile_id)
        if latest_score_run is None:
            raise JobConfigurationError("No score run available for apply")
        return str(latest_score_run["id"])

    def _ensure_apply_context(self) -> tuple[str, str]:
        self.repository.ensure_profile(profile_id=self.profile_id, immich_user_id=self.immich_user_id)
        action_policy_id = self.repository.ensure_action_policy(
            policy_id=f"{self.profile_id}-{DEFAULT_POLICY_KEY}",
            profile_id=self.profile_id,
            policy_key=DEFAULT_POLICY_KEY,
            display_name=DEFAULT_POLICY_DISPLAY_NAME,
            execution_mode="manual",
        )
        destination_id = self.repository.ensure_action_destination(
            destination_id=f"{self.profile_id}-{DEFAULT_TRASH_DESTINATION_KEY}",
            profile_id=self.profile_id,
            destination_key=DEFAULT_TRASH_DESTINATION_KEY,
            destination_type="trash",
            immich_resource_id=DEFAULT_TRASH_DESTINATION_RESOURCE_ID,
        )
        return action_policy_id, destination_id


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
                result = {"error": str(error), "errorType": type(error).__name__}
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
        runtime_settings = load_runtime_settings(
            repository,
            profile_id=profile_id,
            default_review_album_resource_id=review_album_resource_id,
            default_review_threshold=review_threshold,
        )
        label_resolver = LabelResolver(runtime_settings.label_resolver_config)
        feature_assembler = FeatureAssembler(runtime_settings.label_resolver_config.known_category_keys)
        signal_collector = ManualSignalCollector(
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
            asset_client=asset_client,
            signal_collector=signal_collector,
            feature_input_builder=feature_input_builder,
            label_resolver=label_resolver,
            training_job=training_job,
            inference_job=inference_job,
            profile_id=profile_id,
            immich_user_id=immich_user_id,
            batch_size=_load_learn_batch_size(repository, profile_id),
            review_threshold=runtime_settings.review_threshold,
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

    return JobService(handlers={job_type: handler for job_type in JOB_TYPES}, now_factory=now_factory)


def _load_learn_batch_size(repository: StorageRepository, profile_id: str) -> int:
    for row in repository.list_execution_schedules(profile_id):
        if row["job_type"] in {"learn", "collect"}:
            return max(1, int(row["batch_size"]))
    return DEFAULT_BATCH_SIZE
