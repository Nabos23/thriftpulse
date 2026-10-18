"""
Cloudinary Connector for permanent image hosting and CDN delivery.
Zero heavy SDK required - uses lightweight signed HTTP REST uploads via httpx.
Supports single CLOUDINARY_URL (standard) or individual credentials.
"""
from __future__ import annotations

import hashlib
import os
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class CloudinaryClient:
    """Zero-dependency HTTP client for Cloudinary image uploads."""

    def __init__(self) -> None:
        self.cloud_name: str = ""
        self.api_key: str = ""
        self.api_secret: str = ""
        self._load_credentials()

    def _load_credentials(self) -> None:
        """Parse credentials from CLOUDINARY_URL or discrete settings."""
        raw_url = os.getenv("CLOUDINARY_URL") or getattr(settings, "CLOUDINARY_URL", "")
        if raw_url and raw_url.startswith("cloudinary://"):
            try:
                parsed = urllib.parse.urlparse(raw_url)
                self.api_key = parsed.username or ""
                self.api_secret = parsed.password or ""
                self.cloud_name = parsed.hostname or ""
            except Exception as e:
                logger.warning("cloudinary_url_parse_error", error=str(e))

        # Fallback to discrete keys if not resolved via URL
        if not self.cloud_name:
            self.cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME") or getattr(settings, "CLOUDINARY_CLOUD_NAME", "")
        if not self.api_key:
            self.api_key = os.getenv("CLOUDINARY_API_KEY") or getattr(settings, "CLOUDINARY_API_KEY", "")
        if not self.api_secret:
            self.api_secret = os.getenv("CLOUDINARY_API_SECRET") or getattr(settings, "CLOUDINARY_API_SECRET", "")

    def is_configured(self) -> bool:
        """Returns True if all required Cloudinary credentials are present."""
        self._load_credentials()
        return bool(self.cloud_name and self.api_key and self.api_secret)

    def upload_image_bytes(
        self,
        image_bytes: bytes,
        filename: str = "shoe.jpg",
        folder: str = "shoes",
    ) -> Optional[str]:
        """
        Upload image bytes to Cloudinary using signed authentication.
        Returns the permanent HTTPS secure_url, or None if upload failed.
        """
        if not self.is_configured():
            logger.warning("cloudinary_upload_skipped_not_configured")
            return None

        try:
            timestamp = str(int(time.time()))
            
            # Cloudinary signature requires parameters sorted alphabetically: folder=..., timestamp=...
            to_sign = f"folder={folder}&timestamp={timestamp}{self.api_secret}"
            signature = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()

            upload_url = f"https://api.cloudinary.com/v1_1/{self.cloud_name}/image/upload"
            data = {
                "api_key": self.api_key,
                "timestamp": timestamp,
                "folder": folder,
                "signature": signature,
            }
            files = {"file": (filename, image_bytes)}

            with httpx.Client(timeout=25.0) as client:
                resp = client.post(upload_url, data=data, files=files)
                if resp.status_code == 200:
                    payload = resp.json()
                    secure_url = payload.get("secure_url")
                    logger.info("cloudinary_upload_success", url=secure_url, filename=filename)
                    return secure_url
                else:
                    logger.error(
                        "cloudinary_upload_failed",
                        status_code=resp.status_code,
                        response=resp.text,
                        filename=filename,
                    )
                    return None
        except Exception as e:
            logger.error("cloudinary_upload_exception", error=str(e), filename=filename)
            return None

    def upload_image_file(self, file_path: str | Path, folder: str = "shoes") -> Optional[str]:
        """Upload a local image file by path."""
        p = Path(file_path)
        if not p.exists():
            logger.error("cloudinary_file_not_found", path=str(p))
            return None
        return self.upload_image_bytes(p.read_bytes(), filename=p.name, folder=folder)


_cloudinary_client: Optional[CloudinaryClient] = None


def get_cloudinary_client() -> CloudinaryClient:
    """Singleton getter for CloudinaryClient."""
    global _cloudinary_client
    if _cloudinary_client is None:
        _cloudinary_client = CloudinaryClient()
    return _cloudinary_client
