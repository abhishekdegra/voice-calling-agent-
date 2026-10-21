"""Database service for Welfog Voice Agent interacting with XAMPP MySQL."""

import asyncio
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional
import pymysql
from pymysql.cursors import DictCursor

from app.config import get_settings
from app.utils.logging import logger
from app.utils.pii_masking import mask_sensitive_pii

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
        self._schema_checked = False
        self._ensure_database_and_tables()

    def _ensure_database_and_tables(self):
        """Self-healing: Creates welfog_ai database and all required tables if missing or dropped."""
        try:
            # Connect to MySQL server directly without database selected
            server_conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                cursorclass=DictCursor,
                autocommit=True,
                charset="utf8mb4"
            )
            with server_conn.cursor() as cur:
                # 1. Ensure Database Exists
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{self.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
                cur.execute(f"USE `{self.database}`;")

                # 2. Table: admins
                cur.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                # 3. Table: customers
                cur.execute("""
                CREATE TABLE IF NOT EXISTS customers (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(150) NOT NULL DEFAULT 'Customer',
                    phone VARCHAR(20) NOT NULL,
                    order_id VARCHAR(50) DEFAULT 'WF-10928',
                    product_name VARCHAR(255) DEFAULT 'Welfog Premium Item',
                    product_price VARCHAR(50) DEFAULT '₹999',
                    delivery_time VARCHAR(100) DEFAULT '2-3 Business Days',
                    payment_method VARCHAR(50) DEFAULT 'Cash on Delivery (COD)',
                    notes TEXT,
                    status VARCHAR(30) DEFAULT 'PENDING',
                    call_duration INT DEFAULT 0,
                    call_summary TEXT,
                    transcript LONGTEXT,
                    recording_url VARCHAR(500) DEFAULT NULL,
                    last_called_at DATETIME DEFAULT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_status (status),
                    INDEX idx_phone (phone),
                    INDEX idx_order (order_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                # 4. Table: call_logs
                cur.execute("""
                CREATE TABLE IF NOT EXISTS call_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    customer_id INT DEFAULT NULL,
                    phone VARCHAR(20) NOT NULL,
                    customer_name VARCHAR(150) DEFAULT 'Customer',
                    order_id VARCHAR(50) DEFAULT 'WF-10928',
                    status VARCHAR(30) NOT NULL,
                    duration INT DEFAULT 0,
                    summary TEXT,
                    transcript LONGTEXT,
                    recording_url VARCHAR(500) DEFAULT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_call_phone (phone),
                    INDEX idx_call_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                # 5. Ensure Default Admin
                admin_hash = hash_password("admin@123")
                cur.execute("""
                INSERT INTO admins (username, password_hash)
                VALUES ('admin', %s)
                ON DUPLICATE KEY UPDATE password_hash = %s;
                """, (admin_hash, admin_hash))

                # 6. Check missing columns in customers if table existed previously
                cur.execute("SHOW COLUMNS FROM customers")
                existing = {col['Field'] for col in cur.fetchall()}
                for col_name, col_def in [
                    ('product_name', 'VARCHAR(255) DEFAULT NULL'),
                    ('product_price', 'VARCHAR(50) DEFAULT NULL'),
                    ('delivery_time', 'VARCHAR(100) DEFAULT NULL'),
                    ('payment_method', 'VARCHAR(50) DEFAULT NULL'),
                    ('qa_score', 'DECIMAL(3,1) DEFAULT NULL'),
                    ('customer_sentiment', "VARCHAR(50) DEFAULT NULL"),
                    ('rto_risk', "VARCHAR(50) DEFAULT NULL"),
                    ('qa_notes', 'TEXT DEFAULT NULL')
                ]:
                    if col_name not in existing:
                        cur.execute(f"ALTER TABLE customers ADD COLUMN {col_name} {col_def}")

                # Check missing columns in call_logs
                cur.execute("SHOW COLUMNS FROM call_logs")
                existing_logs = {col['Field'] for col in cur.fetchall()}
                for col_name, col_def in [
                    ('qa_score', 'DECIMAL(3,1) DEFAULT NULL'),
                    ('customer_sentiment', "VARCHAR(50) DEFAULT NULL"),
                    ('rto_risk', "VARCHAR(50) DEFAULT NULL"),
                    ('qa_notes', 'TEXT DEFAULT NULL')
                ]:
                    if col_name not in existing_logs:
                        cur.execute(f"ALTER TABLE call_logs ADD COLUMN {col_name} {col_def}")

                # 7. Seed initial sample records if customer table is brand new/empty
                cur.execute("SELECT COUNT(*) AS cnt FROM customers")
                if cur.fetchone()["cnt"] == 0:
                    seed_data = [
                        ('Sidharth Sharma', '9828628181', 'WF-10928', 'Noise-Cancelling Wireless Headphones', '₹1,499', 'Tomorrow by 4 PM', 'Cash on Delivery (COD)', 'Plot 42, Near Metro Station, Mansarovar, Jaipur (302020)', 'PENDING'),
                        ('Abhishek Degra', '9521399708', 'WF-10929', 'Smart Fitness Watch Series 5', '₹2,299', 'In 2 Days', 'Prepaid (UPI)', 'House No 12, Malviya Nagar, Sector 4, Jaipur (302017)', 'PENDING'),
                        ('Lokesh Choudhary', '9358991311', 'WF-10930', 'Fast Charging Power Bank 20000mAh', '₹999', 'Tomorrow by 1 PM', 'Cash on Delivery (COD)', 'Vijay Lal Degra ki Dhani, Sinwar, Jaipur', 'PENDING')
                    ]
                    cur.executemany("""
                    INSERT INTO customers (name, phone, order_id, product_name, product_price, delivery_time, payment_method, notes, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, seed_data)

            server_conn.close()
            self._schema_checked = True
        except Exception as e:
            logger.error("db_ensure_database_and_tables_error", error=str(e))

    def _get_connection(self):
        """Create a new MySQL connection with DictCursor and self-healing resilience."""
        try:
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
        except pymysql.err.OperationalError as e:
            # If database does not exist (1049) or table issue (1146), auto-heal and retry!
            if len(e.args) > 0 and e.args[0] in (1049, 1146):
                logger.info("db_auto_healing_triggered", reason=str(e))
                self._ensure_database_and_tables()
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
            raise

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
        notes: Optional[str] = None,
        product_name: Optional[str] = None,
        product_price: Optional[str] = None,
        delivery_time: Optional[str] = None,
        payment_method: Optional[str] = None
    ) -> int:
        """Insert a single customer into queue with rich order context."""
        def _insert():
            cleaned_phone = "".join(c for c in phone if c.isdigit())
            if len(cleaned_phone) == 12 and cleaned_phone.startswith("91"):
                cleaned_phone = cleaned_phone[2:]

            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO customers (
                            name, phone, order_id, notes, status,
                            product_name, product_price, delivery_time, payment_method
                        )
                        VALUES (%s, %s, %s, %s, 'PENDING', %s, %s, %s, %s)
                        """,
                        (
                            name.strip() or "Customer",
                            cleaned_phone,
                            (order_id or "WF-10928").strip(),
                            notes or "",
                            product_name.strip() if product_name else "Welfog Premium Item",
                            product_price.strip() if product_price else "₹999",
                            delivery_time.strip() if delivery_time else "2-3 Business Days",
                            payment_method.strip() if payment_method else "Cash on Delivery (COD)"
                        )
                    )
                    return cur.lastrowid
            finally:
                conn.close()

        return await asyncio.to_thread(_insert)

    async def bulk_add_customers(self, entries: List[Dict[str, str]]) -> int:
        """Bulk insert customers from list of dicts with optional order metadata."""
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
                            INSERT INTO customers (
                                name, phone, order_id, notes, status,
                                product_name, product_price, delivery_time, payment_method
                            )
                            VALUES (%s, %s, %s, %s, 'PENDING', %s, %s, %s, %s)
                            """,
                            (
                                item.get("name", "Customer").strip() or "Customer",
                                cleaned,
                                item.get("order_id", "WF-10928").strip() or "WF-10928",
                                item.get("notes", "Bulk Onboarded"),
                                item.get("product_name") or "Welfog Premium Item",
                                item.get("product_price") or "₹999",
                                item.get("delivery_time") or "2-3 Business Days",
                                item.get("payment_method") or "Cash on Delivery (COD)"
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
        notes: Optional[str] = None,
        product_name: Optional[str] = None,
        product_price: Optional[str] = None,
        delivery_time: Optional[str] = None,
        payment_method: Optional[str] = None
    ) -> bool:
        """Edit customer info and order metadata."""
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
                        SET name = %s, phone = %s, order_id = %s, notes = %s,
                            product_name = COALESCE(%s, product_name),
                            product_price = COALESCE(%s, product_price),
                            delivery_time = COALESCE(%s, delivery_time),
                            payment_method = COALESCE(%s, payment_method)
                        WHERE id = %s
                        """,
                        (
                            name.strip(),
                            cleaned,
                            order_id.strip() if order_id else "WF-10928",
                            notes or "",
                            product_name,
                            product_price,
                            delivery_time,
                            payment_method,
                            customer_id
                        )
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
        recording_url: Optional[str] = None,
        qa_score: Optional[float] = None,
        customer_sentiment: Optional[str] = None,
        rto_risk: Optional[str] = None,
        qa_notes: Optional[str] = None
    ) -> bool:
        """Update customer call status and record notes/transcript/recording/QA scores."""
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
                        params.append(mask_sensitive_pii(call_summary))

                    if transcript is not None:
                        updates.append("transcript = %s")
                        params.append(mask_sensitive_pii(transcript))

                    if recording_url is not None:
                        updates.append("recording_url = %s")
                        params.append(recording_url)

                    if qa_score is not None:
                        updates.append("qa_score = %s")
                        params.append(qa_score)

                    if customer_sentiment is not None:
                        updates.append("customer_sentiment = %s")
                        params.append(customer_sentiment.upper())

                    if rto_risk is not None:
                        updates.append("rto_risk = %s")
                        params.append(rto_risk.upper())

                    if qa_notes is not None:
                        updates.append("qa_notes = %s")
                        params.append(mask_sensitive_pii(qa_notes))

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
        recording_url: Optional[str] = None,
        qa_score: Optional[float] = None,
        customer_sentiment: Optional[str] = None,
        rto_risk: Optional[str] = None,
        qa_notes: Optional[str] = None
    ) -> int:
        """Insert historical call record into call_logs table with QA metrics."""
        def _insert():
            conn = self._get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO call_logs (
                            customer_id, phone, customer_name, order_id, status, duration, 
                            summary, transcript, recording_url, qa_score, customer_sentiment, rto_risk, qa_notes
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            customer_id, phone, customer_name, order_id, status.upper(), duration,
                            mask_sensitive_pii(summary or ""),
                            mask_sensitive_pii(transcript or ""),
                            recording_url or "",
                            qa_score if qa_score is not None else 9.0,
                            (customer_sentiment or "NEUTRAL").upper(),
                            (rto_risk or "LOW").upper(),
                            mask_sensitive_pii(qa_notes or "")
                        )
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
