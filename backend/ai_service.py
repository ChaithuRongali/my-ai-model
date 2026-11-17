"""Secure OpenAI integration for My AI.

Rules followed here:
  * The API key is read from environment variables / the .env file only.
  * No key is ever written into code, logs, or messages shown to the user.
  * Errors are translated into short, safe messages.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Sequence
from pathlib import Path

import openai
from dotenv import load_dotenv

from .models import ChatMessage

logger = logging.getLogger("my_ai.ai_service")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_SYSTEM_PROMPT = (
    "You are My AI, a friendly, helpful and intelligent AI assistant. "
    "Explain concepts clearly, provide accurate information, "
    "and help users solve problems."
)

# Model names coming from a request must look like model names. The slash is
# allowed because providers such as Groq use IDs like "openai/gpt-oss-20b".
SAFE_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]{1,64}$")

_client: openai.OpenAI | None = None


class AIServiceError(Exception):
    """An error whose message is safe to display to the user."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class ConfigurationError(AIServiceError):
    """Raised when the project is not set up correctly."""


def api_key() -> str:
    """Return the API key, or raise a friendly setup error."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or key == "your_api_key_here":
        raise ConfigurationError(
            "OPENAI_API_KEY is not set. Open the .env file in the my-ai folder "
            "and paste your key after the equals sign."
        )
    return key


def is_configured() -> bool:
    """True when a non-placeholder API key is present."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    return bool(key) and key != "your_api_key_here"


def model_name() -> str:
    """The default model from .env, or the built-in default."""
    return os.getenv("OPENAI_MODEL", "").strip() or DEFAULT_MODEL


def system_prompt() -> str:
    """The assistant personality from .env, or the built-in default."""
    return os.getenv("SYSTEM_PROMPT", "").strip() or DEFAULT_SYSTEM_PROMPT


def resolve_model(requested: str | None) -> str:
    """Choose and validate the model name we will send to OpenAI."""
    chosen = (requested or "").strip() or model_name()
    if not SAFE_MODEL_PATTERN.fullmatch(chosen):
        raise AIServiceError("That model name is not valid.")
    return chosen


def base_url() -> str | None:
    """Return the custom OpenAI-compatible endpoint, if configured."""
    return os.getenv("OPENAI_BASE_URL", "").strip() or None


def get_client() -> openai.OpenAI:
    """Create (once) and return the OpenAI-compatible client."""
    global _client
    if _client is None:
        _client = openai.OpenAI(
            api_key=api_key(),
            base_url=base_url(),
            timeout=60.0,
            max_retries=2,
        )
    return _client


def build_messages(history: Sequence[ChatMessage]) -> list[dict[str, str]]:
    """Put the system prompt first, then the conversation messages.

    Any 'system' message supplied by a user is skipped: only the server
    decides My AI's instructions.
    """
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt()}]
    for message in history:
        if message.role == "system":
            continue
        messages.append({"role": message.role, "content": message.content})
    return messages


def translate_error(exc: Exception) -> AIServiceError:
    """Convert a library exception into a short, safe user message."""
    if isinstance(exc, AIServiceError):
        return exc
    if isinstance(exc, openai.AuthenticationError):
        return AIServiceError(
            "OpenAI could not verify the API key. Check OPENAI_API_KEY in .env."
        )
    if isinstance(exc, openai.RateLimitError):
        return AIServiceError(
            "The OpenAI rate limit or quota was reached. Please wait and try again."
        )
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return AIServiceError(
            "Could not reach OpenAI. Check your internet connection and try again."
        )
    if isinstance(exc, openai.BadRequestError):
        logger.warning("OpenAI rejected a request: %s", exc)
        return AIServiceError(
            "OpenAI rejected the request. The model name may be unavailable; "
            "check OPENAI_MODEL in .env."
        )
    if isinstance(exc, openai.OpenAIError):
        logger.exception("OpenAI API error")
        return AIServiceError("The AI service had a problem. Please try again.")
    logger.exception("Unexpected error while calling the AI")
    return AIServiceError("Something unexpected happened. Please try again.")


def ask_ai(history: Sequence[ChatMessage], *, model: str | None = None) -> str:
    """Send the conversation to OpenAI and return the assistant's reply.

    `history` is the list of messages so far, oldest first.
    """
    try:
        selected_model = resolve_model(model)
        response = get_client().chat.completions.create(
            model=selected_model,
            messages=build_messages(history),
            temperature=0.7,
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise AIServiceError("The AI returned an empty reply. Please try again.")
        return content.strip()
    except AIServiceError:
        raise
    except Exception as exc:  # noqa: BLE001 - translated into a safe message
        raise translate_error(exc) from exc


def stream_ai(history: Sequence[ChatMessage], *, model: str | None = None):
    """Yield the assistant's reply in small pieces as OpenAI produces them.

    Because this is a generator, errors are raised while it is being iterated,
    not when it is created. The API route catches those errors below.
    """
    try:
        selected_model = resolve_model(model)
        stream = get_client().chat.completions.create(
            model=selected_model,
            messages=build_messages(history),
            temperature=0.7,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except AIServiceError:
        raise
    except Exception as exc:  # noqa: BLE001 - translated into a safe message
        raise translate_error(exc) from exc


def config_summary() -> dict[str, object]:
    """A safe summary for debugging (never includes the key itself)."""
    return {
        "configured": is_configured(),
        "base_url": base_url() or "https://api.openai.com/v1",
        "model": model_name(),
        "system_prompt_length": len(system_prompt()),
    }
