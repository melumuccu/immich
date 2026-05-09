from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from smart_ranker.immich_client import AssetSnapshot


def normalize_text(value: str | None) -> str:
    return (value or "").casefold()


@dataclass(frozen=True)
class PersonLabelConfig:
    person_category_key: str = "person"
    family_category_key: str = "family"
    child_category_key: str = "child"
    family_person_ids: frozenset[str] = field(default_factory=frozenset)
    child_person_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class MechanicalRule:
    category_key: str
    source: str
    keywords: tuple[str, ...]

    def matches(self, asset_input: "AssetFeatureInput") -> bool:
        haystack = asset_input.source_text(self.source)
        if not haystack:
            return False
        return any(keyword.casefold() in haystack for keyword in self.keywords)


@dataclass(frozen=True)
class LabelResolverConfig:
    person_labels: PersonLabelConfig = field(default_factory=PersonLabelConfig)
    mechanical_rules: tuple[MechanicalRule, ...] = ()
    smart_search_category_keys: tuple[str, ...] = ("landscape", "pet")
    other_category_key: str = "other"

    @property
    def known_category_keys(self) -> tuple[str, ...]:
        ordered: list[str] = [
            self.person_labels.person_category_key,
            self.person_labels.family_category_key,
            self.person_labels.child_category_key,
        ]
        ordered.extend(rule.category_key for rule in self.mechanical_rules)
        ordered.extend(self.smart_search_category_keys)
        ordered.append(self.other_category_key)

        unique_keys: list[str] = []
        for key in ordered:
            if key not in unique_keys:
                unique_keys.append(key)
        return tuple(unique_keys)


@dataclass(frozen=True)
class AssetFeatureInput:
    asset: AssetSnapshot
    embedding: Sequence[float]
    ocr_text: str | None = None
    tag_names: tuple[str, ...] = ()
    weak_smart_categories: tuple[str, ...] = ()

    def source_text(self, source: str) -> str:
        normalized_source = source.casefold()
        if normalized_source == "ocr_text":
            return normalize_text(self.ocr_text)
        if normalized_source == "file_name":
            return normalize_text(self.asset.original_file_name)
        if normalized_source == "original_path":
            return normalize_text(self.asset.original_path)
        if normalized_source == "tag_names":
            return "\n".join(tag.casefold() for tag in self.tag_names)
        raise ValueError(f"Unsupported source: {source}")


@dataclass(frozen=True)
class LabelResolution:
    candidate_labels: tuple[str, ...]
    selected_person_label: str | None
    weak_smart_categories: tuple[str, ...]


@dataclass(frozen=True)
class FeatureRow:
    asset_id: str
    candidate_labels: tuple[str, ...]
    vector: list[float]


@dataclass(frozen=True)
class FeatureMatrix:
    feature_names: tuple[str, ...]
    rows: list[FeatureRow]


class LabelResolver:
    def __init__(self, config: LabelResolverConfig) -> None:
        self.config = config

    def resolve(self, asset_input: AssetFeatureInput) -> LabelResolution:
        labels: set[str] = set()
        selected_person_label: str | None = None

        people_ids = set(asset_input.asset.people)
        child_matches = people_ids.intersection(self.config.person_labels.child_person_ids)
        family_matches = people_ids.intersection(self.config.person_labels.family_person_ids)

        if child_matches:
            labels.add(self.config.person_labels.person_category_key)
            labels.add(self.config.person_labels.child_category_key)
            selected_person_label = self.config.person_labels.child_category_key
        elif family_matches:
            labels.add(self.config.person_labels.person_category_key)
            labels.add(self.config.person_labels.family_category_key)
            selected_person_label = self.config.person_labels.family_category_key
        elif people_ids:
            labels.add(self.config.person_labels.person_category_key)
            selected_person_label = self.config.person_labels.person_category_key

        for rule in self.config.mechanical_rules:
            if rule.matches(asset_input):
                labels.add(rule.category_key)

        accepted_smart_labels = tuple(
            category_key
            for category_key in asset_input.weak_smart_categories
            if category_key in self.config.smart_search_category_keys
        )
        labels.update(accepted_smart_labels)

        if not labels:
            labels.add(self.config.other_category_key)

        return LabelResolution(
            candidate_labels=tuple(sorted(labels)),
            selected_person_label=selected_person_label,
            weak_smart_categories=tuple(sorted(accepted_smart_labels)),
        )


class FeatureAssembler:
    def __init__(self, category_keys: Iterable[str]) -> None:
        self.category_keys = tuple(category_keys)

    def feature_names(self, embedding_dimensions: int) -> tuple[str, ...]:
        names = [f"embedding_{index}" for index in range(embedding_dimensions)]
        names.extend(
            [
                "meta_is_favorite",
                "meta_is_trashed",
                "meta_visibility_timeline",
                "meta_visibility_archive",
                "meta_has_people",
                "meta_person_count",
                "meta_has_ocr_text",
                "meta_ocr_char_count",
                "meta_tag_count",
                "meta_path_depth",
            ]
        )
        names.extend(f"label_{category_key}" for category_key in self.category_keys)
        return tuple(names)

    def build_matrix(
        self,
        inputs: Sequence[AssetFeatureInput],
        resolutions: Sequence[LabelResolution],
    ) -> FeatureMatrix:
        if len(inputs) != len(resolutions):
            raise ValueError("inputs and resolutions must have the same length")

        if not inputs:
            return FeatureMatrix(feature_names=tuple(), rows=[])

        embedding_dimensions = len(inputs[0].embedding)
        feature_names = self.feature_names(embedding_dimensions)
        rows = [
            self.build_row(asset_input, resolution, embedding_dimensions)
            for asset_input, resolution in zip(inputs, resolutions)
        ]
        return FeatureMatrix(feature_names=feature_names, rows=rows)

    def build_row(
        self,
        asset_input: AssetFeatureInput,
        resolution: LabelResolution,
        embedding_dimensions: int,
    ) -> FeatureRow:
        if len(asset_input.embedding) != embedding_dimensions:
            raise ValueError("embedding dimensions must be consistent across rows")

        visibility = asset_input.asset.visibility or ""
        vector = [float(value) for value in asset_input.embedding]
        vector.extend(
            [
                float(asset_input.asset.is_favorite),
                float(asset_input.asset.is_trashed),
                float(visibility == "timeline"),
                float(visibility == "archive"),
                float(bool(asset_input.asset.people)),
                float(len(asset_input.asset.people)),
                float(bool(asset_input.ocr_text)),
                float(len(asset_input.ocr_text or "")),
                float(len(asset_input.tag_names)),
                float(self._path_depth(asset_input.asset.original_path)),
            ]
        )
        candidate_set = set(resolution.candidate_labels)
        vector.extend(float(category_key in candidate_set) for category_key in self.category_keys)
        return FeatureRow(
            asset_id=asset_input.asset.id,
            candidate_labels=resolution.candidate_labels,
            vector=vector,
        )

    @staticmethod
    def _path_depth(path: str | None) -> int:
        if not path:
            return 0
        return len([segment for segment in path.split("/") if segment])