import httpx


class LocalClient:
    """Async client for llama-server's POST /completion."""

    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 30.0):
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout)

    async def completion(self, prompt: str, **params) -> str:
        resp = await self._http.post("/completion", json={"prompt": prompt, **params})
        resp.raise_for_status()
        return resp.json()["content"]
