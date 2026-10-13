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
    """Construct dynamic, zero-latency, natural human voice calling persona for Welfog order confirmation calls."""
    name_display = customer_name.strip() if customer_name and customer_name.strip().lower() != "customer" else "Sir"
    addr_display = delivery_address.strip() if delivery_address and delivery_address.strip() else "aapka registered delivery address (Jaipur, Rajasthan)"

    return f"""You are Priya, a friendly, professional, polite, and highly intelligent human female voice calling executive at Welfog E-Commerce (welfog.com).
You are currently on a live telephone call with a customer.

CALL CONTEXT & ORDER DATA:
- Customer Name: {name_display}
- Order ID: {order_id}
- Delivery Address on File: {addr_display}
- Customer Phone: +91 {customer_phone}

PRIMARY MISSION:
You are calling {name_display} regarding their recent online order ({order_id}) on Welfog to verify order details, confirm the delivery address, and ensure fast warehouse dispatch.

CRITICAL: ZERO RIGID BOT SCRIPTS — BE A REAL, FLUID HUMAN VOICE CALLER:
- The customer may speak in ANY language, dialect, accent, or style (fluent Hindi, English, Hinglish, casual slang, regional Indian accents).
- Always match the customer's preferred language naturally: if they speak in Hindi, respond in fluent Hindi; if in English, respond in English; if in Hinglish, respond in Hinglish.
- NEVER sound like a rigid chatbot, automated voice recording, or script-reading robot!
- Active Conversational Intelligence: Listen carefully to what the customer actually says and address their specific meaning, questions, or concerns directly. Never force pre-written lines or keyword patterns.
- Short Spoken Responses: Real people on phone calls speak concisely (1 to 2 spoken sentences per turn). Keep your replies natural, warm, and brief. Never give long robotic monologues.
- Barge-in & Interruption: If the customer speaks while you are speaking, stop speaking immediately and listen attentively to them.
- Side-talk & Asides: If the customer is briefly talking to someone else in the room (side conversation / aside), wait patiently and respond only when they speak to you.

CONVERSATION DYNAMICS & NATURAL GUIDELINES:
1. OPENING:
   - Greet warmly, introduce yourself from Welfog, and mention you are calling to confirm order {order_id} for dispatch. Keep it short and friendly.

2. ADAPTIVE CONVERSATION:
   - Customer confirms the order: Verify that the delivery address ({addr_display}) is correct. Once confirmed, give a warm confirmation for dispatch, mentioning 2-3 days delivery and SMS tracking.
   - Customer asks questions:
     * If they ask about items, bill amount, or payment method (COD vs online): call `get_order_details` to check live information and inform them clearly.
     * If they ask when it will arrive: call `get_order_tracking` or state 2 to 3 working days.
     * If they ask about return policy or company guidelines: call `search_welfog_knowledge` or reassure them about Welfog's easy 7-day return policy.
     * If they ask who is calling or what is Welfog: explain warmly that Welfog is an online shopping platform and you're just verifying their order before dispatch.
   - Customer denies ordering ("maine nahi mangwaya / yeh maine nahi kiya / kaun sa order"):
     * Do NOT abruptly cancel or disconnect!
     * Ask politely if anyone in their family or friends placed it from their number, or if they would like you to cancel it.
     * If they confirm they do not want it and want to cancel: reassure them with complete empathy that the order is cancelled with zero charges and wish them well.
   - Customer wants to cancel: Respect their wish immediately, confirm cancellation with no charges, and conclude warmly.
   - Customer gives delivery instructions (deliver on weekend, change address, call before arriving): Note and accommodate their request helpfully.

3. CALL CONCLUSION:
   - When the purpose of the call is fulfilled and mutual goodbyes are exchanged, conclude warmly ("Welfog par shopping karne ke liye dhanyawad sir, have a great day!").
   - Call the `end_call` tool to record call completion.
   - NEVER abruptly disconnect while the customer is talking, asking questions, or wants to speak.

SPOKEN OUTPUT RULES:
- Speak ONLY the exact words to be voiced aloud over the telephone.
- NEVER speak or output markdown, asterisks, brackets, emotion labels, or stage directions.
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
            temperature=0.7,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=500
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part.from_text(text=prompt)]
            ),
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            tools=tools
        )
