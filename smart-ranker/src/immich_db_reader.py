from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import psycopg


def parse_embedding(value: str | Sequence[float]) -> list[float]:
    if isinstance(value, str):
        stripped = value.strip().removeprefix("[").removesuffix("]")
        if not stripped:
            return []
        return [float(part.strip()) for part in stripped.split(",")]

    return [float(part) for part in value]


@dataclass(frozen=True)
class ImmichDbConfig:
    dsn: str


class ImmichDbReader:
    def __init__(
        self,
        config: ImmichDbConfig,
        *,
        connection: psycopg.Connection | None = None,
    ) -> None:
        self.config = config
        self._owns_connection = connection is None
        self.connection = connection

    def close(self) -> None:
        if self._owns_connection and self.connection is not None:
            self.connection.close()

    def fetch_embedding(self, asset_id: str) -> list[float] | None:
        results = self.fetch_embeddings([asset_id])
        return results.get(asset_id)

    def fetch_embeddings(self, asset_ids: Iterable[str]) -> dict[str, list[float]]:
        asset_id_list = list(asset_ids)
        if not asset_id_list:
            return {}

        connection = self._ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                '''
                SELECT "assetId"::text, "embedding"::text
                FROM smart_search
                WHERE "assetId" = ANY(%s)
                ''',
                (asset_id_list,),
            )
            rows = cursor.fetchall()

        return {str(asset_id): parse_embedding(embedding) for asset_id, embedding in rows}

    def _ensure_connection(self) -> psycopg.Connection:
        if self.connection is None:
            self.connection = psycopg.connect(self.config.dsn, autocommit=True)
            with self.connection.cursor() as cursor:
                cursor.execute("SET default_transaction_read_only = on")
        return self.connection
