from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from smart_ranker.storage.bootstrap import bootstrap_storage


EXPECTED_TABLES = {
    "schema_migrations",
    "ranker_profile",
    "person_group",
    "person_group_member",
    "category",
    "routing_rule",
    "training_signal_rule",
    "category_score_policy",
    "action_destination",
    "action_policy",
    "action_policy_step",
    "execution_schedule",
    "collector_cursor",
    "feedback_event",
    "inference_trace",
    "action_execution_log",
}


class StorageBootstrapTest(unittest.TestCase):
    def test_bootstrap_storage_creates_runtime_dirs_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir) / "state"

            first_result = bootstrap_storage(state_dir=state_dir)

            self.assertTrue(first_result.paths.db_dir.is_dir())
            self.assertTrue(first_result.paths.models_dir.is_dir())
            self.assertTrue(first_result.paths.snapshots_dir.is_dir())
            self.assertTrue(first_result.paths.logs_dir.is_dir())
            self.assertTrue(first_result.paths.db_path.is_file())
            self.assertEqual(
                ["0001_initial_storage.sql", "0002_collect_batch_cursor.sql"],
                first_result.migration_result.applied_migrations,
            )

            with sqlite3.connect(first_result.paths.db_path) as connection:
                table_rows = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
                table_names = {row[0] for row in table_rows.fetchall()}

            self.assertTrue(EXPECTED_TABLES.issubset(table_names))

            second_result = bootstrap_storage(state_dir=state_dir)
            self.assertEqual([], second_result.migration_result.applied_migrations)
            self.assertEqual(
                ["0001_initial_storage.sql", "0002_collect_batch_cursor.sql"],
                second_result.migration_result.skipped_migrations,
            )


if __name__ == "__main__":
    unittest.main()
