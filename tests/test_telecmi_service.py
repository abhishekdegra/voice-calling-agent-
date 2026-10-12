"""Tests for TeleCMI telephony service."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.telecmi_service import TeleCMIService


@pytest.mark.asyncio
async def test_get_app_token_mock():
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "code": 200,
        "secret": "mock_jwt_token_12345",
        "expiresIn": "30d"
    }
    mock_client.post.return_value = mock_resp

    service = TeleCMIService(client=mock_client)
    token = await service.get_app_token(force_refresh=True)
    assert token == "mock_jwt_token_12345"


@pytest.mark.asyncio
async def test_initiate_streaming_call_payload():
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"code": 200, "call_id": "cmi_call_999"}
    mock_client.post.return_value = mock_resp

    service = TeleCMIService(client=mock_client)
    res = await service.initiate_streaming_call(
        customer_phone="9876543210",
        custom_websocket_url="wss://test.domain/ws/telecmi"
    )

    assert res["success"] is True
    assert res["customer_phone"] == "919876543210"
    assert res["call_id"] == "cmi_call_999"

    # Verify PCMO payload sent to TeleCMI
    call_args = mock_client.post.call_args
    assert call_args is not None
    json_data = call_args[1]["json"]
    assert json_data["to"] == 919876543210
    assert len(json_data["pcmo"]) == 1
    assert json_data["pcmo"][0]["action"] == "stream"
    assert json_data["pcmo"][0]["ws_url"] == "wss://test.domain/ws/telecmi"
