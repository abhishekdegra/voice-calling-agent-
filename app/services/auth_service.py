"""Authentication and session management for Welfog Admin Dashboard."""

import hmac
import hashlib
import time
import json
import base64
from typing import Optional
from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.db_service import get_db_service

SECRET_KEY = "welfog_voice_calling_secret_key_2026_super_secure"
SESSION_COOKIE_NAME = "welfog_session"
SESSION_EXPIRY_SECONDS = 86400 * 7  # 7 days

security_bearer = HTTPBearer(auto_error=False)


def create_session_token(username: str) -> str:
    """Create a signed, tamper-proof session token."""
    payload = {
        "sub": username,
        "exp": int(time.time()) + SESSION_EXPIRY_SECONDS
    }
    payload_bytes = json.dumps(payload).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(payload_bytes).decode("utf-8").rstrip("=")
    signature = hmac.new(SECRET_KEY.encode("utf-8"), b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{signature}"


def verify_session_token(token: str) -> Optional[str]:
    """Verify signed session token and return username if valid."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        b64_payload, signature = parts
        expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), b64_payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        
        # Add back padding
        pad = len(b64_payload) % 4
        if pad:
            b64_payload += "=" * (4 - pad)
        data = json.loads(base64.urlsafe_b64decode(b64_payload.encode("utf-8")).decode("utf-8"))
        if data.get("exp", 0) < int(time.time()):
            return None
        return data.get("sub")
    except Exception:
        return None


async def get_current_admin(
    request: Request,
    bearer: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer)
) -> str:
    """FastAPI dependency requiring authenticated admin user."""
    token = None
    if bearer and bearer.credentials:
        token = bearer.credentials
    elif SESSION_COOKIE_NAME in request.cookies:
        token = request.cookies[SESSION_COOKIE_NAME]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please login as admin."
        )

    username = verify_session_token(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please login again."
        )

    return username
