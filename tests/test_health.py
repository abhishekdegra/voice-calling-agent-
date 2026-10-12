"""Tests for health check endpoints."""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data == {"status": "ok"}


@pytest.mark.asyncio
async def test_integrations_diagnostic_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/integrations")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "integrations" in data
        assert "telecmi" in data["integrations"]
        assert "welfog_api" in data["integrations"]
