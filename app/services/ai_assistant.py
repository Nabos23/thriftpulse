"""
Multilingual AI Assistant for Store Owner.
Handles conversational inquiries in English, Urdu, and Roman Urdu.
Executes tool calls to query SQLite database and dispatches shoe images.
"""
from __future__ import annotations

import json
from typing import Any
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.database import search_orders, get_order_by_code, get_order_by_id, get_recent_orders
from app.core.logging import get_logger
from app.models.order import Order

logger = get_logger(__name__)

_client: AsyncOpenAI | None = None


def _get_active_provider_and_model() -> tuple[str, str]:
    provider = getattr(settings, "LLM_PROVIDER", "auto").lower()
    if provider == "openrouter":
        return "openrouter", settings.DEFAULT_MODEL
    elif provider == "groq":
        return "groq", getattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")
    elif provider == "openai":
        return "openai", getattr(settings, "DEFAULT_MODEL", "gpt-4.1")

    # Auto mode resolution:
    if settings.OPENROUTER_API_KEY:
        return "openrouter", settings.DEFAULT_MODEL
    if settings.GROQ_API_KEY:
        return "groq", getattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")
    if settings.OPENAI_API_KEY:
        return "openai", "gpt-4.1"

    return "openrouter", settings.DEFAULT_MODEL


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        provider, _ = _get_active_provider_and_model()
        if provider == "openrouter":
            api_key = settings.OPENROUTER_API_KEY or settings.OPENAI_API_KEY
            _client = AsyncOpenAI(
                api_key=api_key,
                base_url=settings.OPENROUTER_BASE_URL,
                default_headers={
                    "HTTP-Referer": settings.BASE_URL,
                    "X-Title": settings.STORE_NAME,
                },
            )
        elif provider == "groq":
            _client = AsyncOpenAI(
                api_key=settings.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
            )
        else:
            _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


SYSTEM_PROMPT = """ALWAYS Reply in English, even if the human is talking in Urdu or Roman Urdu.
You are the intelligent WhatsApp AI Assistant for "Thrifted Shoes PK", assisting the store OWNER.
The owner messages you via WhatsApp (in English, Urdu, or Roman Urdu like "Ali k joote ki details do", "Ali ka order add karo: 03129214688, Lahore, Jordan 4 size 42, 4500 COD", "Mark TS-1001 as Shipped", "Sheet check karo").

Tool Priority & Rules:
1. DATABASE FIRST: For any general query, search, customer lookup, or order status check, ALWAYS use the local database first (`search_orders_db` or `get_recent_orders_db`).
2. GOOGLE SHEETS ON REQUEST ONLY: ONLY call `read_google_sheet` if the owner explicitly asks to check, read, or search the "sheet", "Google Sheet", or "spreadsheet" (e.g. "sheet check karo", "search in sheet", "sheet mein dekho").
3. ADDING ORDERS: When the owner asks to add or record an order (e.g. "Add order for Bilal...", "Bilal ka order add karo..."), ALWAYS call `add_order_to_sheet_and_db` with all extracted fields (name, phone, city, address, shoe model, size, price).
4. ORDER CONFIRMATION: When an order is added, confirm politely with:
   - Order Code (e.g. TS-1002)
   - Customer Name & Phone
   - Delivery Address & City
   - Shoe Article & Size
   - Amount & Payment Method
   - 1-Tap Waybill Print Link
5. UPDATING STATUS: When the owner asks to update order status (e.g. "Mark TS-1001 as Dispatched/Delivered/Cancelled"), use `update_order_status_in_sheet`.
6. SINGLE MATCH: If search yields a SINGLE match, summarize customer name, phone, address, shoe, and COD price clearly along with pic of the shoe.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_order_to_sheet_and_db",
            "description": "Add a complete new order into Google Sheets and local database when customer or owner dictates order details. Generates order code, thermal waybill, and syncs immediately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {
                        "type": "string",
                        "description": "Customer full name (e.g. 'Soban Bin Nadeem', 'Ali Raza')",
                    },
                    "phone_primary": {
                        "type": "string",
                        "description": "Customer mobile phone number (e.g. '03129214688')",
                    },
                    "city": {
                        "type": "string",
                        "description": "Delivery city (e.g. 'Lahore', 'Karachi', 'Islamabad')",
                    },
                    "address": {
                        "type": "string",
                        "description": "Complete street delivery address",
                    },
                    "shoe_brand_model": {
                        "type": "string",
                        "description": "Shoe article, brand, and model (e.g. 'Nike Dunk High', 'Jordan 4 Retro', 'Adidas Yeezy 350')",
                    },
                    "shoe_size": {
                        "type": "string",
                        "description": "Shoe size (e.g. '41', '42', '9 UK', '10 US')",
                    },
                    "price": {
                        "type": "number",
                        "description": "Total COD price in PKR (e.g. 4200, 5500)",
                    },
                    "payment_method": {
                        "type": "string",
                        "description": "Payment method (default: 'Cash on Delivery')",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Special instructions or notes",
                    },
                    "area": {
                        "type": "string",
                        "description": "Neighborhood/Town/Sector (optional)",
                    },
                    "phone_secondary": {
                        "type": "string",
                        "description": "Alternative phone number (optional)",
                    },
                },
                "required": [
                    "customer_name",
                    "phone_primary",
                    "city",
                    "address",
                    "shoe_brand_model",
                    "shoe_size",
                    "price",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_google_sheet",
            "description": "Read orders directly from the live Google Sheet. Use ONLY when the owner explicitly asks to check or read the Google Sheet or spreadsheet (e.g. 'sheet check karo', 'search sheet'). For all general queries and customer lookups, always use search_orders_db instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword or order code (e.g. 'Ali', 'TS-1001', '03129214688', 'Lahore')",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows to return (default: 5)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_order_status_in_sheet",
            "description": "Update the delivery or processing status of an order in Google Sheets and database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_code": {
                        "type": "string",
                        "description": "The order code (e.g. 'TS-1001')",
                    },
                    "new_status": {
                        "type": "string",
                        "description": "The updated status (e.g. 'Confirmed', 'Dispatched', 'Delivered', 'Cancelled', 'Returned')",
                    },
                },
                "required": ["order_code", "new_status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_orders_db",
            "description": "Search for orders across customer name, phone number, city, shoe description, or order code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search term (e.g. 'Ali', '03129214688', 'Lahore', 'Nike Air', 'TS-1001')",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_orders_db",
            "description": "Get the most recent orders placed in the store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent orders to fetch (default: 5)",
                    }
                },
            },
        },
    },
]


def _format_order_card(order: Order, base_url: str) -> str:
    invoice_link = f"{base_url}/invoice/{order.order_code}"
    lines = [
        f"👟 *Order #{order.order_code}*",
        f"━━━━━━━━━━━━━━━━━━",
        f"👤 *Customer:* {order.customer_name}",
        f"📞 *Primary Phone:* {order.phone_primary}",
    ]
    if order.phone_secondary:
        lines.append(f"📱 *Alt Phone:* {order.phone_secondary}")
    lines.extend([
        f"🏙️ *City:* {order.city}",
        f"📍 *Address:* {order.full_address}",
        f"👟 *Item:* {order.shoe_brand_model} (Size: {order.shoe_size})",
        f"💵 *Amount:* PKR {order.price:,.0f} ({order.payment_method})",
        f"📦 *Status:* {order.status}",
        f"📅 *Date:* {order.created_at[:16]}",
        f"📄 *Waybill Link:* {invoice_link}",
    ])
    if order.notes:
        lines.append(f"📝 *Note:* {order.notes}")

    if order.shoe_image_path:
        lines.append("\n📸 _Shoe picture sent below:_")
    return "\n".join(lines)


async def execute_tool(name: str, args: dict[str, Any], base_url: str = "") -> tuple[str, list[Order]]:
    """Execute tool and return JSON result + list of matched orders."""
    if name == "add_order_to_sheet_and_db":
        try:
            from app.connectors.google_sheets import get_sheets_sync
            from app.core.database import insert_order
            from app.services.invoice_generator import save_invoice_file

            sheets = get_sheets_sync()
            order_code = sheets.get_next_order_code()

            order_data = {
                "order_code": order_code,
                "customer_name": args.get("customer_name", "").strip(),
                "phone_primary": args.get("phone_primary", "").strip(),
                "phone_secondary": args.get("phone_secondary", "").strip(),
                "city": args.get("city", "").strip(),
                "area": args.get("area", "").strip() or args.get("city", "").strip(),
                "address": args.get("address", "").strip(),
                "nearest_landmark": args.get("nearest_landmark", "").strip(),
                "shoe_brand_model": args.get("shoe_brand_model", "").strip(),
                "shoe_size": str(args.get("shoe_size", "")).strip(),
                "price": float(args.get("price", 0)),
                "payment_method": args.get("payment_method", "Cash on Delivery").strip(),
                "notes": args.get("notes", "").strip(),
                "shoe_image_path": "",
                "status": "Pending",
                "sheets_synced": True,
            }

            new_order = await insert_order(order_data)
            inv_path = save_invoice_file(new_order)
            new_order.invoice_path = inv_path

            # Append to Google Sheet in real-time
            sheet_res = sheets.append_order(new_order)

            result_summary = {
                "status": "success",
                "order_code": new_order.order_code,
                "customer_name": new_order.customer_name,
                "phone": new_order.phone_primary,
                "city": new_order.city,
                "full_address": new_order.full_address,
                "shoe": f"{new_order.shoe_brand_model} (Size: {new_order.shoe_size})",
                "price": f"PKR {new_order.price:,.0f}",
                "payment_method": new_order.payment_method,
                "invoice_url": f"{base_url}/invoice/{new_order.order_code}",
                "google_sheets_sync": sheet_res.get("status", "unknown"),
            }
            return json.dumps(result_summary), [new_order]
        except Exception as e:
            logger.error("add_order_tool_error", error=str(e))
            return json.dumps({"status": "error", "error": str(e)}), []

    elif name == "read_google_sheet":
        try:
            from app.connectors.google_sheets import get_sheets_sync
            sheets = get_sheets_sync()
            rows = sheets.search_sheet(args.get("query", ""), limit=args.get("limit", 5))
            return json.dumps(rows), []
        except Exception as e:
            logger.error("read_google_sheet_error", error=str(e))
            return json.dumps({"status": "error", "error": str(e)}), []

    elif name == "update_order_status_in_sheet":
        try:
            from app.connectors.google_sheets import get_sheets_sync
            from app.core.database import get_db_connection
            sheets = get_sheets_sync()
            order_code = args.get("order_code", "").strip().upper()
            new_status = args.get("new_status", "").strip()
            sheet_res = sheets.update_order_status(order_code, new_status)

            # Also update SQLite DB
            try:
                conn = get_db_connection()
                with conn:
                    conn.execute(
                        "UPDATE orders SET status = ? WHERE order_code = ? OR order_code = ?",
                        (new_status, order_code, order_code.lower())
                    )
                conn.close()
            except Exception:
                pass

            return json.dumps(sheet_res), []
        except Exception as e:
            logger.error("update_order_status_tool_error", error=str(e))
            return json.dumps({"status": "error", "error": str(e)}), []

    elif name == "search_orders_db":
        query = args.get("query", "")
        orders = await search_orders(query, limit=5)
        if not orders:
            # Fallback to search directly in Google Sheet
            try:
                from app.connectors.google_sheets import get_sheets_sync
                sheets = get_sheets_sync()
                sheet_rows = sheets.search_sheet(query, limit=5)
                if sheet_rows:
                    return json.dumps(sheet_rows), []
            except Exception:
                pass
        serialized = [o.model_dump() for o in orders]
        return json.dumps(serialized), orders

    elif name == "get_recent_orders_db":
        limit = args.get("limit", 5)
        orders = await get_recent_orders(limit=limit)
        if not orders:
            try:
                from app.connectors.google_sheets import get_sheets_sync
                sheets = get_sheets_sync()
                sheet_rows = sheets.search_sheet("", limit=limit)
                if sheet_rows:
                    return json.dumps(sheet_rows), []
            except Exception:
                pass
        serialized = [o.model_dump() for o in orders]
        return json.dumps(serialized), orders

    return "[]", []


async def process_owner_query(text: str, sender_phone: str, base_url: str) -> dict[str, Any]:
    """
    Main query pipeline for WhatsApp message from owner.
    Returns:
      {
        "reply_text": str,
        "image_url": str | None,
        "image_caption": str | None
      }
    """
    client = _get_client()
    provider, active_model = _get_active_provider_and_model()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]

    try:
        response = await client.chat.completions.create(
            model=active_model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )

        choice = response.choices[0].message
        image_to_send: str | None = None
        caption_to_send: str | None = None

        if choice.tool_calls:
            # Handle tool calls - normalize to dict for maximum OpenRouter compatibility
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": choice.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in choice.tool_calls
                ],
            }
            messages.append(assistant_msg)
            matched_orders: list[Order] = []

            for tool_call in choice.tool_calls:
                fn_name = tool_call.function.name
                raw_args = tool_call.function.arguments or "{}"
                try:
                    fn_args = json.loads(raw_args)
                    if not isinstance(fn_args, dict):
                        fn_args = {"query": str(fn_args)}
                except Exception:
                    fn_args = {"query": text}

                tool_output, orders = await execute_tool(fn_name, fn_args, base_url)
                matched_orders.extend(orders)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_output,
                })

            # Check if exactly one order was matched -> prepare image dispatch
            if len(matched_orders) == 1:
                single_order = matched_orders[0]
                if single_order.shoe_image_path:
                    # Construct full image URL
                    rel = single_order.shoe_image_path.lstrip("/")
                    image_to_send = f"{base_url}/{rel}"
                    caption_to_send = f"👟 Shoe photo for {single_order.customer_name} (#{single_order.order_code})"

            # Get final AI answer
            second_resp = await client.chat.completions.create(
                model=active_model,
                messages=messages,
                temperature=0.2,
            )
            final_reply = second_resp.choices[0].message.content or ""

            return {
                "reply_text": final_reply,
                "image_url": image_to_send,
                "image_caption": caption_to_send,
            }

        return {
            "reply_text": choice.content or "Main aapki kya madad kar sakta hoon?",
            "image_url": None,
            "image_caption": None,
        }

    except Exception as e:
        logger.error("ai_assistant_error", error=str(e), query=text)
        # Fallback to direct DB search if OpenAI fails
        fallback_orders = await search_orders(text, limit=3)
        if fallback_orders:
            card = _format_order_card(fallback_orders[0], base_url)
            img = f"{base_url}/{fallback_orders[0].shoe_image_path.lstrip('/')}" if fallback_orders[0].shoe_image_path else None
            return {
                "reply_text": f"Found order:\n\n{card}",
                "image_url": img,
                "image_caption": f"Shoe for {fallback_orders[0].customer_name}",
            }
        return {
            "reply_text": "Maazrat, database search mein masla aya. Barah-e-karam dobara koshish karein.",
            "image_url": None,
            "image_caption": None,
        }
