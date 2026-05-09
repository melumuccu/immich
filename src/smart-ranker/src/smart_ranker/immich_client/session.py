from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests


class ImmichHttpError(RuntimeError):
    def __init__(self, method: str, url: str, status_code: int, response_text: str) -> None:
        super().__init__(f"Immich request failed: {method} {url} -> {status_code}")
        self.method = method
        self.url = url
        self.status_code = status_code
        self.response_text = response_text


@dataclass(frozen=True)
class ResponseEnvelope:
    status_code: int
    payload: Any


class ImmichSession:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        read_retries: int = 2,
        api_prefix: str = "/api",
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.read_retries = read_retries
        self.api_prefix = api_prefix.strip("/")
        self.session = session or requests.Session()

    def close(self) -> None:
        self.session.close()

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> ResponseEnvelope:
        return self.request("GET", path, params=params, retry=True)

    def post(self, path: str, *, json_body: Any | None = None) -> ResponseEnvelope:
        return self.request("POST", path, json_body=json_body)

    def put(self, path: str, *, json_body: Any | None = None) -> ResponseEnvelope:
        return self.request("PUT", path, json_body=json_body)

    def delete(self, path: str, *, json_body: Any | None = None) -> ResponseEnvelope:
        return self.request("DELETE", path, json_body=json_body)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        retry: bool = False,
    ) -> ResponseEnvelope:
        url = f"{self.base_url}/{self.api_prefix}/{path.lstrip('/')}"
        headers = {
            "Accept": "application/json",
            "x-api-key": self.api_key,
        }

        attempts = self.read_retries + 1 if retry else 1
        response: requests.Response | None = None

        for attempt in range(attempts):
            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=self.timeout,
            )

            if response.status_code < 500 or attempt == attempts - 1:
                break

            time.sleep(0.25 * (attempt + 1))

        assert response is not None

        if response.status_code >= 400:
            raise ImmichHttpError(method=method, url=url, status_code=response.status_code, response_text=response.text)

        if not response.content:
            payload: Any = None
        else:
            payload = response.json()

        return ResponseEnvelope(status_code=response.status_code, payload=payload)
