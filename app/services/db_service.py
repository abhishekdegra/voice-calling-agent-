"""Database service for Welfog Voice Agent interacting with XAMPP MySQL."""

import asyncio
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional
import pymysql
from pymysql.cursors import DictCursor

from app.config import get_settings
from app.utils.logging import logger

PASSWORD_SALT = "welfog_salt_2026"


def hash_password(password: str) -> str:
    """Hash password with application salt."""
    return hashlib.sha256((PASSWORD_SALT + password).encode("utf-8")).hexdigest()


class DatabaseService:
    """Manages MySQL connections and queries for customers, logs, and authentication."""

    def __init__(self):
        self.settings = get_settings()
        self.host = self.settings.db_host or "localhost"
        self.port = int(self.settings.db_port or 3306)
        self.user = self.settings.db_user or "root"
        self.password = self.settings.db_password or ""
        self.database = self.settings.db_name or "welfog_ai"

    def _get_connection(self):
        """Create a new MySQL connection with DictCursor."""
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            cursorclass=DictCursor,
            autocommit=True,
            charset="utf8mb4"
        )

    async def verify_admin(self, username: str, password: str) -> bool:
        """Verify admin login credentials against MySQL database."""
        def _verify():
            expected_hash = hash_password(password)
            try:
                conn = self._get_connection()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT password_hash FROM admins WHERE username = %s LIMIT 1",
                        (username,)
                    )
                    row = cur.fetchone()
                    if row and row["password_hash"] == expected_hash:
                        return True
                    # Also allow direct match if admin@123
                    if username == "admin" and password == "admin@123":
                        return True
                    return False
            except Exception as e:
                logger.error("db_verify_admin_error", error=str(e))
                # Fallback for admin@123
                return username == "admin" and password == "admin@123"
            finally:
                if 'conn' in locals() and conn:
                    conn.close()

        return await asyncio.to_thread(_verify)

    async def get_customers(
        self,
        status: Optional[str] = None,
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetch all onboarded customers with optional status or text filter."""
        def _fetch():
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    query = "SELECT * FROM customers WHERE 1=1"
                    params = []

                    if status and status.upper() != "ALL":
                        query += " AND status = %s"
                        params.append(status.upper())

                    if search:
                        query += " AND (name LIKE %s OR phone LIKE %s OR order_id LIKE %s)"
                        like_val = f"%{search}%"
                        params.extend([like_val, like_val, like_val])

                    query += " ORDER BY FIELD(status, 'CALLING', 'CONNECTED', 'PENDING', 'COMPLETED', 'NO_ANSWER', 'BUSY', 'FAILED'), id ASC"
                    cur.execute(query, tuple(params))
                    rows = cur.fetchall()
                    for r in rows:
                        if isinstance(r.get("created_at"), datetime):
                            r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                        if isinstance(r.get("updated_at"), datetime):
                            r["updated_at"] = r["updated_at"].strftime("%Y-%m-%d %H:%M:%S")
                        if isinstance(r.get("last_called_at"), datetime):
                            r["last_called_at"] = r["last_called_at"].strftime("%Y-%m-%d %H:%M:%S")
                    return rows
            finally:
                conn.close()

        return await asyncio.to_thread(_fetch)

    async def get_customer(self, customer_id: int) -> Optional[Dict[str, Any]]:
        """Fetch customer by ID."""
        def _fetch():
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM customers WHERE id = %s", (customer_id,))
                    row = cur.fetchone()
                    if row:
                        for k in ["created_at", "updated_at", "last_called_at"]:
                            if isinstance(row.get(k), datetime):
                                row[k] = row[k].strftime("%Y-%m-%d %H:%M:%S")
                    return row
            finally:
                conn.close()

        return await asyncio.to_thread(_fetch)

    async def get_next_pending_customer(self) -> Optional[Dict[str, Any]]:
        """Retrieve the next pending customer in the calling queue."""
        def _fetch():
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM customers WHERE status = 'PENDING' ORDER BY id ASC LIMIT 1"
                    )
                    row = cur.fetchone()
                    if row:
                        for k in ["created_at", "updated_at", "last_called_at"]:
                            if isinstance(row.get(k), datetime):
                                row[k] = row[k].strftime("%Y-%m-%d %H:%M:%S")
                    return row
            finally:
                conn.close()

        return await asyncio.to_thread(_fetch)

    async def add_customer(
        self,
        name: str,
        phone: str,
        order_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> int:
        """Insert a single customer into queue."""
        def _insert():
            # Standardize 10 digit Indian number
            cleaned_phone = "".join(c for c in phone if c.isdigit())
            if len(cleaned_phone) == 12 and cleaned_phone.startswith("91"):
                cleaned_phone = cleaned_phone[2:]

            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO customers (name, phone, order_id, notes, status)
                        VALUES (%s, %s, %s, %s, 'PENDING')
                        """,
                        (name.strip() or "Customer", cleaned_phone, (order_id or "WF-10928").strip(), notes or "")
                    )
                    return cur.lastrowid
            finally:
                conn.close()

        return await asyncio.to_thread(_insert)

    async def bulk_add_customers(self, entries: List[Dict[str, str]]) -> int:
        """Bulk insert customers from list of dicts."""
        def _bulk_insert():
            conn = self._get_connection()
            try:
                count = 0
                with conn.cursor() as cur:
                    for item in entries:
                        raw_phone = item.get("phone", "")
                        cleaned = "".join(c for c in raw_phone if c.isdigit())
                        if len(cleaned) == 12 and cleaned.startswith("91"):
                            cleaned = cleaned[2:]
                        if not cleaned or len(cleaned) < 10:
                            continue

                        cur.execute(
                            """
                            INSERT INTO customers (name, phone, order_id, notes, status)
                            VALUES (%s, %s, %s, %s, 'PENDING')
                            """,
                            (
                                item.get("name", "Customer").strip() or "Customer",
                                cleaned,
                                item.get("order_id", "WF-10928").strip() or "WF-10928",
                                item.get("notes", "Bulk Onboarded")
                            )
                        )
                        count += 1
                return count
            finally:
                conn.close()

        return await asyncio.to_thread(_bulk_insert)

    async def update_customer(
        self,
        customer_id: int,
        name: str,
        phone: str,
        order_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> bool:
        """Edit customer info."""
        def _edit():
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cleaned = "".join(c for c in phone if c.isdigit())
                    if len(cleaned) == 12 and cleaned.startswith("91"):
                        cleaned = cleaned[2:]
                    cur.execute(
                        """
                        UPDATE customers 
                        SET name = %s, phone = %s, order_id = %s, notes = %s 
                        WHERE id = %s
                        """,
                        (name.strip(), cleaned, order_id.strip() if order_id else "WF-10928", notes or "", customer_id)
                    )
                    return True
            finally:
                conn.close()

        return await asyncio.to_thread(_edit)

    async def update_customer_status(
        self,
        customer_id: int,
        status: str,
        call_duration: Optional[int] = None,
        call_summary: Optional[str] = None,
        transcript: Optional[str] = None,
        recording_url: Optional[str] = None
    ) -> bool:
        """Update customer call status and record notes/transcript/recording."""
        def _update():
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    updates = ["status = %s", "last_called_at = NOW()"]
                    params = [status.upper()]

                    if call_duration is not None:
                        updates.append("call_duration = %s")
                        params.append(call_duration)

                    if call_summary is not None:
                        updates.append("call_summary = %s")
                        params.append(call_summary)

                    if transcript is not None:
                        updates.append("transcript = %s")
                        params.append(transcript)

                    if recording_url is not None:
                        updates.append("recording_url = %s")
                        params.append(recording_url)

                    params.append(customer_id)
                    cur.execute(
                        f"UPDATE customers SET {', '.join(updates)} WHERE id = %s",
                        tuple(params)
                    )
                    return True
            finally:
                conn.close()

        return await asyncio.to_thread(_update)

    async def delete_customer(self, customer_id: int) -> bool:
        """Delete customer by ID."""
        def _delete():
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM customers WHERE id = %s", (customer_id,))
                    return True
            finally:
                conn.close()

        return await asyncio.to_thread(_delete)

    async def reset_customer(self, customer_id: int) -> bool:
        """Reset customer back to PENDING."""
        def _reset():
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE customers SET status = 'PENDING', call_duration = 0, call_summary = NULL WHERE id = %s",
                        (customer_id,)
                    )
                    return True
            finally:
                conn.close()

        return await asyncio.to_thread(_reset)

    async def reset_all_customers(self) -> int:
        """Reset all completed or failed customers back to PENDING for a new campaign."""
        def _reset_all():
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE customers SET status = 'PENDING', call_duration = 0, call_summary = NULL WHERE status != 'PENDING'"
                    )
                    return cur.rowcount
            finally:
                conn.close()

        return await asyncio.to_thread(_reset_all)

    async def reset_unanswered_customers(self) -> int:
        """Reset only NO_ANSWER, BUSY, or FAILED customers back to PENDING for re-calling."""
        def _reset_unanswered():
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE customers SET status = 'PENDING', call_duration = 0, call_summary = NULL WHERE status IN ('NO_ANSWER', 'BUSY', 'FAILED')"
                    )
                    return cur.rowcount
            finally:
                conn.close()

        return await asyncio.to_thread(_reset_unanswered)

    async def record_call_log(
        self,
        customer_id: Optional[int],
        phone: str,
        customer_name: str,
        order_id: str,
        status: str,
        duration: int,
        summary: Optional[str] = None,
        transcript: Optional[str] = None,
        recording_url: Optional[str] = None
    ) -> int:
        """Insert historical call record into call_logs table."""
        def _insert():
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO call_logs (customer_id, phone, customer_name, order_id, status, duration, summary, transcript, recording_url)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (customer_id, phone, customer_name, order_id, status.upper(), duration, summary or "", transcript or "", recording_url or "")
                    )
                    return cur.lastrowid
            finally:
                conn.close()

        return await asyncio.to_thread(_insert)

    async def get_call_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch recent call logs."""
        def _fetch():
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT * FROM call_logs ORDER BY id DESC LIMIT %s",
                        (limit,)
                    )
                    rows = cur.fetchall()
                    for r in rows:
                        if isinstance(r.get("created_at"), datetime):
                            r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                    return rows
            finally:
                conn.close()

        return await asyncio.to_thread(_fetch)

    async def get_dashboard_stats(self) -> Dict[str, Any]:
        """Aggregate high-level metrics for dashboard cards."""
        def _stats():
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) AS total FROM customers")
                    total = cur.fetchone()["total"]

                    cur.execute("SELECT COUNT(*) AS pending FROM customers WHERE status = 'PENDING'")
                    pending = cur.fetchone()["pending"]

                    cur.execute("SELECT COUNT(*) AS completed FROM customers WHERE status = 'COMPLETED'")
                    completed = cur.fetchone()["completed"]

                    cur.execute("SELECT COUNT(*) AS no_answer FROM customers WHERE status = 'NO_ANSWER'")
                    no_answer = cur.fetchone()["no_answer"]

                    cur.execute("SELECT COUNT(*) AS failed FROM customers WHERE status IN ('FAILED', 'BUSY')")
                    failed = cur.fetchone()["failed"]

                    cur.execute("SELECT COALESCE(SUM(duration), 0) AS total_duration FROM call_logs")
                    total_duration = cur.fetchone()["total_duration"]

                    attempted = completed + no_answer + failed
                    rate = round((completed / attempted * 100), 1) if attempted > 0 else 0.0

                    return {
                        "total_customers": total,
                        "pending_calls": pending,
                        "completed_calls": completed,
                        "no_answer_calls": no_answer,
                        "failed_calls": failed,
                        "total_duration_seconds": int(total_duration),
                        "success_rate_percent": rate
                    }
            finally:
                conn.close()

        return await asyncio.to_thread(_stats)


_db_service: Optional[DatabaseService] = None


def get_db_service() -> DatabaseService:
    """Return singleton DatabaseService instance."""
    global _db_service
    if _db_service is None:
        _db_service = DatabaseService()
    return _db_service
