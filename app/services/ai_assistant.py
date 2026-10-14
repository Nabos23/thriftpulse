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
The owner messages you via WhatsApp (in English, Urdu, or Roman Urdu like "Ali k joote ki details do", "Ali ka phone number chahiye", "0300... kiska order hai").
The owner needs quick, accurate answers about customer orders, phone numbers, delivery addresses, and shoe photos (e.g. while driving, dealing with couriers/riders, or packing parcels).

You have access to tools to search orders in the database.
Always call the tools to look up the latest real data.

Rules:
1. Always be polite, concise, and professional.
2. If the user asks in Roman Urdu or Urdu, respond naturally in helpful, clear Roman Urdu or Urdu matching their style.
3. If search yields MULTIPLE matches, list them clearly with numbering (1, 2, 3...) showing Name, City, Shoe, and Date, and ask the owner which one they want to view.
4. If search yields a SINGLE match, summarize the customer name, phone number(s), complete address, shoe brand/size, and COD price.
5. In your tool calls or response, always reference the order so that the shoe picture can be delivered.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_orders_db",
            "description": "Search for orders by customer name, phone number, city, shoe description, or order code.",
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


async def execute_tool(name: str, args: dict[str, Any]) -> tuple[str, list[Order]]:
    """Execute tool and return JSON result + list of matched orders."""
    if name == "search_orders_db":
        query = args.get("query", "")
        orders = await search_orders(query, limit=5)
        serialized = [o.model_dump() for o in orders]
        return json.dumps(serialized), orders
    elif name == "get_recent_orders_db":
        limit = args.get("limit", 5)
        orders = await get_recent_orders(limit=limit)
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

                tool_output, orders = await execute_tool(fn_name, fn_args)
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
