from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from smart_ranker.immich_client import ActionResult, AssetSnapshot, SearchResult
from smart_ranker.storage import bootstrap_storage
from smart_ranker.storage.repository import (
    ActionExecutionLogRecord,
    FeedbackEventRecord,
    InferenceTraceRecord,
    StorageRepository,
)
from smart_ranker.web.app import create_app
from smart_ranker.web.job_service import build_job_service


class FakeAssetClient:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.search_metadata_calls: list[dict[str, object]] = []

    def search_metadata(self, payload: dict[str, object]) -> SearchResult:
        self.search_metadata_calls.append(dict(payload))
        return self.responses.pop(0)


class FakeEmbeddingReader:
    def __init__(self, embeddings_by_asset_id: dict[str, list[float]]) -> None:
        self.embeddings_by_asset_id = embeddings_by_asset_id

    def fetch_embeddings(self, asset_ids) -> dict[str, list[float]]:
        return {
            asset_id: list(self.embeddings_by_asset_id[asset_id])
            for asset_id in asset_ids
            if asset_id in self.embeddings_by_asset_id
        }


class FakeActionClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object] | list[str]]] = []

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> ActionResult:
        self.calls.append(("add_assets_to_album", album_id, asset_ids))
        return ActionResult(status_code=200, ok=True, payload={"albumId": album_id, "ids": asset_ids})

    def update_asset(self, asset_id: str, payload: dict[str, object]) -> ActionResult:
        self.calls.append(("update_asset", asset_id, payload))
        return ActionResult(status_code=200, ok=True, payload={"assetId": asset_id, **payload})


def make_asset(
    *,
    asset_id: str,
    favorite: bool = False,
    trashed: bool = False,
    visibility: str = "timeline",
    people: tuple[str, ...] = (),
) -> AssetSnapshot:
    return AssetSnapshot(
        id=asset_id,
        is_favorite=favorite,
        is_trashed=trashed,
        visibility=visibility,
        people=people,
        original_file_name=f"{asset_id}.jpg",
        original_path=f"/library/{asset_id}.jpg",
        updated_at="2026-05-09T00:00:00Z",
        payload={"id": asset_id},
    )


class WebAppTest(unittest.TestCase):
    def test_app_factory_does_not_connect_to_immich_db_on_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                "os.environ",
                {
                    "SMART_RANKER_IMMICH_BASE_URL": "http://127.0.0.1:2283",
                    "SMART_RANKER_IMMICH_API_KEY": "dummy",
                    "SMART_RANKER_IMMICH_DB_DSN": "postgresql://immich:password@127.0.0.1:5432/immich",
                    "SMART_RANKER_IMMICH_USER_ID": "user-1",
                },
                clear=False,
            ):
                with patch(
                    "smart_ranker.immich_db_reader.psycopg.connect",
                    side_effect=AssertionError("startup must not connect to Immich DB"),
                ):
                    app = create_app(state_dir=Path(temp_dir) / "state", profile_id="profile-1")

            client = TestClient(app)
            response = client.get("/")

            self.assertEqual(200, response.status_code)

    def test_manual_job_api_runs_collect_train_score_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bootstrap_result = bootstrap_storage(state_dir=Path(temp_dir) / "state")
            repository = StorageRepository(bootstrap_result.paths.db_path)
            asset_client = FakeAssetClient(
                [
                    SearchResult(
                        items=[
                            make_asset(asset_id="person-positive", favorite=True, people=("person-1",)),
                            make_asset(asset_id="person-negative", trashed=True, people=("person-1",)),
                        ],
                        next_page=None,
                        has_next_page=False,
                        raw={},
                    )
                ]
            )
            action_client = FakeActionClient()
            job_service = build_job_service(
                storage_paths=bootstrap_result.paths,
                repository=repository,
                profile_id="profile-1",
                immich_user_id="immich-user-1",
                asset_client=asset_client,
                embedding_reader=FakeEmbeddingReader(
                    {
                        "person-positive": [2.0, 1.5],
                        "person-negative": [-2.0, -1.5],
                    }
                ),
                action_client=action_client,
                review_album_resource_id="album-1",
                review_threshold=1.1,
                now_factory=lambda: "2026-05-09T12:00:00Z",
            )
            app = create_app(
                state_dir=Path(temp_dir) / "state",
                profile_id="profile-1",
                job_service=job_service,
            )
            client = TestClient(app)

            collect_response = client.post("/api/jobs/collect", json={"trigger": "test"})
            train_response = client.post("/api/jobs/train", json={"trigger": "test"})
            score_response = client.post("/api/jobs/score", json={"trigger": "test"})
            apply_response = client.post("/api/jobs/apply", json={"trigger": "test"})

            self.assertEqual(202, collect_response.status_code)
            self.assertEqual(202, train_response.status_code)
            self.assertEqual(202, score_response.status_code)
            self.assertEqual(202, apply_response.status_code)

            collect_payload = collect_response.json()
            train_payload = train_response.json()
            score_payload = score_response.json()
            apply_payload = apply_response.json()

            collect_status = client.get(f"/api/jobs/{collect_payload['jobRunId']}").json()
            train_status = client.get(f"/api/jobs/{train_payload['jobRunId']}").json()
            score_status = client.get(f"/api/jobs/{score_payload['jobRunId']}").json()
            apply_status = client.get(f"/api/jobs/{apply_payload['jobRunId']}").json()

            self.assertEqual("completed", collect_status["status"])
            self.assertEqual(2, collect_status["result"]["assetCount"])
            self.assertEqual(2, collect_status["result"]["featureInputCount"])

            self.assertEqual("completed", train_status["status"])
            self.assertIn("generic", train_status["result"]["modelKeys"])
            self.assertIn("person", train_status["result"]["modelKeys"])

            self.assertEqual("completed", score_status["status"])
            self.assertTrue(score_status["result"]["dryRun"])
            self.assertEqual(1, score_status["result"]["traceCount"])

            self.assertEqual("completed", apply_status["status"])
            self.assertFalse(apply_status["result"]["dryRun"])
            self.assertEqual(1, apply_status["result"]["traceCount"])
            self.assertEqual(2, len(action_client.calls))

            ledger = client.get("/api/event-ledger").json()
            self.assertEqual(2, len(ledger["inferenceTraces"]))
            self.assertEqual(4, len(ledger["actionExecutionLogs"]))

    def test_manual_job_api_reports_configuration_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                "os.environ",
                {
                    "SMART_RANKER_IMMICH_BASE_URL": "",
                    "SMART_RANKER_IMMICH_API_KEY": "",
                    "SMART_RANKER_IMMICH_DB_DSN": "",
                    "SMART_RANKER_IMMICH_USER_ID": "",
                },
                clear=False,
            ):
                app = create_app(state_dir=Path(temp_dir) / "state", profile_id="profile-1")
                client = TestClient(app)

                response = client.post("/api/jobs/train", json={"trigger": "test"})

                self.assertEqual(202, response.status_code)
                payload = response.json()
                self.assertEqual("train", payload["jobType"])
                self.assertIn("jobRunId", payload)

                status_response = client.get(f"/api/jobs/{payload['jobRunId']}")
                self.assertEqual(200, status_response.status_code)
                status_payload = status_response.json()
                self.assertEqual(payload["jobRunId"], status_payload["jobRunId"])
                self.assertEqual("failed", status_payload["status"])
                self.assertEqual("JobConfigurationError", status_payload["result"]["errorType"])

    def test_console_endpoints_and_html_are_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bootstrap_result = bootstrap_storage(state_dir=Path(temp_dir) / "state")
            repository = StorageRepository(bootstrap_result.paths.db_path)
            repository.insert_profile(profile_id="profile-1", immich_user_id="immich-user-1")
            repository.insert_person_group(
                group_id="group-1",
                profile_id="profile-1",
                group_key="family",
                display_name="Family",
                group_type="person",
            )
            repository.insert_category(
                category_id="category-1",
                profile_id="profile-1",
                category_key="document",
                display_name="Document",
                category_type="core",
                media_scope="all",
            )
            repository.insert_action_policy(
                policy_id="policy-1",
                profile_id="profile-1",
                policy_key="review",
                display_name="Review Policy",
                execution_mode="manual",
            )
            repository.insert_action_destination(
                destination_id="dest-1",
                profile_id="profile-1",
                destination_key="review-album",
                destination_type="album",
                immich_resource_id="album-1",
            )
            repository.insert_inference_trace(
                InferenceTraceRecord(
                    id="trace-1",
                    profile_id="profile-1",
                    immich_asset_id="asset-1",
                    trigger_type="manual",
                    execution_mode="manual",
                    candidate_categories=["document"],
                    score={"generic": 0.31},
                    final_score=0.31,
                    threshold_snapshot={"review_threshold": 0.2},
                    protected=False,
                    occurred_at="2026-05-09T12:00:00Z",
                )
            )
            repository.insert_feedback_event(
                FeedbackEventRecord(
                    id="feedback-1",
                    profile_id="profile-1",
                    immich_asset_id="asset-1",
                    feedback_type="delete_candidate_rescued",
                    label_value=1.0,
                    sample_weight=0.5,
                    occurred_at="2026-05-09T12:01:00Z",
                )
            )
            repository.insert_action_execution_log(
                ActionExecutionLogRecord(
                    id="log-1",
                    profile_id="profile-1",
                    inference_trace_id="trace-1",
                    action_policy_id="policy-1",
                    destination_id="dest-1",
                    immich_asset_id="asset-1",
                    action_type="add_to_album",
                    execution_mode="manual",
                    dry_run=True,
                    status="planned",
                    request={"albumId": "album-1"},
                    response={},
                    error_message=None,
                    executed_at="2026-05-09T12:02:00Z",
                )
            )

            snapshot_path = bootstrap_result.paths.snapshots_dir / "train-run-1.json"
            snapshot_path.write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "trained_at": "2026-05-09T12:03:00Z",
                        "models": [{"model_key": "generic", "artifact_path": "models/run-1/generic.pkl"}],
                    }
                ),
                encoding="utf-8",
            )

            app = create_app(state_dir=Path(temp_dir) / "state", profile_id="profile-1")
            client = TestClient(app)

            html = client.get("/")
            self.assertEqual(200, html.status_code)
            self.assertIn("Person Group", html.text)
            self.assertIn("Event Ledger", html.text)

            person_groups = client.get("/api/person-groups").json()
            categories = client.get("/api/categories").json()
            policies = client.get("/api/policies").json()
            models = client.get("/api/models").json()
            ledger = client.get("/api/event-ledger").json()

            self.assertEqual("Family", person_groups[0]["display_name"])
            self.assertEqual("document", categories[0]["category_key"])
            self.assertEqual("review", policies[0]["policy_key"])
            self.assertEqual("run-1", models[0]["runId"])
            self.assertEqual(1, len(ledger["feedbackEvents"]))
            self.assertEqual(1, len(ledger["inferenceTraces"]))
            self.assertEqual(1, len(ledger["actionExecutionLogs"]))


if __name__ == "__main__":
    unittest.main()
