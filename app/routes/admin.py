import csv
import io
import os
import time
import uuid
import asyncio
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Response, Request, UploadFile, File, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.auth_service import (
    create_session_token,
    get_current_admin,
    SESSION_COOKIE_NAME,
    SESSION_EXPIRY_SECONDS
)
from app.services.db_service import get_db_service
from app.services.call_auditor import get_call_auditor

router = APIRouter(prefix="/api", tags=["Admin & Customers"])


# ==================== Pydantic Schemas ====================

class LoginRequest(BaseModel):
    username: str
    password: str


class CustomerCreateRequest(BaseModel):
    name: str = Field(default="Customer")
    phone: str
    order_id: Optional[str] = Field(default="WF-10928")
    product_name: Optional[str] = Field(default="Welfog Premium Item")
    product_price: Optional[str] = Field(default="₹999")
    delivery_time: Optional[str] = Field(default="2-3 Business Days")
    payment_method: Optional[str] = Field(default="Cash on Delivery (COD)")
    notes: Optional[str] = Field(default="")


class BulkCustomerItem(BaseModel):
    name: Optional[str] = "Customer"
    phone: str
    order_id: Optional[str] = "WF-10928"
    product_name: Optional[str] = "Welfog Premium Item"
    product_price: Optional[str] = "₹999"
    delivery_time: Optional[str] = "2-3 Business Days"
    payment_method: Optional[str] = "Cash on Delivery (COD)"
    notes: Optional[str] = "Bulk Import"


class BulkCustomerRequest(BaseModel):
    customers: Optional[List[BulkCustomerItem]] = None
    raw_text: Optional[str] = None  # Comma or newline separated phone numbers / CSV


class CustomerStatusUpdateRequest(BaseModel):
    status: str
    call_duration: Optional[int] = None
    call_summary: Optional[str] = None
    transcript: Optional[str] = None
    recording_url: Optional[str] = None
    qa_score: Optional[float] = None
    customer_sentiment: Optional[str] = None
    rto_risk: Optional[str] = None
    qa_notes: Optional[str] = None


class CustomerUpdateRequest(BaseModel):
    name: str
    phone: str
    order_id: Optional[str] = "WF-10928"
    product_name: Optional[str] = None
    product_price: Optional[str] = None
    delivery_time: Optional[str] = None
    payment_method: Optional[str] = None
    notes: Optional[str] = ""


class CallLogCreateRequest(BaseModel):
    customer_id: Optional[int] = None
    phone: str
    customer_name: Optional[str] = "Customer"
    order_id: Optional[str] = "WF-10928"
    status: str
    duration: int = 0
    summary: Optional[str] = ""
    transcript: Optional[str] = ""
    recording_url: Optional[str] = ""
    qa_score: Optional[float] = None
    customer_sentiment: Optional[str] = None
    rto_risk: Optional[str] = None
    qa_notes: Optional[str] = None


# ==================== Authentication Endpoints ====================

@router.post("/auth/login")
async def login(req: LoginRequest, response: Response):
    """Admin login endpoint setting HTTPOnly session cookie."""
    db = get_db_service()
    valid = await db.verify_admin(req.username.strip(), req.password)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password. Please use admin credentials."
        )

    token = create_session_token(req.username.strip())
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_EXPIRY_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False  # Allow local HTTP testing
    )
    return {
        "success": True,
        "token": token,
        "username": req.username.strip(),
        "message": "Login successful"
    }


@router.post("/auth/logout")
async def logout(response: Response):
    """Admin logout clearing session cookie."""
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return {"success": True, "message": "Logged out successfully"}


@router.get("/auth/me")
async def get_me(username: str = Depends(get_current_admin)):
    """Return currently authenticated admin username."""
    return {"username": username}


# ==================== Customer Onboarding Endpoints ====================

@router.get("/customers")
async def list_customers(
    status: Optional[str] = None,
    search: Optional[str] = None,
    _: str = Depends(get_current_admin)
):
    """Fetch customer queue with optional status or search filter."""
    db = get_db_service()
    customers = await db.get_customers(status=status, search=search)
    return {"customers": customers, "count": len(customers)}


@router.get("/orders/lookup")
async def lookup_order(
    order_id: str,
    _: str = Depends(get_current_admin)
):
    """
    Fetch real order information (product title, price, delivery time, address) from live Welfog APIs.
    """
    from app.services.welfog_service import WelfogService
    service = WelfogService()
    try:
        clean_order_id = order_id.strip()
        tracking_res = await service.get_order_tracking(user_id=1, order_id=clean_order_id)
        details_res = await service.get_order_details(user_id=1, order_id=clean_order_id)

        found = False
        product_name = None
        product_price = None
        delivery_time = None
        payment_method = None
        delivery_address = None
        customer_name = None
        customer_phone = None

        if tracking_res.get("success") and tracking_res.get("data") and tracking_res["data"].get("result") != "not_found":
            found = True
            t_data = tracking_res["data"]
            product_name = t_data.get("product_title") or tracking_res.get("product_title")
            raw_del = t_data.get("expected_delivery")
            if raw_del and not str(raw_del).isdigit():
                delivery_time = str(raw_del)
            else:
                flow = t_data.get("order_status_detail", {}).get("order_status", {}).get("order_flow", {})
                del_flow = flow.get("delivered", {})
                del_date = del_flow.get("date")
                if del_date:
                    delivery_time = f"Expected by {del_date[:10]}"
                else:
                    delivery_time = "In 2-3 Business Days"

        if details_res.get("success") and details_res.get("details"):
            found = True
            d_raw = details_res["details"]
            d_item = d_raw
            if isinstance(d_raw, dict) and "data" in d_raw:
                if isinstance(d_raw["data"], list) and len(d_raw["data"]) > 0:
                    d_item = d_raw["data"][0]
                elif isinstance(d_raw["data"], dict):
                    d_item = d_raw["data"]

            if not product_name:
                product_name = d_item.get("product_title") or d_item.get("product_name")

            raw_price = d_item.get("grand_total") or d_item.get("subtotal") or d_item.get("total")
            if raw_price is not None:
                raw_str = str(raw_price).strip()
                if raw_str.lower().startswith("rs"):
                    product_price = "₹" + raw_str[2:].strip()
                elif not raw_str.startswith("₹"):
                    product_price = f"₹{raw_str}"
                else:
                    product_price = raw_str

            raw_pay = d_item.get("payment_type") or d_item.get("payment_mode") or d_item.get("payment_status_string")
            if raw_pay:
                if "cod" in str(raw_pay).lower() or "cash" in str(raw_pay).lower():
                    payment_method = "Cash on Delivery (COD)"
                else:
                    payment_method = str(raw_pay)

            ship = d_item.get("shipping_address")
            if isinstance(ship, dict):
                customer_name = ship.get("name")
                customer_phone = ship.get("phone")
                addr_parts = [ship.get("address"), ship.get("city"), ship.get("state")]
                valid_parts = [str(p).strip() for p in addr_parts if p and str(p).strip()]
                full_addr = ", ".join(valid_parts)
                if ship.get("postal_code"):
                    full_addr += f" ({ship.get('postal_code')})"
                delivery_address = full_addr
            elif isinstance(ship, str):
                delivery_address = ship

            if not customer_name:
                customer_name = d_item.get("customer_name") or d_item.get("user_name")
            if not customer_phone:
                customer_phone = d_item.get("customer_phone") or d_item.get("phone")

        order_payload = {
            "order_id": clean_order_id,
            "product_name": product_name,
            "product_price": product_price,
            "delivery_time": delivery_time,
            "payment_method": payment_method,
            "delivery_address": delivery_address,
            "customer_name": customer_name,
            "customer_phone": customer_phone
        }

        return {
            "found": found,
            "order_id": clean_order_id,
            "product_name": product_name,
            "product_price": product_price,
            "delivery_time": delivery_time,
            "payment_method": payment_method,
            "delivery_address": delivery_address,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "order": order_payload,
            "message": "Real order details retrieved from Welfog API" if found else "Order not found in remote API. You can enter or edit details manually."
        }
    finally:
        await service.close()


@router.post("/customers")
async def create_customer(
    req: CustomerCreateRequest,
    _: str = Depends(get_current_admin)
):
    """Onboard a single customer into calling queue with complete order details."""
    db = get_db_service()
    customer_id = await db.add_customer(
        name=req.name,
        phone=req.phone,
        order_id=req.order_id,
        notes=req.notes,
        product_name=req.product_name,
        product_price=req.product_price,
        delivery_time=req.delivery_time,
        payment_method=req.payment_method
    )
    return {"success": True, "customer_id": customer_id, "message": "Customer onboarded successfully"}


@router.post("/customers/bulk")
async def bulk_create_customers(
    req: BulkCustomerRequest,
    _: str = Depends(get_current_admin)
):
    """Bulk onboard customers via JSON list or raw comma/newline text."""
    entries: List[Dict[str, str]] = []

    if req.customers:
        for c in req.customers:
            entries.append({
                "name": c.name or "Customer",
                "phone": c.phone,
                "order_id": c.order_id or "WF-10928",
                "product_name": c.product_name or "Welfog Premium Item",
                "product_price": c.product_price or "₹999",
                "delivery_time": c.delivery_time or "2-3 Business Days",
                "payment_method": c.payment_method or "Cash on Delivery (COD)",
                "notes": c.notes or "Bulk Import"
            })

    if req.raw_text:
        lines = req.raw_text.strip().splitlines()
        for idx, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) >= 2:
                # Format: Name, Phone, OrderID (optional), Product (optional), Price (optional)
                entries.append({
                    "name": parts[0],
                    "phone": parts[1],
                    "order_id": parts[2] if len(parts) > 2 else f"WF-1092{idx+1}",
                    "product_name": parts[3] if len(parts) > 3 else "Welfog Premium Item",
                    "product_price": parts[4] if len(parts) > 4 else "₹999",
                    "delivery_time": "2-3 Business Days",
                    "payment_method": "Cash on Delivery (COD)",
                    "notes": "Bulk Pasted"
                })
            else:
                # Format: Just Phone
                entries.append({
                    "name": f"Customer {idx+1}",
                    "phone": parts[0],
                    "order_id": f"WF-1092{idx+1}",
                    "product_name": "Welfog Premium Item",
                    "product_price": "₹999",
                    "delivery_time": "2-3 Business Days",
                    "payment_method": "Cash on Delivery (COD)",
                    "notes": "Bulk Pasted"
                })

    db = get_db_service()
    count = await db.bulk_add_customers(entries)
    return {"success": True, "imported_count": count, "message": f"{count} customers added to queue"}


@router.get("/customers/export-csv")
async def export_customers_csv(
    _: str = Depends(get_current_admin)
):
    """Export all customers and call outcomes as a downloadable CSV."""
    db = get_db_service()
    customers = await db.get_customers()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Name", "Phone", "Order ID", "Product Name", "Product Price",
        "Delivery Time", "Payment Method", "Status", "Duration (s)",
        "Last Called At", "Address/Notes", "Recording URL"
    ])
    for c in customers:
        writer.writerow([
            c.get("id"),
            c.get("name"),
            c.get("phone"),
            c.get("order_id"),
            c.get("product_name", ""),
            c.get("product_price", ""),
            c.get("delivery_time", ""),
            c.get("payment_method", ""),
            c.get("status"),
            c.get("call_duration", 0),
            c.get("last_called_at", ""),
            c.get("notes", ""),
            c.get("recording_url", "")
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=customers_export.csv"}
    )


@router.get("/customers/{customer_id}")
async def get_customer_details(
    customer_id: int,
    _: str = Depends(get_current_admin)
):
    """Retrieve details, notes, and full conversation transcript for a customer."""
    db = get_db_service()
    customer = await db.get_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.put("/customers/{customer_id}")
async def edit_customer(
    customer_id: int,
    req: CustomerUpdateRequest,
    _: str = Depends(get_current_admin)
):
    """Update customer details and order metadata."""
    db = get_db_service()
    await db.update_customer(
        customer_id=customer_id,
        name=req.name,
        phone=req.phone,
        order_id=req.order_id,
        notes=req.notes,
        product_name=req.product_name,
        product_price=req.product_price,
        delivery_time=req.delivery_time,
        payment_method=req.payment_method
    )
    return {"success": True, "message": "Customer updated successfully"}


@router.delete("/customers/{customer_id}")
async def delete_customer(
    customer_id: int,
    _: str = Depends(get_current_admin)
):
    """Remove a customer from the queue."""
    db = get_db_service()
    await db.delete_customer(customer_id)
    return {"success": True, "message": "Customer deleted"}


@router.post("/customers/{customer_id}/reset")
async def reset_customer(
    customer_id: int,
    _: str = Depends(get_current_admin)
):
    """Reset single customer status back to PENDING."""
    db = get_db_service()
    await db.reset_customer(customer_id)
    return {"success": True, "message": "Customer status reset to PENDING"}


@router.post("/customers/reset-all")
async def reset_all_customers(
    _: str = Depends(get_current_admin)
):
    """Reset all finished or failed customers back to PENDING."""
    db = get_db_service()
    count = await db.reset_all_customers()
    return {"success": True, "reset_count": count, "message": f"{count} customers reset to PENDING"}


@router.post("/customers/retry-unanswered")
async def retry_unanswered_customers(
    _: str = Depends(get_current_admin)
):
    """Reset NO_ANSWER, BUSY, and FAILED customers back to PENDING for auto-retrying."""
    db = get_db_service()
    count = await db.reset_unanswered_customers()
    return {"success": True, "reset_count": count, "message": f"{count} unanswered/busy customers reset to PENDING"}




@router.post("/customers/{customer_id}/status")
async def update_status(
    customer_id: int,
    req: CustomerStatusUpdateRequest,
    _: str = Depends(get_current_admin)
):
    """Update customer status, call duration, notes, transcript, recording, and QA scores."""
    db = get_db_service()
    await db.update_customer_status(
        customer_id=customer_id,
        status=req.status,
        call_duration=req.call_duration,
        call_summary=req.call_summary,
        transcript=req.transcript,
        recording_url=req.recording_url,
        qa_score=req.qa_score,
        customer_sentiment=req.customer_sentiment,
        rto_risk=req.rto_risk,
        qa_notes=req.qa_notes
    )
    return {"success": True}


# ==================== Audio Recording Upload ====================

@router.post("/recordings/upload")
async def upload_recording(
    audio: UploadFile = File(...),
    _: str = Depends(get_current_admin)
):
    """Upload recorded call audio (.webm/.mp3/.wav) and save to static recordings."""
    try:
        contents = await audio.read()
        if not contents or len(contents) < 300:
            return {"success": False, "error": "Audio recording payload too small or empty"}

        rec_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "recordings")
        os.makedirs(rec_dir, exist_ok=True)
        filename = f"rec_{int(time.time())}_{uuid.uuid4().hex[:8]}.webm"
        file_path = os.path.join(rec_dir, filename)

        with open(file_path, "wb") as f:
            f.write(contents)

        recording_url = f"/static/recordings/{filename}"
        return {"success": True, "recording_url": recording_url}
    except Exception as e:
        return {"success": False, "error": f"Failed to save recording: {str(e)}"}


# ==================== Auto-Dialer & Campaign Queue ====================

@router.get("/campaign/next")
async def get_next_customer(
    _: str = Depends(get_current_admin)
):
    """Get next customer in queue to be called automatically."""
    db = get_db_service()
    next_cust = await db.get_next_pending_customer()
    return {"has_next": next_cust is not None, "customer": next_cust}


@router.get("/stats")
async def get_stats(
    _: str = Depends(get_current_admin)
):
    """Return dashboard analytics metrics."""
    db = get_db_service()
    return await db.get_dashboard_stats()


# ==================== Call Logs ====================

@router.post("/call-logs")
async def save_call_log(
    req: CallLogCreateRequest,
    _: str = Depends(get_current_admin)
):
    """Save call outcome, recording URL and full transcript into call_logs with QA metrics."""
    db = get_db_service()
    log_id = await db.record_call_log(
        customer_id=req.customer_id,
        phone=req.phone,
        customer_name=req.customer_name or "Customer",
        order_id=req.order_id or "WF-10928",
        status=req.status,
        duration=req.duration,
        summary=req.summary,
        transcript=req.transcript,
        recording_url=req.recording_url,
        qa_score=req.qa_score,
        customer_sentiment=req.customer_sentiment,
        rto_risk=req.rto_risk,
        qa_notes=req.qa_notes
    )

    # Also update customer status and recording in customers table
    if req.customer_id:
        await db.update_customer_status(
            customer_id=req.customer_id,
            status=req.status,
            call_duration=req.duration,
            call_summary=req.summary,
            transcript=req.transcript,
            recording_url=req.recording_url,
            qa_score=req.qa_score,
            customer_sentiment=req.customer_sentiment,
            rto_risk=req.rto_risk,
            qa_notes=req.qa_notes
        )

        # If call was finalized from browser without QA score yet, trigger auditor in background
        if req.qa_score is None and req.transcript and len(req.transcript) > 15:
            auditor = get_call_auditor()
            asyncio.create_task(
                auditor.audit_call(
                    call_id=f"log_{log_id}",
                    customer_id=req.customer_id,
                    customer_name=req.customer_name or "Customer",
                    phone=req.phone,
                    order_id=req.order_id or "WF-10928",
                    transcript=req.transcript,
                    call_duration=req.duration,
                    status=req.status
                )
            )

    return {"success": True, "log_id": log_id}


@router.get("/call-logs")
async def list_call_logs(
    limit: int = 50,
    _: str = Depends(get_current_admin)
):
    """List recent call history logs."""
    db = get_db_service()
    logs = await db.get_call_logs(limit=limit)
    return {"logs": logs, "count": len(logs)}


@router.get("/telecmi/webrtc-config")
async def get_webrtc_config():
    """Return runtime TeleCMI WebRTC credentials from server environment."""
    from app.config import get_settings
    settings = get_settings()
    return {
        "user_id": settings.telecmi_user_id or "5002_33338876",
        "password": settings.telecmi_user_password or "",
        "sbc": settings.telecmi_sbc or "sbcind.telecmi.com",
        "caller_id": settings.telecmi_caller_id or ""
    }

