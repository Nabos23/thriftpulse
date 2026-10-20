"""
Application settings loaded from environment / .env file.
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Base Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    UPLOADS_DIR: Path = BASE_DIR / "app" / "static" / "uploads" / "shoes"
    INVOICES_DIR: Path = BASE_DIR / "app" / "static" / "invoices"

    def model_post_init(self, __context) -> None:
        # Detect Vercel serverless environment (filesystem outside /tmp is read-only)
        if os.getenv("VERCEL"):
            tmp = Path("/tmp")
            self.UPLOADS_DIR = tmp / "uploads" / "shoes"
            self.INVOICES_DIR = tmp / "invoices"
            if "thrift_orders.db" in self.DATABASE_URL and not self.DATABASE_URL.startswith("sqlite+aiosqlite:////"):
                self.DATABASE_URL = "sqlite+aiosqlite:////tmp/thrift_orders.db"
                self.SYNC_DATABASE_URL = "sqlite:////tmp/thrift_orders.db"
            if not Path(self.GOOGLE_TOKEN_PATH).is_absolute():
                self.GOOGLE_TOKEN_PATH = "/tmp/google_token.json"

    # WhatsApp Business API
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_WABA_ID: str = ""
    WHATSAPP_VERIFY_TOKEN: str = "thrift_bot_verify"
    WHATSAPP_ORDER_TEMPLATE: str = "thrift_new_order_alert"
    USE_TEMPLATE_FOR_ALERTS: bool = False  # Set to True when template is registered in Meta Business Manager

    # Owner / Admin Contacts (supports single or comma-separated list)
    OWNER_PHONE_NUMBER: str = ""
    OWNER_PHONE_NUMBERS: str = ""

    # LLM Settings (OpenRouter / Groq / OpenAI)
    # Modes: "auto" (prefers OpenRouter if key set, else Groq, else OpenAI), "openrouter", "groq", "openai"
    LLM_PROVIDER: str = "auto"
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    DEFAULT_MODEL: str = "openrouter/free"  # e.g. "openrouter/free" or "meta-llama/llama-3.3-70b-instruct:free"

    # Groq Settings (100% Free LLM + Whisper)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_WHISPER_MODEL: str = "whisper-large-v3-turbo"

    # OpenAI Fallback
    OPENAI_API_KEY: str = ""

    # Whisper Audio Transcription Settings
    # Modes: "auto" (Groq free cloud if key exists -> local faster-whisper -> OpenAI), "groq", "local", "openai"
    WHISPER_PROVIDER: str = "auto"
    LOCAL_WHISPER_MODEL: str = "base"  # "tiny", "base", "small"
    WHISPER_MODEL: str = "whisper-1"  # For OpenAI / OpenRouter

    # Google Sheets (Service Account / OAuth)
    GOOGLE_SERVICE_ACCOUNT_PATH: str = "service_account.json"
    GOOGLE_SERVICE_ACCOUNT_JSON: str = ""  # Raw JSON string for Vercel env variable
    SPREADSHEET_ID: str = ""
    ORDERS_SHEET_NAME: str = "Orders"
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/google/callback"
    GOOGLE_TOKEN_PATH: str = "google_token.json"
    GOOGLE_CREDENTIALS_PATH: str = "google_credentials.json"

    # Database (Turso Cloud LibSQL or local SQLite fallback)
    DATABASE_URL: str = "sqlite+aiosqlite:///thrift_orders.db"
    SYNC_DATABASE_URL: str = "sqlite:///thrift_orders.db"
    TURSO_DATABASE_URL: str = ""
    TURSO_AUTH_TOKEN: str = ""

    # Cloudinary Image CDN (for permanent image persistence across serverless container restarts)
    CLOUDINARY_URL: str = ""
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    # App & Network
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    BASE_URL: str = "https://crave-pendant-moonscape.ngrok-free.dev"

    # Store Branding
    STORE_NAME: str = "Thrifteddripss"
    STORE_TAGLINE: str = "Premium Pre-Loved Sneakers & Footwear"
    STORE_CONTACT: str = "+92 312 9214688"

    @property
    def is_dev(self) -> bool:
        return self.ENVIRONMENT.lower() == "development"

    @property
    def whatsapp_token_header(self) -> dict:
        return {
            "Authorization": f"Bearer {self.WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def normalize_phone(phone: str) -> str:
        """Standardize phone to international digits-only (e.g. 923129214688)."""
        import re
        digits = re.sub(r"\D", "", phone or "")
        if not digits:
            return ""
        if digits.startswith("03") and len(digits) == 11:
            digits = "92" + digits[1:]
        elif digits.startswith("00"):
            digits = digits[2:]
        return digits

    @property
    def owner_phones(self) -> list[str]:
        """
        Return a clean, deduplicated list of normalized owner phone numbers
        from OWNER_PHONE_NUMBERS and/or OWNER_PHONE_NUMBER.
        """
        raw_items: list[str] = []
        if self.OWNER_PHONE_NUMBERS:
            raw_items.extend(self.OWNER_PHONE_NUMBERS.split(","))
        if self.OWNER_PHONE_NUMBER:
            raw_items.extend(self.OWNER_PHONE_NUMBER.split(","))

        phones: list[str] = []
        for item in raw_items:
            norm = self.normalize_phone(item.strip())
            if norm and norm not in phones:
                phones.append(norm)
        return phones


settings = Settings()
