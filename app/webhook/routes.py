"""
WhatsApp Webhook Router for Meta Cloud API:
- Handshake verification (GET /webhook)
- Inbound event processing (POST /webhook)
- Voice note audio download + Whisper STT
- Multilingual owner query handling & shoe photo delivery
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.core.database import log_message
from app.core.logging import get_logger
from app.connectors.whatsapp_client import get_whatsapp_client
from app.services.voice import transcribe_audio
from app.services.ai_assistant import process_owner_query

logger = get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


def _is_owner(phone: str) -> bool:
    """Check if the sender phone number belongs to the store owner/admin."""
    clean = phone.replace("+", "").strip()
    owner_clean = settings.OWNER_PHONE_NUMBER.replace("+", "").strip()
    if clean == owner_clean:
        return True
    for o in settings.OWNER_PHONE_NUMBERS:
        if clean == o.replace("+", "").strip():
            return True
    return False


@router.get("")
@router.get("/")
@router.get("/api/index/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification handshake."""
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("webhook_verified_successfully")
        return PlainTextResponse(content=hub_challenge)

    logger.warning(
        "webhook_verification_failed",
        mode=hub_mode,
        token_match=(hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN),
    )
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("")
@router.post("/")
@router.post("/api/index/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receive inbound WhatsApp events from Meta.
    Always returns 200 within 3 seconds, handles in background task.
    """
    try:
        payload = await request.json()
    except Exception as e:
        logger.error("webhook_json_error", error=str(e))
        return {"status": "ok"}

    # Determine base URL for links and media
    host_header = request.headers.get("host") or f"{settings.HOST}:{settings.PORT}"
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    current_base_url = f"{scheme}://{host_header}" if host_header else settings.BASE_URL

    background_tasks.add_task(_process_payload, payload, current_base_url)
    return {"status": "ok"}


async def _process_payload(payload: dict[str, Any], base_url: str) -> None:
    try:
        if payload.get("object") != "whatsapp_business_account":
            return

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                contacts = value.get("contacts", [])

                name_map: dict[str, str] = {}
                for contact in contacts:
                    wa_id = contact.get("wa_id", "")
                    name = contact.get("profile", {}).get("name", "")
                    if wa_id:
                        name_map[wa_id] = name

                for raw_msg in messages:
                    await _handle_incoming_message(raw_msg, name_map, base_url)

    except Exception as e:
        logger.error("webhook_process_payload_error", error=str(e), exc_info=True)


async def _handle_incoming_message(raw_msg: dict, name_map: dict[str, str], base_url: str) -> None:
    msg_id = raw_msg.get("id", "")
    sender_phone = raw_msg.get("from", "")
    msg_type = raw_msg.get("type", "")
    sender_name = name_map.get(sender_phone, "User")
    wa = get_whatsapp_client()

    logger.info("incoming_whatsapp_message", msg_id=msg_id, sender=sender_phone, type=msg_type)

    # Mark as read
    wa.mark_read(msg_id)

    query_text = ""

    # Case 1: Plain Text
    if msg_type == "text":
        query_text = raw_msg.get("text", {}).get("body", "").strip()

    # Case 2: Audio / Voice Note
    elif msg_type == "audio":
        audio_info = raw_msg.get("audio", {})
        media_id = audio_info.get("id")
        mime_type = audio_info.get("mime_type", "audio/ogg")

        if media_id:
            media_url = wa.get_media_url(media_id)
            if media_url:
                audio_bytes = wa.download_media(media_url)
                if audio_bytes:
                    query_text = await transcribe_audio(audio_bytes, mime_type)

    if not query_text:
        if msg_type == "audio" and _is_owner(sender_phone):
            wa.send_text(
                sender_phone,
                "⚠️ Voice note transcribe nahi ho saki. Barah-e-karam apna sawal text message mein likh kar bhejein ya GROQ_API_KEY check karein.",
            )
        return

    # Log incoming message to database
    await log_message(msg_id, sender_phone, msg_type, query_text)

    # Route based on whether sender is Owner or Customer
    if _is_owner(sender_phone):
        logger.info("owner_query_detected", sender=sender_phone, query=query_text)
        wa.react(sender_phone, msg_id, "🔍")

        ai_response = await process_owner_query(query_text, sender_phone, base_url)

        # 1. Send text reply
        reply_text = ai_response.get("reply_text") or "Details fetch ho gaye hain."
        wa.send_text(sender_phone, reply_text)

        # 2. Send shoe photo if available via direct binary upload to Meta
        image_raw = ai_response.get("image_url")  # raw shoe_image_path from DB e.g. /static/uploads/shoes/shoe_abc.jpg
        print(f"[IMAGE_DEBUG] [WEBHOOK] Owner query finished. image_raw='{image_raw}'")
        logger.info("webhook_image_dispatch_start", image_raw=image_raw)
        if image_raw:
            caption = ai_response.get("image_caption") or "Shoe Photo"
            candidates = []
            if image_raw.startswith("/"):
                candidates.append(Path(image_raw))
            filename = Path(image_raw).name
            candidates.append(Path("/tmp") / "uploads" / "shoes" / filename)
            candidates.append(settings.BASE_DIR / "app" / image_raw.lstrip("/"))
            candidates.append(settings.UPLOADS_DIR / filename)

            sent = False
            for disk_path in candidates:
                exists = disk_path.exists()
                print(f"[IMAGE_DEBUG] [WEBHOOK] Candidate '{disk_path}' exists={exists}")
                logger.info("webhook_image_candidate_check", path=str(disk_path), exists=exists)
                if exists:
                    print(f"[IMAGE_DEBUG] [WEBHOOK] Found image on disk at '{disk_path}', sending via Meta upload...")
                    send_res = wa.send_image_file(sender_phone, str(disk_path), caption=caption)
                    print(f"[IMAGE_DEBUG] [WEBHOOK] wa.send_image_file result: {send_res}")
                    logger.info("webhook_send_image_file_result", result=send_res)
                    sent = True
                    break

            if not sent:
                print(f"[IMAGE_DEBUG] [WEBHOOK] WARNING: None of the candidate disk paths existed on disk for '{image_raw}'!")
                logger.warning("webhook_image_not_found_on_disk", image_raw=image_raw, candidates=[str(c) for c in candidates])
                if image_raw.startswith("http://") or image_raw.startswith("https://"):
                    img_url = image_raw
                else:
                    public_base = (settings.BASE_URL if ("localhost" in base_url or "127.0.0.1" in base_url) else base_url).rstrip("/")
                    img_url = f"{public_base}/{image_raw.lstrip('/')}"
                print(f"[IMAGE_DEBUG] [WEBHOOK] Attempting URL dispatch fallback: {img_url}")
                url_send_res = wa.send_image(sender_phone, img_url, caption=caption)
                print(f"[IMAGE_DEBUG] [WEBHOOK] wa.send_image fallback result: {url_send_res}")
        else:
            print("[IMAGE_DEBUG] [WEBHOOK] No image_raw returned by ai_response (image_url was None or empty).")

    else:
        # Non-owner / Customer greeting
        order_url = f"{base_url}/order"
        customer_msg = (
            f"Assalam-o-Alaikum {sender_name}! 👟✨\n"
            f"Welcome to *{settings.STORE_NAME}*.\n\n"
            f"To place an order or confirm your shoes, please submit details here:\n"
            f"🔗 {order_url}\n\n"
            f"Our team will get back to you shortly!"
        )
        wa.send_text(sender_phone, customer_msg)
