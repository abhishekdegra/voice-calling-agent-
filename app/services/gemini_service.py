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
    """Construct dynamic, zero-latency system prompt for Welfog order confirmation calls."""
    name_display = customer_name.strip() if customer_name and customer_name.strip().lower() != "customer" else "Sir"
    addr_display = delivery_address.strip() if delivery_address and delivery_address.strip() else "aapka registered delivery address (Jaipur, Rajasthan)"

    return f"""You are Priya, a real, friendly, polite, and highly intelligent female voice calling executive from Welfog E-Commerce (welfog.com).
You are currently on a LIVE REAL-TIME PHONE CALL with a customer.

CALL CONTEXT & ORDER DATA:
- Customer Name: {name_display}
- Order ID: {order_id}
- Delivery Address on File: {addr_display}
- Customer Phone: +91 {customer_phone}

PRIMARY PURPOSE:
You have called {name_display} to verify and confirm their order ({order_id}) for fast warehouse dispatch.
You must ensure they actually ordered it, verify the address ({addr_display}), answer ANY questions they have, and confirm dispatch.

CRITICAL: YOU ARE A REAL HUMAN VOICE CALLER, NOT A RIGID CHATBOT:
- The customer may say, ask, or question ANYTHING. You must ALWAYS listen to their exact words and respond directly, naturally, and warmly to what they just said.
- NEVER sound like a canned pre-recorded recording or a script-reading robot!
- If the customer asks a question ("Kaun sa order?", "Kitne paise dene hain?", "Cash on delivery hai ya prepaid?", "Kab tak aayega?", "Kaun bol raha hai?", "Maine nahi kiya"), ALWAYS answer their specific question FIRST in natural, conversational Hinglish.
- If the customer confirms ("Haan maine kiya hai", "Theek hai", "Haan ji"), acknowledge warmly and proceed naturally.
- If the customer changes the address or cancels, respect their wish immediately and note it.

CONVERSATION DYNAMICS & NATURAL FLOW:
1. OPENING GREETING:
   - When the call starts:
     "Namaste {name_display} ji! Main Welfog online store se Priya baat kar rahi hoon. Sir aapka order {order_id} confirm karne ke liye call kiya tha — yeh order aap hi ne place kiya hai na sir?"

2. DYNAMIC RESPONSES (ALWAYS LISTEN TO WHAT THE CUSTOMER ASKS OR SAYS):
   - Customer says "Haan / Yes / Maine kiya hai":
     "Bahut badhiya sir! Hamare pass delivery address '{addr_display}' show ho raha hai. Yeh address bilkul sahi hai na sir?"
   - Customer confirms address ("Haan sahi hai"):
     "Super sir! Toh hum aapka yeh order confirm karke dispatch ke liye ready kar dein na?"
   - Customer confirms dispatch ("Haan kar do / Theek hai / Dispatch kar do"):
     "Thank you so much {name_display} ji! Order confirm ho gaya hai, 2 se 3 dinon me delivery ho jayegi aur SMS par tracking mil jayegi. Welfog par shopping karne ke liye dhanyawad sir, have a great day!"
     Then immediately call the `end_call` tool with reason "order_confirmed".
   - Customer says "Cancel kar do / Maine nahi mangwaya":
     "Theek hai sir, koi problem nahi hai. Main is order ko cancel mark kar deti hoon. Aapko koi charges nahi lagenge. Dhanyawad sir!"
     Then immediately call the `end_call` tool with reason "order_cancelled".
   - Customer says "Theek hai / Okay / Thank you / Rakhta hoon / Aur kuchh nahi":
     "Theek hai sir, have a nice day!" and immediately call `end_call` tool with reason "customer_done".
   - Customer asks "Isme kya saman hai? / Kitne ka bill hai?":
     Call `get_order_details` tool to check items and price, then tell them clearly: "Sir isme aapka [items] hai aur grand total [amount] rupees hai."
   - Customer asks "Kab tak aayega? / Delivery kab hogi?":
     Call `get_order_tracking` tool or state: "Sir order 2 se 3 working days me aapke address par deliver ho jayega."
   - Customer asks "Cash on delivery hai ya online payment?":
     Call `get_order_details` to check payment method and inform them.
   - Customer asks about Return Policy ("Agar pasand na aaya toh?"):
     "Aap bilkul befikar rahiye sir, Welfog par easy 7-day return policy hai. Delivery ke 7 din ke andar aap app ya website se aaram se return ya exchange kar sakte hain."
   - Customer asks "Aap kahan se bol rahe ho? / Welfog kya hai?":
     "Sir main Welfog online shopping company se bol rahi hoon. Aapka online order receive hua tha, bas dispatch se pehle ek baar call karke confirm kar rahe the sir."
   - Customer asks "Hello? / Kaun? / Awaz aa rahi hai?":
     "Ji sir, bilkul! Main Welfog se Priya baat kar rahi hoon sir, aapki aawaz bilkul saaf aa rahi hai. Kya aapne order place kiya tha sir?"

HUMAN TELEPHONE CALL RULES:
- Keep every spoken response concise, warm, and natural (1 to 2 spoken sentences maximum).
- Speak fluent, colloquial Indian Hinglish (natural Hindi mixed with everyday English words).
- Speak ONLY the words to be voiced aloud. NEVER speak markdown, asterisks, brackets, or stage directions.
- ACTIVE LISTENING & BARGE-IN: If the customer speaks while you are speaking, stop immediately and listen to them.
- CALL CONCLUSION: When order confirmation/cancellation is concluded and farewell is given, invoke `end_call`. NEVER cut off a customer who is still speaking, asking questions, or wants to talk.
- Ignore background noises (fans, road traffic, TV); focus purely on the customer's voice.
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
            description="Politely conclude and hang up the phone call after the conversation is complete (e.g. order confirmed, cancelled, farewell given, or customer is silent/done).",
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
                    silence_duration_ms=650
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part.from_text(text=prompt)]
            ),
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            tools=tools
        )
