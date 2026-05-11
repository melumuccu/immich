from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from smart_ranker.immich_client import ActionResult, AssetSnapshot, BinaryResponseEnvelope, PersonSnapshot, SearchResult
from smart_ranker.master_data import load_runtime_settings
from smart_ranker.storage import bootstrap_storage
from smart_ranker.web.app import (
    LIVE_RELOAD_ACCESS_LOG_FILTER,
    UVICORN_ACCESS_LOGGER_NAME,
)
from smart_ranker.storage.repository import (
    ActionExecutionLogRecord,
    ApplyExclusionAssetRecord,
    FeedbackEventRecord,
    InferenceTraceRecord,
    ScoreResultRecord,
    ScoreRunRecord,
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
        self.calls: list[tuple[str, object, object]] = []

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> ActionResult:
        self.calls.append(("add_assets_to_album", album_id, asset_ids))
        return ActionResult(status_code=200, ok=True, payload={"albumId": album_id, "ids": asset_ids})

    def update_asset(self, asset_id: str, payload: dict[str, object]) -> ActionResult:
        self.calls.append(("update_asset", asset_id, payload))
        return ActionResult(status_code=200, ok=True, payload={"assetId": asset_id, **payload})

    def trash_assets(self, asset_ids: list[str], *, force: bool = False) -> ActionResult:
        self.calls.append(("trash_assets", list(asset_ids), {"force": force}))
        return ActionResult(status_code=200, ok=True, payload={"ids": list(asset_ids), "force": force})


class FakePeopleClient:
    def __init__(self) -> None:
        self.search_calls: list[tuple[str, bool, int | None]] = []
        self.list_calls: list[tuple[int, int, bool]] = []

    def search_people(
        self,
        name: str,
        *,
        with_hidden: bool = False,
        limit: int | None = None,
    ) -> list[PersonSnapshot]:
        self.search_calls.append((name, with_hidden, limit))
        return [
            PersonSnapshot(
                id="person-1",
                name="Kid",
                is_hidden=with_hidden,
                face_asset_id="face-1",
                payload={"id": "person-1"},
            )
        ]

    def list_people(self, *, page: int = 1, size: int = 500, with_hidden: bool = False) -> list[PersonSnapshot]:
        self.list_calls.append((page, size, with_hidden))
        return [
            PersonSnapshot(
                id="person-2",
                name="Family",
                is_hidden=with_hidden,
                face_asset_id=None,
                payload={"id": "person-2"},
            )
        ]


class FakeThumbnailAssetClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str | None]] = []

    def get_asset_thumbnail(
        self,
        asset_id: str,
        *,
        size: str | None = None,
        format: str | None = None,
    ) -> BinaryResponseEnvelope:
        self.calls.append((asset_id, size, format))
        return BinaryResponseEnvelope(
            status_code=200,
            payload=b"thumbnail-bytes",
            content_type="image/webp",
            cache_control="public, max-age=60",
            etag='"thumb-1"',
        )


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

    def test_manual_job_api_runs_learn_score_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bootstrap_result = bootstrap_storage(state_dir=Path(temp_dir) / "state")
            repository = StorageRepository(bootstrap_result.paths.db_path)
            asset_client = FakeAssetClient(
                [
                    SearchResult(
                        items=[make_asset(asset_id="person-positive", favorite=True, people=("person-1",))],
                        next_page=None,
                        has_next_page=False,
                        raw={},
                    ),
                    SearchResult(
                        items=[make_asset(asset_id="person-negative", trashed=True, people=("person-1",))],
                        next_page=None,
                        has_next_page=False,
                        raw={},
                    ),
                    SearchResult(
                        items=[
                            make_asset(asset_id="person-positive", favorite=True, people=("person-1",)),
                            make_asset(asset_id="person-negative", trashed=True, people=("person-1",)),
                            make_asset(asset_id="neutral-low"),
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
                        "neutral-low": [-1.8, -1.4],
                    }
                ),
                action_client=action_client,
                review_album_resource_id="album-1",
                review_threshold=0.5,
                now_factory=lambda: "2026-05-09T12:00:00Z",
            )
            app = create_app(
                state_dir=Path(temp_dir) / "state",
                profile_id="profile-1",
                job_service=job_service,
            )
            client = TestClient(app)

            learn_response = client.post("/api/jobs/learn", json={"trigger": "test"})
            score_response = client.post("/api/jobs/score", json={"trigger": "test"})
            apply_response = client.post("/api/jobs/apply", json={"trigger": "test"})

            self.assertEqual(202, learn_response.status_code)
            self.assertEqual(202, score_response.status_code)
            self.assertEqual(202, apply_response.status_code)

            learn_payload = learn_response.json()
            score_payload = score_response.json()
            apply_payload = apply_response.json()

            learn_status = client.get(f"/api/jobs/{learn_payload['jobRunId']}").json()
            score_status = client.get(f"/api/jobs/{score_payload['jobRunId']}").json()
            apply_status = client.get(f"/api/jobs/{apply_payload['jobRunId']}").json()

            self.assertEqual("completed", learn_status["status"])
            self.assertEqual(1, learn_status["result"]["favoriteSignalCount"])
            self.assertEqual(1, learn_status["result"]["trashSignalCount"])
            self.assertEqual(2, learn_status["result"]["trainingAssetCount"])
            self.assertIn("generic", learn_status["result"]["modelKeys"])
            self.assertIn("person", learn_status["result"]["modelKeys"])

            self.assertEqual("completed", score_status["status"])
            self.assertEqual(3, score_status["result"]["scoredAssetCount"])
            self.assertIn("scoreRunId", score_status["result"])

            self.assertEqual("completed", apply_status["status"])
            self.assertFalse(apply_status["result"]["dryRun"])
            self.assertEqual(1, apply_status["result"]["appliedCount"])
            self.assertEqual(["neutral-low"], apply_status["result"]["assetIds"])
            self.assertEqual(1, len(action_client.calls))
            self.assertEqual("trash_assets", action_client.calls[0][0])

            ledger = client.get("/api/event-ledger").json()
            self.assertEqual(1, len(ledger["favoriteSignals"]))
            self.assertEqual(1, len(ledger["trashSignals"]))
            self.assertEqual(1, len(ledger["scoreRuns"]))
            self.assertEqual(3, len(ledger["scoreResults"]))
            self.assertEqual(1, len(ledger["actionExecutionLogs"]))
            self.assertEqual(1, len(ledger["applyExclusionAssets"]))

    def test_manual_learn_uses_schedule_batch_size_for_signal_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bootstrap_result = bootstrap_storage(state_dir=Path(temp_dir) / "state")
            repository = StorageRepository(bootstrap_result.paths.db_path)
            repository.insert_profile(profile_id="profile-1", immich_user_id="immich-user-1")
            repository.upsert_execution_schedule(
                schedule_id="schedule-learn",
                profile_id="profile-1",
                job_type="learn",
                run_mode="manual",
                cron_expr=None,
                dry_run=False,
                batch_size=1,
                enabled=True,
            )
            asset_client = FakeAssetClient(
                [
                    SearchResult(
                        items=[make_asset(asset_id="person-positive", favorite=True, people=("person-1",))],
                        next_page=None,
                        has_next_page=False,
                        raw={},
                    ),
                    SearchResult(
                        items=[make_asset(asset_id="person-negative", trashed=True, people=("person-1",))],
                        next_page=None,
                        has_next_page=False,
                        raw={},
                    ),
                ]
            )
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
                action_client=FakeActionClient(),
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

            response = client.post("/api/jobs/learn", json={"trigger": "test"})
            status_payload = client.get(f"/api/jobs/{response.json()['jobRunId']}").json()

            self.assertEqual(1, status_payload["result"]["batchSize"])
            self.assertEqual(1, status_payload["result"]["favoriteSignalCount"])
            self.assertEqual(1, status_payload["result"]["trashSignalCount"])
            self.assertEqual({"isFavorite": True, "size": 1, "page": 1}, asset_client.search_metadata_calls[0])
            self.assertEqual({"isTrashed": True, "size": 1, "page": 1}, asset_client.search_metadata_calls[1])

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

                response = client.post("/api/jobs/learn", json={"trigger": "test"})

                self.assertEqual(202, response.status_code)
                payload = response.json()
                self.assertEqual("learn", payload["jobType"])
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
            repository.insert_score_run(
                ScoreRunRecord(
                    id="score-run-1",
                    profile_id="profile-1",
                    model_run_id="run-1",
                    trigger_type="manual",
                    status="completed",
                    scope={"jobType": "score"},
                    started_at="2026-05-09T12:01:30Z",
                    completed_at="2026-05-09T12:01:45Z",
                )
            )
            repository.insert_score_results(
                [
                    ScoreResultRecord(
                        id="score-result-1",
                        score_run_id="score-run-1",
                        profile_id="profile-1",
                        immich_asset_id="asset-1",
                        total_score=0.31,
                        rank_index=1,
                        category_scores={"generic": 0.31},
                        current_state={"isTrashed": False, "traceId": "trace-1"},
                        scored_at="2026-05-09T12:01:45Z",
                    )
                ]
            )
            repository.insert_apply_exclusion_asset(
                ApplyExclusionAssetRecord(
                    id="exclude-1",
                    profile_id="profile-1",
                    immich_asset_id="asset-1",
                    score_run_id="score-run-1",
                    action_log_id="log-1",
                    reason="auto-trash",
                    excluded_at="2026-05-09T12:02:00Z",
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
            settings_html = client.get("/settings")
            score_review_html = client.get("/score-review")
            self.assertEqual(200, html.status_code)
            self.assertEqual(200, settings_html.status_code)
            self.assertEqual(200, score_review_html.status_code)
            self.assertIn("Person Group", html.text)
            self.assertIn("Event Ledger", html.text)
            self.assertIn("score review", html.text)
            self.assertIn("settings", html.text)
            self.assertIn("Person Group", settings_html.text)
            self.assertIn("score review", score_review_html.text)

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
            self.assertEqual(1, len(ledger["scoreRuns"]))
            self.assertEqual(1, len(ledger["scoreResults"]))
            self.assertEqual(1, len(ledger["applyExclusionAssets"]))

    def test_score_review_api_paginates_and_thumbnail_proxy_uses_injected_client(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            bootstrap_result = bootstrap_storage(state_dir=state_dir)
            repository = StorageRepository(bootstrap_result.paths.db_path)
            repository.insert_profile(profile_id="profile-1", immich_user_id="immich-user-1")
            repository.insert_score_run(
                ScoreRunRecord(
                    id="score-run-1",
                    profile_id="profile-1",
                    model_run_id="run-1",
                    trigger_type="manual",
                    status="completed",
                    scope={"jobType": "score"},
                    started_at="2026-05-09T12:01:30Z",
                    completed_at="2026-05-09T12:01:45Z",
                )
            )
            repository.insert_score_results(
                [
                    ScoreResultRecord(
                        id=f"score-result-{index:03d}",
                        score_run_id="score-run-1",
                        profile_id="profile-1",
                        immich_asset_id=f"asset-{index:03d}",
                        total_score=index / 1000,
                        rank_index=index,
                        category_scores={"generic": index / 1000},
                        current_state={
                            "originalFileName": f"IMG_{index:03d}.JPG",
                            "originalPath": f"/library/2026/IMG_{index:03d}.JPG",
                            "isFavorite": index % 2 == 0,
                            "isTrashed": False,
                        },
                        scored_at="2026-05-09T12:01:45Z",
                    )
                    for index in range(1, 106)
                ]
            )

            app = create_app(state_dir=state_dir, profile_id="profile-1")
            thumbnail_client = FakeThumbnailAssetClient()
            app.state.asset_client = thumbnail_client
            client = TestClient(app)

            html = client.get("/score-review")
            page_one = client.get("/api/score-review")
            page_two = client.get("/api/score-review", params={"page": 2, "scoreRunId": "score-run-1"})
            thumbnail = client.get("/api/assets/asset-010/thumbnail")

            self.assertEqual(200, html.status_code)
            self.assertIn("score review", html.text)

            self.assertEqual(200, page_one.status_code)
            page_one_payload = page_one.json()
            self.assertEqual("score-run-1", page_one_payload["scoreRunId"])
            self.assertEqual(100, page_one_payload["pageSize"])
            self.assertEqual(105, page_one_payload["totalItems"])
            self.assertEqual(2, page_one_payload["totalPages"])
            self.assertEqual(100, len(page_one_payload["items"]))
            self.assertEqual("asset-001", page_one_payload["items"][0]["immichAssetId"])
            self.assertEqual("/api/assets/asset-001/thumbnail", page_one_payload["items"][0]["thumbnailUrl"])

            self.assertEqual(200, page_two.status_code)
            page_two_payload = page_two.json()
            self.assertEqual(2, page_two_payload["page"])
            self.assertEqual(5, len(page_two_payload["items"]))
            self.assertEqual("asset-101", page_two_payload["items"][0]["immichAssetId"])

            self.assertEqual(200, thumbnail.status_code)
            self.assertEqual(b"thumbnail-bytes", thumbnail.content)
            self.assertEqual("image/webp", thumbnail.headers["content-type"])
            self.assertEqual("public, max-age=60", thumbnail.headers["cache-control"])
            self.assertEqual([("asset-010", None, None)], thumbnail_client.calls)

    def test_jobs_models_endpoint_includes_runtime_reset_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bootstrap_result = bootstrap_storage(state_dir=Path(temp_dir) / "state")
            bootstrap_result.paths.runtime_reset_token_path().write_text("reset-token-1", encoding="utf-8")

            app = create_app(state_dir=Path(temp_dir) / "state", profile_id="profile-1")
            client = TestClient(app)

            payload = client.get("/api/settings/jobs-models").json()

            self.assertEqual([], payload["models"])
            self.assertEqual("reset-token-1", payload["runtimeResetToken"])

    def test_live_reload_endpoint_is_dev_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            default_app = create_app(state_dir=Path(temp_dir) / "state", profile_id="profile-1")
            default_client = TestClient(default_app)

            disabled_payload = default_client.get("/api/dev/live-reload").json()
            self.assertFalse(disabled_payload["enabled"])
            self.assertIsNone(disabled_payload["token"])

            with patch.dict("os.environ", {"SMART_RANKER_LIVE_RELOAD": "1"}, clear=False):
                live_reload_app = create_app(state_dir=Path(temp_dir) / "state-live", profile_id="profile-1")

            live_reload_client = TestClient(live_reload_app)
            enabled_payload = live_reload_client.get("/api/dev/live-reload").json()

            self.assertTrue(enabled_payload["enabled"])
            self.assertGreater(enabled_payload["intervalMs"], 0)
            self.assertTrue(enabled_payload["token"])

    def test_live_reload_filter_is_attached_only_when_enabled(self) -> None:
        access_logger = logging.getLogger(UVICORN_ACCESS_LOGGER_NAME)
        access_logger.removeFilter(LIVE_RELOAD_ACCESS_LOG_FILTER)

        with tempfile.TemporaryDirectory() as temp_dir:
            create_app(state_dir=Path(temp_dir) / "state-disabled", profile_id="profile-1")
            self.assertNotIn(LIVE_RELOAD_ACCESS_LOG_FILTER, access_logger.filters)

            with patch.dict("os.environ", {"SMART_RANKER_LIVE_RELOAD": "1"}, clear=False):
                create_app(state_dir=Path(temp_dir) / "state-enabled", profile_id="profile-1")

            self.assertIn(LIVE_RELOAD_ACCESS_LOG_FILTER, access_logger.filters)

        access_logger.removeFilter(LIVE_RELOAD_ACCESS_LOG_FILTER)

    def test_people_search_endpoint_uses_injected_people_client(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            people_client = FakePeopleClient()
            app = create_app(
                state_dir=Path(temp_dir) / "state",
                profile_id="profile-1",
                people_client=people_client,
            )
            client = TestClient(app)

            search_response = client.get("/api/immich/people", params={"q": "Kid", "with_hidden": True, "limit": 10})
            list_response = client.get("/api/immich/people", params={"limit": 5})

            self.assertEqual(200, search_response.status_code)
            self.assertEqual("person-1", search_response.json()["items"][0]["id"])
            self.assertEqual(("Kid", True, 10), people_client.search_calls[0])

            self.assertEqual(200, list_response.status_code)
            self.assertEqual("person-2", list_response.json()["items"][0]["id"])
            self.assertEqual((1, 5, False), people_client.list_calls[0])

    def test_settings_endpoints_can_seed_and_update_master_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            bootstrap_result = bootstrap_storage(state_dir=state_dir)
            repository = StorageRepository(bootstrap_result.paths.db_path)
            repository.insert_profile(profile_id="profile-1", immich_user_id="immich-user-1")

            with patch.dict(
                "os.environ",
                {
                    "SMART_RANKER_IMMICH_BASE_URL": "http://127.0.0.1:2283",
                    "SMART_RANKER_IMMICH_API_KEY": "dummy",
                    "SMART_RANKER_IMMICH_DB_DSN": "postgresql://immich:password@127.0.0.1:5432/immich",
                    "SMART_RANKER_IMMICH_USER_ID": "immich-user-1",
                },
                clear=False,
            ):
                app = create_app(state_dir=state_dir, profile_id="profile-1")

            client = TestClient(app)

            seed_response = client.post(
                "/api/settings/seed-defaults",
                json={"reviewAlbumResourceId": "album-9", "reviewThreshold": 0.25},
            )
            self.assertEqual(200, seed_response.status_code)
            seed_payload = seed_response.json()
            self.assertEqual(2, len(seed_payload["personGroups"]))
            self.assertEqual(8, len(seed_payload["categories"]))
            self.assertEqual(9, len(seed_payload["routingRules"]))
            self.assertEqual(3, len(seed_payload["schedules"]))

            groups_payload = client.get("/api/settings/person-groups").json()
            groups_payload["personGroups"][0]["members"] = [
                {"immichPersonId": "person-1", "immichPersonName": "Alice"}
            ]
            groups_response = client.put("/api/settings/person-groups", json=groups_payload)
            self.assertEqual(200, groups_response.status_code)
            self.assertEqual(
                "person-1",
                groups_response.json()["personGroups"][0]["members"][0]["immichPersonId"],
            )

            policies_payload = client.get("/api/settings/policies").json()
            policies_payload["policies"][0]["display"]["reviewThreshold"] = 0.33
            policies_response = client.put("/api/settings/policies", json=policies_payload)
            self.assertEqual(200, policies_response.status_code)

            jobs_models = client.get("/api/settings/jobs-models").json()
            self.assertEqual(3, len(jobs_models["schedules"]))

            runtime_settings = load_runtime_settings(repository, profile_id="profile-1")
            self.assertEqual(0.33, runtime_settings.review_threshold)
            self.assertEqual(
                frozenset({"person-1"}),
                runtime_settings.label_resolver_config.person_labels.family_person_ids,
            )


if __name__ == "__main__":
    unittest.main()
