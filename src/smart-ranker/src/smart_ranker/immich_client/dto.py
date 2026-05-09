from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AssetSnapshot:
    id: str
    is_favorite: bool
    is_trashed: bool
    visibility: str | None
    people: tuple[str, ...]
    original_file_name: str | None
    original_path: str | None
    updated_at: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class PersonSnapshot:
    id: str
    name: str | None
    is_hidden: bool
    face_asset_id: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class SearchResult:
    items: list[Any]
    next_page: str | None
    has_next_page: bool
    raw: dict[str, Any]


@dataclass(frozen=True)
class ActionResult:
    status_code: int
    ok: bool
    payload: Any