from __future__ import annotations

from pathlib import Path

from ai_context_hub.db import upsert_conversation
from ai_context_hub.exporter import export_all
from ai_context_hub.models import Conversation, Message
from ai_context_hub.packs import build_pack, count_tokens


def _seed() -> None:
    upsert_conversation(
        Conversation(
            id="codex:pack-1",
            provider="codex",
            model="gpt-test",
            title="登录实现",
            source_ref="codex-session://pack-1",
            source_type="codex_local",
            messages=[
                Message(role="user", timestamp=None, text="实现登录"),
                Message(role="assistant", text="已完成。\n```python\nprint('ok')\n```"),
                Message(role="tool", kind="tool_result", text="2 passed"),
            ],
        )
    )
    upsert_conversation(
        Conversation(
            id="deepseek:pack-2",
            provider="deepseek",
            model="deepseek-test",
            title="登录方案",
            source_ref="https://chat.deepseek.com/a/chat/s/pack-2",
            source_type="browser_snapshot",
            messages=[
                Message(role="user", text="比较两种登录方案"),
                Message(role="assistant", text="建议使用短期令牌与刷新令牌。"),
            ],
        )
    )


def test_pack_has_conversation_level_sources_and_budget(hub_home) -> None:
    _seed()
    result = build_pack(
        conversation_ids=["codex:pack-1", "deepseek:pack-2"],
        budget=2000,
        mode="working",
    )

    assert result["status"] == "ok"
    path = Path(hub_home) / result["path"]
    content = path.read_text(encoding="utf-8")
    assert 'source="Codex"' in content
    assert 'source="DeepSeek"' in content
    assert "多个 AI 系统的聊天记录" in content
    assert count_tokens(content) <= 2000


def test_export_writes_sanitized_files(hub_home) -> None:
    _seed()
    result = export_all()

    assert result["status"] == "ok"
    manifest = Path(hub_home) / "exports" / "manifest.json"
    assert manifest.exists()
    files = list((Path(hub_home) / "exports" / "conversations").rglob("*.md"))
    assert len(files) == 2
    assert "来源：Codex" in files[0].read_text(encoding="utf-8")
