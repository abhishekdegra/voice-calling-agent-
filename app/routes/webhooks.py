"""TeleCMI webhook endpoints for CDR, call state, and recording events."""

from typing import Any, Dict
from fastapi import APIRouter, Request

from app.models.call_session import CallState
from app.routes.calls import get_orchestrator
from app.utils.logging import logger

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])


@router.post("/telecmi/events")
async def handle_telecmi_event(request: Request) -> Dict[str, Any]:
    """
    Receives call event callbacks from TeleCMI:
    - ringing
    - answered
    - completed / hangup
    - busy / no_answer
    """
    try:
        body = await request.json()
    except Exception:
        body = dict(await request.form())

    logger.info("telecmi_webhook_received", extra={"payload": body})

    call_id = body.get("extra_param") or body.get("call_id") or body.get("uuid")
    event = body.get("event") or body.get("status") or body.get("call_status")

    orch = get_orchestrator()
    if call_id and call_id in orch.sessions:
        session = orch.sessions[call_id]
        if event in {"answered", "connected"}:
            session.transition_to(CallState.ANSWERED)
            pickup_evt = session.metadata.get("pickup_event")
            if pickup_evt and not pickup_evt.is_set():
                pickup_evt.set()
        elif event in {"ringing"}:
            session.transition_to(CallState.RINGING)
        elif event in {"busy"}:
            session.transition_to(CallState.BUSY)
        elif event in {"no_answer", "timeout"}:
            session.transition_to(CallState.NO_ANSWER)
        elif event in {"completed", "hangup", "terminated"}:
            session.transition_to(CallState.COMPLETED)

    return {"status": "ok", "received": True}


@router.post("/telecmi/recording")
async def handle_telecmi_recording(request: Request) -> Dict[str, Any]:
    """
    Receives callback when TeleCMI finishes recording a call.
    """
    try:
        body = await request.json()
    except Exception:
        body = dict(await request.form())

    logger.info("telecmi_recording_callback", extra={"payload": body})
    return {"status": "ok", "recorded": True}
