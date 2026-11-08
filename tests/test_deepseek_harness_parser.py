from __future__ import annotations

import json
from pathlib import Path

import zstandard as zstd

from ai_context_hub.parsers.deepseek_harness import discover_conversations


def test_reads_compressed_deepseek_harness_session(tmp_path: Path) -> None:
    session_id = "session-11111111-2222-3333-4444-555555555555"
    session_dir = (
        tmp_path
        / "sessions"
        / "project"
        / session_id
    )
    session_dir.mkdir(parents=True)
    events = [
        {
            "type": "session",
            "version": 4,
            "id": session_id,
            "createdAt": 1700000000000,
            "cwd": r"C:\work",
        },
        {
            "type": "request/context",
            "time": 1700000001000,
            "data": {"model": "deepseek-test"},
        },
        {
            "type": "user/message",
            "time": 1700000002000,
            "data": {
                "role": "user",
                "content": [{"type": "text", "text": "Harness 问题"}],
            },
        },
        {
            "type": "assistant/message",
            "time": 1700000003000,
            "data": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "reasoning", "text": "隐藏推理"},
                        {"type": "text", "text": "Harness 回答"},
                    ],
                }
            },
        },
        {
            "type": "tool/call",
            "time": 1700000004000,
            "data": {"name": "read", "arguments": '{"path":"README.md"}'},
        },
        {
            "type": "tool/result",
            "time": 1700000005000,
            "data": {
                "message": {
                    "role": "tool",
                    "content": [{"type": "text", "text": "文件内容"}],
                }
            },
        },
    ]
    payload = "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"
    with (session_dir / "session.v4.jsonl.zstd").open("wb") as output:
        output.write(zstd.ZstdCompressor().compress(payload.encode("utf-8")))

    cache_dir = tmp_path / "storages" / "session_projcache" / "sessions"
    cache_dir.mkdir(parents=True)
    (cache_dir / f"{session_id}.json").write_text(
        json.dumps(
            {
                "version": "7",
                "record": {
                    "identity": {"createdAt": "1700000000000"},
                    "rows": {"title": {"val": "Harness 测试"}},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    conversations = list(discover_conversations(tmp_path))

    assert len(conversations) == 1
    conversation = conversations[0]
    assert conversation.id == f"deepseek_harness:{session_id}"
    assert conversation.title == "Harness 测试"
    assert conversation.model == "deepseek-test"
    assert [message.role for message in conversation.messages] == [
        "user",
        "assistant",
        "tool",
        "tool",
    ]
    assert all("隐藏推理" not in message.text for message in conversation.messages)
