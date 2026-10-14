"""
WhatsApp Business Cloud API connector ?" outbound messaging and media downloads.
Ported and enhanced from RentDesk WhatsApp client.
"""
from __future__ import annotations

import httpx
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_BASE = "https://graph.facebook.com/v19.0"


def _handle_error(tool_name: str, e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code in (401, 403):
            return (
                f"Authorization error in {tool_name}: the WhatsApp Business account "
                f"lacks permission (HTTP {e.response.status_code}). "
                "Check WHATSAPP_ACCESS_TOKEN in .env."
            )
        return f"API error in {tool_name} (HTTP {e.response.status_code}): {e.response.text[:300]}"
    return f"Unexpected error in {tool_name}: {e}"


class WhatsAppClient:
    """Outbound WhatsApp Business API client."""

    def __init__(self) -> None:
        self._phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID

    @property
    def _token(self) -> str:
        return settings.WHATSAPP_ACCESS_TOKEN

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    # "?"? Send Text "?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?

    def send_text(self, to: str, text: str) -> dict[str, Any]:
        """Send a plain text message to a phone number or group."""
        try:
            body = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": True, "body": text},
            }
            resp = httpx.post(
                f"{_BASE}/{self._phone_number_id}/messages",
                headers=self._auth_headers,
                json=body,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            msg_id = data.get("messages", [{}])[0].get("id", "")
            return {"status": "sent", "message_id": msg_id}
        except Exception as e:
            err = _handle_error("send_text", e)
            logger.error("whatsapp_send_text_error", to=to, error=err)
            return {"status": "error", "error": err}

    # "?"? Send Image "?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?

    def send_image(self, to: str, image_url: str, caption: str = "") -> dict[str, Any]:
        """Send an image via public URL with optional caption."""
        try:
            body = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "image",
                "image": {"link": image_url, "caption": caption},
            }
            resp = httpx.post(
                f"{_BASE}/{self._phone_number_id}/messages",
                headers=self._auth_headers,
                json=body,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            msg_id = data.get("messages", [{}])[0].get("id", "")
            return {"status": "sent", "message_id": msg_id}
        except Exception as e:
            err = _handle_error("send_image", e)
            logger.error("whatsapp_send_image_error", to=to, image_url=image_url, error=err)
            return {"status": "error", "error": err}

    def upload_media(self, file_path: str, mime_type: str = "image/jpeg") -> str | None:
        """
        Directly upload media binary to Meta Graph API.
        Returns media_id on success, or None on error.
        Guarantees instant delivery without needing any public URL!
        """
        try:
            from pathlib import Path
            p = Path(file_path)
            if not p.exists():
                logger.error("media_file_not_found", path=file_path)
                return None

            headers = {"Authorization": f"Bearer {self._token}"}
            with open(p, "rb") as f:
                files = {"file": (p.name, f, mime_type)}
                data = {"messaging_product": "whatsapp", "type": mime_type}
                resp = httpx.post(
                    f"{_BASE}/{self._phone_number_id}/media",
                    headers=headers,
                    data=data,
                    files=files,
                    timeout=30,
                )
                resp.raise_for_status()
                media_id = resp.json().get("id")
                logger.info("media_uploaded_to_meta", media_id=media_id, file=p.name)
                return media_id
        except Exception as e:
            logger.error("media_upload_error", error=str(e), path=file_path)
            return None

    def send_image_file(self, to: str, file_path: str, caption: str = "") -> dict[str, Any]:
        """Upload local image file directly to Meta and send via media ID."""
        media_id = self.upload_media(file_path)
        if not media_id:
            return {"status": "error", "error": "Media upload failed"}
        try:
            body = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "image",
                "image": {"id": media_id, "caption": caption},
            }
            resp = httpx.post(
                f"{_BASE}/{self._phone_number_id}/messages",
                headers=self._auth_headers,
                json=body,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            msg_id = data.get("messages", [{}])[0].get("id", "")
            return {"status": "sent", "message_id": msg_id, "media_id": media_id}
        except Exception as e:
            err = _handle_error("send_image_file", e)
            logger.error("whatsapp_send_image_file_error", to=to, error=err)
            return {"status": "error", "error": err}

    # "?"? Send Document (Invoice PDF) "?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?

    def send_document(self, to: str, document_url: str, filename: str = "Invoice.pdf", caption: str = "") -> dict[str, Any]:
        """Send a document (e.g. PDF invoice) via public URL."""
        try:
            body = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "document",
                "document": {"link": document_url, "caption": caption, "filename": filename},
            }
            resp = httpx.post(
                f"{_BASE}/{self._phone_number_id}/messages",
                headers=self._auth_headers,
                json=body,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            msg_id = data.get("messages", [{}])[0].get("id", "")
            return {"status": "sent", "message_id": msg_id}
        except Exception as e:
            err = _handle_error("send_document", e)
            logger.error("whatsapp_send_document_error", to=to, document_url=document_url, error=err)
            return {"status": "error", "error": err}

    # "?"? Send Message Template (Bypasses 24h Window) "?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"

    def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str = "en_US",
        components: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Send a pre-approved Meta Message Template.
        Essential for server-initiated alerts when the 24-hour service window is closed.
        """
        try:
            body = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": language_code},
                    "components": components or [],
                },
            }
            resp = httpx.post(
                f"{_BASE}/{self._phone_number_id}/messages",
                headers=self._auth_headers,
                json=body,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            msg_id = data.get("messages", [{}])[0].get("id", "")
            return {"status": "sent", "message_id": msg_id}
        except Exception as e:
            err = _handle_error("send_template", e)
            logger.error("whatsapp_send_template_error", to=to, template=template_name, error=err)
            return {"status": "error", "error": err}

    def send_order_alert_template(
        self,
        to: str,
        order_code: str,
        customer_name: str,
        phone: str,
        city: str,
        shoe_item: str,
        amount: str,
        image_url: str | None = None,
        invoice_code: str | None = None,
        template_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Send the structured new-order alert template to the owner.
        Template format:
          Header: Image (Shoe photo)
          Body variables: {{1}}=OrderCode, {{2}}=Customer, {{3}}=Phone, {{4}}=City, {{5}}=Item, {{6}}=Amount
          Button 0: Dynamic URL suffix for invoice
        """
        t_name = template_name or settings.WHATSAPP_ORDER_TEMPLATE
        components: list[dict[str, Any]] = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": str(order_code)},
                    {"type": "text", "text": str(customer_name)},
                    {"type": "text", "text": str(phone)},
                    {"type": "text", "text": str(city)},
                    {"type": "text", "text": str(shoe_item)},
                    {"type": "text", "text": str(amount)},
                ],
            }
        ]

        return self.send_template(to=to, template_name=t_name, components=components)

    # "?"? React "?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?

    def react(self, to: str, message_id: str, emoji: str) -> dict[str, Any]:
        """Add an emoji reaction to a message."""
        try:
            body = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "reaction",
                "reaction": {"message_id": message_id, "emoji": emoji},
            }
            resp = httpx.post(
                f"{_BASE}/{self._phone_number_id}/messages",
                headers=self._auth_headers,
                json=body,
                timeout=10,
            )
            resp.raise_for_status()
            return {"status": "reacted", "emoji": emoji}
        except Exception as e:
            err = _handle_error("react", e)
            logger.warning("whatsapp_react_error", error=err)
            return {"status": "error", "error": err}

    # "?"? Media Resolution & Download "?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?"?

    def get_media_url(self, media_id: str) -> str | None:
        """Resolve a WhatsApp media_id to a download URL."""
        try:
            resp = httpx.get(
                f"{_BASE}/{media_id}",
                headers=self._auth_headers,
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("url")
        except Exception as e:
            logger.error("whatsapp_get_media_url_error", media_id=media_id, error=str(e))
            return None

    def download_media(self, url: str) -> bytes | None:
        """Download raw bytes from a WhatsApp media URL."""
        try:
            resp = httpx.get(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=60,
                follow_redirects=True,
            )
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.error("whatsapp_download_media_error", error=str(e))
            return None

    def mark_read(self, message_id: str) -> dict[str, Any]:
        """Mark an incoming message as read."""
        try:
            body = {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
            }
            resp = httpx.post(
                f"{_BASE}/{self._phone_number_id}/messages",
                headers=self._auth_headers,
                json=body,
                timeout=10,
            )
            resp.raise_for_status()
            return {"status": "marked_read"}
        except Exception as e:
            logger.warning("whatsapp_mark_read_error", message_id=message_id, error=str(e))
            return {"status": "error", "error": str(e)}


_client: WhatsAppClient | None = None


def get_whatsapp_client() -> WhatsAppClient:
    global _client
    if _client is None:
        _client = WhatsAppClient()
    return _client
