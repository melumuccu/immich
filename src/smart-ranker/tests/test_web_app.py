from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from smart_ranker.storage import bootstrap_storage
from smart_ranker.storage.repository import (
    ActionExecutionLogRecord,
    FeedbackEventRecord,
    InferenceTraceRecord,
    StorageRepository,
)
from smart_ranker.web.app import create_app


class WebAppTest(unittest.TestCase):
    def test_manual_job_api_returns_job_run_id_and_job_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(state_dir=Path(temp_dir) / "state", profile_id="profile-1")
            client = TestClient(app)

            response = client.post("/api/jobs/train", json={"trigger": "test"})

            self.assertEqual(202, response.status_code)
            payload = response.json()
            self.assertEqual("train", payload["jobType"])
            self.assertIn("jobRunId", payload)

            status_response = client.get(f"/api/jobs/{payload['jobRunId']}")
            self.assertEqual(200, status_response.status_code)
            self.assertEqual(payload["jobRunId"], status_response.json()["jobRunId"])

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
