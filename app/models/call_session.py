"""Call session models and state machine definitions."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CallState(str, Enum):
    CREATED = "CREATED"
    CALLING = "CALLING"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    AI_SESSION_STARTED = "AI_SESSION_STARTED"
    CONVERSATION_ACTIVE = "CONVERSATION_ACTIVE"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NO_ANSWER = "NO_ANSWER"
    BUSY = "BUSY"
    DISCONNECTED = "DISCONNECTED"


class CallSession(BaseModel):
    call_id: str
    user_id: int
    order_id: Optional[str] = None
    customer_phone: str
    telecmi_call_id: Optional[str] = None
    language: str = "Hindi"
    status: CallState = CallState.CREATED
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    current_intent: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def transition_to(self, new_status: CallState):
        """Update call state safely."""
        self.status = new_status
        if new_status in {
            CallState.COMPLETED,
            CallState.FAILED,
            CallState.NO_ANSWER,
            CallState.BUSY,
            CallState.DISCONNECTED
        } and not self.ended_at:
            self.ended_at = datetime.now(timezone.utc)

    def record_tool_call(self, tool_name: str, args: Dict[str, Any], result: Any, latency_ms: float):
        """Record structured tool call metrics."""
        self.tool_calls.append({
            "tool": tool_name,
            "args": args,
            "result": result,
            "latency_ms": latency_ms,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
