from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ..config import codex_home
from ..models import Conversation, Message

MAX_TOOL_CALL_CHARS = 50_000
MAX_TOOL_RESULT_CHARS = 100_000


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return (
        value[:limit]
        + "\n\n[工具输出已截断；完整原始记录保留在 Codex 会话 JSONL 中]"
    )


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (_as_text(item) for item in value)))
    if isinstance(value, dict):
        for key in ("text", "content", "output"):
            if key in value:
                return _as_text(value[key])
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return _as_text(content)
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        item_type = item.get("type", "")
        if item_type in {
            "input_text",
            "output_text",
            "text",
            "summary_text",
            "code",
            "input_image",
        }:
            text = _as_text(item.get("text") or item.get("content"))
            if item_type == "input_image" and not text:
                text = "[图片附件]"
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def load_thread_names(codex_root: Path) -> dict[str, str]:
    index_path = codex_root / "session_index.jsonl"
    result: dict[str, str] = {}
    if not index_path.exists():
        return result
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        identifier = item.get("id")
        title = item.get("thread_name")
        if identifier and title:
            result[str(identifier)] = str(title)
    return result


def discover_session_files(codex_root: Path | None = None) -> list[Path]:
    root = codex_root or codex_home()
    directories = [
        root / "sessions",
        root / "sessions-archive",
        root / "archived_sessions",
    ]
    files: list[Path] = []
    for directory in directories:
        if directory.exists():
            files.extend(directory.rglob("*.jsonl"))
    return sorted(set(files), key=lambda item: item.stat().st_mtime)


def parse_session_file(
    path: Path,
    title_map: dict[str, str] | None = None,
    tool_call_limit: int = MAX_TOOL_CALL_CHARS,
    tool_result_limit: int = MAX_TOOL_RESULT_CHARS,
) -> Conversation | None:
    title_map = title_map or {}
    session_id: str | None = None
    created_at: str | None = None
    source_ref = str(path)
    model: str | None = None
    messages: list[Message] = []
    last_timestamp: str | None = None
    current_cwd: str | None = None

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        timestamp = item.get("timestamp")
        if timestamp:
            last_timestamp = timestamp
        item_type = item.get("type")
        payload = item.get("payload") or {}

        if item_type == "session_meta":
            session_id = str(
                payload.get("session_id")
                or payload.get("id")
                or session_id
                or ""
            )
            created_at = payload.get("timestamp") or created_at or timestamp
            current_cwd = payload.get("cwd") or current_cwd
            continue

        if item_type == "turn_context":
            model = payload.get("model") or model
            current_cwd = payload.get("cwd") or current_cwd
            continue

        if item_type != "response_item":
            continue

        payload_type = payload.get("type")
        role = payload.get("role")
        if payload_type == "message" and role in {"user", "assistant"}:
            text = _message_text(payload.get("content"))
            if role == "user" and not _is_real_user_message(item, payload):
                continue
            if text.strip():
                messages.append(
                    Message(
                        role=role,
                        timestamp=timestamp,
                        kind="message",
                        text=text,
                        metadata={},
                    )
                )
            continue

        if payload_type in {"function_call", "custom_tool_call"}:
            name = payload.get("name") or "tool"
            arguments = payload.get("arguments", payload.get("input", ""))
            text = f"[工具调用] {name}\n{_clip(_as_text(arguments), tool_call_limit)}".strip()
            messages.append(
                Message(
                    role="tool",
                    timestamp=timestamp,
                    kind="tool_call",
                    text=text,
                    metadata={
                        "call_id": payload.get("call_id"),
                        "name": name,
                    },
                )
            )
            continue

        if payload_type in {"function_call_output", "custom_tool_call_output"}:
            output = _clip(_as_text(payload.get("output")), tool_result_limit)
            messages.append(
                Message(
                    role="tool",
                    timestamp=timestamp,
                    kind="tool_result",
                    text=f"[工具结果]\n{output}".strip(),
                    metadata={"call_id": payload.get("call_id")},
                )
            )

    if not session_id:
        stem = path.stem
        session_id = stem.rsplit("-", 5)[-5:]
    if not messages:
        return None

    first_user = next(
        (message.text.strip().splitlines()[0] for message in messages if message.role == "user"),
        "未命名 Codex 会话",
    )
    title = title_map.get(session_id) or first_user[:80]
    return Conversation(
        id=f"codex:{session_id}",
        provider="codex",
        model=model,
        title=title,
        created_at=created_at,
        updated_at=last_timestamp,
        source_ref=f"codex-session://{session_id}",
        source_type="codex_local",
        messages=messages,
    ).ordered()


def _is_real_user_message(item: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Exclude harness-injected instructions and guardian review transcripts."""
    metadata = item.get("metadata") or {}
    if metadata.get("guardian_sources"):
        return False
    passthrough = payload.get("internal_chat_message_metadata_passthrough") or {}
    kinds = passthrough.get("content_item_kinds") or []
    synthetic_prefixes = (
        "agents_md.",
        "environments.",
        "system.",
        "developer.",
    )
    if any(str(kind).startswith(synthetic_prefixes) for kind in kinds):
        return False
    item_metadata = passthrough.get("content_item_metadata") or []
    provenance_types = {
        ((entry or {}).get("provenance") or {}).get("type")
        for entry in item_metadata
        if isinstance(entry, dict)
    }
    return "user" in provenance_types


def discover_conversations(
    codex_root: Path | None = None,
) -> Iterable[Conversation]:
    root = codex_root or codex_home()
    title_map = load_thread_names(root)
    latest_by_id: dict[str, Conversation] = {}
    for file in discover_session_files(root):
        conversation = parse_session_file(file, title_map)
        if conversation is None:
            continue
        existing = latest_by_id.get(conversation.id)
        if existing is None or (conversation.updated_at or "") >= (existing.updated_at or ""):
            latest_by_id[conversation.id] = conversation
    return latest_by_id.values()
