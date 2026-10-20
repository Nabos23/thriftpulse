"""
Google Sheets sync connector for Thrift Shoes orders.
Uses OAuth2 token with automatic token refresh.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials

from app.core.config import settings
from app.core.logging import get_logger
from app.models.order import Order

logger = get_logger(__name__)

_SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

SHEET_HEADERS = [
    "Order Code",
    "Date & Time",
    "Customer Name",
    "Primary Phone",
    "Alt Phone",
    "City",
    "Full Address",
    "Shoe Article / Brand",
    "Shoe Size",
    "Price (PKR)",
    "Payment Method",
    "Status",
    "Photo URL / Path",
    "Invoice URL / Path",
    "Notes",
]


class GoogleSheetsSync:
    """Manages appending and syncing thrift orders to Google Sheets."""

    def __init__(self) -> None:
        self._creds: Any = None
        self._token_path = settings.GOOGLE_TOKEN_PATH
        self._creds_path = settings.GOOGLE_CREDENTIALS_PATH
        self._spreadsheet_id = settings.SPREADSHEET_ID
        self._sheet_name = settings.ORDERS_SHEET_NAME

    def _get_creds(self) -> Any:
        """Load Service Account credentials (file or env) or OAuth2 user token."""
        if self._creds and getattr(self._creds, "valid", False) and getattr(self._creds, "token", None):
            return self._creds

        # 1. Service Account JSON string from environment variable (ideal for Vercel)
        sa_json_str = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if sa_json_str:
            try:
                # Handle possible wrapping quotes
                if (sa_json_str.startswith("'") and sa_json_str.endswith("'")) or (sa_json_str.startswith('"') and sa_json_str.endswith('"')):
                    sa_json_str = sa_json_str[1:-1].strip()

                # Support base64 encoded JSON if provided
                if not sa_json_str.startswith("{"):
                    import base64
                    try:
                        sa_json_str = base64.b64decode(sa_json_str).decode("utf-8")
                    except Exception:
                        pass

                info = json.loads(sa_json_str)
                # Crucial fix for Vercel: unescape literal \n into real newlines in private_key
                if "private_key" in info and isinstance(info["private_key"], str):
                    info["private_key"] = info["private_key"].replace("\\n", "\n")

                creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
                creds.refresh(Request())
                self._creds = creds
                logger.info("google_sheets_service_account_env_loaded")

                # Cache to /tmp/service_account.json on serverless if possible
                try:
                    tmp_sa = Path("/tmp/service_account.json")
                    if not tmp_sa.exists():
                        tmp_sa.write_text(json.dumps(info), encoding="utf-8")
                except Exception:
                    pass

                return creds
            except Exception as e:
                logger.error("service_account_json_env_error", error=str(e))

        # 2. Local service_account.json file
        sa_path = Path(getattr(settings, "GOOGLE_SERVICE_ACCOUNT_PATH", "service_account.json"))
        if sa_path.exists():
            try:
                creds = service_account.Credentials.from_service_account_file(str(sa_path), scopes=_SCOPES)
                creds.refresh(Request())
                self._creds = creds
                return creds
            except Exception as e:
                logger.error("service_account_file_error", error=str(e))

        # 3. Fallback to user OAuth token file
        creds_oauth: Credentials | None = None
        if Path(self._token_path).exists():
            try:
                creds_oauth = Credentials.from_authorized_user_file(self._token_path, _SCOPES)
            except Exception:
                creds_oauth = None

        if creds_oauth and creds_oauth.expired and creds_oauth.refresh_token:
            try:
                creds_oauth.refresh(Request())
                with open(self._token_path, "w", encoding="utf-8") as f:
                    f.write(creds_oauth.to_json())
                logger.info("google_token_refreshed")
            except Exception as e:
                logger.warning("google_token_refresh_failed", error=str(e))
                creds_oauth = None

        if creds_oauth and creds_oauth.valid:
            self._creds = creds_oauth
            return creds_oauth

        raise RuntimeError(
            "No valid Google credentials found. Please provide GOOGLE_SERVICE_ACCOUNT_JSON or place service_account.json."
        )

    def _auth_headers(self) -> dict[str, str]:
        creds = self._get_creds()
        if not getattr(creds, "token", None) or not getattr(creds, "valid", False):
            creds.refresh(Request())
        return {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def ensure_headers(self) -> None:
        """Ensure sheet tab and header row exist in the spreadsheet."""
        if not self._spreadsheet_id:
            logger.warning("google_sheets_no_spreadsheet_id")
            return

        try:
            headers = self._auth_headers()
            # 1. Check if sheet tab exists
            meta_resp = httpx.get(
                f"{_SHEETS_BASE}/{self._spreadsheet_id}",
                headers=headers,
                timeout=15,
            )
            meta_resp.raise_for_status()
            existing_sheets = [s["properties"]["title"] for s in meta_resp.json().get("sheets", [])]

            if self._sheet_name not in existing_sheets:
                logger.info("creating_sheet_tab", sheet=self._sheet_name)
                add_resp = httpx.post(
                    f"{_SHEETS_BASE}/{self._spreadsheet_id}:batchUpdate",
                    headers=headers,
                    json={
                        "requests": [
                            {"addSheet": {"properties": {"title": self._sheet_name}}}
                        ]
                    },
                    timeout=15,
                )
                add_resp.raise_for_status()
                logger.info("sheet_tab_created", sheet=self._sheet_name)

            # 2. Check if headers exist
            resp = httpx.get(
                f"{_SHEETS_BASE}/{self._spreadsheet_id}/values/{self._sheet_name}!A1:O1",
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 200:
                values = resp.json().get("values", [])
                if values:
                    logger.info("sheets_headers_exist", sheet=self._sheet_name)
                    return

            # Append or initialize headers
            body = {"values": [SHEET_HEADERS]}
            write_resp = httpx.put(
                f"{_SHEETS_BASE}/{self._spreadsheet_id}/values/{self._sheet_name}!A1:O1?valueInputOption=USER_ENTERED",
                headers=headers,
                json=body,
                timeout=15,
            )
            write_resp.raise_for_status()
            logger.info("sheets_headers_written", sheet=self._sheet_name)
        except Exception as e:
            logger.warning("sheets_ensure_headers_warning", error=str(e))

    def append_order(self, order: Order, base_url: str = "") -> dict[str, Any]:
        """Append a new order row to the Google Sheet with full clickable URLs."""
        if not self._spreadsheet_id:
            logger.warning("sheets_skip_no_spreadsheet_id")
            return {"status": "skipped", "reason": "no_spreadsheet_id"}

        try:
            headers = self._auth_headers()

            # Determine public base URL for clickable links
            b = (base_url or settings.BASE_URL).rstrip("/")
            if ("localhost" in b or "127.0.0.1" in b) and settings.BASE_URL and "localhost" not in settings.BASE_URL:
                b = settings.BASE_URL.rstrip("/")

            # Clickable Photo URL(s)
            if order.shoe_image_path:
                raw_items = [p.strip() for p in order.shoe_image_path.split(",") if p.strip()]
                formatted_urls = []
                for p in raw_items:
                    if p.startswith("http://") or p.startswith("https://"):
                        formatted_urls.append(p)
                    else:
                        formatted_urls.append(f"{b}/{p.lstrip('/')}")
                photo_url = ", ".join(formatted_urls)
            else:
                photo_url = ""

            # Clickable Invoice URL
            invoice_url = f"{b}/invoice/{order.order_code}"

            row = [
                order.order_code,
                order.created_at,
                order.customer_name,
                order.phone_primary,
                order.phone_secondary or "",
                order.city,
                order.full_address,
                order.shoe_brand_model,
                order.shoe_size,
                order.price,
                order.payment_method,
                order.status,
                photo_url,
                invoice_url,
                order.notes or "",
            ]

            body = {"values": [row]}
            resp = httpx.post(
                f"{_SHEETS_BASE}/{self._spreadsheet_id}/values/{self._sheet_name}!A1:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS",
                headers=headers,
                json=body,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            updated_range = data.get("updates", {}).get("updatedRange", "")
            logger.info("sheets_order_appended", order_code=order.order_code, range=updated_range)
            return {"status": "ok", "range": updated_range}
        except Exception as e:
            logger.error("sheets_append_error", order_code=order.order_code, error=str(e))
            return {"status": "error", "error": str(e)}

    def get_all_rows(self) -> list[dict[str, Any]]:
        """Fetch all order rows from the Google Sheet as dictionaries."""
        if not self._spreadsheet_id:
            logger.warning("sheets_skip_no_spreadsheet_id")
            return []

        try:
            headers = self._auth_headers()
            resp = httpx.get(
                f"{_SHEETS_BASE}/{self._spreadsheet_id}/values/{self._sheet_name}!A2:O",
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("values", [])
            results = []
            for row_idx, r in enumerate(data, start=2):
                if not r or not any(str(x).strip() for x in r):
                    continue
                padded = list(r) + [""] * (len(SHEET_HEADERS) - len(r))
                item = {
                    "row_number": row_idx,
                    "order_code": str(padded[0]).strip(),
                    "created_at": str(padded[1]).strip(),
                    "customer_name": str(padded[2]).strip(),
                    "phone_primary": str(padded[3]).strip(),
                    "phone_secondary": str(padded[4]).strip(),
                    "city": str(padded[5]).strip(),
                    "full_address": str(padded[6]).strip(),
                    "shoe_brand_model": str(padded[7]).strip(),
                    "shoe_size": str(padded[8]).strip(),
                    "price": str(padded[9]).strip(),
                    "payment_method": str(padded[10]).strip(),
                    "status": str(padded[11]).strip(),
                    "shoe_image_path": str(padded[12]).strip(),
                    "invoice_path": str(padded[13]).strip(),
                    "notes": str(padded[14]).strip(),
                }
                results.append(item)
            return results
        except Exception as e:
            logger.error("sheets_read_error", error=str(e))
            return []

    def search_sheet(self, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        """Search across all order rows in Google Sheets."""
        rows = self.get_all_rows()
        if not rows:
            return []
        if not query or not query.strip():
            # Return recent rows (newest first)
            return rows[-limit:][::-1]

        q = query.strip().lower()
        matched = []
        for r in reversed(rows):
            searchable = " ".join([
                r.get("order_code", ""),
                r.get("customer_name", ""),
                r.get("phone_primary", ""),
                r.get("phone_secondary", ""),
                r.get("city", ""),
                r.get("full_address", ""),
                r.get("shoe_brand_model", ""),
                r.get("status", ""),
                r.get("notes", ""),
            ]).lower()
            if q in searchable:
                matched.append(r)
                if len(matched) >= limit:
                    break
        return matched

    def get_next_order_code(self) -> str:
        """Find the highest order code across Google Sheets and local SQLite DB."""
        highest_num = 1000
        import re

        # 1. Check Google Sheets
        try:
            rows = self.get_all_rows()
            for r in rows:
                code = r.get("order_code", "").strip()
                m = re.search(r"TS-(\d+)", code, re.IGNORECASE)
                if m:
                    try:
                        num = int(m.group(1))
                        if num > highest_num:
                            highest_num = num
                    except ValueError:
                        pass
        except Exception:
            pass

        # 2. Check local SQLite DB
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT order_code FROM orders")
            for db_row in cursor.fetchall():
                code = str(db_row[0] or "").strip()
                m = re.search(r"TS-(\d+)", code, re.IGNORECASE)
                if m:
                    try:
                        num = int(m.group(1))
                        if num > highest_num:
                            highest_num = num
                    except ValueError:
                        pass
            conn.close()
        except Exception:
            pass

        return f"TS-{highest_num + 1}"

    def update_order_status(self, order_code: str, new_status: str) -> dict[str, Any]:
        """Update the Status column (L) of a given order in Google Sheets."""
        if not self._spreadsheet_id:
            return {"status": "skipped", "reason": "no_spreadsheet_id"}
        try:
            rows = self.get_all_rows()
            target_row = None
            clean_code = order_code.strip().upper()
            for r in rows:
                if r.get("order_code", "").strip().upper() == clean_code:
                    target_row = r["row_number"]
                    break

            if not target_row:
                return {"status": "not_found", "message": f"Order {order_code} not found in sheet"}

            headers = self._auth_headers()
            cell_range = f"{self._sheet_name}!L{target_row}"
            body = {"values": [[new_status]]}
            resp = httpx.put(
                f"{_SHEETS_BASE}/{self._spreadsheet_id}/values/{cell_range}?valueInputOption=USER_ENTERED",
                headers=headers,
                json=body,
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("sheets_status_updated", order_code=order_code, row=target_row, status=new_status)
            return {"status": "ok", "order_code": order_code, "new_status": new_status, "row": target_row}
        except Exception as e:
            logger.error("sheets_update_status_error", error=str(e), order_code=order_code)
            return {"status": "error", "error": str(e)}

    def update_order_note(self, order_code: str, note: str) -> dict[str, Any]:
        """Update or append to the Notes column (O) of a given order in Google Sheets."""
        if not self._spreadsheet_id:
            return {"status": "skipped", "reason": "no_spreadsheet_id"}
        try:
            rows = self.get_all_rows()
            target_row = None
            clean_code = order_code.strip().upper()
            existing_note = ""
            for r in rows:
                if r.get("order_code", "").strip().upper() == clean_code:
                    target_row = r["row_number"]
                    existing_note = r.get("notes", "")
                    break

            if not target_row:
                return {"status": "not_found", "message": f"Order {order_code} not found in sheet"}

            new_notes = f"{existing_note}; {note}".strip("; ") if existing_note else note
            headers = self._auth_headers()
            cell_range = f"{self._sheet_name}!O{target_row}"
            body = {"values": [[new_notes]]}
            resp = httpx.put(
                f"{_SHEETS_BASE}/{self._spreadsheet_id}/values/{cell_range}?valueInputOption=USER_ENTERED",
                headers=headers,
                json=body,
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("sheets_note_updated", order_code=order_code, row=target_row)
            return {"status": "ok", "order_code": order_code, "notes": new_notes, "row": target_row}
        except Exception as e:
            logger.error("sheets_update_note_error", error=str(e), order_code=order_code)
            return {"status": "error", "error": str(e)}


_sheets_sync: GoogleSheetsSync | None = None


def get_sheets_sync() -> GoogleSheetsSync:
    global _sheets_sync
    if _sheets_sync is None:
        _sheets_sync = GoogleSheetsSync()
    return _sheets_sync
