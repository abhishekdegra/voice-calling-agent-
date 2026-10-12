"""Controlled Knowledge Tools for Gemini AI function calling."""

import time
from typing import Any, Dict, Optional
from app.services.qdrant_service import QdrantService
from app.utils.logging import logger


class KnowledgeTools:
    """
    Search Welfog knowledge base / FAQs / policies via Qdrant.
    Only used for non-order questions (e.g., refund policy rules, shipping timings, return process).
    """

    def __init__(self, qdrant_service: Optional[QdrantService] = None):
        self.qdrant_service = qdrant_service or QdrantService()

    async def search_welfog_knowledge(self, query: str) -> Dict[str, Any]:
        """Search company return policies, warranty, shipping FAQs, and guidelines."""
        start_time = time.perf_counter()
        if not query or not query.strip():
            return {"status": "error", "message": "Query cannot be empty."}

        try:
            res = await self.qdrant_service.search_knowledge(query=query.strip(), limit=3)
            latency_ms = (time.perf_counter() - start_time) * 1000

            if not res.get("configured"):
                # Fallback policy answers if Qdrant cluster is not yet configured in local development
                return {
                    "status": "success",
                    "note": "Standard Welfog Policy Overview",
                    "information": (
                        "Welfog standard return window is 7 days from delivery for eligible items in original condition. "
                        "Refunds are processed within 5-7 working days after quality inspection. "
                        "Shipping is typically delivered within 3-5 business days."
                    )
                }

            if not res.get("success"):
                return {"status": "error", "message": "Knowledge search failed."}

            chunks = res.get("chunks", [])
            if not chunks:
                return {"status": "empty", "message": "No relevant policy or FAQ document found."}

            return {
                "status": "success",
                "results": [{"title": c["title"], "content": c["text"]} for c in chunks]
            }
        except Exception as e:
            logger.error("tool_search_knowledge_error", error=str(e), query=query)
            return {"status": "error", "message": "Error searching Welfog knowledge base."}
