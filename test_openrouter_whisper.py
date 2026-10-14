"""
Verification test for OpenRouter and Multi-Engine Whisper (Groq / Local).
"""
import asyncio
import sys
from unittest.mock import patch, MagicMock

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.core.config import settings
from app.services.ai_assistant import _get_client
from app.services.voice import transcribe_audio, _mime_to_ext


def test_configuration():
    print("[1/4] Checking OpenRouter, Groq, and Whisper configuration...")
    assert settings.LLM_PROVIDER in ("openrouter", "auto", "groq"), f"Expected openrouter/auto/groq, got {settings.LLM_PROVIDER}"
    assert "openrouter.ai" in settings.OPENROUTER_BASE_URL
    assert settings.WHISPER_PROVIDER == "auto"
    print(f"✓ Configuration valid: Provider={settings.LLM_PROVIDER}, Model={settings.DEFAULT_MODEL}, Whisper={settings.WHISPER_PROVIDER}")


def test_openrouter_client_init():
    print("\n[2/4] Testing OpenRouter AsyncOpenAI client initialization...")
    client = _get_client()
    assert client is not None
    assert str(client.base_url).startswith("https://openrouter.ai") or str(client.base_url).startswith("https://api.groq.com")
    print(f"✓ AI Client successfully initialized with base_url: {client.base_url}")


def test_mime_mapping():
    print("\n[3/4] Testing MIME to extension mapping for audio formats...")
    assert _mime_to_ext("audio/ogg; codecs=opus") == "ogg"
    assert _mime_to_ext("audio/mp4") == "mp4"
    assert _mime_to_ext("audio/mpeg") == "mp3"
    assert _mime_to_ext("audio/wav") == "wav"
    print("✓ MIME audio mapping accurate for all WhatsApp voice note types.")


def test_whisper_auto_fallback():
    print("\n[4/4] Testing Whisper multi-engine fallback and empty handling...")
    # Empty bytes test
    empty_result = asyncio.run(transcribe_audio(b""))
    assert empty_result == "", "Expected empty string for empty audio"
    print("✓ Empty audio bytes handled gracefully.")

    # Test auto-detection fallback without crashing
    with patch("app.services.voice._run_local_transcription", return_value="Ali ka number kya hai"):
        res = asyncio.run(transcribe_audio(b"dummy_audio_bytes", "audio/ogg"))
        assert res == "Ali ka number kya hai"
        print("✓ Local faster-whisper fallback invoked and returned transcript successfully.")

    print("\n" + "=" * 60)
    print("🎉 ALL OPENROUTER & WHISPER TESTS PASSED PERFECTLY!")
    print("=" * 60)


if __name__ == "__main__":
    test_configuration()
    test_openrouter_client_init()
    test_mime_mapping()
    test_whisper_auto_fallback()
