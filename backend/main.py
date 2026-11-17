"""My AI - FastAPI backend.

Conversations and messages are stored in SQLite, so chat history survives
refreshes and the sidebar can show real conversations.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import database as db
from .ai_service import (
    AIServiceError,
    ConfigurationError,
    ask_ai,
    config_summary,
    resolve_model,
    stream_ai,
)
from .models import ChatMessage, ChatRequest, ChatResponse, ConversationSummary  # noqa: F401

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)

FRONTEND_DIR = PROJECT_ROOT / "frontend"
db.init_db()


def allowed_origins() -> list[str]:
    """Build the list of browser addresses allowed to call this API."""
    configured = os.getenv("ALLOWED_ORIGINS", "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]

    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]


def title_from_message(message: str) -> str:
    """Make a short sidebar title from the first user message."""
    clean = " ".join(message.split())
    return clean[:60] + ("..." if len(clean) > 60 else "")


def resolve_conversation(request: ChatRequest) -> ConversationSummary:
    """Find the conversation, or create one for the first message."""
    conversation_id = request.conversation_id or None
    if conversation_id is None:
        return db.create_conversation(title_from_message(request.message))

    conversation = db.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


def name_conversation_if_needed(conversation_id: int, message: str) -> None:
    """Give a new conversation its title only after a successful reply."""
    conversation = db.get_conversation(conversation_id)
    if conversation and conversation.title == "New conversation":
        db.rename_conversation(conversation_id, title_from_message(message))


app = FastAPI(
    title="My AI API",
    description="Backend API for the My AI chatbot.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "app": "My AI", "message": "Backend is running."}


@app.get("/api/config")
def get_config() -> dict[str, object]:
    """Safe configuration facts (never includes the API key)."""
    return config_summary()


# -------------------- Conversation management --------------------


@app.get("/api/conversations", response_model=list[ConversationSummary])
def list_conversations() -> list[ConversationSummary]:
    return db.list_conversations()


@app.post("/api/conversations", response_model=ConversationSummary, status_code=201)
def create_conversation(title: str | None = None) -> ConversationSummary:
    return db.create_conversation(title or "New conversation")


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: int) -> dict[str, object]:
    conversation = db.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"conversation": conversation, "messages": db.get_messages(conversation_id)}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: int) -> dict[str, bool]:
    if not db.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"deleted": True}


@app.delete("/api/conversations/{conversation_id}/messages")
def clear_conversation_messages(conversation_id: int) -> dict[str, bool]:
    if db.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    db.clear_messages(conversation_id)
    return {"cleared": True}


# -------------------- Chat --------------------


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Non-streaming chat endpoint (reliable fallback)."""
    conversation = resolve_conversation(request)
    try:
        selected_model = resolve_model(request.model)
    except AIServiceError as exc:
        raise HTTPException(status_code=400, detail=exc.user_message) from exc

    db.add_message(conversation.id, "user", request.message)
    history = db.get_messages(conversation.id)

    try:
        reply = ask_ai(history, model=selected_model)
    except ConfigurationError as exc:
        db.delete_last_message(conversation.id)
        raise HTTPException(status_code=503, detail=exc.user_message) from exc
    except AIServiceError as exc:
        db.delete_last_message(conversation.id)
        raise HTTPException(status_code=502, detail=exc.user_message) from exc

    db.add_message(conversation.id, "assistant", reply)
    name_conversation_if_needed(conversation.id, request.message)
    return ChatResponse(reply=reply, conversation_id=conversation.id, model=selected_model)


def sse(event: str, payload: dict[str, object]) -> str:
    """Format one Server-Sent Event message."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Streaming chat endpoint backed by SQLite memory."""
    conversation = resolve_conversation(request)
    db.add_message(conversation.id, "user", request.message)
    history = db.get_messages(conversation.id)

    try:
        selected_model = resolve_model(request.model)
    except AIServiceError as exc:
        db.delete_last_message(conversation.id)
        raise HTTPException(status_code=400, detail=exc.user_message) from exc

    def generate() -> Iterator[str]:
        collected: list[str] = []
        try:
            for piece in stream_ai(history, model=selected_model):
                collected.append(piece)
                yield sse("delta", {"text": piece})
            reply = "".join(collected).strip()
            if not reply:
                raise AIServiceError("The AI returned an empty reply. Please try again.")
            db.add_message(conversation.id, "assistant", reply)
            name_conversation_if_needed(conversation.id, request.message)
            yield sse(
                "done",
                {"model": selected_model, "conversation_id": conversation.id},
            )
        except AIServiceError as exc:
            db.delete_last_message(conversation.id)
            yield sse("error", {"message": exc.user_message})
        except Exception:  # noqa: BLE001 - never leak technical details
            db.delete_last_message(conversation.id)
            yield sse("error", {"message": "Something unexpected happened. Please try again."})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# IMPORTANT: mount static files LAST so /api/* routes are matched first.
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
