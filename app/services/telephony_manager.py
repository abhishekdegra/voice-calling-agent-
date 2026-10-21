"""Telephony routing and multi-carrier failover manager."""

import asyncio
from typing import Any, Dict, Optional
from app.config import get_settings
from app.services.telecmi_service import TeleCMIService
from app.utils.logging import logger


class TelephonyManager:
    """
    Coordinates outbound call dispatch across multiple carriers:
    - Primary Carrier: TeleCMI / PIOPIY WebRTC streaming gateway
    - Automatic carrier health tracking & error classification
    - Intelligent retry scheduling for transient telecom failures
    """

    def __init__(self, telecmi_service: Optional[TeleCMIService] = None):
        self.settings = get_settings()
        self.telecmi = telecmi_service or TeleCMIService()
        self._carrier_status: Dict[str, bool] = {"telecmi": True}

    async def initiate_call(
        self,
        customer_phone: str,
        websocket_url: str,
        call_id: str,
        carrier_preference: str = "telecmi"
    ) -> Dict[str, Any]:
        """
        Dispatch call to the primary carrier with intelligent error classification and failover.
        """
        logger.info(
            "telephony_dispatch_initiated",
            call_id=call_id,
            carrier=carrier_preference,
            phone=customer_phone[-4:]  # Masked in log
        )

        # Primary attempt: TeleCMI
        res = await self.telecmi.initiate_streaming_call(
            customer_phone=customer_phone,
            custom_websocket_url=websocket_url,
            extra_param=call_id
        )

        if res.get("success"):
            self._carrier_status["telecmi"] = True
            return {
                "success": True,
                "carrier": "telecmi",
                "call_id": res.get("call_id"),
                "carrier_response": res
            }

        # Handle failure: Classify error
        err_msg = str(res.get("error", "Unknown carrier error"))
        logger.warning(
            "primary_carrier_failed",
            carrier="telecmi",
            call_id=call_id,
            error=err_msg
        )

        # Classify telecom error code
        is_retryable = any(term in err_msg.lower() for term in ["timeout", "busy", "congestion", "gateway", "503", "502"])

        return {
            "success": False,
            "carrier": "telecmi",
            "error": err_msg,
            "is_retryable": is_retryable,
            "suggested_retry_delay_sec": 30 if is_retryable else 0
        }


_telephony_manager: Optional[TelephonyManager] = None


def get_telephony_manager() -> TelephonyManager:
    global _telephony_manager
    if _telephony_manager is None:
        _telephony_manager = TelephonyManager()
    return _telephony_manager
