from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from smart_ranker.master_data import (
    load_master_data,
    load_runtime_settings,
    save_person_groups,
    seed_master_data,
)
from smart_ranker.storage import bootstrap_storage
from smart_ranker.storage.repository import StorageRepository


class MasterDataTest(unittest.TestCase):
    def test_seed_master_data_populates_default_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bootstrap_result = bootstrap_storage(state_dir=Path(temp_dir) / "state")
            repository = StorageRepository(bootstrap_result.paths.db_path)

            bundle = seed_master_data(
                repository,
                profile_id="profile-1",
                immich_user_id="immich-user-1",
                review_album_resource_id="album-1",
                review_threshold=0.2,
            )

            self.assertEqual(2, len(bundle["personGroups"]))
            self.assertEqual(8, len(bundle["categories"]))
            self.assertEqual(9, len(bundle["routingRules"]))
            self.assertEqual(1, len(bundle["policies"]))
            self.assertEqual(2, len(bundle["destinations"]))
            self.assertEqual(4, len(bundle["schedules"]))
            self.assertEqual({1000}, {item["batchSize"] for item in bundle["schedules"]})

            category_keys = {item["categoryKey"] for item in bundle["categories"]}
            self.assertIn("person", category_keys)
            self.assertIn("child", category_keys)
            self.assertIn("other", category_keys)

            runtime_settings = load_runtime_settings(
                repository,
                profile_id="profile-1",
            )
            self.assertEqual(0.2, runtime_settings.review_threshold)
            self.assertEqual("album-1", runtime_settings.review_album_resource_id)
            self.assertIn("landscape", runtime_settings.label_resolver_config.smart_search_category_keys)
            self.assertIn("pet", runtime_settings.label_resolver_config.smart_search_category_keys)
            self.assertEqual("other", runtime_settings.label_resolver_config.other_category_key)

            mechanical_keys = {rule.category_key for rule in runtime_settings.label_resolver_config.mechanical_rules}
            self.assertIn("document", mechanical_keys)
            self.assertIn("screenshot", mechanical_keys)

    def test_person_group_members_flow_into_runtime_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bootstrap_result = bootstrap_storage(state_dir=Path(temp_dir) / "state")
            repository = StorageRepository(bootstrap_result.paths.db_path)
            seed_master_data(
                repository,
                profile_id="profile-1",
                immich_user_id="immich-user-1",
            )

            save_person_groups(
                repository,
                profile_id="profile-1",
                immich_user_id="immich-user-1",
                groups=[
                    {
                        "groupKey": "family",
                        "displayName": "家族",
                        "groupType": "person_set",
                        "aliases": ["family"],
                        "enabled": True,
                        "members": [
                            {
                                "immichPersonId": "person-1",
                                "immichPersonName": "Alice",
                            }
                        ],
                    },
                    {
                        "groupKey": "child",
                        "displayName": "我が子",
                        "groupType": "person_set",
                        "aliases": ["child"],
                        "enabled": True,
                        "members": [
                            {
                                "immichPersonId": "person-2",
                                "immichPersonName": "Kid",
                            }
                        ],
                    },
                ],
            )

            runtime_settings = load_runtime_settings(
                repository,
                profile_id="profile-1",
            )
            self.assertEqual(
                frozenset({"person-1"}),
                runtime_settings.label_resolver_config.person_labels.family_person_ids,
            )
            self.assertEqual(
                frozenset({"person-2"}),
                runtime_settings.label_resolver_config.person_labels.child_person_ids,
            )

            bundle = load_master_data(repository, "profile-1")
            family_group = next(item for item in bundle["personGroups"] if item["groupKey"] == "family")
            child_group = next(item for item in bundle["personGroups"] if item["groupKey"] == "child")
            self.assertEqual("person-1", family_group["members"][0]["immichPersonId"])
            self.assertEqual("person-2", child_group["members"][0]["immichPersonId"])


if __name__ == "__main__":
    unittest.main()
