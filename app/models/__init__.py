"""Models package for Welfog Voice Agent."""

from app.models.call_session import CallSession, CallState
from app.models.call_outcome import CallOutcome

__all__ = ["CallSession", "CallState", "CallOutcome"]
