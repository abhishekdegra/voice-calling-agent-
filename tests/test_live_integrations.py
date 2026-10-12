"""Live integration tests against external Welfog and TeleCMI endpoints."""

import pytest
from app.services.telecmi_service import TeleCMIService
from app.services.welfog_service import WelfogService


@pytest.mark.asyncio
async def test_live_telecmi_token():
    """Verify TeleCMI token generation against live TeleCMI REST API."""
    service = TeleCMIService()
    token = await service.get_app_token(force_refresh=True)
    await service.close()
    assert token is not None
    assert len(token) > 20


@pytest.mark.asyncio
async def test_live_telecmi_user_login():
    """Verify agent login against live TeleCMI REST API."""
    service = TeleCMIService()
    login_res = await service.agent_login()
    await service.close()
    assert login_res["success"] is True
    assert "agent" in login_res
    assert login_res["agent"]["id"] == "5002_33338876"


@pytest.mark.asyncio
async def test_live_welfog_purchase_history():
    """Verify purchase history against live Welfog API."""
    service = WelfogService()
    res = await service.get_order_history(user_id=1, limit=5)
    await service.close()
    assert res["success"] is True
    assert isinstance(res["orders"], list)


@pytest.mark.asyncio
async def test_live_welfog_order_track():
    """Verify order tracking endpoint against live Welfog tracking API."""
    service = WelfogService()
    res = await service.get_order_tracking(user_id=1, order_id="TEST_SAMPLE")
    await service.close()
    assert res["success"] is True
    assert "data" in res
