"""
Multi-Engine Voice Note Transcription.
Supports:
1. Groq Cloud Whisper (100% Free, ultra-fast ~300ms, large-v3-turbo)
2. Local faster-whisper (100% Free, offline, zero API keys, CPU/GPU)
3. OpenAI Whisper (fallback)
"""
from __future__ import annotations

import asyncio
import io
import os
import tempfile
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_openai_client: AsyncOpenAI | None = None
_groq_client: AsyncOpenAI | None = None
_local_model = None


def _get_groq_client() -> AsyncOpenAI:
    global _groq_client
    if _groq_client is None:
        _groq_client = AsyncOpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )
    return _groq_client


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_client


def _get_local_model():
    global _local_model
    if _local_model is None:
        from faster_whisper import WhisperModel
        model_size = getattr(settings, "LOCAL_WHISPER_MODEL", "base")
        logger.info("loading_local_whisper_model", model_size=model_size)
        _local_model = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _local_model


async def _transcribe_groq(audio_bytes: bytes, ext: str) -> str:
    """Transcribe using Groq Free Whisper API."""
    if not settings.GROQ_API_KEY:
        return ""
    client = _get_groq_client()
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = f"voice_note.{ext}"
    model_name = getattr(settings, "GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
    response = await client.audio.transcriptions.create(
        model=model_name,
        file=audio_file,
        response_format="text",
    )
    return response.strip() if isinstance(response, str) else (getattr(response, "text", "") or "").strip()


def _run_local_transcription(audio_bytes: bytes, ext: str) -> str:
    """CPU-bound local faster-whisper execution in a worker thread."""
    model = _get_local_model()
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        segments, _ = model.transcribe(
            tmp_path,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        text_parts = [segment.text for segment in segments]
        return " ".join(text_parts).strip()
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


async def _transcribe_local(audio_bytes: bytes, ext: str) -> str:
    """Transcribe using local faster-whisper without blocking async event loop."""
    try:
        return await asyncio.to_thread(_run_local_transcription, audio_bytes, ext)
    except Exception as e:
        logger.error("local_whisper_error", error=str(e))
        return ""


async def _transcribe_openai(audio_bytes: bytes, ext: str) -> str:
    """Transcribe using OpenAI Whisper."""
    if not settings.OPENAI_API_KEY:
        return ""
    client = _get_openai_client()
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = f"voice_note.{ext}"
    response = await client.audio.transcriptions.create(
        model=settings.WHISPER_MODEL,
        file=audio_file,
        response_format="text",
    )
    return response.strip() if isinstance(response, str) else (getattr(response, "text", "") or "").strip()


async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    """
    Transcribe raw audio bytes using the configured Whisper strategy.
    Handles Urdu, Roman Urdu, Hindi, and English seamlessly.
    Auto-detect order: Groq Free Cloud -> Local faster-whisper -> OpenAI.
    """
    if not audio_bytes:
        logger.warning("transcribe_audio_empty_bytes")
        return ""

    ext = _mime_to_ext(mime_type)
    provider = settings.WHISPER_PROVIDER.lower()
    text = ""

    # Strategy 1: Explicit Groq or Auto with Groq Key
    if provider == "groq" or (provider == "auto" and settings.GROQ_API_KEY):
        try:
            logger.info("transcribing_audio_with_groq", ext=ext)
            text = await _transcribe_groq(audio_bytes, ext)
            if text:
                logger.info("groq_transcription_success", length=len(text), preview=text[:60])
                return text
        except Exception as e:
            logger.warning("groq_whisper_failed_fallback_local", error=str(e))

    # Strategy 2: Local faster-whisper (Offline / 100% Free)
    if provider in ("local", "auto") and not text:
        try:
            logger.info("transcribing_audio_with_local_whisper", ext=ext)
            text = await _transcribe_local(audio_bytes, ext)
            if text:
                logger.info("local_transcription_success", length=len(text), preview=text[:60])
                return text
        except Exception as e:
            logger.warning("local_whisper_failed", error=str(e))

    # Strategy 3: OpenAI Whisper fallback
    if (provider in ("openai", "auto") or not text) and settings.OPENAI_API_KEY:
        try:
            logger.info("transcribing_audio_with_openai", ext=ext)
            text = await _transcribe_openai(audio_bytes, ext)
            if text:
                logger.info("openai_transcription_success", length=len(text), preview=text[:60])
                return text
        except Exception as e:
            logger.error("openai_whisper_failed", error=str(e))

    if not text:
        logger.warning("transcription_failed_no_provider_succeeded", provider=provider)
    return text


def _mime_to_ext(mime_type: str) -> str:
    """Map MIME type to a file extension Whisper understands."""
    mime_lower = mime_type.lower()
    mapping = {
        "audio/ogg": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp4": "mp4",
        "audio/wav": "wav",
        "audio/webm": "webm",
        "audio/x-m4a": "m4a",
        "audio/aac": "m4a",
    }
    for key, ext in mapping.items():
        if key in mime_lower:
            return ext
    return "ogg"
