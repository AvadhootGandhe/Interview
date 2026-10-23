"""Async client for llama-server's `POST /completion` endpoint."""
from __future__ import annotations

import httpx


class LocalLLMError(Exception):
    """llama-server could not be reached or returned an error."""


class LocalClient:
    def __init__(self, base_url: str, timeout_s: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def complete(self, prompt: str, **params) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    f"{self.base_url}/completion", json={"prompt": prompt, **params}
                )
                resp.raise_for_status()
                return resp.json()["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LocalLLMError(str(exc)) from exc
