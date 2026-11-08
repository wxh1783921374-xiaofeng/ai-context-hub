from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, Iterable

from ..config import iso_from_epoch
from ..models import Conversation, Message


def _parts_text(content: dict[str, Any]) -> str:
    content_type = content.get("content_type") or ""
    parts = content.get("parts")
    if parts is None and "text" in content:
        parts = [content.get("text")]
    if parts is None and content_type == "code":
        parts = [content.get("text", "")]
    rendered: list[str] = []
    for part in parts or []:
        if isinstance(part, str):
            rendered.append(part)
        elif isinstance(part, dict):
            for key in ("text", "content"):
                if part.get(key):
                    rendered.append(str(part[key]))
                    break
            else:
                asset = part.get("asset_pointer")
                if asset:
                    rendered.append(f"[附件: {asset}]")
    return "\n\n".join(item for item in rendered if item.strip())


def _active_path(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = conversation.get("mapping") or {}
    current = conversation.get("current_node")
    path: list[dict[str, Any]] = []
    visited: set[str] = set()
    while current and current in mapping and current not in visited:
        visited.add(current)
        node = mapping[current]
        path.append(node)
        current = node.get("parent")
    path.reverse()
    return path


def _fallback_path(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = conversation.get("mapping") or {}
    nodes = [item for item in mapping.values() if item.get("message")]
    return sorted(
        nodes,
        key=lambda item: (
            ((item.get("message") or {}).get("create_time") or 0),
            str(item.get("id") or ""),
        ),
    )


def parse_conversation(payload: dict[str, Any]) -> Conversation | None:
    nodes = _active_path(payload) or _fallback_path(payload)
    messages: list[Message] = []
    model: str | None = None
    for node in nodes:
        message = node.get("message") or {}
        author = message.get("author") or {}
        role = author.get("role")
        if role not in {"user", "assistant", "tool"}:
            continue
        text = _parts_text(message.get("content") or {})
        if not text.strip():
            continue
        metadata = message.get("metadata") or {}
        model = metadata.get("model_slug") or metadata.get("model") or model
        messages.append(
            Message(
                role="tool" if role == "tool" else role,
                timestamp=iso_from_epoch(message.get("create_time")),
                kind="message" if role != "tool" else "tool_result",
                text=text,
                metadata={"node_id": node.get("id")},
            )
        )
    if not messages:
        return None
    identifier = str(payload.get("id") or payload.get("conversation_id") or "")
    if not identifier:
        return None
    title = payload.get("title") or "未命名 ChatGPT 会话"
    return Conversation(
        id=f"chatgpt:{identifier}",
        provider="chatgpt",
        model=model,
        title=title,
        created_at=iso_from_epoch(payload.get("create_time")),
        updated_at=iso_from_epoch(payload.get("update_time")),
        source_ref=f"chatgpt://conversation/{identifier}",
        source_type="chatgpt_export",
        messages=messages,
    ).ordered()


def _load_conversations_json(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        candidate = path / "conversations.json"
        if not candidate.exists():
            candidates = list(path.rglob("conversations.json"))
            if not candidates:
                raise ValueError("目录中没有 conversations.json")
            candidate = candidates[0]
        data = json.loads(candidate.read_text(encoding="utf-8"))
    elif path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            candidates = [
                name for name in archive.namelist() if name.endswith("conversations.json")
            ]
            if not candidates:
                raise ValueError("ZIP 中没有 conversations.json")
            data = json.loads(archive.read(candidates[0]).decode("utf-8"))
    elif path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError("ChatGPT 导入仅支持 ZIP、目录或 conversations.json")

    if isinstance(data, dict) and isinstance(data.get("conversations"), list):
        return data["conversations"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "mapping" in data:
        return [data]
    raise ValueError("无法识别的 ChatGPT conversations.json 结构")


def import_chatgpt_export(
    path: Path,
    raw_dir: Path | None = None,
) -> Iterable[Conversation]:
    records = _load_conversations_json(path)
    if raw_dir and path.is_file():
        raw_dir.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".zip":
            target = raw_dir / f"chatgpt-{path.stat().st_size}-{path.name}"
            if not target.exists():
                shutil.copy2(path, target)
    for record in records:
        conversation = parse_conversation(record)
        if conversation:
            yield conversation
