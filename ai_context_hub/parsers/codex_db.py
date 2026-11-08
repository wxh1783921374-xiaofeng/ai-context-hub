from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from ..config import codex_home, iso_from_epoch
from ..models import Conversation, Message


MAX_TOOL_CHARS = 100_000


def _clip(value: str, limit: int = MAX_TOOL_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n\n[工具记录已截断；原始记录仍在 Codex 数据库中]"


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            if item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]))
            elif item.get("type") == "image":
                parts.append("[图片附件]")
    return "\n\n".join(parts).strip()


def _command_text(item: dict[str, Any]) -> str:
    command = str(item.get("command") or "")
    output = str(item.get("aggregatedOutput") or "")
    status = item.get("status")
    exit_code = item.get("exitCode")
    lines = [f"[命令] {command}"]
    if status:
        lines.append(f"[状态] {status}")
    if exit_code is not None:
        lines.append(f"[退出码] {exit_code}")
    if output:
        lines.extend(["[输出]", output])
    return _clip("\n".join(lines))


def _file_change_text(item: dict[str, Any]) -> str:
    blocks: list[str] = []
    for change in item.get("changes") or []:
        path = str(change.get("path") or "")
        diff = str(change.get("diff") or "")
        kind = change.get("kind") or {}
        blocks.append(f"[文件: {path}] {kind}\n{diff}")
    return _clip("\n\n".join(blocks))


def _mcp_text(item: dict[str, Any]) -> str:
    result = item.get("result")
    if isinstance(result, dict):
        result = _content_text(result.get("content")) or json.dumps(
            result,
            ensure_ascii=False,
        )
    lines = [
        f"[MCP] {item.get('server', '')}/{item.get('tool', '')}",
        f"[参数] {json.dumps(item.get('arguments') or {}, ensure_ascii=False)}",
    ]
    if item.get("error"):
        lines.append(f"[错误] {item['error']}")
    elif result:
        lines.extend(["[结果]", str(result)])
    return _clip("\n".join(lines))


def _convert_item(row: sqlite3.Row) -> Message | None:
    try:
        payload = json.loads(row["item_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    item_type = row["item_type"]
    timestamp = iso_from_epoch(int(row["created_at_ms"]) / 1000)
    if item_type == "userMessage":
        text = _content_text(payload.get("content"))
        if text:
            return Message(
                role="user",
                timestamp=timestamp,
                kind="message",
                text=text,
            )
    elif item_type == "agentMessage":
        text = str(payload.get("text") or "").strip()
        if text:
            return Message(
                role="assistant",
                timestamp=timestamp,
                kind="message",
                text=text,
                metadata={"phase": payload.get("phase")},
            )
    elif item_type == "plan":
        text = str(payload.get("text") or "").strip()
        if text:
            return Message(
                role="assistant",
                timestamp=timestamp,
                kind="plan",
                text=text,
            )
    elif item_type == "commandExecution":
        return Message(
            role="tool",
            timestamp=timestamp,
            kind="tool_result",
            text=_command_text(payload),
        )
    elif item_type == "fileChange":
        return Message(
            role="tool",
            timestamp=timestamp,
            kind="file_change",
            text=_file_change_text(payload),
        )
    elif item_type == "mcpToolCall":
        return Message(
            role="tool",
            timestamp=timestamp,
            kind="tool_result",
            text=_mcp_text(payload),
        )
    elif item_type == "imageView":
        return Message(
            role="tool",
            timestamp=timestamp,
            kind="tool_result",
            text=f"[查看图片] {payload.get('path', '')}",
        )
    return None


def discover_thread_conversations(
    codex_root: Path | None = None,
) -> Iterable[Conversation]:
    root = codex_root or codex_home()
    state_path = root / "state_5.sqlite"
    history_path = root / "thread_history_1.sqlite"
    if not state_path.exists() or not history_path.exists():
        return []

    state = sqlite3.connect(f"file:{state_path.as_posix()}?mode=ro", uri=True)
    history = sqlite3.connect(f"file:{history_path.as_posix()}?mode=ro", uri=True)
    state.row_factory = sqlite3.Row
    history.row_factory = sqlite3.Row
    conversations: list[Conversation] = []
    try:
        threads = state.execute(
            """
            SELECT id, title, name, created_at, updated_at, model, cwd,
                   source, thread_source
            FROM threads
            WHERE thread_source = 'user'
            ORDER BY updated_at ASC
            """
        ).fetchall()
        for thread in threads:
            rows = history.execute(
                """
                SELECT item_type, item_json, created_at_ms
                FROM thread_items
                WHERE thread_id = ?
                ORDER BY rollout_ordinal, created_at_ms
                """,
                (thread["id"],),
            ).fetchall()
            messages = [
                message
                for row in rows
                if (message := _convert_item(row)) is not None
            ]
            if not any(message.role == "user" for message in messages):
                continue
            first_user = next(
                (message.text.strip().splitlines()[0] for message in messages if message.role == "user"),
                "",
            )
            title = thread["name"] or thread["title"] or first_user[:100] or "Codex 会话"
            conversations.append(
                Conversation(
                    id=f"codex:{thread['id']}",
                    provider="codex",
                    model=thread["model"],
                    title=title,
                    created_at=iso_from_epoch(thread["created_at"]),
                    updated_at=iso_from_epoch(thread["updated_at"]),
                    source_ref=f"codex-thread://{thread['id']}",
                    source_type="codex_sqlite",
                    messages=messages,
                ).ordered()
            )
    finally:
        state.close()
        history.close()
    return conversations
