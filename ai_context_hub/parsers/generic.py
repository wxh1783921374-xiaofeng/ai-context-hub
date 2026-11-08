from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from ..models import Conversation, Message


ROLE_HEADING = re.compile(
    r"^\s{0,3}(?:#{2,4}\s*)?(User|用户|Human|Assistant|助手|AI|Model|DeepSeek|ChatGPT|Gemini|豆包)\s*[:：]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _role_from_heading(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"user", "用户", "human"}:
        return "user"
    return "assistant"


def parse_markdown(path: Path) -> Conversation:
    text = path.read_text(encoding="utf-8")
    title = path.stem
    provider = "generic"
    matches = list(ROLE_HEADING.finditer(text))
    messages: list[Message] = []
    if matches:
        prefix = text[: matches[0].start()].strip()
        for line in prefix.splitlines():
            if line.startswith("# "):
                title = line[2:].strip() or title
                break
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[match.end() : end].strip()
            if body:
                messages.append(
                    Message(
                        role=_role_from_heading(match.group(1)),
                        kind="message",
                        text=body,
                    )
                )
    if not messages:
        messages = [Message(role="assistant", kind="message", text=text.strip())]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Conversation(
        id=f"generic:{digest[:16]}",
        provider=provider,
        title=title,
        source_ref=f"file://{path.resolve()}",
        source_type="generic_import",
        messages=messages,
    ).ordered()


def parse_json_file(path: Path) -> Iterable[Conversation]:
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data if isinstance(data, list) else [data]
    for record in records:
        if not isinstance(record, dict):
            continue
        if "mapping" in record and isinstance(record["mapping"], dict):
            from .chatgpt import parse_conversation

            parsed = parse_conversation(record)
            if parsed:
                yield parsed
            continue
        messages_data = record.get("messages")
        if not isinstance(messages_data, list):
            continue
        identifier = str(record.get("id") or "")
        if not identifier:
            encoded = json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
            identifier = hashlib.sha256(encoded).hexdigest()[:16]
        provider = str(record.get("provider") or "generic").lower()
        messages = [
            Message.model_validate(
                {
                    "role": item.get("role", "assistant"),
                    "kind": item.get("kind", "message"),
                    "text": str(item.get("text", "")),
                    "timestamp": item.get("timestamp"),
                    "metadata": item.get("metadata") or {},
                }
            )
            for item in messages_data
            if isinstance(item, dict) and str(item.get("text", "")).strip()
        ]
        if not messages:
            continue
        yield Conversation(
            id=f"{provider}:{identifier}",
            provider=provider,
            model=record.get("model"),
            title=record.get("title") or path.stem,
            created_at=record.get("created_at"),
            updated_at=record.get("updated_at"),
            source_ref=record.get("source_ref") or f"file://{path.resolve()}",
            source_type="generic_import",
            messages=messages,
        ).ordered()


def import_generic(path: Path) -> Iterable[Conversation]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        yield from parse_json_file(path)
    elif suffix in {".md", ".markdown", ".txt"}:
        yield parse_markdown(path)
    else:
        raise ValueError("通用导入仅支持 .json、.md、.markdown 和 .txt")
