"""Tests for controlled OrderTools and KnowledgeTools."""

import pytest
from unittest.mock import AsyncMock
from app.tools.order_tools import OrderTools
from app.tools.knowledge_tools import KnowledgeTools


@pytest.mark.asyncio
async def test_order_tools_tracking():
    mock_welfog = AsyncMock()
    mock_welfog.get_order_tracking.return_value = {
        "success": True,
        "data": {
            "current_order_status": "shipped",
            "expected_delivery": "2026-10-15",
            "tracking_code": "TRACK888",
            "product_title": "Cotton T-Shirt"
        }
    }

    tools = OrderTools(welfog_service=mock_welfog)
    res = await tools.get_order_tracking(user_id=1, order_id="123")
    assert res["status"] == "success"
    assert res["current_status"] == "shipped"
    assert res["tracking_code"] == "TRACK888"


@pytest.mark.asyncio
async def test_knowledge_tools_fallback():
    mock_qdrant = AsyncMock()
    mock_qdrant.search_knowledge.return_value = {
        "success": False,
        "configured": False,
        "chunks": []
    }

    tools = KnowledgeTools(qdrant_service=mock_qdrant)
    res = await tools.search_welfog_knowledge(query="what is return policy?")
    assert res["status"] == "success"
    assert "7 days" in res["information"]
