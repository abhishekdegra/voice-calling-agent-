import csv
import io
import os
import time
import uuid
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

router = APIRouter(prefix="/api", tags=["Admin & Customers"])


# ==================== Pydantic Schemas ====================

class LoginRequest(BaseModel):
    username: str
    password: str


class CustomerCreateRequest(BaseModel):
    name: str = Field(default="Customer")
    phone: str
    order_id: Optional[str] = Field(default="WF-10928")
    notes: Optional[str] = Field(default="")


class BulkCustomerItem(BaseModel):
    name: Optional[str] = "Customer"
    phone: str
    order_id: Optional[str] = "WF-10928"
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


class CustomerUpdateRequest(BaseModel):
    name: str
    phone: str
    order_id: Optional[str] = "WF-10928"
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


@router.post("/customers")
async def create_customer(
    req: CustomerCreateRequest,
    _: str = Depends(get_current_admin)
):
    """Onboard a single customer into calling queue."""
    db = get_db_service()
    customer_id = await db.add_customer(
        name=req.name,
        phone=req.phone,
        order_id=req.order_id,
        notes=req.notes
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
                # Format: Name, Phone, OrderID (optional)
                entries.append({
                    "name": parts[0],
                    "phone": parts[1],
                    "order_id": parts[2] if len(parts) > 2 else f"WF-1092{idx+1}",
                    "notes": "Bulk Pasted"
                })
            else:
                # Format: Just Phone
                entries.append({
                    "name": f"Customer {idx+1}",
                    "phone": parts[0],
                    "order_id": f"WF-1092{idx+1}",
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
    writer.writerow(["ID", "Name", "Phone", "Order ID", "Status", "Duration (s)", "Last Called At", "Notes", "Recording URL"])
    for c in customers:
        writer.writerow([
            c.get("id"),
            c.get("name"),
            c.get("phone"),
            c.get("order_id"),
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
    """Update customer details (name, phone, order_id, notes)."""
    db = get_db_service()
    await db.update_customer(
        customer_id=customer_id,
        name=req.name,
        phone=req.phone,
        order_id=req.order_id,
        notes=req.notes
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
    """Update customer status, call duration, notes, transcript, and recording."""
    db = get_db_service()
    await db.update_customer_status(
        customer_id=customer_id,
        status=req.status,
        call_duration=req.call_duration,
        call_summary=req.call_summary,
        transcript=req.transcript,
        recording_url=req.recording_url
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
    """Save call outcome, recording URL and full transcript into call_logs."""
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
        recording_url=req.recording_url
    )

    # Also update customer status and recording in customers table
    if req.customer_id:
        await db.update_customer_status(
            customer_id=req.customer_id,
            status=req.status,
            call_duration=req.duration,
            call_summary=req.summary,
            transcript=req.transcript,
            recording_url=req.recording_url
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

