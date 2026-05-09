from __future__ import annotations

from typing import Any, Callable

from smart_ranker.immich_client.dto import ActionResult, AssetSnapshot, PersonSnapshot, SearchResult


def normalize_asset_snapshot(payload: dict[str, Any]) -> AssetSnapshot:
    people = payload.get("people") or []
    person_ids = tuple(person.get("id") for person in people if isinstance(person, dict) and person.get("id"))

    return AssetSnapshot(
        id=str(payload["id"]),
        is_favorite=bool(payload.get("isFavorite", False)),
        is_trashed=bool(payload.get("isTrashed", False)),
        visibility=payload.get("visibility"),
        people=person_ids,
        original_file_name=payload.get("originalFileName"),
        original_path=payload.get("originalPath"),
        updated_at=payload.get("updatedAt"),
        payload=payload,
    )


def normalize_person_snapshot(payload: dict[str, Any]) -> PersonSnapshot:
    return PersonSnapshot(
        id=str(payload["id"]),
        name=payload.get("name"),
        is_hidden=bool(payload.get("isHidden", False)),
        face_asset_id=payload.get("faceAssetId"),
        payload=payload,
    )


def normalize_search_result(
    payload: dict[str, Any],
    item_normalizer: Callable[[dict[str, Any]], Any],
) -> SearchResult:
    items = [item_normalizer(item) for item in payload.get("items", [])]
    next_page = payload.get("nextPage")
    has_next_page = bool(payload.get("hasNextPage", next_page is not None))
    return SearchResult(items=items, next_page=next_page, has_next_page=has_next_page, raw=payload)


def normalize_action_result(status_code: int, payload: Any) -> ActionResult:
    return ActionResult(status_code=status_code, ok=200 <= status_code < 300, payload=payload)
