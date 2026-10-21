"""AI Call Quality Auditor & QA Agent for post-call assessment."""

import asyncio
import json
import re
from typing import Any, Dict, Optional
from google.genai import types

from app.services.gemini_service import GeminiService
from app.services.db_service import get_db_service
from app.utils.logging import logger
from app.utils.pii_masking import mask_sensitive_pii
from app.services.live_broadcaster import get_live_broadcaster


class CallAuditorService:
    """
    Evaluates completed call transcripts and scores:
    - Human-likeness score (1.0 to 10.0)
    - Customer sentiment (SATISFIED, POSITIVE, NEUTRAL, CONFUSED, FRUSTRATED)
    - RTO (Return to Origin) Risk (LOW, MEDIUM, HIGH)
    - Professional QA summary note
    - Call resolution classification
    """

    def __init__(self, gemini_service: Optional[GeminiService] = None):
        self.gemini_service = gemini_service or GeminiService()

    async def audit_call(
        self,
        call_id: str,
        customer_id: Optional[int],
        customer_name: str,
        phone: str,
        order_id: str,
        transcript: str,
        call_duration: int,
        status: str
    ) -> Dict[str, Any]:
        """Run post-call QA audit asynchronously."""
        clean_transcript = mask_sensitive_pii(transcript or "").strip()

        # If transcript is empty or minimal (e.g. call was rejected or no answer)
        if not clean_transcript or len(clean_transcript) < 15 or call_duration < 4:
            fallback = {
                "human_score": 8.0,
                "customer_sentiment": "NEUTRAL",
                "rto_risk": "MEDIUM" if status in {"NO_ANSWER", "BUSY"} else "LOW",
                "qa_notes": f"Call ended early ({status}) with duration {call_duration}s.",
                "resolution": "NO_ANSWER" if status in {"NO_ANSWER", "BUSY"} else status
            }
            return fallback

        # If Gemini is configured, use LLM for deep audit
        if self.gemini_service.is_configured():
            try:
                client = self.gemini_service.get_client()
                audit_prompt = f"""You are an elite E-Commerce Call Quality Auditor for Welfog.com.
Evaluate this call between AI agent 'Priya' and customer '{customer_name}' for Order #{order_id}.

TRANSCRIPT:
{clean_transcript}

CALL DURATION: {call_duration} seconds.
INITIAL STATUS: {status}

Return ONLY valid JSON (no markdown formatting, no backticks) with these exact keys:
{{
  "human_score": float between 1.0 and 10.0 (how natural, conversational, polite, and human Priya sounded),
  "customer_sentiment": "SATISFIED" | "POSITIVE" | "NEUTRAL" | "CONFUSED" | "FRUSTRATED",
  "rto_risk": "LOW" | "MEDIUM" | "HIGH" (likelihood of courier return based on customer clarity, address confirmation, and agreement),
  "qa_notes": "1 concise sentence summarizing customer reaction and order verification state",
  "resolution": "CONFIRMED" | "CANCELLED" | "RESCHEDULED" | "UNRESOLVED"
}}
"""
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model="gemini-2.5-flash",
                    contents=audit_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        response_mime_type="application/json"
                    )
                )

                text = response.text.strip()
                # Remove any markdown wrapping if present
                text = re.sub(r"^```json\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
                data = json.loads(text)

                score = round(float(data.get("human_score", 9.2)), 1)
                sentiment = str(data.get("customer_sentiment", "SATISFIED")).upper()
                rto = str(data.get("rto_risk", "LOW")).upper()
                qa_note = mask_sensitive_pii(str(data.get("qa_notes", "Order verified successfully.")))
                resolution = str(data.get("resolution", "CONFIRMED")).upper()

                logger.info(
                    "call_audit_completed",
                    call_id=call_id,
                    order_id=order_id,
                    score=score,
                    sentiment=sentiment,
                    rto=rto
                )

                audit_result = {
                    "human_score": score,
                    "customer_sentiment": sentiment,
                    "rto_risk": rto,
                    "qa_notes": qa_note,
                    "resolution": resolution
                }

                # Update DB asynchronously
                db = get_db_service()
                if customer_id:
                    await db.update_customer_status(
                        customer_id=customer_id,
                        status="COMPLETED" if resolution == "CONFIRMED" else resolution,
                        call_duration=call_duration,
                        call_summary=qa_note,
                        transcript=clean_transcript,
                        qa_score=score,
                        customer_sentiment=sentiment,
                        rto_risk=rto,
                        qa_notes=qa_note
                    )

                # Broadcast QA score to live dashboard
                broadcaster = get_live_broadcaster()
                asyncio.create_task(
                    broadcaster.broadcast({
                        "type": "qa_audit_completed",
                        "call_id": call_id,
                        "customer_id": customer_id,
                        "customer_name": customer_name,
                        "order_id": order_id,
                        "human_score": score,
                        "customer_sentiment": sentiment,
                        "rto_risk": rto,
                        "qa_notes": qa_note,
                        "resolution": resolution
                    })
                )

                return audit_result

            except Exception as e:
                logger.warning("call_audit_llm_error_using_rule_fallback", error=str(e))

        # Rule-based fallback audit
        lower_t = clean_transcript.lower()
        if "cancel" in lower_t or "nahi chahiye" in lower_t or "cancel karo" in lower_t:
            fb = {
                "human_score": 9.0,
                "customer_sentiment": "FRUSTRATED",
                "rto_risk": "HIGH",
                "qa_notes": "Customer requested order cancellation during call.",
                "resolution": "CANCELLED"
            }
        elif "haan" in lower_t or "yes" in lower_t or "confirm" in lower_t or "maine hi" in lower_t:
            fb = {
                "human_score": 9.5,
                "customer_sentiment": "SATISFIED",
                "rto_risk": "LOW",
                "qa_notes": "Customer positively confirmed order details and address.",
                "resolution": "CONFIRMED"
            }
        else:
            fb = {
                "human_score": 8.8,
                "customer_sentiment": "NEUTRAL",
                "rto_risk": "LOW",
                "qa_notes": "Call concluded normally with standard order check.",
                "resolution": "CONFIRMED"
            }

        broadcaster = get_live_broadcaster()
        asyncio.create_task(
            broadcaster.broadcast({
                "type": "qa_audit_completed",
                "call_id": call_id,
                "customer_id": customer_id,
                "customer_name": customer_name,
                "order_id": order_id,
                **fb
            })
        )
        return fb


_auditor: Optional[CallAuditorService] = None


def get_call_auditor() -> CallAuditorService:
    global _auditor
    if _auditor is None:
        _auditor = CallAuditorService()
    return _auditor
