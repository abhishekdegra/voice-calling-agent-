"""PII, OTP, and sensitive financial credential masking utilities for voice transcripts & logs."""

import re
from typing import Optional


# Precompiled regex patterns for performance
# 1. OTP / Verification codes (4 to 6 consecutive digits with context keywords or standalone formatted)
_OTP_CONTEXT_PATTERN = re.compile(
    r"(?i)\b(?:otp|code|pin|verification\s*code|one\s*time\s*password|passcode)[\s:=–-]+([0-9]{4,6})\b"
)
_STANDALONE_OTP_PATTERN = re.compile(
    r"(?i)\b(?:otp\s*hai|code\s*hai|likho)\s*[:=–-]?\s*([0-9]{4,6})\b"
)

# 2. Credit/Debit Card numbers (13 to 19 digits, with or without spaces/hyphens)
_CARD_PATTERN = re.compile(
    r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|6(?:011|5[0-9][0-9])[0-9]{12}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|(?:2131|1800|35\d{3})\d{11}|[0-9]{4}[\s-][0-9]{4}[\s-][0-9]{4}[\s-][0-9]{4})\b"
)

# 3. CVV / CVC (3 or 4 digits near security code keywords)
_CVV_PATTERN = re.compile(
    r"(?i)\b(?:cvv|cvc|security\s*code)[\s:=–-]+([0-9]{3,4})\b"
)

# 4. Aadhaar Numbers (12 digits, often formatted as 4-4-4)
_AADHAAR_PATTERN = re.compile(
    r"\b[2-9]{1}[0-9]{3}[\s-]?[0-9]{4}[\s-]?[0-9]{4}\b"
)

# 5. Sensitive passwords / PIN hints
_PASSWORD_PATTERN = re.compile(
    r"(?i)\b(?:password|mpin|atm\s*pin)[\s:=–-]+(\S+)\b"
)


def mask_sensitive_pii(text: Optional[str]) -> str:
    """
    Scrub sensitive customer credentials (OTP, Card Numbers, CVV, Aadhaar, MPIN)
    from transcripts and logs before database persistence and client streaming.
    Preserves regular prices (₹999), order IDs (WF-10928), and phone numbers.
    """
    if not text:
        return ""

    masked = text

    # Mask credit/debit card numbers
    masked = _CARD_PATTERN.sub("[REDACTED_CARD]", masked)

    # Mask Aadhaar numbers (verify length)
    def _mask_aadhaar(match):
        val = match.group(0).replace(" ", "").replace("-", "")
        if len(val) == 12:
            return "[REDACTED_AADHAAR]"
        return match.group(0)

    masked = _AADHAAR_PATTERN.sub(_mask_aadhaar, masked)

    # Mask CVV
    masked = _CVV_PATTERN.sub(lambda m: m.group(0).replace(m.group(1), "[REDACTED_CVV]"), masked)

    # Mask OTP with keyword context
    masked = _OTP_CONTEXT_PATTERN.sub(lambda m: m.group(0).replace(m.group(1), "[REDACTED_OTP]"), masked)
    masked = _STANDALONE_OTP_PATTERN.sub(lambda m: m.group(0).replace(m.group(1), "[REDACTED_OTP]"), masked)

    # Mask passwords / MPIN
    masked = _PASSWORD_PATTERN.sub(lambda m: m.group(0).replace(m.group(1), "[REDACTED_PIN]"), masked)

    return masked
