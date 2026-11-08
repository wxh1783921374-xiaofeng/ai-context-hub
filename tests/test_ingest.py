from __future__ import annotations

from ai_context_hub.db import get_conversation, upsert_conversation
from ai_context_hub.ingest import ingest_browser_capture
from ai_context_hub.models import BrowserCapture, Conversation, Message


def test_browser_partial_snapshot_does_not_drop_existing_tail(hub_home) -> None:
    first = BrowserCapture(
        provider="gemini",
        conversation_id="abc123",
        title="测试会话",
        url="https://gemini.google.com/app/abc123",
        captured_at="2026-01-01T00:00:03+00:00",
        complete=True,
        messages=[
            Message(role="user", text="问题一"),
            Message(role="assistant", text="回答一"),
        ],
    )
    ingest_browser_capture(first)

    partial = first.model_copy(deep=True)
    partial.complete = False
    partial.captured_at = "2026-01-01T00:00:04+00:00"
    partial.messages = [Message(role="user", text="问题一")]
    ingest_browser_capture(partial)

    stored = get_conversation("gemini:abc123")
    assert stored is not None
    assert [item.text for item in stored.messages] == ["问题一", "回答一"]


def test_upsert_is_idempotent(hub_home) -> None:
    conversation = Conversation(
        id="generic:one",
        provider="generic",
        title="幂等",
        source_type="generic_import",
        messages=[Message(role="user", text="只写一次")],
    )
    assert upsert_conversation(conversation) == "new"
    assert upsert_conversation(conversation) == "unchanged"
