"""Call outcome structured summary model."""

from typing import Optional
from pydantic import BaseModel, Field


class CallOutcome(BaseModel):
    call_id: str
    call_status: str  # completed, failed, no_answer, busy, customer_declined, etc.
    intent: str = "order_confirmation"  # order_confirmation, order_tracking, refund_question, policy_question, etc.
    customer_language: str = "Hindi"
    order_id: Optional[str] = None
    resolution: str = "completed"  # confirmed, answered, escalated, declined, unresolved
    escalation_required: bool = False
    notes: Optional[str] = None
    duration_seconds: Optional[float] = None
