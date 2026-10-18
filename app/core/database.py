"""
Database connector supporting Turso Cloud (libSQL over HTTP pipeline) with
seamless fallback to local SQLite (WAL mode).
Zero local Rust/C compiler dependencies - 100% portable across Windows, Linux, and Vercel.
"""
from __future__ import annotations

import asyncio
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.models.order import Order

logger = get_logger(__name__)


# ── Turso Cloud LibSQL Pipeline Helpers ─────────────────────────────────────────

def is_turso_enabled() -> bool:
    """Check if Turso database credentials are configured."""
    url = getattr(settings, "TURSO_DATABASE_URL", "") or os.getenv("TURSO_DATABASE_URL", "")
    token = getattr(settings, "TURSO_AUTH_TOKEN", "") or os.getenv("TURSO_AUTH_TOKEN", "")
    return bool(url and token)


def _get_turso_endpoint() -> str:
    """Derive Turso HTTP /v2/pipeline endpoint from URL."""
    raw = getattr(settings, "TURSO_DATABASE_URL", "") or os.getenv("TURSO_DATABASE_URL", "")
    if raw.startswith("libsql://"):
        host = raw[len("libsql://"):].rstrip("/")
        return f"https://{host}/v2/pipeline"
    cleaned = raw.rstrip("/")
    if not cleaned.endswith("/v2/pipeline"):
        return f"{cleaned}/v2/pipeline"
    return cleaned


def _get_turso_headers() -> dict[str, str]:
    token = getattr(settings, "TURSO_AUTH_TOKEN", "") or os.getenv("TURSO_AUTH_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _serialize_turso_arg(v: Any) -> dict[str, Any]:
    """Serialize Python types to Hrana v2 protocol types."""
    if v is None:
        return {"type": "null"}
    elif isinstance(v, bool):
        return {"type": "integer", "value": "1" if v else "0"}
    elif isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    elif isinstance(v, float):
        return {"type": "float", "value": v}
    else:
        return {"type": "text", "value": str(v)}


def _deserialize_turso_val(cell: dict[str, Any]) -> Any:
    """Deserialize Hrana v2 cell into Python type."""
    t = cell.get("type")
    if t == "null":
        return None
    elif t == "integer":
        val = cell.get("value")
        return int(val) if val is not None else None
    elif t == "float":
        val = cell.get("value")
        return float(val) if val is not None else None
    elif t == "text":
        return cell.get("value", "")
    elif t == "blob":
        return cell.get("base64", "")
    return cell.get("value")


def _turso_query(sql: str, args: list[Any] | None = None) -> list[dict[str, Any]]:
    """Execute a SELECT query against Turso Cloud and return list of dicts."""
    endpoint = _get_turso_endpoint()
    headers = _get_turso_headers()
    stmt: dict[str, Any] = {"sql": sql}
    if args:
        stmt["args"] = [_serialize_turso_arg(a) for a in args]
    payload = {"requests": [{"type": "execute", "stmt": stmt}]}

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(endpoint, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        result = data["results"][0]["response"]["result"]
        cols = [c["name"] for c in result["cols"]]
        rows = []
        for raw_row in result["rows"]:
            row_dict = {cols[i]: _deserialize_turso_val(raw_row[i]) for i in range(len(cols))}
            rows.append(row_dict)
        return rows


def _turso_execute(sql: str, args: list[Any] | None = None) -> dict[str, Any]:
    """Execute an INSERT/UPDATE/DDL statement against Turso Cloud."""
    endpoint = _get_turso_endpoint()
    headers = _get_turso_headers()
    stmt: dict[str, Any] = {"sql": sql}
    if args:
        stmt["args"] = [_serialize_turso_arg(a) for a in args]
    payload = {"requests": [{"type": "execute", "stmt": stmt}]}

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(endpoint, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["results"][0]["response"]["result"]


# ── SQLite Local Fallback Helpers ──────────────────────────────────────────────

def _get_db_path() -> Path:
    """Use /tmp on Vercel/serverless environments where cwd is read-only."""
    if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return Path("/tmp/thrift_orders.db")
    return Path("thrift_orders.db")


def get_db_connection() -> sqlite3.Connection:
    """Get a connection to the local SQLite database with safe journal mode."""
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        try:
            conn.execute("PRAGMA journal_mode=DELETE;")
        except Exception:
            pass
    return conn


def _row_to_order(row: sqlite3.Row | dict[str, Any]) -> Order:
    """Convert an SQLite Row or Turso dict into a Pydantic Order model."""
    return Order(
        id=int(row["id"]) if row.get("id") is not None else None,
        order_code=str(row["order_code"]),
        created_at=str(row["created_at"]),
        customer_name=str(row["customer_name"]),
        phone_primary=str(row["phone_primary"]),
        phone_secondary=str(row.get("phone_secondary") or ""),
        address=str(row["address"]),
        area=str(row["area"]),
        city=str(row["city"]),
        nearest_landmark=str(row.get("nearest_landmark") or ""),
        shoe_brand_model=str(row["shoe_brand_model"]),
        shoe_size=str(row["shoe_size"]),
        price=float(row["price"]),
        payment_method=str(row.get("payment_method") or "Cash on Delivery"),
        shoe_image_path=str(row.get("shoe_image_path") or ""),
        invoice_path=str(row.get("invoice_path") or ""),
        status=str(row.get("status") or "Pending"),
        notes=str(row.get("notes") or ""),
        sheets_synced=bool(int(row.get("sheets_synced") or 0)),
    )


# ── Database Operations (Turso Cloud + SQLite Local Fallback) ──────────────────

def init_db() -> None:
    """Initialize database tables and indexes on Turso Cloud and/or SQLite."""
    create_orders_sql = """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_code TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            customer_name TEXT NOT NULL,
            phone_primary TEXT NOT NULL,
            phone_secondary TEXT,
            address TEXT NOT NULL,
            area TEXT NOT NULL,
            city TEXT NOT NULL,
            nearest_landmark TEXT,
            shoe_brand_model TEXT NOT NULL,
            shoe_size TEXT NOT NULL,
            price REAL NOT NULL,
            payment_method TEXT DEFAULT 'Cash on Delivery',
            shoe_image_path TEXT,
            invoice_path TEXT,
            status TEXT DEFAULT 'Pending',
            notes TEXT,
            sheets_synced INTEGER DEFAULT 0
        )
    """
    create_logs_sql = """
        CREATE TABLE IF NOT EXISTS message_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE,
            sender_phone TEXT,
            raw_type TEXT,
            text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_orders_customer_name ON orders(customer_name);",
        "CREATE INDEX IF NOT EXISTS idx_orders_phone_primary ON orders(phone_primary);",
        "CREATE INDEX IF NOT EXISTS idx_orders_order_code ON orders(order_code);",
        "CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);",
    ]

    if is_turso_enabled():
        try:
            _turso_execute(create_orders_sql)
            _turso_execute(create_logs_sql)
            for idx in indexes:
                _turso_execute(idx)
            logger.info("turso_database_initialized", endpoint=_get_turso_endpoint())
        except Exception as e:
            logger.error("turso_init_db_error", error=str(e))

    # Also initialize local SQLite for local dev or fallback
    try:
        conn = get_db_connection()
        try:
            with conn:
                conn.execute(create_orders_sql)
                conn.execute(create_logs_sql)
                for idx in indexes:
                    conn.execute(idx)
            logger.info("sqlite_database_initialized", db_path=str(_get_db_path().resolve()))
        finally:
            conn.close()
    except Exception as e:
        logger.warning("sqlite_init_db_warning", error=str(e))


def insert_order_sync(data: dict[str, Any]) -> Order:
    """Synchronous insertion of an order into Turso Cloud or local SQLite."""
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Mode 1: Turso Cloud
    if is_turso_enabled():
        try:
            # Generate next order code if not provided
            max_row = _turso_query("SELECT MAX(id) as max_id FROM orders")
            max_id = (max_row[0]["max_id"] if max_row else 0) or 0
            order_code = data.get("order_code") or f"TS-{1000 + max_id + 1}"

            # Guarantee order_code uniqueness
            while True:
                exists = _turso_query("SELECT 1 FROM orders WHERE order_code = ?", [order_code])
                if not exists:
                    break
                m = re.search(r"TS-(\d+)", order_code, re.IGNORECASE)
                if m:
                    order_code = f"TS-{int(m.group(1)) + 1}"
                else:
                    order_code = f"{order_code}_1"

            sql = """
                INSERT INTO orders (
                    order_code, created_at, customer_name, phone_primary, phone_secondary,
                    address, area, city, nearest_landmark, shoe_brand_model, shoe_size,
                    price, payment_method, shoe_image_path, invoice_path, status, notes, sheets_synced
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING *
            """
            args = [
                order_code,
                now_iso,
                data["customer_name"],
                data["phone_primary"],
                data.get("phone_secondary", ""),
                data["address"],
                data["area"],
                data["city"],
                data.get("nearest_landmark", ""),
                data["shoe_brand_model"],
                data["shoe_size"],
                float(data["price"]),
                data.get("payment_method", "Cash on Delivery"),
                data.get("shoe_image_path", ""),
                data.get("invoice_path", ""),
                data.get("status", "Pending"),
                data.get("notes", ""),
                1 if data.get("sheets_synced") else 0,
            ]
            rows = _turso_query(sql, args)
            if rows:
                logger.info("order_inserted_turso", order_code=order_code)
                return _row_to_order(rows[0])
        except Exception as e:
            logger.error("turso_insert_order_error_falling_back_to_sqlite", error=str(e))

    # Mode 2: Local SQLite fallback
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(id) as max_id FROM orders")
            row = cursor.fetchone()
            next_id = (row["max_id"] or 0) + 1
            order_code = data.get("order_code") or f"TS-{1000 + next_id}"

            while True:
                cursor.execute("SELECT 1 FROM orders WHERE order_code = ?", (order_code,))
                if not cursor.fetchone():
                    break
                m = re.search(r"TS-(\d+)", order_code, re.IGNORECASE)
                if m:
                    order_code = f"TS-{int(m.group(1)) + 1}"
                else:
                    order_code = f"{order_code}_1"

            cursor.execute("""
                INSERT INTO orders (
                    order_code, created_at, customer_name, phone_primary, phone_secondary,
                    address, area, city, nearest_landmark, shoe_brand_model, shoe_size,
                    price, payment_method, shoe_image_path, invoice_path, status, notes, sheets_synced
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order_code,
                now_iso,
                data["customer_name"],
                data["phone_primary"],
                data.get("phone_secondary", ""),
                data["address"],
                data["area"],
                data["city"],
                data.get("nearest_landmark", ""),
                data["shoe_brand_model"],
                data["shoe_size"],
                float(data["price"]),
                data.get("payment_method", "Cash on Delivery"),
                data.get("shoe_image_path", ""),
                data.get("invoice_path", ""),
                data.get("status", "Pending"),
                data.get("notes", ""),
                1 if data.get("sheets_synced") else 0,
            ))
            inserted_id = cursor.lastrowid
            cursor.execute("SELECT * FROM orders WHERE id = ?", (inserted_id,))
            saved_row = cursor.fetchone()
            return _row_to_order(saved_row)
    finally:
        conn.close()


async def insert_order(data: dict[str, Any]) -> Order:
    return await asyncio.to_thread(insert_order_sync, data)


def get_order_by_id_sync(order_id: int) -> Optional[Order]:
    if is_turso_enabled():
        try:
            rows = _turso_query("SELECT * FROM orders WHERE id = ?", [order_id])
            if rows:
                return _row_to_order(rows[0])
        except Exception as e:
            logger.error("turso_get_order_by_id_error", error=str(e), order_id=order_id)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        row = cursor.fetchone()
        return _row_to_order(row) if row else None
    finally:
        conn.close()


async def get_order_by_id(order_id: int) -> Optional[Order]:
    return await asyncio.to_thread(get_order_by_id_sync, order_id)


def get_order_by_code_sync(code: str) -> Optional[Order]:
    clean_code = code.strip()

    # 1. Turso Cloud
    if is_turso_enabled():
        try:
            rows = _turso_query(
                "SELECT * FROM orders WHERE order_code = ? OR order_code = ?",
                [clean_code, clean_code.upper()],
            )
            if rows:
                return _row_to_order(rows[0])
        except Exception as e:
            logger.error("turso_get_order_by_code_error", error=str(e), code=clean_code)

    # 2. Local SQLite
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE order_code = ? OR order_code = ?", (clean_code, clean_code.upper()))
        row = cursor.fetchone()
        if row:
            return _row_to_order(row)
    finally:
        conn.close()

    # 3. Fallback to Google Sheets
    try:
        from app.connectors.google_sheets import get_sheets_sync
        sheets = get_sheets_sync()
        rows = sheets.search_sheet(clean_code, limit=3)
        for r in rows:
            if r.get("order_code", "").strip().upper() == clean_code.upper():
                return Order(
                    id=int(r.get("row_number") or 1),
                    order_code=r.get("order_code", ""),
                    created_at=str(r.get("created_at") or ""),
                    customer_name=r.get("customer_name", ""),
                    phone_primary=r.get("phone_primary", ""),
                    phone_secondary=r.get("phone_secondary", ""),
                    address=r.get("full_address", "") or r.get("city", ""),
                    area=r.get("city", ""),
                    city=r.get("city", ""),
                    shoe_brand_model=r.get("shoe_brand_model", ""),
                    shoe_size=r.get("shoe_size", ""),
                    price=float(str(r.get("price", "0")).replace(",", "") or 0),
                    payment_method=r.get("payment_method", "Cash on Delivery"),
                    status=r.get("status", "Pending"),
                    shoe_image_path=r.get("shoe_image_path", ""),
                    invoice_path=r.get("invoice_path", ""),
                    notes=r.get("notes", ""),
                )
    except Exception as e:
        logger.error("get_order_by_code_sheet_fallback_error", error=str(e), code=clean_code)
    return None


async def get_order_by_code(code: str) -> Optional[Order]:
    return await asyncio.to_thread(get_order_by_code_sync, code)


def search_orders_sync(query: str, limit: int = 10) -> list[Order]:
    """Search orders across multiple fields: name, phone, city, shoe, or code."""
    clean_q = query.strip()
    pattern = f"%{clean_q}%"

    if is_turso_enabled():
        try:
            sql = """
                SELECT * FROM orders
                WHERE customer_name LIKE ?
                   OR phone_primary LIKE ?
                   OR phone_secondary LIKE ?
                   OR order_code LIKE ?
                   OR city LIKE ?
                   OR shoe_brand_model LIKE ?
                ORDER BY id DESC
                LIMIT ?
            """
            rows = _turso_query(sql, [pattern, pattern, pattern, pattern, pattern, pattern, limit])
            return [_row_to_order(r) for r in rows]
        except Exception as e:
            logger.error("turso_search_orders_error", error=str(e), query=clean_q)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM orders
            WHERE customer_name LIKE ?
               OR phone_primary LIKE ?
               OR phone_secondary LIKE ?
               OR order_code LIKE ?
               OR city LIKE ?
               OR shoe_brand_model LIKE ?
            ORDER BY id DESC
            LIMIT ?
        """, (pattern, pattern, pattern, pattern, pattern, pattern, limit))

        rows = cursor.fetchall()
        return [_row_to_order(r) for r in rows]
    finally:
        conn.close()


async def search_orders(query: str, limit: int = 10) -> list[Order]:
    return await asyncio.to_thread(search_orders_sync, query, limit)


def get_recent_orders_sync(limit: int = 10) -> list[Order]:
    if is_turso_enabled():
        try:
            rows = _turso_query("SELECT * FROM orders ORDER BY id DESC LIMIT ?", [limit])
            return [_row_to_order(r) for r in rows]
        except Exception as e:
            logger.error("turso_get_recent_orders_error", error=str(e))

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        return [_row_to_order(r) for r in rows]
    finally:
        conn.close()


async def get_recent_orders(limit: int = 10) -> list[Order]:
    return await asyncio.to_thread(get_recent_orders_sync, limit)


def update_order_sync_status_sync(order_id: int, synced: bool, invoice_path: Optional[str] = None) -> None:
    if is_turso_enabled():
        try:
            if invoice_path:
                _turso_execute(
                    "UPDATE orders SET sheets_synced = ?, invoice_path = ? WHERE id = ?",
                    [1 if synced else 0, invoice_path, order_id],
                )
            else:
                _turso_execute(
                    "UPDATE orders SET sheets_synced = ? WHERE id = ?",
                    [1 if synced else 0, order_id],
                )
            return
        except Exception as e:
            logger.error("turso_update_order_sync_status_error", error=str(e), order_id=order_id)

    conn = get_db_connection()
    try:
        with conn:
            if invoice_path:
                conn.execute(
                    "UPDATE orders SET sheets_synced = ?, invoice_path = ? WHERE id = ?",
                    (1 if synced else 0, invoice_path, order_id),
                )
            else:
                conn.execute(
                    "UPDATE orders SET sheets_synced = ? WHERE id = ?",
                    (1 if synced else 0, order_id),
                )
    finally:
        conn.close()


def get_orders_by_codes_sync(codes: list[str]) -> list[Order]:
    """Retrieve multiple orders by order codes in requested order."""
    orders: list[Order] = []
    for c in codes:
        clean = c.strip()
        if not clean:
            continue
        ord_obj = get_order_by_code_sync(clean)
        if ord_obj:
            orders.append(ord_obj)
    return orders


async def get_orders_by_codes(codes: list[str]) -> list[Order]:
    return await asyncio.to_thread(get_orders_by_codes_sync, codes)



async def update_order_sync_status(order_id: int, synced: bool, invoice_path: Optional[str] = None) -> None:
    await asyncio.to_thread(update_order_sync_status_sync, order_id, synced, invoice_path)


def log_message_sync(message_id: str, sender: str, raw_type: str, text: str) -> None:
    if is_turso_enabled():
        try:
            _turso_execute(
                "INSERT OR IGNORE INTO message_logs (message_id, sender_phone, raw_type, text) VALUES (?, ?, ?, ?)",
                [message_id, sender, raw_type, text],
            )
            return
        except Exception as e:
            logger.error("turso_log_message_error", error=str(e), message_id=message_id)

    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
                INSERT OR IGNORE INTO message_logs (message_id, sender_phone, raw_type, text)
                VALUES (?, ?, ?, ?)
            """, (message_id, sender, raw_type, text))
    finally:
        conn.close()


async def log_message(message_id: str, sender: str, raw_type: str, text: str) -> None:
    await asyncio.to_thread(log_message_sync, message_id, sender, raw_type, text)
