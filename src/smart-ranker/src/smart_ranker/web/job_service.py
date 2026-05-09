from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
        result = handler(payload or {}) if handler is not None else {"accepted": True}
        job_run = JobRun(
            id=job_id,
            job_type=job_type,
            status="completed",
            submitted_at=submitted_at,
            payload=payload or {},
            result=result,
        )
        self._jobs[job_id] = job_run
        return job_run

    def get(self, job_id: str) -> JobRun | None:
        return self._jobs.get(job_id)