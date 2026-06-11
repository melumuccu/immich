from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from smart_ranker.immich_client import AssetReadClient, ImmichHttpError, ImmichSession, PeopleClient
from smart_ranker.master_data import (
    load_master_data,
    resolve_seed_inputs,
    save_categories_and_routing,
    save_person_groups,
    save_policies,
    save_schedules,
    seed_master_data,
)
from smart_ranker.storage import bootstrap_storage
from smart_ranker.storage.repository import StorageRepository
from smart_ranker.web.job_service import JobConfigurationError, JobRuntimeConfig, JobService, build_job_service


LIVE_RELOAD_ENV = "SMART_RANKER_LIVE_RELOAD"
LIVE_RELOAD_INTERVAL_MS = 1000
LIVE_RELOAD_SUFFIXES = frozenset({".py", ".css", ".html", ".js"})
LIVE_RELOAD_PATH = "/api/dev/live-reload"
UVICORN_ACCESS_LOGGER_NAME = "uvicorn.access"


class LiveReloadAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple) or len(record.args) < 3:
            return True

        path = str(record.args[2])
        return not path.startswith(LIVE_RELOAD_PATH)


LIVE_RELOAD_ACCESS_LOG_FILTER = LiveReloadAccessLogFilter()


def _configure_live_reload_access_log_filter(enabled: bool) -> None:
    access_logger = logging.getLogger(UVICORN_ACCESS_LOGGER_NAME)
    filter_installed = any(filter_ is LIVE_RELOAD_ACCESS_LOG_FILTER for filter_ in access_logger.filters)

    if enabled and not filter_installed:
        access_logger.addFilter(LIVE_RELOAD_ACCESS_LOG_FILTER)
        return

    if not enabled and filter_installed:
        access_logger.removeFilter(LIVE_RELOAD_ACCESS_LOG_FILTER)


def create_app(
    *,
    state_dir: Path | str | None = None,
    profile_id: str = "default-profile",
    job_service: JobService | None = None,
    people_client: PeopleClient | None = None,
) -> FastAPI:
    bootstrap_result = bootstrap_storage(state_dir=state_dir)
    repository = StorageRepository(bootstrap_result.paths.db_path)
    app = FastAPI(title="Smart Ranker")
    app.state.paths = bootstrap_result.paths
    app.state.repository = repository
    app.state.profile_id = profile_id
    app.state.auto_rebuild_job_service = job_service is None
    app.state.people_client = people_client
    app.state.asset_client = None
    app.state.job_service = job_service or build_job_service(
        storage_paths=bootstrap_result.paths,
        repository=repository,
        profile_id=profile_id,
    )

    web_dir = Path(__file__).resolve().parent
    static_dir = web_dir / "static"
    app.state.live_reload_enabled = os.getenv(LIVE_RELOAD_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    _configure_live_reload_access_log_filter(app.state.live_reload_enabled)
    app.state.live_reload_watch_dir = web_dir
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    def _render_console() -> HTMLResponse:
        asset_version = _build_live_reload_token()
        asset_query = urlencode({"v": asset_version})
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        html = html.replace(
            'href="/static/styles.css"',
            f'href="/static/styles.css?{asset_query}"',
        )
        html = html.replace(
            'src="/static/app.js"',
            f'src="/static/app.js?{asset_query}"',
        )
        return HTMLResponse(content=html)

    @app.get("/")
    def index() -> HTMLResponse:
        return _render_console()

    @app.get("/settings")
    def settings() -> HTMLResponse:
        return _render_console()

    @app.get("/score-review")
    def score_review() -> HTMLResponse:
        return _render_console()

    def _build_live_reload_token() -> str:
        watch_dir = app.state.live_reload_watch_dir
        digest = hashlib.blake2b(digest_size=16)
        for file_path in sorted(watch_dir.rglob("*")):
            if not file_path.is_file() or file_path.suffix not in LIVE_RELOAD_SUFFIXES:
                continue
            stat = file_path.stat()
            digest.update(str(file_path.relative_to(watch_dir)).encode("utf-8"))
            digest.update(b":")
            digest.update(str(stat.st_mtime_ns).encode("ascii"))
            digest.update(b":")
            digest.update(str(stat.st_size).encode("ascii"))
            digest.update(b";")
        return digest.hexdigest()

    @app.get("/api/dev/live-reload")
    def live_reload_status() -> dict:
        if not app.state.live_reload_enabled:
            return {
                "enabled": False,
                "intervalMs": LIVE_RELOAD_INTERVAL_MS,
                "token": None,
            }

        return {
            "enabled": True,
            "intervalMs": LIVE_RELOAD_INTERVAL_MS,
            "token": _build_live_reload_token(),
        }

    def _load_models() -> list[dict]:
        snapshots = []
        for snapshot_path in sorted(app.state.paths.snapshots_dir.glob("train-*.json")):
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshots.append(
                {
                    "snapshotPath": str(snapshot_path),
                    "runId": payload.get("run_id"),
                    "trainedAt": payload.get("trained_at"),
                    "models": payload.get("models", []),
                }
            )
        return snapshots

    def _load_runtime_reset_token() -> str | None:
        token_path = app.state.paths.runtime_reset_token_path()
        if not token_path.exists():
            return None
        token = token_path.read_text(encoding="utf-8").strip()
        return token or None

    def _load_settings() -> dict:
        return load_master_data(app.state.repository, app.state.profile_id)

    def _resolve_immich_user_id(payload: dict | None = None) -> str:
        explicit_user_id = payload.get("immichUserId") if payload else None
        if explicit_user_id:
            return str(explicit_user_id)

        profile_row = app.state.repository.get_profile(app.state.profile_id)
        if profile_row is not None and profile_row["immich_user_id"]:
            return str(profile_row["immich_user_id"])

        try:
            return resolve_seed_inputs()[0]
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    def _reload_job_service() -> bool:
        if not app.state.auto_rebuild_job_service:
            return False
        app.state.job_service = build_job_service(
            storage_paths=app.state.paths,
            repository=app.state.repository,
            profile_id=app.state.profile_id,
        )
        return True

    def _get_people_client() -> PeopleClient:
        existing_client = app.state.people_client
        if existing_client is not None:
            return existing_client

        try:
            runtime_config = JobRuntimeConfig.from_env()
        except JobConfigurationError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        app.state.people_client = PeopleClient(
            ImmichSession(runtime_config.immich_base_url, runtime_config.immich_api_key)
        )
        return app.state.people_client

    def _get_asset_client() -> AssetReadClient:
        existing_client = app.state.asset_client
        if existing_client is not None:
            return existing_client

        try:
            runtime_config = JobRuntimeConfig.from_env()
        except JobConfigurationError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        app.state.asset_client = AssetReadClient(
            ImmichSession(runtime_config.immich_base_url, runtime_config.immich_api_key)
        )
        return app.state.asset_client

    def _serialize_score_result_row(row) -> dict:
        category_scores = json.loads(row["category_scores_json"] or "{}")
        current_state = json.loads(row["current_state_json"] or "{}")
        asset_id = str(row["immich_asset_id"])
        return {
            "id": row["id"],
            "scoreRunId": row["score_run_id"],
            "immichAssetId": asset_id,
            "totalScore": float(row["total_score"]),
            "rankIndex": int(row["rank_index"]),
            "categoryScores": category_scores,
            "currentState": current_state,
            "thumbnailUrl": f"/api/assets/{asset_id}/thumbnail",
        }

    def _normalize_score_review_sort_order(value: str | None) -> str:
        return "desc" if str(value or "").lower() == "desc" else "asc"

    @app.post("/api/jobs/{job_type}")
    def submit_job(job_type: str, payload: dict | None = None) -> JSONResponse:
        if job_type not in {"learn", "score", "apply"}:
            raise HTTPException(status_code=404, detail="Unknown job type")
        job_run = app.state.job_service.submit(job_type, payload)
        return JSONResponse(
            status_code=202,
            content={
                "jobRunId": job_run.id,
                "jobType": job_run.job_type,
                "status": job_run.status,
                "submittedAt": job_run.submitted_at,
            },
        )

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job_run = app.state.job_service.get(job_id)
        if job_run is None:
            raise HTTPException(status_code=404, detail="Unknown job id")
        return {
            "jobRunId": job_run.id,
            "jobType": job_run.job_type,
            "status": job_run.status,
            "submittedAt": job_run.submitted_at,
            "payload": job_run.payload,
            "result": job_run.result,
        }

    @app.get("/api/person-groups")
    def list_person_groups() -> list[dict]:
        rows = app.state.repository.list_person_groups(app.state.profile_id)
        return [dict(row) for row in rows]

    @app.get("/api/categories")
    def list_categories() -> list[dict]:
        rows = app.state.repository.list_categories(app.state.profile_id)
        return [dict(row) for row in rows]

    @app.get("/api/policies")
    def list_policies() -> list[dict]:
        rows = app.state.repository.list_action_policies(app.state.profile_id)
        return [dict(row) for row in rows]

    @app.get("/api/models")
    def list_models() -> list[dict]:
        return _load_models()

    @app.get("/api/immich/people")
    def list_immich_people(
        q: str | None = None,
        limit: int = 20,
        with_hidden: bool = False,
    ) -> dict:
        people_client = _get_people_client()
        normalized_limit = max(1, min(limit, 100))
        try:
            if q and q.strip():
                people = people_client.search_people(
                    q.strip(),
                    with_hidden=with_hidden,
                    limit=normalized_limit,
                )
            else:
                people = people_client.list_people(page=1, size=normalized_limit, with_hidden=with_hidden)
        except ImmichHttpError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

        return {
            "items": [
                {
                    "id": person.id,
                    "name": person.name,
                    "isHidden": person.is_hidden,
                    "faceAssetId": person.face_asset_id,
                }
                for person in people[:normalized_limit]
            ]
        }

    @app.get("/api/assets/{asset_id}/thumbnail")
    def get_asset_thumbnail(asset_id: str) -> Response:
        asset_client = _get_asset_client()
        try:
            thumbnail = asset_client.get_asset_thumbnail(asset_id)
        except ImmichHttpError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

        headers = {}
        if thumbnail.cache_control:
            headers["Cache-Control"] = thumbnail.cache_control
        if thumbnail.etag:
            headers["ETag"] = thumbnail.etag
        return Response(
            content=thumbnail.payload,
            media_type=thumbnail.content_type or "image/jpeg",
            headers=headers,
        )

    @app.get("/api/score-review")
    def get_score_review(
        page: int = 1,
        page_size: int = Query(100, alias="pageSize"),
        score_run_id: str | None = Query(None, alias="scoreRunId"),
        sort_order: str = Query("asc", alias="sortOrder"),
    ) -> dict:
        normalized_page_size = min(max(1, int(page_size)), 100)
        requested_page = max(1, int(page))
        resolved_sort_order = _normalize_score_review_sort_order(sort_order)

        selected_score_run = (
            app.state.repository.get_score_run(app.state.profile_id, score_run_id)
            if score_run_id
            else app.state.repository.get_latest_completed_score_run(app.state.profile_id)
        )
        if selected_score_run is None:
            return {
                "scoreRunId": None,
                "page": 1,
                "pageSize": normalized_page_size,
                "sortOrder": resolved_sort_order,
                "totalItems": 0,
                "totalPages": 0,
                "items": [],
            }

        resolved_score_run_id = str(selected_score_run["id"])
        total_items = app.state.repository.count_score_results(
            app.state.profile_id,
            score_run_id=resolved_score_run_id,
        )
        total_pages = (total_items + normalized_page_size - 1) // normalized_page_size if total_items else 0
        resolved_page = min(requested_page, total_pages) if total_pages else 1
        offset = max(0, (resolved_page - 1) * normalized_page_size)
        rows = app.state.repository.list_score_results_page(
            app.state.profile_id,
            score_run_id=resolved_score_run_id,
            limit=normalized_page_size,
            offset=offset,
            sort_order=resolved_sort_order,
        )

        return {
            "scoreRunId": resolved_score_run_id,
            "page": resolved_page,
            "pageSize": normalized_page_size,
            "sortOrder": resolved_sort_order,
            "totalItems": total_items,
            "totalPages": total_pages,
            "items": [_serialize_score_result_row(row) for row in rows],
            "scoreRun": {
                "id": selected_score_run["id"],
                "modelRunId": selected_score_run["model_run_id"],
                "triggerType": selected_score_run["trigger_type"],
                "status": selected_score_run["status"],
                "startedAt": selected_score_run["started_at"],
                "completedAt": selected_score_run["completed_at"],
            },
        }

    @app.get("/api/settings/person-groups")
    def get_person_group_settings() -> dict:
        return {"personGroups": _load_settings()["personGroups"]}

    @app.put("/api/settings/person-groups")
    def update_person_group_settings(payload: dict) -> dict:
        immich_user_id = _resolve_immich_user_id(payload)
        saved = save_person_groups(
            app.state.repository,
            profile_id=app.state.profile_id,
            immich_user_id=immich_user_id,
            groups=payload.get("personGroups", []),
        )
        return {
            "personGroups": saved,
            "jobServiceReloaded": _reload_job_service(),
        }

    @app.get("/api/settings/categories-routing")
    def get_categories_and_routing_settings() -> dict:
        settings = _load_settings()
        return {
            "categories": settings["categories"],
            "routingRules": settings["routingRules"],
        }

    @app.put("/api/settings/categories-routing")
    def update_categories_and_routing_settings(payload: dict) -> dict:
        immich_user_id = _resolve_immich_user_id(payload)
        saved = save_categories_and_routing(
            app.state.repository,
            profile_id=app.state.profile_id,
            immich_user_id=immich_user_id,
            categories=payload.get("categories", []),
            routing_rules=payload.get("routingRules", []),
        )
        return {
            **saved,
            "jobServiceReloaded": _reload_job_service(),
        }

    @app.get("/api/settings/policies")
    def get_policy_settings() -> dict:
        settings = _load_settings()
        return {
            "policies": settings["policies"],
            "destinations": settings["destinations"],
        }

    @app.put("/api/settings/policies")
    def update_policy_settings(payload: dict) -> dict:
        immich_user_id = _resolve_immich_user_id(payload)
        saved = save_policies(
            app.state.repository,
            profile_id=app.state.profile_id,
            immich_user_id=immich_user_id,
            policies=payload.get("policies", []),
            destinations=payload.get("destinations", []),
        )
        return {
            **saved,
            "jobServiceReloaded": _reload_job_service(),
        }

    @app.get("/api/settings/jobs-models")
    def get_job_and_model_settings() -> dict:
        settings = _load_settings()
        return {
            "schedules": settings["schedules"],
            "models": _load_models(),
            "runtimeResetToken": _load_runtime_reset_token(),
        }

    @app.put("/api/settings/schedules")
    def update_schedule_settings(payload: dict) -> dict:
        immich_user_id = _resolve_immich_user_id(payload)
        saved = save_schedules(
            app.state.repository,
            profile_id=app.state.profile_id,
            immich_user_id=immich_user_id,
            schedules=payload.get("schedules", []),
        )
        return {
            "schedules": saved,
            "jobServiceReloaded": _reload_job_service(),
        }

    @app.post("/api/settings/seed-defaults")
    def seed_default_settings(payload: dict | None = None) -> dict:
        request_payload = payload or {}
        try:
            immich_user_id = _resolve_immich_user_id(request_payload)
            immich_user_id, review_album_resource_id, review_threshold = resolve_seed_inputs(
                immich_user_id=immich_user_id,
                review_album_resource_id=request_payload.get("reviewAlbumResourceId"),
                review_threshold=request_payload.get("reviewThreshold"),
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        seeded = seed_master_data(
            app.state.repository,
            profile_id=app.state.profile_id,
            immich_user_id=immich_user_id,
            review_album_resource_id=review_album_resource_id,
            review_threshold=review_threshold,
        )
        seeded["jobServiceReloaded"] = _reload_job_service()
        return seeded

    @app.get("/api/event-ledger")
    def event_ledger() -> dict:
        feedback_rows = app.state.repository.list_feedback_events(app.state.profile_id)
        trace_rows = app.state.repository.list_inference_traces(app.state.profile_id)
        action_rows = app.state.repository.list_action_execution_logs(app.state.profile_id)
        favorite_signal_rows = app.state.repository.list_favorite_signals(app.state.profile_id)
        trash_signal_rows = app.state.repository.list_trash_signals(app.state.profile_id)
        score_run_rows = app.state.repository.list_score_runs(app.state.profile_id)
        latest_score_run = app.state.repository.get_latest_completed_score_run(app.state.profile_id)
        score_result_rows = (
            app.state.repository.list_score_results(app.state.profile_id, score_run_id=str(latest_score_run["id"]))
            if latest_score_run is not None
            else []
        )
        exclusion_rows = app.state.repository.list_apply_exclusion_assets(app.state.profile_id)
        return {
            "feedbackEvents": [dict(row) for row in feedback_rows],
            "inferenceTraces": [dict(row) for row in trace_rows],
            "actionExecutionLogs": [dict(row) for row in action_rows],
            "favoriteSignals": [dict(row) for row in favorite_signal_rows],
            "trashSignals": [dict(row) for row in trash_signal_rows],
            "scoreRuns": [dict(row) for row in score_run_rows],
            "scoreResults": [dict(row) for row in score_result_rows],
            "applyExclusionAssets": [dict(row) for row in exclusion_rows],
        }

    @app.post("/api/apply-exclusions/{asset_id}/clear")
    def clear_apply_exclusion(asset_id: str) -> dict:
        normalized_asset_id = str(asset_id).strip()
        if not normalized_asset_id:
            raise HTTPException(status_code=400, detail="asset_id is required")

        cleared_count = app.state.repository.deactivate_apply_exclusion_asset(
            app.state.profile_id,
            normalized_asset_id,
        )
        return {
            "assetId": normalized_asset_id,
            "clearedCount": cleared_count,
            "activeAssetIds": sorted(app.state.repository.list_active_apply_exclusion_asset_ids(app.state.profile_id)),
        }

    return app
