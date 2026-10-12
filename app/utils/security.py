"""Security, validation, and normalization helpers."""

import re
from typing import Any, Dict, List, Optional


def normalize_indian_phone_number(phone: str) -> str:
    """
    Normalizes an Indian phone number to 91XXXXXXXXXX format as required by TeleCMI.
    Examples:
        '9876543210' -> '919876543210'
        '+91 9876543210' -> '919876543210'
        '09876543210' -> '919876543210'
        '919876543210' -> '919876543210'
    """
    # Remove all non-digit characters
    cleaned = re.sub(r"\D", "", phone or "")

    if len(cleaned) == 10:
        return f"91{cleaned}"
    elif len(cleaned) == 11 and cleaned.startswith("0"):
        return f"91{cleaned[1:]}"
    elif len(cleaned) == 12 and cleaned.startswith("91"):
        return cleaned
    elif len(cleaned) > 10 and cleaned.endswith(cleaned[-10:]):
        # Extract last 10 digits if country code is included
        return f"91{cleaned[-10:]}"
    return cleaned


def is_valid_phone_number(phone: str) -> bool:
    """Validate if phone number is a valid 12-digit Indian number starting with 91."""
    normalized = normalize_indian_phone_number(phone)
    return bool(re.match(r"^91[6-9]\d{9}$", normalized))


def sanitize_customer_output(text: str) -> str:
    """Strip any internal technical leaks or unwanted formatting before speech."""
    if not text:
        return ""
    # Strip json or code blocks if Gemini accidentally outputs them
    text = re.sub(r"```[a-zA-Z]*", "", text)
    text = text.replace("```", "")
    return text.strip()


def verify_order_ownership(
    requested_order_id: str,
    user_id: int,
    order_data: Optional[Dict[str, Any]] = None,
    order_history: Optional[List[Dict[str, Any]]] = None
) -> bool:
    """
    Validates that a given order belongs to the requesting user_id.
    Prevents BOLA/IDOR attacks where customer A requests invoice or refund for customer B.
    """
    requested_str = str(requested_order_id).strip()

    # Direct match from order details if user_id or customer_id is present
    if order_data:
        # Check standard fields: user_id, customer_id, user.id
        owner_id = order_data.get("user_id") or order_data.get("customer_id")
        if owner_id is not None and int(owner_id) == int(user_id):
            return True
        user_obj = order_data.get("user")
        if isinstance(user_obj, dict) and user_obj.get("id") is not None:
            if int(user_obj["id"]) == int(user_id):
                return True

    # Check within user's order history list
    if order_history:
        for order in order_history:
            oid = str(order.get("id") or order.get("oid") or order.get("order_id") or order.get("code") or "")
            if oid and oid == requested_str:
                return True

    return False
