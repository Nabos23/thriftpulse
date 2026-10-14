"""
SQLite Database helper for Thrift Shoes orders and message logs.
Zero-config local database with WAL mode for fast concurrency.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from app.core.config import settings
from app.core.logging import get_logger
from app.models.order import Order

import os

logger = get_logger(__name__)


def _get_db_path() -> Path:
    """Use /tmp on Vercel/serverless environments where cwd is read-only."""
    if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return Path("/tmp/thrift_orders.db")
    return Path("thrift_orders.db")


def get_db_connection() -> sqlite3.Connection:
    """Get a connection to the SQLite database with safe journal mode."""
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


def init_db() -> None:
    """Initialize database tables and indexes."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
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
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS message_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT UNIQUE,
                    sender_phone TEXT,
                    raw_type TEXT,
                    text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Search indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_customer_name ON orders(customer_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_phone_primary ON orders(phone_primary);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_order_code ON orders(order_code);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);")

        logger.info("database_initialized", db_path=str(_get_db_path().resolve()))
    finally:
        conn.close()


def _row_to_order(row: sqlite3.Row) -> Order:
    return Order(
        id=row["id"],
        order_code=row["order_code"],
        created_at=str(row["created_at"]),
        customer_name=row["customer_name"],
        phone_primary=row["phone_primary"],
        phone_secondary=row["phone_secondary"] or "",
        address=row["address"],
        area=row["area"],
        city=row["city"],
        nearest_landmark=row["nearest_landmark"] or "",
        shoe_brand_model=row["shoe_brand_model"],
        shoe_size=row["shoe_size"],
        price=float(row["price"]),
        payment_method=row["payment_method"] or "Cash on Delivery",
        shoe_image_path=row["shoe_image_path"] or "",
        invoice_path=row["invoice_path"] or "",
        status=row["status"] or "Pending",
        notes=row["notes"] or "",
        sheets_synced=bool(row["sheets_synced"]),
    )


def insert_order_sync(data: dict[str, Any]) -> Order:
    """Synchronous insertion of an order."""
    conn = get_db_connection()
    try:
        with conn:
            # Generate next order code if not provided
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(id) as max_id FROM orders")
            row = cursor.fetchone()
            next_id = (row["max_id"] or 0) + 1
            order_code = data.get("order_code") or f"TS-{1000 + next_id}"
            now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE order_code = ? OR order_code = ?", (code, code.upper()))
        row = cursor.fetchone()
        return _row_to_order(row) if row else None
    finally:
        conn.close()


async def get_order_by_code(code: str) -> Optional[Order]:
    return await asyncio.to_thread(get_order_by_code_sync, code)


def search_orders_sync(query: str, limit: int = 10) -> list[Order]:
    """Search orders across multiple fields: name, phone, city, shoe, or code."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        clean_q = query.strip()
        pattern = f"%{clean_q}%"

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


async def update_order_sync_status(order_id: int, synced: bool, invoice_path: Optional[str] = None) -> None:
    await asyncio.to_thread(update_order_sync_status_sync, order_id, synced, invoice_path)


def log_message_sync(message_id: str, sender: str, raw_type: str, text: str) -> None:
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
