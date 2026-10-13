"""Tests for Voice Orchestrator lifecycle and tool dispatching."""

import pytest
from app.models.call_session import CallState
from app.services.voice_orchestrator import VoiceOrchestrator
from app.services.gemini_service import GeminiService, get_gemini_tools
from google.genai import types


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


@pytest.mark.asyncio
async def test_end_call_tool_execution():
    orch = VoiceOrchestrator()
    session = orch.create_session(user_id=1, customer_phone="9876543210", order_id="WF-10928")
    
    # Execute end_call tool
    result = await orch._execute_tool("end_call", {"reason": "order_confirmed"}, session)
    assert result["status"] == "success"
    assert session.metadata.get("call_concluded") is True
    assert session.metadata.get("concluded_reason") == "order_confirmed"
    assert session.metadata.get("concluded_time") is not None


def test_gemini_tools_and_live_config_latency():
    # Verify end_call is in declared tools
    tools = get_gemini_tools()
    tool_names = [fn.name for t in tools for fn in t.function_declarations]
    assert "end_call" in tool_names
    assert "get_order_details" in tool_names
    assert "get_order_tracking" in tool_names

    # Verify live config has low-latency VAD settings
    service = GeminiService(api_key="dummy_key_for_test")
    config = service.build_live_config(
        customer_name="Abhishek",
        order_id="WF-10928"
    )
    assert config.realtime_input_config is not None
    vad = config.realtime_input_config.automatic_activity_detection
    assert vad.end_of_speech_sensitivity == types.EndSensitivity.END_SENSITIVITY_HIGH
    assert vad.silence_duration_ms == 650
