"""Data models for My AI.

These Pydantic models describe the shape of data that travels between the
frontend (the browser) and the backend (Python). Pydantic checks the data
automatically: if something is the wrong type or the wrong length, FastAPI
rejects it before our own code runs. That is our first layer of input safety.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# A message must be from one of these three "roles". Nothing else is allowed.
Role = Literal["system", "user", "assistant"]

# How long a single chat message may be. This prevents someone from sending
# a gigantic payload that could slow down or overload the app.
MAX_MESSAGE_LENGTH = 8000


def utc_now() -> datetime:
    """Return the current time in UTC (the standard time used by servers)."""
    return datetime.now(timezone.utc)


class ChatMessage(BaseModel):
    """One message in a conversation."""

    role: Role
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    created_at: datetime = Field(default_factory=utc_now)


class ChatRequest(BaseModel):
    """What the frontend sends when the user presses Send."""

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    conversation_id: int | None = None
    model: str | None = None
    # The last few messages, oldest first. Phase 8 will replace this with
    # a database lookup, but keeping it here lets conversation memory work now.
    history: list[ChatMessage] = Field(default_factory=list, max_length=50)

    @field_validator("message")
    @classmethod
    def clean_and_check_message(cls, value: str) -> str:
        """Remove surrounding whitespace and reject empty messages."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Message cannot be empty.")
        return cleaned


class ChatResponse(BaseModel):
    """What the backend sends back after the AI replies."""

    reply: str
    conversation_id: int
    model: str
    created_at: datetime = Field(default_factory=utc_now)


class ConversationSummary(BaseModel):
    """One row in the sidebar's conversation history list."""

    id: int
    title: str
    created_at: datetime
    updated_at: datetime
