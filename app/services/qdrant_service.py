"""Welfog Knowledge Base RAG Client supporting existing aidata.welfog.com API and direct Qdrant."""

import time
from typing import Any, Dict, List, Optional
import httpx
from qdrant_client import AsyncQdrantClient

from app.config import get_settings
from app.utils.logging import logger


class QdrantService:
    """
    Connects to Welfog's existing Knowledge Base system:
    - Primary preference: Existing Welfog Knowledge Search API (https://aidata.welfog.com/api/search)
    - Secondary fallback: Direct Qdrant cluster connection if QDRANT_URL is set
    Does NOT answer live order questions (those route strictly to WelfogService).
    """

    def __init__(
        self,
        qdrant_client: Optional[AsyncQdrantClient] = None,
        http_client: Optional[httpx.AsyncClient] = None
    ):
        self.settings = get_settings()
        self._qdrant_client = qdrant_client
        self._http_client = http_client

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or getattr(self._http_client, "is_closed", False) is True:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0),
                headers={"Content-Type": "application/json", "User-Agent": "WelfogVoiceAgent/1.0"}
            )
        return self._http_client

    async def _get_qdrant_client(self) -> Optional[AsyncQdrantClient]:
        if not self.settings.qdrant_url:
            return None
        if self._qdrant_client is None:
            self._qdrant_client = AsyncQdrantClient(
                url=self.settings.qdrant_url,
                api_key=self.settings.qdrant_api_key or None,
                timeout=5.0
            )
        return self._qdrant_client

    async def close(self):
        """Close clients."""
        if self._qdrant_client:
            await self._qdrant_client.close()
        if self._http_client and not getattr(self._http_client, "is_closed", False):
            await self._http_client.aclose()

    async def search_knowledge(
        self,
        query: str,
        query_vector: Optional[List[float]] = None,
        limit: int = 5
    ) -> Dict[str, Any]:
        """
        Search Welfog knowledge base.
        First prefers existing Welfog Knowledge Search API at aidata.welfog.com.
        Otherwise falls back to direct Qdrant if configured.
        """
        start_time = time.perf_counter()

        # 1. Prefer existing Welfog Knowledge Search API (aidata.welfog.com)
        if self.settings.welfog_knowledge_api_key:
            return await self._search_via_welfog_api(query, limit, start_time)

        # 2. Check if direct Qdrant is configured
        qdrant = await self._get_qdrant_client()
        if qdrant:
            return await self._search_via_qdrant(qdrant, query, query_vector, limit, start_time)

        # 3. Not configured yet - do not invent credentials
        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.info("knowledge_search_unconfigured", latency_ms=latency_ms)
        return {
            "success": False,
            "configured": False,
            "message": "Welfog knowledge search is awaiting API key configuration (WELFOG_KNOWLEDGE_API_KEY or QDRANT_URL).",
            "chunks": []
        }

    async def _search_via_welfog_api(
        self,
        query: str,
        limit: int,
        start_time: float
    ) -> Dict[str, Any]:
        """Query https://aidata.welfog.com/api/search directly."""
        client = await self._get_http_client()
        url = self.settings.welfog_knowledge_api_url
        headers = {
            "x-api-key": self.settings.welfog_knowledge_api_key,
            "Authorization": f"Bearer {self.settings.welfog_knowledge_api_key}"
        }
        payload = {"query": query, "limit": limit}

        try:
            res = await client.post(url, json=payload, headers=headers)
            latency_ms = (time.perf_counter() - start_time) * 1000

            if res.status_code == 200:
                data = res.json()
                results = data.get("results", [])
                chunks = []
                for item in results:
                    chunks.append({
                        "score": item.get("score", 1.0),
                        "title": item.get("title", "Welfog Knowledge"),
                        "text": item.get("text") or item.get("content") or str(item)
                    })
                if not chunks and data.get("context"):
                    chunks.append({
                        "score": 1.0,
                        "title": "Welfog Knowledge Context",
                        "text": data["context"]
                    })

                logger.info(
                    "welfog_knowledge_api_search_success",
                    query=query,
                    chunks_count=len(chunks),
                    latency_ms=latency_ms
                )
                return {
                    "success": True,
                    "configured": True,
                    "provider": "welfog_knowledge_api",
                    "chunks": chunks
                }
            else:
                logger.warning(
                    "welfog_knowledge_api_search_failed",
                    query=query,
                    latency_ms=latency_ms,
                    extra={"status_code": res.status_code}
                )
                return {
                    "success": False,
                    "configured": True,
                    "provider": "welfog_knowledge_api",
                    "error": f"Knowledge API returned HTTP {res.status_code}",
                    "chunks": []
                }
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error("welfog_knowledge_api_exception", query=query, error=str(e), latency_ms=latency_ms)
            return {
                "success": False,
                "configured": True,
                "provider": "welfog_knowledge_api",
                "error": str(e),
                "chunks": []
            }

    async def _search_via_qdrant(
        self,
        client: AsyncQdrantClient,
        query: str,
        query_vector: Optional[List[float]],
        limit: int,
        start_time: float
    ) -> Dict[str, Any]:
        """Direct Qdrant cluster vector retrieval."""
        try:
            if query_vector:
                results = await client.search(
                    collection_name=self.settings.qdrant_collection,
                    query_vector=query_vector,
                    limit=limit
                )
            else:
                results = await client.query_points(
                    collection_name=self.settings.qdrant_collection,
                    query=query,
                    limit=limit
                )
                results = getattr(results, "points", results)

            latency_ms = (time.perf_counter() - start_time) * 1000
            chunks = []
            for hit in results:
                payload = getattr(hit, "payload", {}) or {}
                chunks.append({
                    "score": getattr(hit, "score", 0.0),
                    "title": payload.get("title") or payload.get("source") or "Policy",
                    "text": payload.get("text") or payload.get("content") or payload.get("chunk") or str(payload)
                })

            logger.info(
                "qdrant_direct_search_success",
                query=query,
                chunks_count=len(chunks),
                latency_ms=latency_ms
            )
            return {
                "success": True,
                "configured": True,
                "provider": "qdrant_direct",
                "chunks": chunks
            }
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error("qdrant_direct_search_error", query=query, error=str(e), latency_ms=latency_ms)
            return {
                "success": False,
                "configured": True,
                "provider": "qdrant_direct",
                "error": str(e),
                "chunks": []
            }
