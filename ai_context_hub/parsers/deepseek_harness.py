from __future__ import annotations

import json
import io
from pathlib import Path
from typing import Any, Iterable

import zstandard as zstd

from ..config import iso_from_epoch
from ..models import Conversation, Message


MAX_TOOL_CHARS = 100_000


def _clip(value: str, limit: int = MAX_TOOL_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n\n[工具记录已截断；原始记录仍在 DeepSeek Harness 会话中]"


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
            parts.append(str(item["text"]))
    return "\n\n".join(parts).strip()


def _title_map(dsh_root: Path) -> dict[str, str]:
    root = dsh_root / "storages" / "session_projcache" / "sessions"
    result: dict[str, str] = {}
    if not root.exists():
        return result
    for path in root.glob("session-*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        record = payload.get("record") or {}
        identity = record.get("identity") or {}
        title = ((record.get("rows") or {}).get("title") or {}).get("val")
        session_id = path.stem
        if title:
            result[session_id] = str(title)
        created = identity.get("createdAt")
        if created and session_id not in result:
            result[session_id] = f"DeepSeek Harness {session_id[-8:]}"
    return result


def _session_files(dsh_root: Path) -> list[Path]:
    root = dsh_root / "sessions"
    if not root.exists():
        return []
    return sorted(root.rglob("session.v4.jsonl.zstd"))


def parse_session(path: Path, fallback_title: str | None = None) -> Conversation | None:
    messages: list[Message] = []
    session_id = path.parent.name
    created_at: str | None = None
    updated_at: str | None = None
    model: str | None = None
    title: str | None = None

    try:
        with path.open("rb") as raw:
            decompressor = zstd.ZstdDecompressor()
            with decompressor.stream_reader(raw) as stream:
                with io.TextIOWrapper(stream, encoding="utf-8") as text_stream:
                    for raw_line in text_stream:
                        try:
                            event = json.loads(raw_line)
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            continue
                        event_time = event.get("time")
                        if event.get("type") == "session":
                            session_id = str(event.get("id") or session_id)
                            created_at = iso_from_epoch(
                                (event.get("createdAt") or event_time or 0) / 1000
                            )
                        if event_time:
                            updated_at = iso_from_epoch(event_time / 1000)
                        event_type = event.get("type")
                        data = event.get("data") or {}
                        if event_type == "request/context":
                            model = data.get("model") or model
                        elif event_type == "session/title":
                            title = data.get("title") or title
                        elif event_type == "user/message":
                            text = _content_text(data.get("content"))
                            if text:
                                messages.append(
                                    Message(
                                        role="user",
                                        timestamp=iso_from_epoch(
                                            event_time / 1000 if event_time else None
                                        ),
                                        kind="message",
                                        text=text,
                                    )
                                )
                        elif event_type == "assistant/message":
                            message = data.get("message") or {}
                            text = _content_text(message.get("content"))
                            if text:
                                messages.append(
                                    Message(
                                        role="assistant",
                                        timestamp=iso_from_epoch(
                                            event_time / 1000 if event_time else None
                                        ),
                                        kind="message",
                                        text=text,
                                    )
                                )
                        elif event_type == "tool/call":
                            name = data.get("name") or "tool"
                            arguments = data.get("arguments") or ""
                            messages.append(
                                Message(
                                    role="tool",
                                    timestamp=iso_from_epoch(
                                        event_time / 1000 if event_time else None
                                    ),
                                    kind="tool_call",
                                    text=_clip(f"[工具调用] {name}\n{arguments}"),
                                )
                            )
                        elif event_type == "tool/result":
                            text = _content_text(
                                (data.get("message") or {}).get("content")
                            )
                            if text:
                                messages.append(
                                    Message(
                                        role="tool",
                                        timestamp=iso_from_epoch(
                                            event_time / 1000 if event_time else None
                                        ),
                                        kind="tool_result",
                                        text=_clip(text),
                                    )
                                )
    except (OSError, zstd.ZstdError):
        return None

    if not any(message.role == "user" for message in messages):
        return None
    first_user = next(
        (message.text.strip().splitlines()[0] for message in messages if message.role == "user"),
        "",
    )
    title = title or fallback_title or first_user[:100] or "DeepSeek Harness 会话"
    return Conversation(
        id=f"deepseek_harness:{session_id}",
        provider="deepseek_harness",
        model=model,
        title=title,
        created_at=created_at,
        updated_at=updated_at or created_at,
        source_ref=f"dsh-session://{session_id}",
        source_type="deepseek_harness_local",
        messages=messages,
    ).ordered()


def discover_conversations(dsh_root: Path) -> Iterable[Conversation]:
    titles = _title_map(dsh_root)
    for path in _session_files(dsh_root):
        session_id = path.parent.name
        conversation = parse_session(path, titles.get(session_id))
        if conversation:
            yield conversation
