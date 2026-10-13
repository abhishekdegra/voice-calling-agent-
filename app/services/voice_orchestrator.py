"""Voice Orchestrator managing bidirectional audio streaming between TeleCMI and Gemini Live."""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, Optional
from fastapi import WebSocket, WebSocketDisconnect
from google.genai import types

from app.config import get_settings
from app.models.call_session import CallSession, CallState
from app.models.call_outcome import CallOutcome
from app.services.gemini_service import GeminiService
from app.services.telecmi_service import TeleCMIService
from app.tools.order_tools import OrderTools
from app.tools.knowledge_tools import KnowledgeTools
from app.utils.audio import AudioAdapter
from app.utils.logging import logger
from app.utils.security import normalize_indian_phone_number


class VoiceOrchestrator:
    """
    Central orchestrator coordinating:
    - TeleCMI call setup & events
    - Real-time customer audio streaming
    - Gemini Multimodal Live API streaming
    - Tool invocation (Welfog Order APIs + Qdrant RAG)
    - Audio format adaptation & resampling
    - Call lifecycle state & outcomes
    """

    def __init__(
        self,
        gemini_service: Optional[GeminiService] = None,
        telecmi_service: Optional[TeleCMIService] = None,
        order_tools: Optional[OrderTools] = None,
        knowledge_tools: Optional[KnowledgeTools] = None
    ):
        self.settings = get_settings()
        self.gemini_service = gemini_service or GeminiService()
        self.telecmi_service = telecmi_service or TeleCMIService()
        self.order_tools = order_tools or OrderTools()
        self.knowledge_tools = knowledge_tools or KnowledgeTools()
        self.sessions: Dict[str, CallSession] = {}
        self.outcomes: Dict[str, CallOutcome] = {}

    def create_session(
        self,
        user_id: int,
        customer_phone: str,
        order_id: Optional[str] = None,
        language: str = "Hindi"
    ) -> CallSession:
        """Create and register a new call session."""
        call_id = f"welfog_call_{uuid.uuid4().hex[:12]}"
        normalized_phone = normalize_indian_phone_number(customer_phone)

        session = CallSession(
            call_id=call_id,
            user_id=user_id,
            order_id=order_id,
            customer_phone=normalized_phone,
            language=language,
            status=CallState.CREATED
        )
        self.sessions[call_id] = session
        logger.info(
            "call_session_created",
            call_id=call_id,
            user_id=user_id,
            order_id=order_id,
            extra={"phone": normalized_phone, "language": language}
        )
        return session

    def get_session(self, call_id: str) -> Optional[CallSession]:
        return self.sessions.get(call_id)

    async def initiate_outbound_call(self, call_id: str) -> Dict[str, Any]:
        """Trigger TeleCMI outbound call and command stream to our WebSocket."""
        session = self.get_session(call_id)
        if not session:
            return {"success": False, "error": f"Session {call_id} not found"}

        session.transition_to(CallState.CALLING)
        logger.info("initiating_telecmi_call", call_id=call_id, user_id=session.user_id)

        ws_url = f"{self.settings.telecmi_websocket_url}?call_id={call_id}"

        res = await self.telecmi_service.initiate_streaming_call(
            customer_phone=session.customer_phone,
            custom_websocket_url=ws_url,
            extra_param=call_id
        )

        if res.get("success"):
            session.telecmi_call_id = str(res.get("call_id") or "")
            session.transition_to(CallState.RINGING)
            return {"success": True, "call_id": call_id, "telecmi_response": res}
        else:
            session.transition_to(CallState.FAILED)
            self._finalize_outcome(session, "telephony_initiation_failed", False)
            return {"success": False, "error": res.get("error")}

    async def handle_telecmi_stream(
        self,
        websocket: WebSocket,
        call_id: Optional[str] = None
    ):
        """
        Main WebSocket pipeline connecting TeleCMI call audio <-> Gemini Live API.
        """
        await websocket.accept()

        query_params = dict(websocket.query_params)
        extracted_order = query_params.get("order_id") or query_params.get("call_id") or (call_id if call_id and not call_id.startswith("test") else None) or "WF-10928"
        extracted_phone = query_params.get("phone") or "9876543210"
        extracted_name = query_params.get("name") or "Customer"
        extracted_address = query_params.get("address") or query_params.get("notes") or ""

        from app.services.db_service import get_db_service
        try:
            db = get_db_service()
            clean_digits = "".join(c for c in extracted_phone if c.isdigit())
            if len(clean_digits) == 12 and clean_digits.startswith("91"):
                clean_digits = clean_digits[2:]
            matching = await db.get_customers(search=clean_digits)
            if matching:
                cust = matching[0]
                if cust.get("name") and cust["name"] != "Customer":
                    extracted_name = cust["name"]
                if cust.get("notes") and cust["notes"] not in {"Bulk Import", "Bulk Pasted"}:
                    extracted_address = cust["notes"]
                if cust.get("order_id"):
                    extracted_order = cust["order_id"]
        except Exception as e:
            logger.warning("db_customer_lookup_fallback", error=str(e))

        if not extracted_address or extracted_address in {"Bulk Import", "Bulk Pasted"}:
            extracted_address = "Plot 42, Near Metro Station, Mansarovar, Jaipur (302020)"

        session: Optional[CallSession] = None
        if call_id and call_id in self.sessions:
            session = self.sessions[call_id]
        elif self.sessions:
            for s in reversed(list(self.sessions.values())):
                if s.status in {CallState.CREATED, CallState.CALLING, CallState.RINGING}:
                    session = s
                    break

        if not session:
            session = self.create_session(
                user_id=1,
                customer_phone=extracted_phone,
                order_id=extracted_order
            )
        else:
            if extracted_order and not session.order_id:
                session.order_id = extracted_order

        session.metadata["customer_name"] = extracted_name
        session.metadata["delivery_address"] = extracted_address

        session.transition_to(CallState.ANSWERED)
        logger.info(
            "telecmi_websocket_connected",
            call_id=session.call_id,
            order_id=session.order_id,
            extra={"customer": extracted_name, "address": extracted_address}
        )

        audio_adapter = AudioAdapter(
            telecmi_sample_rate=16000,
            gemini_input_sample_rate=16000,
            gemini_output_sample_rate=24000
        )

        if not self.gemini_service.is_configured():
            logger.error("gemini_not_configured_for_stream", call_id=session.call_id)
            session.transition_to(CallState.FAILED)
            await websocket.close(code=1011, reason="Gemini API Key unconfigured")
            self._finalize_outcome(session, "gemini_unconfigured", False)
            return

        session.transition_to(CallState.AI_SESSION_STARTED)
        gemini_client = self.gemini_service.get_client()
        live_config = self.gemini_service.build_live_config(
            customer_name=extracted_name,
            order_id=extracted_order,
            customer_phone=extracted_phone,
            delivery_address=extracted_address,
            include_tools=True
        )
        model_id = self.settings.gemini_live_model

        try:
            async with gemini_client.aio.live.connect(model=model_id, config=live_config) as gemini_session:
                session.transition_to(CallState.CONVERSATION_ACTIVE)
                logger.info("gemini_live_session_active", call_id=session.call_id)

                pickup_event = asyncio.Event()
                session.metadata["pickup_event"] = pickup_event

                greeting_task = asyncio.create_task(
                    self._await_pickup_and_greet(
                        gemini_session=gemini_session,
                        session=session,
                        pickup_event=pickup_event,
                        customer_name=extracted_name,
                        order_id=extracted_order
                    )
                )

                stream_in_task = asyncio.create_task(
                    self._customer_to_gemini(websocket, gemini_session, audio_adapter, session, pickup_event)
                )
                stream_out_task = asyncio.create_task(
                    self._gemini_to_customer(websocket, gemini_session, audio_adapter, session)
                )
                silence_task = asyncio.create_task(
                    self._monitor_silence(websocket, gemini_session, session, pickup_event)
                )

                done, pending = await asyncio.wait(
                    [stream_in_task, stream_out_task, silence_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                greeting_task.cancel()
                for task in pending:
                    task.cancel()

                for task in done:
                    if not task.cancelled():
                        exc = task.exception()
                        if exc:
                            raise exc

        except WebSocketDisconnect:
            logger.info("telecmi_call_hung_up", call_id=session.call_id)
            session.transition_to(CallState.DISCONNECTED)
        except Exception as e:
            logger.error("voice_orchestrator_stream_error", call_id=session.call_id, error=str(e))
            session.transition_to(CallState.FAILED)
        finally:
            if session.status not in {CallState.COMPLETED, CallState.FAILED, CallState.DISCONNECTED}:
                session.transition_to(CallState.COMPLETED)
            self._finalize_outcome(session, "conversation_completed", True)

    async def _await_pickup_and_greet(
        self,
        gemini_session: Any,
        session: CallSession,
        pickup_event: asyncio.Event,
        customer_name: str,
        order_id: str
    ):
        """Wait for customer pickup signal before triggering Priya opening greeting."""
        try:
            await asyncio.wait_for(pickup_event.wait(), timeout=60.0)
            session.transition_to(CallState.ANSWERED)
            logger.info("customer_answered_triggering_opening_greeting", call_id=session.call_id)

            await asyncio.sleep(0.4)

            name_greeting = customer_name if customer_name != "Customer" else "Sir"
            greeting_instruction = (
                f"Customer {name_greeting} has just answered the call. "
                f"Introduce yourself warmly and naturally as Priya from Welfog store regarding order {order_id}. "
                "Greet them politely and ask naturally if they placed this order and if everything is good for delivery confirmation. "
                "Keep it short (1 to 2 spoken sentences), warm, and human-like. Do not read rigid scripts or output markdown."
            )
            await gemini_session.send_client_content(
                turns=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=greeting_instruction)]
                    )
                ],
                turn_complete=True
            )
            logger.info("opening_greeting_dispatched_to_gemini", call_id=session.call_id)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.error("greeting_trigger_error", call_id=session.call_id, error=str(e))

    async def _customer_to_gemini(
        self,
        websocket: WebSocket,
        gemini_session: Any,
        audio_adapter: AudioAdapter,
        session: CallSession,
        pickup_event: asyncio.Event
    ):
        """Receive audio bytes from TeleCMI, filter background noise, and stream to Gemini Live."""
        try:
            chunks_received = 0
            session.metadata["last_customer_speech_time"] = time.time()
            session.metadata["silence_prompt_count"] = 0

            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    logger.info("websocket_disconnect_received", call_id=session.call_id)
                    break

                if "bytes" in message and message["bytes"]:
                    if not pickup_event.is_set():
                        pickup_event.set()
                    raw_audio = message["bytes"]
                    pcm16 = audio_adapter.telecmi_to_gemini(raw_audio)
                    if pcm16:
                        chunks_received += 1
                        is_ai_speaking = bool(session.metadata.get("is_ai_speaking", False))
                        last_ai_audio = session.metadata.get("last_ai_audio_time", 0.0)
                        if is_ai_speaking and (time.time() - last_ai_audio > 0.8):
                            is_ai_speaking = False
                            session.metadata["is_ai_speaking"] = False

                        gated_pcm, is_speech = audio_adapter.process_incoming_pcm(
                            pcm16, 
                            is_ai_speaking=is_ai_speaking
                        )
                        if is_speech:
                            session.metadata["last_customer_speech_time"] = time.time()
                            session.metadata["silence_prompt_count"] = 0
                            session.metadata["call_concluded"] = False
                            session.metadata.pop("farewell_time", None)

                        if chunks_received % 50 == 0:
                            logger.info(
                                "forwarding_customer_audio_to_gemini",
                                call_id=session.call_id,
                                chunks=chunks_received,
                                is_speech=is_speech,
                                is_ai_speaking=is_ai_speaking
                            )
                        if gated_pcm:
                            await gemini_session.send_realtime_input(
                                audio=types.Blob(data=gated_pcm, mime_type="audio/pcm;rate=16000")
                            )
                elif "text" in message and message["text"]:
                    try:
                        data = json.loads(message["text"])
                        event = (data.get("event") or data.get("action") or "").lower()
                        if event in ("call_answered", "answered", "call_connected", "connected", "start", "answer"):
                            if not pickup_event.is_set():
                                pickup_event.set()
                        elif event in ("stop", "hangup"):
                            logger.info("telecmi_hangup_event", call_id=session.call_id)
                            break
                        elif event == "media" and "payload" in data:
                            if not pickup_event.is_set():
                                pickup_event.set()
                            import base64
                            raw_audio = base64.b64decode(data["payload"])
                            pcm16 = audio_adapter.telecmi_to_gemini(raw_audio)
                            if pcm16:
                                is_ai_speaking = bool(session.metadata.get("is_ai_speaking", False))
                                last_ai_audio = session.metadata.get("last_ai_audio_time", 0.0)
                                if is_ai_speaking and (time.time() - last_ai_audio > 0.8):
                                    is_ai_speaking = False
                                    session.metadata["is_ai_speaking"] = False

                                gated_pcm, is_speech = audio_adapter.process_incoming_pcm(
                                    pcm16, 
                                    is_ai_speaking=is_ai_speaking
                                )
                                if is_speech:
                                    session.metadata["last_customer_speech_time"] = time.time()
                                    session.metadata["silence_prompt_count"] = 0
                                    session.metadata["call_concluded"] = False
                                    session.metadata.pop("farewell_time", None)

                                if gated_pcm:
                                    await gemini_session.send_realtime_input(
                                        audio=types.Blob(data=gated_pcm, mime_type="audio/pcm;rate=16000")
                                    )
                    except json.JSONDecodeError:
                        pass
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass

    async def _gemini_to_customer(
        self,
        websocket: WebSocket,
        gemini_session: Any,
        audio_adapter: AudioAdapter,
        session: CallSession
    ):
        """Receive audio & tool calls from Gemini Live across all conversational turns and stream audio to TeleCMI."""
        try:
            while True:
                if session.status in {CallState.COMPLETED, CallState.DISCONNECTED, CallState.FAILED}:
                    break

                try:
                    async for response in gemini_session.receive():
                        server_content = getattr(response, "server_content", None)
                        if server_content:
                            if getattr(server_content, "interrupted", False):
                                session.metadata["is_ai_speaking"] = False
                                logger.info("gemini_speech_interrupted_by_customer", call_id=session.call_id)
                                try:
                                    await websocket.send_text(json.dumps({"event": "interrupted"}))
                                except Exception:
                                    pass

                            model_turn = getattr(server_content, "model_turn", None)
                            if model_turn:
                                for part in getattr(model_turn, "parts", []):
                                    inline_data = getattr(part, "inline_data", None)
                                    if inline_data and getattr(inline_data, "data", None):
                                        session.metadata["is_ai_speaking"] = True
                                        session.metadata["last_ai_audio_time"] = time.time()
                                        raw_gemini_pcm = inline_data.data
                                        telecmi_audio = audio_adapter.gemini_to_telecmi(raw_gemini_pcm)
                                        if telecmi_audio:
                                            try:
                                                await websocket.send_bytes(telecmi_audio)
                                            except (WebSocketDisconnect, RuntimeError):
                                                logger.info("telecmi_ws_closed_during_audio_send", call_id=session.call_id)
                                                return
                                            except Exception as send_err:
                                                logger.warning("failed_sending_telecmi_audio", error=str(send_err))
                                    elif getattr(part, "text", None):
                                        try:
                                            await websocket.send_text(json.dumps({"event": "ai_transcript", "text": part.text}))
                                        except Exception:
                                            pass

                            if getattr(server_content, "turn_complete", False):
                                session.metadata["is_ai_speaking"] = False
                                logger.info("gemini_turn_completed_listening_to_customer", call_id=session.call_id)
                                try:
                                    await websocket.send_text(json.dumps({"event": "turn_complete"}))
                                except Exception:
                                    pass

                                # If farewell was spoken or end_call invoked, start post-farewell silence watch
                                # NEVER cut the call immediately! Line stays alive.
                                if session.metadata.get("call_concluded"):
                                    session.metadata["farewell_time"] = time.time()

                        tool_call = getattr(response, "tool_call", None)
                        if tool_call:
                            session.metadata["is_ai_speaking"] = False
                            session.transition_to(CallState.TOOL_CALL)
                            function_responses = []

                            for call in getattr(tool_call, "function_calls", []):
                                fn_name = call.name
                                fn_args = call.args or {}
                                call_id_val = call.id

                                logger.info(
                                    "executing_gemini_tool",
                                    call_id=session.call_id,
                                    tool_name=fn_name,
                                    extra={"args": fn_args}
                                )
                                try:
                                    await websocket.send_text(json.dumps({"event": "tool_calling", "tool": fn_name}))
                                except Exception:
                                    pass

                                t_start = time.perf_counter()
                                tool_result = await self._execute_tool(fn_name, fn_args, session)
                                latency_ms = (time.perf_counter() - t_start) * 1000

                                session.record_tool_call(fn_name, fn_args, tool_result, latency_ms)

                                function_responses.append(
                                    types.FunctionResponse(
                                        name=fn_name,
                                        id=call_id_val,
                                        response={"result": tool_result}
                                    )
                                )

                            session.transition_to(CallState.TOOL_RESULT)
                            await gemini_session.send_tool_response(function_responses=function_responses)
                            session.transition_to(CallState.CONVERSATION_ACTIVE)

                except (WebSocketDisconnect, asyncio.CancelledError):
                    raise
                except Exception as stream_err:
                    logger.warning("gemini_receive_turn_cycle_warning", call_id=session.call_id, error=str(stream_err))
                    if "closed" in str(stream_err).lower() or "1007" in str(stream_err):
                        break
                    await asyncio.sleep(0.05)

        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.error("voice_orchestrator_gemini_to_customer_error", call_id=session.call_id, error=str(e))

    async def _monitor_silence(
        self,
        websocket: WebSocket,
        gemini_session: Any,
        session: CallSession,
        pickup_event: asyncio.Event
    ):
        """
        Proactive Silence & Call Concluding Watcher:
        1. If conversation has reached farewell (order confirmed/cancelled), wait for 7 FULL SECONDS
           of true silence from the customer before disconnecting.
        2. If customer speaks at ANY point during or after farewell, the hangup is CANCELLED immediately.
        3. Mid-call silence:
           - 15s silence: Priya prompts 'Hello sir, kya aap mujhe sun pa rahe hain?'
           - 27s total silence: Priya delivers polite goodbye, waits 5s of silence, then disconnects.
        """
        try:
            await pickup_event.wait()
            # Wait 8s grace period after customer pickup for opening greeting to begin
            await asyncio.sleep(8.0)
            session.metadata.setdefault("last_customer_speech_time", time.time())
            session.metadata.setdefault("silence_prompt_count", 0)

            while True:
                await asyncio.sleep(1.0)
                if session.status in {CallState.COMPLETED, CallState.DISCONNECTED, CallState.FAILED}:
                    break

                # Post-farewell silence check:
                # Disconnect ONLY IF customer has stayed completely silent for 7 seconds after farewell!
                if session.metadata.get("call_concluded") and session.metadata.get("farewell_time"):
                    farewell_t = session.metadata["farewell_time"]
                    last_speech = session.metadata.get("last_customer_speech_time", farewell_t)
                    silence_since_farewell = time.time() - max(farewell_t, last_speech)
                    if silence_since_farewell >= 7.0:
                        reason = session.metadata.get("concluded_reason", "completed")
                        logger.info("silence_watcher_concluding_after_7s_farewell_silence", call_id=session.call_id, reason=reason)
                        try:
                            await websocket.send_text(json.dumps({
                                "event": "hangup",
                                "reason": reason,
                                "delay_ms": 500
                            }))
                        except Exception:
                            pass
                        break
                    continue

                # If AI is currently speaking, do not count silence against caller
                if session.metadata.get("is_ai_speaking"):
                    session.metadata["last_customer_speech_time"] = time.time()
                    continue

                silence_duration = time.time() - session.metadata.get("last_customer_speech_time", time.time())
                prompt_count = session.metadata.get("silence_prompt_count", 0)

                # Tier 1 Mid-call silence check (15 seconds of dead silence)
                if silence_duration >= 15.0 and prompt_count == 0:
                    session.metadata["silence_prompt_count"] = 1
                    session.metadata["last_customer_speech_time"] = time.time()
                    logger.info("silence_watcher_prompting_unresponsive_caller", call_id=session.call_id, silence_sec=silence_duration)
                    try:
                        await gemini_session.send_client_content(
                            turns=[
                                types.Content(
                                    role="user",
                                    parts=[types.Part.from_text(
                                        text="[The customer has been silent for 15 seconds. In 1 short polite Hindi sentence, check if they can hear you: 'Hello sir, kya aap mujhe sun pa rahe hain?']"
                                    )]
                                )
                            ],
                            turn_complete=True
                        )
                    except Exception as e:
                        logger.warning("silence_tier1_prompt_error", error=str(e))

                # Tier 2 Mid-call silence check (Customer remained silent for 12s after Tier 1 prompt)
                elif silence_duration >= 12.0 and prompt_count == 1:
                    session.metadata["silence_prompt_count"] = 2
                    session.metadata["call_concluded"] = True
                    session.metadata["concluded_time"] = time.time()
                    session.metadata["concluded_reason"] = "no_response"
                    logger.info("silence_watcher_concluding_silent_call", call_id=session.call_id)
                    try:
                        await gemini_session.send_client_content(
                            turns=[
                                types.Content(
                                    role="user",
                                    parts=[types.Part.from_text(
                                        text="[Customer is still unresponsive. Say politely: 'Theek hai sir, lagta hai aap busy hain ya call disconnect ho gayi hai. Have a nice day sir!' and conclude.]"
                                    )]
                                )
                            ],
                            turn_complete=True
                        )
                    except Exception as e:
                        logger.warning("silence_tier2_prompt_error", error=str(e))

                    # Set farewell_time to now, allowing 6s silence watch before cutting
                    session.metadata["farewell_time"] = time.time()

        except (asyncio.CancelledError, WebSocketDisconnect):
            pass
        except Exception as e:
            logger.error("silence_watcher_error", call_id=session.call_id, error=str(e))

    async def _execute_tool(
        self,
        name: str,
        args: Dict[str, Any],
        session: CallSession
    ) -> Dict[str, Any]:
        """Dispatch tool calls securely with customer session isolation."""
        user_id = session.user_id
        order_id = args.get("order_id") or session.order_id

        if name == "get_order_tracking":
            session.current_intent = "order_tracking"
            return await self.order_tools.get_order_tracking(user_id=user_id, order_id=str(order_id or ""))
        elif name == "get_order_details":
            session.current_intent = "order_details"
            return await self.order_tools.get_order_details(user_id=user_id, order_id=str(order_id or ""))
        elif name == "get_order_history":
            session.current_intent = "order_history"
            limit = int(args.get("limit", 5))
            return await self.order_tools.get_order_history(user_id=user_id, limit=limit)
        elif name == "get_refund_status":
            session.current_intent = "refund_status"
            return await self.order_tools.get_refund_status(user_id=user_id, order_id=str(order_id or ""))
        elif name == "get_invoice":
            session.current_intent = "invoice"
            return await self.order_tools.get_invoice(user_id=user_id, order_id=str(order_id or ""))
        elif name == "search_welfog_knowledge":
            session.current_intent = "knowledge_policy"
            query = args.get("query", "")
            return await self.knowledge_tools.search_welfog_knowledge(query=str(query))
        elif name == "end_call":
            session.current_intent = "call_ended"
            reason = args.get("reason", "order_confirmed")
            session.metadata["call_concluded"] = True
            session.metadata["concluded_time"] = time.time()
            session.metadata["concluded_reason"] = reason
            logger.info("gemini_tool_end_call_invoked", call_id=session.call_id, reason=reason)
            return {"status": "success", "message": f"Farewell recorded: {reason}. Watching for customer response before closing."}
        else:
            return {"status": "error", "message": f"Unknown tool: {name}"}

    def _finalize_outcome(self, session: CallSession, notes: str, success: bool):
        """Construct structured outcome report for the call session."""
        duration = None
        if session.started_at and session.ended_at:
            duration = (session.ended_at - session.started_at).total_seconds()

        outcome = CallOutcome(
            call_id=session.call_id,
            call_status=session.status.value.lower(),
            intent=session.current_intent or "order_confirmation",
            customer_language=session.language,
            order_id=session.order_id,
            resolution="completed" if success else "failed",
            escalation_required=not success,
            notes=notes,
            duration_seconds=duration
        )
        self.outcomes[session.call_id] = outcome
        logger.info(
            "call_outcome_finalized",
            call_id=session.call_id,
            order_id=session.order_id,
            user_id=session.user_id,
            extra=outcome.model_dump()
        )
        return outcome
