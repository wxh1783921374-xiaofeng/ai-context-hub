from __future__ import annotations

import json
from pathlib import Path

from ai_context_hub.parsers.codex import parse_session_file


def _line(payload: dict, item_type: str, timestamp: str, metadata: dict | None = None) -> str:
    return json.dumps(
        {
            "timestamp": timestamp,
            "ordinal": 1,
            "type": item_type,
            "payload": payload,
            **({"metadata": metadata} if metadata is not None else {}),
        },
        ensure_ascii=False,
    )


def test_codex_parser_keeps_real_messages_and_tools(tmp_path: Path) -> None:
    path = tmp_path / "rollout-test.jsonl"
    session_id = "11111111-2222-3333-4444-555555555555"
    records = [
        _line(
            {
                "session_id": session_id,
                "id": session_id,
                "timestamp": "2026-01-01T00:00:00Z",
                "cwd": r"C:\work",
                "model_provider": "openai",
            },
            "session_meta",
            "2026-01-01T00:00:00Z",
        ),
        _line(
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "# AGENTS.md instructions"}],
                "internal_chat_message_metadata_passthrough": {
                    "content_item_kinds": ["agents_md.instructions"],
                    "content_item_metadata": [{"provenance": {"type": "agents_md"}}],
                },
            },
            "response_item",
            "2026-01-01T00:00:01Z",
            {},
        ),
        _line(
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "请检查登录功能"}],
                "internal_chat_message_metadata_passthrough": {
                    "content_item_kinds": ["user.text"],
                    "content_item_metadata": [{"provenance": {"type": "user"}}],
                },
            },
            "response_item",
            "2026-01-01T00:00:02Z",
            {"retained_source": {"complete": True}},
        ),
        _line(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "我先读取相关文件。"}],
            },
            "response_item",
            "2026-01-01T00:00:03Z",
            {},
        ),
        _line(
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "隐藏推理"}],
            },
            "response_item",
            "2026-01-01T00:00:04Z",
            {},
        ),
        _line(
            {
                "type": "function_call",
                "name": "exec_command",
                "arguments": '{"cmd":"pytest"}',
                "call_id": "call-1",
            },
            "response_item",
            "2026-01-01T00:00:05Z",
            {},
        ),
        _line(
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "2 passed",
            },
            "response_item",
            "2026-01-01T00:00:06Z",
            {},
        ),
        _line(
            {
                "type": "turn_context",
                "model": "gpt-test",
                "cwd": r"C:\work",
            },
            "turn_context",
            "2026-01-01T00:00:07Z",
        ),
    ]
    path.write_text("\n".join(records) + "\n", encoding="utf-8")

    conversation = parse_session_file(path, {session_id: "登录检查"})

    assert conversation is not None
    assert conversation.id == f"codex:{session_id}"
    assert conversation.title == "登录检查"
    assert conversation.model == "gpt-test"
    assert [message.role for message in conversation.messages] == [
        "user",
        "assistant",
        "tool",
        "tool",
    ]
    assert all("AGENTS.md instructions" not in item.text for item in conversation.messages)
    assert all("隐藏推理" not in item.text for item in conversation.messages)
    assert "pytest" in conversation.messages[2].text


def test_codex_parser_skips_guardian_review(tmp_path: Path) -> None:
    path = tmp_path / "rollout-guardian.jsonl"
    session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    records = [
        _line(
            {"session_id": session_id, "id": session_id, "timestamp": "2026-01-01T00:00:00Z"},
            "session_meta",
            "2026-01-01T00:00:00Z",
        ),
        _line(
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "The following is the Codex agent history",
                    }
                ],
                "internal_chat_message_metadata_passthrough": {
                    "content_item_kinds": ["user.text"],
                    "content_item_metadata": [{"provenance": {"type": "user"}}],
                },
            },
            "response_item",
            "2026-01-01T00:00:01Z",
            {"guardian_sources": [{"id": "review"}]},
        ),
        _line(
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "真实问题"}],
                "internal_chat_message_metadata_passthrough": {
                    "content_item_kinds": ["user.text"],
                    "content_item_metadata": [{"provenance": {"type": "user"}}],
                },
            },
            "response_item",
            "2026-01-01T00:00:02Z",
            {"retained_source": {"complete": True}},
        ),
    ]
    path.write_text("\n".join(records) + "\n", encoding="utf-8")

    conversation = parse_session_file(path)

    assert conversation is not None
    assert [item.text for item in conversation.messages] == ["真实问题"]
