from __future__ import annotations

import unittest

from smart_ranker.feature_pipeline import (
    AssetFeatureInput,
    FeatureAssembler,
    LabelResolver,
    LabelResolverConfig,
    MechanicalRule,
    PersonLabelConfig,
)
from smart_ranker.immich_client import AssetSnapshot


def make_asset(*, asset_id: str, people: tuple[str, ...], file_name: str, path: str) -> AssetSnapshot:
    return AssetSnapshot(
        id=asset_id,
        is_favorite=False,
        is_trashed=False,
        visibility="timeline",
        people=people,
        original_file_name=file_name,
        original_path=path,
        updated_at="2026-05-09T00:00:00Z",
        payload={"id": asset_id},
    )


class FeaturePipelineTest(unittest.TestCase):
    def test_label_resolver_combines_people_mechanical_rules_and_smart_labels(self) -> None:
        resolver = LabelResolver(
            LabelResolverConfig(
                person_labels=PersonLabelConfig(
                    family_person_ids=frozenset({"person-family"}),
                    child_person_ids=frozenset({"person-child"}),
                ),
                mechanical_rules=(
                    MechanicalRule(category_key="document", source="ocr_text", keywords=("invoice", "receipt")),
                    MechanicalRule(
                        category_key="screenshot",
                        source="file_name",
                        keywords=("screenshot", "スクリーンショット"),
                    ),
                ),
            )
        )

        asset_input = AssetFeatureInput(
            asset=make_asset(
                asset_id="asset-1",
                people=("person-child",),
                file_name="Screenshot_0001.png",
                path="/library/Screenshot_0001.png",
            ),
            embedding=[0.1, 0.2, 0.3],
            ocr_text="Invoice total: 1200",
            tag_names=("camera",),
            weak_smart_categories=("landscape",),
        )

        resolution = resolver.resolve(asset_input)

        self.assertEqual("child", resolution.selected_person_label)
        self.assertEqual(
            ("child", "document", "landscape", "person", "screenshot"),
            resolution.candidate_labels,
        )
        self.assertEqual(("landscape",), resolution.weak_smart_categories)

    def test_feature_assembler_builds_stable_matrix_with_other_fallback(self) -> None:
        config = LabelResolverConfig(
            person_labels=PersonLabelConfig(),
            mechanical_rules=(
                MechanicalRule(category_key="document", source="ocr_text", keywords=("invoice",)),
            ),
        )
        resolver = LabelResolver(config)
        assembler = FeatureAssembler(config.known_category_keys)

        first_input = AssetFeatureInput(
            asset=make_asset(
                asset_id="asset-1",
                people=(),
                file_name="IMG_0001.JPG",
                path="/photos/2026/IMG_0001.JPG",
            ),
            embedding=[0.1, 0.2],
            ocr_text=None,
            tag_names=(),
            weak_smart_categories=(),
        )
        second_input = AssetFeatureInput(
            asset=make_asset(
                asset_id="asset-2",
                people=("person-1",),
                file_name="invoice.jpg",
                path="/docs/invoice.jpg",
            ),
            embedding=[0.3, 0.4],
            ocr_text="invoice no.42",
            tag_names=("paper", "scan"),
            weak_smart_categories=("pet",),
        )

        matrix = assembler.build_matrix(
            [first_input, second_input],
            [resolver.resolve(first_input), resolver.resolve(second_input)],
        )

        self.assertEqual(2, len(matrix.rows))
        self.assertIn("embedding_0", matrix.feature_names)
        self.assertIn("meta_person_count", matrix.feature_names)
        self.assertIn("label_other", matrix.feature_names)
        self.assertIn("label_pet", matrix.feature_names)

        first_row = matrix.rows[0]
        second_row = matrix.rows[1]
        self.assertEqual(("other",), first_row.candidate_labels)
        self.assertEqual(("document", "person", "pet"), second_row.candidate_labels)
        self.assertEqual(len(matrix.feature_names), len(first_row.vector))
        self.assertEqual(len(matrix.feature_names), len(second_row.vector))


if __name__ == "__main__":
    unittest.main()