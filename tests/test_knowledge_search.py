"""Tests for Welfog Knowledge Search API integration."""

import pytest
from app.services.knowledge_service import (
    KnowledgeSearchService,
    search_welfog_knowledge,
    search_welfog_knowledge_async,
)


@pytest.mark.asyncio
async def test_live_welfog_knowledge_search_refund_policy():
    """
    Verifies that calling the existing Welfog Knowledge Search API
    with 'What is our refund policy?' returns valid knowledge chunks from Qdrant.
    """
    service = KnowledgeSearchService()
    try:
        res = await service.search_async("What is our refund policy?", limit=3)
        
        # Verify HTTP and API response
        assert res["ok"] is True, f"Search failed with error: {res.get('error')}"
        assert res["found"] > 0, "Expected at least 1 document chunk found"
        assert len(res["results"]) > 0, "Expected non-empty results array"
        assert len(res["context"]) > 50, "Expected non-empty context string"
        
        # Verify content relevance
        top_result = res["results"][0]
        assert "title" in top_result
        assert "text" in top_result
        assert "score" in top_result
        
        # Check that top results mention refund/return policies
        combined_text = " ".join([r.get("text", "") for r in res["results"]]).lower()
        assert "refund" in combined_text or "return" in combined_text, (
            "Expected results to contain refund or return policy terms"
        )
    finally:
        await service.close()


def test_sync_welfog_knowledge_search():
    """Verify synchronous helper works cleanly."""
    res = search_welfog_knowledge("refund policy", limit=2)
    assert res["ok"] is True
    assert res["found"] > 0
    assert len(res["results"]) > 0
