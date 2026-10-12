"""WebSocket endpoint for real-time TeleCMI bidirectional audio streaming."""

from typing import Optional
from fastapi import APIRouter, WebSocket, Query

from app.routes.calls import get_orchestrator
from app.utils.logging import logger

router = APIRouter(tags=["Streaming"])


@router.websocket("/ws/telecmi")
async def telecmi_audio_stream(
    websocket: WebSocket,
    call_id: Optional[str] = Query(None)
):
    """
    WebSocket streaming endpoint.
    TeleCMI streams live customer audio to this endpoint, and receives Gemini response audio.
    """
    logger.info("incoming_telecmi_websocket", call_id=call_id)
    orch = get_orchestrator()
    await orch.handle_telecmi_stream(websocket, call_id=call_id)
