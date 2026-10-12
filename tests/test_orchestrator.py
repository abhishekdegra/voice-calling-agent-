"""Tests for Voice Orchestrator lifecycle and tool dispatching."""

import pytest
from app.models.call_session import CallState
from app.services.voice_orchestrator import VoiceOrchestrator


def test_session_creation_and_state_transitions():
    orch = VoiceOrchestrator()
    session = orch.create_session(user_id=1, customer_phone="9876543210", order_id="ORD123")

    assert session.customer_phone == "919876543210"
    assert session.status == CallState.CREATED
    assert session.user_id == 1
    assert session.order_id == "ORD123"

    session.transition_to(CallState.CALLING)
    assert session.status == CallState.CALLING

    session.transition_to(CallState.ANSWERED)
    assert session.status == CallState.ANSWERED

    session.transition_to(CallState.COMPLETED)
    assert session.status == CallState.COMPLETED
    assert session.ended_at is not None

    outcome = orch._finalize_outcome(session, "test completion", True)
    assert outcome.call_id == session.call_id
    assert outcome.call_status == "completed"
    assert outcome.resolution == "completed"
    assert outcome.escalation_required is False
