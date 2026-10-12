"""TeleCMI / PIOPIY Telephony Service."""

import time
from typing import Any, Dict, List, Optional
import httpx

from app.config import get_settings
from app.utils.logging import logger
from app.utils.security import normalize_indian_phone_number


class TeleCMIService:
    """
    Manages TeleCMI / PIOPIY telephony interactions:
    - Token generation (/v2/token)
    - Agent user authentication (/v2/user/login)
    - PCMO outbound calling (/v2/global_pcmo_make_call)
    - Recording playback URLs (/v2/play)
    """

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self.settings = get_settings()
        self._client = client
        self._cached_app_token: Optional[str] = None
        self._app_token_expiry: float = 0
        self._timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=10.0)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or getattr(self._client, "is_closed", False) is True:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": "WelfogVoiceAgent/1.0", "Content-Type": "application/json"}
            )
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get_app_token(self, force_refresh: bool = False) -> Optional[str]:
        """
        Authenticate with TeleCMI /v2/token to get JWT access token.
        Payload: {"appid": 33338876, "secret": "..."}
        """
        now = time.time()
        if not force_refresh and self._cached_app_token and now < self._app_token_expiry:
            return self._cached_app_token

        start_time = time.perf_counter()
        client = await self._get_client()
        url = f"{self.settings.telecmi_rest_base}/v2/token"
        payload = {
            "appid": int(self.settings.telecmi_app_id),
            "secret": self.settings.telecmi_app_secret
        }

        try:
            response = await client.post(url, json=payload)
            latency_ms = (time.perf_counter() - start_time) * 1000

            if response.status_code == 200:
                data = response.json()
                token = data.get("secret")
                if token:
                    self._cached_app_token = token
                    # Default expiration buffer (valid for 30d in TeleCMI response)
                    self._app_token_expiry = now + 86400
                    logger.info("telecmi_token_success", latency_ms=latency_ms)
                    return token

            logger.error(
                "telecmi_token_failed",
                latency_ms=latency_ms,
                extra={"status_code": response.status_code, "body": response.text}
            )
            return None
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error("telecmi_token_exception", latency_ms=latency_ms, error=str(e))
            return None

    async def agent_login(self) -> Dict[str, Any]:
        """
        Authenticate TeleCMI user agent via /v2/user/login.
        Payload: {"id": "5002_33338876", "password": "..."}
        """
        start_time = time.perf_counter()
        client = await self._get_client()
        url = f"{self.settings.telecmi_rest_base}/v2/user/login"
        payload = {
            "id": self.settings.telecmi_user_id,
            "password": self.settings.telecmi_user_password
        }

        try:
            response = await client.post(url, json=payload)
            latency_ms = (time.perf_counter() - start_time) * 1000

            if response.status_code == 200:
                data = response.json()
                logger.info("telecmi_user_login_success", latency_ms=latency_ms)
                return {
                    "success": True,
                    "agent": data.get("agent"),
                    "token": data.get("token")
                }
            else:
                logger.warning(
                    "telecmi_user_login_failed",
                    latency_ms=latency_ms,
                    extra={"status_code": response.status_code, "response": response.text}
                )
                return {"success": False, "error": f"Login returned {response.status_code}"}
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error("telecmi_user_login_exception", latency_ms=latency_ms, error=str(e))
            return {"success": False, "error": str(e)}

    async def initiate_streaming_call(
        self,
        customer_phone: str,
        custom_websocket_url: Optional[str] = None,
        extra_param: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Initiates outbound phone call to customer and commands TeleCMI to stream audio
        to our FastAPI WebSocket server using PCMO stream action.
        """
        normalized_number = normalize_indian_phone_number(customer_phone)
        ws_url = custom_websocket_url or self.settings.telecmi_websocket_url

        # Build PCMO action array
        pcmo_actions: List[Dict[str, Any]] = [
            {
                "action": "stream",
                "ws_url": ws_url,
                "listen_mode": "callee",
                "voice_quality": "16000",
                "stream_on_answer": True
            }
        ]

        payload: Dict[str, Any] = {
            "appid": int(self.settings.telecmi_app_id),
            "secret": self.settings.telecmi_app_secret,
            "from": int(self.settings.telecmi_caller_id or self.settings.telecmi_app_id),
            "to": int(normalized_number),
            "pcmo": pcmo_actions
        }
        if extra_param:
            payload["extra_param"] = extra_param

        start_time = time.perf_counter()
        client = await self._get_client()
        url = f"{self.settings.telecmi_rest_base}/v2/global_pcmo_make_call"

        try:
            response = await client.post(url, json=payload)
            latency_ms = (time.perf_counter() - start_time) * 1000

            if response.status_code in {200, 201}:
                data = response.json()
                if data.get("status") == "error" or data.get("code") in {"cmi-401", "cmi-422", 401, 422}:
                    err_msg = data.get("msg") or data
                    logger.warning(
                        "telecmi_outbound_call_rejected",
                        customer_phone=normalized_number,
                        latency_ms=latency_ms,
                        extra={"error": err_msg, "code": data.get("code")}
                    )
                    return {
                        "success": False,
                        "customer_phone": normalized_number,
                        "error": f"TeleCMI error: {err_msg} (code: {data.get('code')})"
                    }

                logger.info(
                    "telecmi_outbound_call_initiated",
                    customer_phone=normalized_number,
                    latency_ms=latency_ms,
                    extra={"response": data}
                )
                return {
                    "success": True,
                    "customer_phone": normalized_number,
                    "data": data,
                    "call_id": data.get("call_id") or data.get("id") or data.get("request_id")
                }
            else:
                logger.warning(
                    "telecmi_outbound_call_failed",
                    customer_phone=normalized_number,
                    latency_ms=latency_ms,
                    extra={"status_code": response.status_code, "body": response.text}
                )
                return {
                    "success": False,
                    "customer_phone": normalized_number,
                    "error": f"TeleCMI API returned HTTP {response.status_code}: {response.text}"
                }
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "telecmi_outbound_call_exception",
                customer_phone=normalized_number,
                latency_ms=latency_ms,
                error=str(e)
            )
            return {"success": False, "customer_phone": normalized_number, "error": str(e)}

    def get_recording_url(self, file_name: str) -> str:
        """Construct playback URL for a TeleCMI call recording."""
        return (
            f"{self.settings.telecmi_rest_base}/v2/play"
            f"?appid={self.settings.telecmi_app_id}"
            f"&secret={self.settings.telecmi_app_secret}"
            f"&file={file_name}"
        )
