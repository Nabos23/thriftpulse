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
The owner messages you via WhatsApp (in English, Urdu, or Roman Urdu).

FORMATTING RULES (CRITICAL):
- NEVER use markdown tables (no | pipes | or |---| separators). WhatsApp does NOT render tables.
- Use plain text with emoji labels and *bold* for field names.
- Use line breaks between fields.
- Do NOT include raw image file paths or invoice paths in the reply text — these are sent separately as links/files.
- Waybill/invoice link MUST be a full URL like https://thriftpulse-kohl.vercel.app/invoice/TS-1001 — never a relative path.
- Keep responses concise and clean.

Tool Priority & Rules:
1. DATABASE FIRST: For any general query, search, customer lookup, or order status check, ALWAYS use the local database first (`search_orders_db` or `get_recent_orders_db`).
2. GOOGLE SHEETS ON REQUEST ONLY: ONLY call `read_google_sheet` if the owner explicitly asks to check or read the "sheet", "Google Sheet", or "spreadsheet" (e.g. "sheet check karo", "sheet mein dekho").
3. ADDING ORDERS: When the owner asks to add or record an order, ALWAYS call `add_order_to_sheet_and_db` with all extracted fields.
4. ORDER CONFIRMATION: When an order is added, confirm with order code, name, phone, city, shoe, price, and the full waybill URL.
5. UPDATING STATUS: When asked to update status (e.g. "Mark TS-1001 as Dispatched"), call `update_order_status_in_sheet`.
6. SINGLE MATCH: When search yields ONE order, reply in this exact WhatsApp format:

📦 *Order #TS-XXXX*
━━━━━━━━━━━━━━━━━━
👤 *Customer:* Name
📞 *Phone:* 0312...
🏙️ *City:* Lahore
📍 *Address:* Full address
👟 *Shoe:* Nike Dunk High (Size: 41)
💵 *Amount:* PKR 4,200 (Cash on Delivery)
📦 *Status:* Pending
📅 *Date:* 2026-10-14 20:26
📄 *Waybill:* https://thriftpulse-kohl.vercel.app/invoice/TS-XXXX
📸 _(Shoe photo sent below)_
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
    # Always use public base_url for invoice, never relative paths
    public_base = base_url.rstrip("/")
    invoice_link = f"{public_base}/invoice/{order.order_code}"
    lines = [
        f"📦 *Order #{order.order_code}*",
        f"━━━━━━━━━━━━━━━━━━",
        f"👤 *Customer:* {order.customer_name}",
        f"📞 *Phone:* {order.phone_primary}",
    ]
    if order.phone_secondary:
        lines.append(f"📱 *Alt Phone:* {order.phone_secondary}")
    lines.extend([
        f"🏙️ *City:* {order.city}",
        f"📍 *Address:* {order.full_address}",
        f"👟 *Shoe:* {order.shoe_brand_model} (Size: {order.shoe_size})",
        f"💵 *Amount:* PKR {order.price:,.0f} ({order.payment_method})",
        f"📦 *Status:* {order.status}",
        f"📅 *Date:* {order.created_at[:16]}",
        f"📄 *Waybill:* {invoice_link}",
    ])
    if order.notes:
        lines.append(f"📝 *Note:* {order.notes}")
    if order.shoe_image_path:
        lines.append("📸 _(Shoe photo sent below)_")
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
        print(f"[IMAGE_DEBUG] search_orders_db query='{query}' -> SQLite found {len(orders)} orders")
        logger.info("search_orders_db_sqlite", query=query, found=len(orders))
        if not orders:
            # Fallback to search directly in Google Sheet
            try:
                from app.connectors.google_sheets import get_sheets_sync
                sheets = get_sheets_sync()
                sheet_rows = sheets.search_sheet(query, limit=5)
                print(f"[IMAGE_DEBUG] search_orders_db fallback to Google Sheet -> found {len(sheet_rows)} rows")
                logger.info("search_orders_db_sheet_fallback", query=query, found=len(sheet_rows))
                if sheet_rows:
                    from app.models.order import Order
                    sheet_orders = []
                    for sr in sheet_rows:
                        try:
                            sheet_orders.append(Order(
                                order_code=sr.get("order_code", ""),
                                customer_name=sr.get("customer_name", ""),
                                phone_primary=sr.get("phone_primary", ""),
                                phone_secondary=sr.get("phone_secondary", ""),
                                address=sr.get("full_address", ""),
                                area=sr.get("city", ""),
                                city=sr.get("city", ""),
                                shoe_brand_model=sr.get("shoe_brand_model", ""),
                                shoe_size=sr.get("shoe_size", ""),
                                price=float(str(sr.get("price", "0")).replace(",", "") or 0),
                                payment_method=sr.get("payment_method", "Cash on Delivery"),
                                status=sr.get("status", "Pending"),
                                shoe_image_path=sr.get("shoe_image_path", ""),
                                invoice_path=sr.get("invoice_path", ""),
                                notes=sr.get("notes", ""),
                            ))
                        except Exception as parse_err:
                            print(f"[IMAGE_DEBUG] Failed to parse sheet row to Order: {parse_err}")
                    print(f"[IMAGE_DEBUG] Converted {len(sheet_orders)} sheet rows to Order objects (images: {[o.shoe_image_path for o in sheet_orders]})")
                    return json.dumps(sheet_rows), sheet_orders
            except Exception as e:
                print(f"[IMAGE_DEBUG] Error querying Google Sheets fallback: {e}")
                logger.error("search_orders_db_sheet_error", error=str(e))
        serialized = [o.model_dump() for o in orders]
        return json.dumps(serialized), orders

    elif name == "get_recent_orders_db":
        limit = args.get("limit", 5)
        orders = await get_recent_orders(limit=limit)
        print(f"[IMAGE_DEBUG] get_recent_orders_db limit={limit} -> SQLite found {len(orders)} orders")
        if not orders:
            try:
                from app.connectors.google_sheets import get_sheets_sync
                sheets = get_sheets_sync()
                sheet_rows = sheets.search_sheet("", limit=limit)
                print(f"[IMAGE_DEBUG] get_recent_orders_db fallback to Google Sheet -> found {len(sheet_rows)} rows")
                if sheet_rows:
                    from app.models.order import Order
                    sheet_orders = []
                    for sr in sheet_rows:
                        try:
                            sheet_orders.append(Order(
                                order_code=sr.get("order_code", ""),
                                customer_name=sr.get("customer_name", ""),
                                phone_primary=sr.get("phone_primary", ""),
                                phone_secondary=sr.get("phone_secondary", ""),
                                address=sr.get("full_address", ""),
                                area=sr.get("city", ""),
                                city=sr.get("city", ""),
                                shoe_brand_model=sr.get("shoe_brand_model", ""),
                                shoe_size=sr.get("shoe_size", ""),
                                price=float(str(sr.get("price", "0")).replace(",", "") or 0),
                                payment_method=sr.get("payment_method", "Cash on Delivery"),
                                status=sr.get("status", "Pending"),
                                shoe_image_path=sr.get("shoe_image_path", ""),
                                invoice_path=sr.get("invoice_path", ""),
                                notes=sr.get("notes", ""),
                            ))
                        except Exception:
                            pass
                    return json.dumps(sheet_rows), sheet_orders
            except Exception as e:
                print(f"[IMAGE_DEBUG] Error in get_recent_orders_db sheet fallback: {e}")
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

                print(f"[IMAGE_DEBUG] Calling tool '{fn_name}' with args: {fn_args}")
                tool_output, orders = await execute_tool(fn_name, fn_args, base_url)
                matched_orders.extend(orders)
                print(f"[IMAGE_DEBUG] Tool '{fn_name}' returned {len(orders)} Order objects")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_output,
                })

            print(f"[IMAGE_DEBUG] Total matched_orders across all tools: {len(matched_orders)}")
            # Check if exactly one order was matched -> prepare image dispatch
            if len(matched_orders) == 1:
                single_order = matched_orders[0]
                print(f"[IMAGE_DEBUG] Single order matched: #{single_order.order_code}, shoe_image_path='{single_order.shoe_image_path}'")
                if single_order.shoe_image_path:
                    image_to_send = single_order.shoe_image_path
                    caption_to_send = f"👟 Shoe photo for {single_order.customer_name} (#{single_order.order_code})"
                    print(f"[IMAGE_DEBUG] Prepared image_to_send='{image_to_send}'")
                else:
                    print(f"[IMAGE_DEBUG] Order has no shoe_image_path!")
            else:
                print(f"[IMAGE_DEBUG] matched_orders count is {len(matched_orders)} (not 1), skipping single-image dispatch")

            # Get final AI answer
            second_resp = await client.chat.completions.create(
                model=active_model,
                messages=messages,
                temperature=0.2,
            )
            final_reply = second_resp.choices[0].message.content or ""

            print(f"[IMAGE_DEBUG] Returning ai_response with image_url='{image_to_send}'")
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
