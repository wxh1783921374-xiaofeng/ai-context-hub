from __future__ import annotations

from fastapi.testclient import TestClient

from ai_context_hub.api import app
from ai_context_hub.config import local_token
from ai_context_hub.db import upsert_conversation
from ai_context_hub.models import Conversation, Message


def test_capture_requires_token_and_accepts_snapshot(hub_home) -> None:
    client = TestClient(app)
    payload = {
        "provider": "doubao",
        "conversation_id": "api-test",
        "title": "API 测试",
        "url": "https://www.doubao.com/chat/api-test",
        "model": "doubao-test",
        "captured_at": "2026-01-01T00:00:00Z",
        "complete": True,
        "messages": [
            {"role": "user", "text": "你好"},
            {"role": "assistant", "text": "你好，有什么可以帮你？"},
        ],
        "snapshot_hash": "abc",
    }

    unauthorized = client.post("/api/v1/capture", json=payload)
    assert unauthorized.status_code == 401

    authorized = client.post(
        "/api/v1/capture",
        json=payload,
        headers={"X-AI-Context-Token": local_token()},
    )
    assert authorized.status_code == 200
    assert authorized.json()["conversation_id"] == "doubao:api-test"


def test_status_and_conversation_endpoints(hub_home) -> None:
    upsert_conversation(
        Conversation(
            id="gemini:read-one",
            provider="gemini",
            title="读取测试",
            source_type="browser_snapshot",
            messages=[Message(role="user", text="搜索唯一词 zebra")],
        )
    )
    client = TestClient(app)

    status = client.get("/api/v1/status")
    search = client.get("/api/v1/conversations", params={"q": "zebra"})
    detail = client.get("/api/v1/conversations/gemini:read-one")

    assert status.status_code == 200
    assert status.json()["counts"]["all"] == 1
    assert search.json()["count"] == 1
    assert detail.json()["title"] == "读取测试"
