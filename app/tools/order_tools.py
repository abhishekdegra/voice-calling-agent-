"""Controlled Order Tools for Gemini AI function calling."""

import time
from typing import Any, Dict, Optional
from app.services.welfog_service import WelfogService
from app.utils.logging import logger


class OrderTools:
    """
    Controlled tool suite for order queries.
    Enforces customer isolation (user_id is bound from the verified call session).
    """

    def __init__(self, welfog_service: Optional[WelfogService] = None):
        self.welfog_service = welfog_service or WelfogService()

    async def get_order_history(self, user_id: int, limit: int = 5) -> Dict[str, Any]:
        """Fetch customer purchase history summary."""
        start_time = time.perf_counter()
        try:
            res = await self.welfog_service.get_order_history(user_id=int(user_id), limit=limit)
            latency_ms = (time.perf_counter() - start_time) * 1000
            
            if not res.get("success"):
                return {"status": "error", "message": "Unable to retrieve order history at this time."}

            orders = res.get("orders", [])
            summary = []
            for order in orders:
                summary.append({
                    "order_id": order.get("id") or order.get("code") or order.get("oid"),
                    "order_date": order.get("date") or order.get("created_at"),
                    "grand_total": order.get("grand_total"),
                    "delivery_status": order.get("delivery_status") or order.get("status"),
                    "payment_status": order.get("payment_status")
                })

            return {"status": "success", "orders": summary, "count": len(summary)}
        except Exception as e:
            logger.error("tool_get_order_history_error", error=str(e), user_id=user_id)
            return {"status": "error", "message": "Error retrieving order history."}

    async def get_order_tracking(self, user_id: int, order_id: str) -> Dict[str, Any]:
        """Fetch real-time delivery status for a specific order."""
        start_time = time.perf_counter()
        if not order_id:
            return {"status": "error", "message": "Order ID is required to track the order."}

        try:
            res = await self.welfog_service.get_order_tracking(user_id=int(user_id), order_id=str(order_id))
            latency_ms = (time.perf_counter() - start_time) * 1000

            if not res.get("success"):
                return {"status": "error", "message": "Order tracking details not found."}

            data = res.get("data", {})
            return {
                "status": "success",
                "order_id": str(order_id),
                "current_status": data.get("current_order_status"),
                "expected_delivery": data.get("expected_delivery"),
                "tracking_code": data.get("tracking_code"),
                "product_title": data.get("product_title"),
                "status_detail": data.get("order_status_detail")
            }
        except Exception as e:
            logger.error("tool_get_order_tracking_error", error=str(e), user_id=user_id, order_id=order_id)
            return {"status": "error", "message": "Error checking tracking status."}

    async def get_order_details(self, user_id: int, order_id: str) -> Dict[str, Any]:
        """Fetch full details of an order."""
        start_time = time.perf_counter()
        if not order_id:
            return {"status": "error", "message": "Order ID is required."}

        try:
            res = await self.welfog_service.get_order_details(user_id=int(user_id), order_id=str(order_id))
            latency_ms = (time.perf_counter() - start_time) * 1000

            if not res.get("success"):
                return {"status": "error", "message": res.get("error", "Order details not found.")}

            d_raw = res.get("details", {})
            details = d_raw
            if isinstance(d_raw, dict) and "data" in d_raw:
                if isinstance(d_raw["data"], list) and len(d_raw["data"]) > 0:
                    details = d_raw["data"][0]
                elif isinstance(d_raw["data"], dict):
                    details = d_raw["data"]

            raw_price = details.get("grand_total") or details.get("subtotal") or details.get("total")
            if raw_price is not None:
                raw_str = str(raw_price).strip()
                if raw_str.lower().startswith("rs"):
                    price_str = "₹" + raw_str[2:].strip()
                elif not raw_str.startswith("₹"):
                    price_str = f"₹{raw_str}"
                else:
                    price_str = raw_str
            else:
                price_str = None

            return {
                "status": "success",
                "order_id": str(order_id),
                "product_title": details.get("product_title"),
                "current_order_status": details.get("current_order_status") or details.get("delivery_status_string"),
                "grand_total": price_str,
                "payment_status": details.get("payment_type") or details.get("payment_status_string") or details.get("payment_status"),
                "order_date": details.get("order_date") or details.get("date"),
                "order_flow": details.get("order_flow")
            }
        except Exception as e:
            logger.error("tool_get_order_details_error", error=str(e), user_id=user_id, order_id=order_id)
            return {"status": "error", "message": "Error retrieving order details."}

    async def get_refund_status(self, user_id: int, order_id: str) -> Dict[str, Any]:
        """Fetch refund request status for an order with ownership verification."""
        start_time = time.perf_counter()
        if not order_id:
            return {"status": "error", "message": "Order ID is required."}

        try:
            res = await self.welfog_service.get_refund_status(user_id=int(user_id), order_id=str(order_id))
            latency_ms = (time.perf_counter() - start_time) * 1000

            if not res.get("success"):
                return {"status": "error", "message": res.get("error", "Unable to verify refund status.")}

            return {
                "status": "success",
                "order_id": str(order_id),
                "refund_status": res.get("refund_status") or "Not initiated",
                "refund_amount": res.get("refund_amount"),
                "message": res.get("message")
            }
        except Exception as e:
            logger.error("tool_get_refund_status_error", error=str(e), user_id=user_id, order_id=order_id)
            return {"status": "error", "message": "Error retrieving refund status."}

    async def get_invoice(self, user_id: int, order_id: str) -> Dict[str, Any]:
        """Check invoice availability with ownership verification."""
        start_time = time.perf_counter()
        if not order_id:
            return {"status": "error", "message": "Order ID is required."}

        try:
            res = await self.welfog_service.get_invoice(user_id=int(user_id), order_id=str(order_id))
            latency_ms = (time.perf_counter() - start_time) * 1000

            if not res.get("success"):
                return {"status": "error", "message": res.get("error", "Invoice not accessible.")}

            return {
                "status": "success",
                "order_id": str(order_id),
                "invoice_available": True,
                "message": "Invoice is verified and available. It has also been sent to your registered email/account."
            }
        except Exception as e:
            logger.error("tool_get_invoice_error", error=str(e), user_id=user_id, order_id=order_id)
            return {"status": "error", "message": "Error accessing invoice information."}
