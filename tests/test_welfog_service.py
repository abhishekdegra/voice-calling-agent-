"""Tests for Welfog Service wrappers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.welfog_service import WelfogService


@pytest.mark.asyncio
async def test_get_order_history_mock():
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"id": "ORD100", "grand_total": 1299, "status": "shipped"}],
        "meta": {"current_page": 1}
    }
    mock_client.get.return_value = mock_resp

    service = WelfogService(client=mock_client)
    res = await service.get_order_history(user_id=1, limit=5)
    assert res["success"] is True
    assert len(res["orders"]) == 1
    assert res["orders"][0]["id"] == "ORD100"


@pytest.mark.asyncio
async def test_get_order_tracking_mock():
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": "found",
        "current_order_status": "out_for_delivery",
        "expected_delivery": "2026-10-10",
        "tracking_code": "WF123456"
    }
    mock_client.post.return_value = mock_resp

    service = WelfogService(client=mock_client)
    res = await service.get_order_tracking(user_id=1, order_id="ORD100")
    assert res["success"] is True
    assert res["order_status"] == "out_for_delivery"
    assert res["tracking_code"] == "WF123456"


@pytest.mark.asyncio
async def test_refund_status_ownership_protection():
    # If ownership fails, it should reject before exposing data
    service = WelfogService()
    with patch.object(service, "_verify_customer_order", return_value=False):
        res = await service.get_refund_status(user_id=1, order_id="ORD999")
        assert res["success"] is False
        assert "ownership validation failed" in res["error"].lower()
