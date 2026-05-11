from __future__ import annotations

import unittest
from uuid import UUID
from unittest.mock import patch

from smart_ranker.immich_db_reader import ImmichDbConfig, ImmichDbReader, parse_embedding


class FakeCursor:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.cursors: list[FakeCursor] = []
        self.closed = False

    def cursor(self):
        cursor = FakeCursor(self.rows)
        self.cursors.append(cursor)
        return cursor

    def close(self):
        self.closed = True


class ImmichDbReaderTest(unittest.TestCase):
    def test_parse_embedding_supports_vector_text(self) -> None:
        self.assertEqual([1.0, 2.5, 3.0], parse_embedding("[1, 2.5, 3]"))
        self.assertEqual([], parse_embedding("[]"))

    def test_reader_connects_lazily_when_connection_not_injected(self) -> None:
        fake_connection = FakeConnection(rows=[("asset-1", "[0.1, 0.2, 0.3]")])

        with patch("smart_ranker.immich_db_reader.psycopg.connect", return_value=fake_connection) as connect_mock:
            reader = ImmichDbReader(ImmichDbConfig(dsn="postgresql://ignored"))

            connect_mock.assert_not_called()

            result = reader.fetch_embeddings(["asset-1"])

        self.assertEqual({"asset-1": [0.1, 0.2, 0.3]}, result)
        connect_mock.assert_called_once_with("postgresql://ignored", autocommit=True)
        self.assertEqual(2, len(fake_connection.cursors))
        self.assertEqual("SET default_transaction_read_only = on", fake_connection.cursors[0].executed[0][0])
        query, params = fake_connection.cursors[1].executed[0]
        self.assertIn('FROM smart_search', query)
        self.assertEqual((['asset-1'],), params)

    def test_fetch_embeddings_uses_read_only_query_shape(self) -> None:
        fake_connection = FakeConnection(rows=[(UUID("11111111-1111-1111-1111-111111111111"), "[0.1, 0.2, 0.3]")])
        reader = ImmichDbReader(ImmichDbConfig(dsn="postgresql://ignored"), connection=fake_connection)

        result = reader.fetch_embeddings(["asset-1"])

        self.assertEqual({"11111111-1111-1111-1111-111111111111": [0.1, 0.2, 0.3]}, result)
        self.assertEqual(1, len(fake_connection.cursors))
        query, params = fake_connection.cursors[0].executed[0]
        self.assertIn('FROM smart_search', query)
        self.assertIn('SELECT "assetId"::text', query)
        self.assertIn('"assetId" = ANY(%s)', query)
        self.assertEqual((['asset-1'],), params)


if __name__ == "__main__":
    unittest.main()
