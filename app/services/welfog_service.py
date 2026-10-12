"""Welfog Order, Tracking, Refund, and Invoice API client."""

import time
from typing import Any, Dict, List, Optional
import httpx

from app.config import get_settings
from app.utils.logging import logger
from app.utils.security import verify_order_ownership


class WelfogService:
    """
    Async client wrapper for external Welfog APIs:
    - Purchase history
    - Live order tracking
    - Purchase history details
    - Return / refund request status
    - Invoice download/details
    """

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self.settings = get_settings()
        self._client = client
        self._default_timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=10.0)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or getattr(self._client, "is_closed", False) is True:
            self._client = httpx.AsyncClient(
                timeout=self._default_timeout,
                headers={"User-Agent": "WelfogVoiceAgent/1.0", "Accept": "application/json"}
            )
        return self._client

    async def close(self):
        """Close underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get_order_history(
        self,
        user_id: int,
        page: int = 1,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Fetch customer purchase history.
        GET /api/v2/purchase-history/{user_id}
        """
        start_time = time.perf_counter()
        client = await self._get_client()
        url = f"{self.settings.welfog_api_base}/api/v2/purchase-history/{user_id}"
        params = {"page": page, "per_page": limit, "limit": limit}

        try:
            response = await client.get(url, params=params)
            latency_ms = (time.perf_counter() - start_time) * 1000

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    "welfog_api_order_history_success",
                    user_id=user_id,
                    latency_ms=latency_ms
                )
                return {
                    "success": True,
                    "orders": data.get("data", []),
                    "meta": data.get("meta", {})
                }
            else:
                logger.warning(
                    "welfog_api_order_history_failed",
                    user_id=user_id,
                    latency_ms=latency_ms,
                    extra={"status_code": response.status_code}
                )
                return {
                    "success": False,
                    "error": f"API returned status {response.status_code}",
                    "orders": []
                }
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "welfog_api_order_history_exception",
                user_id=user_id,
                latency_ms=latency_ms,
                error=str(e)
            )
            return {"success": False, "error": "Connection error to Welfog order history", "orders": []}

    async def get_order_tracking(
        self,
        user_id: int,
        order_id: str
    ) -> Dict[str, Any]:
        """
        Fetch real-time tracking status of an order.
        POST /api/onedelivery/welfog_track
        """
        start_time = time.perf_counter()
        client = await self._get_client()
        url = f"{self.settings.welfog_api_base}/api/onedelivery/welfog_track"
        payload = {"order_id": str(order_id), "user_id": int(user_id)}

        try:
            response = await client.post(url, json=payload)
            latency_ms = (time.perf_counter() - start_time) * 1000

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    "welfog_api_order_tracking_success",
                    user_id=user_id,
                    order_id=str(order_id),
                    latency_ms=latency_ms
                )
                return {
                    "success": True,
                    "data": data,
                    "order_status": data.get("current_order_status"),
                    "expected_delivery": data.get("expected_delivery"),
                    "tracking_code": data.get("tracking_code"),
                    "product_title": data.get("product_title"),
                    "order_status_detail": data.get("order_status_detail")
                }
            else:
                logger.warning(
                    "welfog_api_order_tracking_failed",
                    user_id=user_id,
                    order_id=str(order_id),
                    latency_ms=latency_ms,
                    extra={"status_code": response.status_code}
                )
                return {"success": False, "error": f"Order tracking returned {response.status_code}"}
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "welfog_api_order_tracking_exception",
                user_id=user_id,
                order_id=str(order_id),
                latency_ms=latency_ms,
                error=str(e)
            )
            return {"success": False, "error": "Connection error to Welfog tracking service"}

    async def get_order_details(
        self,
        user_id: int,
        order_id: str
    ) -> Dict[str, Any]:
        """
        Fetch single order detailed breakdown.
        GET /api/v2/purchase-history-details/{order_id}?user_id={user_id}
        """
        start_time = time.perf_counter()
        client = await self._get_client()
        url = f"{self.settings.welfog_api_base}/api/v2/purchase-history-details/{order_id}"
        params = {"user_id": user_id}

        try:
            response = await client.get(url, params=params)
            latency_ms = (time.perf_counter() - start_time) * 1000

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    "welfog_api_order_details_success",
                    user_id=user_id,
                    order_id=str(order_id),
                    latency_ms=latency_ms
                )
                return {"success": True, "details": data}
            elif response.status_code == 404:
                return {"success": False, "error": "Order not found or does not exist"}
            else:
                logger.warning(
                    "welfog_api_order_details_failed",
                    user_id=user_id,
                    order_id=str(order_id),
                    latency_ms=latency_ms,
                    extra={"status_code": response.status_code}
                )
                return {"success": False, "error": f"Details API returned {response.status_code}"}
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "welfog_api_order_details_exception",
                user_id=user_id,
                order_id=str(order_id),
                latency_ms=latency_ms,
                error=str(e)
            )
            return {"success": False, "error": "Connection error to Welfog order details"}

    async def get_refund_status(
        self,
        user_id: int,
        order_id: str
    ) -> Dict[str, Any]:
        """
        Fetch return / refund status with strict ownership validation.
        GET /api/v2/return-request/{order_id}
        """
        # 1. Ownership check first: verify that order_id belongs to user_id
        ownership_valid = await self._verify_customer_order(user_id, order_id)
        if not ownership_valid:
            logger.warning(
                "refund_status_ownership_denied",
                user_id=user_id,
                order_id=str(order_id)
            )
            return {
                "success": False,
                "error": "Order ownership validation failed. Cannot access refund status for another user."
            }

        start_time = time.perf_counter()
        client = await self._get_client()
        url = f"{self.settings.welfog_api_base}/api/v2/return-request/{order_id}"

        try:
            response = await client.get(url)
            latency_ms = (time.perf_counter() - start_time) * 1000

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    "welfog_api_refund_status_success",
                    user_id=user_id,
                    order_id=str(order_id),
                    latency_ms=latency_ms
                )
                return {
                    "success": True,
                    "order_id": order_id,
                    "refund_status": data.get("refund_status"),
                    "refund_amount": data.get("refund_amount"),
                    "message": data.get("message"),
                    "isbankvalid": data.get("isbankvalid")
                }
            else:
                return {"success": False, "error": f"Refund status API returned {response.status_code}"}
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "welfog_api_refund_status_exception",
                user_id=user_id,
                order_id=str(order_id),
                latency_ms=latency_ms,
                error=str(e)
            )
            return {"success": False, "error": "Connection error to Welfog refund status"}

    async def get_invoice(
        self,
        user_id: int,
        order_id: str
    ) -> Dict[str, Any]:
        """
        Fetch invoice details with strict customer ownership validation.
        GET /get_invoice?order_id={order_id}
        """
        # Strict ownership verification
        ownership_valid = await self._verify_customer_order(user_id, order_id)
        if not ownership_valid:
            logger.warning(
                "invoice_ownership_denied",
                user_id=user_id,
                order_id=str(order_id)
            )
            return {
                "success": False,
                "error": "Ownership validation failed. Customer not authorized to view invoice for this order."
            }

        start_time = time.perf_counter()
        client = await self._get_client()
        url = f"{self.settings.supplier_service_base}/get_invoice"
        params = {"order_id": order_id}

        try:
            response = await client.get(url, params=params)
            latency_ms = (time.perf_counter() - start_time) * 1000

            if response.status_code == 200:
                logger.info(
                    "welfog_api_invoice_success",
                    user_id=user_id,
                    order_id=str(order_id),
                    latency_ms=latency_ms
                )
                return {
                    "success": True,
                    "order_id": order_id,
                    "invoice_url": str(response.url),
                    "message": "Invoice verified and accessible for this customer."
                }
            elif response.status_code == 404:
                return {"success": False, "error": "Invoice not yet generated or not found"}
            else:
                return {"success": False, "error": f"Invoice service returned {response.status_code}"}
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "welfog_api_invoice_exception",
                user_id=user_id,
                order_id=str(order_id),
                latency_ms=latency_ms,
                error=str(e)
            )
            return {"success": False, "error": "Connection error to Welfog invoice service"}

    async def _verify_customer_order(self, user_id: int, order_id: str) -> bool:
        """Helper to verify that order belongs to user_id via history or details check."""
        # Check order history
        history_res = await self.get_order_history(user_id, page=1, limit=50)
        if history_res.get("success") and history_res.get("orders"):
            if verify_order_ownership(order_id, user_id, order_history=history_res["orders"]):
                return True

        # Check order details with user_id
        details_res = await self.get_order_details(user_id, order_id)
        if details_res.get("success") and details_res.get("details"):
            if verify_order_ownership(order_id, user_id, order_data=details_res["details"]):
                return True

        # In case the mock/test environment allows checking without populated history:
        return False
