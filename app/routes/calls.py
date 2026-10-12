"""Call management endpoints for initiating and monitoring outbound AI calls."""

from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from app.models.call_session import CallSession
from app.models.call_outcome import CallOutcome
from app.services.voice_orchestrator import VoiceOrchestrator
from app.utils.security import is_valid_phone_number

router = APIRouter(prefix="/api/calls", tags=["Calls"])

# Global or dependency-injected orchestrator
_orchestrator = VoiceOrchestrator()


def get_orchestrator() -> VoiceOrchestrator:
    return _orchestrator


class InitiateCallRequest(BaseModel):
    user_id: int = Field(..., description="Welfog customer user ID")
    customer_phone: str = Field(..., description="Indian phone number (10 or 12 digits)")
    order_id: Optional[str] = Field(None, description="Order ID to discuss with customer")
    language: str = Field("Hindi", description="Preferred starting language")


@router.post("/outbound")
async def initiate_call(
    req: InitiateCallRequest,
    orch: VoiceOrchestrator = Depends(get_orchestrator)
) -> Dict[str, Any]:
    """
    Initiates an outbound AI call to a Welfog customer regarding their order.
    """
    if not is_valid_phone_number(req.customer_phone):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Indian phone number '{req.customer_phone}'. Must be a valid 10-digit mobile number."
        )

    # 1. Create call session
    session = orch.create_session(
        user_id=req.user_id,
        customer_phone=req.customer_phone,
        order_id=req.order_id,
        language=req.language
    )

    # 2. Trigger TeleCMI outbound call
    result = await orch.initiate_outbound_call(session.call_id)
    if not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=f"TeleCMI failed to initiate call: {result.get('error')}"
        )

    return {
        "status": "initiated",
        "call_id": session.call_id,
        "customer_phone": session.customer_phone,
        "order_id": session.order_id,
        "telecmi_call_id": session.telecmi_call_id
    }


@router.get("/{call_id}")
async def get_call_session(
    call_id: str,
    orch: VoiceOrchestrator = Depends(get_orchestrator)
) -> CallSession:
    """Retrieve current state and tool execution logs for a call."""
    session = orch.get_session(call_id)
    if not session:
        raise HTTPException(status_code=404, detail="Call session not found")
    return session


@router.get("/{call_id}/outcome")
async def get_call_outcome(
    call_id: str,
    orch: VoiceOrchestrator = Depends(get_orchestrator)
) -> CallOutcome:
    """Retrieve final structured outcome of the call."""
    outcome = orch.outcomes.get(call_id)
    if not outcome:
        session = orch.get_session(call_id)
        if not session:
            raise HTTPException(status_code=404, detail="Call outcome not found")
        return orch._finalize_outcome(session, "in-progress outcome inquiry", True)
    return outcome
