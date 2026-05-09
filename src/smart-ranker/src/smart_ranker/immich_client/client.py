from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from smart_ranker.immich_client.dto import ActionResult, AssetSnapshot, PersonSnapshot, SearchResult
from smart_ranker.immich_client.normalizers import (
    normalize_action_result,
    normalize_asset_snapshot,
    normalize_person_snapshot,
    normalize_search_result,
)
from smart_ranker.immich_client.session import ImmichSession


@dataclass(frozen=True)
class CapabilityRegistry:
    search_metadata_path: str = "search/metadata"
    search_smart_path: str = "search/smart"
    search_person_path: str = "search/person"
    people_path: str = "people"
    asset_path: str = "assets"
    asset_ocr_suffix: str = "ocr"
    album_path: str = "albums"
    tag_path: str = "tags"
    trash_restore_assets_path: str = "trash/restore/assets"


class AssetReadClient:
    def __init__(self, session: ImmichSession, capabilities: CapabilityRegistry | None = None) -> None:
        self.session = session
        self.capabilities = capabilities or CapabilityRegistry()

    def get_asset(self, asset_id: str) -> AssetSnapshot:
        response = self.session.get(f"{self.capabilities.asset_path}/{asset_id}")
        return normalize_asset_snapshot(response.payload)

    def get_asset_ocr(self, asset_id: str) -> ActionResult:
        response = self.session.get(
            f"{self.capabilities.asset_path}/{asset_id}/{self.capabilities.asset_ocr_suffix}"
        )
        return normalize_action_result(response.status_code, response.payload)

    def search_metadata(self, payload: dict[str, Any]) -> SearchResult:
        response = self.session.post(self.capabilities.search_metadata_path, json_body=payload)
        return normalize_search_result(response.payload, normalize_asset_snapshot)

    def search_smart(self, payload: dict[str, Any]) -> SearchResult:
        response = self.session.post(self.capabilities.search_smart_path, json_body=payload)
        return normalize_search_result(response.payload, normalize_asset_snapshot)


class PeopleClient:
    def __init__(self, session: ImmichSession, capabilities: CapabilityRegistry | None = None) -> None:
        self.session = session
        self.capabilities = capabilities or CapabilityRegistry()

    def list_people(self, *, page: int = 1, size: int = 500, with_hidden: bool = False) -> list[PersonSnapshot]:
        response = self.session.get(
            self.capabilities.people_path,
            params={"page": page, "size": size, "withHidden": with_hidden},
        )
        people_payload = response.payload.get("people", response.payload if isinstance(response.payload, list) else [])
        return [normalize_person_snapshot(person) for person in people_payload]

    def search_people(self, name: str, *, with_hidden: bool = False) -> list[PersonSnapshot]:
        response = self.session.get(
            self.capabilities.search_person_path,
            params={"name": name, "withHidden": with_hidden},
        )
        return [normalize_person_snapshot(person) for person in response.payload]


class ActionWriteClient:
    def __init__(self, session: ImmichSession, capabilities: CapabilityRegistry | None = None) -> None:
        self.session = session
        self.capabilities = capabilities or CapabilityRegistry()

    def update_asset(self, asset_id: str, payload: dict[str, Any]) -> ActionResult:
        response = self.session.put(f"{self.capabilities.asset_path}/{asset_id}", json_body=payload)
        return normalize_action_result(response.status_code, response.payload)

    def add_assets_to_album(self, album_id: str, asset_ids: Iterable[str]) -> ActionResult:
        response = self.session.put(
            f"{self.capabilities.album_path}/{album_id}/assets",
            json_body={"ids": list(asset_ids)},
        )
        return normalize_action_result(response.status_code, response.payload)

    def tag_assets(self, tag_id: str, asset_ids: Iterable[str]) -> ActionResult:
        response = self.session.put(
            f"{self.capabilities.tag_path}/{tag_id}/assets",
            json_body={"ids": list(asset_ids)},
        )
        return normalize_action_result(response.status_code, response.payload)

    def restore_assets(self, asset_ids: Iterable[str]) -> ActionResult:
        response = self.session.post(
            self.capabilities.trash_restore_assets_path,
            json_body={"ids": list(asset_ids)},
        )
        return normalize_action_result(response.status_code, response.payload)