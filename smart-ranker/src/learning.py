from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from smart_ranker.immich_client import AssetSnapshot
from smart_ranker.storage.repository import (
    FavoriteSignalRecord,
    StorageRepository,
    TrashSignalRecord,
)


TRASH_SEARCH_PAYLOAD = {
    "withDeleted": True,
    "trashedAfter": "1970-01-01T00:00:00Z",
}


def fetch_assets_by_search(
    asset_client: Any,
    *,
    base_payload: dict[str, Any] | None = None,
    batch_size: int,
    max_assets: int | None = None,
) -> list[AssetSnapshot]:
    payload = dict(base_payload or {})
    page: str | int = payload.pop("page", 1)
    assets: list[AssetSnapshot] = []
    seen_asset_ids: set[str] = set()

    while True:
        result = asset_client.search_metadata({**payload, "size": batch_size, "page": page})
        for asset in result.items:
            if asset.id in seen_asset_ids:
                continue
            assets.append(asset)
            seen_asset_ids.add(asset.id)
            if max_assets is not None and len(assets) >= max_assets:
                return assets

        if not result.has_next_page:
            return assets

        if result.next_page:
            page = result.next_page
            continue

        page = int(page) + 1 if str(page).isdigit() else len(assets) + 1


@dataclass(frozen=True)
class LearningSyncResult:
    favorite_assets: list[AssetSnapshot]
    trash_assets: list[AssetSnapshot]
    training_assets: list[AssetSnapshot]
    favorite_cleared_count: int
    trash_restored_count: int
    excluded_trash_count: int


class ManualSignalCollector:
    def __init__(
        self,
        repository: StorageRepository,
        asset_client: Any,
        *,
        profile_id: str,
        now_factory,
    ) -> None:
        self.repository = repository
        self.asset_client = asset_client
        self.profile_id = profile_id
        self.now_factory = now_factory

    def sync(self, *, batch_size: int, max_assets: int | None = None) -> LearningSyncResult:
        occurred_at = self.now_factory()
        favorite_assets = fetch_assets_by_search(
            self.asset_client,
            base_payload={"isFavorite": True},
            batch_size=batch_size,
            max_assets=max_assets,
        )
        trash_assets = fetch_assets_by_search(
            self.asset_client,
            base_payload=TRASH_SEARCH_PAYLOAD,
            batch_size=batch_size,
            max_assets=max_assets,
        )

        for asset in favorite_assets:
            self.repository.upsert_favorite_signal(
                FavoriteSignalRecord(
                    id=str(uuid4()),
                    profile_id=self.profile_id,
                    immich_asset_id=asset.id,
                    first_seen_at=occurred_at,
                    last_seen_at=occurred_at,
                    cleared_at=None,
                    metadata=_serialize_asset_snapshot(asset),
                )
            )

        for asset in trash_assets:
            self.repository.upsert_trash_signal(
                TrashSignalRecord(
                    id=str(uuid4()),
                    profile_id=self.profile_id,
                    immich_asset_id=asset.id,
                    first_seen_at=occurred_at,
                    last_seen_at=occurred_at,
                    restored_at=None,
                    metadata=_serialize_asset_snapshot(asset),
                )
            )

        favorite_cleared_count = self.repository.mark_missing_favorite_signals_cleared(
            self.profile_id,
            [asset.id for asset in favorite_assets],
            cleared_at=occurred_at,
        )
        trash_restored_count = self.repository.mark_missing_trash_signals_restored(
            self.profile_id,
            [asset.id for asset in trash_assets],
            restored_at=occurred_at,
        )

        return LearningSyncResult(
            favorite_assets=favorite_assets,
            trash_assets=trash_assets,
            training_assets=self._build_training_assets(),
            favorite_cleared_count=favorite_cleared_count,
            trash_restored_count=trash_restored_count,
            excluded_trash_count=0,
        )

    def _build_training_assets(self) -> list[AssetSnapshot]:
        favorite_by_asset_id = {
            str(row["immich_asset_id"]): row
            for row in self.repository.list_favorite_signals(self.profile_id)
            if row["immich_asset_id"]
        }
        trash_by_asset_id = {
            str(row["immich_asset_id"]): row
            for row in self.repository.list_trash_signals(self.profile_id)
            if row["immich_asset_id"]
        }

        training_assets: list[AssetSnapshot] = []
        for asset_id in sorted(set(favorite_by_asset_id) | set(trash_by_asset_id)):
            favorite_row = favorite_by_asset_id.get(asset_id)
            trash_row = trash_by_asset_id.get(asset_id)

            selected_kind = "favorite"
            selected_row = favorite_row
            if favorite_row is None and trash_row is not None:
                selected_kind = "trash"
                selected_row = trash_row
            elif favorite_row is not None and trash_row is not None:
                favorite_seen = str(favorite_row["last_seen_at"] or "")
                trash_seen = str(trash_row["last_seen_at"] or "")
                if (trash_seen, 1) >= (favorite_seen, 0):
                    selected_kind = "trash"
                    selected_row = trash_row

            if selected_row is None:
                continue

            asset = _deserialize_asset_snapshot(selected_row["metadata_json"])
            if selected_kind == "trash":
                asset = replace(asset, is_favorite=False, is_trashed=True)
            else:
                asset = replace(asset, is_favorite=True, is_trashed=False)
            training_assets.append(asset)

        return training_assets


def _serialize_asset_snapshot(asset: AssetSnapshot) -> dict[str, Any]:
    return {
        "id": asset.id,
        "isFavorite": asset.is_favorite,
        "isTrashed": asset.is_trashed,
        "visibility": asset.visibility,
        "people": list(asset.people),
        "originalFileName": asset.original_file_name,
        "originalPath": asset.original_path,
        "updatedAt": asset.updated_at,
        "payload": asset.payload,
    }


def _deserialize_asset_snapshot(raw_payload: str | dict[str, Any] | None) -> AssetSnapshot:
    if isinstance(raw_payload, str):
        payload = json.loads(raw_payload) if raw_payload else {}
    elif isinstance(raw_payload, dict):
        payload = raw_payload
    else:
        payload = {}

    asset_id = str(payload.get("id") or payload.get("assetId") or "")
    return AssetSnapshot(
        id=asset_id,
        is_favorite=bool(payload.get("isFavorite", False)),
        is_trashed=bool(payload.get("isTrashed", False)),
        visibility=str(payload.get("visibility") or "timeline"),
        people=tuple(str(item) for item in payload.get("people", []) if str(item).strip()),
        original_file_name=str(payload.get("originalFileName") or f"{asset_id}.jpg"),
        original_path=str(payload.get("originalPath") or f"/library/{asset_id}.jpg"),
        updated_at=str(payload.get("updatedAt") or ""),
        payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {"id": asset_id},
    )
