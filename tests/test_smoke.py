"""Repeatable smoke tests for My AI.

These tests use a FAKE AI client and a TEMPORARY database, so they cost
nothing and never touch your real chat.db.

Run from the project root:
    .venv/bin/python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

# Set these BEFORE importing backend modules.
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "my-ai-smoke.db")
os.environ["OPENAI_API_KEY"] = ""

import httpx2  # noqa: E402
import openai  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import ai_service, database  # noqa: E402
from backend.main import app  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class FakeCompletions:
    """Minimal stand-in for OpenAI's chat completions resource."""

    def create(self, **kwargs):
        if kwargs.get("stream"):
            def chunks():
                for piece in ["Hello", " from", " My AI"]:
                    yield SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content=piece))]
                    )
            return chunks()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Hello from My AI"))]
        )


class FakeClient:
    chat = SimpleNamespace(completions=FakeCompletions())


class MyAITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        ai_service._client = FakeClient()
        for conversation in database.list_conversations():
            database.delete_conversation(conversation.id)

    # -------------------- Startup and UI --------------------

    def test_health_endpoint(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_frontend_files_are_served(self) -> None:
        for path, token in (("/", "message-input"), ("/style.css", "data-theme"), ("/script.js", "fetch(")):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(token, response.text)

    def test_config_endpoint_never_leaks_key(self) -> None:
        response = self.client.get("/api/config")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["configured"])
        self.assertNotIn("sk-", response.text)

    # -------------------- Input validation --------------------

    def test_invalid_input_is_rejected(self) -> None:
        cases = [
            ({"message": "   "}, 422),
            ({"message": "x" * 8001}, 422),
            ({"message": "Hi", "history": [{"role": "hacker", "content": "x"}]}, 422),
            ({"message": "Hi", "model": "bad model!!"}, 400),
        ]
        for payload, expected_status in cases:
            with self.subTest(payload=str(payload)[:40]):
                response = self.client.post("/api/chat", json=payload)
                self.assertEqual(response.status_code, expected_status)

    def test_cors_is_not_wildcard(self) -> None:
        from backend.main import allowed_origins

        self.assertNotIn("*", allowed_origins())

    def test_custom_base_url_and_groq_model(self) -> None:
        old_key = os.environ.get("OPENAI_API_KEY", "")
        old_base = os.environ.get("OPENAI_BASE_URL", "")
        try:
            os.environ["OPENAI_API_KEY"] = "gsk-dummy-not-real"
            os.environ["OPENAI_BASE_URL"] = "https://api.groq.com/openai/v1"
            ai_service._client = None

            self.assertEqual(ai_service.base_url(), "https://api.groq.com/openai/v1")
            self.assertEqual(
                ai_service.resolve_model("openai/gpt-oss-20b"),
                "openai/gpt-oss-20b",
            )
            client = ai_service.get_client()
            self.assertEqual(
                str(client.base_url).rstrip("/"),
                "https://api.groq.com/openai/v1",
            )
        finally:
            os.environ["OPENAI_API_KEY"] = old_key
            if old_base:
                os.environ["OPENAI_BASE_URL"] = old_base
            else:
                os.environ.pop("OPENAI_BASE_URL", None)
            ai_service._client = None

    # -------------------- Error handling --------------------

    def test_missing_key_is_safe(self) -> None:
        ai_service._client = None
        response = self.client.post("/api/chat", json={"message": "Hello"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("OPENAI_API_KEY", response.json()["detail"])

    def test_openai_errors_are_translated(self) -> None:
        request = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
        response_401 = httpx2.Response(401, request=request)
        exceptions = [
            openai.AuthenticationError("SECRET", response=response_401, body=None),
            openai.APIConnectionError(message="SECRET", request=request),
        ]
        for exc in exceptions:
            with self.subTest(error=type(exc).__name__):
                safe = ai_service.translate_error(exc).user_message
                self.assertNotIn("SECRET", safe)
                self.assertTrue(safe)

    # -------------------- Chat and memory --------------------

    def test_chat_saves_history_and_streams(self) -> None:
        created = self.client.post("/api/conversations")
        self.assertEqual(created.status_code, 201)
        conversation_id = created.json()["id"]

        first = self.client.post(
            "/api/chat", json={"conversation_id": conversation_id, "message": "First question"}
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["reply"], "Hello from My AI")

        stream = self.client.post(
            "/api/chat/stream",
            json={"conversation_id": conversation_id, "message": "Second question"},
        )
        self.assertEqual(stream.status_code, 200)
        self.assertIn("event: delta", stream.text)
        self.assertIn("event: done", stream.text)
        self.assertIn(str(conversation_id), stream.text)

        detail = self.client.get(f"/api/conversations/{conversation_id}").json()
        self.assertEqual(
            [message["role"] for message in detail["messages"]],
            ["user", "assistant", "user", "assistant"],
        )

        # History survives a fresh database connection (= app restart).
        stored = database.get_messages(conversation_id)
        self.assertEqual(len(stored), 4)
        self.assertEqual(stored[0].content, "First question")
        self.assertEqual(stored[-1].content, "Hello from My AI")

        listed = self.client.get("/api/conversations").json()
        self.assertEqual(listed[0]["title"], "First question")

    # -------------------- Conversation management --------------------

    def test_conversation_management(self) -> None:
        conversation_id = self.client.post("/api/conversations").json()["id"]
        self.assertEqual(
            self.client.get(f"/api/conversations/{conversation_id}").status_code, 200
        )

        self.assertEqual(
            self.client.delete(f"/api/conversations/{conversation_id}/messages").status_code,
            200,
        )
        self.assertEqual(
            self.client.get(f"/api/conversations/{conversation_id}").json()["messages"], []
        )

        self.assertEqual(
            self.client.delete(f"/api/conversations/{conversation_id}").status_code, 200
        )
        self.assertEqual(
            self.client.get(f"/api/conversations/{conversation_id}").status_code, 404
        )

    def test_failed_message_does_not_pollute_history(self) -> None:
        conversation_id = self.client.post("/api/conversations").json()["id"]
        ai_service._client = None
        self.client.post("/api/chat", json={"conversation_id": conversation_id, "message": "Oops"})
        detail = self.client.get(f"/api/conversations/{conversation_id}").json()
        self.assertEqual(detail["messages"], [])
        self.assertEqual(detail["conversation"]["title"], "New conversation")

    # -------------------- Secret hygiene --------------------

    def test_no_secrets_in_frontend_or_gitignore(self) -> None:
        frontend = ""
        for name in ("index.html", "style.css", "script.js"):
            frontend += (PROJECT_ROOT / "frontend" / name).read_text()
        for secret_token in ("api_key", "sk-", "OPENAI_API_KEY"):
            self.assertNotIn(secret_token, frontend)
        gitignore = (PROJECT_ROOT / ".gitignore").read_text()
        self.assertIn(".env", gitignore)
        self.assertIn("*.db", gitignore)


if __name__ == "__main__":
    unittest.main()
