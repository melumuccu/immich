from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from smart_ranker.cli import main
from smart_ranker.master_data import seed_master_data
from smart_ranker.storage import bootstrap_storage
from smart_ranker.storage.repository import (
    ActionExecutionLogRecord,
    ApplyExclusionAssetRecord,
    CollectorCursorRecord,
    FavoriteSignalRecord,
    FeedbackEventRecord,
    InferenceTraceRecord,
    ScoreResultRecord,
    ScoreRunRecord,
    StorageRepository,
    TrashSignalRecord,
)


class CliTest(unittest.TestCase):
    def test_reset_runtime_data_clears_job_outputs_and_keeps_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"
            bootstrap_result = bootstrap_storage(state_dir=state_dir)
            repository = StorageRepository(bootstrap_result.paths.db_path)
            seed_master_data(
                repository,
                profile_id="profile-1",
                immich_user_id="immich-user-1",
                review_album_resource_id="album-1",
                review_threshold=0.25,
            )

            person_group_count = len(repository.list_person_groups("profile-1"))
            category_count = len(repository.list_categories("profile-1"))
            action_policy_count = len(repository.list_action_policies("profile-1"))
            action_destination_count = len(repository.list_action_destinations("profile-1"))
            execution_schedule_count = len(repository.list_execution_schedules("profile-1"))

            action_policy_id = str(repository.list_action_policies("profile-1")[0]["id"])
            destination_id = str(repository.list_action_destinations("profile-1")[0]["id"])

            repository.upsert_collector_cursor(
                CollectorCursorRecord(
                    id="cursor-1",
                    profile_id="profile-1",
                    collector_key="asset-diff",
                    updated_after="2026-05-10T00:00:00Z",
                    trashed_after="2026-05-10T00:00:00Z",
                    last_succeeded_at="2026-05-10T00:00:00Z",
                    last_attempted_at="2026-05-10T00:00:00Z",
                    last_run_id="run-1",
                )
            )
            repository.insert_feedback_event(
                FeedbackEventRecord(
                    id="feedback-1",
                    profile_id="profile-1",
                    category_id=None,
                    source_trace_id=None,
                    immich_asset_id="asset-1",
                    feedback_type="delete_candidate_rescued",
                    previous_score=0.1,
                    label_value=1.0,
                    sample_weight=2.0,
                    metadata={"source": "test"},
                    note="kept",
                    occurred_at="2026-05-10T00:00:01Z",
                )
            )
            repository.insert_inference_trace(
                InferenceTraceRecord(
                    id="trace-1",
                    profile_id="profile-1",
                    immich_asset_id="asset-1",
                    trigger_type="manual",
                    execution_mode="manual",
                    candidate_categories=["person"],
                    score={"person": 0.95},
                    final_score=0.95,
                    threshold_snapshot={"review_threshold": 0.25},
                    protected=False,
                    occurred_at="2026-05-10T00:00:02Z",
                )
            )
            repository.insert_action_execution_log(
                ActionExecutionLogRecord(
                    id="action-1",
                    profile_id="profile-1",
                    inference_trace_id="trace-1",
                    action_policy_id=action_policy_id,
                    destination_id=destination_id,
                    immich_asset_id="asset-1",
                    action_type="add_to_album",
                    execution_mode="manual",
                    dry_run=False,
                    status="executed",
                    request={"albumId": "album-1"},
                    response={"ok": True},
                    error_message=None,
                    executed_at="2026-05-10T00:00:03Z",
                )
            )
            repository.upsert_favorite_signal(
                FavoriteSignalRecord(
                    id="favorite-1",
                    profile_id="profile-1",
                    immich_asset_id="asset-favorite",
                    first_seen_at="2026-05-10T00:00:00Z",
                    last_seen_at="2026-05-10T00:00:00Z",
                    cleared_at=None,
                    metadata={"id": "asset-favorite"},
                )
            )
            repository.upsert_trash_signal(
                TrashSignalRecord(
                    id="trash-1",
                    profile_id="profile-1",
                    immich_asset_id="asset-trash",
                    first_seen_at="2026-05-10T00:00:00Z",
                    last_seen_at="2026-05-10T00:00:00Z",
                    restored_at=None,
                    metadata={"id": "asset-trash"},
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
                    started_at="2026-05-10T00:00:04Z",
                    completed_at="2026-05-10T00:00:05Z",
                )
            )
            repository.insert_score_results(
                [
                    ScoreResultRecord(
                        id="score-result-1",
                        score_run_id="score-run-1",
                        profile_id="profile-1",
                        immich_asset_id="asset-1",
                        total_score=0.12,
                        rank_index=1,
                        category_scores={"generic": 0.12},
                        current_state={"isTrashed": False},
                        scored_at="2026-05-10T00:00:05Z",
                    )
                ]
            )
            repository.insert_apply_exclusion_asset(
                ApplyExclusionAssetRecord(
                    id="exclude-1",
                    profile_id="profile-1",
                    immich_asset_id="asset-1",
                    score_run_id="score-run-1",
                    action_log_id="action-1",
                    reason="auto-trash",
                    excluded_at="2026-05-10T00:00:06Z",
                )
            )

            model_dir = bootstrap_result.paths.models_dir / "run-1"
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "generic.pkl").write_bytes(b"model")
            (bootstrap_result.paths.snapshots_dir / "train-run-1.json").write_text("{}", encoding="utf-8")
            (bootstrap_result.paths.logs_dir / "app.log").write_text("keep", encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["reset-runtime-data", "--state-dir", str(state_dir)])

            self.assertEqual(0, exit_code)
            self.assertEqual(person_group_count, len(repository.list_person_groups("profile-1")))
            self.assertEqual(category_count, len(repository.list_categories("profile-1")))
            self.assertEqual(action_policy_count, len(repository.list_action_policies("profile-1")))
            self.assertEqual(action_destination_count, len(repository.list_action_destinations("profile-1")))
            self.assertEqual(execution_schedule_count, len(repository.list_execution_schedules("profile-1")))

            self.assertIsNone(repository.get_collector_cursor("profile-1", "asset-diff"))
            self.assertEqual([], repository.list_feedback_events("profile-1"))
            self.assertEqual([], repository.list_inference_traces("profile-1"))
            self.assertEqual([], repository.list_action_execution_logs("profile-1"))
            self.assertEqual([], repository.list_favorite_signals("profile-1"))
            self.assertEqual([], repository.list_trash_signals("profile-1"))
            self.assertEqual([], repository.list_apply_exclusion_assets("profile-1"))
            self.assertEqual([], repository.list_score_runs("profile-1"))

            self.assertEqual([], list(bootstrap_result.paths.models_dir.iterdir()))
            self.assertEqual([], list(bootstrap_result.paths.snapshots_dir.iterdir()))
            self.assertTrue((bootstrap_result.paths.logs_dir / "app.log").exists())
            self.assertTrue(bootstrap_result.paths.runtime_reset_token_path().is_file())
            self.assertTrue(bootstrap_result.paths.runtime_reset_token_path().read_text(encoding="utf-8").strip())

            stdout = output.getvalue()
            self.assertIn("deleted_collector_cursor=1", stdout)
            self.assertIn("deleted_feedback_event=1", stdout)
            self.assertIn("deleted_inference_trace=1", stdout)
            self.assertIn("deleted_action_execution_log=1", stdout)
            self.assertIn("deleted_favorite_signal=1", stdout)
            self.assertIn("deleted_trash_signal=1", stdout)
            self.assertIn("deleted_apply_exclusion_asset=1", stdout)
            self.assertIn("deleted_score_result=1", stdout)
            self.assertIn("deleted_score_run=1", stdout)
            self.assertIn("cleared_models=1", stdout)
            self.assertIn("cleared_snapshots=1", stdout)
            self.assertIn("runtime_reset_token=", stdout)


if __name__ == "__main__":
    unittest.main()
