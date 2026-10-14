"""Gemini Multimodal Live API service wrapper for real-time bidirectional voice."""

import asyncio
from typing import Any, AsyncIterator, Callable, Dict, List, Optional
from google import genai
from google.genai import types

from app.config import get_settings
from app.utils.logging import logger


def build_system_prompt(
    customer_name: str = "Customer",
    order_id: str = "WF-10928",
    customer_phone: str = "",
    delivery_address: str = "aapka registered home address"
) -> str:
    """Construct dynamic, zero-latency, production-ready human voice calling persona for Welfog order confirmation calls."""
    name_display = customer_name.strip() if customer_name and customer_name.strip().lower() != "customer" else "Sir"
    addr_display = delivery_address.strip() if delivery_address and delivery_address.strip() else "aapka registered delivery address (Jaipur, Rajasthan)"

    return f"""You are Priya, a real human female customer support executive at Welfog E-Commerce (welfog.com). You are on a live phone call with customer {name_display}.

CALL CONTEXT:
- Customer: {name_display} | Order: {order_id} | Phone: +91 {customer_phone}
- Delivery Address: {addr_display}

PURPOSE: Confirm order {order_id} details and delivery address for warehouse dispatch.

HOW YOU TALK (CRITICAL — FOLLOW EXACTLY):
- You are a REAL PERSON on a phone call, NOT a chatbot.
- Speak in natural conversational Hinglish (mix of Hindi + English as Indians naturally speak on calls).
- ULTRA SHORT replies: Maximum 1-2 short sentences per turn. Like how you'd actually talk on phone.
- After your greeting, STOP and WAIT for customer to speak first.
- If customer says something (anything at all), respond naturally to what they said.
- If customer stays silent for a few seconds after your greeting, YOU take initiative and say something like: "Sir, aapka order {order_id} hai Welfog se, bas confirm karna tha dispatch ke liye."

CONVERSATION FLOW (natural, not scripted):
1. GREETING: Just say your name and company. Example: "Namaste {name_display} ji, main Priya, Welfog se bol rahi hoon." STOP HERE. Wait for customer.
2. AFTER CUSTOMER RESPONDS: Based on what they say, naturally bring up the order. Example: "Ji sir, aapka order {order_id} hai, bas delivery confirm karni thi."
3. ADDRESS VERIFICATION: Casually mention: "Address {addr_display} pe hi bhejni hai na?"
4. WRAP UP: Once confirmed: "Perfect sir, dispatch ho jayega. Dhanyawad!" Then call end_call tool.

UNDERSTANDING THE CUSTOMER:
- Customer can speak ANY language: Hindi, English, Hinglish, Marathi, Punjabi, anything.
- Understand MEANING, not specific words. "Haan", "Ji", "Ha bhai", "Yes", "OK" = confirmation.
- "Maine hi kiya tha" = "I placed it myself" = STRONG confirmation. NEVER treat as denial.
- "Kab aayega?" / "Tracking?" = They want the order = CONFIRMATION. Say 2-3 din me aa jayega.
- ONLY cancel if customer EXPLICITLY says "cancel karo", "nahi chahiye", "cancel my order".

STRICT RULES:
- Never output markdown, asterisks, brackets, or stage directions.
- Never give long speeches. Keep it conversational and quick.
- Respond IMMEDIATELY when customer speaks — zero hesitation. Start speaking right away with a natural brief acknowledgment (e.g. 'Ji sir', 'Haan ji', 'Bilkul') as real human agents naturally do.
- Match customer's energy and language. If they're casual, be casual. If formal, be formal.
"""


SYSTEM_PROMPT = build_system_prompt()



def get_gemini_tools() -> List[types.Tool]:
    """Define function calling schemas for Welfog voice agent."""
    declarations = [
        types.FunctionDeclaration(
            name="get_order_tracking",
            description="Fetch real-time delivery status, tracking number, and expected delivery date for an order.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "order_id": types.Schema(
                        type="STRING",
                        description="The unique order ID to track (e.g. '12345' or 'ORD-987')"
                    )
                },
                required=["order_id"]
            )
        ),
        types.FunctionDeclaration(
            name="get_order_details",
            description="Fetch item breakdown, total price, payment method, and details for a customer's order.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "order_id": types.Schema(
                        type="STRING",
                        description="The unique order ID to fetch details for"
                    )
                },
                required=["order_id"]
            )
        ),
        types.FunctionDeclaration(
            name="get_order_history",
            description="Fetch the list of recent orders placed by this customer.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "limit": types.Schema(
                        type="INTEGER",
                        description="Number of recent orders to fetch (default: 5)"
                    )
                }
            )
        ),
        types.FunctionDeclaration(
            name="get_refund_status",
            description="Check the refund status, amount, and bank verification for an order.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "order_id": types.Schema(
                        type="STRING",
                        description="The order ID for which refund status is queried"
                    )
                },
                required=["order_id"]
            )
        ),
        types.FunctionDeclaration(
            name="get_invoice",
            description="Verify and retrieve invoice availability for an order.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "order_id": types.Schema(
                        type="STRING",
                        description="The order ID to get the invoice for"
                    )
                },
                required=["order_id"]
            )
        ),
        types.FunctionDeclaration(
            name="search_welfog_knowledge",
            description="Search Welfog company policies, return window guidelines, warranty, and FAQs via knowledge base.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(
                        type="STRING",
                        description="The customer's question regarding return policy, refund rules, or company guidelines"
                    )
                },
                required=["query"]
            )
        ),
        types.FunctionDeclaration(
            name="end_call",
            description="Record that the call objectives are concluded and farewell has been exchanged.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "reason": types.Schema(
                        type="STRING",
                        description="Reason for ending the call: 'order_confirmed', 'order_cancelled', 'customer_done', 'no_response'"
                    )
                },
                required=["reason"]
            )
        )
    ]
    return [types.Tool(function_declarations=declarations)]


class GeminiService:
    """
    Manages Gemini Multimodal Live API connections.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.settings = get_settings()
        self.api_key = api_key or self.settings.gemini_api_key
        self._client: Optional[genai.Client] = None

    def get_client(self) -> genai.Client:
        """Create or return genai.Client singleton."""
        if not self._client:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not set in environment or settings.")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def is_configured(self) -> bool:
        """Check if Gemini API key is configured."""
        return bool(self.api_key and self.api_key != "your_gemini_api_key_here")

    def build_live_config(
        self,
        customer_name: str = "Customer",
        order_id: str = "WF-10928",
        customer_phone: str = "",
        delivery_address: str = "aapka registered home address",
        include_tools: bool = True
    ) -> types.LiveConnectConfig:
        """Construct LiveConnectConfig for audio in/out + personalized context + voice."""
        voice_name = self.settings.gemini_voice_name or "Aoede"
        prompt = build_system_prompt(
            customer_name=customer_name,
            order_id=order_id,
            customer_phone=customer_phone,
            delivery_address=delivery_address
        )
        tools = get_gemini_tools() if include_tools else None
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            temperature=0.35,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    prefix_padding_ms=100,
                    silence_duration_ms=250
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part.from_text(text=prompt)]
            ),
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            tools=tools
        )
