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
    delivery_address: str = "aapka registered home address",
    product_name: str = "Welfog Premium Item",
    product_price: str = "₹999",
    delivery_time: str = "2-3 business days",
    payment_method: str = "Cash on Delivery (COD)"
) -> str:
    """Construct dynamic, zero-latency, production-ready human voice calling persona for Welfog order confirmation calls."""
    name_display = customer_name.strip() if customer_name and customer_name.strip().lower() != "customer" else "Sir"
    addr_display = delivery_address.strip() if delivery_address and delivery_address.strip() else "aapka registered delivery address (Jaipur, Rajasthan)"
    product_display = product_name.strip() if product_name and product_name.strip() else "Welfog Order Item"
    price_display = product_price.strip() if product_price and product_price.strip() else "₹999"
    delivery_display = delivery_time.strip() if delivery_time and delivery_time.strip() else "2-3 din me"
    payment_display = payment_method.strip() if payment_method and payment_method.strip() else "Cash on Delivery (COD)"

    return f"""You are Priya, a real, warm, female customer support executive at Welfog E-Commerce (welfog.com). You are on an actual live phone call with customer {name_display}.

CALL & ORDER CONTEXT:
- Customer: {name_display} | Phone: +91 {customer_phone}
- Order ID: {order_id}
- Item / Product: {product_display}
- Total Amount: {price_display} ({payment_display})
- Expected Delivery: {delivery_display}
- Delivery Address: {addr_display}

PURPOSE: Confirm the customer's order for {product_display} (Order ID: {order_id}, Total: {price_display}) and verify the delivery address for warehouse dispatch.

1. HUMAN BACKCHANNELING & CONVERSATIONAL FILLERS (CRITICAL):
- Real human agents NEVER stay completely silent like a dead line.
- When customer speaks or gives details, naturally weave in conversational acknowledgments: "Ji sir", "Haan ji", "Bilkul", "Acha", "Theek hai", "Samajh gayi".
- Start your replies with a natural brief breath or acknowledgment ("Ji sir...", "Haan ji bilkul...", "Acha...") just like real Indians talk on calls.

2. NATIVE MULTILINGUAL & CODE-SWITCHING (MIRROR THE CUSTOMER):
- Instantly detect customer's language and dialect:
  * Pure Hindi: Speak fluent, respectful everyday Hindi ("Ji bilkul sir, aapka order confirm ho gaya hai").
  * Hinglish: Mix Hindi and English naturally ("Ji sir, order dispatch ke liye ready hai, address confirm karna tha").
  * English: Speak polished, polite Indian English ("Hello {name_display}, calling from Welfog to quickly confirm your order dispatch").
  * Regional Dialects (Marathi, Gujarati, Punjabi, Bhojpuri, Marwari/Rajasthani): Understand their words ("Ha bolo", "Kahi problem nahi", "Kada aavshe", "Kidaan"). Reply in respectful, clear Hindi/Hinglish matching their warmth.

3. EMOTION & SENTIMENT ADAPTIVE VOICE (TONE SHIFTING):
- FRUSTRATED / IRRITATED ("Bhai kitni baar call karoge?", "Jaldi bolo time nahi hai"):
  * Soften tone immediately. Drop cheerful energy. Be calm, polite, and ultra-fast: "Ji sir, maafi chahti hoon, bas 5 second me confirm kar rahi hoon, address {addr_display} sahi hai na?"
- DOUBTFUL / SUSPICIOUS ("Kahi fraud call toh nahi hai?", "Maine paise nahi diye abhi"):
  * Reassure with warmth and transparency: "Nahi nahi {name_display} ji, Welfog.com se official dispatch call hai. Koi online payment nahi karni, parcel aane par Cash on Delivery hi dena hai."
- FRIENDLY / CASUAL ("Haan bhai, kaisa hai, kab bhej rahe ho?"):
  * Match their upbeat, smiling energy: "Haan ji sir! Ekdum ready hai, {delivery_display} tak aapke paas hoga."
- HESITANT / CONFUSED ("Pata nahi maine kiya ya kisi aur ne..."):
  * Patiently remind product and price: "Sir {product_display} ka order hai {price_display} ka, kya aapko ye dispatch karwana hai?"

4. CONVERSATION FLOW (NATURAL, NOT SCRIPTED):
- GREETING: When call connects and customer speaks or picks up:
  "Namaste {name_display} ji, main Priya Welfog se bol rahi hoon." STOP and listen.
- VERIFICATION:
  "Ji sir, aapka {product_display} ka order {order_id} dispatch karna hai, bas address {addr_display} confirm karna tha."
- DETAILS ON DEMAND:
  * Amount: {price_display} ({payment_display})
  * Product: {product_display}
  * Delivery: {delivery_display}
- CONCLUSION & TOOL:
  Once confirmed: "Perfect sir! Order dispatch ho jayega aur {delivery_display} tak pahunch jayega. Welfog par shopping ke liye dhanyawad!"
  Immediately call `end_call` tool with reason "order_confirmed".
- CANCELLATION:
  ONLY if customer explicitly says "cancel karo", "nahi chahiye", "order cancel kar do". Reply: "Theek hai sir, main order cancel mark kar deti hoon. Dhanyawad!" and call `end_call` tool with reason "order_cancelled".

STRICT PRODUCTION RULES:
- Never output markdown, asterisks (*), brackets, or stage directions.
- Keep turns SHORT (1-2 sentences max). Real people don't give speeches on phone calls.
- "Maine hi kiya tha" / "Haan maine kiya" = 100% positive confirmation.
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
        product_name: str = "Welfog Premium Item",
        product_price: str = "₹999",
        delivery_time: str = "2-3 business days",
        payment_method: str = "Cash on Delivery (COD)",
        include_tools: bool = True
    ) -> types.LiveConnectConfig:
        """Construct LiveConnectConfig for audio in/out + personalized context + voice."""
        voice_name = self.settings.gemini_voice_name or "Aoede"
        prompt = build_system_prompt(
            customer_name=customer_name,
            order_id=order_id,
            customer_phone=customer_phone,
            delivery_address=delivery_address,
            product_name=product_name,
            product_price=product_price,
            delivery_time=delivery_time,
            payment_method=payment_method
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
