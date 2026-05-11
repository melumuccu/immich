from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

from smart_ranker.immich_client.dto import ActionResult, AssetSnapshot, PersonSnapshot, SearchResult
from smart_ranker.immich_client.normalizers import (
    normalize_action_result,
    normalize_asset_snapshot,
    normalize_person_snapshot,
    normalize_search_result,
)
from smart_ranker.immich_client.session import ImmichHttpError, ImmichSession


@dataclass(frozen=True)
class CapabilityRegistry:
    search_metadata_path: str = "search/metadata"
    search_smart_path: str = "search/smart"
    search_person_path: str = "search/person"
    people_path: str = "people"
    asset_path: str = "assets"
    asset_ocr_suffix: str = "ocr"
    asset_thumbnail_suffix: str = "thumbnail"
    album_path: str = "albums"
    tag_path: str = "tags"
    trash_assets_path: str = "assets"
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

    def get_asset_thumbnail(
        self,
        asset_id: str,
        *,
        size: str | None = None,
        format: str | None = None,
    ):
        params: dict[str, Any] = {}
        if size:
            params["size"] = size
        if format:
            params["format"] = format
        return self.session.get_bytes(
            f"{self.capabilities.asset_path}/{asset_id}/{self.capabilities.asset_thumbnail_suffix}",
            params=params or None,
        )

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

    def search_people(
        self,
        name: str,
        *,
        with_hidden: bool = False,
        limit: int | None = None,
    ) -> list[PersonSnapshot]:
        normalized_name = _normalize_person_query(name)
        if not normalized_name:
            return []

        try:
            response = self.session.get(
                self.capabilities.search_person_path,
                params={"name": name, "withHidden": with_hidden},
            )
        except ImmichHttpError as error:
            if error.status_code not in {400, 404}:
                raise
            return self._search_people_via_listing(
                normalized_name,
                with_hidden=with_hidden,
                limit=limit,
            )

        return [normalize_person_snapshot(person) for person in response.payload][:limit]

    def _search_people_via_listing(
        self,
        normalized_name: str,
        *,
        with_hidden: bool,
        limit: int | None,
    ) -> list[PersonSnapshot]:
        page = 1
        page_size = min(max(limit or 100, 100), 500)
        matches: list[PersonSnapshot] = []

        while True:
            people = self.list_people(page=page, size=page_size, with_hidden=with_hidden)
            for person in people:
                if normalized_name in _normalize_person_query(person.name):
                    matches.append(person)
                    if limit is not None and len(matches) >= limit:
                        return matches

            if len(people) < page_size:
                return matches

            page += 1


def _normalize_person_query(value: str | None) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", value).casefold().strip()


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

    def trash_assets(self, asset_ids: Iterable[str], *, force: bool = False) -> ActionResult:
        response = self.session.delete(
            self.capabilities.trash_assets_path,
            json_body={"ids": list(asset_ids), "force": force},
        )
        return normalize_action_result(response.status_code, response.payload)

    def restore_assets(self, asset_ids: Iterable[str]) -> ActionResult:
        response = self.session.post(
            self.capabilities.trash_restore_assets_path,
            json_body={"ids": list(asset_ids)},
        )
        return normalize_action_result(response.status_code, response.payload)
