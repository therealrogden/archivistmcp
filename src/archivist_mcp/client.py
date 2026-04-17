from typing import Any
import httpx

from .config import Config


class ArchivistClient:
    def __init__(self, config: Config, timeout: float = 30.0):
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={"x-api-key": config.api_key},
            timeout=timeout,
        )

    @property
    def campaign_id(self) -> str:
        return self._config.campaign_id

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        response = await self._client.get("/health")
        response.raise_for_status()
        return response.json()

    async def get(self, path: str, **params: Any) -> Any:
        response = await self._client.get(path, params=params or None)
        response.raise_for_status()
        return response.json()

    async def post(self, path: str, json: dict[str, Any]) -> Any:
        response = await self._client.post(path, json=json)
        response.raise_for_status()
        return response.json()

    async def patch(self, path: str, json: dict[str, Any]) -> Any:
        response = await self._client.patch(path, json=json)
        response.raise_for_status()
        return response.json()

    async def delete(self, path: str) -> None:
        response = await self._client.delete(path)
        response.raise_for_status()
