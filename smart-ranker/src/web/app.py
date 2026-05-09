from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from smart_ranker.storage import bootstrap_storage
from smart_ranker.storage.repository import StorageRepository
from smart_ranker.web.job_service import JobService


def create_app(
    *,
    state_dir: Path | str | None = None,
    profile_id: str = "default-profile",
    job_service: JobService | None = None,
) -> FastAPI:
    bootstrap_result = bootstrap_storage(state_dir=state_dir)
    repository = StorageRepository(bootstrap_result.paths.db_path)
    app = FastAPI(title="Smart Ranker")
    app.state.paths = bootstrap_result.paths
    app.state.repository = repository
    app.state.profile_id = profile_id
    app.state.job_service = job_service or JobService()

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.post("/api/jobs/{job_type}")
    def submit_job(job_type: str, payload: dict | None = None) -> JSONResponse:
        if job_type not in {"collect", "train", "score", "apply"}:
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

    @app.get("/api/event-ledger")
    def event_ledger() -> dict:
        feedback_rows = app.state.repository.list_feedback_events(app.state.profile_id)
        trace_rows = app.state.repository.list_inference_traces(app.state.profile_id)
        action_rows = app.state.repository.list_action_execution_logs(app.state.profile_id)
        return {
            "feedbackEvents": [dict(row) for row in feedback_rows],
            "inferenceTraces": [dict(row) for row in trace_rows],
            "actionExecutionLogs": [dict(row) for row in action_rows],
        }

    return app
