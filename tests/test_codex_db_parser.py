from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ai_context_hub.parsers.codex_db import discover_thread_conversations


def test_codex_database_includes_user_threads_and_skips_guardian(tmp_path: Path) -> None:
    state_path = tmp_path / "state_5.sqlite"
    history_path = tmp_path / "thread_history_1.sqlite"
    state = sqlite3.connect(state_path)
    state.execute(
        """
        CREATE TABLE threads (
            id TEXT PRIMARY KEY, title TEXT, name TEXT, created_at INTEGER,
            updated_at INTEGER, model TEXT, cwd TEXT, source TEXT,
            thread_source TEXT
        )
        """
    )
    state.executemany(
        "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "thread-user",
                "原始标题",
                "用户线程",
                1700000000,
                1700000010,
                "gpt-test",
                r"C:\work",
                "vscode",
                "user",
            ),
            (
                "thread-guardian",
                "Guardian review",
                "Guardian review",
                1700000000,
                1700000010,
                "gpt-test",
                r"C:\work",
                "guardian",
                "guardian_review",
            ),
        ],
    )
    state.commit()
    state.close()

    history = sqlite3.connect(history_path)
    history.execute(
        """
        CREATE TABLE thread_items (
            thread_id TEXT, turn_id TEXT, item_id TEXT, rollout_ordinal INTEGER,
            created_at_ms INTEGER, item_json TEXT, item_type TEXT
        )
        """
    )
    items = [
        (
            "thread-user",
            "turn-1",
            "u1",
            1,
            1700000001_000,
            json.dumps(
                {
                    "type": "userMessage",
                    "content": [{"type": "text", "text": "真实问题"}],
                },
                ensure_ascii=False,
            ),
            "userMessage",
        ),
        (
            "thread-user",
            "turn-1",
            "r1",
            2,
            1700000002_000,
            json.dumps({"type": "reasoning", "content": ["隐藏推理"]}, ensure_ascii=False),
            "reasoning",
        ),
        (
            "thread-user",
            "turn-1",
            "a1",
            3,
            1700000003_000,
            json.dumps(
                {"type": "agentMessage", "text": "真实回答", "phase": "final_answer"},
                ensure_ascii=False,
            ),
            "agentMessage",
        ),
        (
            "thread-guardian",
            "turn-2",
            "u2",
            1,
            1700000004_000,
            json.dumps(
                {
                    "type": "userMessage",
                    "content": [{"type": "text", "text": "Guardian"}],
                },
                ensure_ascii=False,
            ),
            "userMessage",
        ),
    ]
    history.executemany(
        """
        INSERT INTO thread_items(
            thread_id, turn_id, item_id, rollout_ordinal,
            created_at_ms, item_json, item_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        items,
    )
    history.commit()
    history.close()

    conversations = list(discover_thread_conversations(tmp_path))

    assert len(conversations) == 1
    conversation = conversations[0]
    assert conversation.id == "codex:thread-user"
    assert conversation.title == "用户线程"
    assert [message.text for message in conversation.messages] == ["真实问题", "真实回答"]
