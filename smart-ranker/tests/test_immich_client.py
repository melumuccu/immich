from __future__ import annotations

import json
import unittest

from smart_ranker.immich_client import ActionWriteClient, AssetReadClient, ImmichSession, PeopleClient


class FakeResponse:
    def __init__(self, status_code: int, payload, *, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        if isinstance(payload, bytes):
            self.content = payload
            self.text = payload.decode("utf-8", errors="ignore")
        else:
            self.text = json.dumps(payload) if payload is not None else ""
            self.content = self.text.encode("utf-8") if payload is not None else b""

    def json(self):
        return self._payload


class FakeRequestsSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def request(self, method, url, headers=None, params=None, json=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "json": json,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)

    def close(self) -> None:
        return None


class ImmichClientTest(unittest.TestCase):
    def test_search_metadata_supports_nested_assets_payload(self) -> None:
        fake_session = FakeRequestsSession(
            [
                FakeResponse(
                    200,
                    {
                        "albums": {"items": []},
                        "assets": {
                            "items": [
                                {
                                    "id": "asset-1",
                                    "isFavorite": True,
                                    "isTrashed": False,
                                    "visibility": "timeline",
                                    "people": [{"id": "person-1"}],
                                    "originalFileName": "IMG_0001.JPG",
                                    "originalPath": "/library/IMG_0001.JPG",
                                    "updatedAt": "2026-05-09T00:00:00Z",
                                }
                            ],
                            "nextPage": "2",
                            "count": 1,
                        },
                    },
                )
            ]
        )
        session = ImmichSession(base_url="http://immich.local", api_key="secret", session=fake_session)

        search_result = AssetReadClient(session).search_metadata({"page": 1})

        self.assertEqual(["asset-1"], [item.id for item in search_result.items])
        self.assertEqual("2", search_result.next_page)
        self.assertTrue(search_result.has_next_page)

    def test_asset_and_people_clients_use_expected_routes(self) -> None:
        fake_session = FakeRequestsSession(
            [
                FakeResponse(
                    200,
                    {
                        "items": [
                            {
                                "id": "asset-1",
                                "isFavorite": True,
                                "isTrashed": False,
                                "visibility": "timeline",
                                "people": [{"id": "person-1"}],
                                "originalFileName": "IMG_0001.JPG",
                                "originalPath": "/library/IMG_0001.JPG",
                                "updatedAt": "2026-05-09T00:00:00Z",
                            }
                        ],
                        "nextPage": "2",
                        "hasNextPage": True,
                    },
                ),
                FakeResponse(
                    200,
                    [
                        {
                            "id": "person-1",
                            "name": "Kid",
                            "isHidden": False,
                            "faceAssetId": "asset-1",
                        }
                    ],
                ),
                FakeResponse(
                    200,
                    {
                        "people": [
                            {
                                "id": "person-2",
                                "name": "Family",
                                "isHidden": True,
                                "faceAssetId": "asset-2",
                            }
                        ]
                    },
                ),
            ]
        )
        session = ImmichSession(
            base_url="http://immich.local",
            api_key="secret",
            session=fake_session,
            timeout=12.5,
        )

        asset_client = AssetReadClient(session)
        people_client = PeopleClient(session)

        search_result = asset_client.search_metadata({"isFavorite": True, "page": 1})
        searched_people = people_client.search_people("Kid", with_hidden=True)
        all_people = people_client.list_people(page=2, size=50, with_hidden=True)

        self.assertEqual("asset-1", search_result.items[0].id)
        self.assertEqual(("person-1",), search_result.items[0].people)
        self.assertEqual("2", search_result.next_page)
        self.assertTrue(search_result.has_next_page)
        self.assertEqual("person-1", searched_people[0].id)
        self.assertEqual("person-2", all_people[0].id)

        self.assertEqual("POST", fake_session.calls[0]["method"])
        self.assertEqual("http://immich.local/api/search/metadata", fake_session.calls[0]["url"])
        self.assertEqual({"isFavorite": True, "page": 1}, fake_session.calls[0]["json"])
        self.assertEqual("secret", fake_session.calls[0]["headers"]["x-api-key"])

        self.assertEqual("GET", fake_session.calls[1]["method"])
        self.assertEqual("http://immich.local/api/search/person", fake_session.calls[1]["url"])
        self.assertEqual({"name": "Kid", "withHidden": "true"}, fake_session.calls[1]["params"])

        self.assertEqual("GET", fake_session.calls[2]["method"])
        self.assertEqual("http://immich.local/api/people", fake_session.calls[2]["url"])
        self.assertEqual({"page": 2, "size": 50, "withHidden": "true"}, fake_session.calls[2]["params"])

    def test_asset_thumbnail_uses_binary_thumbnail_route(self) -> None:
        fake_session = FakeRequestsSession(
            [
                FakeResponse(
                    200,
                    b"thumbnail-bytes",
                    headers={
                        "Content-Type": "image/webp",
                        "Cache-Control": "public, max-age=60",
                        "ETag": '"thumb-1"',
                    },
                )
            ]
        )
        session = ImmichSession(base_url="http://immich.local", api_key="secret", session=fake_session)

        thumbnail = AssetReadClient(session).get_asset_thumbnail("asset-1")

        self.assertEqual(b"thumbnail-bytes", thumbnail.payload)
        self.assertEqual("image/webp", thumbnail.content_type)
        self.assertEqual("public, max-age=60", thumbnail.cache_control)
        self.assertEqual('"thumb-1"', thumbnail.etag)
        self.assertEqual("GET", fake_session.calls[0]["method"])
        self.assertEqual("http://immich.local/api/assets/asset-1/thumbnail", fake_session.calls[0]["url"])

    def test_people_search_falls_back_to_people_list_when_search_api_rejects_query(self) -> None:
        fake_session = FakeRequestsSession(
            [
                FakeResponse(400, {"message": "unsupported search endpoint"}),
                FakeResponse(
                    200,
                    {
                        "people": [
                            {
                                "id": "person-1",
                                "name": "椎乃",
                                "isHidden": False,
                                "faceAssetId": "asset-1",
                            },
                            {
                                "id": "person-2",
                                "name": "Family",
                                "isHidden": False,
                                "faceAssetId": "asset-2",
                            },
                        ]
                    },
                ),
            ]
        )
        session = ImmichSession(base_url="http://immich.local", api_key="secret", session=fake_session)
        people_client = PeopleClient(session)

        people = people_client.search_people("椎乃", limit=16)

        self.assertEqual(["person-1"], [person.id for person in people])
        self.assertEqual("http://immich.local/api/search/person", fake_session.calls[0]["url"])
        self.assertEqual({"name": "椎乃", "withHidden": "false"}, fake_session.calls[0]["params"])
        self.assertEqual("http://immich.local/api/people", fake_session.calls[1]["url"])
        self.assertEqual({"page": 1, "size": 100, "withHidden": "false"}, fake_session.calls[1]["params"])

    def test_action_write_client_uses_expected_routes(self) -> None:
        fake_session = FakeRequestsSession(
            [
                FakeResponse(200, {"id": "asset-1"}),
                FakeResponse(200, [{"id": "asset-1", "success": True}]),
                FakeResponse(200, [{"id": "asset-1", "success": True}]),
                FakeResponse(200, [{"id": "asset-1", "success": True}]),
                FakeResponse(200, {"count": 1}),
            ]
        )
        session = ImmichSession(base_url="http://immich.local", api_key="secret", session=fake_session)
        action_client = ActionWriteClient(session)

        action_client.update_asset("asset-1", {"description": "score=0.1"})
        action_client.add_assets_to_album("album-1", ["asset-1"])
        action_client.tag_assets("tag-1", ["asset-1"])
        trash_result = action_client.trash_assets(["asset-1"])
        restore_result = action_client.restore_assets(["asset-1"])

        self.assertTrue(trash_result.ok)
        self.assertTrue(restore_result.ok)
        self.assertEqual("http://immich.local/api/assets/asset-1", fake_session.calls[0]["url"])
        self.assertEqual("http://immich.local/api/albums/album-1/assets", fake_session.calls[1]["url"])
        self.assertEqual("http://immich.local/api/tags/tag-1/assets", fake_session.calls[2]["url"])
        self.assertEqual("http://immich.local/api/assets", fake_session.calls[3]["url"])
        self.assertEqual("DELETE", fake_session.calls[3]["method"])
        self.assertEqual({"ids": ["asset-1"], "force": False}, fake_session.calls[3]["json"])
        self.assertEqual("http://immich.local/api/trash/restore/assets", fake_session.calls[4]["url"])


if __name__ == "__main__":
    unittest.main()
