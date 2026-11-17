"""SQLite storage for My AI conversations and messages.

SQLite is a small database that lives in a single file on your Mac. No server
or extra software is needed. The file is ignored by Git (see .gitignore).
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import ChatMessage, ConversationSummary

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DATABASE_PATH", PROJECT_ROOT / "chat.db"))

MAX_HISTORY_MESSAGES = 40


def utc_now_text() -> str:
    """Current UTC time as text that Pydantic can read back."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@contextmanager
def db_connection() -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, and always close it."""
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """Create the tables if they do not exist yet."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL
                    REFERENCES conversations(id) ON DELETE CASCADE,
                role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content         TEXT NOT NULL,
                created_at      TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages (conversation_id, id)
            """
        )


def _row_to_summary(row: sqlite3.Row) -> ConversationSummary:
    return ConversationSummary(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def create_conversation(title: str = "New conversation") -> ConversationSummary:
    now = utc_now_text()
    clean_title = title.strip()[:80] or "New conversation"
    with db_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)",
            (clean_title, now, now),
        )
        conversation_id = cursor.lastrowid
    return get_conversation(conversation_id)  # type: ignore[return-value]


def get_conversation(conversation_id: int) -> ConversationSummary | None:
    with db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    return _row_to_summary(row) if row else None


def list_conversations(limit: int = 50) -> list[ConversationSummary]:
    with db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_summary(row) for row in rows]


def get_messages(
    conversation_id: int, limit: int = MAX_HISTORY_MESSAGES
) -> list[ChatMessage]:
    """Return the most recent messages, oldest first, for the AI prompt."""
    with db_connection() as connection:
        rows = connection.execute(
            """
            SELECT role, content, created_at FROM (
                SELECT id, role, content, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
            """,
            (conversation_id, limit),
        ).fetchall()
    return [
        ChatMessage(role=row["role"], content=row["content"], created_at=row["created_at"])
        for row in rows
    ]


def add_message(conversation_id: int, role: str, content: str) -> ChatMessage:
    now = utc_now_text()
    with db_connection() as connection:
        connection.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, now),
        )
        connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
        )
    return ChatMessage(role=role, content=content, created_at=now)  # type: ignore[arg-type]


def touch_conversation(conversation_id: int) -> None:
    with db_connection() as connection:
        connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (utc_now_text(), conversation_id),
        )


def rename_conversation(conversation_id: int, title: str) -> None:
    with db_connection() as connection:
        connection.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title.strip()[:80] or "New conversation", conversation_id),
        )


def delete_conversation(conversation_id: int) -> bool:
    with db_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )
    return cursor.rowcount > 0


def clear_messages(conversation_id: int) -> None:
    """Delete all messages but keep the conversation itself."""
    with db_connection() as connection:
        connection.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
        )
        connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (utc_now_text(), conversation_id),
        )


def delete_last_message(conversation_id: int) -> None:
    """Used when an AI request fails and its user message should be undone."""
    with db_connection() as connection:
        connection.execute(
            """
            DELETE FROM messages WHERE id = (
                SELECT id FROM messages WHERE conversation_id = ?
                ORDER BY id DESC LIMIT 1
            )
            """,
            (conversation_id,),
        )
