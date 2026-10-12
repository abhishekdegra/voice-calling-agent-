"""Reusable client for Welfog Knowledge Search API (aidata.welfog.com).

Connects to existing Welfog Knowledge Admin Qdrant vector search backend:
Endpoint: POST https://aidata.welfog.com/api/search
Headers:
  Content-Type: application/json
  x-api-key: <WELFOG_KNOWLEDGE_API_KEY>
  Accept: application/json
Payload:
  {"query": "<text>", "limit": 5, "threshold": 0.5 (optional)}
"""

import asyncio
import time
from typing import Any, Dict, List, Optional
import httpx

from app.config import get_settings
from app.utils.logging import logger


class KnowledgeSearchService:
    """Service wrapper for Welfog Knowledge Search API."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None
    ):
        settings = get_settings()
        self.api_url = api_url or settings.welfog_knowledge_api_url
        self.api_key = api_key or settings.welfog_knowledge_api_key
        self._client = client
        self._timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=15.0)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or getattr(self._client, "is_closed", False) is True:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "WelfogVoiceAgent/1.0"
                }
            )
        return self._client

    async def close(self):
        """Close async HTTP client."""
        if self._client and not getattr(self._client, "is_closed", False):
            await self._client.aclose()

    async def search_async(
        self,
        query: str,
        limit: int = 5,
        threshold: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Asynchronously search Welfog company knowledge.
        Returns normalized dictionary with ok, found, results, context, instruction, error.
        """
        q = (query or "").strip()
        if not q:
            return {
                "ok": False,
                "query": "",
                "found": 0,
                "results": [],
                "context": "",
                "instruction": "",
                "error": "Query cannot be empty"
            }

        if not self.api_key:
            return {
                "ok": False,
                "query": q,
                "found": 0,
                "results": [],
                "context": "",
                "instruction": "",
                "error": "WELFOG_KNOWLEDGE_API_KEY is not configured"
            }

        body: Dict[str, Any] = {
            "query": q,
            "limit": max(1, min(20, int(limit or 5)))
        }
        if threshold is not None:
            body["threshold"] = float(threshold)

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "Accept": "application/json"
        }

        start_time = time.perf_counter()
        client = await self._get_client()

        for attempt in range(2):
            try:
                res = await client.post(self.api_url, json=body, headers=headers)
                latency_ms = (time.perf_counter() - start_time) * 1000

                if res.status_code == 200:
                    data = res.json()
                    results = data.get("results") if isinstance(data.get("results"), list) else []
                    found = int(data.get("found") or len(results) or 0)
                    
                    logger.info(
                        "welfog_knowledge_search_success",
                        query=q[:60],
                        found=found,
                        latency_ms=latency_ms
                    )
                    return {
                        "ok": bool(data.get("ok", True)),
                        "query": data.get("query") or q,
                        "found": found,
                        "results": results,
                        "context": str(data.get("context") or "").strip(),
                        "instruction": str(data.get("instruction") or "").strip(),
                        "error": None
                    }
                else:
                    logger.warning(
                        "welfog_knowledge_search_failed",
                        query=q[:60],
                        status_code=res.status_code,
                        latency_ms=latency_ms
                    )
                    return {
                        "ok": False,
                        "query": q,
                        "found": 0,
                        "results": [],
                        "context": "",
                        "instruction": "",
                        "error": f"API returned HTTP {res.status_code}: {res.text}"
                    }
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt == 0:
                    await asyncio.sleep(1.0)
                    continue
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.error("welfog_knowledge_search_exception", query=q[:60], error=str(e), latency_ms=latency_ms)
                return {
                    "ok": False,
                    "query": q,
                    "found": 0,
                    "results": [],
                    "context": "",
                    "instruction": "",
                    "error": str(e)
                }
            except Exception as e:
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.error("welfog_knowledge_search_exception", query=q[:60], error=str(e), latency_ms=latency_ms)
                return {
                    "ok": False,
                    "query": q,
                    "found": 0,
                    "results": [],
                    "context": "",
                    "instruction": "",
                    "error": str(e)
                }

    def search_sync(
        self,
        query: str,
        limit: int = 5,
        threshold: Optional[float] = None
    ) -> Dict[str, Any]:
        """Synchronous wrapper for search_async."""
        import asyncio
        return asyncio.run(self.search_async(query, limit, threshold))


# Standalone convenience functions
async def search_welfog_knowledge_async(
    query: str,
    limit: int = 5,
    threshold: Optional[float] = None
) -> Dict[str, Any]:
    """Convenience async helper to query Welfog knowledge base."""
    service = KnowledgeSearchService()
    try:
        return await service.search_async(query, limit, threshold)
    finally:
        await service.close()


def search_welfog_knowledge(
    query: str,
    limit: int = 5,
    threshold: Optional[float] = None
) -> Dict[str, Any]:
    """Convenience synchronous helper to query Welfog knowledge base."""
    service = KnowledgeSearchService()
    return service.search_sync(query, limit, threshold)
